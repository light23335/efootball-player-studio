"""Reuse an imported content library, without its original delta ZIP or scripts."""
from pathlib import Path
import contextlib,copy,csv,hashlib,io,json,struct,uuid,zipfile
from export_payload import FilePayload,metadata
from content_delta import CONTENT,read_catalogue,compact,TABLES,ALIASES
PREFIX='assets/gateway-release/'
STEM=PREFIX+'custom-resources/legends-v10/pc3700_mobile_and'
CPK=PREFIX+'custom-resources/legends-v10/dt870_mobile_and.cpk'
FORMAT='studio-imported-content-materials-v1'

def cache_path(resources,catalogue):
 return Path(resources)/('content-materials-'+hashlib.sha256(compact(catalogue)).hexdigest()[:24]+'.zip')

def retain_materials(apk,library,catalogue=None):
 """Small data/media snapshot; already prepared large containers are referenced."""
 if catalogue is None:
  path=Path(library.resources)/'content-catalogue.json'
  catalogue=json.loads(path.read_text('utf8'))if path.is_file()else{}
 if not catalogue.get('packages'):return None
 target=cache_path(library.resources,catalogue)
 if target.is_file():return target
 temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  with zipfile.ZipFile(apk)as source,zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1)as dest:
   release=json.loads(source.read(PREFIX+'release-manifest.json'));items={}
   for info in source.infolist():
    name=info.filename
    container=name.startswith((PREFIX+'livedata/',PREFIX+'custom-resources/legends-v10/'))and name.endswith(('.pak','.utoc','.ucas'))
    media=name.startswith(('assets/card-designer/backgrounds/','assets/card-designer/background-videos/'))and name.endswith(('.png','.jpg','.webm','.mp4'))
    if not(container or media or name==CPK):continue
    if container:
     n=Path(name);cached=library.containers/(n.stem+'_10_P'+n.suffix)
     if not cached.is_file()or cached.stat().st_size!=info.file_size:raise ValueError('导入内容缓存尚未准备完整：'+n.name)
     from compile_cache import digest_file
     items[name]={'cache':cached.name,'bytes':info.file_size,'crc32':info.CRC,'sha256':digest_file(cached)}
    else:
     raw=source.read(info);dest.writestr(name,raw);items[name]={'member':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
   if CPK not in items or STEM+'.utoc'not in items or STEM+'.ucas'not in items:raise ValueError('当前内容库缺少原生资料或资源容器')
   from personal_source import read
   personal=read(source,release)
   dest.writestr('materials.json',compact({'format':FORMAT,'release_id':release.get('base_release_id',release['release_id']),
     'catalogue':catalogue,'items':items,'personal':personal,'engine_sha256':library.profile['native_engine_sha256']}))
  temporary.replace(target)
 finally:temporary.unlink(missing_ok=True)
 return target

class Overlay:
 """Read-only virtual source. Final APK is written once from the real source."""
 def __init__(self,archive,replacements):self.archive=archive;self.replacements=replacements
 def __getattr__(self,name):return getattr(self.archive,name)
 def payload(self,name):return self.replacements.get(name)
 def namelist(self):return list(dict.fromkeys([*self.archive.namelist(),*self.replacements]))
 def getinfo(self,name):
  if name not in self.replacements:return self.archive.getinfo(name)
  value=self.replacements[name];info=zipfile.ZipInfo(name);info.file_size=value.bytes if isinstance(value,FilePayload)else len(value);info.compress_type=zipfile.ZIP_STORED;return info
 def open(self,name,*args,**kwargs):
  name=name.filename if isinstance(name,zipfile.ZipInfo)else name
  value=self.replacements.get(name)
  if value is None:return self.archive.open(name,*args,**kwargs)
  return value.open()if isinstance(value,FilePayload)else io.BytesIO(value)
 def read(self,name,*args):
  with self.open(name)as stream:return stream.read()

def missing(catalogue,required):
 current={r['package_id']:r['manifest_sha256']for r in catalogue.get('packages',[])}
 for row in required.get('packages',[]):
  if row['package_id']in current and current[row['package_id']]!=row['manifest_sha256']:raise ValueError('同一内容增量编号不同：'+row['package_id'])
 pending={r['package_id']for r in catalogue.get('packages',[])if r.get('pending_entities')}
 return[r['package_id']for r in required.get('packages',[])if r['package_id']not in current or r['package_id']in pending and not r.get('pending_entities')]

def synchronize(archive,library,work,progress=lambda **kw:None):
 path=Path(library.resources)/'content-catalogue.json'
 if not path.is_file():return archive,{},None
 wanted=json.loads(path.read_text('utf8'));previous=read_catalogue(archive);needed=missing(previous,wanted)
 if not needed:return archive,{},None
 progress(message='从当前资料库补齐已导入的内容增量（无需原始增量 ZIP）')
 cached=cache_path(library.resources,wanted)
 if not cached.is_file():
  from apk_sources import recorded
  donor=recorded(library,library.store).get('apk')
  if not donor or not Path(donor).is_file():raise ValueError('此旧资料库尚未保存自动补齐缓存，且当时导入的游戏已不在原位置；请重新导入该游戏库，无需原始增量 ZIP')
  retain_materials(donor,library,wanted)
 work=Path(work)/'content-autofill';work.mkdir()
 with zipfile.ZipFile(cached)as material:
  inventory=json.loads(material.read('materials.json'))
  if inventory.get('format')!=FORMAT or compact(inventory['catalogue'])!=compact(wanted)or inventory['engine_sha256']!=library.profile['native_engine_sha256']:raise ValueError('内容库自动补齐缓存与当前数据库不一致')
  refs={}
  for name,row in inventory['items'].items():
   if 'cache'in row:
    if Path(row['cache']).name!=row['cache']:raise ValueError('内容资源缓存路径无效')
    value=FilePayload.from_path(library.containers/row['cache'])
    if value.bytes!=row['bytes']or metadata(value)['sha256']!=row['sha256']:raise ValueError('已导入的资源缓存校验异常：'+row['cache'])
    refs[name]=value
   else:
    raw=material.read(row['member'])
    if len(raw)!=row['bytes']or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('内容资料缓存校验失败：'+name)
    refs[name]=raw
  from native_cpk import Cpk,unwrap,wrap
  from native_tables import rows
  from native_coaches import COACH
  from content_asset_merge import _selection as select_material_entities
  selected_players,selected_routes,_,_,_,_=select_material_entities(previous,wanted,needed)
  source_cpk=Cpk(archive.read(CPK));donor_cpk=Cpk(refs[CPK]);table_changes={};added_cards=set();identifiers={int(cid)for cid in selected_players}
  new_identifiers=identifiers-{int(r['card_id'])for r in previous.get('players',[])}
  auxiliary={int(r['base_id'])for r in selected_players.values()if str(r.get('base_id','')).isdigit()}
  for route in selected_routes:
   auxiliary.update(int(route[k])for k in('portraitKey','modelNativeId')if str(route.get(k,'')).isdigit())
  for name,(stride,offset)in{**TABLES,COACH:(176,0)}.items():
   if name not in source_cpk.files or name not in donor_cpk.files:continue
   original=source_cpk.read(name);current=rows(unwrap(original),stride,offset,require_sorted=False);donor=rows(unwrap(donor_cpk.read(name)),stride,offset,require_sorted=False)
   allowed={int(c.get('coach_id',c.get('id')))for c in wanted.get('coaches',[])}if name==COACH else identifiers|auxiliary
   for cid in allowed:
    if cid not in donor:continue
    if cid in current:
     # Existing player modifications belong to the selected game, including native cards.
     if cid in new_identifiers and name.endswith('/Player.bin')and current[cid]!=donor[cid]:raise ValueError('内容卡 '+str(cid)+' 在来源游戏中已有不同资料，自动补齐未覆盖；请核对所选游戏库')
     continue
    current[cid]=donor[cid]
    if name.endswith('/Player.bin')and cid in identifiers:added_cards.add(cid)
   raw=b''.join(current[c]for c in sorted(current))
   if raw!=unwrap(original):table_changes[name]=wrap(raw,original)
  original=source_cpk.read(ALIASES)
  parse=lambda raw:list(csv.reader(io.StringIO(raw.decode('utf8'))))
  old=parse(unwrap(original));aliases={r[0]:r[1]for r in old[1:]if len(r)==2}
  import re
  for before,after in parse(unwrap(donor_cpk.read(ALIASES)))[1:]:
   match=re.match(r'^(\d+)(?:_|_l|f)?$',before)
   if match and int(match[1])in identifiers|auxiliary:aliases.setdefault(before,after)
  out=io.StringIO(newline='');writer=csv.writer(out,lineterminator='\r\n');writer.writerow(old[0]);writer.writerows(sorted(aliases.items()))
  if out.getvalue().encode()!=unwrap(original):table_changes[ALIASES]=wrap(out.getvalue().encode(),original)
  cpk=source_cpk.replace(table_changes)if table_changes else source_cpk.raw
  replacements={CPK:cpk,PREFIX+'livedata/dt870_mobile_and.cpk':cpk}
  key=(library.containers/'resource-key.bin').read_bytes()
  if hashlib.sha256(key).hexdigest()!=library.profile['resource_key_sha256']:raise ValueError('内容库资源密钥校验失败')
  from content_asset_merge import merge_material_assets
  native_replacements,asset_report=merge_material_assets(archive,refs,library,key,work,previous,wanted,needed,inventory.get('personal',{}))
  replacements.update(native_replacements)
  required_media=set(asset_report['media_paths'])
  for name,value in refs.items():
   if name not in required_media:continue
   if name not in archive.namelist():replacements[name]=value
   else:
    with archive.open(name)as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if metadata(value)['sha256']!=digest:raise ValueError('新增内容所需素材与来源游戏不同，未覆盖：'+name)
  merged=copy.deepcopy(previous);merged.update(format='studio-content-catalogue-v1',base_version='V17',runtime_abi='v17-content-art/1')
  for kind,keyname in [('packages','package_id'),('players','card_id'),('routes','cardId'),('coaches','coach_id')]:
   rows_by={str(r.get(keyname,r.get('id'))):r for r in previous.get(kind,[])}
   for row in wanted.get(kind,[]):
    key=str(row.get(keyname,row.get('id')))
    if kind=='packages'and key in needed:rows_by[key]=row
    else:rows_by.setdefault(key,row)
   merged[kind]=list(rows_by.values())
  for kind in('card_suites','card_suite_additions'):
   key=lambda r:(str(r['nativeType']),str(r['variant']),r.get('id',''))
   values={key(r):r for r in previous.get(kind,[])}
   for row in wanted.get(kind,[]):values.setdefault(key(row),row)
   merged[kind]=list(values.values())
  replacements[CONTENT]=compact(merged)
  release=json.loads(archive.read(PREFIX+'release-manifest.json'));listed={r['path']:r for r in release['files']}
  for name,value in replacements.items():
   if not name.startswith(PREFIX):continue
   rel=name[len(PREFIX):];row={'path':rel,**metadata(value)}
   if rel in listed:listed[rel].update(row)
   else:release['files'].append(row)
  replacements[PREFIX+'release-manifest.json']=compact(release)
  return Overlay(archive,replacements),replacements,{'packages':needed,'added_cards':len(added_cards),'added_native_chunks':asset_report['added_native_chunks'],'assets':asset_report,'source':'imported-library-cache','original_delta_zip_required':False}
