"""Mobile hair coverage, native section and channel translation regressions."""
from pathlib import Path
import copy,io,os,sys,unittest
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_head_materials import plan,maps,partition,remap_alpha,verify_native_hair,NATIVE_CLIP,masked_components,sample_indices
from native_mesh import make_lod,read_lod,head_arrays


class Head:
    def __init__(self,alpha_mode='MASK'):
        # Two disjoint UV islands: an opaque face and a two-triangle card.
        # The opaque half of the card must stay on the hair material too.
        self.values={0:np.array([[0,0,0],[1,0,0],[0,1,0],[2,0,0],[3,0,0],[2,1,0],[3,1,0]],dtype=float),
            1:np.array([[0,0,1]]*7,dtype=float),
            2:np.array([[.1,.1],[.4,.1],[.1,.4],[.6,.1],[.9,.1],[.6,.9],[.9,.9]]),
            3:np.zeros((7,4),dtype=int),4:np.array([[1,0,0,0]]*7,dtype=float),
            5:np.array([[0],[1],[2],[3],[4],[5],[4],[6],[5]])}
        self.primitive={'attributes':dict(POSITION=0,NORMAL=1,TEXCOORD_0=2,JOINTS_0=3,WEIGHTS_0=4),'indices':5,'material':0}
        self.doc={'materials':[{'alphaMode':alpha_mode,'alphaCutoff':.3333,'doubleSided':True,
            'pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0}}],
            'textures':[],'images':[],'bufferViews':[],'nodes':[{'name':'sk_head'}],'skins':[{'joints':[0]}]}
        self.binary=b''
        pixels=np.full((32,32,4),255,dtype=np.uint8);pixels[25:,16:,3]=0
        self.add_image(Image.fromarray(pixels))
    def head(self):return self.primitive
    def read(self,i):return self.values[i].copy()
    def add_image(self,image):
        png=io.BytesIO();image.save(png,format='PNG');raw=png.getvalue();view=len(self.doc['bufferViews'])
        self.doc['bufferViews'].append({'byteOffset':len(self.binary),'byteLength':len(raw)});self.binary+=raw
        self.doc['images'].append({'bufferView':view});self.doc['textures'].append({'source':len(self.doc['images'])-1})
        return {'index':len(self.doc['textures'])-1}


class MobileHeadMaterialTests(unittest.TestCase):
    def test_material_revision_invalidates_face_cache_without_rebuilding_card(self):
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        from compile_cache import CompileCache
        from native_art import compile_art
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'assets').mkdir();library=SimpleNamespace(store=SimpleNamespace(root=root))
            project={'appearance':{},'native_card':{},'model':{}};identity={'person_id':1}
            cache=CompileCache(root/'cache',{})
            with patch('native_art._compile_card_art',return_value=([],{},{})) as card,patch('native_art._compile_face_art',return_value=([],{})) as face:
                compile_art(project,identity,library,cache=cache)
                with patch('native_head_materials.REVISION','new-material-compiler'):
                    compile_art(project,identity,library,cache=cache)
                self.assertEqual(card.call_count,1);self.assertEqual(face.call_count,2)
    def test_mixed_atlas_keeps_opaque_face_and_whole_card(self):
        g=Head();before=copy.deepcopy(g.doc);p=plan(g)
        self.assertEqual(p['triangle_materials'].tolist(),[0,1,1]);self.assertEqual(g.doc,before)
        self.assertEqual(p['report']['hair_triangles'],2)
        self.assertEqual(p['hair_diffuse'].tobytes(),p['diffuse'].tobytes())

    def test_legacy_default_repeat_accepts_negative_and_shifted_uv_without_editing_it(self):
        g=Head();expected=plan(g)['triangle_materials']
        for offset in ((-1,-2),(2,3)):
            with self.subTest(offset=offset):
                source=Head();source.values[2]+=offset
                before=copy.deepcopy(source.values);p=plan(source)
                np.testing.assert_array_equal(p['triangle_materials'],expected)
                for key in before:np.testing.assert_array_equal(source.values[key],before[key])
                self.assertEqual(p['report']['coverage_sampler'],{'wrapS':'REPEAT','wrapT':'REPEAT'})
                self.assertTrue(p['report']['source_uv_unchanged'])
                self.assertEqual(p['report']['outside_unit_uv_vertices'],7)

    def test_seam_crossing_is_sampled_as_continuous_triangle_not_vertex_modulo(self):
        pixels=np.full((16,16,4),255,dtype=np.uint8);pixels[:,0,3]=0
        uv=np.array([[.9,.1],[1.1,.1],[1.1,.8]])
        actual,_=masked_components(np.array([[0,1,2]]),uv,Image.fromarray(pixels),.5)
        self.assertEqual(actual.tolist(),[1])
        # A vertex-wise modulo turns this into a different triangle which
        # never reaches the transparent strip at the actual U=1 crossing.
        wrong,_=masked_components(np.array([[0,1,2]]),uv%1,Image.fromarray(pixels),.5)
        self.assertEqual(wrong.tolist(),[0])

    def test_wrap_modes_and_axes_use_authored_texel_addressing(self):
        pixels=np.full((16,16,4),255,dtype=np.uint8);pixels[:,:3,3]=0
        image=Image.fromarray(pixels);faces=np.array([[0,1,2]])
        uv=np.array([[1.02,.2],[1.12,.2],[1.02,.4]])
        for wrap,expected in ((10497,1),(33071,0),(33648,0)):
            result,_=masked_components(faces,uv,image,.5,(wrap,10497))
            self.assertEqual(result.tolist(),[expected],wrap)
        # Clamp samples the left edge for negative U; repeat/mirror do not.
        uv=np.array([[-.6,.2],[-.5,.2],[-.6,.4]])
        for wrap,expected in ((10497,0),(33071,1),(33648,0)):
            result,_=masked_components(faces,uv,image,.5,(wrap,10497))
            self.assertEqual(result.tolist(),[expected],wrap)
        values=np.arange(-5,7)
        np.testing.assert_array_equal(sample_indices(values,3,33648),[1,2,2,1,0,0,1,2,2,1,0,0])

    def test_plan_reads_explicit_sampler_and_invalid_values_fail_without_uv_corruption(self):
        g=Head();g.doc['samplers']=[{'wrapS':33071,'wrapT':33648}];g.doc['textures'][0]['sampler']=0
        self.assertEqual(plan(g)['report']['coverage_sampler'],{'wrapS':'CLAMP_TO_EDGE','wrapT':'MIRRORED_REPEAT'})
        g.doc['samplers'][0]['wrapS']=123
        with self.assertRaisesRegex(ValueError,'寻址'):plan(g)
        g=Head();g.values[2][0,0]=float('nan')
        with self.assertRaisesRegex(ValueError,'无效 UV'):plan(g)
        g=Head();g.values[2][0,0]=10**20
        with self.assertRaisesRegex(ValueError,'UV 范围'):plan(g)

    def test_opaque_does_not_infer_cutouts_and_blend_fails_explicitly(self):
        self.assertEqual(plan(Head('OPAQUE'))['triangle_materials'].tolist(),[0,0,0])
        with self.assertRaisesRegex(ValueError,'BLEND'):plan(Head('BLEND'))

    def test_native_two_sided_policy_is_reported_for_single_sided_source(self):
        g=Head();g.doc['materials'][0]['doubleSided']=False;r=plan(g)['report']
        self.assertFalse(r['source_double_sided']);self.assertTrue(r['native_hair_two_sided']);self.assertTrue(r['warnings'])

    def test_cutoff_conversion_preserves_every_8bit_texel_pass_fail(self):
        a=np.full((1,256,4),255,dtype=np.uint8);a[0,:,3]=np.arange(256)
        for cutoff in (0,.01,.1,.3333,.5,.9,.999,1):
            converted=np.asarray(remap_alpha(Image.fromarray(a),cutoff))
            np.testing.assert_array_equal(converted[:,:,3]/255>=NATIVE_CLIP,a[:,:,3]/255>=cutoff)
            np.testing.assert_array_equal(converted[:,:,:3],a[:,:,:3])

    def test_mr_is_repacked_using_green_roughness_not_blue_metallic(self):
        g=Head();mat=g.doc['materials'][0];pbr=mat['pbrMetallicRoughness']
        pbr['metallicRoughnessTexture']=g.add_image(Image.new('RGBA',(4,4),(3,180,240,255)))
        pbr['roughnessFactor']=.5
        mat['occlusionTexture']={**g.add_image(Image.new('RGBA',(4,4),(55,100,200,255))),'strength':.5}
        p=plan(g);m=maps(g,p)
        self.assertEqual(m['Face_SRO'].getpixel((0,0)),(64,90,155,255))
        self.assertEqual(m['Hair_High_SRO'].tobytes(),m['Face_SRO'].tobytes())
        self.assertIn('not used',p['report']['channels']['specular'])

    def test_authored_normal_keeps_independent_dimensions_and_reports_hair_limit(self):
        g=Head();g.doc['materials'][0]['normalTexture']=g.add_image(Image.new('RGBA',(8,4),(128,128,255,255)))
        p=plan(g);m=maps(g,p);self.assertEqual(m['Face_N'].size,(8,4))
        self.assertTrue(any('NormalMap' in w for w in p['report']['warnings']))

    def test_normal_and_diffuse_keep_their_own_native_sampler_modes(self):
        g=Head();mat=g.doc['materials'][0]
        g.doc['samplers']=[{'wrapS':33071,'wrapT':10497},{'wrapS':33648,'wrapT':33071}]
        g.doc['textures'][0]['sampler']=0
        mat['normalTexture']=g.add_image(Image.new('RGBA',(4,4),(128,128,255,255)))
        g.doc['textures'][-1]['sampler']=1
        p=plan(g);maps(g,p)
        self.assertEqual(p['texture_wraps']['Face_D'],(33071,10497))
        self.assertEqual(p['texture_wraps']['Face_N'],(33648,33071))
        self.assertEqual(p['report']['native_texture_addressing']['Hair_D'],{'AddressX':'TA_Clamp','AddressY':'TA_Wrap'})

    def test_transformed_and_second_uv_textures_are_rejected(self):
        for change in ({'texCoord':1},{'extensions':{'KHR_texture_transform':{'offset':[.1,0]}}}):
            g=Head();g.doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture'].update(change)
            with self.assertRaisesRegex(ValueError,'TEXCOORD_0'):plan(g)

    def test_section_serialization_preserves_all_triangle_corner_attributes(self):
        g=Head();faces=g.values[5].reshape(-1,3);count=len(g.values[0])
        head={'faces':faces,'triangles':len(faces),'vertices':count,'bones':[0],'required_bones':[0]}
        for name,width in (('positions',3),('normals',3),('uv',2),('tangents',8),('skin',8)):
            head[name]=np.arange(count*width).reshape(count,width).astype('<f4' if name in ('positions','normals','uv') else 'uint8')
        p=partition(head,[1,0,1]);result=make_lod({'required':b'\0\0','active':b'\0\0','nuv':1},p);lod=read_lod(result,0)
        self.assertEqual([(s['material'],s['triangles']) for s in lod['sections']],[(0,1),(1,2)])
        self.assertEqual(lod['end'],len(result))
        indices=np.frombuffer(lod['indices'],dtype='<u2').reshape(-1,3)
        for name,raw,width,dtype in [('positions',lod['positions'],3,'<f4'),('tangents',lod['tangents'],8,'uint8'),('skin',lod['skin'],8,'uint8')]:
            actual=np.frombuffer(raw,dtype=dtype).reshape(-1,width)[indices]
            np.testing.assert_array_equal(actual,head[name][faces[[1,0,2]]])
        self.assertEqual(sum(s['triangles'] for s in lod['sections']),len(faces))

    def test_uv_tangents_follow_uv_rotation_and_mirror(self):
        g=Head();g.values[0]=np.tile(g.values[0],(15,1));count=len(g.values[0])
        for i in (1,2,3,4):g.values[i]=np.tile(g.values[i],(15,1))
        # head_arrays has the mobile minimum 100 vertices. Unused copies do
        # not change the first triangle, whose UV U direction is +X.
        h=head_arrays(g,1)
        decoded=(h['tangents'].astype(np.uint8)^128).astype(float)/127.5-1
        np.testing.assert_allclose(decoded[:3,:3],[[1,0,0]]*3,atol=.005)
        np.testing.assert_allclose(decoded[:3,4:7],[[0,1,0]]*3,atol=.005)
        g.values[2][:,0]=1-g.values[2][:,0];mirrored=head_arrays(g,1)
        d=(mirrored['tangents'].astype(np.uint8)^128).astype(float)/127.5-1
        np.testing.assert_allclose(d[:3,:3],[[-1,0,0]]*3,atol=.005)
        np.testing.assert_array_equal(np.sign(decoded[:3,7]),-np.sign(d[:3,7]))


CACHE=Path(os.environ.get('V17_CONTAINERS',Path(__file__).resolve().parents[2]/'球员工坊-V17/library/versions/V17-c61d1ce6/containers'))
@unittest.skipUnless(CACHE.is_dir(),'requires prepared original mobile resource cache')
class NativeHairContractTests(unittest.TestCase):
    def test_cooked_texture_sampler_survives_real_texture_rebuild_for_all_modes(self):
        import itertools
        from native_art import Assets
        from native_head_materials import compile_texture,native_texture_wrap,NATIVE_WRAP
        from native_texture import cooked_mip
        assets=Assets(CACHE);image=Image.new('RGBA',(8,4),(12,34,56,78))
        for suffix in ('Face_D','Hair_High_D','Face_N','Hair_High_SRO'):
            raw,_=assets.get('/Game/Assets/character/RealFace/T_133543_'+suffix)
            for wrap in itertools.product((10497,33071,33648),repeat=2):
                with self.subTest(channel=suffix,wrap=wrap):
                    encoded=compile_texture(raw,'/Game/Test/T_999_'+suffix,image,wrap)
                    self.assertEqual(native_texture_wrap(encoded),{'AddressX':NATIVE_WRAP[wrap[0]],'AddressY':NATIVE_WRAP[wrap[1]]})
                    mip=cooked_mip(encoded)
                    self.assertEqual((mip['width'],mip['height'],mip['format']),(8,4,'PF_B8G8R8A8'))
                    self.assertEqual(mip['data'],image.tobytes('raw','BGRA'))
                    # Recompiling an already stamped source must replace its
                    # address properties rather than append duplicate tags.
                    second=compile_texture(encoded,'/Game/Test/T_999_'+suffix,image,tuple(reversed(wrap)))
                    self.assertEqual(native_texture_wrap(second),{'AddressX':NATIVE_WRAP[wrap[1]],'AddressY':NATIVE_WRAP[wrap[0]]})

    def test_actual_hq_and_mq_contracts_reject_an_opaque_or_single_sided_template(self):
        import struct
        from native_art import Assets
        from native_iostore import package_names
        assets=Assets(CACHE)
        for quality in ('HQ','MQ'):
            raw,_=assets.get('/Game/Assets/character/RealFace/MI_133543_Head_Hair_'+quality)
            self.assertEqual(verify_native_hair(raw,quality)['blend_mode'],'BLEND_Masked')
            names=package_names(raw)
            tag=struct.pack('<6I2B',names.index('TwoSided'),0,names.index('BoolProperty'),0,0,0,1,0)
            changed=raw.replace(tag,tag[:-2]+b'\0\0')
            with self.assertRaisesRegex(ValueError,'MASK'):verify_native_hair(changed,quality)


if __name__=='__main__':unittest.main()
