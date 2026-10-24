from pathlib import Path
import copy,json,struct,sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_glb import Glb
from rig_compatibility import adapt_skeleton
from test_head_preview import fixture

def changed(raw,bone,offset):
    source=Glb(raw);doc=copy.deepcopy(source.doc);binary=bytearray(source.binary)
    doc['nodes'][bone]['translation']=[offset,0,0]
    access=doc['accessors'][doc['skins'][0]['inverseBindMatrices']];view=doc['bufferViews'][access['bufferView']]
    at=view.get('byteOffset',0)+access.get('byteOffset',0)+bone*64+12*4;struct.pack_into('<f',binary,at,-offset)
    text=json.dumps(doc,separators=(',',':')).encode();text+=b' '*(-len(text)%4);binary.extend(b'\0'*(-len(binary)%4))
    chunks=struct.pack('<II',len(text),0x4e4f534a)+text+struct.pack('<II',len(binary),0x004e4942)+binary
    return Glb(struct.pack('<4sII',b'glTF',2,len(chunks)+12)+chunks)

class RigCompatibilityTests(unittest.TestCase):
    def test_unused_bones_and_submillimetre_facial_pivots_rebind_without_geometry_changes(self):
        source=Glb(fixture(1.38));reference=changed(fixture(1.38),15,.5)
        rebound,report=adapt_skeleton(source,reference);self.assertEqual(report['status'],'compatible-template-rebind')
        for key in ('POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'):
            np.testing.assert_array_equal(source.read(source.head()['attributes'][key]),rebound.read(rebound.head()['attributes'][key]))
        _,report=adapt_skeleton(source,changed(fixture(1.38),14,.00025));self.assertTrue(report['authored_geometry_unchanged'])
    def test_foreign_binding_warns_and_uses_neutral_attachment_without_changing_geometry(self):
        source=Glb(fixture(1.38))
        for bone,amount in ((5,.01),(14,.01)):
            rebound,report=adapt_skeleton(source,changed(fixture(1.38),bone,amount))
            self.assertEqual(report['status'],'neutral-native-attachment');self.assertTrue(report['warning'])
            np.testing.assert_array_equal(source.read(source.head()['attributes']['POSITION']),rebound.read(rebound.head()['attributes']['POSITION']))
        reference=Glb(fixture(1.38));reference.doc['nodes'][14]['name']='different'
        _,report=adapt_skeleton(source,reference);self.assertEqual(report['status'],'neutral-native-attachment')

if __name__=='__main__':unittest.main()
