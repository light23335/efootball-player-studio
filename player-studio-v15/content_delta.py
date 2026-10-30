"""Declarative V17 content additions. ZIP scripts/native snapshots are never run.

Build an immutable, local source APK, then reuse the normal catalogue importer
and game compiler. No user project, signing key or owned game player is edited.
"""
from pathlib import Path, PurePosixPath
import collections, contextlib, copy, csv, hashlib, io, json, os, re, sqlite3, struct, zipfile

PREFIX = 'assets/gateway-release/'
CONTENT = PREFIX + 'custom-resources/studio-content/catalogue.json'
CPKS = (PREFIX+'livedata/dt870_mobile_and.cpk', PREFIX+'custom-resources/legends-v10/dt870_mobile_and.cpk')
TABLES = {'common/etc/pesdb/Player.bin': (400, 8),
          'common/etc/appearance/PlayerAppearance.bin': (64, 0),
          'common/etc/pesdb/PlayerVariationDetail.bin': (168, 0)}
ALIASES = 'common/etc/playercard/filenameConvTable.csv'

def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')

def sha(raw): return hashlib.sha256(raw).hexdigest()

def safe_path(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\0' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('增量包文件路径无效：'+str(name)[:160])
    return name

class Delta:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file() or self.path.suffix.lower() != '.zip': raise ValueError('请选择独立内容增量 ZIP，不是工程或 APK')
        self.archive = zipfile.ZipFile(self.path)
        try:
            infos = self.archive.infolist(); names = [i.filename for i in infos]
            if len(names) != len(set(n.casefold() for n in names)) or len(names)>30000: raise ValueError('增量包存在重复文件或文件过多')
            for i in infos:
                safe_path(i.filename)
                if i.flag_bits & 1 or i.is_dir() or (i.external_attr>>16)&0o170000 == 0o120000: raise ValueError('增量包不支持加密、目录项或符号链接')
            if sum(i.file_size for i in infos)>2*1024**3 or max((i.file_size for i in infos), default=0)>512*1024**2: raise ValueError('增量包展开体积超出支持范围')
            if self.archive.getinfo('manifest.json').file_size>16*1024**2: raise ValueError('增量包清单过大')
            raw=self.archive.read('manifest.json'); self.digest=sha(raw); self.manifest=json.loads(raw)
            m=self.manifest
            if m.get('format')!='efootball-workshop-content-delta' or type(m.get('schema_version')) is not int or m['schema_version']not in(1,2) or m.get('base_version')!='V17': raise ValueError('不支持的增量包格式或基底；当前支持 V17 内容增量 v1／v2')
            if m['schema_version']==2:
                from content_delta_v2 import CAPABILITIES
                if m.get('runtime_abi')!='v17-content-art/1'or m.get('compatibility',{}).get('engine_family')!='efootball-v17-arm64':raise ValueError('增量包声明的 V17 运行时接口族不支持')
                unknown=set(m.get('required_capabilities',[]))-CAPABILITIES
                if unknown:raise ValueError('此增量包需要尚未支持的内容能力：'+', '.join(sorted(unknown)))
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}',str(m.get('package_id',''))): raise ValueError('增量包永久编号无效')
            policy=m.get('import_policy',{})
            if any(policy.get(k) is not False for k in ('delete_originals','modify_gameplay','ownership_grants')): raise ValueError('增量包必须仅添加内容，不能删除原资料、修改玩法或发卡')
            entries=m.get('entries')
            if not isinstance(entries,list) or not 1<=len(entries)<=29999: raise ValueError('增量包缺少文件清单')
            self.entries={}
            for row in entries:
                name=safe_path(row['path'])
                if name in self.entries or not re.fullmatch('[a-f0-9]{64}',str(row.get('sha256',''))) or type(row.get('bytes')) is not int or row['bytes']<0: raise ValueError('增量包文件清单格式错误：'+name)
                if self.archive.getinfo(name).file_size!=row['bytes']: raise ValueError('增量文件长度不符：'+name)
                with self.archive.open(name) as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=row['sha256']: raise ValueError('增量文件哈希不符：'+name)
                self.entries[name]=row
            if set(names)!=set(self.entries)|{'manifest.json'}: raise ValueError('增量包包含未登记文件')
        except Exception:
            self.archive.close(); raise
    def __enter__(self): return self
    def __exit__(self,*args): self.archive.close()
    def data(self,name):
        if name not in self.entries: raise ValueError('增量包引用未登记文件：'+name)
        return self.archive.read(name)
    def json(self,name): return json.loads(self.data(name))
    def blob(self,ref):
        name=safe_path(ref['path']); entry=self.entries.get(name)
        if not entry or any(entry.get(k)!=ref.get(k) for k in ('bytes','sha256')): raise ValueError('增量包资源引用与清单不一致：'+name)
        return self.data(name)
    def summary(self):
        return {'package_id':self.manifest['package_id'],'manifest_sha256':self.digest,'base_version':'V17',
                'schema_version':self.manifest['schema_version'],
                'versions':self.manifest.get('target_content_versions',[]),'counts':self.manifest.get('counts',{}),
                'bytes':self.path.stat().st_size,'verified_files':len(self.entries)}

def read_catalogue(archive):
    if CONTENT not in archive.namelist(): return {'packages':[], 'players':[], 'routes':[]}
    value=json.loads(archive.read(CONTENT))
    if value.get('format')!='studio-content-catalogue-v1': raise ValueError('APK 内内容增量凭据格式无效')
    return value

def merge_table(raw, table, delta, owned=()):
    """Idempotent exact additions; never overwrite a native or DIY record."""
    name=table['path']
    if table.get('removed') or table.get('updated'): raise ValueError('此版增量导入不允许替换或删除原生记录：'+name)
    if name==ALIASES:
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf8')))); fields=['before','after']
        current={r['before']:r['after'] for r in rows}; changed=False
        for row in table['added']:
            key=str(row['before']); value=str(row['after'])
            if key in current and current[key]!=value: raise ValueError('头像别名冲突：'+key)
            if key not in current: rows.append({'before':key,'after':value}); current[key]=value; changed=True
        if not changed:return raw
        out=io.StringIO(newline=''); w=csv.DictWriter(out,fieldnames=fields,lineterminator='\r\n'); w.writeheader(); w.writerows(rows); return out.getvalue().encode('utf8')
    if name not in TABLES or (table.get('stride'),table.get('key_offset'),table.get('key_bytes'))!=(*TABLES[name],8): raise ValueError('不支持的原生增量表布局：'+name)
    size,offset=TABLES[name]
    if len(raw)%size: raise ValueError('原生表长度错误：'+name)
    current={int.from_bytes(raw[a+offset:a+offset+8],'little'):raw[a:a+size] for a in range(0,len(raw),size)}
    if len(current)!=len(raw)//size: raise ValueError('原生表含重复编号：'+name)
    added=set()
    for row in table['added']:
        key=int(row['key']); record=delta.blob(row['record'])
        if key in added or len(record)!=size or int.from_bytes(record[offset:offset+8],'little')!=key: raise ValueError('增量记录编号或长度不符：'+name+' / '+str(key))
        added.add(key)
        if key in current and current[key]!=record: raise ValueError('球员原生记录冲突：'+str(key)+' / '+name)
        current.setdefault(key,record)
    baseline=b''.join(current[k] for k in sorted(current) if k not in added and k not in set(owned))
    if sha(baseline)!=table['base_sha256']: raise ValueError('V17 基底表校验不符，未覆盖现有资料：'+name)
    return b''.join(current[k] for k in sorted(current))

def merge_iostore(delta,archive,work,key):
    from native_iostore import Container, append_container, package_names, package_id, read_package_header
    d=delta.json('native/iostore-delta.json')
    if d.get('target_container')!='pc3700_mobile_and' or d.get('removed') or d.get('replaced'): raise ValueError('不支持的资源增量容器')
    member=PREFIX+'custom-resources/legends-v10/pc3700_mobile_and'
    srcpath=work/'source/pc3700_mobile_and.utoc'; srcpath.parent.mkdir()
    for ext in ('.utoc','.ucas'): srcpath.with_suffix(ext).write_bytes(archive.read(member+ext))
    source=Container(srcpath,key)
    if source.container_id!=int(d['container_id']): raise ValueError('V17 资源容器身份不符')
    additions=[]; paths={}; packages=[]; present={}
    for row in d['package_store_entries']:
        p={**row,'id':int(row['id']),'imports':[int(x) for x in row['imports']]}
        if p['id'] in present: raise ValueError('增量包存在重复资源包编号')
        present[p['id']]=p
    for row in d['chunks']:
        cid=bytes.fromhex(row['chunk_id_hex']); raw=delta.blob(row['payload'])
        if len(cid)!=12 or cid[11]!=row['type'] or int.from_bytes(cid[:8],'little')!=int(row['package_id']): raise ValueError('资源 chunk 身份不符')
        if cid in source.by_id:
            if source.read_chunk(source.by_id[cid])!=raw: raise ValueError('资源编号冲突：'+row['package_id'])
            continue
        index=len(additions); additions.append((cid,raw))
        # Old pc3700 has a shortened mount. Derive the canonical path from
        # the package name; preserve both names for old references.
        canonical=None
        if cid[11]==2:
            names=package_names(raw)
            canonical=next((n for n in names if n.startswith('/Game/') and package_id(n)==int.from_bytes(cid[:8],'little')),None)
            if not canonical: raise ValueError('增量资源缺少原生包名')
            pid=int.from_bytes(cid[:8],'little')
            if pid not in present: raise ValueError('增量资源缺少 package-store 依赖')
            packages.append(present[pid]); paths['PesMobile/Content/'+canonical[6:]+'.uasset']=index
        for virtual in row['virtual_paths']:
            if not virtual.startswith('../../../'): raise ValueError('资源虚拟路径不符')
            name=safe_path(virtual[9:])
            if name in paths and paths[name]!=index: raise ValueError('增量资源路径重复：'+name)
            paths[name]=index
    # V17's native activation mounts pc3700. Also merge the new standalone
    # face containers into that mounted store, so adding their APK paths does
    # not depend on V19 executable bootstrap code. Keep original files too.
    extra_folder=work/'extra';extra_folder.mkdir()
    for row in delta.json('native/additional-containers.json')['files']:
        name=row['apk_path']
        if not re.fullmatch(re.escape(PREFIX)+r'livedata/pc[0-9]{4,5}_mobile_and\.(pak|utoc|ucas)',name):raise ValueError('增量附加容器路径无效')
        (extra_folder/Path(name).name).write_bytes(delta.blob(row['payload']))
    new_chunks={cid:raw for cid,raw in additions}; new_packages={p['id']:p for p in packages}
    chunk_positions={cid:n for n,(cid,raw)in enumerate(additions)}
    for toc in sorted(extra_folder.glob('*.utoc')):
        extra=Container(toc,key);header=next(i for i,c in enumerate(extra.chunk_ids)if c[11]==10)
        _,stores=read_package_header(extra.read_chunk(header),strict=False)
        stores={p['id']:p for p in stores}
        for n,cid in enumerate(extra.chunk_ids):
            if cid[11]==10:continue
            raw=extra.read_chunk(n)
            if cid in source.by_id:
                if source.read_chunk(source.by_id[cid])!=raw:raise ValueError('附加头模资源与原包冲突：'+toc.name)
                continue
            if cid in new_chunks:
                # The supplied V19 standalone stores contain higher-priority
                # versions of some NEW packages. Match its ordered mounts;
                # never replace an existing V17 chunk (checked above).
                if new_chunks[cid]!=raw:
                    additions[chunk_positions[cid]]=(cid,raw);new_chunks[cid]=raw
                    if cid[11]==2:
                        pid=int.from_bytes(cid[:8],'little')
                        if pid not in stores:raise ValueError('附加资源缺少依赖索引')
                        packages=[stores[pid]if p['id']==pid else p for p in packages];new_packages[pid]=stores[pid]
                continue
            index=len(additions);additions.append((cid,raw));new_chunks[cid]=raw;chunk_positions[cid]=index
            for virtual,chunk in extra.paths.items():
                if chunk==n:
                    name=safe_path(virtual.removeprefix('../../../'))
                    if name in paths and paths[name]!=index:raise ValueError('附加资源路径冲突：'+name)
                    paths[name]=index
            if cid[11]==2:
                canonical=next((p for p in package_names(raw)if p.startswith('/Game/') and package_id(p)==int.from_bytes(cid[:8],'little')),None)
                # Some authored packages intentionally retain their donor's
                # internal name. Their verified container path is authoritative.
                if canonical:paths['PesMobile/Content/'+canonical[6:]+'.uasset']=index
                pid=int.from_bytes(cid[:8],'little')
                if pid not in stores:raise ValueError('附加头模缺少依赖索引')
                if pid not in new_packages:packages.append(stores[pid]);new_packages[pid]=stores[pid]
    output=work/'merged/pc3700_mobile_and.utoc'; output.parent.mkdir()
    if not additions: return {member+ext:archive.read(member+ext) for ext in ('.utoc','.ucas')}
    append_container(source,output,additions,paths,packages)
    return {member+ext:output.with_suffix(ext).read_bytes() for ext in ('.utoc','.ucas')}

def authored_routes(delta,players):
    """Read only 128-byte route DATA from a snapshot; never use its code/hooks."""
    declared=delta.json('native/authored-bindings.json'); keys=declared.get('authored_draw_keys',{})
    if not keys: return []
    blob=bytes.fromhex(json.loads(delta.blob(declared['source_native_payload']))['blob_hex']); result=[]
    for cid,key in keys.items():
        key=str(key); needle=struct.pack('<Q',int(cid)); found=[]; at=0
        while (at:=blob.find(needle,at))>=0:
            row=blob[at:at+128]; at+=1
            if len(row)!=128 or row[40:49]!=bytes([16])+(key+'_').encode() or row[64:73]!=bytes([16])+(key+'f').encode(): continue
            if row[16]==255: face=str(struct.unpack_from('<Q',row,24)[0])
            else: face=row[17:17+row[16]//2].decode('ascii')
            if not re.fullmatch('[0-9]{1,16}',face) or not 0<int(face)<2**63: raise ValueError('增量作者卡模型编号无效：'+cid)
            p=players[cid]['definition']; result_row={'cardId':int(cid),'suiteDonorId':struct.unpack_from('<Q',row,8)[0],
                'portraitKey':key,'modelFaceKey':'','modelNativeId':int(face),'club_id':int(p.get('initial_base_team_id') or 0),
                'position':p['parameters'][0],'maximum_overall':max(1,min(127,int(p.get('_overall') or 90))),
                'presentation_rarity':10}
            found.append(result_row)
        if len(found)!=1: raise ValueError('增量作者卡原生绑定不唯一：'+cid)
        result.append(found[0])
    return result

def project_levels(players,corrections,costs):
    for row in corrections:
        cid=str(row['card_id']); cap=row['level_limit']
        if cid not in players or type(cap) is not int or not 1<=cap<len(costs): raise ValueError('增量等级投影无效：'+cid)
        p=players[cid]['definition']; info=p['level_info']; level=info['level']
        if level!=1: raise ValueError('资源库新增卡必须为未获得的 1 级定义')
        info.update(level_limit=cap,exp_total=0,exp_current_level=0,exp_to_next_level=costs[2] if cap>1 else 0,customize_point=0)

def build_source(delta,apk,output,work,profile,progress=lambda **kw:None):
    if delta.manifest['schema_version']==2:
        from content_delta_v2 import build_source as build_v2
        return build_v2(delta,apk,output,work,profile,progress)
    from native_cpk import Cpk, unwrap, wrap
    from apk_format import replace_entries
    with zipfile.ZipFile(apk) as archive:
        with archive.open('lib/arm64-v8a/libUE4.so') as stream: engine=hashlib.file_digest(stream,'sha256').hexdigest()
        if engine!=delta.manifest['compatibility']['native_engine_sha256'] or engine!=profile['native_engine_sha256'] or profile.get('game_version')!='V17': raise ValueError('增量包需要对应的原 V17 引擎，未改动当前库')
        previous=read_catalogue(archive)
        for receipt in previous['packages']:
            if receipt['package_id']==delta.manifest['package_id']:
                if receipt['manifest_sha256']!=delta.digest: raise ValueError('同名增量包内容已改变，请使用新的包编号')
                return {'already_installed':True,**receipt}
        release=json.loads(archive.read(PREFIX+'release-manifest.json'))
        from personal_source import read,seed
        inherited=read(archive,release); own=seed(inherited,{},{}); owned={n for value in own.values() for n in value['aliases']}
        data=delta.json('data/players.json'); players={str(r['card_id']):copy.deepcopy(r) for r in data['players']}
        if len(players)!=len(data['players']) or len(players)!=delta.manifest['counts']['new_player_cards']: raise ValueError('增量卡片数或编号重复')
        for cid,row in players.items():
            p=row['definition']; params=p.get('parameters')
            if str(p.get('gameplayer_id',{}).get('id'))!=cid or p['gameplayer_id'].get('serial')!=0 or row.get('default_import_action')!='register_catalogue_only' or not isinstance(params,list) or len(params)!=147: raise ValueError('增量球员定义不符：'+cid)
        from apk_literals import module_reader,literal_assignments
        costs=literal_assignments(module_reader(apk)('pes_tables'),{'EXPERIENCE_LIST'})['EXPERIENCE_LIST']
        if costs and isinstance(costs[0],(list,tuple)):
            pairs=dict(costs); costs=[0,0]+[pairs[n] for n in range(2,max(pairs)+1)]
        project_levels(players,data.get('level_info_projection',[]),costs)
        replacements={}; seen=set()
        progress(message='合并新增球员原生记录、外观和头像别名')
        for container in delta.json('native/cpk-deltas.json')['containers']:
            name=container['source_container']
            if name not in CPKS or name in seen: raise ValueError('增量包请求修改非内容资料容器')
            seen.add(name); cpk=Cpk(archive.read(name)); tables={}
            for table in container['tables']:
                if table['path'] in tables: raise ValueError('增量表重复')
                original=cpk.read(table['path']); raw=unwrap(original)
                tables[table['path']]=wrap(merge_table(raw,table,delta,owned),original)
            replacements[name]=cpk.replace(tables)
        if seen!=set(CPKS): raise ValueError('增量包原生资料容器不完整')
        progress(message='合并大小头像、头模和依赖资源')
        with archive.open('lib/arm64-v8a/libUE4.so') as stream: stream.seek(profile['resource_key_offset']); key=stream.read(32)
        if sha(key)!=profile['resource_key_sha256']: raise ValueError('V17 原生资源密钥校验不符')
        replacements.update(merge_iostore(delta,archive,work,key))
        for row in delta.json('native/additional-containers.json')['files']:
            name=row['apk_path']
            if not re.fullmatch(re.escape(PREFIX)+r'livedata/pc[0-9]{4,5}_mobile_and\.(pak|utoc|ucas)',name): raise ValueError('增量附加容器路径无效')
            raw=delta.blob(row['payload'])
            if name in archive.namelist() and archive.read(name)!=raw: raise ValueError('附加容器冲突：'+name)
            replacements[name]=raw
        for row in delta.json('assets/card-art-files.json')['files']:
            name=safe_path(row['source_path'])
            if not re.fullmatch(r'assets/card-designer/(backgrounds|background-videos)/[A-Za-z0-9_.-]+\.(png|webm|mp4|jpg)',name): raise ValueError('卡面增量文件类型不支持：'+name)
            raw=delta.blob(row['payload']); old=archive.read(name) if name in archive.namelist() else None
            if old is not None and old!=raw and (row['operation']!='replace_exact' or sha(old)!=row.get('expected_before_sha256')): raise ValueError('卡面资源冲突：'+name)
            replacements[name]=raw
        coaches=delta.json('data/coaches.json')
        if any(coaches.get(k) for k in ('added','updated','removed')): raise ValueError('此版不支持未配备原生表的教练增量；当前 V18/V19 教练应为空增量')
        suites=delta.json('data/card-suites.json')
        if suites.get('removed') or suites.get('updates'): raise ValueError('不支持未提供前置哈希的卡面模板替换')
        document=copy.deepcopy(previous); document['format']='studio-content-catalogue-v1'
        current={str(r['card_id']):r for r in document['players']}
        for cid,row in players.items():
            if cid in current and compact(current[cid])!=compact(row): raise ValueError('已安装卡片定义冲突：'+cid)
            current[cid]=row
        document['players']=list(current.values()); document['routes']+=authored_routes(delta,players)
        receipt=delta.summary(); document['packages'].append(receipt)
        # Retain declared suite data; the importer also builds workshop-native
        # presets from the verified merged resource index.
        document['card_suites']=suites['full_target_catalogue']
        document['card_suite_additions']=suites.get('added',[])
        replacements[CONTENT]=compact(document)
        progress(message='登记资源库卡片；不向存档自动发卡')
        db=sqlite3.connect(':memory:')
        try:
            name=PREFIX+'outputs/efootball/local-club.sqlite3'; db.deserialize(archive.read(name))
            with db:
                for cid,row in players.items():
                    p=compact(row['definition']).decode('utf8'); origin=row['origin']; existing=db.execute('select payload from managed_cards where card_id=?',(cid,)).fetchone()
                    if existing and compact(json.loads(existing[0]))!=compact(row['definition']): raise ValueError('原包卡片定义冲突：'+cid)
                    db.execute('insert or ignore into managed_cards values(?,?,?,?,?,?)',(cid,sha(p.encode()),p,origin['card_type'],origin.get('subtype'), 'studio-content:'+receipt['package_id']))
            if db.execute('pragma quick_check').fetchone()[0]!='ok': raise ValueError('新增卡片资料库校验失败')
            replacements[name]=db.serialize()
        finally: db.close()
        listed={r['path']:r for r in release['files']}
        for name,raw in replacements.items():
            if name.startswith(PREFIX):
                rel=name[len(PREFIX):]; record={'path':rel,'bytes':len(raw),'sha256':sha(raw)}
                if rel in listed: listed[rel].update(record)
                else: release['files'].append(record)
        replacements[PREFIX+'release-manifest.json']=compact(release)
    progress(message='生成本地增量来源副本；保留原 APK')
    replace_entries(apk,output,replacements)
    with zipfile.ZipFile(output) as check:
        for name,raw in replacements.items():
            with check.open(name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=sha(raw): raise ValueError('增量来源写回校验失败：'+name)
    return receipt

def finish_catalogue(apk,resources):
    """Register canonical aliases and preserve current 2.0.4 preset fixes."""
    resources=Path(resources)
    with zipfile.ZipFile(apk) as archive: document=read_catalogue(archive)
    if not document['packages']: return None
    with contextlib.closing(sqlite3.connect(resources/'library.sqlite3')) as db,db:
        for route in document['routes']:
            cid=str(route['cardId']); key=route['portraitKey']
            for tail in ('_','_l'):
                # The declarative alias table is authoritative: many authored
                # large portraits intentionally reuse their small texture key.
                db.execute('insert or ignore into card_aliases values(?,?)',(cid+tail,key+'_'))
            db.execute('update players set base_id=? where id=?',(str(route['modelNativeId']),cid))
        (resources/'content-catalogue.json').write_bytes(compact(document))
    if document.get('coaches'):
        path=resources/'coaches.json';coaches=json.loads(path.read_text('utf8'));by_id={str(c['id']):c for c in coaches['coaches']}
        for row in document['coaches']:
            cid=str(row.get('coach_id',row.get('id')));definition=row['definition']
            if cid not in by_id or str((definition.get('coach_id')or{}).get('id'))!=cid:raise ValueError('内容教练定义与原生 Coach.bin 不一致：'+cid)
            by_id[cid].update(raw_payload=copy.deepcopy(definition),raw_payload_verified=True,source='内容增量 · 已核对原生教练表')
        path.write_bytes(compact(coaches));catalog_path=resources/'catalog.json';catalog=json.loads(catalog_path.read_text('utf8'));catalog['coaches']=coaches['coaches'];catalog_path.write_bytes(compact(catalog))
    from card_preset_catalogue import build
    added=build(resources,write=False,verbose=False)
    path=resources/'native-card-presets.json'; previous=json.loads(path.read_text('utf8'))
    rows={r['id']:r for r in previous['rows']}
    declared=set()
    for suite in document.get('card_suite_additions',document.get('card_suites',[])):
        kind=int(suite['nativeType'],16);declared.add((f'{kind>>4:02d}{kind&15:02d}',int(suite['variant'])))
    signature=lambda r:tuple((p['slot'],p['kind'],p['path'],p.get('blend','source-over'))for p in r['layers'])
    seen={signature(r)for r in rows.values()}
    for row in added['rows']:
        key=signature(row)
        if (row['native_style'],row['native_agent'])in declared and key not in seen:
            rows.setdefault(row['id'],row);seen.add(key)
    previous['rows']=list(rows.values()); previous['counts']=dict(collections.Counter(r['card_type'] for r in rows.values()))
    previous['content_packages']=[r['package_id'] for r in document['packages']]; path.write_bytes(compact(previous))
    return {'packages':document['packages'],'players':len(document['players']),'declared_suites':len(document.get('card_suites',[])),
            'workshop_presets':len(rows),'routes':len(document['routes'])}
