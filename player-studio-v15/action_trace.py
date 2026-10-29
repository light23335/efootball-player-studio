"""Bounded native player-action journal; no engine object is read by Python.

Native callbacks publish a committed event ring in private RW memory. This
consumer only copies that buffer, so leaving a match cannot leave a dangling
actor/coach pointer in a Python worker. IDs not independently decoded retain
their native number instead of receiving an invented action description.
"""
import datetime,json,logging,math,os,struct,threading,time,shutil
from pathlib import Path

MAGIC=0x54524331
VERSION=1
HEADER_BYTES=4096
EVENT_BYTES=128
CAPACITY=4096
BUFFER_BYTES=HEADER_BYTES+EVENT_BYTES*CAPACITY
SCHEMA={'version':VERSION,'magic':MAGIC,'bytes':BUFFER_BYTES,'header_bytes':HEADER_BYTES,
        'event_bytes':EVENT_BYTES,'capacity':CAPACITY,'enabled_offset':4,
        'sequence_offset':16,'dropped_offset':24}
KINDS={1:'action_change',2:'ai_shot_request',3:'ai_shot_power',4:'motion_selection'}
# Original 6d45fc4 maps shoot state 10 and control mode 0/2/3 to 9/10/11.
ACTIONS={9:'普通射门',10:'控制射门',11:'大力射门（紫射）'}
SHOT_TYPES={0:'普通射门',1:'控制射门',2:'大力射门（紫射）',4:'挑射'}
_THREADS=[]
_CHANNELS=[]
_CONFIG=None
_PUBLIC_URIS={}


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
    if not seq or slot>=22:raise ValueError('动作日志球员编号无效')
    position=list(map(finite,struct.unpack_from('<3f',raw,52)))
    target=list(map(finite,struct.unpack_from('<3f',raw,64)))
    before,after=map(finite,struct.unpack_from('<2f',raw,76))
    kind,original,selected,reason=struct.unpack_from('<4I',raw,84)
    if kind not in KINDS:raise ValueError('动作日志事件类型无效')
    record={'sequence':seq,'event':KINDS[kind],'frame':frame,'phase':phase,
            'team':slot//11,'slot':slot,'team_slot':slot%11,
            'action':{'id':action,'name':ACTIONS.get(action,'原生动作 '+str(action))},
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
    return record


class RingReader:
    def __init__(self,read,fence=lambda:None):
        self.read=read;self.fence=fence;self.sequence=0;self.dropped=0
        self.unknown_reported=False

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

    def _open(self):
        self.path=self.folder/('actions-'+self.run+'-'+str(self.part)+'.jsonl')
        self.stream=self.path.open('a',encoding='utf8',newline='\n')
        self.stream.write(json.dumps({'event':'trace_header','version':VERSION,'coverage':'both teams; native action transitions and AI shot request/power',
                                     'duplicate_getters_suppressed':True,'unknown_actions_keep_native_id':True},ensure_ascii=False)+'\n')
        self.stream.flush()

    def append(self,events):
        if not events:return
        with self.lock:
            for event in events:
                value={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**event}
                if value.get('player_id') in self.names:value['player_name']=self.names[value['player_id']]
                self.stream.write(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n');self.total+=1
            self.stream.flush()
            if self.stream.tell()>self.max_bytes:
                self.stream.close();self.completed.append(self.path);self.part+=1;self._open()
            status={'enabled':True,'events':self.total,'path':self.path.name,'part':self.part,'schema':VERSION}
            tmp=self.folder/'status.tmp';tmp.write_text(json.dumps(status,ensure_ascii=False),'utf8');tmp.replace(self.folder/'status.json')

    def close(self):
        with self.lock:
            if self.stream and not self.stream.closed:self.stream.close()


def register_channel(buffer,offset,schema,fence):
    if schema!=SCHEMA or type(offset)is not int or offset<0 or offset%16:
        raise ValueError('动作观察通道格式无效')
    view=memoryview(buffer).cast('B')
    if offset+BUFFER_BYTES>len(view):raise ValueError('动作观察缓冲区不完整')
    def read(at,size):
        if type(at)is not int or type(size)is not int or at<0 or size<0 or at+size>BUFFER_BYTES:
            raise ValueError('动作观察缓冲区越界')
        return bytes(view[offset+at:offset+at+size])
    channel={'view':view,'offset':offset,'reader':RingReader(read,fence),'fence':fence,'thread':None}
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
        changed=time.monotonic();last_export=0;exported_count=-1;completed_exports=set()
        try:
            while True:
                events=channel['reader'].drain();journal.append(events);now=time.monotonic()
                if events:changed=now
                # Export only a quiet snapshot (pause/menu), away from engine
                # callbacks. A permission/codec/JNI failure cannot affect play.
                if now-changed>=3 and now-last_export>=15 and exported_count!=journal.total:
                    last_export=now
                    try:
                        for completed in journal.completed:
                            if completed not in completed_exports:export_public(completed);completed_exports.add(completed)
                        uri=export_public(journal.path);exported_count=journal.total
                        status={'public_log':uri,'private_file':journal.path.name,'events':journal.total}
                        (journal.folder/'public-export.json').write_text(json.dumps(status,ensure_ascii=False),'utf8')
                    except Exception as error:
                        (journal.folder/'public-export.json').write_text(json.dumps({'private_file':journal.path.name,'export_error':str(error)},ensure_ascii=False),'utf8')
                time.sleep(.05)
        except Exception:
            logging.getLogger(__name__).exception('Action observer stopped; native gameplay retained')
            struct.pack_into('<I',view,at+4,0);fence()
        finally:journal.close()
    thread=threading.Thread(target=worker,name='PlayerActionLog',daemon=True);channel['thread']=thread
    _THREADS.append((channel,journal,thread));thread.start()
