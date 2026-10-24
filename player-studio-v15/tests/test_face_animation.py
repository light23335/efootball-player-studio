from pathlib import Path
import copy,sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_mesh import custom_face_bone_map,head_arrays,make_lod,read_lod

class CustomFaceAnimationTests(unittest.TestCase):
    def test_native_jaw_and_eye_motion_cannot_pull_custom_face_but_head_neck_still_move(self):
        class Head:
            doc={'skins':[{'joints':list(range(16))}],
                 'nodes':[{'name':('sk_head' if i==7 else 'skf_'+str(i) if i>=8 else 'body_'+str(i)),
                           'children':[i+1] if i<7 else list(range(8,16)) if i==7 else []} for i in range(16)]}
            arrays={'p':np.arange(300,dtype=float).reshape(100,3)*.001,'n':np.tile([0.,1.,0.],(100,1)),
                    'uv':np.arange(200,dtype=float).reshape(100,2)*.001,
                    'j':np.tile([5,7,8,14],(100,1)),'w':np.tile([.1,.2,.3,.4],(100,1)),
                    'i':np.arange(99).reshape(-1,1)}
            def head(self):return {'attributes':dict(POSITION='p',NORMAL='n',TEXCOORD_0='uv',JOINTS_0='j',WEIGHTS_0='w'),'indices':'i'}
            def read(self,key):return self.arrays[key].copy()
        head=Head();saved=copy.deepcopy(head.arrays);before=head_arrays(head,16)
        mapping=custom_face_bone_map(head,range(16));fixed=head_arrays(head,16,bone_remap=mapping)
        for key in ('positions','faces','uv','tangents'):np.testing.assert_array_equal(before[key],fixed[key])
        for key in saved:np.testing.assert_array_equal(head.arrays[key],saved[key])
        def offset(mesh,translations):
            joints=np.asarray(mesh['bones'])[mesh['skin'][:,:4]]
            return (translations[joints]*mesh['skin'][:,4:,None]/255).sum(1)
        movement=np.zeros((16,3));movement[8:]=[0,-15,5]
        self.assertGreater(float(np.linalg.norm(offset(before,movement),axis=1).max()),10)
        np.testing.assert_array_equal(offset(fixed,movement),np.zeros((100,3)))
        movement[:]=0;movement[5]=[10,0,0];movement[7]=[0,0,10]
        expected=np.tile([26/255*10,0,229/255*10],(100,1))
        np.testing.assert_allclose(offset(fixed,movement),expected)
        # The close-up and match slots both retain the same safe expression.
        for active in (range(16),range(8)):
            safe=head_arrays(head,16,bone_remap=custom_face_bone_map(head,active))
            template={'required':np.arange(16,dtype='<u2').tobytes(),'active':np.asarray(list(active),dtype='<u2').tobytes(),'nuv':1}
            lod=read_lod(make_lod(template,safe),0)
            self.assertEqual(lod['sections'][0]['bones'],[5,7])
            self.assertTrue(all(head.doc['nodes'][b]['name'].startswith('body_') or b==7 for b in lod['sections'][0]['bones']))

if __name__=='__main__':unittest.main()
