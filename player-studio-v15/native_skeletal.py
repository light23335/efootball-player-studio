"""Shared, bounded native skeletal-mesh decoder for desktop and Android."""
from pathlib import Path
import json,struct
import numpy as np
from native_iostore import package_names
from native_mesh import read_lod


FACE_DECODER_REVISION='complete-native-face-lods-v2'


def mesh_lods(raw):
    marker=b'\x01\x01\0\0\0\0\x01\0\0\0';at=0;lods=[]
    while (at:=raw.find(marker,at))>=0:
        try:
            lod=read_lod(raw,at)
            if lod['vertices'] and not any(p['start']<=at<p['end'] for p in lods):lods.append(lod)
        except (ValueError,struct.error):pass
        at+=1
    if not lods:raise ValueError('此原版脸模的网格档位尚未适配')
    return lods


def face_details(raw):
    names=package_names(raw);_,bones,_=skeleton(raw,names);lods=mesh_lods(raw)
    details=[]
    for lod in lods:
        source=np.frombuffer(lod['skin'],dtype=np.uint8).reshape(lod['vertices'],8);used=set()
        for section in lod['sections']:
            start=section['base_vertex'];part=source[start:start+section['vertices']];palette=np.asarray(section['bones'])
            if np.any(part[:,:4]>=len(palette)):raise ValueError('原版脸模蒙皮索引越界')
            used.update(palette[part[:,:4][part[:,4:]>0]].tolist())
        if any(b>=len(bones) for b in used):raise ValueError('原版脸模骨骼索引越界')
        facial=[bones[b]['name'] for b in sorted(used) if bones[b]['name'].startswith('skf_') or bones[b]['name']=='skf']
        details.append({'vertices':lod['vertices'],'weighted_bones':len(used),'facial_bones':facial})
    return {'lods':len(lods),'highest_vertices':max(l['vertices'] for l in lods),
            'facial_bones':max(len(d['facial_bones']) for d in details),'bones':len(bones),'lod_details':details}


def allow_closeup_lod(raw):
    """Allow the retained animated LOD0 without forcing it at long distances.

    The pc3600 mesh keeps both LODs but its cooked PerPlatformInt MinLod is
    1. The stock player loader can override that; a newly named face must
    not depend on that original-player lookup to expose its close-up LOD.
    """
    if len(mesh_lods(raw))<2:return raw,{'changed':False,'reason':'single-lod'}
    names=package_names(raw)
    if not all(n in names for n in ('MinLod','StructProperty','PerPlatformInt')):
        return raw,{'changed':False,'reason':'native-default'}
    tag=(struct.pack('<6I',names.index('MinLod'),0,names.index('StructProperty'),0,8,0)
         +struct.pack('<2I',names.index('PerPlatformInt'),0)+bytes(17))
    start=raw.find(tag)
    if start<0 or raw.find(tag,start+1)>=0:raise ValueError('原版模型的 MinLod 属性格式未适配')
    at=start+len(tag);cooked,value=struct.unpack_from('<2I',raw,at)
    if cooked!=1 or not 0<=value<8:raise ValueError('原版模型的 MinLod 平台值未适配')
    result=bytearray(raw);struct.pack_into('<I',result,at+4,0)
    return bytes(result),{'changed':bool(value),'original':value,'export':0,'distance_lods_preserved':True}

def object_imports(raw,names):
    from cityhash import CityHash64
    h=struct.unpack_from('<16I',raw)
    hashes={((CityHash64((p+'/'+p.rsplit('/',1)[-1]).lower().encode('utf-16-le'))&((1<<62)-1))|(2<<62)):p for p in names if p.startswith('/Game/')}
    return [hashes.get(v[0],'') for v in struct.iter_unpack('<Q',raw[h[10]:h[11]])]

def skeleton(raw,names):
    h=struct.unpack_from('<16I',raw);found=[]
    for at in range(h[13]+h[14],min(len(raw)-32,100000)):
        count=struct.unpack_from('<I',raw,at)[0]
        if not 20<=count<=600 or at+8+count*52>len(raw):continue
        if struct.unpack_from('<I',raw,at+4+count*12)[0]!=count:continue
        info=[struct.unpack_from('<IIi',raw,at+4+i*12) for i in range(count)]
        if any(a>=len(names) or b>1000 or not -1<=parent<i for i,(a,b,parent) in enumerate(info)):continue
        pose=np.frombuffer(raw,dtype='<f4',count=count*10,offset=at+8+count*12).reshape(count,10).copy()
        if not np.isfinite(pose).all() or not np.allclose(np.linalg.norm(pose[:,:4],axis=1),1,atol=.01):continue
        bones=[{'name':names[a]+('_'+str(b-1) if b else ''),'parent':parent} for a,b,parent in info]
        found.append((at,bones,pose))
    if len(found)!=1:raise ValueError('无法唯一识别原版头模骨架')
    return found[0]

def local_matrix(q,t,s):
    x,y,z,w=q
    m=np.array([[1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w,0],
                [2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w,0],
                [2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y,0],[0,0,0,1]],float)
    m[:3,:3]*=s;m[:3,3]=t;return m

def mesh_glb(assets,path):
    raw=assets.raw(path);names=package_names(raw);start,bones,poses=skeleton(raw,names);imports=object_imports(raw,names)
    materials=[]
    for count in range(1,33):
        at=start-4-count*40
        if at<0 or struct.unpack_from('<I',raw,at)[0]!=count:continue
        refs=[struct.unpack_from('<i',raw,at+4+i*40)[0] for i in range(count)]
        if all(v<0 and -v-1<len(imports) and imports[-v-1] for v in refs):materials=[imports[-v-1] for v in refs];break
    if not materials:raise ValueError('无法识别原版头模的材质映射')
    marker=b'\x01\x01\0\0\0\0\x01\0\0\0';at=0;lods=[]
    while (at:=raw.find(marker,at))>=0:
        try:lods.append(read_lod(raw,at))
        except (ValueError,struct.error):pass
        at+=1
    if not lods:raise ValueError('此原版脸模的网格档位尚未适配')
    lod=max(lods,key=lambda x:x['vertices']);count=lod['vertices'];binary=bytearray()
    doc={'asset':{'version':'2.0','generator':'Player Studio Android UE4.26 reader'},'buffers':[{}],
         'bufferViews':[],'accessors':[],'nodes':[],'meshes':[],'materials':[],'skins':[],'scenes':[{'nodes':[]}],'scene':0}
    def accessor(values,kind,component=5126):
        values=np.asarray(values,dtype={5126:'<f4',5125:'<u4',5123:'<u2'}[component])
        while len(binary)%4:binary.append(0)
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':values.nbytes});binary.extend(values.tobytes())
        entry={'bufferView':view,'componentType':component,'count':len(values),'type':kind}
        if kind=='VEC3':entry.update(min=values.min(axis=0).tolist(),max=values.max(axis=0).tolist())
        doc['accessors'].append(entry);return len(doc['accessors'])-1
    global_matrices=[]
    for i,(bone,pose) in enumerate(zip(bones,poses)):
        rotation=pose[[0,2,1,3]].astype(float);rotation[3]*=-1
        translation=pose[[4,6,5]].astype(float)/100;scale=pose[[7,9,8]].astype(float)
        node={'name':bone['name'],'rotation':rotation.tolist(),'translation':translation.tolist(),'scale':scale.tolist()}
        doc['nodes'].append(node);matrix=local_matrix(rotation,translation,scale)
        if bone['parent']>=0:
            parent=bone['parent'];doc['nodes'][parent].setdefault('children',[]).append(i);matrix=global_matrices[parent]@matrix
        else:doc['scenes'][0]['nodes'].append(i)
        global_matrices.append(matrix)
    ibm=np.linalg.inv(np.stack(global_matrices)).transpose(0,2,1).reshape(len(bones),16)
    doc['skins']=[{'joints':list(range(len(bones))),'inverseBindMatrices':accessor(ibm,'MAT4')}]
    positions=np.frombuffer(lod['positions'],dtype='<f4').reshape(count,3)[:,[0,2,1]]/100
    packed=np.frombuffer(lod['tangents'],dtype=np.uint8).reshape(count,-1)
    if lod['high_tangent']:raise ValueError('此脸模的高精度切线尚未适配')
    normals=((packed[:,4:7]^128).astype(float)/127.5-1)[:,[0,2,1]];normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
    uv=np.frombuffer(lod['uv_data'],dtype='<f4' if lod['full_uv'] else '<f2').reshape(count,lod['nuv'],2)[:,0].astype(float)
    source=np.frombuffer(lod['skin'],dtype=np.uint8).reshape(count,8);joints=np.zeros((count,4),dtype='<u2');weights=source[:,4:].astype(float)/255
    for section in lod['sections']:
        begin,end=section['base_vertex'],section['base_vertex']+section['vertices'];mapping=np.asarray(section['bones'])
        if np.any(source[begin:end,:4]>=len(mapping)):raise ValueError('原版脸模蒙皮索引越界')
        joints[begin:end]=mapping[source[begin:end,:4]]
    attributes={'POSITION':accessor(positions,'VEC3'),'NORMAL':accessor(normals,'VEC3'),'TEXCOORD_0':accessor(uv,'VEC2'),
                'JOINTS_0':accessor(joints,'VEC4',5123),'WEIGHTS_0':accessor(weights,'VEC4')}
    indices=np.frombuffer(lod['indices'],dtype='<u2' if lod['index_width']==2 else '<u4');primitives=[]
    for section in lod['sections']:
        index=section['material']
        if not 0<=index<len(materials):raise ValueError('原版脸模材质编号越界')
        faces=indices[section['base_index']:section['base_index']+section['triangles']*3]
        primitives.append({'attributes':attributes,'indices':accessor(faces,'SCALAR',5125),'material':index})
    for path in materials:
        name=path.rsplit('/',1)[-1];material={'name':name,'extras':{'studio_material_path':path},'pbrMetallicRoughness':{'metallicFactor':0,'roughnessFactor':1}}
        if 'hair' in name.lower() or 'eyelash' in name.lower():material.update(alphaMode='MASK',alphaCutoff=.3333,doubleSided=True)
        doc['materials'].append(material)
    doc['meshes']=[{'primitives':primitives}];doc['scenes'][0]['nodes'].append(len(doc['nodes']));doc['nodes'].append({'mesh':0,'skin':0,'name':'NativeHead'})
    doc['buffers'][0]['byteLength']=len(binary);text=json.dumps(doc,separators=(',',':')).encode();text+=b' '*(-len(text)%4);binary+=b'\0'*(-len(binary)%4)
    payload=struct.pack('<II',len(text),0x4e4f534a)+text+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<4sII',b'glTF',2,len(payload)+12)+payload
