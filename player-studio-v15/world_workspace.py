"""Local stadium/tournament designs, separate from player projects and saves."""
import copy,hashlib,json,math,os,re,uuid
from pathlib import Path

FORMAT='player-studio-world-workspace'
ASSET=re.compile(r'[a-f0-9]{64}\.(?:png|jpg|jpeg|webp|glb)')


def default_slot(ident):
 return {'stadium_id':ident,'custom_stadium_name':'工坊球场 '+str(ident-100),
  'stadium_color1':37,'stadium_color2':30,'stadium_color3':40,'stadium_color4':40,
  'goalnet_pattern':1,'goalnet_color1':40,'goalnet_color2':40,'pitch_pattern':1,
  'entrance_set':1,'bill_set':1,'pitchside_objects':[0]*6,'goal_effect1':0,
  'goal_effect2':0,'kickoff_effect':0,'objects':[None]*6,'stand_tifo':None}


def default():return {'format':FORMAT,'version':1,'stadium':{'enabled':False,'unlock_all':True,'selected':101,'slots':[default_slot(i)for i in(101,102,103)]},'tournaments':[]}


def unlock_catalogue():
 from studio_resources import bundled_resources
 return json.loads((bundled_resources()/'native-stadium-catalogue.json').read_text('utf8'))


def transform(value):
 if not isinstance(value,dict):raise ValueError('装置变换格式无效')
 out={'offset':value.get('offset',[0,0,0]),'rotation':value.get('rotation',0),'scale':value.get('scale',1)}
 if not isinstance(out['offset'],list)or len(out['offset'])!=3:raise ValueError('装置偏移需要 X、Y、Z 三项')
 for v in [*out['offset'],out['rotation'],out['scale']]:
  if type(v)not in(int,float)or not math.isfinite(v):raise ValueError('装置变换必须是有限数值')
 if any(abs(v)>100 for v in out['offset'])or not -360<=out['rotation']<=360 or not .01<=out['scale']<=100:raise ValueError('装置偏移 ±100 米，旋转 ±360°，缩放 0.01–100')
 return out


def normalize(value,assets=None,compile=False):
 if not isinstance(value,dict)or value.get('format')!=FORMAT or value.get('version')!=1:raise ValueError('球场与赛事工作区版本无效')
 if len(json.dumps(value,ensure_ascii=False))>4*1024*1024:raise ValueError('球场与赛事资料过大')
 out=copy.deepcopy(value);s=out.get('stadium')
 if not isinstance(s,dict)or type(s.get('enabled'))is not bool or s.get('selected')not in(101,102,103):raise ValueError('球场设置无效')
 s.setdefault('unlock_all',True)
 if type(s['unlock_all'])is not bool:raise ValueError('解锁球场资源须为开关')
 if not isinstance(s.get('slots'),list)or sorted(r.get('stadium_id',0)for r in s['slots'])!=[101,102,103]:raise ValueError('球场需要三个独立原生槽位')
 limits={**{'stadium_color'+str(i):63 for i in range(1,5)},'goalnet_pattern':7,'goalnet_color1':63,'goalnet_color2':63,
         'pitch_pattern':15,'entrance_set':255,'bill_set':255,'goal_effect1':255,'goal_effect2':255,'kickoff_effect':255}
 for row in s['slots']:
  row.setdefault('stand_tifo',None)
  stand=row['stand_tifo']
  if stand is not None:
   if not isinstance(stand,dict)or stand.get('kind')!='stand'or not re.fullmatch(r'[a-f0-9]{64}\.(?:png|jpg|jpeg|webp)',stand.get('asset','')):raise ValueError('看台 TIFO 图片引用无效')
   if assets is not None and not(Path(assets)/stand['asset']).is_file():raise ValueError('看台 TIFO 图片缺失')
   if not re.fullmatch(r'[a-f0-9]{64}\.glb',stand.get('preview_asset','')):raise ValueError('看台 TIFO 预览引用无效')
   stand['name']=str(stand.get('name')or'看台 TIFO')[:80];stand['transform']=transform({})
   from stadium_assets import stand_layout
   if stand.get('layout')=='mosaic':stand.pop('preview_revision',None)
   stand['layout']=stand_layout(stand.get('layout','poster'))
  row['custom_stadium_name']=str(row.get('custom_stadium_name','')).strip()[:24]
  if '\0'in row['custom_stadium_name']:raise ValueError('球场名称不能含空字符')
  for key,high in limits.items():
   if type(row.get(key))is not int or not 0<=row[key]<=high:raise ValueError('球场参数 '+key+' 超出原生范围')
  if not isinstance(row.get('pitchside_objects'),list)or len(row['pitchside_objects'])!=6 or any(type(v)is not int or not 0<=v<=255 for v in row['pitchside_objects']):raise ValueError('场边原生对象需要六个有效槽位')
  if not isinstance(row.get('objects'),list)or len(row['objects'])!=6:raise ValueError('自制装置需要六个独立槽位')
  for obj in row['objects']:
   if obj is None:continue
   if not isinstance(obj,dict)or obj.get('kind')not in('image','model'):raise ValueError('自制装置类型无效')
   name=obj.get('asset','')
   if not isinstance(name,str)or not ASSET.fullmatch(name):raise ValueError('自制装置素材引用无效')
   if assets is not None and not(Path(assets)/name).is_file():raise ValueError('自制装置素材缺失：'+str(obj.get('name')or name))
   preview=obj.get('preview_asset')
   if preview is not None and(not isinstance(preview,str)or not re.fullmatch(r'[a-f0-9]{64}\.glb',preview)):raise ValueError('装置预览资源引用无效')
   obj['name']=str(obj.get('name')or'TIFO / 装置')[:80];obj['transform']=transform(obj.get('transform',{}))
   for k,d in [('width',12),('height',8)]:
    v=obj.get(k,d)
    if type(v)not in(int,float)or not math.isfinite(v)or not .1<=v<=100:raise ValueError('TIFO 尺寸范围为 0.1–100 米')
    obj[k]=v
 t=out.get('tournaments')
 if not isinstance(t,list)or len(t)>32:raise ValueError('最多保存 32 个锦标赛')
 seen=set()
 for row in t:
  ident=str(uuid.UUID(row['uuid']))
  if ident in seen:raise ValueError('锦标赛身份重复')
  seen.add(ident)
  if type(row.get('enabled',False))is not bool:raise ValueError('锦标赛启用状态无效')
  row.setdefault('include_diy',True);row.setdefault('auto_coaching',True)
  from tournament_rules import difficulty,normalize_cover,match_minutes
  if 'cover'in row:
   row['cover']=normalize_cover(row['cover'])
   if assets is not None and row['cover']and not(Path(assets)/row['cover']['asset_id']).is_file():raise ValueError('锦标赛封面图片缺失，请重新选择图片')
  # Compiled artwork belongs to an exported APK, never a local design.
  row.pop('cover_artwork',None)
  row['difficulty']=difficulty(row);row.pop('division',None)
  row['match_minutes']=match_minutes(row)
  for i,stage in enumerate(row.get('stages',[])):
   kind=stage.get('type','knockout');stage.setdefault('uuid',str(uuid.uuid5(uuid.UUID(ident),f'stage:{i}:{kind}')))
   defaults={'name':{'groups':'小组赛','league':'联赛阶段','playoff':'附加赛','knockout':'淘汰赛'}.get(kind,kind),
    'groups':1,'cycles':1,'rounds':0,'advance_per_group':2,'playoff_per_group':0,'advance':1,'legs':1,
    'away_goals':False,'away_goals_extra_time':False,'extra_time':True,'penalties':True,'neutral_final':True,'round_overrides':{}}
   for key,default_value in defaults.items():stage.setdefault(key,default_value)
  if compile and row.get('enabled'):
   from tournament_rules import normalize as rules
   checked=rules(row);row.clear();row.update(checked)
 return out


def catalogue(library):
 from native_stadium_table import read
 assets=library.face_assets();base='/Game/Assets/bg/AdditionalAsset/Blueprint/DT_CS_PitchsideObject'
 rows=read(assets.get(base)[0])[3]
 return {'objects':[{'id':int(k),'name':v['asset'].rsplit('/',1)[-1].split('.')[0],
         'path':v['asset'].rsplit('.',1)[0],'kind':'level'if v['level']else'model'}for k,v in rows.items()if k.isdigit()],
         'anchors':unlock_catalogue().get('anchors',[]),'materials':unlock_catalogue()['assets'],
         'placement':'native anchor local; no full-stadium import'}


def team_catalogue(library,store,document=None):
 """Read the imported APK's declarative league registry, never execute it."""
 from apk_sources import recorded
 import zipfile
 identities=library.identities();teams=copy.deepcopy(identities['team']);known={int(r['id'])for r in teams};value=None
 path=library.resources/'team-leagues.json'
 if path.is_file():value=json.loads(path.read_text('utf8'))
 else:
  source=recorded(library,store).get('apk')
  if source and Path(source).is_file():
   with zipfile.ZipFile(source)as archive:
    member='assets/gateway-release/outputs/reference/ziru-data/ml_competition_registry.json'
    if member in archive.namelist():
     if archive.getinfo(member).file_size>2*1024*1024:raise ValueError('联赛目录过大')
     value=json.loads(archive.read(member))
 labels={'English League':'英格兰联赛','Italian League':'意大利联赛','Spanish League':'西班牙联赛',
  'French League':'法国联赛','German League':'德国联赛','Portuguese League':'葡萄牙联赛','Dutch League':'荷兰联赛',
  'English 2nd Division':'英格兰乙级联赛','Italian 2nd Division':'意大利乙级联赛','Spanish 2nd Division':'西班牙乙级联赛'}
 leagues=[]
 for key,row in (value or{}).get('competitions',{}).items():
  ids=list(dict.fromkeys(int(v)for v in row.get('team_ids',[])if type(v)is int and v in known))
  if ids:leagues.append({'id':str(key),'name':labels.get(row.get('name'),row.get('name')or str(key)),'name_en':row.get('name',''),'team_ids':ids})
 references=national_references(library,identities)
 national=national_teams(library,identities,references)
 native_by_nation={}
 for team,nation in national.items():
  if int(team)in references:native_by_nation.setdefault(nation,[]).append(int(team))
 # Only a unique ID actually referenced as a national team is canonical.
 # If an imported source is ambiguous, omit that country from random draws
 # instead of guessing by label, numeric ID order or a preset squad alias.
 canonical={nation:ids[0]for nation,ids in native_by_nation.items()if len(ids)==1}
 families={}
 for row in teams:
  nation=national.get(str(row['id']))
  if nation is not None:
   native=int(row['id'])in references
   row.update(national_team_nation_id=nation,national_team_kind='native'if native else'squad_alias'if nation in native_by_nation else'country_mapped',
              national_mapping_source='verified_native_reference'if native else'exact_unique_country_name',
              random_national_team_id=canonical.get(nation))
   families.setdefault(nation,[]).append(row)
 for family in families.values():
  for row in family:
   if row['national_team_kind']=='country_mapped':row['selection_label']=row['name']+'（国籍映射编号，未验证原生引用）'
   elif len(family)>1:row['selection_label']=row['name']+('（国家队编号）'if int(row['id'])in references else'（队套编号，同国家球员池）')
 if national:leagues.insert(0,{'id':'national','name':'国家队','name_en':'National teams','team_ids':sorted(canonical.values())})
 availability=team_availability(library,store,[r['id']for r in teams],document,nations=national)
 for row in teams:row['tournament_eligibility']=availability[str(row['id'])]
 return {'teams':teams,'leagues':leagues,'national_team_nations':national}


def national_references(library,identities=None):
 """Exact native national IDs referenced by player definitions."""
 import contextlib
 referenced=set()
 with contextlib.closing(library.db())as db:
  for raw, in db.execute('select payload from players'):
   ident=json.loads(raw).get('initial_base_national_team_id')
   if type(ident)is int and ident>0:referenced.add(ident)
 return referenced


def national_teams(library,identities=None,references=None):
 """Reliable Country membership, independent of native team-ID verification.

 Country IDs differ from team IDs. Do not assume they share an ID or use a
 club's country to choose players. Ambiguous names are not guessed.
 """
 identities=identities or library.identities();by_name={}
 for r in identities['nation']:
  key=str(r.get('name_en')or'').casefold().strip()
  if key:by_name.setdefault(key,set()).add(int(r['id']))
 out={}
 for r in identities['team']:
  candidates=by_name.get(str(r.get('name_en')or'').casefold().strip(),set())
  if len(candidates)==1:out[str(r['id'])]=next(iter(candidates))
 return out


def selection_document(library,store=None,document=None):
 """Read selection inputs only; never reserve identities or train owned cards."""
 out=copy.deepcopy(document)if document is not None else{}
 out['tournament_national_team_nations']=national_teams(library)
 if document is not None:return out
 out.setdefault('players',[])
 # Imported personal definitions preserve their original-person bindings.
 if store is not None:
  from apk_sources import recorded
  import zipfile
  source=recorded(library,store).get('apk')
  member='assets/gateway-release/custom-resources/personal-player-studio/players.json'
  if source and Path(source).is_file():
   with zipfile.ZipFile(source)as archive:
    if member in archive.namelist():
     if archive.getinfo(member).file_size>256*1024*1024:raise ValueError('锦标赛来源球员定义过大')
     inherited=json.loads(archive.read(member))
     for key in('players','native_player_catalogue','catalogue_recycle_bin','division_squads'):
      if key in inherited:out[key]=copy.deepcopy(inherited[key])
  projects={}
  saved=getattr(store,'saved_player',None)
  if callable(saved):
   for path in sorted((store.root/'players').glob('*.json')):
    try:project=saved(path.stem)['project']
    except (ValueError,KeyError,OSError):continue
    projects[project['package_id']]=copy.deepcopy(project)
  current=getattr(store,'project',None)
  if isinstance(current,dict)and current.get('package_id')and current.get('identity',{}).get('name','').strip():
   projects[current['package_id']]=copy.deepcopy(current)
  out['tournament_local_projects']=list(projects.values())
 return out


def team_availability(library,store,team_ids,document=None,*,nations=None):
 """The same dynamic pool inspection powers warnings and all random draws."""
 from tournament_eligibility import load_eligibility_index,eligible_teams
 doc=selection_document(library,store,document)
 if nations is not None:doc['tournament_national_team_nations']=nations
 index=load_eligibility_index(library,doc);result={str(team):{}for team in team_ids}
 for include,key in((True,'with_diy'),(False,'without_diy')):
  rows={side:eligible_teams(library,doc,team_ids,include_diy=include,cpu=cpu,index=index)
        for side,cpu in(('cpu',True),('player',False))}
  for team in result:result[team][key]={side:values[team]for side,values in rows.items()}
 return result


def selection_warnings(library,store,tournaments,document=None):
 """Advisory only: no team removal, design changes or export prohibition."""
 ids=sorted({int(team)for t in tournaments for team in t.get('team_ids',[])})
 if not ids:return[]
 availability=team_availability(library,store,ids,document);warnings=[]
 for t in tournaments:
  key='with_diy'if t.get('include_diy',True)else'without_diy'
  for team in t.get('team_ids',[]):
   for side,row in availability[str(team)][key].items():
    if row.get('mode')=='strict'and not row.get('local_pending_export'):continue
    warnings.append({'tournament_uuid':t['uuid'],'tournament_name':t.get('name',''),
        'team_id':team,'side':side,'include_diy':t.get('include_diy',True),
        'source_people':row.get('source_people',row.get('real_people',0)),
        'current_people':row.get('current_people',row.get('real_people',0)),
        'local_pending_export':row.get('local_pending_export',0),'mode':row.get('mode'),
        'reasons':row.get('reasons',[]),
        'message':row.get('warning')or'本地 DIY 需勾选实装后才会进入游戏球队池',
        'export_blocked':False})
 return warnings


def native_preview(store,library,ident):
 """Portable static silhouette, not a rendered native material or stadium."""
 import numpy as np
 from native_static_mesh import find_lods
 from stadium_assets import preview_glb
 from PIL import Image
 if type(ident)is not int:raise ValueError('原生装置编号无效')
 row=next((r for r in catalogue(library)['objects']if r['id']==ident),None)
 if not row:raise ValueError('装置不在当前资源表中')
 if row['kind']=='level':raise ValueError('此对象是动态组合装置，请在游戏球场编辑页面查看')
 raw,_=library.face_assets().get(row['path']);lod=find_lods(raw)[0]
 if lod['vertices']>200000:raise ValueError('此原生装置较复杂，请在游戏内查看')
 positions=np.frombuffer(lod['positions'],dtype='<f4').reshape(-1,3)[:,[0,2,1]]/100
 idx=lod['indices'][0];faces=np.frombuffer(idx['data'],dtype='<u4'if idx['width']==4 else'<u2').reshape(-1,3)[:,::-1]
 normals=np.zeros_like(positions);cross=np.cross(positions[faces[:,1]]-positions[faces[:,0]],positions[faces[:,2]]-positions[faces[:,0]])
 for i in range(3):np.add.at(normals,faces[:,i],cross)
 length=np.linalg.norm(normals,axis=1);normals[length>1e-10]/=length[length>1e-10,None];normals[length<=1e-10]=[0,1,0]
 result=preview_glb(positions,normals,np.zeros((len(positions),2)),faces,Image.new('RGBA',(4,4),(170,195,200,255)))
 name=hashlib.sha256(result).hexdigest()+'.glb';target=store.root/'assets'/name
 if not target.exists():target.write_bytes(result)
 return {'preview_asset':name,'kind':'model','transform':transform({}),'name':row['name'],'preview':'native static shape only; independent renderer, no native material or stadium'}


def load(store):
 p=store.root/'world-workspace.json'
 return normalize(json.loads(p.read_text('utf8')))if p.is_file()else default()


def save(store,value):
 out=normalize(value,store.root/'assets');p=store.root/'world-workspace.json'
 with store.lock:
  temp=p.with_name('.world-'+uuid.uuid4().hex)
  try:
   with temp.open('w',encoding='utf8')as f:json.dump(out,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
   temp.replace(p)
  finally:temp.unlink(missing_ok=True)
 return {'saved':True,'document':out}


def geometry(store,obj):
 from stadium_assets import flatten,tifo
 from PIL import Image
 source=store.root/'assets'/obj['asset']
 if obj['kind']=='image':
  with Image.open(source)as image:return tifo(image,obj['width'],obj['height'])
 return flatten(source.read_bytes())


def import_asset(store,body):
 from stadium_assets import preview_glb
 path=Path(body.get('path',''));kind='image'if path.suffix.lower()in('.png','.jpg','.jpeg','.webp')else'model'
 if kind=='model'and path.suffix.lower()!='.glb':raise ValueError('装置使用 GLB 2.0，图片 TIFO 使用 PNG/JPG/WebP')
 result=store.import_asset(path,kind)
 obj={'kind':kind,'asset':result['id'],'name':path.stem,'width':12,'height':8,'transform':transform({})}
 values=geometry(store,obj);raw=preview_glb(*values);name=hashlib.sha256(raw).hexdigest()+'.glb'
 (store.root/'assets'/name).write_bytes(raw)
 obj['preview_asset']=name
 return {'object':obj,'vertices':len(values[0]),'triangles':len(values[3]),'preview_url':'/assets/'+name,
         'preview':'independent GLB; native anchor positions are schematic, not a game screenshot'}


def import_stand(store,library,body):
 from stadium_assets import stand_image,stand_preview,STAND_PREVIEW_REVISION
 path=Path(body.get('path',''))
 if path.suffix.lower()not in('.png','.jpg','.jpeg','.webp'):raise ValueError('看台 TIFO 请上传 PNG、JPG 或 WebP 图片')
 result=store.import_asset(path,'image');raw=stand_preview(library.face_assets(),stand_image(store.root/'assets'/result['id']))
 name=hashlib.sha256(raw).hexdigest()+'.glb';(store.root/'assets'/name).write_bytes(raw)
 return {'object':{'kind':'stand','asset':result['id'],'name':path.stem,'layout':'poster','preview_asset':name,'preview_revision':STAND_PREVIEW_REVISION+':poster','transform':transform({})},'preview':'native giant poster image surface, independent renderer; default other components retained'}


def refresh_stand_previews(store,library,document):
 """Regenerate obsolete previews from retained images, never replace designs."""
 from stadium_assets import stand_image,stand_preview,stand_layout,STAND_PREVIEW_REVISION
 for slot in document['stadium']['slots']:
  obj=slot.get('stand_tifo')
  if not obj:continue
  layout=stand_layout(obj.get('layout','poster'));obj['layout']=layout;revision=STAND_PREVIEW_REVISION+':'+layout
  if obj.get('preview_revision')==revision:continue
  source=store.root/'assets'/obj['asset']
  if not source.is_file():continue
  raw=stand_preview(library.face_assets(),stand_image(source,layout));name=hashlib.sha256(raw).hexdigest()+'.glb'
  (store.root/'assets'/name).write_bytes(raw);obj.update(preview_asset=name,preview_revision=revision)
 return document


def compile_stadium(store,library,document):
 from native_art import logical_package
 from native_stadium_table import read,append
 from stadium_assets import compile_object
 value=normalize(document,store.root/'assets',compile=True);stadium=value['stadium']
 runtime={'enabled':stadium['enabled'],'unlock_all':stadium['unlock_all'],'selected':stadium['selected'],'slots':[],'custom_assets':[]};art=[];reports=[]
 if not stadium['enabled']:return art,runtime,{'enabled':False}
 assets=library.face_assets();base='/Game/Assets/bg/AdditionalAsset/Blueprint/DT_CS_PitchsideObject'
 composite='/Game/Assets/bg/AdditionalAsset/Table/CDT_CS_PitchsideObject'
 tables={p:assets.get(p)for p in(base,base+'_High',composite,composite+'_High')}
 occupied=set().union(*({int(k)for k in read(raw)[3]if k.isdigit()}for raw,meta in tables.values()))
 # Stable paths retain their IDs across reordered/removed objects. Never
 # reclaim another path's old ID: append-only tables may still reference it.
 existing={}
 for raw,meta in tables.values():
  for key,row in read(raw)[3].items():
   if row['asset'].startswith('/Game/PlayerStudio/Stadium/')and key.isdigit():
    path=row['asset'].rsplit('.',1)[0];ident=int(key)
    if path in existing and existing[path]!=ident:raise ValueError('球场高低画质对象编号不一致：'+path)
    existing[path]=ident
 available=iter(i for i in range(200,256)if i not in occupied);entries={}
 for slot in stadium['slots']:
  native={k:copy.deepcopy(v)for k,v in slot.items()if k not in('objects','stand_tifo')};native['has_invalid_assets']='NO'
  for index,obj in enumerate(slot['objects']):
   if obj is None:continue
   try:
    geometry_data=geometry(store,obj);ident=f'S{slot["stadium_id"]}_P{index+1}'
    packages,path,report=compile_object(assets,geometry_data,ident,obj['transform'])
    row_id=existing[path]if path in existing else next(available)
    entries[row_id]=path;native['pitchside_objects'][index]=row_id
    runtime['custom_assets'].append({'stadium_asset_type':'OBJECT','stadium_asset_id':row_id,'stadium_asset_name':obj['name']})
    art.extend(packages);reports.append(dict(report,name=obj['name'],stadium_id=slot['stadium_id'],slot=index+1,row_id=row_id))
   except (ValueError,OSError,KeyError,StopIteration)as e:raise ValueError(f'球场 {slot["custom_stadium_name"]}／装置 {index+1} {obj["name"]}：{e}')from e
  runtime['slots'].append(native)
 for path,(raw,meta)in tables.items():
  result,report=append(raw,entries);art.append((path,result,meta))
 from stadium_assets import compile_stand_tifos
 stand_art,stand_reports=compile_stand_tifos(assets,store,stadium,runtime);art.extend(stand_art)
 # An original soft reference must resolve to the changed native table, not
 # an older duplicate from the base container. Include the entrance table in
 # the same stock-container replacement path as the pitchside object tables.
 native_tables=list(tables)+[p for p,_,_ in stand_art if '/Blueprint/DT_CS_'in p or '/Table/CDT_CS_'in p]
 return art,runtime,{'enabled':True,'objects':reports,'stand_tifos':stand_reports,'native_anchor_count':6,'native_table_paths':native_tables,'in_game_tested':False}
