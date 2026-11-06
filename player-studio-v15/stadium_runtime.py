"""Seed native custom-stadium slots without replacing original stadium logic."""
import copy,hashlib,json,threading

_LOCK=threading.RLock()
KEY='player_studio_stadium_revision_v1'


def asset_key(asset):
 if not isinstance(asset,dict)or type(asset.get('stadium_asset_id'))is not int or asset['stadium_asset_id']<0 or not isinstance(asset.get('stadium_asset_type'),str)or not asset['stadium_asset_type']:raise ValueError('球场持有资源格式无效，原记录保留')
 return asset['stadium_asset_type'],asset['stadium_asset_id']


OWNED_KEY='stadium_asset_unlocked_v1'


def owned_assets(conn,inherited=()):
 row=conn.execute('select value from meta where key=?',(OWNED_KEY,)).fetchone();saved=json.loads(row[0])if row else[]
 if not isinstance(saved,list):raise ValueError('球场持有资源不是列表，原记录保留')
 owned={}
 for a in [*(inherited or[]),*saved]:
  k=asset_key(a);owned[k]={**owned.get(k,{}),**copy.deepcopy(a)}
 return list(owned.values())


def unlock(conn,value,inherited=()):
 """Typed ownership, matching V22. No coins, slot edits or one-shot marker."""
 catalog=value.get('unlock_catalogue')or{}
 additions=(catalog.get('assets',[])if value.get('unlock_all')else[])+(value.get('custom_assets',[])if value.get('enabled')else[])
 if not additions:return None
 key=catalog.get('owned_key')
 if key!=OWNED_KEY:raise ValueError('球场资源持有记录接口不符')
 conn.execute('SAVEPOINT studio_stadium_unlock')
 try:
  saved=owned_assets(conn);owned={asset_key(a):a for a in owned_assets(conn,inherited)}
  for a in additions:
   k=asset_key(a)
   if k not in owned:owned[k]=copy.deepcopy(a)
  result=list(owned.values())
  if saved!=result:conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',(key,json.dumps(result,ensure_ascii=False)))
  conn.execute('RELEASE studio_stadium_unlock');return result
 except BaseException:
  conn.execute('ROLLBACK TO studio_stadium_unlock');conn.execute('RELEASE studio_stadium_unlock');raise


def validate_slot(slot):
 """V22's verified ranges, including effect IDs31/32/33 and projections64."""
 import custom_stadium as native
 if not isinstance(slot,dict)or slot.get('stadium_id')not in(101,102,103):raise ValueError('球场槽位无效')
 defaults={'stadium_color1':37,'stadium_color2':30,'stadium_color3':40,'stadium_color4':40,'goalnet_pattern':1,
  'goalnet_color1':40,'goalnet_color2':40,'pitch_pattern':1,'entrance_set':1,'bill_set':1,'goal_effect1':0,'goal_effect2':0,'kickoff_effect':0}
 limits={**{k:63 for k in defaults if 'color'in k},'goalnet_pattern':7,'pitch_pattern':15}
 out={'stadium_id':slot['stadium_id'],'custom_stadium_name':native._name(slot.get('custom_stadium_name','')),'has_invalid_assets':'NO'}
 for key,default in defaults.items():out[key]=native._int(slot.get(key,default),0,limits.get(key,255),key)
 objects=slot.get('pitchside_objects',[0]*6)
 if not isinstance(objects,list)or len(objects)!=6:raise ValueError('装置位需要六个整数')
 out['pitchside_objects']=[native._int(v,0,255,'pitchside_objects')for v in objects]
 return out


def apply(conn,document):
 value=document.get('stadium')or{}
 if not value.get('enabled'):return False
 # Ownership changes must never re-seed the three slots and erase in-game edits.
 seeded={k:value[k]for k in ('enabled','selected','slots')}
 revision=hashlib.sha256(json.dumps(seeded,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 row=conn.execute('select value from meta where key=?',(KEY,)).fetchone()
 if row and row[0]==revision:return False
 import custom_stadium
 native=custom_stadium.state(conn);before=copy.deepcopy(native)
 by_id={r['stadium_id']:r for r in native['slots']}
 for slot in value['slots']:by_id[slot['stadium_id']]=custom_stadium.validate_slot(slot)
 native.update(slots=[by_id[i]for i in(101,102,103)],selected=value['selected'])
 with conn:
  conn.execute('insert or ignore into meta values(?,?)',(KEY+':backup:'+revision,json.dumps(before,ensure_ascii=False)))
  custom_stadium.save(conn,native)
  conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',(KEY,revision))
 return True


def install(document,logic):
 if logic is None:return
 cls=type(logic);original=cls.handle
 if getattr(original,'_studio_stadium',False):return
 import custom_stadium
 custom_stadium.validate_slot=validate_slot
 def handle(self,command,request):
  with _LOCK:apply(self.conn,document())
  out=original(self,command,request)
  if isinstance(out,dict)and out.get('result')=='NOERR':
   entry=out.get('entry_info')
   with _LOCK:
    if command in('CMD_LOGIN','CMD_LOGINBACKUP'):
     unlock(self.conn,document().get('stadium')or{},entry.get('stadium_asset_unlocked_list',[])if isinstance(entry,dict)else[])
    # Native pages can request ownership again after login. Never replace it
    # with the empty list captured in an old V17 response template.
    if isinstance(entry,dict):entry['stadium_asset_unlocked_list']=owned_assets(self.conn,entry.get('stadium_asset_unlocked_list',[]))
    if 'stadium_asset_unlocked_list'in out:out['stadium_asset_unlocked_list']=owned_assets(self.conn,out['stadium_asset_unlocked_list'])
  return out
 handle._studio_stadium=True;cls.handle=handle
