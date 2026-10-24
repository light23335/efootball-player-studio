"""Clone inspected UE4 packages and compile personal RGBA textures."""
from pathlib import Path
import io
import json
import struct

from native_iostore import Container,package_id,package_names,rename_package,export_rebindings,read_package_header
from native_appearance import face_skin,original_face_skin


def logical_package(path):
    prefix='../../../PesMobile/Content/'
    return '/Game/'+path.removeprefix(prefix).removesuffix('.uasset')


class Assets:
    def __init__(self,folder):
        folder=Path(folder);key=(folder/'resource-key.bin').read_bytes()
        self.files={};self.stores={};self.containers=[]
        self.face_cache={}
        # User APK patch containers override the companion's base packages.
        for path in sorted(folder.glob('*.utoc'),key=lambda p:('_P' in p.stem,p.name)):
            if path.stem=='global':continue
            container=Container(path,key);self.containers.append(container)
            for name,index in container.paths.items():self.files[name]=(container,index)

    def get(self,path):
        if path.startswith('/Game/'):path='../../../PesMobile/Content/'+path[6:]+'.uasset'
        elif not path.startswith('../../../'):path='../../../'+path
        if path not in self.files:raise ValueError('原版资源缺失：'+path)
        container,index=self.files[path]
        return container.read_chunk(index),self.metadata(container,container.chunk_ids[index])

    def face(self,path):
        """Select this exact face's complete skinning, not a later LOD-only copy.

        The stock client's mount/quality selection is not alphabetical. A
        later pc3700 copy can contain only match geometry whereas pc3600 has
        the original animated close-up LOD. Never substitute another face.
        """
        from native_skeletal import face_details
        if path.startswith('/Game/'):path='../../../PesMobile/Content/'+path[6:]+'.uasset'
        elif not path.startswith('../../../'):path='../../../'+path
        if path in self.face_cache:return self.face_cache[path]
        candidates=[];errors=[]
        for priority,container in enumerate(self.containers):
            if path not in container.paths:continue
            index=container.paths[path];raw=container.read_chunk(index)
            try:details=face_details(raw)
            except (ValueError,struct.error) as exc:
                errors.append(container.path.name+': '+str(exc));continue
            rank=(details['facial_bones'],details['highest_vertices'],details['lods'],priority)
            candidates.append((rank,raw,container,index,details))
        if not candidates:raise ValueError('无法读取此原版脸模的骨架和网格档位：'+path+('；'+errors[0] if errors else ''))
        _,raw,container,index,details=max(candidates,key=lambda c:c[0])
        result=(raw,self.metadata(container,container.chunk_ids[index]),dict(details,container=container.path.name))
        self.face_cache[path]=result
        return result

    def metadata(self,container,chunk_id):
        key=str(container.path)
        if key not in self.stores:
            index=next(i for i,c in enumerate(container.chunk_ids) if c[11]==10)
            _,packages=read_package_header(container.read_chunk(index),strict=False)
            self.stores[key]={p['id']:p for p in packages}
        return dict(self.stores[key][int.from_bytes(chunk_id[:8],'little')])


def texture(raw,name,image):
    """Replace the single cooked platform stream with an inline RGBA mip.

    The native texture's property prefix and sRGB/normal settings are retained.
    External source mips are discarded, so the new package is self contained.
    """
    from PIL import Image
    if not isinstance(image,Image.Image):image=Image.open(io.BytesIO(image))
    image=image.convert('RGBA')
    w,h=image.size
    if not 1<=w<=4096 or not 1<=h<=4096:raise ValueError('Native texture dimensions exceed the supported range')
    names=package_names(raw)
    formats=[n for n in names if n.startswith('PF_')]
    if len(formats)!=1:raise ValueError('Expected one original cooked pixel format')
    raw,metadata=rename_package(raw,name,{formats[0]:'PF_B8G8R8A8'})
    names=package_names(raw);summary=struct.unpack_from('<16I',raw)
    marker=formats[0].encode()+b'\0'
    at=raw.find(marker,summary[13]+summary[14])
    if at<0 or raw.find(marker,at+1)>=0:raise ValueError('Could not locate unique native texture platform data')
    start=at-16
    # ImportedSize is consumed independently of the cooked mip dimensions.
    # Keep both in agreement, especially when using a 128px UI template.
    if 'ImportedSize' in names and 'IntPoint' in names:
        marker_size=struct.pack('<II',names.index('ImportedSize'),0)
        prop=raw.find(marker_size,summary[13]+summary[14],start)
        if prop>=0:
            if (struct.unpack_from('<I',raw,prop+8)[0]!=names.index('StructProperty') or
                struct.unpack_from('<I',raw,prop+16)[0]!=8 or
                struct.unpack_from('<I',raw,prop+24)[0]!=names.index('IntPoint')):raise ValueError('Native imported texture size layout changed')
            payload=prop+49
            if raw[prop+48]==1:payload+=16
            elif raw[prop+48]!=0:raise ValueError('Native imported texture size GUID changed')
            updated=bytearray(raw);struct.pack_into('<II',updated,payload,w,h);raw=bytes(updated)
    if struct.unpack_from('<i',raw,at-4)[0]!=len(marker):raise ValueError('Invalid native pixel-format string')
    exports=(summary[12]-summary[11])//72
    if exports!=1:raise ValueError('Only single-export texture packages have been verified')
    export_at=summary[11]
    absolute_delta=struct.unpack_from('<Q',raw,export_at)[0]-(summary[13]+summary[14])
    fmt=b'PF_B8G8R8A8\0'
    header=struct.pack('<iii',w,h,1)+struct.pack('<i',len(fmt))+fmt+struct.pack('<6Iq',0,1,1,0x48,w*h*4,w*h*4,0)
    pixels_at=start+len(header)
    header=header[:-8]+struct.pack('<q',pixels_at+absolute_delta)
    pixels=image.tobytes('raw','BGRA')
    body=header+pixels+struct.pack('<iiii',w,h,1,0)+struct.pack('<II',names.index('None'),0)
    result=bytearray(raw[:start]+body)
    struct.pack_into('<q',result,start-8,len(result)-8+absolute_delta)
    struct.pack_into('<Q',result,export_at+8,struct.unpack_from('<Q',raw,export_at+8)[0]+len(result)-len(raw))
    return bytes(result),metadata


def clone_group(packages,renames,overrides=None):
    """Rebind every public object import and package dependency in a group."""
    changes={}
    for old,new in renames.items():changes[old]=new;changes[old.rsplit('/',1)[-1]]=new.rsplit('/',1)[-1]
    ids={package_id(old):package_id(new) for old,new in renames.items()}
    hashes={}
    for old,(raw,meta) in packages.items():hashes.update(export_rebindings(raw,renames[old],changes))
    result=[]
    for old,(raw,meta) in packages.items():
        raw=(overrides or {}).get(old,raw)
        encoded,newmeta=rename_package(raw,renames[old],changes,hashes,ids)
        newmeta.update(imports=[ids.get(i,i) for i in meta['imports']],bundles=meta['bundles'])
        result.append((renames[old],encoded,newmeta))
    return result


def verify_portrait_locations(packages,binding):
    """Check both independently loaded UI paths before an APK is published."""
    prefix='/Game/Assets/ui/Data/Thumbnail/Player/'
    names=[p[0] for p in packages]
    if len(names)!=len(set(names)):raise ValueError('个人美术资源路径重复，未生成 APK')
    required={binding['asset_key']+'_',binding['asset_key']+'f',*binding.get('card_aliases',{}).values()}
    missing=[prefix+folder+name for folder in ('','Variation2022/') for name in sorted(required)
             if prefix+folder+name not in names]
    if missing:raise ValueError('卡面或抽卡动画资源缺失：'+', '.join(missing))
    return {'root':True,'Variation2022':True,'textures_per_location':len(required)}


def compile_art(project,identity,library,rigged_path=None,reference_path=None,mesh_metadata=None,asset_key=None):
    from PIL import Image,ImageFont,ImageDraw
    from native_glb import Glb,prove_binding
    from native_mesh import replace_head
    assets=Assets(library.containers);person=str(asset_key or identity['person_id']);cid=str(identity['card_id'])
    result=[];report={};card=project['native_card'];appearance=project['appearance']
    model=project.get('model') or {};native_face=None
    if (model.get('native_source') or {}).get('path'):
        path=model['native_source']['path']
        try:
            raw,meta,report['face_source']=assets.face(path)
            raw,report['skin_tone']=original_face_skin(raw,model,library.resources,
                                                      (project.get('source_player') or {}).get('id'))
            native_face=(raw,meta,path)
        except (ValueError,OSError) as exc:
            raise ValueError(project['identity']['name']+'：'+str(exc)) from exc
    portrait=appearance.get('portrait')
    if not portrait or appearance.get('hide_portrait'):raise ValueError('请先选择需要实装的球员卡图')
    base='/Game/Assets/ui/Data/Thumbnail/Player/'
    template,_=assets.get('/Game/Assets/character/RealFace/56321_')
    from native_thumbnail import card_portrait
    canvas=card_portrait(project,library.store.root/'assets')
    def add_texture(name,pixels,original=template):
        # Native UI cards and Blueprint acquisition cards do not share the
        # final-path converter. LoadCardFileFront appends Variation2022/ for
        # special cards (V13 0x38854b0); the native UI uses the root folder.
        # Publish real packages in both locations, including the F07 portrait
        # and the layers resolved through filenameConvTable.csv.
        for folder in ('','Variation2022/'):
            path=base+folder+name
            raw,meta=texture(original,path,pixels);result.append((path,raw,meta))
    from native_thumbnail import render as render_thumbnail
    from thumbnail_background import background,REVISION
    from thumbnail_motion import plan,names
    backdrop=background(project,library)
    mini_portrait=card_portrait(project,library.store.root/'assets',include_underlay=False) if appearance.get('thumbnail_mode','card')=='card' else None
    foreground=render_thumbnail(project,library.store.root/'assets',mini_portrait)
    # Use the actual MobileIcon texture contract, not the RealFace 512px
    # portrait template. User crop coordinates remain in the 512px canvas.
    mini_template,_=assets.get('/Game/Assets/ui/Data/Thumbnail/Player/100012_')
    backdrop=backdrop.resize((128,128),Image.Resampling.LANCZOS)
    foreground=foreground.resize((128,128),Image.Resampling.LANCZOS)
    flat=backdrop.copy();flat.alpha_composite(foreground);add_texture(person+'_',flat,mini_template)
    add_texture(person+'_b',backdrop,mini_template);add_texture(person+'_m',foreground,mini_template)
    motion=plan(project,library)
    report['thumbnail']={'background_linked':True,'revision':motion['revision'],'mode':appearance.get('thumbnail_mode','card'),
                         'animation':motion,'static_fallback':True,'separate_foreground':True,'native_size':[128,128]}
    # The detail card and contract animation request the native 'f' portrait,
    # while squad thumbnails request '_'. Both names must be real packages.
    clear=Image.new('RGBA',(4,4))
    add_texture(person+'_clear',clear)
    aliases={}
    style=card['native_style']
    for slot in ('f04','f06','f09'):
        if slot=='f04' and not card.get('preset_id'):continue
        aliases[f'{style}_{slot}_{cid}_']=person+'_clear'
    date=appearance.get('card_date') or ''
    full_portrait=canvas.copy()
    if card['card_type']=='BigTime' and date and appearance.get('card_date_visible') is not False:
        import datetime
        day=datetime.date.fromisoformat(date)
        label=f"{day.day} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][day.month-1]} '{day.year%100:02d}"
        fontfile=library.store.root/'assets'/card['fonts']['sans']['asset_id']
        # Native UMG date placement is expressed in the same 268 x 384 units.
        box=card['ui']['widgets']['Text_Date'];factor=1200/268
        font=ImageFont.truetype(str(fontfile),round(box['size']*96/72*factor))
        date_image=Image.new('RGBA',canvas.size);draw=ImageDraw.Draw(date_image)
        draw.text(((box['x']+box['w']/2)*factor,(box['y']+box['h']/2)*factor),label,font=font,anchor='mm',fill='white',stroke_width=1,stroke_fill=(0,0,0,76))
        full_portrait.alpha_composite(date_image)
        add_texture(person+'_date',date_image.resize((512,512),Image.Resampling.LANCZOS))
        aliases[f'{style}_f09_{cid}_']=person+'_date'
    # F07 is PlayerImage in BP_PlayerAcquisitionCard.SetPlayerImage. F06 is
    # another card decoration layer; it must not receive a second portrait.
    add_texture(person+'f',full_portrait.resize((512,512),Image.Resampling.LANCZOS))
    binding={'appearance_id':int(card['source_id']),'portrait_name':person+'_','asset_key':person,'card_aliases':aliases,
             'thumbnail_names':names(person,motion)}
    report['portrait_locations']=verify_portrait_locations(result,binding)
    if not model.get('asset'):raise ValueError('请先载入游戏原版脸模或已绑定 V13 骨架的自制 GLB')
    if native_face:
        raw,meta,path=native_face
        from native_skeletal import allow_closeup_lod
        raw,report['closeup_lod']=allow_closeup_lod(raw)
        target='/Game/Assets/character/RealFace/SK_'+person+'_Face'
        encoded,newmeta=rename_package(raw,target)
        newmeta.update(imports=meta['imports'],bundles=meta['bundles'])
        result.append((target,encoded,newmeta))
        report.update(native_packages=len(result),model='original-game-face',source=path,
                      original_video_resources_preserved=True,in_game_tested=False)
        return result,binding,report
    static=Glb((library.store.root/'assets'/model['asset']).read_bytes())
    if not rigged_path:
        bound=static
    else:
        bound=Glb(Path(rigged_path).read_bytes());report['binding_proof']=prove_binding(static,bound)
    if not reference_path or not mesh_metadata:raise ValueError('尚未准备已核对的 V13 脸模骨架模板')
    reference=Glb(Path(reference_path).read_bytes())
    from rig_compatibility import adapt_skeleton
    bound,report['rig_compatibility']=adapt_skeleton(bound,reference)
    source=next(c for c in assets.containers if c.path.stem=='pc3600_mobile_and')
    face='/Game/Assets/character/RealFace/'
    original=source.read('../../../PesMobile/Content/Assets/character/RealFace/SK_133543_Face.uasset')
    original_meta=assets.metadata(source,struct.pack('<QHBB',package_id(face+'SK_133543_Face'),0,0,2))
    converted,report['mesh']=replace_head(original,bound,reference,mesh_metadata,model.get('neck_seam') is not False,model.get('head_vertical_cm',0),model.get('preserve_expression') is not False,model.get('binding_handles'))
    from native_skeletal import allow_closeup_lod
    converted,report['closeup_lod']=allow_closeup_lod(converted)
    packages={face+'SK_133543_Face':(original,original_meta)}
    for name in ['MI_133543_Head_FaceUpcon_HQ','MI_133543_Head_FaceUpcon_MQ','T_133543_Face_D','T_133543_Face_N','T_133543_Face_SRO']:
        packages[face+name]=assets.get(face+name)
    renames={name:name.replace('133543',person) for name in packages}
    overrides={face+'SK_133543_Face':face_skin(converted,model.get('skin_tone'))}
    maps={'D':Image.open(io.BytesIO(static.image())).convert('RGBA'),
          'N':Image.new('RGBA',(4,4),(128,128,255,255)),
          'SRO':Image.new('RGBA',(4,4),(64,160,255,255))}
    for name,raw,meta in clone_group(packages,renames,overrides):
        if name.startswith(face+'T_'+person+'_Face_'):
            raw=texture(raw,name,maps[name.rsplit('_',1)[-1]])[0]
        result.append((name,raw,meta))
    report.update(native_packages=len(result),portrait_pixels=[512,512],card_aliases=len(aliases),
                  face_texture_pixels=list(maps['D'].size),face_materials='own diffuse and neutral normal/SRO',
                  original_video_resources_preserved=True,in_game_tested=False)
    return result,binding,report
