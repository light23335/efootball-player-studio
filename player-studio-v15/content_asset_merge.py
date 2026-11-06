"""Compiler-only, entity-scoped IoStore additions from an imported library.

The chosen source owns every existing package. Cache snapshots are donors for
missing declared content, never replacements for unrelated source containers.
"""
from pathlib import Path
import ast,collections,hashlib,io,json,re
from content_delta import PREFIX,safe_path
from export_payload import FilePayload
from native_iostore import Container,read_package_header,append_container

STEM=PREFIX+'custom-resources/legends-v10/pc3700_mobile_and'


def _suite_key(row):return str(row['nativeType']),str(row['variant']),row.get('id','')


def _selection(previous,wanted,needed):
    receipts={r['package_id']:r for r in previous.get('packages',[])}
    declared={r['package_id']for r in wanted.get('packages',[])}
    if not set(needed)<=declared:raise ValueError('自动补齐缺少已登记内容归属')
    players={str(r['card_id']):r for r in wanted.get('players',[])}
    routes={str(r['cardId']):r for r in wanted.get('routes',[])}
    suites={_suite_key(r):r for k in('card_suites','card_suite_additions')for r in wanted.get(k,[])}
    old_players={str(r['card_id'])for r in previous.get('players',[])}
    old_routes={str(r['cardId'])for r in previous.get('routes',[])}
    old_suites={_suite_key(r)for k in('card_suites','card_suite_additions')for r in previous.get(k,[])}
    selected=set(players)-old_players;selected_routes=set(routes)-old_routes
    selected_suites=set(suites)-old_suites;package_roots=set();media=set();pending=[]
    for ident in needed:
        receipt=receipts.get(ident,{})
        media.update(receipt.get('asset_conflicts',[]))
        for value in receipt.get('pending_entities',[]):
            pending.append(value)
            kind,sep,entity=str(value).partition(':')
            if not sep:raise ValueError('无法证明待补齐实体的资源归属：'+str(value))
            if kind in('player_card','card','route'):
                if entity not in players:raise ValueError('待补齐球员未在当前内容登记：'+entity)
                selected.add(entity)
                if entity in routes:selected_routes.add(entity)
            elif kind=='native_package':
                try:package_roots.add(int(entity))
                except ValueError:raise ValueError('待补齐资源包编号无效：'+entity)from None
            elif kind=='card_suite':
                try:key=tuple(map(str,ast.literal_eval(entity)))
                except (ValueError,SyntaxError,TypeError):raise ValueError('待补齐卡面模板身份无效：'+entity)from None
                if len(key)!=3 or key not in suites:raise ValueError('待补齐卡面模板未登记：'+entity)
                selected_suites.add(key)
            elif kind=='asset':media.add(entity)
            elif kind in('coach','coach_card'):
                if entity not in {str(r.get('coach_id',r.get('id')))for r in wanted.get('coaches',[])}:
                    raise ValueError('待补齐教练未登记：'+entity)
            else:raise ValueError('无法证明待补齐实体的资源归属：'+str(value))
    selected_routes|=selected&set(routes)
    selected|=selected_routes
    if not selected<=players.keys():raise ValueError('美术绑定缺少球员归属')
    return ({k:players[k]for k in sorted(selected)},[routes[k]for k in sorted(selected_routes)],
            [suites[k]for k in sorted(selected_suites)],package_roots,media,pending)


def _raw(value):
    if isinstance(value,FilePayload):
        with value.open()as stream:return stream.read()
    return value


class _BytesData:
    def __init__(self,raw):self.raw=raw;self.bytes=len(raw)
    def open(self):return io.BytesIO(self.raw)


class _Index:
    def __init__(self):
        self.providers=collections.defaultdict(list);self.paths=collections.defaultdict(list)
        self.containers=[];self.hashes={}
    def add(self,container,label,excluded=()):
        excluded=set(excluded);chunks=collections.defaultdict(dict);metadata={}
        for i,cid in enumerate(container.chunk_ids):
            pid=int.from_bytes(cid[:8],'little')
            if cid[11]!=10 and pid not in excluded:chunks[pid][cid]=i
        header=next((i for i,c in enumerate(container.chunk_ids)if c[11]==10),None)
        if header is not None:
            _,rows=read_package_header(container.read_chunk(header),strict=False)
            metadata={r['id']:r for r in rows}
        by_pid=collections.defaultdict(dict)
        for name,i in container.paths.items():
            cid=container.chunk_ids[i];pid=int.from_bytes(cid[:8],'little')
            if pid in excluded:continue
            name=safe_path(name.removeprefix('../../../'))
            by_pid[pid][name]=cid;self.paths[name].append((pid,cid))
        for pid,values in chunks.items():
            self.providers[pid].append(dict(container=container,label=label,chunks=values,
                                            sources={cid:(container,i)for cid,i in values.items()},
                                            metadata=metadata.get(pid),paths=by_pid[pid],labels={label}))
        self.containers.append(label)
    def digest(self,p,cid):
        container,index=p['sources'][cid];key=id(container),cid
        if key not in self.hashes:self.hashes[key]=hashlib.sha256(container.read_chunk(index)).digest()
        return self.hashes[key]
    def describe(self,pid):
        names=sorted({n for p in self.providers.get(pid,[])for n in p['paths']})
        return names[0]if names else str(pid)


def _same(index,a,b):
    return (a['metadata']==b['metadata']and set(a['chunks'])==set(b['chunks'])and
            all(index.digest(a,cid)==index.digest(b,cid)for cid in a['chunks']))


def _families(offers):
    """Native *_optional sidecars are chunks of their same-name main package."""
    result=[dict(p,chunks=dict(p['chunks']),sources=dict(p['sources']),paths=dict(p['paths']),labels=set(p['labels']))for p in offers if p['metadata']is not None]
    for p in offers:
        if p['metadata']is not None:continue
        family=p['label'].removesuffix('_optional')
        matches=[q for q in result if q['label']==family]
        if len(matches)==1 and p['label'].endswith('_optional'):
            q=matches[0]
            for name,cid in p['paths'].items():
                if name in q['paths']and q['paths'][name]!=cid:
                    raise ValueError('optional 资源同路径已有不同原生编号：'+name)
            for cid in set(q['chunks'])&set(p['chunks']):
                before={n for n,c in q['paths'].items()if c==cid}
                after={n for n,c in p['paths'].items()if c==cid}
                path=next(iter(sorted(before|after)),cid.hex())
                a,ai=q['sources'][cid];b,bi=p['sources'][cid]
                if before!=after or a.read_chunk(ai)!=b.read_chunk(bi):
                    raise ValueError('optional 资源同 chunk 编号已有不同内容或路径：'+path)
            for cid,index in p['chunks'].items():
                if cid not in q['chunks']:
                    q['chunks'][cid]=index;q['sources'][cid]=p['sources'][cid]
            q['paths'].update(p['paths']);q['labels']|=p['labels']
        else:result.append(p)
    return result


def _read_source(archive,member,key,folder):
    toc=folder/(str(len(list(folder.glob('*.utoc'))))+'.utoc')
    toc.write_bytes(archive.read(member+'.utoc'))
    payload=archive.payload(member+'.ucas')if hasattr(archive,'payload')else None
    if not isinstance(payload,FilePayload):payload=FilePayload.from_zip(archive,member+'.ucas')
    return Container(toc,key,data=payload)


def _suite_prefix(row):
    kind=int(str(row['nativeType']),16)
    return f'{kind>>4:02d}{kind&15:02d}_{row["variant"]}_'


def _roots(players,routes,suites,index,media_names,full_index=None):
    # Same numeric/prefix ownership rule as content_delta_v2.dependency_map,
    # indexed once rather than rescanning the entire native library per card.
    from native_models import person_keys,resolve_face
    paths={name:values[0][1]for name,values in index.paths.items()}
    model_paths={name:values[0][1]for name,values in(full_index or index).paths.items()}
    numeric=collections.defaultdict(set);prefix_index=collections.defaultdict(set)
    small=collections.defaultdict(set);faces_by_family=collections.defaultdict(list)
    for name,chunk in paths.items():
        pid=int.from_bytes(chunk[:8],'little');stem=Path(name).stem
        for token in re.findall(r'(?<!\d)\d{4,}(?!\d)',name):numeric[token].add(pid)
        match=re.match(r'^(\d{4}_\d+_)',stem)
        if match:prefix_index[match[1]].add(pid)
        if '/RealFace/'in name or '/ui/Data/Thumbnail/Player/'in name:
            for token in re.findall(r'(?<!\d)\d{1,3}(?!\d)',stem):small[token].add(pid)
    for name in model_paths:
        stem=Path(name).stem;face=re.fullmatch(r'SK_(\d+)(?:(?:ep|lg|hi|sp)\d+v\d+)?_Face',stem)
        if '/RealFace/'in name and face:faces_by_family[face[1]].append(dict(name=stem,path=name))
    route_by={str(r['cardId']):r for r in routes};roots=set();evidence=collections.defaultdict(list)
    for cid,row in players.items():
        route=route_by.get(cid,{});value=int(cid);kind=value>>40&255
        prefix=f'{kind>>4:02d}{kind&15:02d}_{value>>28&4095}_'
        tokens={cid,str(row.get('base_id','')),str(route.get('portraitKey','')),str(route.get('modelNativeId',''))}-{''}
        pids=set(prefix_index.get(prefix,()))
        for token in tokens:pids.update(numeric.get(token,()));pids.update(small.get(token,()))
        roots|=pids
        for pid in pids:evidence[pid].append('player_card:'+cid)
    # Native 64-bit model lookup IDs encode person/variant flags. Resolve an
    # exact native face variant via the existing proven resolver rather than
    # mistaking the 64-bit card ID for the short face-family name.
    for route in routes:
        cid=str(route['cardId']);portrait=str(route.get('portraitKey',''))
        if portrait and not (numeric.get(portrait)or small.get(portrait)):
            raise ValueError('内容绑定缺少已登记头像素材：'+portrait)
        model=route.get('modelNativeId')
        if model:
            keys=set(person_keys(model));faces=[r for key in keys for r in faces_by_family.get(key,[])]
            face,info=resolve_face(faces,model)
            if face is None or not info.get('exact'):
                raise ValueError('无法证明内容绑定模型的原生资源归属：'+str(model))
            pid=int.from_bytes(model_paths[face['path']][:8],'little');roots.add(pid);evidence[pid].append('route_model:'+cid)
    selected_media=set();suite_resources=set()
    prefixes={_suite_prefix(row)for row in suites}
    for row in suites:suite_resources.update(map(str,row.get('resourceIds',[])))
    for name,cid in paths.items():
        stem=Path(name).stem
        if stem in suite_resources or any(stem.startswith(prefix)for prefix in prefixes):
            pid=int.from_bytes(cid[:8],'little');roots.add(pid);evidence[pid].append('card_suite')
    route_by={str(r['cardId']):r for r in routes}
    for name in media_names:
        stem=Path(name).stem;numeric=set(re.findall(r'(?<!\d)\d{4,}(?!\d)',name))
        wanted=stem in suite_resources or any(stem.startswith(p)for p in prefixes)
        for cid,row in players.items():
            route=route_by.get(cid,{})
            tokens={cid,str(row.get('base_id','')),str(route.get('portraitKey',''))}-{''}
            if tokens&numeric:wanted=True
        if wanted:selected_media.add(name)
    for row in suites:
        prefix=_suite_prefix(row);resources=set(map(str,row.get('resourceIds',[])))
        if resources and not any(Path(n).stem in resources or Path(n).stem.startswith(prefix)for n in[*paths,*selected_media]):
            raise ValueError('缺少已登记卡面模板资源：'+prefix)
    return roots,evidence,selected_media


def merge_material_assets(archive,refs,library,key,work,previous,wanted,needed,personal):
    """Return only required native additions and selected-media audit paths.

    Existing source chunks/paths/package imports are immutable. New packages
    (all bulk chunks included) are appended to the already mounted pc3700.
    Required conflicts fail with a concrete asset path before any append.
    """
    players,routes,suites,pending_roots,pending_media,pending=_selection(previous,wanted,needed)
    folder=Path(work)/'entity-assets';folder.mkdir()
    sources=folder/'source';sources.mkdir()
    source=_Index();donor=_Index();target=None
    release_name=PREFIX+'release-manifest.json'
    if release_name not in archive.namelist():raise ValueError('来源缺少已核对的原生容器清单')
    release=json.loads(archive.read(release_name));listed={PREFIX+r['path']for r in release['files']}
    for name in archive.namelist():
        if not name.endswith('.utoc')or name[:-5]+'.ucas'not in archive.namelist():continue
        allowed=re.fullmatch(r'assets/(?:global|pc\d{4,5}_mobile_and(?:_optional)?)\.utoc',name)or(
            name in listed and re.fullmatch(re.escape(PREFIX)+r'(?:livedata|custom-resources/legends-v10)/pc\d{4,5}_mobile_and(?:_optional)?\.utoc',name))
        if not allowed:raise ValueError('来源原生容器不在已核对范围：'+name)
        member=name[:-5];container=_read_source(archive,member,key,sources)
        source.add(container,member)
        if member==STEM:target=container
    if target is None:raise ValueError('来源缺少已挂载的 pc3700 原生内容容器')
    canonical={}
    for path in sorted(Path(library.containers).glob('*.utoc')):
        stem=path.stem.removesuffix('_10_P')
        if stem not in canonical or path.stem.endswith('_10_P'):canonical[stem]=path
    excluded=set()
    if personal.get('players'):
        from personal_source import ownership,owned_art_paths
        owners=list(ownership(personal).values())
    else:owners=[]
    incoming_tocs={Path(name).stem:name for name in refs if name.endswith('.utoc')}
    incoming_folder=folder/'incoming';incoming_folder.mkdir()
    for stem in sorted(set(canonical)|set(incoming_tocs)):
        if stem in incoming_tocs:
            member=incoming_tocs[stem];data_name=member[:-5]+'.ucas'
            if data_name not in refs:raise ValueError('已验证内容缺少对应 UCAS：'+member)
            path=incoming_folder/(stem+'.utoc');path.write_bytes(_raw(refs[member]))
            data=refs[data_name]
            container=Container(path,key,data=data if isinstance(data,FilePayload)else _BytesData(data))
        else:
            path=canonical[stem]
            if not path.with_suffix('.ucas').is_file():raise ValueError('内容缓存缺少 UCAS：'+path.name)
            container=Container(path,key)
        omit=set()
        if stem=='pc3700_mobile_and'and owners:
            omit={int.from_bytes(container.chunk_ids[i][:8],'little')for i in owned_art_paths(container,owners)}
            excluded|=omit
        donor.add(container,stem,omit)
    incoming_labels={Path(name).stem for name in refs if name.endswith('.utoc')}
    incoming=_Index()
    for pid,offers in donor.providers.items():
        for p in offers:
            if p['label']not in incoming_labels:continue
            for name,cid in p['paths'].items():incoming.paths[name].append((pid,cid))
    media_names={n for n in refs if n.startswith('assets/card-designer/')}
    roots,evidence,media=_roots(players,routes,suites,incoming,media_names,full_index=donor)
    roots|=pending_roots
    for pid in pending_roots:evidence[pid].append('pending_native_package')
    media|=pending_media
    for name in media:
        safe_path(name)
        if name not in refs or not name.startswith('assets/card-designer/'):
            raise ValueError('待补齐媒体缺少已验证来源归属：'+name)
        if name in archive.namelist()and archive.read(name)!=_raw(refs[name]):
            raise ValueError('所需内容媒体与来源不同，未覆盖：'+name)
    queue=collections.deque(sorted(roots));closure=set();chosen={};retained=set();external={}
    while queue:
        pid=queue.popleft()
        if pid in closure:continue
        closure.add(pid);all_offers=_families(donor.providers.get(pid,[]));existing=_families(source.providers.get(pid,[]))
        for provider in all_offers:
            for name,cid in provider['paths'].items():
                if any(old_cid!=cid for _,old_cid in source.paths.get(name,[])):
                    raise ValueError('所需资源同路径已有不同原生编号：'+name)
        offers=[p for p in all_offers if p['labels']&incoming_labels]
        if not offers and not existing and all_offers:
            # Companion/base cache records are already mounted external native
            # dependencies. They are not imported additions and are never
            # copied into pc3700 or assigned an invented mount precedence.
            if not any(p['metadata']is not None for p in all_offers):
                raise ValueError('原版依赖缺少主包 package-store：'+donor.describe(pid))
            external[pid]=[dict(containers=sorted(p['labels']),paths=sorted(p['paths']))for p in all_offers]
            for p in all_offers:
                if p['metadata']is not None:queue.extend(p['metadata']['imports'])
            continue
        if not offers:offers=all_offers
        if not offers:
            if not existing:raise ValueError('所需内容依赖缺少已验证资源：'+str(pid))
            offered=existing[0]
            if offered['metadata']is None:raise ValueError('所需依赖缺少 package-store：'+source.describe(pid))
            if any(not _same(source,offered,p)for p in existing[1:]):
                raise ValueError('来源中所需资源有多个不同版本：'+source.describe(pid))
        else:
            offered=offers[0]
            if offered['metadata']is None:raise ValueError('内容依赖缺少 package-store：'+donor.describe(pid))
            if not existing and any(not _same(donor,offered,p)for p in offers[1:]):
                raise ValueError('所需缓存资源有多个不同版本：'+donor.describe(pid))
            # The same ID and bytes are required, including all bulk chunks
            # and the package-store import list; source modifications outside
            # this selected closure never enter this comparison.
            for old in existing:
                # Base and patch containers legitimately carry different
                # versions of one PID. Compare each source provider with its
                # corresponding donor container, preserving every original
                # mounted version; do not invent cross-container precedence.
                matching=[p for p in offers if p['label']==Path(old['label']).name]
                if not matching:matching=offers
                structurally=[p for p in matching if old['metadata']==p['metadata']and set(old['chunks'])==set(p['chunks'])]
                if not structurally:
                    raise ValueError('所需资源依赖或 chunk 身份与来源不同：'+donor.describe(pid))
                if not any(all(source.digest(old,cid)==donor.digest(p,cid)for cid in p['chunks'])for p in structurally):
                    raise ValueError('所需资源内容与来源不同，未覆盖：'+donor.describe(pid))
            for p in offers:
                for name,cid in p['paths'].items():
                    if any(other!=cid for _,other in donor.paths.get(name,[])):
                        raise ValueError('所需缓存资源同路径有不同原生编号：'+name)
                    if any(old_cid!=cid for _,old_cid in source.paths.get(name,[])):
                        raise ValueError('所需资源同路径已有不同原生编号：'+name)
        if existing:retained.add(pid)
        else:chosen[pid]=offered
        for p in existing or[offered]:queue.extend(p['metadata']['imports'])
    # Every new dependency must have a package identity (type 2); no orphan
    # bulk chunk is copied merely because its container was present in cache.
    for pid,p in chosen.items():
        if not any(cid[11]==2 for cid in p['chunks']):raise ValueError('新增资源缺少主包 chunk：'+donor.describe(pid))
    additions=[];new_paths={};metadata=[]
    for pid,p in sorted(chosen.items()):
        positions={}
        for cid,i in sorted(p['chunks'].items()):
            positions[cid]=len(additions);container,index=p['sources'][cid];additions.append((cid,container.read_chunk(index)))
        for offer in[p]:
            for name,cid in offer['paths'].items():new_paths[name]=positions[cid]
        metadata.append(p['metadata'])
    replacements={}
    if additions:
        output=folder/'merged.utoc'
        append_container(target,output,additions,new_paths,metadata)
        replacements.update({STEM+ext:FilePayload.from_path(output.with_suffix(ext))for ext in('.utoc','.ucas')})
    # Nontrivial changed PAK snapshots have no inspected chunk ownership map.
    # Do not silently dismiss them as IoStore wrappers. The 365-byte empty
    # mount PAKs are still compared when actually required by a new package.
    labels={p['label']for p in chosen.values()}
    for name,value in refs.items():
        if not name.endswith('.pak'):continue
        stem=Path(name).stem;required=stem in labels or stem=='pc3700_mobile_and'and bool(additions)
        if not required:continue
        if name in archive.namelist():
            if archive.read(name)!=_raw(value):raise ValueError('所需原生 PAK 与来源不同，未覆盖：'+name)
        elif len(_raw(value))>365:
            raise ValueError('新增 PAK 缺少可核对的资源归属，未复制：'+name)
    main_new={pid for pid,offers in donor.providers.items()if pid not in source.providers and
              any(p['label']=='pc3700_mobile_and'for p in offers)}
    report=dict(revision='entity-scoped-native-assets-v1',selected_player_ids=sorted(players),
                selected_route_ids=[r['cardId']for r in routes],selected_suite_keys=[list(_suite_key(r))for r in suites],
                pending_entities=pending,root_package_ids=sorted(roots),
                root_evidence={str(pid):sorted(set(values))for pid,values in evidence.items()},
                required_package_ids=sorted(closure),retained_source_packages=sorted(retained),
                added_package_ids=sorted(chosen),added_native_chunks=len(additions),
                external_native_dependencies={str(pid):values for pid,values in sorted(external.items())},
                excluded_personal_package_ids=sorted(excluded),
                unselected_new_main_packages=[dict(id=pid,path=donor.describe(pid))for pid in sorted(main_new-closure)],
                media_paths=sorted(media),source_existing_containers_preserved=True,
                source_package_conflicts_checked_only_in_required_closure=True)
    return replacements,report
