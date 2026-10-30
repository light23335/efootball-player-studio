"""Bounded native player-action journal; no engine object is read by Python.

Native callbacks publish a committed event ring in private RW memory. This
consumer only copies that buffer, so leaving a match cannot leave a dangling
actor/coach pointer in a Python worker. IDs not independently decoded retain
their native number instead of receiving an invented action description.
"""
import datetime,json,logging,math,os,struct,threading,time,shutil
import hashlib,copy
from pathlib import Path

MAGIC=0x54524331
VERSION=3
HEADER_BYTES=4096
EVENT_BYTES=192
CAPACITY=4096
BUFFER_BYTES=HEADER_BYTES+EVENT_BYTES*CAPACITY
SCHEMA={'version':VERSION,'magic':MAGIC,'bytes':BUFFER_BYTES,'header_bytes':HEADER_BYTES,
        'event_bytes':EVENT_BYTES,'capacity':CAPACITY,'enabled_offset':4,
        'sequence_offset':16,'dropped_offset':24,'counters_offset':3072,
        'counter_stride':128,'counter_sources':6,'counter_kinds':[1,2,3,4,6],'validity_offset':100}
COUNTERS=('entered','disabled','null_actor','invalid_slot','null_root','identity_mismatch',
          'invalid_phase','deduplicated','contention','published','missing_game_info',
          'invalid_request','root_mismatch','context_invalid_slot','context_missing','actor_not_in_current_match')
KINDS={1:'action_change',2:'ai_shot_request',3:'ai_shot_power',4:'motion_selection',5:'native_diagnostic',6:'ai_candidate_choice',7:'movement_sample'}
STAGES={1:'native_request_before_preference',2:'request_after_preference',
        3:'native_power_before_preference',4:'power_after_preference',5:'native_candidate_before_preference',6:'candidate_after_preference'}
# 6d45fc4 maps actor state 10 PLUS control mode to output IDs 9/10/11.
# This hook reads the raw state, not that function's result. Labelling raw
# state 10 as a controlled shot would make the diagnostic itself misleading.
ACTIONS={}
SHOT_TYPES={0:'普通射门',1:'控制射门',2:'挑射',3:'大力射门（紫射）',4:'原生射门模式 1'}
NATIVE_KINDS=(1,2,3,4,6,7)
_THREADS=[]
_CHANNELS=[]
_CONFIG=None
_PUBLIC_URIS={}
_PENDING=[]
_EVENT_LOCK=threading.RLock()
_MATCH_STATE={}
_ACTIVE_GAME=None


def finite(value):return round(value,6)if math.isfinite(value)else None


def export_public(path):
    """Copy our own completed snapshot to Downloads, never query other files."""
    from java import jclass,jarray,jbyte
    context=jclass('com.chaquo.python.Python').getPlatform().getApplication()
    sdk=jclass('android.os.Build$VERSION').SDK_INT
    if sdk<29:
        folder=Path(str(jclass('android.os.Environment').getExternalStoragePublicDirectory('Download')))/'PlayerStudioLogs'
        folder.mkdir(parents=True,exist_ok=True);target=folder/path.name;shutil.copyfile(path,target)
        return str(target)
    resolver=context.getContentResolver();values=jclass('android.content.ContentValues')()
    integer=jclass('java.lang.Integer');uri=_PUBLIC_URIS.get(str(path))
    if uri is None:
        values.put('_display_name',path.name);values.put('mime_type','application/x-ndjson')
        values.put('relative_path','Download/PlayerStudioLogs');values.put('is_pending',integer(1))
        uri=resolver.insert(jclass('android.provider.MediaStore$Downloads').EXTERNAL_CONTENT_URI,values)
        if uri is None:raise OSError('Download log entry unavailable')
        _PUBLIC_URIS[str(path)]=uri
    stream=resolver.openOutputStream(uri,'wt')
    if stream is None:raise OSError('Download log stream unavailable')
    try:
        with path.open('rb')as source:
            for data in iter(lambda:source.read(64*1024),b''):
                stream.write(jarray(jbyte)(data))
        stream.flush()
    finally:stream.close()
    pending=jclass('android.content.ContentValues')();pending.put('is_pending',integer(0))
    resolver.update(uri,pending,None,None)
    return str(uri)


def decode_event(raw):
    if len(raw)!=EVENT_BYTES:raise ValueError('动作日志事件长度无效')
    seq,root,actor=struct.unpack_from('<QQQ',raw)
    frame,phase,slot,action,request,subtype,skills=struct.unpack_from('<7I',raw,24)
    kind,original,selected,reason=struct.unpack_from('<4I',raw,84)
    if not seq or (slot>=22 and kind!=5):raise ValueError('动作日志球员编号无效')
    position=list(map(finite,struct.unpack_from('<3f',raw,52)))
    target=list(map(finite,struct.unpack_from('<3f',raw,64)))
    before,after=map(finite,struct.unpack_from('<2f',raw,76))
    if kind not in KINDS:raise ValueError('动作日志事件类型无效')
    record={'sequence':seq,'event':KINDS[kind],'frame':frame,'phase':phase,
            'team':slot//11,'slot':slot,'team_slot':slot%11,
            'action':{'id':action,'name':ACTIONS.get(action,'原生状态 '+str(action)),
                      'source':'actor_state_byte_0xad0'},
            'request':{'id':request,'subtype':subtype,
                       'name':SHOT_TYPES.get(subtype,'原生射门类型 '+str(subtype))if request==25 else '原生请求 '+str(request)},
            'skills':[name for bit,name in ((1,'弧线落叶射门'),(2,'掠地瞬击'),(4,'重炮攻门'))if skills&bit],
            'position':position,'target':target,'power_before':before,'power_after':after,
            'original_type':original,'selected_type':selected,'reason_code':reason,
            'native_match_key':hex(root),'native_actor_key':hex(actor),
            'player_id':struct.unpack_from('<Q',raw,104)[0],
            'player_serial':struct.unpack_from('<Q',raw,120)[0],
            'caller':hex(struct.unpack_from('<Q',raw,112)[0])}
    if kind==4:
        record['motion']={'family_id':original,'name':'弧线落叶射门动作'if original==160 else '原生动作族 '+str(original),
                          'selection_succeeded':bool(selected)}
    record['native_game_actor_key']=hex(struct.unpack_from('<Q',raw,176)[0])
    record['callback_object_key']=hex(actor)
    record['correlation']={'player_slot_key':hex(root)+':'+str(slot),'frame':frame,'caller':record['caller']}
    if action==0xffffffff:record['action']=None
    if kind==3:
        word=struct.unpack_from('<I',raw,128)[0]
        record['native_control']={'word':word,'mode':(word>>16)&255,'stunning':bool(word&(1<<26))}
    if kind==6:
        before_kind,after_kind=struct.unpack_from('<II',raw,128)
        names={1:'射门',2:'传球',3:'盘带候选',10:'原生类别 10（待核对）'}
        record['candidate']={'original_id':original,'selected_id':selected,'original_kind':before_kind,'selected_kind':after_kind,
                             'original_name':names.get(before_kind,'原生类别 '+str(before_kind)),
                             'selected_name':names.get(after_kind,'原生类别 '+str(after_kind)),
                             'changed':original!=selected,'no_executable_candidate':original==30 and selected==30,'motion_execution_confirmed':False}
        if original==30:record['candidate']['original_name']='当前无可用候选'
        if selected==30:record['candidate']['selected_name']='当前无可用候选'
    ai_flags=struct.unpack_from('<I',raw,148)[0]
    record['ai_styles']=[name for bit,name in ((4,'内切突破'),(7,'独狼'))if ai_flags&(1<<bit)]
    flags=struct.unpack_from('<I',raw,100)[0]
    record['identity_verified']=bool(flags&1)
    record['slot_source']='native GameActor index'if flags&4 else 'current PlayerInfo table'if flags&2 else 'unverified'
    record['match_membership_verified']=bool(flags&2)
    if kind==5:
        record.update(team=None,slot=None,team_slot=None,frame=None,phase=None,
                      player_id=None,player_serial=None,position=None,target=None,skills=None,
                      action=None,request=None,power_before=None,power_after=None)
        record['diagnostic']={'source':KINDS.get(selected,'unknown'),
                              'reason':COUNTERS[reason]if reason<len(COUNTERS)else 'unknown',
                              'raw_context_slot':original if reason==13 else None,
                              'unverified_object_key':hex(actor)}
        record['native_actor_key']=None
    else:
        record['stage']=STAGES.get(reason)
        if not flags&1:record.update(player_id=None,player_serial=None)
    if kind in (2,3):
        record['original_type_name']=SHOT_TYPES.get(original,'原生射门类型 '+str(original))
        record['selected_type_name']=SHOT_TYPES.get(selected,'原生射门类型 '+str(selected))
        record['correlation']['actor']=hex(actor)
        if kind==2:record['modification_reason']='preference_type_rewrite'if reason==2 and original!=selected else 'type_unchanged'if reason==2 else 'native_request'
        else:record['modification_reason']='bounded_power_adjustment'if reason==4 and before!=after else 'power_unchanged'if reason==4 else 'native_power'
    return record


class RingReader:
    def __init__(self,read,fence=lambda:None):
        self.read=read;self.fence=fence;self.sequence=0;self.dropped=0
        self.unknown_reported=False

    def diagnostics(self):
        raw=self.read(SCHEMA['counters_offset'],SCHEMA['counter_stride']*SCHEMA['counter_sources'])
        return {'sources':{KINDS[k]:dict(zip(COUNTERS,struct.unpack_from('<'+str(len(COUNTERS))+'Q',raw,(k-1)*128)))for k in SCHEMA['counter_kinds']},
                'published':struct.unpack('<Q',self.read(16,8))[0],
                'dropped':struct.unpack('<Q',self.read(24,8))[0],
                'enabled':struct.unpack('<I',self.read(4,4))[0],
                'counter_contention':bool(struct.unpack('<I',self.read(40,4))[0]),
                'counters_are_atomic_individual_samples':True}

    def drain(self):
        head=self.read(0,40)
        if len(head)!=40 or struct.unpack_from('<I',head)[0]!=MAGIC:return []
        published=struct.unpack_from('<Q',head,16)[0]
        dropped=struct.unpack_from('<Q',head,24)[0];out=[]
        if published<self.sequence:
            out.append({'event':'trace_reset','previous_sequence':self.sequence});self.sequence=0
        if published-self.sequence>CAPACITY:
            missed=published-self.sequence-CAPACITY
            out.append({'event':'trace_overrun','lost_events':missed})
            self.sequence=published-CAPACITY
        if dropped>self.dropped:out.append({'event':'trace_contention','lost_events':dropped-self.dropped})
        if struct.unpack_from('<I',head,32)[0] and not self.unknown_reported:
            out.append({'event':'trace_contention','lost_events':0,'count_is_lower_bound':True});self.unknown_reported=True
        self.dropped=dropped
        for seq in range(self.sequence+1,published+1):
            at=HEADER_BYTES+(seq%CAPACITY)*EVENT_BYTES
            record=self.read(at,EVENT_BYTES);self.fence()
            # A producer may wrap this slot while the consumer copies it.
            # Never report a torn action or silently assign it to another actor.
            committed=self.read(at,8)
            if record[:8]!=committed or struct.unpack('<Q',committed)[0]!=seq:
                out.append({'event':'trace_overrun','lost_events':1});self.sequence=seq;continue
            out.append(decode_event(record));self.sequence=seq
        return out


class Journal:
    def __init__(self,root,max_bytes=32*1024*1024,names=None):
        self.folder=Path(root)/'outputs/efootball/player-actions';self.folder.mkdir(parents=True,exist_ok=True)
        self.max_bytes=max_bytes;self.part=0;self.path=None;self.stream=None;self.names=names or {}
        self.run=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(os.getpid())
        self.total=0;self.lock=threading.RLock();self.completed=[];self._open()
        self.counts={};self.match_id=None;self.roster={}
        self.losses={'ring_overrun':0,'native_contention':0,'metadata':0,'unknown':False}

    def _open(self):
        self.path=self.folder/('actions-'+self.run+'-'+str(self.part)+'.jsonl')
        self.stream=self.path.open('a',encoding='utf8',newline='\n')
        self.stream.write(json.dumps({'event':'trace_header','version':VERSION,
                                     'coverage':'native state getter observations, movement samples, motion selection attempts, AI candidate pass/dribble/shot choices and shot requests/power before and after preference',
                                     'not_proof_of_every_played_animation':True,'gameplay_acceptance':'pending',
                                     'duplicate_getters_suppressed':True,'unknown_actions_keep_native_id':True},ensure_ascii=False)+'\n')
        self.stream.flush()

    def append(self,events):
        if not events:return
        with self.lock:
            for event in events:
                value={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**event}
                if self.match_id is not None:value['match_id']=self.match_id
                if value.get('player_id') in self.names:value['player_name']=self.names[value['player_id']]
                self.counts[value['event']]=self.counts.get(value['event'],0)+1
                if value['event']in ('trace_overrun','trace_contention','trace_metadata_overrun'):
                    key={'trace_overrun':'ring_overrun','trace_contention':'native_contention','trace_metadata_overrun':'metadata'}[value['event']]
                    self.losses[key]+=value.get('lost_events',0)
                    self.losses['unknown']|=bool(value.get('count_is_lower_bound'))
                self.stream.write(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n');self.total+=1
            self.stream.flush()
            if self.stream.tell()>self.max_bytes:
                self.stream.close();self.completed.append(self.path);self.part+=1;self._open()
            native=sum(self.counts.get(KINDS[k],0)for k in NATIVE_KINDS)
            status={'enabled':True,'events':self.total,'native_events':native,'event_counts':self.counts,
                    'match_id':self.match_id,'path':self.path.name,'part':self.part,'schema':VERSION,
                    'lost_events':dict(self.losses),
                    'capture_complete':False,'completion_note':'inspect lifecycle, native counters and gap reports; no universal action coverage proof'}
            tmp=self.folder/'status.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False),'utf8');tmp.replace(self.folder/'status.json')

    def close(self):
        with self.lock:
            if self.stream and not self.stream.closed:self.stream.close()

    def switch_match(self,match_id,metadata):
        with self.lock:
            if self.match_id==str(match_id):return
            if self.match_id is not None:self.append([{'event':'match_capture_closed','reason':'next match','clean_finish':False}])
            self.stream.close();self.completed.append(self.path);self.part=0
            self.match_id=str(match_id);self.roster={};self.counts={};self.total=0
            self.losses={'ring_overrun':0,'native_contention':0,'metadata':0,'unknown':False}
            self.run=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(os.getpid())+'-match-'+hashlib.sha256(self.match_id.encode()).hexdigest()[:12]
            self._open();self.append([{'event':'match_capture_opened',**metadata}])


def record_lifecycle(event,metadata):
    """Queue copies of already published state; no engine calls or pointers."""
    if not _CONFIG or not _CONFIG['enabled']:return
    with _EVENT_LOCK:
        if len(_PENDING)>=2048:
            _PENDING[-1]={'event':'trace_metadata_overrun','lost_events':_PENDING[-1].get('lost_events',0)+1};return
        _PENDING.append({'event':event,**copy.deepcopy(metadata)})


def observe_match(spec,snapshot):
    if not _CONFIG or not _CONFIG['enabled']:return
    gid=spec['game_id'];previous=_MATCH_STATE.get(gid)
    values={k:snapshot.get(k)for k in ('game_id','phase','period','clock_frames','score','match_clock')}
    values['game_id']=gid
    values['roster']=[{**{k:p.get(k)for k in ('expected_index','lineup_slot','physical_index')},
                      'id':spec['players'][p['expected_index']]['id'],
                      'serial':spec['players'][p['expected_index']]['serial']}for p in snapshot['live']]
    key=(values['phase'],values['period'],tuple(values['score']),int(values['clock_frames']//1800),
         tuple((p['id'],p['lineup_slot'])for p in values['roster']))
    if previous==key:return
    _MATCH_STATE.clear();_MATCH_STATE[gid]=key
    record_lifecycle('match_state',values)


def install_lifecycle(logic=None):
    if logic is None:
        import gate_logic
        cls=gate_logic.GateLogic
    else:cls=type(logic)
    previous=cls.handle
    if getattr(previous,'_studio_action_lifecycle',False):return
    def handle(self,command,request):
        global _ACTIVE_GAME
        response=previous(self,command,request)
        try:
            if isinstance(response,dict) and response.get('result')=='NOERR':
                data={'command':command,'game_id':request.get('game_id',response.get('game_id'))}
                if command=='CMD_START_GAME':
                    if data['game_id'] is None:data.update(game_id='gateway-'+str(time.time_ns()),id_source='process-local accepted start; native match ID unavailable')
                    _ACTIVE_GAME=data['game_id'];record_lifecycle('match_start',data)
                elif command=='CMD_GET_VSCOM_GAME_RESULT':
                    result=request.get('match_result')or{}
                    data.update(game_id=result.get('game_id',data['game_id'])or _ACTIVE_GAME,
                                result={k:v for k,v in result.items()if k in ('score','home_score','away_score','own_goals','opponent_goals','result','game_id')})
                    record_lifecycle('match_end',data)
                elif command in ('CMD_GET_MAINMENU_INFO','CMD_GET_LEAGUE_COM_INFO'):
                    record_lifecycle('match_exit',data)
        except Exception:logging.getLogger(__name__).exception('Action lifecycle log failed; native response retained')
        return response
    handle._studio_action_lifecycle=True;cls.handle=handle


def register_channel(buffer,offset,schema,fence):
    if schema!=SCHEMA or type(offset)is not int or offset<0 or offset%16:
        raise ValueError('动作观察通道格式无效')
    view=memoryview(buffer).cast('B')
    if offset+BUFFER_BYTES>len(view):raise ValueError('动作观察缓冲区不完整')
    def read(at,size):
        if type(at)is not int or type(size)is not int or at<0 or size<0 or at+size>BUFFER_BYTES:
            raise ValueError('动作观察缓冲区越界')
        return bytes(view[offset+at:offset+at+size])
    channel={'view':view,'offset':offset,'reader':RingReader(read,fence),'fence':fence,'thread':None,'stop':threading.Event()}
    _CHANNELS.append(channel)
    if _CONFIG and _CONFIG['enabled']:start(channel,_CONFIG['root'],_CONFIG['names'])
    return channel


def configure(root,document):
    global _CONFIG
    names={}
    for row in document.get('players',[]):
        identity=row.get('identity',{});owned=row.get('owned',{});name=owned.get('name')or owned.get('name_en')
        if name:
            for cid in [identity.get('card_id'),*identity.get('previous_card_ids',[])]:
                if type(cid)is int:names[cid]=str(name)
    enabled=document.get('action_trace',{}).get('enabled')is True
    _CONFIG={'root':Path(root),'names':names,'enabled':enabled}
    if enabled:
        # Observe a copy already published by the existing match adapter. Its
        # policy, snapshot decoder and native execution proof stay unchanged.
        from ai_match_runtime import Bridge
        previous=Bridge.native_log
        if not getattr(previous,'_studio_action_trace',False):
            def native_log(self,snapshot):
                result=previous(self,snapshot)
                try:observe_match(self.spec,snapshot)
                except Exception:logging.getLogger(__name__).exception('Action match-state observation failed')
                return result
            native_log._studio_action_trace=True;Bridge.native_log=native_log
    for channel in _CHANNELS:
        if enabled:start(channel,root,names)
        else:struct.pack_into('<I',channel['view'],channel['offset']+4,0);channel['fence']()


def start(channel,root,names=None):
    if channel['thread'] is not None:
        channel['journal'].names=names or {}
        struct.pack_into('<I',channel['view'],channel['offset']+4,1);channel['fence']();return
    journal=Journal(root,names=names);view=channel['view'];at=channel['offset'];fence=channel['fence']
    channel['journal']=journal
    # The native producer remains a no-op until storage and the consumer exist.
    struct.pack_into('<I',view,at,MAGIC);fence();struct.pack_into('<I',view,at+4,1);fence()
    def worker():
        changed=time.monotonic();last_export=0;exported_count=-1;completed_exports=set();heartbeat=-5;force_export=False
        try:
            while not channel['stop'].is_set():
                with _EVENT_LOCK:pending=list(_PENDING);_PENDING.clear()
                closing=[]
                for row in pending:
                    gid=row.get('game_id')
                    if row['event']in ('match_start','match_state') and gid is not None:
                        journal.switch_match(gid,{'source':'accepted gateway or verified coaching snapshot'})
                        exported_count=-1
                    if row['event']in ('match_end','match_exit'):
                        closing.append(row);continue
                    journal.append([row])
                    if row['event']in ('match_end','match_exit') or row['event']=='match_state' and row.get('phase')!=1:force_export=True
                events=channel['reader'].drain()
                for row in events:
                    if row.get('identity_verified'):
                        key=(row['team'],row['slot']);identity=(row['player_id'],row['player_serial'])
                        if journal.roster.get(key)!=identity:
                            journal.append([{'event':'match_state','source':'observed_native_slot_identity',
                                             'team':key[0],'slot':key[1],'previous':journal.roster.get(key),
                                             'player_id':identity[0],'player_serial':identity[1]}]);journal.roster[key]=identity
                journal.append(events);now=time.monotonic()
                if closing:
                    journal.append(closing+[{'event':'trace_summary','native':channel['reader'].diagnostics(),
                                            'written_counts':dict(journal.counts),'observed_slots':len(journal.roster),
                                            'lost_events':dict(journal.losses),
                                            'capture_complete':False,'end_received':True}]);force_export=True
                if events:changed=now
                if now-heartbeat>=5:
                    diagnostic=channel['reader'].diagnostics()
                    journal.append([{'event':'trace_heartbeat','native':diagnostic,
                                     'worker_alive':True,'written_native_events':sum(journal.counts.get(KINDS[k],0)for k in NATIVE_KINDS),
                                     'lost_events':diagnostic['dropped'],'capture_complete':False}]);heartbeat=now
                # Busy matches also export every 15 seconds. File IO remains
                # in this worker, never a native callback or gameplay thread.
                if exported_count!=journal.total and (now-last_export>=15 or force_export or now-changed>=3 and now-last_export>=3):
                    last_export=now
                    try:
                        for completed in journal.completed:
                            if completed not in completed_exports:export_public(completed);completed_exports.add(completed)
                        uri=export_public(journal.path);exported_count=journal.total
                        status={'public_log':uri,'private_file':journal.path.name,'events':journal.total,
                                'native_events':sum(journal.counts.get(KINDS[k],0)for k in NATIVE_KINDS),
                                'event_counts':journal.counts,'match_id':journal.match_id,
                                'lost_events':dict(journal.losses),
                                'snapshot_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                'policy':'periodic 15s, quiet 3s, lifecycle flush; worker IO duration may extend interval'}
                        (journal.folder/'public-export.json').write_text(json.dumps(status,ensure_ascii=False),'utf8')
                        force_export=False
                    except Exception as error:
                        (journal.folder/'public-export.json').write_text(json.dumps({'private_file':journal.path.name,'export_error':str(error)},ensure_ascii=False),'utf8')
                time.sleep(.05)
        except Exception:
            logging.getLogger(__name__).exception('Action observer stopped; native gameplay retained')
            struct.pack_into('<I',view,at+4,0);fence()
        finally:
            try:
                journal.append([{'event':'trace_summary','reason':'observer_stopped','native':channel['reader'].diagnostics(),
                                 'written_counts':dict(journal.counts),'lost_events':dict(journal.losses),'capture_complete':False}])
                for path in [*journal.completed,journal.path]:export_public(path)
            except Exception:logging.getLogger(__name__).warning('Final action export failed',exc_info=True)
            journal.close()
    thread=threading.Thread(target=worker,name='PlayerActionLog',daemon=True);channel['thread']=thread
    _THREADS.append((channel,journal,thread));thread.start()


def shutdown():
    for channel in _CHANNELS:channel['stop'].set()
    for channel in _CHANNELS:
        thread=channel.get('thread')
        if thread is not None and thread is not threading.current_thread():thread.join(timeout=1)


import atexit
atexit.register(shutdown)
