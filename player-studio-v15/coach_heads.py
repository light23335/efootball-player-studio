"""Inspect and replace existing manager face packages; never guess a new coach route."""
from export_errors import call as _export_data
from export_errors import export_context, exported
from pathlib import Path
import copy,hashlib,io,json,os,re,threading,uuid

FOLDER='PesMobile/Content/Assets/character/DemoFace/Manager/'
TARGET=re.compile(re.escape(FOLDER)+r'SK_\d+(?:sp\d+v\d+)?_Face\.uasset\Z')
ASSET=re.compile(r'[a-f0-9]{64}\.glb\Z')
REVISION='coach-head-v2-lod-materials'


def target_path(value):
    if not isinstance(value,str) or not TARGET.fullmatch(value):raise ValueError('请选择资源库中的教练头模')
    return value


def normalize(value):
    if not isinstance(value,dict):raise ValueError('教练头模配置无效')
    target=target_path(value.get('target'))
    mode=value.get('mode')
    if mode not in ('native','custom'):raise ValueError('教练头模替换方式无效')
    row={'target':target,'mode':mode}
    if mode=='native':row['source']=target_path(value.get('source'))
    else:
        asset=value.get('asset_id')
        if not isinstance(asset,str) or not ASSET.fullmatch(asset):raise ValueError('请导入完整的 GLB 教练头模')
        row['asset_id']=asset
    return row


class CoachHeadStore:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'coach-heads.json';self.lock=threading.RLock()

    def list(self):
        with self.lock:
            if not self.path.exists():return []
            doc=_export_data("资料文件",self.path,"读取并解析 JSON",lambda: json.loads(self.path.read_text(encoding='utf8')))
            if doc.get('version')!=1 or not isinstance(doc.get('rows'),list):raise ValueError('教练头模配置版本无效')
            rows=[normalize(r) for r in doc['rows']]
            if len({r['target'] for r in rows})!=len(rows):raise ValueError('教练头模配置包含重复目标')
            return rows

    def write(self,rows):
        rows=[normalize(r) for r in rows]
        if self.path.exists():
            backup=self.root/'backups';backup.mkdir(exist_ok=True)
            (backup/('coach-heads-'+uuid.uuid4().hex+'.json')).write_bytes(self.path.read_bytes())
        temporary=self.path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('w',encoding='utf8') as f:
            json.dump({'version':1,'rows':rows},f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        temporary.replace(self.path)

    def save(self,row):
        row=normalize(row)
        with self.lock:self.write([r for r in self.list() if r['target']!=row['target']]+[row])
        return row

    def delete(self,target):
        target=target_path(target)
        with self.lock:self.write([r for r in self.list() if r['target']!=target])


def catalogue(library,coaches):
    if library.state['phase']!='ready':return {'ready':False,'rows':[],'saved':CoachHeadStore(library.store.root).list()}
    paths=sorted({p.removeprefix('../../../') for p in library.face_assets().files if TARGET.fullmatch(p.removeprefix('../../../'))})
    rows=[]
    for path in paths:
        name=Path(path).stem;match=re.fullmatch(r'SK_(\d+)(?:sp\d+v(\d+))?_Face',name)
        base=int(match[1]);variant=int(match[2] or 0)
        # IDs encode the person in their low 28 bits and the card variant above.
        # This labels candidates, not a claim that every stock loader uses this route.
        matches=[c for c in coaches if int(c['id'])&0xfffffff==base and ((int(c['id'])>>28)&4095)==variant]
        family=[c for c in coaches if int(c['id'])&0xfffffff==base]
        label=next((c.get('name') or c.get('name_en') for c in matches or family),'未匹配姓名')
        rows.append({'path':path,'name':name,'label':label,'variant':variant,'coach_ids':[str(c['id']) for c in matches]})
    return {'ready':True,'rows':rows,'saved':CoachHeadStore(library.store.root).list()}


def require_path(library,path):
    path=target_path(path)
    if library.state['phase']!='ready':raise ValueError('请先准备游戏资源，再查看教练头模')
    if '../../../'+path not in library.face_assets().files:raise ValueError('当前版本资源库没有这个教练头模，请重新选择')
    return path


def original(library,path):
    path=require_path(library,path)
    key=REVISION+':'+path
    cached=library.cache.get(key)
    if cached and (library.store.root/'assets'/cached['asset_id']).is_file():return cached
    with library.convert_lock:
        target,details=library.convert_face({'path':path})
        target,materials=library.texture_model(target,{'path':path})
        asset=library.store.import_asset(target,'model')
        result={'asset_id':asset['id'],'url':asset['url'],'path':path,**details,**materials}
        library.cache[key]=result
        library.cache_path.write_text(json.dumps(library.cache,ensure_ascii=False,indent=2),encoding='utf8')
        return result


def opaque_materials(source):
    """An opaque face's packed alpha is not hair opacity when atlasing."""
    from PIL import Image
    from glb_import import encode
    from native_glb import Glb
    doc=copy.deepcopy(source.doc);binary=bytearray(source.binary)
    for index,material in enumerate(doc.get('materials',[])):
        if material.get('alphaMode','OPAQUE')!='OPAQUE':continue
        pbr=material.get('pbrMetallicRoughness',{});tex=pbr.get('baseColorTexture')
        if not tex:continue
        primitive={'material':index}
        image=Image.open(io.BytesIO(source.image(primitive))).convert('RGBA');image.putalpha(255)
        buffer=io.BytesIO();image.save(buffer,format='PNG');raw=buffer.getvalue()
        binary.extend(bytes(-len(binary)%4));offset=len(binary);binary.extend(raw)
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(raw)})
        image_index=len(doc.setdefault('images',[]));doc['images'].append({'bufferView':view,'mimeType':'image/png'})
        texture_index=len(doc.setdefault('textures',[]));doc['textures'].append({'source':image_index})
        tex['index']=texture_index
        if 'baseColorFactor' in pbr:pbr['baseColorFactor'][3]=1
    return Glb(encode(doc,binary))


def lod_material_bindings(mesh,materials,lod_count):
    """Resolve the material of the generated section zero as UE does at each LOD.

    A cooked LODMaterialMap can redirect section zero to e.g. slot three.
    Replacing just SkeletalMaterials[0] leaves the default mobile LOD sampling
    stock face textures with the imported atlas's UVs.
    """
    infos=mesh.get('Properties',{}).get('LODInfo')
    if not isinstance(infos,list) or len(infos)!=lod_count:raise ValueError('教练模型精度档位的材质资料不完整')
    result=[]
    for level,info in enumerate(infos):
        mapping=info.get('LODMaterialMap',[])
        slot=mapping[0] if mapping and mapping[0]>=0 else 0
        if type(slot) is not int or not 0<=slot<len(materials):raise ValueError('教练模型精度档位的材质索引无效')
        result.append({'lod':level,'section':0,'material_slot':slot,'source_material':materials[slot]['extras']['studio_material_path']})
    return result


def compile_head(library,value,destination=None):
    """Build real cooked packages for an existing manager path, plus read-back proof."""
    from native_art import logical_package,clone_group,texture
    from native_iostore import rename_package,package_names
    from native_skeletal import mesh_glb,face_details
    row=normalize(value);target=require_path(library,row['target']);assets=library.face_assets()
    target_name=logical_package(target if target.startswith('../../../') else '../../../'+target)
    output_name=destination or target_name
    if destination is not None and not re.fullmatch(r'/Game/Assets/character/DemoFace/Manager/SK_[6-9]\d{5}_Face',destination):raise ValueError('个人教练模型目标编号无效')
    report={'target':target,'mode':row['mode'],'in_game_tested':False,'shared_resource_replacement':True}
    if row['mode']=='native':
        source=require_path(library,row['source']);raw,meta,_=assets.face(source)
        encoded,newmeta=rename_package(raw,output_name)
        newmeta.update(imports=meta['imports'],bundles=meta['bundles'])
        packages=[(output_name,encoded,newmeta)];report['source']=source
        report['destination']=output_name
        # Keep the donor's material/skeleton dependencies at their existing paths.
        preview=mesh_glb(type('Source',(),{'raw':lambda self,p:encoded})(),output_name)
        report['face']=face_details(encoded)
        return packages,report,preview,None

    from native_glb import Glb
    from rig_compatibility import adapt_skeleton
    from native_mesh import replace_head
    raw,meta,_=assets.face(target)
    reference=Glb(mesh_glb(type('Source',(),{'raw':lambda self,p:raw})(),target_name))
    file=library.store.root/'assets'/row['asset_id']
    if not file.is_file():raise ValueError('自制教练头模文件缺失，请重新导入')
    source=opaque_materials(Glb(file.read_bytes()));bound,rig=adapt_skeleton(source,reference)
    # The target coach itself is the carrier: its own skeleton, offsets and LODs remain.
    with library.convert_lock:library.run([target],'json')
    document=_export_data("资料文件",library.converted / Path(target).with_suffix('.json'),"读取并解析 JSON",lambda: json.loads((library.converted/Path(target).with_suffix('.json')).read_text(encoding='utf-8-sig')))
    mesh=next((e for e in document if e.get('Type')=='SkeletalMesh' and e.get('ImportedBounds')),None)
    if mesh is None:raise ValueError('教练头模边界资料未能解码')
    converted,mesh_report=replace_head(raw,bound,reference,mesh,neck_seam=False,preserve_expression=False)
    bindings=lod_material_bindings(mesh,reference.doc['materials'],mesh_report['lods'])
    from PIL import Image
    image=Image.open(io.BytesIO(bound.image())).convert('RGBA')
    suffix=hashlib.sha256(output_name.encode()).hexdigest()[:12]
    folder=target_name.rsplit('/',1)[0]+'/'
    group={target_name:(raw,meta)}
    renames={target_name:output_name}
    overrides={target_name:converted}
    for slot in sorted({0,*[b['material_slot'] for b in bindings]}):
        material=reference.doc['materials'][slot]
        material_path=material['extras']['studio_material_path']
        quality='MQ' if material['name'].lower().endswith('_mq') else 'HQ'
        # The atlas includes transparent hair/eyelashes. Retain masked shading
        # at both quality levels, and clone every slot the LOD map can select.
        shader_path=next((m['extras']['studio_material_path'] for m in reference.doc['materials'] if 'hair_'+quality.lower() in m['name'].lower()),None)
        if shader_path is None:
            hair=next((p for p in assets.files if '/DemoFace/Manager/MI_' in p and p.endswith('_Head_Hair_'+quality+'.uasset')),None)
            if hair:shader_path=logical_package(hair)
        if shader_path is None:raise ValueError('当前资源缺少可保留头发透明度的教练材质模板：'+quality)
        shader_raw,shader_meta=assets.get(shader_path)
        material_raw,material_meta=rename_package(shader_raw,material_path)
        material_meta.update(imports=shader_meta['imports'],bundles=shader_meta['bundles'])
        group[material_path]=(material_raw,material_meta)
        renames[material_path]=folder+'MI_StudioCoach_Hair_'+suffix+'_slot'+str(slot)
        with library.convert_lock:library.run(['PesMobile/Content/'+shader_path[6:]+'.uasset'],'json')
        mat_doc=_export_data("资料文件",library.converted / Path('PesMobile/Content/' + shader_path[6:]).with_suffix('.json'),"读取并解析 JSON",lambda: json.loads((library.converted/Path('PesMobile/Content/'+shader_path[6:]).with_suffix('.json')).read_text(encoding='utf-8-sig')))
        params=[p for e in mat_doc for p in e.get('Properties',{}).get('TextureParameterValues',[])]
        mapped={}
        for p in params:
            key=p.get('ParameterInfo',{}).get('Name','').casefold()
            ref=p.get('ParameterValue',{}).get('ObjectPath','')
            if ref.startswith('/Game/'):mapped[key]=ref.split('.')[0]
        diffuse=next((mapped[k] for k in ('basecolormap','basecolor','diffuse','diffusemap') if k in mapped),None)
        if not diffuse:raise ValueError('尚未适配此教练的面部材质参数：'+quality)
        for key,path in mapped.items():
            if path in group:continue
            if path!=diffuse and not any(v in key for v in ('normal','specular','sro')):continue
            tex_raw,tex_meta=assets.get(path);group[path]=(tex_raw,tex_meta)
            renames[path]=folder+'T_StudioCoach_'+suffix+'_'+str(len(group))
            if path==diffuse:pixels=image
            elif 'normal' in key:pixels=Image.new('RGBA',(4,4),(128,128,255,255))
            else:pixels=Image.new('RGBA',(4,4),(64,160,255,255))
            overrides[path]=texture(tex_raw,path,pixels)[0]
        for binding in bindings:
            if binding['material_slot']==slot:binding.update(material=renames[material_path],diffuse=renames[diffuse],shader_template=shader_path)
    packages=clone_group(group,renames,overrides)
    encoded=next(data for name,data,_ in packages if name==output_name)
    if output_name not in package_names(encoded):raise ValueError('教练头模资源名写回校验失败')
    preview=mesh_glb(type('Source',(),{'raw':lambda self,p:encoded})(),output_name)
    report.update(destination=output_name,asset_id=row['asset_id'],rig=rig,mesh=mesh_report,face=face_details(encoded),material_template=bindings[0]['shader_template'],lod_material_bindings=bindings,material_revision=REVISION,private_packages=list(renames.values())[1:])
    return packages,report,preview,image


def preview(library,value):
    from native_library import glb_textures
    row=normalize(value)
    if row['mode']=='native':
        result=dict(original(library,row['source']));result['report']={'mode':'native','target':row['target'],'source':row['source'],'in_game_tested':False}
        require_path(library,row['target']);return result
    packages,report,raw,image=compile_head(library,row)
    from native_glb import Glb
    doc=Glb(raw).doc
    folder=library.store.root/'tmp';folder.mkdir(exist_ok=True)
    token=hashlib.sha256(raw+row['asset_id'].encode()).hexdigest()
    path=folder/('coach-head-'+token+'.glb');path.write_bytes(raw)
    png=io.BytesIO();image.save(png,format='PNG')
    materials={m['name']:(png.getvalue(),{}) for m in doc['materials']}
    output=path.with_name(path.stem+'-textured.glb');glb_textures(path,materials,output)
    asset=library.store.import_asset(output,'model')
    return {'asset_id':asset['id'],'url':asset['url'],'report':report}


def compile_heads(library,rows):
    packages=[];reports=[];seen=set()
    for row in rows:
        with export_context('教练头模',row,'编译原版教练头模替换'):
            row=normalize(row)
            if row['target'] in seen:raise ValueError('不能同时写入两份相同目标的教练头模')
            seen.add(row['target']);art,report,_,_=compile_head(library,row);packages.extend(art);reports.append(report)
    return packages,reports


def replacement_indices(container,packages):
    from native_iostore import package_id
    ids={package_id(name) for name,_,_ in packages}
    return {i for i,chunk in enumerate(container.chunk_ids) if int.from_bytes(chunk[:8],'little') in ids and chunk[11] in (2,3,4)}


def patch_stock_containers(archive,library,packages,reports,work):
    """Replace manager copies at their original mount too, independent of mount order.

    A player patch archive alone can lose to the main pakchunk0 copy. Read each
    baseline from the chosen APK, preserving all unrelated chunks and ZIP entries.
    Companion-only faces are still supplied by the main player patch container.
    """
    import zipfile,shutil
    from native_art import logical_package
    from native_iostore import Container,append_container,read_package_header,package_header
    from native_body import container_parts
    if not packages:return {},[]
    folder=Path(work)/'coach-stock';folder.mkdir()
    key=(library.containers/'resource-key.bin').read_bytes()
    groups={}
    for report in reports:
        target=logical_package('../../../'+report['target'])
        names={target,*report.get('private_packages',[])}
        groups['../../../'+report['target']]=[p for p in packages if p[0] in names]
    patched=[];counter=0

    def patch_entries(source,names,label):
        nonlocal counter
        changes={};known=set(names)
        for member in sorted(n for n in names if n.endswith('.utoc') and Path(n).stem!='global'):
            counter+=1;stem=folder/('source-'+str(counter));index=stem.with_suffix('.utoc')
            index.write_bytes(source.read(member));container=Container(index,key)
            selected=[p for path,group in groups.items() if path in container.paths for p in group]
            if not selected:continue
            unique={p[0]:p for p in selected};selected=list(unique.values())
            ucas=member[:-5]+'.ucas'
            if ucas not in known:raise ValueError('教练原始容器缺少 UCAS：'+member)
            with source.open(ucas) as src,stem.with_suffix('.ucas').open('xb') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
            header_index=next(i for i,cid in enumerate(container.chunk_ids) if cid[11]==10)
            original_read=container.read_chunk
            header=original_read(header_index)
            cid,store=read_package_header(header,strict=False)
            canonical=package_header(cid,store)
            # Stock pakchunk0 pads this chunk to 64 KiB. The normal append
            # writer expects a canonical header; discard zero padding only.
            # Never drop redirects, names, or unknown non-zero metadata.
            if header!=canonical:
                if not header.startswith(canonical) or any(header[len(canonical):]):raise ValueError('教练原始容器含未适配的包重定向资料')
                container.read_chunk=lambda i,_read=original_read,_head=canonical,_index=header_index:_head if i==_index else _read(i)
            output=folder/('patched-'+str(counter)+'.utoc')
            additions,paths,entries=container_parts(selected)
            rebuilt=append_container(container,output,additions,paths,entries,replacement_indices(container,selected))
            # Check the exact overridden bytes, not just that the new paths exist.
            for name,data,_ in selected:
                if rebuilt.read('../../../PesMobile/Content/'+name[6:]+'.uasset')!=data:raise ValueError('教练原始容器替换读回失败')
            changes[member]=output.read_bytes();changes[ucas]=output.with_suffix('.ucas').read_bytes()
            patched.append({'archive':label,'container':member,'packages':[p[0] for p in selected]})
        return changes

    names=archive.namelist()
    # pc3700 was already rebuilt by the normal art compiler.
    top=[n for n in names if not n.startswith('assets/gateway-release/custom-resources/legends-v10/pc3700_mobile_and.')]
    replacements=patch_entries(archive,top,'APK')
    member='assets/pc0000_mobile_and.pak'
    if member in names:
        with archive.open(member) as raw,zipfile.ZipFile(raw) as nested:
            changes=patch_entries(nested,nested.namelist(),member)
            if changes:
                output=folder/'pc0000_mobile_and.pak'
                with zipfile.ZipFile(output,'w',allowZip64=True) as dest:
                    dest.comment=nested.comment
                    for entry in nested.infolist():
                        if entry.filename in changes:dest.writestr(copy.copy(entry),changes[entry.filename])
                        else:
                            with nested.open(entry) as src,dest.open(copy.copy(entry),'w') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
                replacements[member]=output.read_bytes()
    return replacements,patched
