from pathlib import Path
import copy,json,struct,sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_glb import Glb
from native_neck import fit
from head_preview import preview_head

def fixture(bottom):
    doc={'asset':{'version':'2.0'},'bufferViews':[],'accessors':[],'buffers':[{}]}
    binary=bytearray()
    def add(values,kind,component=5126):
        a=np.asarray(values,dtype='<u2' if component==5123 else '<f4')
        binary.extend(b'\0'*(-len(binary)%4));at=len(binary);binary.extend(a.tobytes())
        doc['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':a.nbytes})
        doc['accessors'].append({'bufferView':len(doc['bufferViews'])-1,'componentType':component,'type':kind,'count':len(a)})
        return len(doc['accessors'])-1
    positions=np.asarray([[.055*np.cos(t),y,.04*np.sin(t)] for y in np.linspace(bottom,1.8,5) for t in np.arange(8)*np.pi/4])
    faces=[[r*8+k,r*8+(k+1)%8,(r+1)*8+k] for r in range(4) for k in range(8)]
    attrs={k:add(v,kind,c) for k,v,kind,c in [
        ('POSITION',positions,'VEC3',5126),('NORMAL',np.tile([0,0,1],(40,1)),'VEC3',5126),
        ('TEXCOORD_0',np.arange(80).reshape(40,2)/80,'VEC2',5126),
        ('JOINTS_0',np.tile([5,7,8,14],(40,1)),'VEC4',5123),
        ('WEIGHTS_0',np.tile([.1,.2,.3,.4],(40,1)),'VEC4',5126)]}
    nodes=[{'name':'sk_head' if i==7 else 'skf_'+str(i) if i>=8 else 'body_'+str(i),
            'children':[i+1] if i<7 else list(range(8,16)) if i==7 else []} for i in range(16)]
    inverse=np.tile(np.eye(4),(16,1,1));inverse[7,1,3]=-1.64
    doc.update(nodes=nodes,skins=[{'joints':list(range(16)),'inverseBindMatrices':add(inverse.transpose(0,2,1).reshape(16,16),'MAT4')}],
               meshes=[{'primitives':[{'attributes':attrs,'indices':add(np.asarray(faces).reshape(-1,1),'SCALAR',5123)}]}])
    doc['buffers'][0]['byteLength']=len(binary)
    raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*(-len(raw)%4);binary.extend(b'\0'*(-len(binary)%4))
    chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<4sII',b'glTF',2,len(chunks)+12)+chunks

class HeadPreviewTests(unittest.TestCase):
    def test_complete_imported_collar_is_not_extended_and_handles_match_export(self):
        source=Glb(fixture(1.38));reference=Glb(fixture(1.38));a=source.head()['attributes']
        unchanged,report=fit(source,reference)
        self.assertFalse(unchanged);self.assertTrue(report['complete_import_preserved'])
        payload,_=preview_head(source,reference);preview=Glb(payload);attrs=preview.head()['attributes']
        values=[1,-2,.5,-1,2,-.5];handles={'head':values[:3],'neck_root':values[3:]}
        moved,_=fit(source,reference,0,handles);points=preview.read(attrs['POSITION']).astype(float)
        for target,value in zip(preview.head()['targets'],values):points+=preview.read(target['POSITION'])*value
        np.testing.assert_allclose(points,moved['positions'],atol=8e-7,rtol=0)
        # The native joint nodes and bind matrices remain the same.
        self.assertEqual(preview.doc['nodes'],source.doc['nodes'])
        np.testing.assert_array_equal(preview.read(preview.doc['skins'][0]['inverseBindMatrices']),source.read(source.doc['skins'][0]['inverseBindMatrices']))
    def test_live_placement_matches_native_export_at_positive_and_negative_offsets(self):
        raw=fixture(1.56);source=Glb(raw);reference=Glb(fixture(1.38));saved=copy.deepcopy(source.doc)
        payload,report=preview_head(source,reference);preview=Glb(payload);attrs=preview.head()['attributes']
        positions=preview.read(attrs['POSITION']);delta=preview.read(preview.head()['targets'][1]['POSITION'])
        for cm in (-4,-2,0,1,4):
            changes,_=fit(source,reference,cm)
            np.testing.assert_allclose(positions+delta*cm,changes['positions'],atol=8e-7,rtol=0)
        self.assertTrue(report['protected']);self.assertGreater(report['facial_weighted_vertices'],0)
        self.assertEqual(source.doc,saved);self.assertEqual(source.binary,Glb(raw).binary)
        for name in ('TEXCOORD_0',):
            np.testing.assert_array_equal(preview.read(attrs[name]),source.read(source.head()['attributes'][name]))
        np.testing.assert_array_equal(preview.read(preview.head()['indices']),source.read(source.head()['indices']))
        joints=preview.read(attrs['JOINTS_0']);weights=preview.read(attrs['WEIGHTS_0'])
        self.assertTrue(np.all(joints[weights>0]<8));np.testing.assert_allclose(weights.sum(1),1,atol=1e-7)
        self.assertEqual(preview.doc['meshes'][0]['extras']['targetNames'],['StudioHeadX','StudioHeadY','StudioHeadZ','StudioRootX','StudioRootY','StudioRootZ'])

    def test_raw_comparison_is_separate_and_disabling_collar_fit_keeps_geometry(self):
        source=Glb(fixture(1.56));ref=Glb(fixture(1.38))
        payload,report=preview_head(source,ref,False,False);raw=Glb(payload);a=raw.head()['attributes']
        self.assertFalse(report['protected']);self.assertEqual(report['neck']['status'],'placement-without-neck-extension')
        for name in ('POSITION','NORMAL','TEXCOORD_0','JOINTS_0'):
            np.testing.assert_array_equal(raw.read(a[name]),source.read(source.head()['attributes'][name]))
        weights=raw.read(a['WEIGHTS_0']);np.testing.assert_allclose(weights.sum(1),1,atol=1e-7)
        self.assertTrue(np.any(raw.read(a['JOINTS_0'])[weights>0]>=8))

if __name__=='__main__':unittest.main()
