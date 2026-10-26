"""Canonical head geometry for native multi-section and old preview exports.

Display wrappers are not game coordinates. Equivalent per-section skins from
GLTFExporter share one skeleton; sections retain their triangles and weights.
The uploaded file is never rewritten.
"""
import copy,io,json,struct
import numpy as np
from native_glb import Glb


def encode(doc,binary):
    doc['buffers']=[{'byteLength':len(binary)}]
    raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4)
    binary=bytes(binary)+bytes(-len(binary)%4)
    chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<4sII',b'glTF',2,len(chunks)+12)+chunks


def normalize_head(source):
    d=source.doc;nodes=d.get('nodes',[]);skins=d.get('skins',[])
    wrapper=any(n.get('name')=='ImportedPlayerPreview' and 'normalizedScale' in n.get('extras',{}) for n in nodes)
    if sum(len(m['primitives']) for m in d.get('meshes',[]))==1 and len(skins)<=1 and not wrapper:return source,{'status':'single-mesh'}
    parts=[(i,n,p) for i,n in enumerate(nodes) if 'mesh' in n
           for p in d['meshes'][n['mesh']]['primitives']]
    if not parts:raise ValueError('GLB 没有可用的头部网格')
    if len(parts)==1 and len(skins)<=1 and not wrapper:return source,{'status':'single-mesh'}
    doc=copy.deepcopy(d);binary=bytearray(source.binary)
    def accessor(values,kind,ctype=5126):
        array=np.asarray(values,dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[ctype])
        binary.extend(bytes(-len(binary)%4));at=len(binary);binary.extend(array.tobytes())
        view=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':array.nbytes})
        item={'bufferView':view,'componentType':ctype,'type':kind,'count':len(array)}
        if kind=='VEC3':item.update(min=array.min(0).tolist(),max=array.max(0).tolist())
        index=len(doc.setdefault('accessors',[]));doc['accessors'].append(item);return index
    base=skins[parts[0][1].get('skin',0)] if skins else None
    if base:
        for _,node,_ in parts:
            if 'skin' not in node:raise ValueError('不能混合已绑定与未绑定的头部网格')
            skin=skins[node['skin']]
            if skin['joints']!=base['joints'] or not np.allclose(source.read(skin['inverseBindMatrices']),source.read(base['inverseBindMatrices']),atol=1e-6,rtol=0):
                raise ValueError('多网格使用不同骨架，请先统一绑定')
    materials=list(dict.fromkeys(p.get('material',0) for _,_,p in parts))
    atlas=len(materials)>1;tiles={}
    if atlas:
        from PIL import Image
        # A square grid avoids stretching individual face/hair textures.
        columns=int(np.ceil(np.sqrt(len(materials))));rows=int(np.ceil(len(materials)/columns))
        images=[]
        for mat in materials:
            primitive=next(p for _,_,p in parts if p.get('material',0)==mat)
            image=Image.open(io.BytesIO(source.image(primitive))).convert('RGBA')
            factor=d['materials'][mat].get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1])
            if factor!=[1,1,1,1]:image=Image.fromarray(np.rint(np.asarray(image)*np.asarray(factor)).clip(0,255).astype('uint8'))
            images.append(image)
        size=min(max(max(im.size) for im in images),4096//max(columns,rows))-4
        if size<1:raise ValueError('头模材质数量过多')
        pitch=size+4;canvas=Image.new('RGBA',(columns*pitch,rows*pitch))
        for index,(mat,image) in enumerate(zip(materials,images)):
            x=index%columns*pitch+2;y=index//columns*pitch+2
            image=image.resize((size,size),Image.Resampling.LANCZOS);canvas.paste(image,(x,y))
            canvas.paste(image.resize((size+4,size+4),Image.Resampling.NEAREST),(x-2,y-2));canvas.paste(image,(x,y))
            tiles[mat]=(x,y,size,canvas.width,canvas.height)
        output=io.BytesIO();canvas.save(output,format='PNG');png=output.getvalue()
        binary.extend(bytes(-len(binary)%4));at=len(binary);binary.extend(png)
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':len(png)})
        doc['images']=[{'bufferView':view,'mimeType':'image/png'}];doc['textures']=[{'source':0}]
        material={'name':'NativeHeadAtlas','pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0},'alphaMode':'MASK','alphaCutoff':.3333,'doubleSided':True}
    else:material=copy.deepcopy(d['materials'][materials[0]])
    arrays={k:[] for k in ('POSITION','NORMAL','TEXCOORD_0')}
    if base:arrays.update(JOINTS_0=[],WEIGHTS_0=[])
    indices=[];offset=0
    for _,node,p in parts:
        if p.get('mode',4)!=4:raise ValueError('头模需要使用三角形网格')
        # Native mesh section nodes are identity. Scene-level presentation
        # transforms are deliberately excluded, including the old centering.
        if node.get('matrix') and not np.allclose(np.asarray(node['matrix']).reshape(4,4),np.eye(4),atol=1e-6):
            raise ValueError('头模子网格含未应用的局部变换，请先应用变换')
        if any(node.get(key,default)!=default for key,default in [('translation',[0,0,0]),('rotation',[0,0,0,1]),('scale',[1,1,1])]):raise ValueError('头模子网格含未应用的局部变换')
        attrs=p['attributes'];count=len(source.read(attrs['POSITION']))
        original=source.read(p['indices']).reshape(-1).astype(int) if 'indices' in p else np.arange(count)
        used,remap=np.unique(original,return_inverse=True)
        if len(original)%3 or used.min()<0 or used.max()>=count:raise ValueError('头模三角形索引越界')
        for key in arrays:
            if key not in attrs:raise ValueError('头模缺少 '+key)
            values=source.read(attrs[key])[used]
            if key=='TEXCOORD_0' and atlas:
                x,y,size,w,h=tiles[p.get('material',0)];values=values.copy()
                values[:,0]=(x+np.clip(values[:,0],0,1)*size)/w;values[:,1]=(y+np.clip(values[:,1],0,1)*size)/h
            arrays[key].append(values)
        indices.append(remap+offset);offset+=len(used)
    attrs={key:accessor(np.concatenate(values),{'POSITION':'VEC3','NORMAL':'VEC3','TEXCOORD_0':'VEC2','JOINTS_0':'VEC4','WEIGHTS_0':'VEC4'}[key],5123 if key=='JOINTS_0' else 5126) for key,values in arrays.items()}
    doc['meshes']=[{'name':'NativeHead','primitives':[{'attributes':attrs,'indices':accessor(np.concatenate(indices).reshape(-1,1),'SCALAR',5125),'material':0}]}]
    doc['materials']=[material]
    for node in doc['nodes']:node.pop('mesh',None);node.pop('skin',None)
    roots=[]
    if base:
        joints=set(base['joints']);children={c for j in joints for c in doc['nodes'][j].get('children',[]) if c in joints}
        roots=sorted(joints-children)
        for node in doc['nodes']:
            if 'children' in node:node['children']=[c for c in node['children'] if c in joints]
        doc['skins']=[copy.deepcopy(base)]
    new={'name':'NativeHead','mesh':0}
    if base:new['skin']=0
    roots.append(len(doc['nodes']));doc['nodes'].append(new)
    doc['scenes']=[{'nodes':roots}];doc['scene']=0
    # Export is a neutral head. Saved test clips must never become game poses.
    doc.pop('animations',None)
    return Glb(encode(doc,binary)),{'status':'native-sections-merged','sections':len(parts),'materials':len(materials),'preview_wrapper_removed':wrapper,'facial_weights_preserved':bool(base)}
