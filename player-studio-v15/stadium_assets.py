"""Static decoration/TIFO compilation. Coordinates are local to native anchors."""
import copy,hashlib,io,json,math,struct
from pathlib import Path
import numpy as np
from PIL import Image
from native_glb import Glb
from glb_import import encode

MAX_VERTICES=200000
MAX_TRIANGLES=300000


def matte_material(raw):
    """Disable the verified carrier's environment-reflection multipliers."""
    from native_iostore import package_names
    names=package_names(raw);h=struct.unpack_from('<16I',raw);out=bytearray(raw)
    for key,expected in [('CubeMapIntensity',1.),('df_CubeMapIntensity',3000.),('drs_CubeMapIntensity',2000.),('nf_CubeMapIntensity',250.)]:
        marker=struct.pack('<II',names.index(key),0);at=raw.find(marker,h[13]+h[14])
        if at<0:raise ValueError('装置材质缺少已核对的反射参数：'+key)
        value=raw.find(struct.pack('<II',names.index('ParameterValue'),0),at,at+160)
        if value<0 or struct.unpack_from('<I',raw,value+8)[0]!=names.index('FloatProperty')or struct.unpack_from('<I',raw,value+16)[0]!=4 or raw[value+24]!=0 or struct.unpack_from('<f',raw,value+25)[0]!=expected:
            raise ValueError('装置材质标量布局改变：'+key)
        struct.pack_into('<f',out,value+25,0.)
    return bytes(out)


def matrix(node):
    if 'matrix'in node:return np.asarray(node['matrix'],float).reshape(4,4).T
    x,y,z,w=node.get('rotation',[0,0,0,1]);norm=math.sqrt(x*x+y*y+z*z+w*w)
    if norm<1e-8:raise ValueError('装置模型的旋转四元数无效')
    x,y,z,w=x/norm,y/norm,z/norm,w/norm
    r=np.array([[1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w,0],
                [2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w,0],
                [2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y,0],[0,0,0,1.]])
    r[:3,:3]*=np.asarray(node.get('scale',[1,1,1]));r[:3,3]=node.get('translation',[0,0,0])
    return r


def flatten(raw):
    source=Glb(raw);d=source.doc;nodes=d.get('nodes',[])
    if d.get('skins')or d.get('animations'):raise ValueError('场边装置使用静态 GLB；请应用姿态并移除动画和骨架后导出')
    parts=[];visited=set()
    def visit(index,parent,ancestors):
        if index in ancestors or not 0<=index<len(nodes):raise ValueError('装置模型节点存在循环或无效引用')
        node=nodes[index];world=parent@matrix(node);visited.add(index)
        if 'mesh'in node:
            for primitive in d['meshes'][node['mesh']]['primitives']:parts.append((primitive,world))
        for child in node.get('children',[]):visit(child,world,ancestors|{index})
    scene=d.get('scenes',[{}])[d.get('scene',0)]
    roots=scene.get('nodes')
    if roots is None:
        children={c for n in nodes for c in n.get('children',[])};roots=[i for i in range(len(nodes))if i not in children]
    for index in roots:visit(index,np.eye(4),set())
    if not parts or len(parts)>64:raise ValueError('装置模型需包含 1–64 个三角形网格分段')
    materials=list(dict.fromkeys(p.get('material',-1)for p,_ in parts))
    if len(materials)>32:raise ValueError('装置模型最多支持 32 个材质')
    cols=math.ceil(math.sqrt(len(materials)));rows=math.ceil(len(materials)/cols)
    tile=min(1024,4096//max(cols,rows));inner=tile-8;atlas=Image.new('RGBA',(cols*tile,rows*tile),(255,255,255,255));tiles={}
    for i,mid in enumerate(materials):
        material=d.get('materials',[])[mid]if mid>=0 else{}
        pbr=material.get('pbrMetallicRoughness',{});factor=pbr.get('baseColorFactor',[1,1,1,1])
        if len(factor)!=4 or not np.isfinite(factor).all():raise ValueError('装置材质颜色无效')
        texture=pbr.get('baseColorTexture')
        if texture:
            if texture.get('texCoord',0)!=0 or texture.get('extensions'):raise ValueError('装置贴图请烘焙至第一 UV 通道，暂不支持贴图变换扩展')
            primitive=next(p for p,_ in parts if p.get('material',-1)==mid)
            image=Image.open(io.BytesIO(source.image(primitive))).convert('RGBA')
            image=Image.fromarray(np.rint(np.asarray(image)*np.asarray(factor)).clip(0,255).astype('uint8'))
        else:image=Image.new('RGBA',(4,4),tuple(int(max(0,min(1,v))*255)for v in factor))
        # The inspected carrier is opaque. Transparency is composited against
        # the material's colour; unsupported custom shaders are not copied.
        solid=Image.new('RGBA',image.size,(255,255,255,255));solid.alpha_composite(image);image=solid.convert('RGB').convert('RGBA')
        x=i%cols*tile+4;y=i//cols*tile+4
        image=image.resize((inner,inner),Image.Resampling.LANCZOS)
        atlas.paste(image.resize((tile,tile),Image.Resampling.NEAREST),(x-4,y-4));atlas.paste(image,(x,y));tiles[mid]=(x,y)
    positions=[];normals=[];coords=[];faces=[];cursor=0
    for primitive,world in parts:
        if primitive.get('mode',4)!=4:raise ValueError('装置模型仅支持三角形')
        attrs=primitive['attributes'];p=source.read(attrs['POSITION']).astype(float)
        f=source.read(primitive['indices']).reshape(-1).astype(int)if'indices'in primitive else np.arange(len(p))
        if len(f)%3 or len(f)==0 or f.min()<0 or f.max()>=len(p):raise ValueError('装置模型三角形索引无效')
        if len(p)+cursor>MAX_VERTICES or sum(len(v)for v in faces)+len(f)//3>MAX_TRIANGLES:raise ValueError('装置模型超过 20 万顶点／30 万三角形')
        p=(np.column_stack((p,np.ones(len(p))))@world.T)[:,:3]
        f=f.reshape(-1,3)
        if np.linalg.det(world[:3,:3])<0:f=f[:,::-1]
        if'NORMAL'in attrs:
            try:n=source.read(attrs['NORMAL'])@np.linalg.inv(world[:3,:3])
            except np.linalg.LinAlgError as e:raise ValueError('装置模型含零缩放')from e
        else:
            n=np.zeros_like(p);cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
            for j in range(3):np.add.at(n,f[:,j],cross)
        length=np.linalg.norm(n,axis=1)
        if(length<1e-8).any():raise ValueError('装置模型有退化面或无效法线')
        n/=length[:,None]
        if n.shape!=p.shape or not np.isfinite(n).all():raise ValueError('装置模型法线数量或数值无效')
        uv=source.read(attrs['TEXCOORD_0']).astype(float)if'TEXCOORD_0'in attrs else np.zeros((len(p),2))
        if not np.isfinite(p).all()or not np.isfinite(uv).all()or (uv<-.0001).any()or(uv>1.0001).any():raise ValueError('装置模型坐标无效或 UV 超出 0–1；请先烘焙重复贴图')
        x,y=tiles[primitive.get('material',-1)];uv[:,0]=(x+uv[:,0]*inner)/atlas.width;uv[:,1]=(y+uv[:,1]*inner)/atlas.height
        positions.append(p);normals.append(n);coords.append(uv);faces.append(f+cursor);cursor+=len(p)
    p=np.concatenate(positions)
    if np.ptp(p,axis=0).max()>200:raise ValueError('装置模型大于 200 米，请核对 GLB 单位；不支持整座球场导入')
    return p,np.concatenate(normals),np.concatenate(coords),np.concatenate(faces),atlas


def tifo(image,width=12,height=8):
    """An opaque panel with actual 3 cm thickness; never coincident backfaces."""
    w=width/2;h=height;t=.015
    points=[[-w,0,-t],[w,0,-t],[w,h,-t],[-w,h,-t],[-w,0,t],[w,0,t],[w,h,t],[-w,h,t]]
    quads=[(4,5,6,7),(1,0,3,2),(0,4,7,3),(5,1,2,6),(7,6,2,3),(0,1,5,4)]
    p=[];n=[];uv=[];f=[]
    for q in quads:
        vertices=np.asarray([points[i]for i in q]);normal=np.cross(vertices[1]-vertices[0],vertices[2]-vertices[0]);normal/=np.linalg.norm(normal)
        at=len(p);p.extend(vertices);n.extend([normal]*4);uv.extend([[0,1],[1,1],[1,0],[0,0]]);f.extend([[at,at+1,at+2],[at,at+2,at+3]])
    image=image.convert('RGB').convert('RGBA');image.thumbnail((4096,4096),Image.Resampling.LANCZOS)
    return np.asarray(p),np.asarray(n),np.asarray(uv),np.asarray(f),image


def preview_glb(p,n,uv,f,image,material=None):
    binary=bytearray();doc={'asset':{'version':'2.0','generator':'PlayerStudio static decoration'},'bufferViews':[],'accessors':[]}
    def add(values,kind,component=5126):
        v=np.asarray(values,dtype='<f4'if component==5126 else'<u4');binary.extend(bytes(-len(binary)%4));at=len(binary);binary.extend(v.tobytes())
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':v.nbytes})
        item={'bufferView':view,'componentType':component,'count':len(v),'type':kind}
        if kind=='VEC3':item.update(min=v.min(0).tolist(),max=v.max(0).tolist())
        doc['accessors'].append(item);return len(doc['accessors'])-1
    attrs={k:add(v,t)for k,v,t in(('POSITION',p,'VEC3'),('NORMAL',n,'VEC3'),('TEXCOORD_0',uv,'VEC2'))}
    idx=add(f.reshape(-1,1),'SCALAR',5125);png=io.BytesIO();image.save(png,format='PNG');at=len(binary);binary.extend(png.getvalue())
    view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':len(png.getvalue())})
    doc.update(images=[{'bufferView':view,'mimeType':'image/png'}],textures=[{'source':0}],
               materials=[material or {'name':'Diffuse atlas (opaque native carrier)','pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0,'roughnessFactor':.8}}],
               meshes=[{'primitives':[{'attributes':attrs,'indices':idx,'material':0}]}],nodes=[{'mesh':0}],scenes=[{'nodes':[0]}],scene=0)
    return encode(doc,binary)


def stand_layout(layout='poster'):
    # Migrate saved designs without losing the uploaded source image.
    if layout=='mosaic':return 'poster'
    if layout=='crowd':raise ValueError('当前原生资源尚未接通观众逐人举牌载体')
    if layout not in('poster','repeat'):raise ValueError('巨幅海报排版方式无效')
    return layout


def stand_image(path,layout='poster'):
    from PIL import ImageOps
    layout=stand_layout(layout)
    with Image.open(path)as image:
        image=ImageOps.fit(image.convert('RGB'),(1024,512),method=Image.Resampling.LANCZOS).convert('RGBA')
    if layout=='repeat':
        tile=image.resize((43,47),Image.Resampling.LANCZOS);canvas=Image.new('RGBA',(1024,512))
        for y in range(0,512,47):
            for x in range(0,1024,43):canvas.paste(tile,(x,y))
        return canvas
    return image


STAND_PREVIEW_REVISION='native-poster-source-pixels-native-uv0-v7'


def stand_native_pixels(image):
    """Keep source orientation; native UV0 already presents it correctly.

    V6's assumed reflection was disproved by the installed APK's pixels and
    the user's pitch-side screenshot. Never hide that mistake by mirroring
    both preview UV and texture. Re-export always starts at the source asset.
    """
    return image.copy()


def stand_preview(assets,image):
    """Only material 1 owns the whole poster image. Material 2 is tiled seams.

    Assigning the user's image to both sections tiled the whole photograph
    across the front overlay. Keep native UV0 on the actual image surface;
    UV1 is a lightmap atlas, not a substitute image mapping.
    """
    from native_static_mesh import find_lods
    raw,_=assets.get('/Game/Assets/bg/AdditionalAsset/Entrance/Choreography/SM_choreography');lod=find_lods(raw)[0]
    index=lod['indices'][0];all_faces=np.frombuffer(index['data'],dtype='<u4'if index['width']==4 else'<u2')
    sections=[s for s in lod['sections']if s[0]==1]
    if len(sections)!=1:raise ValueError('原生巨幅海报的整图材质分区改变')
    f=np.concatenate([all_faces[s[1]:s[1]+s[2]*3].reshape(-1,3)for s in sections])[:,::-1]
    used,remap=np.unique(f,return_inverse=True);f=remap.reshape(-1,3)
    p=np.frombuffer(lod['positions'],dtype='<f4').reshape(-1,3)[used][:,[0,2,1]]/100
    # Native +X is the pitch-facing side of this -X stand. Center/rotate it
    # towards preview +Z without reflecting the original image or its UV0.
    p=p[:,[2,1,0]].copy();p[:,0]*=-1
    p[:,0]-=(p[:,0].min()+p[:,0].max())/2
    p[:,2]-=(p[:,2].min()+p[:,2].max())/2
    p[:,1]-=p[:,1].min()
    uv=np.frombuffer(lod['uv'],dtype='<f4'if lod['full_uv']else'<f2').reshape(lod['vertices'],lod['nuv'],2)[used,0].astype(float)
    n=np.zeros_like(p);cross=np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]])
    for j in range(3):np.add.at(n,f[:,j],cross)
    length=np.linalg.norm(n,axis=1);n[length>1e-8]/=length[length>1e-8,None];n[length<=1e-8]=[1,0,0]
    if uv.min()<0 or uv.max()>1:raise ValueError('原生巨幅海报整图 UV 范围改变')
    # SM_choreography material slot 1 is MI_choreo_003_St: native MASK,
    # TwoSided=true, cutoff=.3333. Its image must remain visible from either
    # side when orbiting; alpha cutouts must not become black squares.
    material={'name':'Native giant poster image surface (independent preview)',
              'pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0,'roughnessFactor':.8},
              'alphaMode':'MASK','alphaCutoff':.3333,'doubleSided':True}
    return preview_glb(p,n,uv,f,stand_native_pixels(image),material)


def compile_stand_tifos(assets,store,stadium,runtime):
    """Separate native entrance-theme rows per stadium, changing only TIFO."""
    from native_stadium_table import read_groups,append_groups
    from native_art import clone_group,texture
    if not any(slot.get('stand_tifo')for slot in stadium['slots']):return [],[]
    base='/Game/Assets/bg/AdditionalAsset/Blueprint/DT_CS_EntranceSet1'
    composite='/Game/Assets/bg/AdditionalAsset/Table/CDT_CS_EntranceSet1'
    tables={p:assets.get(p)for p in(base,composite)}
    rows=read_groups(tables[base][0])[3]
    occupied={int(k)for raw,_ in tables.values()for k in read_groups(raw)[3]if k.isdigit()}
    ex='/Game/Assets/bg/AdditionalAsset/Blueprint/Ex/DT_CS_Ex_EntranceSet1'
    if '../../../PesMobile/Content/'+ex[6:]+'.uasset'in assets.files:
        extra=read_groups(assets.get(ex)[0])[3];occupied.update(int(k)for k in extra if k.isdigit())
    available=iter(i for i in range(200,256)if i not in occupied);entries={};art=[];reports=[]
    source='/Game/Assets/bg/AdditionalAsset/Entrance/00001/T_choreo_00001_bsm_alp'
    original,texmeta=assets.get(source)
    for slot in stadium['slots']:
        obj=slot.get('stand_tifo')
        if not obj:continue
        path=f'/Game/PlayerStudio/Stadium/S{slot["stadium_id"]}/T_StandTifo';soft=path+'.T_StandTifo'
        existing=[int(k)for k,r in rows.items()if r['assets'].get('Choreography')==soft]
        if len(existing)>1:raise ValueError('看台 TIFO 主题编号重复')
        try:ident=existing[0]if existing else next(available)
        except StopIteration as exc:raise ValueError('看台 TIFO 原生主题编号已用完')from exc
        layout=stand_layout(obj.get('layout','poster'))
        image=stand_image(store.root/'assets'/obj['asset'],layout)
        native_image=stand_native_pixels(image);changed=texture(original,source,native_image)[0]
        art.extend(clone_group({source:(original,texmeta)},{source:path},{source:changed}))
        # The native selector loads Entrance_<five digit ID> separately.
        from PIL import ImageOps
        thumb_source='/Game/Assets/ui/Data/Thumbnail/StadiumParts/Entrance/Entrance_00001'
        thumb_raw,thumb_meta=assets.get(thumb_source)
        thumb=Image.new('RGBA',(256,256),(17,31,44,255))
        fitted=ImageOps.contain(image.convert('RGBA'),(240,224),Image.Resampling.LANCZOS)
        thumb.alpha_composite(fitted,((256-fitted.width)//2,(256-fitted.height)//2))
        thumb_path=thumb_source.rsplit('/',1)[0]+f'/Entrance_{ident:05d}'
        thumb_changed=texture(thumb_raw,thumb_source,thumb)[0]
        art.extend(clone_group({thumb_source:(thumb_raw,thumb_meta)},{thumb_source:thumb_path},{thumb_source:thumb_changed}))
        # This feature replaces the giant poster only. Every other piece of
        # the entrance set is copied byte-for-byte from the native default.
        entries[ident]=(1,path)
        target=next(r for r in runtime['slots']if r['stadium_id']==slot['stadium_id']);target['entrance_set']=ident
        runtime['custom_assets'].append({'stadium_asset_type':'ENTRANCE','stadium_asset_id':ident,'stadium_asset_name':slot['custom_stadium_name']+' · 看台 TIFO'})
        reports.append({'stadium_id':slot['stadium_id'],'row_id':ident,'source_theme':1,'texture':path,'thumbnail':thumb_path,'name':obj['name'],
                        'layout':layout,'crowd_mosaic':False,'in_game_tested':False,
                        'image_pixels_sha256':hashlib.sha256(native_image.tobytes('raw','BGRA')).hexdigest(),
                        'source_pixels_sha256':hashlib.sha256(image.tobytes('raw','BGRA')).hexdigest(),
                        'orientation':'source pixels unchanged; original native UV0; no horizontal transformation',
                        'thumbnail_pixels_sha256':hashlib.sha256(thumb.tobytes('raw','BGRA')).hexdigest(),
                        'visibility':'native giant-poster only; no audience card animation; default other components preserved'})
    if entries:
        for table,(raw,meta)in tables.items():art.append((table,append_groups(raw,entries)[0],meta))
    verify_stand_tifos(assets,art,reports)
    return art,reports


def verify_stand_tifos(assets,art,reports):
    """Read the final package bytes, including the cooked composite lookup.

    This proves resource integrity, not visibility in a running game.
    """
    from native_stadium_table import read_groups
    from native_iostore import package_id
    from native_body import texture_mips
    if not reports:return
    packages={p:(raw,meta)for p,raw,meta in art}
    if len(packages)!=len(art):raise ValueError('看台 TIFO 生成了重复资源路径')
    tables=('/Game/Assets/bg/AdditionalAsset/Blueprint/DT_CS_EntranceSet1',
            '/Game/Assets/bg/AdditionalAsset/Table/CDT_CS_EntranceSet1')
    for report in reports:
        path=report['texture'];soft=path+'.'+path.rsplit('/',1)[-1]
        for table in tables:
            rows=read_groups(packages[table][0])[3]
            original=read_groups(assets.get(table)[0])[3][str(report['source_theme'])]['assets']
            if rows[str(report['row_id'])]['assets']!={**original,'Choreography':soft}:
                raise ValueError('巨幅海报引用或默认套装部件读回不一致')
        report['package_sha256']={}
        for name,dimensions,pixels in ((path,(1024,512),report['image_pixels_sha256']),
                                      (report['thumbnail'],(256,256),report['thumbnail_pixels_sha256'])):
            raw,meta=packages[name];decoded=texture_mips(raw)
            if meta['id']!=package_id(name)or decoded['format']!='PF_B8G8R8A8' or (decoded['width'],decoded['height'])!=dimensions or len(decoded['mips'])!=1:
                raise ValueError('巨幅海报或缩略图的原生纹理结构读回不一致')
            mip=decoded['mips'][0]
            if mip['storage']!='inline'or mip['sha256']!=pixels:raise ValueError('巨幅海报或缩略图像素读回不一致')
            report['package_sha256'][name]=hashlib.sha256(raw).hexdigest()
        report['resource_readback']='passed: source + cooked composite, default components, inline image + thumbnail pixels'


def compile_object(assets,geometry,identity,transform):
    from native_art import clone_group,texture
    from native_static_mesh import replace
    p,n,uv,f,image=geometry;p=p.copy();n=n.copy()
    # Local GLB Y-up metres -> native Z-up centimetres. Flip triangle winding
    # for the handedness change, then apply the user's local-anchor transform.
    p=p[:,[0,2,1]]*100;n=n[:,[0,2,1]];f=f[:,::-1]
    yaw=math.radians(transform['rotation']);c,s=math.cos(yaw),math.sin(yaw)
    r=np.array([[c,-s,0],[s,c,0],[0,0,1]])
    p=p@r.T*transform['scale']+np.asarray(transform['offset'])*100;n=n@r.T
    source='/Game/Assets/bg/AdditionalAsset/Object/00001/';prefix='/Game/PlayerStudio/Stadium/'+identity+'/'
    mesh=source+'SM_object_00001_low';material=source+'MI_object_00001_low_St'
    packages={k:assets.get(k)for k in(mesh,material,*[source+'T_object_00001_low_'+s for s in('bsm','mtl','nrm','rgm','spe')])}
    changed,report=replace(packages[mesh][0],p,n,uv,f)
    overrides={mesh:changed,material:matte_material(packages[material][0])};renames={k:prefix+('SM_Decoration'if k==mesh else'MI_Decoration'if k==material else'T_'+k.rsplit('_',1)[-1])for k in packages}
    pixels={'bsm':image,'mtl':Image.new('RGBA',(4,4),(0,0,0,255)),
            'nrm':Image.new('RGBA',(4,4),(128,128,255,255)),
            'rgm':Image.new('RGBA',(4,4),(204,204,204,255)),
            'spe':Image.new('RGBA',(4,4),(32,32,32,255))}
    for suffix,pixel in pixels.items():
        key=source+'T_object_00001_low_'+suffix
        # Retain the original package identity until clone_group remaps its
        # imports and every dependent material reference together.
        overrides[key]=texture(packages[key][0],key,pixel)[0]
    result=clone_group(packages,renames,overrides)
    return result,renames[mesh],dict(report,material='diffuse atlas; flat normal; opaque non-metallic fallback',
                                   coordinate_space='native anchor local, centimetres',transform=copy.deepcopy(transform))
