"""Rebind harmless template revisions without moving authored head geometry."""
import copy,json,struct
import numpy as np
from native_glb import Glb,verify_skeleton

def adapt_skeleton(glb,reference):
    try:return _adapt_skeleton(glb,reference)
    except ValueError as exc:return attach_to_native(glb,reference,str(exc))


def attach_to_native(glb,reference,reason):
    """Keep imported geometry/UVs; use a neutral native attachment when rigs differ."""
    primitive=glb.head();attrs=primitive['attributes'];positions=glb.read(attrs['POSITION']);count=len(positions)
    skin=reference.doc['skins'][0];names=[reference.doc['nodes'][j]['name'] for j in skin['joints']]
    head=names.index('sk_head');doc=copy.deepcopy(glb.doc);binary=bytearray(glb.binary)
    # Foreign facial channels cannot drive an unrelated topology safely.
    # The original source file remains available for export without changes.
    doc.pop('animations',None)
    nodes=copy.deepcopy(reference.doc['nodes']);node_index=len(nodes);nodes.append({'mesh':0,'skin':0,'name':'ImportedHead'})
    doc['nodes']=nodes;doc['skins']=[copy.deepcopy(skin)];doc['scenes']=[{'nodes':[node_index]+[i for i in range(node_index) if not any(i in n.get('children',[]) for n in nodes[:node_index])]}];doc['scene']=0
    # Do not keep the reference mesh node, which would render a second head.
    for node in nodes[:node_index]:node.pop('mesh',None);node.pop('skin',None)
    def add(array,kind,component):
        binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);raw=np.asarray(array,dtype='<u2' if component==5123 else '<f4').tobytes();binary.extend(raw)
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(raw)})
        idx=len(doc['accessors']);doc['accessors'].append({'bufferView':view,'componentType':component,'type':kind,'count':len(array)});return idx
    joints=np.zeros((count,4),dtype=np.uint16);joints[:,0]=head;weights=np.zeros((count,4),dtype=np.float32);weights[:,0]=1
    doc['meshes'][0]['primitives'][0]['attributes'].update(JOINTS_0=add(joints,'VEC4',5123),WEIGHTS_0=add(weights,'VEC4',5126))
    doc['skins'][0]['inverseBindMatrices']=add(reference.read(skin['inverseBindMatrices']),'MAT4',5126)
    doc['buffers'][0]['byteLength']=len(binary);raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4);binary.extend(b'\0'*(-len(binary)%4))
    chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    result=Glb(struct.pack('<4sII',b'glTF',2,len(chunks)+12)+chunks);verify_skeleton(result,reference)
    return result,{'status':'neutral-native-attachment','warning':'导入骨架与原生不同，已使用原生头骨中性绑定继续导出；原 GLB 保留。面部表情权重未迁移，请检查头颈位置。','reason':reason,'authored_geometry_unchanged':True}


def _adapt_skeleton(glb,reference):
    try:verify_skeleton(glb,reference);return glb,{'status':'exact-native-rig'}
    except ValueError:pass
    own,game=glb.doc.get('skins',[]),reference.doc.get('skins',[])
    if len(own)!=1 or len(game)!=1:raise ValueError('头模需要一套可核对的原生骨架')
    left=[glb.doc['nodes'][n] for n in own[0]['joints']];right=[reference.doc['nodes'][n] for n in game[0]['joints']]
    if [n.get('name') for n in left]!=[n.get('name') for n in right]:raise ValueError('新版骨骼名称或顺序改变，不能自动迁移头模')
    def parents(doc,skin):
        names={n:doc['nodes'][n].get('name') for n in skin['joints']};return {names[c]:names[p] for p in names for c in doc['nodes'][p].get('children',[]) if c in names}
    if parents(glb.doc,own[0])!=parents(reference.doc,game[0]):raise ValueError('新版骨架层级改变，需要重新绑定')
    attrs=glb.head()['attributes'];joints=glb.read(attrs['JOINTS_0']);weights=glb.read(attrs['WEIGHTS_0']);used=set(joints[weights>1e-7].astype(int))
    inverse=glb.read(own[0]['inverseBindMatrices']);target=reference.read(game[0]['inverseBindMatrices'])
    if inverse.shape!=target.shape:raise ValueError('新版绑定矩阵数量改变')
    adjusted=[]
    for i,(a,b) in enumerate(zip(left,right)):
        name=a.get('name','');facial=name.startswith('skf_')
        if i in used:
            # Never silently retarget a different head/neck/body pivot. Facial
            # template drift up to 1 mm is safe to rebind at the same neutral
            # mesh; actual facial behaviour still follows the player's switch.
            tolerance=.001 if facial else 1e-6
            for key,default in [('translation',[0,0,0]),('rotation',[0,0,0,1]),('scale',[1,1,1])]:
                if not np.allclose(a.get(key,default),b.get(key,default),atol=tolerance if key=='translation' else 1e-6,rtol=0):raise ValueError('新版已使用骨骼的绑定姿态改变：'+name)
            if not np.allclose(inverse[i],target[i],atol=tolerance,rtol=0):raise ValueError('新版已使用骨骼的逆绑定姿态改变：'+name)
        if a!=b or not np.array_equal(inverse[i],target[i]):adjusted.append(name)
    doc=copy.deepcopy(glb.doc);binary=bytearray(glb.binary)
    for node,template in zip(own[0]['joints'],right):
        for key in ('translation','rotation','scale','matrix'):
            doc['nodes'][node].pop(key,None)
            if key in template:doc['nodes'][node][key]=copy.deepcopy(template[key])
    binary.extend(b'\0'*(-len(binary)%4));at=len(binary);values=np.asarray(target,dtype='<f4').tobytes();binary.extend(values)
    view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':len(values)})
    index=len(doc['accessors']);doc['accessors'].append({'bufferView':view,'componentType':5126,'type':'MAT4','count':len(target)})
    doc['skins'][0]['inverseBindMatrices']=index;doc['buffers'][0]['byteLength']=len(binary)
    raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4);binary.extend(b'\0'*(-len(binary)%4))
    chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    result=Glb(struct.pack('<4sII',b'glTF',2,len(chunks)+12)+chunks);verify_skeleton(result,reference)
    # Neutral vertices, topology, UVs and embedded textures are never changed.
    for key in ('POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'):
        if not np.array_equal(glb.read(attrs[key]),result.read(result.head()['attributes'][key])):raise ValueError('迁移绑定意外改变了头模网格，已停止')
    return result,{'status':'compatible-template-rebind','adjusted_bones':adjusted,'authored_geometry_unchanged':True,'maximum_used_facial_pivot_tolerance_m':.001}
