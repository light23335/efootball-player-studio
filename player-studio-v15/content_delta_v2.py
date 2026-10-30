"""Transactional, dependency-aware content updates to a V17-derived source APK."""
from pathlib import Path
import collections,copy,csv,hashlib,io,json,re,sqlite3,struct,zipfile
from content_delta import PREFIX,CONTENT,CPKS,TABLES,ALIASES,compact,sha,safe_path,read_catalogue,project_levels

CAPABILITIES={'content.entities-v2','content.rowwise-merge-v1','content.v17-derived-source-v1','art.registry-v1',
              'art.native-lookup-id-v1','assets.iostore-v1','card-suites.layers-v1','training.level-info-projection-v1'}
LAYOUTS={**TABLES,'common/etc/pesdb/Coach.bin':(176,0)}


def art_routes(delta,players):
    value=delta.json('data/art-bindings.json')
    if value.get('schema')!='efootball-art-bindings/2' or value.get('runtime_abi')!='v17-content-art/1':raise ValueError('不支持的内容美术绑定协议')
    result=[];seen=set();keys=set()
    for row in value['routes']:
        kind=row['entity_kind'];cid=str(row['entity_id'])
        if kind!='player_card' or cid not in players or (kind,cid)in seen:raise ValueError('美术绑定实体无效：'+kind+':'+cid)
        seen.add((kind,cid));portrait=row['portrait'];model=row['model'];key=portrait['key']
        if portrait.get('kind')!='authored_key' or not re.fullmatch('[0-9]{7}',key)or key in keys or portrait.get('small_key')!=key+'_' or portrait.get('detail_key')!=key+'f':raise ValueError('美术绑定头像引用无效：'+cid)
        keys.add(key)
        if model.get('kind')!='native_lookup_id' or not re.fullmatch('[0-9]{1,19}',str(model.get('id','')))or not 0<int(model['id'])<2**63:raise ValueError('美术绑定原生查找 ID 无效：'+cid)
        p=players[cid]['definition'];overall=p.get('_overall') or row.get('display_overall',{}).get('legacy_source_hint',90)
        # Keep the 64-bit lookup ID verbatim. It is not the short player ID.
        result.append({'cardId':int(cid),'suiteDonorId':int(row['suite_donor_id']),'portraitKey':key,'modelFaceKey':'',
                       'modelNativeId':int(model['id']),'club_id':row['club_id'],'position':row['position'],
                       'maximum_overall':int(overall),'presentation_rarity':row['presentation_rarity']})
    return result


def semantic_payload(value):
    value=copy.deepcopy(value)
    for key in list(value):
        if key.startswith('_studio_'):value.pop(key)
    return compact(value)


def rows(raw,stride,offset):
    if len(raw)%stride:raise ValueError('当前原生表长度与已核对布局不符')
    result={int.from_bytes(raw[p+offset:p+offset+8],'little'):raw[p:p+stride]for p in range(0,len(raw),stride)}
    if len(result)!=len(raw)//stride:raise ValueError('当前原生表存在重复编号')
    return result


def record_plan(raw,table,delta):
    """Keep target edits; updates require an explicit matching before hash."""
    name=table['path']
    if name not in LAYOUTS or (table.get('stride'),table.get('key_offset'),table.get('key_bytes'))!=(*LAYOUTS[name],8):raise ValueError('不支持的原生资料表：'+name)
    if table.get('removed'):raise ValueError('内容包不能删除原生资料')
    stride,offset=LAYOUTS[name];current=rows(raw,stride,offset);actions={};conflicts={}
    for mode,values in (('add',table.get('added',[])),('update',table.get('updated',[]))):
        for row in values:
            cid=int(row['key']);record=delta.blob(row['record'])
            if cid in actions or len(record)!=stride or int.from_bytes(record[offset:offset+8],'little')!=cid:raise ValueError('增量原生记录身份无效：'+str(cid))
            old=current.get(cid)
            if old==record:status='reused'
            elif old is None and mode=='add':status='added'
            elif old is not None and mode=='update' and row.get('expected_before_sha256')==sha(old):status='updated'
            else:status='preserved_user';conflicts[str(cid)]='现有原生资料不同：'+name
            actions[cid]=(record,status)
    return current,actions,conflicts


def load_assets(delta,archive,work,key):
    from native_iostore import Container,package_id,package_names,read_package_header
    info=delta.json('native/iostore-delta.json')
    if info.get('target_container')!='pc3700_mobile_and'or info.get('removed')or info.get('replaced'):raise ValueError('内容容器协议不符')
    member=PREFIX+'custom-resources/legends-v10/pc3700_mobile_and'
    folder=work/'source';folder.mkdir(parents=True)
    for ext in ('.utoc','.ucas'):(folder/('pc3700_mobile_and'+ext)).write_bytes(archive.read(member+ext))
    source=Container(folder/'pc3700_mobile_and.utoc',key)
    if source.container_id!=int(info['container_id']):raise ValueError('当前包的 V17 内容容器身份不符')
    packages={int(r['id']):dict(r,id=int(r['id']),imports=[int(i)for i in r['imports']])for r in info['package_store_entries']}
    candidates={};paths={};extra_files=[]
    def add(cid,raw,names):
        if len(cid)!=12 or cid[11]not in(2,3):raise ValueError('内容资源 chunk 类型不支持')
        pid=int.from_bytes(cid[:8],'little');candidates[cid]=raw
        for virtual in names:
            name=safe_path(virtual.removeprefix('../../../'))
            if name in paths and paths[name]!=cid:raise ValueError('包内存在相互冲突的资源路径：'+name)
            paths[name]=cid
        if cid[11]==2:
            own=next((n for n in package_names(raw)if n.startswith('/Game/')and package_id(n)==pid),None)
            if own:paths['PesMobile/Content/'+own[6:]+'.uasset']=cid
            if pid not in packages:raise ValueError('内容资源缺少 package-store 依赖：'+str(pid))
    for row in info['chunks']:
        cid=bytes.fromhex(row['chunk_id_hex'])
        if cid[11]!=row['type']or int.from_bytes(cid[:8],'little')!=int(row['package_id']):raise ValueError('内容资源身份不符')
        add(cid,delta.blob(row['payload']),row['virtual_paths'])
    folder=work/'extra';folder.mkdir()
    for row in delta.json('native/additional-containers.json')['files']:
        name=row['apk_path']
        if not re.fullmatch(re.escape(PREFIX)+r'livedata/pc[0-9]{4,5}_mobile_and\.(pak|utoc|ucas)',name):raise ValueError('附加资源容器路径不支持')
        raw=delta.blob(row['payload']);(folder/Path(name).name).write_bytes(raw);extra_files.append((name,raw))
    for path in sorted(folder.glob('*.utoc')):
        extra=Container(path,key);header=next(i for i,c in enumerate(extra.chunk_ids)if c[11]==10)
        _,metadata=read_package_header(extra.read_chunk(header),strict=False)
        packages.update({p['id']:p for p in metadata})
        for i,cid in enumerate(extra.chunk_ids):
            if cid[11]==10:continue
            add(cid,extra.read_chunk(i),[p for p,n in extra.paths.items()if n==i])
    _,current_meta=read_package_header(source.read_chunk(next(i for i,c in enumerate(source.chunk_ids)if c[11]==10)),strict=False)
    current_meta={r['id']:r for r in current_meta};conflicts={}
    for cid,raw in candidates.items():
        pid=int.from_bytes(cid[:8],'little')
        if cid in source.by_id and source.read_chunk(source.by_id[cid])!=raw:conflicts[pid]='原生资源编号已有不同内容'
        if pid in current_meta and pid in packages and current_meta[pid]!=packages[pid]:conflicts[pid]='资源依赖索引已有不同内容'
    old_paths={n.removeprefix('../../../'):source.chunk_ids[i]for n,i in source.paths.items()}
    for name,cid in paths.items():
        if name in old_paths and old_paths[name]!=cid:conflicts[int.from_bytes(cid[:8],'little')]='原生资源路径已有不同引用：'+name
    # A conflicting dependency invalidates every new package referring to it.
    while True:
        dependants={pid:'依赖资源冲突'for pid,p in packages.items()if pid not in conflicts and set(p['imports'])&set(conflicts)}
        if not dependants:break
        conflicts.update(dependants)
    return source,candidates,paths,packages,conflicts,extra_files


def dependency_map(players,routes,suites,paths,packages):
    route_by={str(r['cardId']):r for r in routes};result={};assets={};all_pids={int.from_bytes(c[:8],'little')for c in paths.values()}
    for cid,row in players.items():
        n=int(cid);style=n>>40&255;prefix=f'{style>>4:02d}{style&15:02d}_{n>>28&4095}_'
        route=route_by.get(cid,{})
        tokens={cid,str(row.get('base_id','')),str(route.get('portraitKey','')),str(route.get('modelNativeId',''))}-{''}
        roots={int.from_bytes(c[:8],'little')for name,c in paths.items()if tokens&set(re.findall(r'(?<![0-9])[0-9]{4,}(?![0-9])',name))or Path(name).stem.startswith(prefix)}
        pending=list(roots)
        while pending:
            pid=pending.pop()
            for dep in packages.get(pid,{}).get('imports',[]):
                if dep in all_pids and dep not in roots:roots.add(dep);pending.append(dep)
        result[cid]=roots;assets[cid]=prefix
    return result,assets


def merge_assets(source,candidates,paths,packages,blocked,work):
    from native_iostore import append_container
    additions=[];new_paths={};metadata={};replace=set();positions={}
    original_paths={p.removeprefix('../../../'):i for p,i in source.paths.items()}
    for cid,raw in candidates.items():
        pid=int.from_bytes(cid[:8],'little')
        if pid in blocked:continue
        own_paths=[p for p,c in paths.items()if c==cid]
        existing=source.by_id.get(cid)
        if existing is not None and all(p in original_paths for p in own_paths):continue
        index=len(additions);additions.append((cid,raw));positions[cid]=index
        if existing is not None:replace.add(existing)
        for name in own_paths:
            if name not in original_paths:new_paths[name]=index
        if cid[11]==2:metadata[pid]=packages[pid]
    member=PREFIX+'custom-resources/legends-v10/pc3700_mobile_and'
    if not additions:return {},0
    target=work/'merged/pc3700_mobile_and.utoc'
    append_container(source,target,additions,new_paths,list(metadata.values()),replace_indices=replace)
    return {member+e:target.with_suffix(e).read_bytes()for e in('.utoc','.ucas')},len(additions)


def build_source(delta,apk,output,work,profile,progress=lambda **kw:None):
    from native_cpk import Cpk,unwrap,wrap
    from apk_format import replace_entries
    from apk_literals import module_reader,literal_assignments
    from engine_compatibility import detect
    from studio_resources import bundled_resources
    from native_diy_binding import code_fingerprint,V17_COMPOSE
    with zipfile.ZipFile(apk)as archive:
        release=json.loads(archive.read(PREFIX+'release-manifest.json'))
        compatible=detect(apk,bundled_resources(),release['release_id'])
        reader=module_reader(apk);functions=[c for c in reader('diy_routes').co_consts if getattr(c,'co_name',None)=='compose']
        if len(functions)!=1 or code_fingerprint(functions[0])!=V17_COMPOSE:raise ValueError('当前包不是已核对的 V17 接口族')
        previous=read_catalogue(archive)
        prior=next((r for r in previous['packages']if r['package_id']==delta.manifest['package_id']),None)
        if prior and prior['manifest_sha256']!=delta.digest:raise ValueError('相同增量包编号内容不同，未覆盖原记录')
        if prior and not prior.get('pending_entities'):return {'already_installed':True,**prior}
        data=delta.json('data/players.json');players={str(r['card_id']):copy.deepcopy(r)for r in data['players']}
        if len(players)!=len(data['players'])or len(players)!=delta.manifest['counts']['new_player_cards']:raise ValueError('增量球员数量或编号重复')
        for cid,row in players.items():
            p=row['definition']
            if str(p.get('gameplayer_id',{}).get('id'))!=cid or p['gameplayer_id'].get('serial')!=0 or row.get('default_import_action')!='register_catalogue_only'or len(p.get('parameters',[]))!=147:raise ValueError('增量球员定义无效：'+cid)
        costs=literal_assignments(reader('pes_tables'),{'EXPERIENCE_LIST'})['EXPERIENCE_LIST']
        if costs and isinstance(costs[0],(list,tuple)):
            pairs=dict(costs);costs=[0,0]+[pairs[n]for n in range(2,max(pairs)+1)]
        project_levels(players,data.get('level_info_projection',[]),costs)
        routes=art_routes(delta,players);suites=delta.json('data/card-suites.json');conflicts={};plans={};aliases={};definition_updates=set()
        if suites.get('removed'):raise ValueError('内容包不能删除原卡面模板')
        coaches=delta.json('data/coaches.json')
        coach_ids={str(r.get('coach_id',r.get('id','')))for r in [*coaches.get('added',[]),*coaches.get('updated',[])]}
        for route in routes:
            cid=str(route['cardId']);old=next((r for r in previous['routes']if str(r['cardId'])==cid),None)
            if old is not None and old!=route:conflicts.setdefault(cid,[]).append('已登记美术绑定不同，保留原绑定')
        progress(message='逐项核对当前包；保留已有 DIY、培养进度和用户修改')
        for container in delta.json('native/cpk-deltas.json')['containers']:
            path=container['source_container']
            if path not in CPKS or path in plans:raise ValueError('内容资料容器不支持或重复')
            cpk=Cpk(archive.read(path));tables=[]
            for table in container['tables']:
                name=table['path'];original=cpk.read(name);raw=unwrap(original)
                if name==ALIASES:
                    if table.get('removed')or table.get('updated'):raise ValueError('头像别名修改必须有原值前置条件')
                    values=list(csv.DictReader(io.StringIO(raw.decode('utf8'))));current={r['before']:r['after']for r in values}
                    aliases[path]=(original,values,current,table['added']);continue
                existing,actions,bad=record_plan(raw,table,delta);tables.append((name,original,existing,actions))
                declared=coach_ids if name=='common/etc/pesdb/Coach.bin'else set(players)
                if any(str(cid)not in declared for cid in actions):raise ValueError('原生增量记录没有对应的已声明实体：'+name)
                for cid,reason in bad.items():conflicts.setdefault('coach:'+cid if name=='common/etc/pesdb/Coach.bin'else cid,[]).append(reason)
            plans[path]=(cpk,tables)
        if set(plans)!=set(CPKS):raise ValueError('内容资料容器不完整')
        seed=sqlite3.connect(':memory:');seed.deserialize(archive.read(PREFIX+'outputs/efootball/local-club.sqlite3'))
        try:
            for cid,row in players.items():
                existing=seed.execute('select payload from managed_cards where card_id=?',(cid,)).fetchone()
                if existing and semantic_payload(json.loads(existing[0]))!=semantic_payload(row['definition']):
                    owned=next((r for r in previous['players']if str(r['card_id'])==cid),None)
                    expected=row.get('expected_before_definition_sha256')
                    if owned and expected==sha(semantic_payload(json.loads(existing[0]))):definition_updates.add(cid)
                    else:conflicts.setdefault(cid,[]).append('当前卡片定义已修改，保留玩家版本')
            with archive.open('lib/arm64-v8a/libUE4.so')as engine:
                engine.seek(profile['resource_key_offset']);key=engine.read(32)
            if sha(key)!=profile['resource_key_sha256']:raise ValueError('当前 V17 派生包资源密钥不同')
            source,candidates,paths,packages,bad_packages,extra_files=load_assets(delta,archive,work,key)
            dependencies,prefixes=dependency_map(players,routes,suites,paths,packages)
            for cid,deps in dependencies.items():
                if deps&set(bad_packages):conflicts.setdefault(cid,[]).append('头像、模型或其依赖资源存在冲突')
                elif not deps and bad_packages:conflicts.setdefault(cid,[]).append('无法证明此卡与冲突资源相互独立，保留原卡并跳过')
            for _,(_,_,current,added)in aliases.items():
                for row in added:
                    before=str(row['before']);after=str(row['after'])
                    if before in current and current[before]!=after:
                        affected=[cid for cid in players if before.startswith(cid+'_')or after.startswith(str(next((r['portraitKey']for r in routes if str(r['cardId'])==cid),'!')))]
                        if not affected:affected=[cid for cid,p in prefixes.items()if before.startswith(p)]
                        for cid in affected:conflicts.setdefault(cid,[]).append('头像或卡面别名已被玩家修改')
            art=[];art_bad=set()
            for row in delta.json('assets/card-art-files.json')['files']:
                name=safe_path(row['source_path'])
                if not re.fullmatch(r'assets/card-designer/(backgrounds|background-videos)/[A-Za-z0-9_.-]+\.(png|webm|mp4|jpg)',name):raise ValueError('卡面文件类型不支持')
                raw=delta.blob(row['payload']);old=archive.read(name)if name in archive.namelist()else None
                allowed=old in(None,raw)or row['operation']=='replace_exact'and sha(old)==row.get('expected_before_sha256')
                if not allowed:
                    art_bad.add(name)
                    for cid,prefix in prefixes.items():
                        if Path(name).stem.startswith(prefix):conflicts.setdefault(cid,[]).append('卡面素材已被玩家修改')
                art.append((row,name,raw,allowed))
            accepted={cid:r for cid,r in players.items()if cid not in conflicts};blocked=set(bad_packages)
            keep_deps=set().union(*(dependencies[c]for c in accepted))if accepted else set()
            rejected_deps=set().union(*(dependencies[c]for c in players if c not in accepted))if len(accepted)!=len(players)else set()
            blocked|=rejected_deps-keep_deps
            replacements,asset_count=merge_assets(source,candidates,paths,packages,blocked,work)
            counts=collections.Counter();statuses={}
            for cid,row in players.items():
                if cid in conflicts:
                    existed=any(int(cid)in existing for _,tables in plans.values()for name,_,existing,_ in tables if name=='common/etc/pesdb/Player.bin')
                    status='preserved_user'if existed else'skipped_conflict'
                else:
                    states=[acts[int(cid)][1]for _,tables in plans.values()for _,_,_,acts in tables if int(cid)in acts]
                    status='added'if 'added'in states else'updated'if 'updated'in states else'reused'
                counts[status]+=1;statuses['player_card:'+cid]={'name':row.get('name',cid),'status':status,'reasons':list(dict.fromkeys(conflicts.get(cid,[])))}
            for path,(cpk,tables)in plans.items():
                changed={}
                for name,original,existing,actions in tables:
                    for cid,(record,status)in actions.items():
                        entity='coach:'+str(cid)if name=='common/etc/pesdb/Coach.bin'else str(cid)
                        if entity not in conflicts and status in('added','updated'):existing[cid]=record
                    result=b''.join(existing[c]for c in sorted(existing))
                    if result!=unwrap(original):changed[name]=wrap(result,original)
                if path in aliases:
                    original,values,current,added=aliases[path]
                    for row in added:
                        before=str(row['before']);after=str(row['after'])
                        owner=next((cid for cid in players if before.startswith(cid+'_')),None)
                        if owner in conflicts or before in current:continue
                        values.append({'before':before,'after':after});current[before]=after
                    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=['before','after'],lineterminator='\r\n');writer.writeheader();writer.writerows(values)
                    if stream.getvalue().encode()!=unwrap(original):changed[ALIASES]=wrap(stream.getvalue().encode(),original)
                if changed:replacements[path]=cpk.replace(changed)
            for row,name,raw,allowed in art:
                if allowed and not any(Path(name).stem.startswith(prefixes[c])for c in conflicts if c in prefixes)or allowed and any(Path(name).stem.startswith(prefixes[c])for c in accepted):
                    if name not in archive.namelist()or archive.read(name)!=raw:replacements[name]=raw
            if not blocked:
                for name,raw in extra_files:
                    if name not in archive.namelist():replacements[name]=raw
                    elif archive.read(name)!=raw:art_bad.add(name)
            if coaches.get('removed'):raise ValueError('内容包不能删除教练')
            # Coaches enter native Coach.bin and the read-only catalogue, never ownership.
            coach_rows={str(r.get('coach_id',r.get('id'))):r for r in previous.get('coaches',[])}
            for row in [*coaches.get('added',[]),*coaches.get('updated',[])]:
                cid=str(row.get('coach_id',row.get('id','')))
                if not cid.isdecimal()or not isinstance(row.get('definition'),dict):raise ValueError('教练增量缺少原生 ID 或定义')
                verified=any(name=='common/etc/pesdb/Coach.bin'and int(cid)in acts for _,tables in plans.values()for name,_,_,acts in tables)
                if not verified:raise ValueError('教练增量缺少可核对的 Coach.bin 原生记录：'+cid)
                entity='coach:'+cid
                if entity not in conflicts:coach_rows[cid]=copy.deepcopy(row)
                statuses[entity]={'status':'preserved_user'if entity in conflicts else'added','reasons':conflicts.get(entity,[])}
            document=copy.deepcopy(previous);document.update(format='studio-content-catalogue-v1',runtime_abi='v17-content-art/1',base_version='V17')
            current={str(r['card_id']):r for r in previous['players']}
            for cid,row in accepted.items():
                if cid in definition_updates:current[cid]=row
                else:current.setdefault(cid,row)
            document['players']=list(current.values());document['coaches']=list(coach_rows.values())
            registry={int(r['cardId']):r for r in previous['routes']}
            # Include assets as individual receipt entries so a partially installed
            # package remains retryable even when the conflict is a shared template.
            for name in sorted(art_bad):
                statuses['asset:'+name]={'status':'preserved_user','reasons':['当前素材不同，保留原文件']}
            for pid,reason in bad_packages.items():statuses['native_package:'+str(pid)]={'status':'preserved_user','reasons':[reason]}
            for row in routes:
                cid=str(row['cardId'])
                if cid in accepted:
                    if row['cardId']in registry and registry[row['cardId']]!=row:
                        # Never change an existing dispatch as a side effect of an update.
                        raise ValueError('已登记美术绑定与资料预检不一致：'+cid)
                    registry.setdefault(row['cardId'],row)
            document['routes']=[registry[c]for c in sorted(registry)]
            receipt={**delta.summary(),'items':statuses,'counts_result':dict(counts),'pending_entities':[k for k,v in statuses.items()if v['status']in('preserved_user','skipped_conflict')],
                     'asset_conflicts':sorted(art_bad),'assets_added':asset_count,'source_kind':'verified-v17-interface-family','source_preserved':True}
            document['packages']=[r for r in previous['packages']if r['package_id']!=receipt['package_id']]+[receipt]
            suite_key=lambda r:(r['nativeType'],str(r['variant']),r.get('id',''))
            all_suites={suite_key(r):r for r in previous.get('card_suites',[])}
            for row in suites['full_target_catalogue']:
                prefix=f"{int(row['nativeType'],16)>>4:02d}{int(row['nativeType'],16)&15:02d}_{row['variant']}_"
                if not any(Path(n).stem.startswith(prefix)for n in art_bad):all_suites.setdefault(suite_key(row),row)
            for update in suites.get('updates',[]):
                row=update.get('value');expected=update.get('expected_before_sha256')
                if not isinstance(row,dict)or not re.fullmatch('[a-f0-9]{64}',str(expected or '')):raise ValueError('卡面模板更新缺少明确的新值和前置哈希')
                key=suite_key(row);old=all_suites.get(key)
                if old is not None and compact(old)==compact(row):continue
                if old is not None and sha(compact(old))==expected:all_suites[key]=copy.deepcopy(row)
                else:
                    entity='card_suite:'+str(key);statuses[entity]={'status':'preserved_user','reasons':['现有卡面模板已改变，未覆盖']}
                    receipt['pending_entities'].append(entity)
            document['card_suites']=list(all_suites.values())
            additions={suite_key(r):r for r in previous.get('card_suite_additions',[])}
            for row in suites.get('added',[]):
                if suite_key(row)in all_suites:additions.setdefault(suite_key(row),row)
            document['card_suite_additions']=list(additions.values());replacements[CONTENT]=compact(document)
            with seed:
                for cid,row in accepted.items():
                    p=compact(row['definition']).decode();origin=row['origin']
                    values=(cid,sha(p.encode()),p,origin['card_type'],origin.get('subtype'),'studio-content:'+receipt['package_id'])
                    if cid in definition_updates:seed.execute('insert or replace into managed_cards values(?,?,?,?,?,?)',values)
                    else:seed.execute('insert or ignore into managed_cards values(?,?,?,?,?,?)',values)
            if seed.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('合并后的卡片数据库校验失败')
            replacements[PREFIX+'outputs/efootball/local-club.sqlite3']=seed.serialize()
        finally:seed.close()
        listed={r['path']:r for r in release['files']}
        for name,raw in replacements.items():
            if name.startswith(PREFIX):
                rel=name[len(PREFIX):];record={'path':rel,'bytes':len(raw),'sha256':sha(raw)}
                if rel in listed:listed[rel].update(record)
                else:release['files'].append(record)
        replacements[PREFIX+'release-manifest.json']=compact(release)
    progress(message=f"合并完成：新增 {counts['added']}，复用 {counts['reused']}，保留用户修改 {counts['preserved_user']}；写入暂存副本")
    replace_entries(apk,output,replacements)
    with zipfile.ZipFile(output)as archive:
        for name,raw in replacements.items():
            with archive.open(name)as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=sha(raw):raise ValueError('暂存副本写回校验失败：'+name)
    return receipt
