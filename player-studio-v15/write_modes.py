"""Explicit source-aware full/incremental selection. APK metadata is data only."""
from pathlib import Path
import copy,hashlib,json,re,threading,zipfile
import personal_source

RELEASE='assets/gateway-release/release-manifest.json'
DESIGN_VERSION=1
_ASSETS={}
_LOCK=threading.Lock()
EDITOR_FIELDS={'studio_version','game_platform','status','editor_ready','preview','custom_coaches','project_import'}

def mode(value):
    if value not in ('full','incremental'):raise ValueError('请选择全量模式或增量模式')
    return value

def encoded(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()

def asset_hashes(value,store):
    from compile_cache import assets_in,digest_file
    result={}
    for name in assets_in(value):
        path=store.root/'assets'/name
        if not path.is_file():result[name]=name.split('.')[0];continue
        stat=path.stat();key=(str(path),stat.st_size,stat.st_mtime_ns)
        with _LOCK:hit=_ASSETS.get(key)
        if hit is None:
            hit=digest_file(path)
            with _LOCK:
                if len(_ASSETS)>512:_ASSETS.clear()
                _ASSETS[key]=hit
        result[name]=hit
    return result

def design(kind,value,store):
    data={k:v for k,v in value.items()if k not in EDITOR_FIELDS}
    if kind=='coaches':data.pop('_compiled_link_ids',None)
    return hashlib.sha256(encoded({'version':DESIGN_VERSION,'kind':kind,'value':data,'assets':asset_hashes(data,store)})).hexdigest()

def designs(projects,coaches,packs,store):
    return {'version':DESIGN_VERSION,**{kind:{row['package_id'if kind=='players'else'uuid']:design(kind,row,store)for row in values}
            for kind,values in [('players',projects),('coaches',coaches),('packs',packs)]}}

def requirements(library):
    path=Path(library.resources)/'content-catalogue.json'
    catalogue=json.loads(path.read_text('utf8'))if path.is_file()else{}
    return {'release_id':library.profile['release_id'],'packages':catalogue.get('packages',[])}

def compatible(archive,release,required):
    if not required:return
    if isinstance(required,str):required={'release_id':required}
    family=lambda value:str(value).split('-studio-',1)[0]
    if family(release.get('base_release_id')or release.get('release_id'))!=family(required['release_id']):
        raise ValueError('写入来源与当前导入的数据库不兼容，请先导入此游戏版本的数据库')
    from content_delta import read_catalogue
    packages={p['package_id']:p.get('manifest_sha256')for p in read_catalogue(archive).get('packages',[])}
    if any(p['package_id']in packages and packages[p['package_id']]!=p.get('manifest_sha256')for p in required.get('packages',[])):
        raise ValueError('来源游戏与当前库的同一内容增量编号不同，未覆盖现有内容')

def source(path,release_id=None):
    if not path:raise ValueError('增量模式请先选择当前使用的游戏主程序 APK；PC 可选择上次成功生成的游戏 APK')
    p=Path(path).absolute()
    if not p.is_file():raise ValueError('游戏主程序 APK 不存在或读取授权已失效，请重新选择')
    with zipfile.ZipFile(p)as archive:
        if RELEASE not in archive.namelist():raise ValueError('请选择游戏主程序 APK，不是离线资源 APK')
        release=json.loads(archive.read(RELEASE))
        compatible(archive,release,release_id)
        doc=personal_source.read(archive,release)
        from content_autofill import missing
        from content_delta import read_catalogue
        pending=missing(read_catalogue(archive),release_id)if isinstance(release_id,dict)else[]
    stat=p.stat();token=hashlib.sha256(encoded([str(p),stat.st_size,stat.st_mtime_ns,doc.get('revision'),pending])).hexdigest()
    return doc,{'path':str(p),'token':token,'players':len(doc.get('players',[])),
                'coaches':len(doc.get('coaches',[])),'packs':len(doc.get('packs',[])),
                'designs_available':doc.get('write_designs',{}).get('version')==DESIGN_VERSION,'auto_content_packages':pending}

def legacy_unchanged(project,definition,store,document=None):
    """Positive exact matches only; lack of old metadata never means unchanged."""
    expected=definition.get('owned',{}).get('_personal_design_revision')
    if not expected:return False
    hashes=asset_hashes(project,store)
    if any(digest!=name.split('.')[0]for name,digest in hashes.items()):return False
    candidate=copy.deepcopy(project)
    active={int(v)for v in candidate.get('booster_ids',[])}
    candidate['custom_boosters']=[b for b in candidate.get('custom_boosters',[])if b['id']in active]
    remapped=copy.deepcopy(candidate);mapping={}
    for booster in remapped.get('custom_boosters',[]):
        native=(document or{}).get('editor_registries',{}).get('boosters',{}).get(booster.get('uuid'))
        if native is not None:mapping[booster['id']]=int(native);booster['id']=int(native)
    remapped['booster_ids']=[mapping.get(v,v)for v in remapped.get('booster_ids',[])]
    versions=list(dict.fromkeys([candidate.get('studio_version'),*[f'2.1.{n}'for n in range(7)],'2.1','2.0.6','2.0.5','2.0.4','2.0.3','2.0']))
    for value in (candidate,remapped):
        for version in versions:
            value['studio_version']=version
            if hashlib.sha256(encoded(value)+b':v16-compiler-1.9.2').hexdigest()==expected:return True
    return False

def statuses(kind,values,doc,store):
    old={row['identity']['package_id']if kind=='players'else row['uuid']:row for row in doc.get(kind,[])}
    fingerprints=doc.get('write_designs',{})
    recorded=fingerprints.get(kind,{})if fingerprints.get('version')==DESIGN_VERSION else {}
    result={}
    for value in values:
        uid=value['package_id'if kind=='players'else'uuid']
        if uid not in old:state='new'
        elif uid in recorded:state='unchanged'if design(kind,value,store)==recorded[uid]else'modified'
        elif kind=='players'and legacy_unchanged(value,old[uid],store,doc):state='unchanged'
        else:state='unverified'
        result[uid]=state
    return result

def retained(doc,writing,selected,compiled):
    result=copy.deepcopy(doc)
    for kind in ('players','coaches','packs'):
        result[kind]=[r for r in doc.get(kind,[])if writing=='incremental'or
            (r['identity']['package_id']if kind=='players'else r['uuid'])in selected[kind]-compiled[kind]]
    keep_coaches={r['uuid']for r in result.get('coaches',[])}
    result['coach_models']=[r for r in doc.get('coach_models',[])if r['uuid']in keep_coaches]
    if writing=='full':
        links={int(v)for c in result['coaches']for v in c.get('payload',{}).get('ability_id',[])[2:]if v}
        result['coach_links']=[r for r in doc.get('coach_links',[])if int(r['id'])in links]
        wanted={str(p.get('agent',{}).get(key,''))for p in result['packs']for key in ('banner_file_c_name','banner_file_d_name')}
        result['pack_covers']={k:v for k,v in doc.get('pack_covers',{}).items()if k in wanted}
        booster_ids={str(v)for p in result['players']for v in p.get('base_parameters',[])[144:147]}
        result['preview_boosters']={k:v for k,v in doc.get('preview_boosters',{}).items()if k in booster_ids}
    return result

def final_designs(old,new,final):
    result={'version':DESIGN_VERSION}
    for kind in ('players','coaches','packs'):
        keys={r['identity']['package_id']if kind=='players'else r['uuid']for r in final[kind]}
        previous=old.get(kind,{})if old.get('version')==DESIGN_VERSION else {}
        result[kind]={uid:digest for uid,digest in {**previous,**new.get(kind,{})}.items()if uid in keys}
    return result

def refresh_packs(packs,old_players,players):
    by_old={str(cid):p['identity']['package_id']for p in old_players for cid in
            {p['identity']['card_id'],*p['identity'].get('previous_card_ids',[])}}
    by_uuid={p['identity']['package_id']:p for p in players};result=copy.deepcopy(packs)
    for pack in result:
        for member in pack['members']:
            uid=by_old.get(str(member['card_id']))
            if not uid:continue
            if uid not in by_uuid:raise ValueError(pack['name']+'：卡包引用了未勾选的旧自建球员，请同时勾选该球员或修改卡包')
            d=by_uuid[uid];payload=copy.deepcopy(d['owned']);cid=d['identity']['card_id']
            payload['gameplayer_id']={'id':cid,'serial':0};payload['parameters']=d['base_parameters']
            payload['level_info'].update(level=1,exp_total=0,exp_current_level=0,customize_point=0)
            member.update(card_id=str(cid),payload=payload,card_type=d['card_type'],subtype=d['card_series'])
    return result

def removals(old,final):
    result=copy.deepcopy(old.get('write_selection',{}).get('removed',{}))
    for kind,field in [('players','player_ids'),('coaches','coach_ids'),('packs','pack_ids')]:
        current={r['identity']['package_id']if kind=='players'else r['uuid']for r in final[kind]}
        if kind=='players':
            gone={int(cid)for r in old.get(kind,[])if r['identity']['package_id']not in current for cid in
                  {r['identity']['card_id'],*r['identity'].get('previous_card_ids',[])}}
            live={int(cid)for r in final[kind]for cid in {r['identity']['card_id'],*r['identity'].get('previous_card_ids',[])}}
        else:
            key='id'if kind=='coaches'else'agent_id'
            gone={int(r[key])for r in old.get(kind,[])if r['uuid']not in current};live={int(r[key])for r in final[kind]}
        result[field]=sorted((set(map(int,result.get(field,[])))|gone)-live)
    return result

def prune_tables(raw,aliases,coach_ids):
    """Only exact, proven source-owned identifiers; no name/range deletion."""
    from native_cpk import Cpk,unwrap,wrap
    from native_coaches import COACH
    from native_tables import ALIASES
    import csv,io
    cpk=Cpk(raw);changes={}
    if coach_ids and COACH in cpk.files:
        original=cpk.read(COACH);data=unwrap(original)
        if len(data)%176:raise ValueError('全量写入：原生教练表长度异常')
        value=b''.join(data[i:i+176]for i in range(0,len(data),176)if int.from_bytes(data[i:i+8],'little')not in coach_ids)
        if value!=data:changes[COACH]=wrap(value,original)
    if aliases:
        original=cpk.read(ALIASES);data=unwrap(original);rows=list(csv.reader(io.StringIO(data.decode('utf8'))));kept=[rows[0]]
        for row in rows[1:]:
            match=re.match(r'^(\d+)(?:_|_l|f)?$',row[0])if row else None
            if not match or int(match[1])not in aliases:kept.append(row)
        out=io.StringIO(newline='');csv.writer(out,lineterminator='\r\n').writerows(kept)
        value=out.getvalue().encode()
        if value!=data:changes[ALIASES]=wrap(value,original)
    return cpk.replace(changes)if changes else raw

def source_container(archive,work,key):
    from native_iostore import Container
    from export_payload import FilePayload,extract
    stem='assets/gateway-release/custom-resources/legends-v10/pc3700_mobile_and'
    path=Path(work)/'write-source.utoc';path.write_bytes(archive.read(stem+'.utoc'))
    info=archive.getinfo(stem+'.ucas')
    value=archive.payload(info.filename)if hasattr(archive,'payload')else None
    data=value if isinstance(value,FilePayload)else FilePayload.from_zip(archive,info.filename)if info.compress_type==zipfile.ZIP_STORED else extract(archive,info.filename,path.with_suffix('.ucas'))
    return Container(path,key,data=data)

def latest_export(store,release_id):
    folder=store.root/'exports'
    for report in sorted(folder.glob('*.report.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
        try:
            if report.stat().st_size>64*1024**2:continue
            data=json.loads(report.read_text('utf8'));apk=Path(data.get('output',''))
            if not data.get('signature',{}).get('verified_v2'):continue
            if apk.parent.resolve()!=folder.resolve()or not apk.is_file():continue
            _,summary=source(apk,release_id);return summary
        except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile):continue
    return None

def patch_seed(archive,replacements,document):
    if not any(document.get('write_selection',{}).get('removed',{}).values()):return
    import sqlite3
    from personal_runtime import apply_write_selection,REGISTRY_KEY
    name='assets/gateway-release/outputs/efootball/local-club.sqlite3'
    if name not in replacements and name not in archive.namelist():return
    conn=sqlite3.connect(':memory:')
    try:
        conn.deserialize(replacements.get(name)or archive.read(name))
        row=conn.execute('select value from meta where key=?',(REGISTRY_KEY,)).fetchone();registry=json.loads(row[0])if row else{}
        with conn:
            apply_write_selection(conn,document,registry)
            conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',(REGISTRY_KEY,json.dumps(registry,separators=(',',':'))))
        if conn.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('全量写入后的初始数据库校验失败')
        replacements[name]=conn.serialize()
    finally:conn.close()
