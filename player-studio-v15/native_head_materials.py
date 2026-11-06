"""Mobile custom-head material translation, using the inspected cooked shaders.

No shader is compiled here. FaceUpcon consumes D/N/SRO; stock masked hair HQ
consumes D/SRO and MQ consumes D only. Hair normals come from the mesh. The
stock hair route is two sided, including for old single-atlas GLBs which were
saved with doubleSided=false. These differences are reported, never hidden.
"""
import io
import math
import struct
import numpy as np
from PIL import Image, ImageDraw

# Bump on compiler changes: native_art includes this in the face cache key.
REVISION='mobile-head-masked-materials-v2-sampler-coverage'
NATIVE_CLIP=.3333
WRAP_NAMES={10497:'REPEAT',33071:'CLAMP_TO_EDGE',33648:'MIRRORED_REPEAT'}
NATIVE_WRAP={10497:'TA_Wrap',33071:'TA_Clamp',33648:'TA_Mirror'}


def verify_native_hair(raw,quality):
    """Fail if a different cache no longer supplies the inspected shader route."""
    from native_iostore import package_names
    from native_skeletal import object_imports
    names=package_names(raw);h=struct.unpack_from('<16I',raw)
    parent='/Game/Assets/MaterialLibrary/Character/Head/MasterMaterials/M_Head_Hair_'+quality
    needed=('BasePropertyOverrides','StructProperty','MaterialInstanceBasePropertyOverrides',
            'TwoSided','BoolProperty','BlendMode','ByteProperty','EBlendMode','BLEND_Masked',
            'OpacityMaskClipValue','FloatProperty')
    if quality not in ('HQ','MQ') or any(n not in names for n in needed) or parent not in object_imports(raw,names):
        raise ValueError('移动端原生毛发材质模板与已核对路线不同')
    tag=struct.pack('<4I',names.index('BasePropertyOverrides'),0,names.index('StructProperty'),0)
    at=raw.find(tag,h[13]+h[14])
    if at<0 or raw.find(tag,at+1)>=0:raise ValueError('原生毛发材质属性不唯一')
    length=struct.unpack_from('<I',raw,at+16)[0]
    if struct.unpack_from('<I',raw,at+24)[0]!=names.index('MaterialInstanceBasePropertyOverrides') or raw[at+48]!=0:
        raise ValueError('原生毛发材质属性结构未适配')
    body=raw[at+49:at+49+length]
    two=struct.pack('<6I2B',names.index('TwoSided'),0,names.index('BoolProperty'),0,0,0,1,0)
    blend=struct.pack('<8IB2I',names.index('BlendMode'),0,names.index('ByteProperty'),0,8,0,
                      names.index('EBlendMode'),0,0,names.index('BLEND_Masked'),0)
    clip=struct.pack('<6IBf',names.index('OpacityMaskClipValue'),0,names.index('FloatProperty'),0,4,0,0,NATIVE_CLIP)
    if not all(body.count(value)==1 for value in (two,blend,clip)):
        raise ValueError('原生毛发模板并非已核对的 MASK／双面／0.3333 路线')
    return {'parent':parent,'blend_mode':'BLEND_Masked','two_sided':True,'clip':NATIVE_CLIP}


def image_for(glb,info):
    if info.get('texCoord',0)!=0 or info.get('extensions'):
        raise ValueError('移动端头模材质暂只支持未变换的 TEXCOORD_0 贴图')
    try:
        image=glb.doc['images'][glb.doc['textures'][info['index']]['source']]
        view=glb.doc['bufferViews'][image['bufferView']]
        start=view.get('byteOffset',0)
        pixels=Image.open(io.BytesIO(glb.binary[start:start+view['byteLength']]))
        if not 1<=pixels.width<=4096 or not 1<=pixels.height<=4096:
            raise ValueError('Native texture dimensions exceed the supported range')
        return pixels.convert('RGBA')
    except (KeyError,IndexError,OSError) as exc:
        raise ValueError('移动端头模材质需要有效的内嵌贴图') from exc


def factor(value,count,label):
    a=np.asarray(value,dtype=float)
    if a.shape!=(count,) or not np.isfinite(a).all() or (a<0).any() or (a>1).any():
        raise ValueError('头模 '+label+' 超出 0–1 范围')
    return a


def base_pixels(glb,material):
    pbr=material.get('pbrMetallicRoughness',{})
    if not pbr.get('baseColorTexture'):raise ValueError('脸模缺少内嵌的 BaseColor 贴图')
    image=image_for(glb,pbr['baseColorTexture'])
    f=factor(pbr.get('baseColorFactor',[1,1,1,1]),4,'BaseColorFactor')
    if not np.array_equal(f,np.ones(4)):
        a=np.asarray(image,dtype=float)/255
        linear=np.where(a[:,:,:3]<=.04045,a[:,:,:3]/12.92,((a[:,:,:3]+.055)/1.055)**2.4)*f[:3]
        a[:,:,:3]=np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
        a[:,:,3]*=f[3]
        image=Image.fromarray(np.rint(a*255).clip(0,255).astype('uint8'))
    return image


def texture_wrap(glb,info):
    """glTF omitted samplers default to REPEAT, including old native GLBs."""
    try:
        texture=glb.doc['textures'][info['index']]
        sampler=glb.doc.get('samplers',[])[texture['sampler']] if 'sampler' in texture else {}
        wrap=tuple(sampler.get(key,10497) for key in ('wrapS','wrapT'))
    except (KeyError,IndexError,TypeError) as exc:
        raise ValueError('头模贴图采样器无效') from exc
    if any(type(v)is not int or v not in WRAP_NAMES for v in wrap):
        raise ValueError('头模贴图寻址模式无效')
    return wrap


def sample_indices(values,size,wrap):
    """Address virtual texels, never modulo individual mesh UV vertices."""
    if wrap==33071:return np.clip(values,0,size-1)
    if wrap==10497:return values%size
    if wrap==33648:
        folded=values%(size*2)
        return np.where(folded<size,folded,size*2-1-folded)
    raise ValueError('头模贴图寻址模式无效')


def _texture_fields(raw):
    """Read the inspected single-export Texture2D's tagged property prefix."""
    from native_iostore import package_names
    names=package_names(raw);h=struct.unpack_from('<16I',raw)
    if h[12]-h[11]!=72:raise ValueError('自制头模贴图导出结构改变')
    pos=h[13]+h[14];fields=[]
    for _ in range(128):
        begin=pos;ident,number=struct.unpack_from('<2I',raw,pos);pos+=8
        if ident>=len(names) or number:raise ValueError('自制头模贴图属性名称无效')
        name=names[ident]
        if name=='None':return names,h,fields,begin
        kind_id,number,length,index=struct.unpack_from('<4I',raw,pos);pos+=16
        if kind_id>=len(names) or number or index:raise ValueError('自制头模贴图属性布局改变')
        kind=names[kind_id];enum=None
        if kind=='StructProperty':pos+=24
        elif kind=='BoolProperty':pos+=1
        elif kind=='ByteProperty':
            enum_id,enum_number=struct.unpack_from('<2I',raw,pos);pos+=8
            if enum_id>=len(names) or enum_number:raise ValueError('自制头模贴图枚举类型无效')
            enum=names[enum_id]
        elif kind not in ('IntProperty','FloatProperty'):raise ValueError('自制头模贴图属性类型未适配：'+kind)
        guid=raw[pos];pos+=1
        if guid==1:pos+=16
        elif guid!=0:raise ValueError('自制头模贴图属性 GUID 无效')
        payload=pos;pos+=length
        if pos>len(raw):raise ValueError('自制头模贴图属性数据不完整')
        fields.append((name,kind,enum,begin,pos,payload,length))
    raise ValueError('自制头模贴图属性过多')


def native_texture_wrap(raw):
    """Read back explicit cooked addressing; a missing property is unknown."""
    names,_,fields,_=_texture_fields(raw);result={}
    for name,kind,enum,_,_,payload,length in fields:
        if name not in ('AddressX','AddressY'):continue
        if name in result or kind!='ByteProperty' or enum!='TextureAddress' or length!=8:
            raise ValueError('自制头模贴图寻址属性布局改变')
        ident,number=struct.unpack_from('<2I',raw,payload)
        if ident>=len(names) or number or names[ident] not in NATIVE_WRAP.values():
            raise ValueError('自制头模贴图寻址属性无效')
        result[name]=names[ident]
    return result


def compile_texture(raw,name,image,wrap):
    """Stamp addressing before rebuilding inline mip offsets, then read it back.

    The stock head textures omit these properties. Keeping that prefix would
    silently drop glTF clamp/mirror modes; writing both avoids relying on a
    particular engine class default. The caller still uses the stock shader.
    """
    from native_iostore import package_names,rename_package
    from native_art import texture
    if len(wrap)!=2 or any(v not in NATIVE_WRAP for v in wrap):raise ValueError('头模贴图寻址模式无效')
    names=package_names(raw);h=struct.unpack_from('<16I',raw)
    raw,_=rename_package(raw,names[h[0]&0x3fffffff],extra_names=(
        'AddressX','AddressY','ByteProperty','TextureAddress',*NATIVE_WRAP.values()))
    names,h,fields,terminator=_texture_fields(raw);parts=[]
    for field,_,_,begin,end,_,_ in fields:
        if field not in ('AddressX','AddressY'):parts.append(raw[begin:end])
    for field,value in zip(('AddressX','AddressY'),wrap):
        parts.append(struct.pack('<8IB2I',names.index(field),0,names.index('ByteProperty'),0,8,0,
                                 names.index('TextureAddress'),0,0,names.index(NATIVE_WRAP[value]),0))
    base=h[13]+h[14];body=b''.join(parts);delta=len(body)-(terminator-base)
    updated=bytearray(raw[:base]+body+raw[terminator:])
    struct.pack_into('<Q',updated,h[11]+8,struct.unpack_from('<Q',raw,h[11]+8)[0]+delta)
    # texture() reconstructs all absolute platform/bulk offsets after the
    # property insertion. Never expose the temporarily shifted cooked stream.
    encoded=texture(bytes(updated),name,image)[0]
    expected={field:NATIVE_WRAP[value] for field,value in zip(('AddressX','AddressY'),wrap)}
    if native_texture_wrap(encoded)!=expected:raise ValueError('自制头模贴图寻址写入后校验失败')
    return encoded


def masked_components(faces,uv,image,cutoff,wrap=(10497,10497)):
    """Classify a legacy atlas by alpha inside UV triangles, then whole islands.

    Shared *edges*, not shared positions, define islands. A card's opaque root
    stays on the hair shader when another triangle of that card needs masking.
    The raster is local to each triangle and excludes atlas gutters outside it.
    """
    if not np.isfinite(uv).all():raise ValueError('头模材质分区含无效 UV')
    alpha=np.asarray(image)[:,:,3];height,width=alpha.shape
    parent=np.arange(len(faces));edges={}
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=int(parent[i])
        return i
    for t,triangle in enumerate(faces):
        for i,j in ((0,1),(1,2),(2,0)):
            edge=tuple(sorted((int(triangle[i]),int(triangle[j]))))
            if edge in edges:parent[root(t)]=root(edges[edge])
            else:edges[edge]=t
    roots=np.asarray([root(i) for i in range(len(faces))]);masked=set()
    raster_pixels=0
    for t,triangle in enumerate(faces):
        key=int(roots[t])
        if key in masked:continue
        points=uv[triangle]*[width,height]-.5
        # Rasterize in the original continuous UV plane. Clamping UVs or
        # applying modulo per vertex would alter triangles crossing a seam.
        bounds=np.concatenate((np.floor(points.min(0)),np.ceil(points.max(0))+1))
        if (np.abs(bounds)>2**40).any():raise ValueError('头模材质分区的 UV 范围过大')
        lo=bounds[:2].astype(np.int64);hi=bounds[2:].astype(np.int64)
        if (hi<=lo).any():continue
        area=int(hi[0]-lo[0])*int(hi[1]-lo[1]);raster_pixels+=area
        if area>64*1024**2 or raster_pixels>512*1024**2:
            raise ValueError('头模材质分区的 UV 重复跨度过大，请先烘焙重复贴图')
        # Bounded tiles avoid allocating a repeated copy of the entire image.
        for y in range(int(lo[1]),int(hi[1]),256):
            if key in masked:break
            ys=np.arange(y,min(y+256,int(hi[1])),dtype=np.int64)
            source_y=sample_indices(ys,height,wrap[1])
            for x in range(int(lo[0]),int(hi[0]),256):
                xs=np.arange(x,min(x+256,int(hi[0])),dtype=np.int64)
                patch=alpha[np.ix_(source_y,sample_indices(xs,width,wrap[0]))]
                if patch.min()/255>=cutoff:continue
                mask=Image.new('1',(len(xs),len(ys)))
                ImageDraw.Draw(mask).polygon([tuple(p-[x,y]) for p in points],fill=1)
                covered=patch[np.asarray(mask,dtype=bool)]
                if covered.size and (covered/255<cutoff).any():masked.add(key);break
    return np.asarray([int(k in masked) for k in roots],dtype=np.uint8),len(set(roots.tolist()))


def remap_alpha(image,cutoff):
    """Keep the cooked clip constant; map authored coverage onto that clip.

    Editing only a cooked MI clip does not compile a matching shader. This
    monotonic alpha conversion avoids depending on an absent shader permutation.
    """
    if abs(cutoff-NATIVE_CLIP)<1e-7:return image.copy()
    a=np.asarray(image).copy();alpha=a[:,:,3].astype(float)/255
    if cutoff==0:alpha=np.ones_like(alpha)
    elif cutoff==1:alpha=np.where(alpha>=1,1,alpha*NATIVE_CLIP)
    else:alpha=np.where(alpha<cutoff,alpha*NATIVE_CLIP/cutoff,
                        NATIVE_CLIP+(alpha-cutoff)*(1-NATIVE_CLIP)/(1-cutoff))
    # Ensure 8-bit texel pass/fail agrees even at the quantised boundary.
    source_pass=np.asarray(image)[:,:,3].astype(float)/255>=cutoff
    values=np.rint(alpha*255).clip(0,255)
    values=np.where(source_pass,np.maximum(values,math.ceil(NATIVE_CLIP*255)),
                    np.minimum(values,math.ceil(NATIVE_CLIP*255)-1))
    a[:,:,3]=values.astype('uint8');return Image.fromarray(a)


def plan(glb):
    p=glb.head();material=glb.doc['materials'][p.get('material',0)]
    mode=material.get('alphaMode','OPAQUE')
    if mode not in ('OPAQUE','MASK'):raise ValueError('移动端原生头发支持 MASK；请先将 BLEND 材质改为裁切遮罩')
    cutoff=float(material.get('alphaCutoff',.5))
    if not math.isfinite(cutoff) or not 0<=cutoff<=1:raise ValueError('头模 Alpha 裁切阈值须在 0–1 内')
    image=base_pixels(glb,material)
    faces=glb.read(p['indices']).reshape(-1,3).astype(int)
    uv=glb.read(p['attributes']['TEXCOORD_0']).astype(float)
    if len(faces)>1000000 or len(uv)>500000:raise ValueError('自制头模顶点或三角形数量不受支持')
    if faces.size==0 or faces.min()<0 or faces.max()>=len(uv):raise ValueError('头模材质分区的三角形索引越界')
    kinds=np.zeros(len(faces),dtype=np.uint8);islands=0
    wrap=texture_wrap(glb,material.get('pbrMetallicRoughness',{})['baseColorTexture'])
    if mode=='MASK':kinds,islands=masked_components(faces,uv,image,cutoff,wrap)
    hair=int(kinds.sum());warnings=[]
    if hair and not material.get('doubleSided',False):
        warnings.append('GLB doubleSided=false；移动端使用原生双面毛发，未创建未经烘焙的单面 shader 变体')
    if hair and material.get('normalTexture'):
        warnings.append('原生毛发 HQ/MQ 无 NormalMap 参数；毛发保留网格法线，普通法线贴图仅用于皮肤 HQ')
    if hair and abs(cutoff-NATIVE_CLIP)>=1e-7:
        warnings.append('裁切阈值通过 Alpha 重映射适配原生 shader；纹素通过关系保留，过滤边缘为近似')
    if material.get('name')=='NativeHeadAtlas':
        warnings.append('旧的多材质归一化图集未保存逐材质 N／MR 元数据；只能使用当前图集中仍保留的通道')
    return {'triangle_materials':kinds,'diffuse':image,'hair_diffuse':remap_alpha(image,cutoff) if mode=='MASK' else image.copy(),'base_wrap':wrap,
            'material':material,'report':{'revision':REVISION,'source_alpha_mode':mode,
            'source_alpha_cutoff':cutoff if mode=='MASK' else None,'native_hair_clip':NATIVE_CLIP,
            'alpha_translation':('unchanged' if abs(cutoff-NATIVE_CLIP)<1e-7 else 'monotonic remap to cooked native clip') if mode=='MASK' else 'not applicable',
            'source_double_sided':bool(material.get('doubleSided',False)),
            'native_hair_two_sided':True if hair else None,'skin_triangles':len(faces)-hair,'hair_triangles':hair,
            'partition':'alpha coverage in UV triangles, propagated across shared-edge islands',
            'coverage_sampler':{'wrapS':WRAP_NAMES[wrap[0]],'wrapT':WRAP_NAMES[wrap[1]]},
            'source_uv_unchanged':True,'outside_unit_uv_vertices':int(((uv<0)|(uv>1)).any(axis=1).sum()),
            'uv_islands':islands,'warnings':warnings,'in_game_tested':False}}


def maps(glb,material_plan):
    material=material_plan['material'];pbr=material.get('pbrMetallicRoughness',{})
    rough=float(factor([pbr.get('roughnessFactor',1)],1,'RoughnessFactor')[0])
    mr=pbr.get('metallicRoughnessTexture');ao=material.get('occlusionTexture');normal=material.get('normalTexture')
    mr_image=image_for(glb,mr) if mr else None;ao_image=image_for(glb,ao) if ao else None
    base_wrap=material_plan['base_wrap'];sro_wrap=texture_wrap(glb,mr or ao) if mr or ao else base_wrap
    if mr and ao and texture_wrap(glb,mr)!=texture_wrap(glb,ao):
        raise ValueError('头模粗糙度与 AO 使用不同的贴图寻址模式，请先烘焙为同一采样方式')
    material_plan['texture_wraps']={'Face_D':base_wrap,'Face_N':texture_wrap(glb,normal) if normal else base_wrap,
        'Face_SRO':sro_wrap,'Hair_High_D':base_wrap,'Hair_D':base_wrap,'Hair_High_SRO':sro_wrap}
    # Only G is roughness in glTF. B metallic is never relabelled specular;
    # native dielectric SRO uses R=specular fallback, G=roughness, B=AO.
    size=mr_image.size if mr_image else ao_image.size if ao_image else (4,4)
    sro=np.empty((size[1],size[0],4),dtype=np.uint8);sro[:]=[64,round(rough*255),255,255]
    if mr_image is not None:sro[:,:,1]=np.rint(np.asarray(mr_image)[:,:,1]*rough).astype('uint8')
    if ao_image is not None:
        strength=float(factor([ao.get('strength',1)],1,'OcclusionStrength')[0])
        channel=np.asarray(ao_image.resize(size,Image.Resampling.BILINEAR))[:,:,0].astype(float)
        sro[:,:,2]=np.rint(255+(channel-255)*strength).astype('uint8')
    n=Image.new('RGBA',(4,4),(128,128,255,255))
    if normal:
        n=image_for(glb,normal);scale=float(normal.get('scale',1))
        if not math.isfinite(scale):raise ValueError('普通法线贴图缩放值无效')
        a=np.asarray(n,dtype=float);v=a[:,:,:3]/127.5-1;v[:,:,:2]*=scale
        v/=np.maximum(np.linalg.norm(v,axis=2,keepdims=True),1e-12)
        a[:,:,:3]=np.rint((v+1)*127.5).clip(0,255);a[:,:,3]=255;n=Image.fromarray(a.astype('uint8'))
    report=material_plan['report']
    report['channels']={'skin_hq_normal':'authored glTF normalTexture RGB' if normal else 'neutral RGB normal fallback',
        'hair_normal':'authored mesh normals; cooked hair has no NormalMap sampler',
        'roughness':'glTF metallicRoughnessTexture.G × roughnessFactor' if mr else 'roughnessFactor',
        'specular':'constant dielectric native fallback R=64/255; metallic channel not used',
        'ao':'glTF occlusionTexture.R with strength' if ao else 'white AO fallback',
        'skin_mq':'native BaseColor only','hair_hq':'native BaseColor + SRO','hair_mq':'native BaseColor only'}
    report['source_metallic_factor']=float(factor([pbr.get('metallicFactor',1)],1,'MetallicFactor')[0])
    report['native_texture_addressing']={key:{axis:NATIVE_WRAP[value] for axis,value in zip(('AddressX','AddressY'),wrap)}
        for key,wrap in material_plan['texture_wraps'].items()}
    if report['source_metallic_factor'] and (mr_image is None or np.asarray(mr_image)[:,:,2].max()):
        report['warnings'].append('原生头模采用非金属材质；金属度未转成 SRO 高光')
    return {'Face_D':material_plan['diffuse'],'Face_N':n,'Face_SRO':Image.fromarray(sro),
            'Hair_High_D':material_plan['hair_diffuse'],'Hair_D':material_plan['hair_diffuse'],
            'Hair_High_SRO':Image.fromarray(sro)}


def partition(head,triangle_materials):
    """Give sections disjoint contiguous vertex ranges and keep every triangle."""
    kinds=np.asarray(triangle_materials)
    if kinds.shape!=(head['triangles'],) or not set(kinds.tolist())<={0,1}:
        raise ValueError('头模材质分区与实际三角形不一致')
    order=[];faces=[];sections=[];base=0;index=0
    for material in (0,1):
        selected=head['faces'][kinds==material]
        if not len(selected):continue
        used,inverse=np.unique(selected,return_inverse=True)
        faces.append(inverse.reshape(-1,3)+base);order.extend(used.tolist())
        sections.append({'material':material,'base_index':index,'triangles':len(selected),
                         'base_vertex':base,'vertices':len(used)})
        base+=len(used);index+=selected.size
    result=dict(head,faces=np.concatenate(faces),vertices=base,sections=sections)
    for name in ('positions','normals','uv','tangents','skin'):result[name]=head[name][order]
    if base>500000:raise ValueError('材质分段后的移动端头模顶点超过上限')
    return result
