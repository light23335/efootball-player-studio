"""Head-only preview with the same collar, placement and LOD0 skinning as APK export."""
from pathlib import Path
import copy,hashlib,json,struct,threading
import numpy as np
from native_glb import Glb,verify_skeleton
from native_mesh import custom_face_bone_map,retained_bone_map
from native_neck import fit
from head_placement import place_without_extension

REVISION='native-roundtrip-head-preview-v3'

def preview_head(glb,reference,protected=True,neck_seam=True):
    verify_skeleton(glb,reference);doc=copy.deepcopy(glb.doc);binary=bytearray(glb.binary)
    a=glb.head()['attributes'];prepare=fit if neck_seam else place_without_extension
    changes,neck=prepare(glb,reference)
    positions=changes.get('positions',glb.read(a['POSITION'])).copy()
    normals=changes.get('normals',glb.read(a['NORMAL'])).copy()
    joints=changes.get('joints',glb.read(a['JOINTS_0'])).astype(int).copy()
    weights=changes.get('weights',glb.read(a['WEIGHTS_0'])).astype(float).copy()
    names=[reference.doc['nodes'][n].get('name','') for n in reference.doc['skins'][0]['joints']]
    affected=int(np.count_nonzero((weights*np.asarray([n.startswith('skf_') for n in names])[joints]).sum(1)>1e-7))
    mapping=custom_face_bone_map(reference,range(len(names))) if protected else retained_bone_map(reference,range(len(names)))
    joints=np.asarray(mapping)[joints]
    for col in range(1,4):
        for previous in range(col):
            same=joints[:,col]==joints[:,previous]
            weights[same,previous]+=weights[same,col];weights[same,col]=0
    weights=np.rint(weights/weights.sum(1,keepdims=True)*255).astype(int)
    weights[np.arange(len(weights)),weights.argmax(1)]+=255-weights.sum(1);weights=weights/255
    def accessor(values,kind,component=5126):
        array=np.asarray(values,dtype='<u2' if component==5123 else '<f4')
        binary.extend(b'\0'*(-len(binary)%4));offset=len(binary);binary.extend(array.tobytes())
        view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':array.nbytes})
        result={'bufferView':view,'componentType':component,'count':len(array),'type':kind}
        if kind=='VEC3':result.update(min=array.min(0).tolist(),max=array.max(0).tolist())
        index=len(doc['accessors']);doc['accessors'].append(result);return index
    primitive=doc['meshes'][0]['primitives'][0]
    primitive['attributes'].update(POSITION=accessor(positions,'VEC3'),NORMAL=accessor(normals,'VEC3'),
        JOINTS_0=accessor(joints,'VEC4',5123),WEIGHTS_0=accessor(weights,'VEC4'))
    targets=[];target_names=[]
    # Placement is linear around a fixed collar. These exact unit deltas let
    # browser handles respond without refitting/reimporting for every pixel.
    for key,label in (('head','Head'),('neck_root','Root')):
        for axis,axis_name in enumerate('XYZ'):
            handles={'head':[0,0,0],'neck_root':[0,0,0]};handles[key][axis]=1
            changed,_=prepare(glb,reference,0,handles)
            targets.append({'POSITION':accessor(changed.get('positions',glb.read(a['POSITION']))-positions,'VEC3')})
            target_names.append('Studio'+label+axis_name)
    primitive['targets']=targets;doc['meshes'][0]['weights']=[0]*6
    doc['meshes'][0].setdefault('extras',{})['targetNames']=target_names
    for node in doc['nodes']:
        if node.get('mesh')==0:node['weights']=[0]*6
    # Keep source test clips available, but the viewer never autoplays them.
    doc['buffers'][0]['byteLength']=len(binary)
    raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4);binary.extend(b'\0'*(-len(binary)%4))
    payload=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<4sII',b'glTF',2,len(payload)+12)+payload,{'neck':neck,'protected':protected,'facial_weighted_vertices':affected}

class HeadPreview:
    def __init__(self,library,package):
        self.library=library;self.package=package;self.store=library.store;self.lock=threading.Lock();self.cache={}
    def prepare(self,project):
        from project_resource_migration import prepare as prepare_project
        project,migrations=prepare_project(project,self.library.resources,self.library.face_assets())
        model=project['model'];asset=model.get('asset')
        if not asset:raise ValueError('请先选择头模')
        if (model.get('native_source') or {}).get('path'):
            path=model['native_source']['path'].removeprefix('../../../')
            if path.startswith('/Game/'):path='PesMobile/Content/'+path[6:]+'.uasset'
            with self.library.db() as db:
                row=db.execute('select id from assets where path=?',(path,)).fetchone()
            if row:
                hit=self.library.convert({'ids':[row[0]]})['results'][row[0]]
                if hit.get('error'):raise ValueError(hit['error'])
                url=hit['url']
            else:url='/assets/'+asset
            return {'revision':REVISION,'url':url,'export_url':url,'raw_url':url,'original_game_face':True,'protected':False,
                    'anchors':{},'migrations':migrations,'notice':'原版头模保留原始面部权重；张嘴和闭眼仅用于预览检查。'}
        signature=hashlib.sha256(json.dumps([REVISION,asset,model.get('rigged_asset'),model.get('neck_seam',True),model.get('preserve_expression',True)],sort_keys=True).encode()).hexdigest()
        with self.lock:
            if signature in self.cache:return copy.deepcopy(self.cache[signature])
            rig=self.package.model_binding(project);glb=Glb(Path(rig).read_bytes() if rig else (self.store.root/'assets'/asset).read_bytes())
            reference_path=self.package.reference_model();reference=Glb(reference_path.read_bytes());urls={};details={}
            from rig_compatibility import adapt_skeleton
            glb,rig_report=adapt_skeleton(glb,reference)
            for label,protected in (('export',model.get('preserve_expression') is not False),('raw',False)):
                data,details=preview_head(glb,reference,protected,model.get('neck_seam') is not False)
                target=self.store.root/'tmp'/('preview-head-'+label+'-'+signature+'.glb')
                try:target.write_bytes(data);item=self.store.import_asset(target,'model')
                finally:target.unlink(missing_ok=True)
                urls[label+'_url']=item['url']
            item=self.store.import_asset(reference_path,'model')
            base,base_report=(fit if model.get('neck_seam') is not False else place_without_extension)(glb,reference)
            v=base.get('positions',glb.read(glb.head()['attributes']['POSITION']));low=v[v[:,1]<v[:,1].min()+.005].mean(0)
            names=[reference.doc['nodes'][n].get('name') for n in reference.doc['skins'][0]['joints']]
            ibm=reference.read(reference.doc['skins'][0]['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
            head=np.linalg.inv(ibm[names.index('sk_head')])[:3,3]
            result={'revision':REVISION,**urls,'reference_url':item['url'],'anchors':{'head':head.tolist(),'neck_root':low.tolist()},
                    'neck':base_report,'rig_compatibility':rig_report,'protected':model.get('preserve_expression') is not False,'original_game_face':False,
                    'notice':(rig_report.get('warning','')+' 原版与自制头模使用相同游戏坐标。定位点调整网格接合，不改动原生骨架。预览与 APK 共用颈部处理和蒙皮；浏览器材质与游戏着色仍可能不同。').strip()}
            self.cache[signature]=copy.deepcopy(result);return result
