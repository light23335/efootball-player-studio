"""Show earned tournament rewards over the actual GameActivity homepage.

The checked native home adapter supplies the render signal. Network prefetch
alone never opens a window. Confirmation marks only an existing award as seen;
this module cannot grant chances, players or progression.
"""
from contextlib import closing
import copy
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time

LOG=logging.getLogger(__name__)
_SERVICE=_CHANNEL=_WORKER=None
_LOCK=threading.RLock()


def _database(root):
    path=(Path(root)/'outputs/efootball/local-club.sqlite3').resolve()
    return path if path.is_file() else None


def offer(root,definitions,event):
    from tournament_runtime import PREFIX
    from tournament_rewards import status
    definition=next((t for t in definitions if t.get('event_id')==event and t.get('enabled',True)),None)
    path=_database(root)
    if definition is None or path is None:return None
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))as conn:
        row=conn.execute('select value from meta where key=?',(PREFIX+definition['uuid'],)).fetchone()
    if row is None:return None
    current=json.loads(row[0]);ledger=current.get('reinforcements',{})
    from tournament_promotion import pending as pending_promotion
    progression=pending_promotion(current)
    if progression and progression['animation']=='PROMOTED':return None
    if current.get('completed') or ledger.get('closed') or ledger.get('run_id')!=current.get('run_id'):return None
    for stage,award in ledger.get('awards',{}).items():
        if award.get('notified') or type(award.get('granted'))is not int or award['granted']<=0:continue
        return {'uuid':definition['uuid'],'run_id':current['run_id'],'stage_uuid':stage,
                'title':'晋级奖励','granted':award['granted'],'available':status(current)['available'],
                'body':current['definition']['name']+'\n\n'+award.get('message','已晋级下一阶段，可以补强球队了！')+
                       '\n\n获得特殊机会：'+str(award['granted'])+' 次\n当前剩余：'+str(status(current)['available'])+
                       ' 次\n\n前往「合约 → 锦标赛特殊机会抽取」使用机会。'}
    return None


def confirm(root,ticket):
    """Read latest state under the gateway lock; never save a stale UI copy."""
    from tournament_runtime import PREFIX,LOCK
    path=_database(root)
    if path is None:return False
    with LOCK,closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=2))as conn,conn:
        conn.execute('begin immediate')
        key=PREFIX+ticket['uuid'];row=conn.execute('select value from meta where key=?',(key,)).fetchone()
        if row is None:return False
        current=json.loads(row[0]);ledger=current.get('reinforcements',{})
        if current.get('run_id')!=ticket['run_id'] or ledger.get('run_id')!=ticket['run_id']:return False
        award=ledger.get('awards',{}).get(ticket['stage_uuid'])
        if award is None or award.get('granted')!=ticket['granted']:return False
        if not award.get('notified'):
            award['notified']=True
            conn.execute('update meta set value=? where key=?',(json.dumps(current,ensure_ascii=False,separators=(',',':')),key))
    return True


class AndroidRewardHost:
    def __init__(self):
        from java import jclass,dynamic_proxy
        self.jclass=jclass;self.proxy=dynamic_proxy
        self.activity=jclass('com.epicgames.ue4.GameActivity').Get()
        if self.activity is None:raise RuntimeError('游戏 Activity 尚未就绪')
        self.dialog=self.task=self.listener=self.dismiss_listener=None

    def show(self,ticket,accepted,failed):
        jc=self.jclass;owner=self
        class Task(self.proxy(jc('java.lang.Runnable'))):
            def run(_self):
                blocked=False
                try:
                    if owner.activity.isFinishing():raise RuntimeError('游戏 Activity 正在退出')
                    class Confirm(owner.proxy(jc('android.content.DialogInterface$OnClickListener'))):
                        def onClick(_self,_dialog,_which):accepted()
                    class Dismiss(owner.proxy(jc('android.content.DialogInterface$OnDismissListener'))):
                        def onDismiss(_self,_dialog):
                            jc('com.epicgames.ue4.NativeCalls').WebViewVisible(False)
                            owner.dialog=None
                    owner.listener=Confirm();owner.dismiss_listener=Dismiss()
                    builder=jc('android.app.AlertDialog$Builder')(owner.activity)
                    builder.setTitle(ticket['title']);builder.setMessage(ticket['body'])
                    builder.setCancelable(False);builder.setPositiveButton('确认',owner.listener)
                    owner.dialog=builder.create();owner.dialog.setOnDismissListener(owner.dismiss_listener)
                    jc('com.epicgames.ue4.NativeCalls').WebViewVisible(True);blocked=True
                    owner.dialog.show()
                    LOG.info('Tournament reward shown: run=%s stage=%s granted=%s',ticket['run_id'],ticket['stage_uuid'],ticket['granted'])
                except Exception:
                    if blocked:jc('com.epicgames.ue4.NativeCalls').WebViewVisible(False)
                    failed();LOG.exception('Tournament reward dialog failed; award retained')
        self.task=Task();self.activity.runOnUiThread(self.task)
        return True


class Presenter:
    def __init__(self,service,channel,host_factory=AndroidRewardHost,clock=time.monotonic):
        self.service=service;self.channel=channel;self.factory=host_factory;self.clock=clock
        self.host=None;self.pending=None;self.ack=None;self.retry_at=0;self.lock=threading.RLock()
        self.signal=None;self.signal_at=0

    def tick(self):
        with self.lock:
            if self.ack is not None:
                ticket=self.ack
                confirm(self.service.root,ticket)  # Exceptions retain ack for a bounded later retry.
                self.ack=self.pending=None
                LOG.info('Tournament reward confirmed: run=%s stage=%s',ticket['run_id'],ticket['stage_uuid'])
            if self.pending is not None or self.clock()<self.retry_at:return False
            if getattr(self.channel,'promotion_busy',lambda:False)():return False
            seq,event=self.channel.rendered()
            if not seq or not event:return False
            if (seq,event)!=self.signal:
                self.signal=(seq,event);self.signal_at=self.clock()
            # A retained render signal is not proof that the player is STILL
            # on that page. Never retry a failed UI over a later match/menu.
            if self.clock()-self.signal_at>2:return False
            # Share the Activity host, without stacking a reward over a schedule.
            import native_tournament_schedule_ui as schedule
            if schedule._HOST is not None and (schedule._HOST.pending or schedule._HOST.shown):return False
            ticket=offer(self.service.root,self.service.definitions(),event)
            if ticket is None:return False
            self.pending=copy.deepcopy(ticket)
            def accepted():
                with self.lock:self.ack=copy.deepcopy(ticket)
            def failed():
                with self.lock:
                    self.pending=None;self.retry_at=self.clock()+3
            try:
                if self.host is None:self.host=self.factory()
                if self.host.show(copy.deepcopy(ticket),accepted,failed)is False:failed();return False
            except Exception:
                failed();raise
            return True


def configure(service):
    global _SERVICE
    with _LOCK:_SERVICE=service
    _start()


def channel_ready(channel):
    global _CHANNEL
    with _LOCK:_CHANNEL=channel
    _start()


def _start():
    global _WORKER
    with _LOCK:
        if _SERVICE is None or _CHANNEL is None or _WORKER is not None and _WORKER.is_alive():return
        presenter=Presenter(_SERVICE,_CHANNEL)
        def work():
            while True:
                try:presenter.tick()
                except Exception:LOG.exception('Tournament reward pending; retrying');time.sleep(2)
                time.sleep(.2)
        _WORKER=threading.Thread(target=work,name='studio-tournament-rewards',daemon=True)
        _WORKER.start()
