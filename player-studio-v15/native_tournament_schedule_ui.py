"""In-game Android Dialog/WebView host, deliberately separate from draw/matches.

No external-browser intent, no game launch and no live injection on import.
The integrator calls dispatch_saved_schedule at the native schedule action.
The original V17 GameActivity.Get() and NativeCalls.WebViewVisible(boolean)
are verified in the APK. Android UI creation still requires device validation.
"""
import logging
import copy
from collections import deque
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

LOG = logging.getLogger(__name__)
_HOST = None
_CHANNEL = None
_SERVICE = None
_WORKER = None
_STATUS_LOCK = threading.RLock()
_STATUS_EVENTS = deque(maxlen=32)
_STATUS = {'ready_reason':'service not configured','worker_tick':None,'write_error':None}
_LAST_FLUSH = 0
_EXTERNAL_STATUS_PATH = None
_EXTERNAL_STATUS_ERROR = None
REVISION = 'v17-tournament-schedule-click-v3'
DIAGNOSTIC_GATES = ('entry','ready','frame','actor','fade_flag','record_pointer','record_length',
                    'record_buffer','record_text','forward_pointer','forward_length','forward_buffer',
                    'forward_text','selected_context','selected_event','event_allowlist','class_pointer',
                    'class_name','state_property','property_offset','menu_state','pending','publish','handled')
CHANNEL_SCHEMA={'bytes':512,'ready':0,'pending':4,'sequence':8,'event_id':16,'actor':24,'acknowledged':32,
                'diagnostics':{'version':1,'version_offset':64,'last_gate':68,'last_reject':72,
                               'observed_state':76,'observed_event':80,'observed_ready':84,
                               'record_count':88,'forward_count':92,'observed_class_name':96,
                               'expected_class_name':104,'property_offset':112,'fade_flag':116,
                               'reached_offset':128,'rejected_offset':256,'capacity':32,
                               'gates':list(DIAGNOSTIC_GATES)}}

# Exact native evidence. This inventory does not install a speculative patch.
ENTRY_EVIDENCE = {
    'engine_sha256': 'efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8',
    'menu_constructor_va': 0x73AA700,
    'menu_update_va': 0x73AA770,
    'schedule_task_constructor_va': 0x7AE8CC4,
    'schedule_request': 'CMD_GET_EVENT_COMPE_TOURNAMENT_MATCH_LIST',
    'challenge_schedule_request': 'CMD_GET_EVENT_MISSION_AI_MATCH_LIST',
    'schedule_visibility_va': 0x32B9ADC,
    'native_click_callback_identified': True,
    'click_function': 'BP_MenuEvCompeEventMainMenu.CallbackTapRecord',
    'click_label': 'Any2W[436]',
    'click_dispatch': 'FlowManager.StartFadeOutFunc(false, record, forward)',
    'click_hook_va': 0x3C9408C,
    'caller_actor': 'FFrame.Object at x20 + 0x18; x0 is FlowManager',
    'required_actor_state': 3,
    'actor_state_name': 'SelectMenu; normal callback does not write MainMenuState',
    'timeout_alert_state': 6,
    'activity': 'com.epicgames.ue4.GameActivity',
    'activity_get_signature': '()Lcom/epicgames/ue4/GameActivity;',
    'visibility_class': 'com.epicgames.ue4.NativeCalls',
    'visibility_method': 'WebViewVisible',
    'visibility_signature': '(Z)V',
    'native_visibility_va': 0x286AB00,
    'external_browser_forbidden': ['jp.konami.android.common.WebBrowser.BrowserStartUp',
                                   'com.epicgames.ue4.GameActivity.AndroidThunkJava_LaunchURL'],
    'original_schedule_button_replaced_in_game': False,
    'device_validated': False,
}


def diagnostic_status():
    """Snapshot our own retained channel; never dereference engine pointers."""
    with _STATUS_LOCK:
        host = _HOST
        return {'schema_version':1,'revision':REVISION,'pid':os.getpid(),
                'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'configured':_SERVICE is not None,'channel_registered':_CHANNEL is not None,
                'external_status_path':str(_EXTERNAL_STATUS_PATH) if _EXTERNAL_STATUS_PATH else None,
                'external_status_error':_EXTERNAL_STATUS_ERROR,
                'worker_alive':bool(_WORKER and _WORKER.is_alive()),
                'worker':copy.deepcopy(_STATUS),
                'channel':_CHANNEL.snapshot() if _CHANNEL else None,
                'host':None if host is None else {'pending':host.pending,'current_url':host.current_url,
                        'dialog_show_returned':host.shown,'last_title':host.last_title,'last_error':host.last_error},
                'events':list(_STATUS_EVENTS),'game_ui_success_asserted':False}


def _external_status_path():
    """App-owned external files remain available when private adb reads fail."""
    global _EXTERNAL_STATUS_PATH,_EXTERNAL_STATUS_ERROR
    if _EXTERNAL_STATUS_PATH is not None:
        return _EXTERNAL_STATUS_PATH
    try:
        from java import jclass
        activity=jclass(ENTRY_EVIDENCE['activity']).Get()
        if activity is None:raise RuntimeError('GameActivity unavailable')
        folder=activity.getExternalFilesDir(None)
        if folder is None:raise RuntimeError('External files directory unavailable')
        _EXTERNAL_STATUS_PATH=Path(str(folder.getAbsolutePath()))/'player-studio-tournament-schedule-ui-status.json'
        _EXTERNAL_STATUS_ERROR=None
    except Exception as exc:
        _EXTERNAL_STATUS_ERROR=type(exc).__name__+': '+str(exc)
    return _EXTERNAL_STATUS_PATH


def _atomic_status(path,value):
    temporary=None
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,
                                         prefix='.tournament-schedule-',suffix='.tmp',delete=False) as output:
            temporary=Path(output.name)
            json.dump(value,output,ensure_ascii=False,indent=2)
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():
            try:temporary.unlink()
            except OSError:pass


def write_status(force=False):
    """Atomic primary/external copies; a diagnostic write cannot block the UI."""
    global _LAST_FLUSH
    with _STATUS_LOCK:
        if not force and time.monotonic()-_LAST_FLUSH<5:
            return False
        paths=[]
        if _SERVICE is not None:
            paths.append(Path(_SERVICE.root)/'outputs/efootball/tournament-schedule-ui-status.json')
        external=_external_status_path()
        if external is not None and external not in paths:paths.append(external)
        if not paths:return False
        try:
            value=diagnostic_status()
        except Exception as exc:
            LOG.warning('Tournament schedule diagnostic snapshot failed: %s',exc)
            return False
        errors={};written=0
        for path in paths:
            try:_atomic_status(path,value);written+=1
            except Exception as exc:errors[str(path)]=type(exc).__name__+': '+str(exc)
        if errors and _STATUS.get('write_error')!=errors:
            LOG.warning('Tournament schedule diagnostic file unavailable: %s',errors)
        _STATUS['write_error']=errors or None
        _LAST_FLUSH=time.monotonic()
        return bool(written)


def _event(name, **details):
    with _STATUS_LOCK:
        _STATUS_EVENTS.append({'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                               'event':name,**details})
    LOG.info('Tournament schedule %s %s',name,details)
    write_status(True)


class ScheduleClick:
    """One-shot intent made by a button adapter, never by a network handler.

    A request alone cannot distinguish entry prefetch from the user's click.
    Keep this boundary explicit until the native click adapter is integrated.
    """
    def __init__(self, uid, clock=time.monotonic):
        self.uid=str(uuid.UUID(uid));self.clock=clock;self.created=clock();self.used=False

    def consume(self, uid):
        if self.used or str(uuid.UUID(uid))!=self.uid or not 0<=self.clock()-self.created<=3:
            return False
        self.used=True
        return True


def local_schedule_url(url, uid):
    """Only the already-existing loopback tournament route may be loaded."""
    uid = str(uuid.UUID(uid))
    parts = urlsplit(url)
    if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1') or parts.username or parts.password:
        raise ValueError('赛程承载只允许游戏自身的本地内容服务')
    # Force port parsing so malformed authorities cannot bypass validation.
    if not parts.port:
        raise ValueError('本地赛程服务缺少端口')
    if parts.path != '/player-studio/tournaments/' + uid:
        raise ValueError('赛程地址与当前赛事不一致')
    query = [(k,v) for k,v in parse_qsl(parts.query) if k != 'host'] + [('host','android')]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


class AndroidScheduleHost:
    """Modal in the actual GameActivity; back dismisses it over the same game.

    All Java references and callbacks remain alive until dismissal. No JS
    interface is installed. The trusted page's return button changes its title;
    a UI-thread Runnable observes that narrow signal and dismisses the Dialog.
    """
    def __init__(self):
        from java import dynamic_proxy, jclass
        self.jclass = jclass
        self.dynamic_proxy = dynamic_proxy
        self.activity = jclass(ENTRY_EVIDENCE['activity']).Get()
        if self.activity is None:
            raise RuntimeError('游戏 Activity 尚未就绪')
        self.dialog = self.web = self.poller = self.dismiss_listener = None
        self.current_url = None
        self.last_error = None
        self.last_title = None
        self.shown = False
        self.pending = False
        self._show_task = None
        self._close_task = None
        self.handler = jclass('android.os.Handler')(jclass('android.os.Looper').getMainLooper())

    def _ui(self, function):
        class Task(self.dynamic_proxy(self.jclass('java.lang.Runnable'))):
            def run(_self):
                function()
        task = Task()
        self.activity.runOnUiThread(task)
        return task

    def open(self, url):
        if self.pending:
            _event('host_open_already_pending')
            return False
        self.pending = True
        _event('host_open_queued',url=url)
        self._show_task = self._ui(lambda: self._show(url))
        return True

    def _show(self, url):
        try:
            if self.activity.isFinishing():
                raise RuntimeError('游戏 Activity 正在退出')
            if self.dialog is not None and self.dialog.isShowing():
                self.web.loadUrl(url)
                self.current_url = url
                return
            jc = self.jclass
            dialog = jc('android.app.Dialog')(self.activity, 16973834)  # Theme_Black_NoTitleBar_Fullscreen
            web = jc('android.webkit.WebView')(self.activity)
            settings = web.getSettings()
            settings.setJavaScriptEnabled(True)
            settings.setDomStorageEnabled(True)
            settings.setAllowFileAccess(False)
            settings.setAllowContentAccess(False)
            settings.setJavaScriptCanOpenWindowsAutomatically(False)
            settings.setSupportMultipleWindows(False)
            settings.setBuiltInZoomControls(False)
            web.setWebViewClient(jc('android.webkit.WebViewClient')())
            web.setBackgroundColor(-16051680)
            dialog.setContentView(web)
            dialog.setCancelable(True)
            dialog.setCanceledOnTouchOutside(False)
            owner = self

            class Dismiss(self.dynamic_proxy(jc('android.content.DialogInterface$OnDismissListener'))):
                def onDismiss(_self, _dialog):
                    owner._dismissed()

            class Poll(self.dynamic_proxy(jc('java.lang.Runnable'))):
                def run(_self):
                    if owner.dialog is None or not owner.dialog.isShowing():
                        return
                    try:
                        title=str(owner.web.getTitle())
                        if title!=owner.last_title:
                            owner.last_title=title
                            _event('webview_title',title=title)
                        if title == 'player-studio-schedule:close':
                            owner.dialog.dismiss()
                            return
                        owner.handler.postDelayed(_self, 150)
                    except Exception:
                        LOG.exception('Tournament WebView host polling failed')
                        owner.close()

            self.dialog, self.web, self.current_url = dialog, web, url
            self.dismiss_listener, self.poller = Dismiss(), Poll()
            dialog.setOnDismissListener(self.dismiss_listener)
            dialog.show()
            self.shown=True
            _event('dialog_show_returned')
            window = dialog.getWindow()
            window.setLayout(-1, -1)
            window.setSoftInputMode(16)  # SOFT_INPUT_ADJUST_RESIZE for team search.
            window.getDecorView().setSystemUiVisibility(self.activity.getWindow().getDecorView().getSystemUiVisibility())
            jc(ENTRY_EVIDENCE['visibility_class']).WebViewVisible(True)
            web.loadUrl(url)
            _event('webview_load_requested',url=url)
            self.handler.postDelayed(self.poller, 150)
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            _event('host_show_failed',error=type(exc).__name__+': '+str(exc))
            LOG.exception('Unable to present the in-game tournament schedule')
            if self.dialog is not None:
                self.dialog.dismiss()
        finally:
            self.pending = False
            write_status(True)

    def _dismissed(self):
        try:
            if self.poller is not None:
                self.handler.removeCallbacks(self.poller)
            if self.web is not None:
                self.web.stopLoading()
                self.web.loadUrl('about:blank')
                self.web.destroy()
        finally:
            self.dialog = self.web = self.poller = self.dismiss_listener = None
            self.current_url = None
            self.shown=False
            self.jclass(ENTRY_EVIDENCE['visibility_class']).WebViewVisible(False)
            _event('dialog_dismissed')

    def close(self):
        def dismiss():
            if self.dialog is not None:
                self.dialog.dismiss()
        self._close_task = self._ui(dismiss)


def open_in_game(url, uid):
    global _HOST
    url = local_schedule_url(url, uid)
    if _HOST is None:
        try:
            _HOST = AndroidScheduleHost()
        except Exception as exc:
            _event('host_create_failed',error=type(exc).__name__+': '+str(exc))
            raise
    return _HOST.open(url)


def dispatch_saved_schedule(command, root, uid, overview_url, names=None, opener=None, click=None):
    """Early native-request adapter. Never enter runtime.state/next_fixture.

    Returns None for unrelated commands or an unsaved event. The caller must
    retain its original native flow until the specific menu replacement is
    validated. A queued UI is explicitly not reported as device-tested success.
    """
    if command not in (ENTRY_EVIDENCE['schedule_request'],ENTRY_EVIDENCE['challenge_schedule_request']):
        return None
    if not isinstance(click,ScheduleClick) or not click.consume(uid):
        return None
    from tournament_schedule_ui import read_saved
    current = read_saved(root, uid)
    if current is None:
        return None
    url = local_schedule_url(overview_url.rstrip('/') + '/' + str(uuid.UUID(uid)), uid)
    queued = (opener or open_in_game)(url, uid)
    return {'uuid': uid, 'run_id': current['run_id'], 'queued': bool(queued),
            'device_validated': False, 'requires_native_menu_integration': True}


def schedule_button_clicked(root, uid, overview_url, opener=None):
    """Preferred integration: consume the actual native button action itself.

    Call before the original action creates/forwards to its stock schedule
    menu, and skip that forwarding if queued. No schedule RPC is needed, so
    closing the Dialog reveals the original event menu rather than a blank
    stock schedule. This function is not automatically wired on import.
    """
    return dispatch_saved_schedule(ENTRY_EVIDENCE['schedule_request'],root,uid,overview_url,
                                   opener=opener,click=ScheduleClick(uid))


class ClickChannel:
    """Retained header/counters only; engine actor addresses are never read."""
    def __init__(self, buffer, offset, schema, fence):
        if schema!=CHANNEL_SCHEMA or not callable(fence) or type(offset)is not int or offset<0 or offset%16:
            raise ValueError('赛程点击通道协议无效')
        if offset+schema['bytes']>len(buffer):
            raise ValueError('赛程点击通道越界')
        self.buffer=buffer;self.offset=offset;self.fence=fence;self.last_result=None
        self.set_ready(False)

    def snapshot(self):
        self.fence()
        raw=bytes(memoryview(self.buffer).cast('B')[self.offset:self.offset+CHANNEL_SCHEMA['bytes']])
        self.fence()
        ui=lambda at:struct.unpack_from('<I',raw,at)[0]
        uq=lambda at:struct.unpack_from('<Q',raw,at)[0]
        diag=CHANNEL_SCHEMA['diagnostics'];gate=lambda n:DIAGNOSTIC_GATES[n-1] if 1<=n<=len(DIAGNOSTIC_GATES) else None
        version=ui(diag['version_offset'])
        return {'ready':ui(0),'pending':ui(4),'sequence':uq(8),'event_id':ui(16),
                'actor_present':bool(uq(24)),'acknowledged':uq(32),'last_dispatch':copy.deepcopy(self.last_result),
                'native_diagnostics_version':version,'last_gate':gate(ui(diag['last_gate'])),
                'last_reject':gate(ui(diag['last_reject'])),
                'observed':None if not version else {
                    'state':None if ui(76)==0xffffffff else ui(76),'event_id':ui(80),'ready':ui(84),
                    'record_count':ui(88),'forward_count':ui(92),'class_fname':uq(96),
                    'expected_class_fname':uq(104),'state_property_offset':struct.unpack_from('<i',raw,112)[0],
                    'fade_flag':ui(116)},
                'reached':{name:ui(diag['reached_offset']+i*4) for i,name in enumerate(DIAGNOSTIC_GATES)},
                'rejected':{name:ui(diag['rejected_offset']+i*4) for i,name in enumerate(DIAGNOSTIC_GATES)}}

    def set_ready(self, ready):
        self.fence()
        struct.pack_into('<I',self.buffer,self.offset,int(bool(ready)))
        self.fence()

    def poll(self, service, opener=None):
        self.fence()
        seq=struct.unpack_from('<Q',self.buffer,self.offset+8)[0]
        pending=struct.unpack_from('<I',self.buffer,self.offset+4)[0]
        event=struct.unpack_from('<I',self.buffer,self.offset+16)[0]
        ack=struct.unpack_from('<Q',self.buffer,self.offset+32)[0]
        self.fence()
        if not seq or not pending or seq==ack or seq!=struct.unpack_from('<Q',self.buffer,self.offset+8)[0]:
            return None
        _event('native_click_received',sequence=seq,event_id=event)
        try:
            definition=next((t for t in service.definitions() if t.get('event_id')==event and t.get('enabled',True)),None)
            if definition is None:
                result={'queued':False,'reason':'saved event no longer enabled'}
            else:
                url=service.overview_url()
                result=schedule_button_clicked(service.root,definition['uuid'],url,opener=opener) if url else {'queued':False,'reason':'content service unavailable'}
            self.last_result=result
            _event('dispatch_finished',sequence=seq,event_id=event,result=result,
                   reason='saved tournament unavailable' if result is None else None)
            return result
        except Exception as exc:
            self.last_result={'queued':False,'error':type(exc).__name__+': '+str(exc)}
            _event('dispatch_failed',sequence=seq,event_id=event,error=self.last_result['error'])
            raise
        finally:
            struct.pack_into('<Q',self.buffer,self.offset+32,seq)
            self.fence()
            struct.pack_into('<I',self.buffer,self.offset+4,0)
            self.fence()
            write_status(True)


def attach_descriptor(payload, hook, body_offset, writable_locations):
    """Used by compose() on desktop and Android; no build-only imports."""
    if not hook.get('tournament_schedule_channel'):
        return
    if payload.get('tournament_schedule_channel') or hook['tournament_schedule_channel']!=CHANNEL_SCHEMA or len(writable_locations)!=1 or writable_locations[0][1]!=CHANNEL_SCHEMA['bytes']:
        raise ValueError('赛程点击通道重复或布局不一致')
    at=hook.get('helper_entries',{}).get('studio_schedule_fence')
    raw=bytes.fromhex(hook['body_hex'])
    if type(at)is not int or at%4 or not 0<=at<=len(raw)-8 or raw[at:at+8]!=bytes.fromhex('bf3b03d5c0035fd6'):
        raise ValueError('赛程点击通道屏障入口无效')
    payload['tournament_schedule_channel']={'version':1,'revision':REVISION,'code_region':'root','fence_offset':body_offset+at,
                                           'data_offset':writable_locations[0][0],'schema':copy.deepcopy(CHANNEL_SCHEMA)}


def configure(service):
    """Called once by the tournament installer, after constructing Service."""
    global _SERVICE
    _SERVICE=service
    _event('service_configured')
    _start_worker()


def register_channel(buffer, offset, schema, fence):
    """Called only after the checked binding installer made its fence executable."""
    global _CHANNEL
    if _CHANNEL is not None:
        _CHANNEL.set_ready(False)
    _CHANNEL=ClickChannel(buffer,offset,schema,fence)
    _event('channel_registered',bytes=schema['bytes'],data_offset=offset)
    _start_worker()
    return _CHANNEL


def register_binding_channel(binding, prefix_address, extension_address):
    """Small integration seam for personal_binding._BindingCtypes.memmove."""
    try:
        descriptor=binding.payload['tournament_schedule_channel'];region=descriptor['code_region']
        if descriptor.get('version')!=1 or descriptor.get('revision')!=REVISION or region not in ('root','extension'):
            raise ValueError('赛程点击通道重定位信息无效')
        raw=bytes.fromhex(binding.payload['extension_blob_hex'] if region=='extension' else binding.payload['blob_hex'])
        at=descriptor['fence_offset'];base=extension_address if region=='extension' else prefix_address
        if not base or type(at)is not int or at%4 or not 0<=at<=len(raw)-8 or raw[at:at+8]!=bytes.fromhex('bf3b03d5c0035fd6'):
            raise ValueError('赛程点击通道内存屏障未核验')
        fence=binding.original.CFUNCTYPE(None)(base+at)
        return register_channel(binding.writable,descriptor['data_offset'],descriptor['schema'],fence)
    except Exception as exc:
        _event('channel_registration_failed',error=type(exc).__name__+': '+str(exc))
        raise


def _start_worker():
    global _WORKER
    if _CHANNEL is None or _SERVICE is None:
        with _STATUS_LOCK:
            _STATUS['ready_reason']='channel not registered' if _CHANNEL is None else 'service not configured'
        write_status(True)
        return
    if _WORKER is not None and _WORKER.is_alive():
        return
    def work():
        while True:
            channel,service=_CHANNEL,_SERVICE
            try:
                _worker_tick(channel,service)
                time.sleep(.1)
            except Exception as exc:
                channel.set_ready(False)
                with _STATUS_LOCK:
                    _STATUS.update(ready_reason='worker exception',worker_error=type(exc).__name__+': '+str(exc),worker_tick=time.time())
                _event('worker_failed',error=_STATUS['worker_error'])
                LOG.exception('Tournament click adapter unavailable; event menu retained')
                time.sleep(1)
    _WORKER=threading.Thread(target=work,name='studio-tournament-schedule',daemon=True)
    _WORKER.start()
    _event('worker_started')


def _worker_tick(channel,service):
    definitions=service.definitions();url=service.overview_url()
    enabled=bool(definitions) and bool(url)
    reason='ready' if enabled else ('no tournament definitions' if not definitions else 'content service unavailable')
    with _STATUS_LOCK:
        changed=_STATUS.get('ready_reason')!=reason
        _STATUS.update(ready_reason=reason,definition_count=len(definitions),
                       enabled_event_ids=[t.get('event_id') for t in definitions],
                       overview_available=bool(url),worker_tick=time.time(),worker_error=None)
    channel.set_ready(enabled)
    if changed:_event('ready_changed',ready=enabled,reason=reason)
    snapshot=channel.snapshot();hits=snapshot['reached']['entry']
    with _STATUS_LOCK:
        previous=_STATUS.get('last_native_entry_count',0)
        _STATUS['last_native_entry_count']=hits
    if hits!=previous:
        _event('native_guard_activity',entry_count=hits,last_gate=snapshot['last_gate'],
               last_reject=snapshot['last_reject'],observed=snapshot['observed'])
    if enabled:channel.poll(service)
    write_status()
