"""Real V17 readback tests; opt in with V17_CONTAINERS (read-only input)."""
import copy,hashlib,os,tempfile,types,unittest
from pathlib import Path

import numpy as np
from PIL import Image
from native_art import Assets
from native_glb import Glb
from native_iostore import Container,package_header,package_id,write_container
from native_body import container_parts,texture_mips
from native_stadium_table import read_groups
from stadium_assets import compile_stand_tifos,stand_image,stand_preview,stand_native_pixels,verify_stand_tifos


@unittest.skipUnless(os.environ.get('V17_CONTAINERS'),'requires read-only V17_CONTAINERS')
class StandTifoNativeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.assets=Assets(Path(os.environ['V17_CONTAINERS']))
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=types.SimpleNamespace(root=Path(self.temp.name));(self.store.root/'assets').mkdir()
  image=Image.new('RGBA',(1024,512),(240,25,35,255));image.paste((25,60,245,255),(512,0,1024,512))
  self.image=image;self.path=self.store.root/'assets'/'test.png';image.save(self.path)
 def compile(self,layouts=('poster','poster'),assets=None):
  slots=[{'stadium_id':101+i,'custom_stadium_name':'Test '+str(i),'stand_tifo':{'asset':'test.png','name':'Test','layout':layout}}for i,layout in enumerate(layouts)]
  runtime={'slots':[{'stadium_id':s['stadium_id'],'entrance_set':1}for s in slots],'custom_assets':[]}
  art,reports=compile_stand_tifos(assets or self.assets,self.store,{'slots':slots},runtime)
  return art,reports,runtime,slots
 def test_native_image_surface_field_facing_and_uses_native_alpha_and_sidedness(self):
  raw=stand_preview(self.assets,self.image);g=Glb(raw);p=g.doc['meshes'][0]['primitives'][0]
  pts=g.read(p['attributes']['POSITION']);f=g.read(p['indices']).reshape(-1,3);uv=g.read(p['attributes']['TEXCOORD_0'])
  cross=np.cross(pts[f[:,1]]-pts[f[:,0]],pts[f[:,2]]-pts[f[:,0]])
  self.assertEqual(len(f),2050);self.assertTrue(np.isfinite(cross).all())
  # On the pitch-facing side the left of the uploaded image stays on the
  # left. Choosing the outside of this double-sided mesh reverses this sign.
  self.assertGreater(float(np.corrcoef(pts[:,0],uv[:,0])[0,1]),.99)
  # Both native texture and preview UV must retain source orientation.
  # Mirroring BOTH would look right in preview while still exporting wrong.
  import io
  pixels=Image.open(io.BytesIO(g.image(p))).convert('RGBA')
  self.assertEqual(pixels.tobytes(),self.image.tobytes())
  for side,x in ((0,pts[:,0].min()),(1,pts[:,0].max())):
   selected=uv[np.isclose(pts[:,0],x),0].mean();px=min(1023,int(selected*1023))
   self.assertEqual(pixels.getpixel((px,10)),self.image.getpixel((16 if side==0 else 1007,10)))
  self.assertTrue((uv>=0).all()and(uv<=1).all());self.assertAlmostEqual(float(pts[:,0].min()+pts[:,0].max()),0,places=4)
  m=g.doc['materials'][0];self.assertEqual(m['alphaMode'],'MASK');self.assertTrue(m['doubleSided']);self.assertAlmostEqual(m['alphaCutoff'],.3333)
 def test_final_iostore_reads_back_every_package_and_two_independent_native_themes(self):
  art,reports,runtime,_=self.compile(('poster','mosaic'))
  self.assertEqual([r['layout']for r in reports],['poster','poster'])
  self.assertEqual([s['entrance_set']for s in runtime['slots']],[200,201])
  additions,paths,packages=container_parts(art);cid=0x50535449464F
  additions.append((cid.to_bytes(8,'little')+b'\0\0\0\x0a',package_header(cid,packages)))
  output=self.store.root/'verification_P.utoc';write_container(output,additions,paths,cid)
  result=Container(output,bytes(32));reloaded=[]
  for name,expected,meta in art:
   actual=result.read('../../../PesMobile/Content/'+name[6:]+'.uasset')
   self.assertEqual(actual,expected);self.assertEqual(meta['id'],package_id(name));reloaded.append((name,actual,meta))
  verify_stand_tifos(self.assets,reloaded,reports)
  lookup={p:r for p,r,_ in reloaded}
  for report in reports:
   for table in ('/Game/Assets/bg/AdditionalAsset/Blueprint/DT_CS_EntranceSet1','/Game/Assets/bg/AdditionalAsset/Table/CDT_CS_EntranceSet1'):
    old=read_groups(self.assets.get(table)[0])[3]['1']['assets'];row=read_groups(lookup[table])[3][str(report['row_id'])]['assets']
    self.assertEqual({k:v for k,v in row.items()if k!='Choreography'},{k:v for k,v in old.items()if k!='Choreography'})
   self.assertFalse(report['crowd_mosaic']);self.assertFalse(report['in_game_tested'])
   self.assertEqual(texture_mips(lookup[report['texture']])['mips'][0]['sha256'],report['image_pixels_sha256'])
 def test_reordered_reexport_preserves_theme_ids_and_existing_rows(self):
  art,_,_,slots=self.compile();overrides={p:(r,m)for p,r,m in art};original=self.assets
  overlay=types.SimpleNamespace(files=original.files,get=lambda p:overrides.get(p)or original.get(p))
  runtime={'slots':[{'stadium_id':s['stadium_id']}for s in reversed(slots)],'custom_assets':[]}
  new,reports=compile_stand_tifos(overlay,self.store,{'slots':list(reversed(slots))},runtime)
  self.assertEqual({r['stadium_id']:r['row_id']for r in reports},{101:200,102:201})
  self.assertEqual([r['entrance_set']for r in runtime['slots']],[201,200])
  self.assertEqual(len(art),len(new))
 def test_readback_gate_rejects_thumbnail_from_another_theme(self):
  art,reports,_,_=self.compile();wrong=copy.deepcopy(reports);wrong[0]['thumbnail_pixels_sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'像素读回'):verify_stand_tifos(self.assets,art,wrong)
 def test_actual_crowd_request_is_rejected_instead_of_silently_rendering_a_banner(self):
  with self.assertRaisesRegex(ValueError,'观众逐人举牌'):self.compile(('crowd',))
 def test_removed_layout_glb_uses_the_original_whole_image(self):
  image=stand_image(self.path,'mosaic');g=Glb(stand_preview(self.assets,image));p=g.doc['meshes'][0]['primitives'][0]
  import io
  actual=Image.open(io.BytesIO(g.image(p))).convert('RGBA')
  self.assertEqual(actual.tobytes(),stand_native_pixels(stand_image(self.path,'poster')).tobytes());self.assertEqual(actual.getpixel((16,10))[3],255)

 def test_cooked_poster_preview_and_thumbnail_retain_unmirrored_source_on_reexport(self):
  before=self.path.read_bytes();art,reports,_,_=self.compile(('poster','repeat'))
  lookup={p:raw for p,raw,_ in art}
  for report in reports:
   design=stand_image(self.path,report['layout']);expected=design
   mip=texture_mips(lookup[report['texture']])['mips'][0]
   self.assertEqual(mip['sha256'],hashlib.sha256(expected.tobytes('raw','BGRA')).hexdigest())
   self.assertEqual(report['source_pixels_sha256'],hashlib.sha256(design.tobytes('raw','BGRA')).hexdigest())
  self.assertEqual(self.path.read_bytes(),before)
  again,second,_,_=self.compile(('poster','repeat'))
  self.assertEqual(art,again);self.assertEqual(reports,second)

 def test_preview_keeps_exact_native_uv0_instead_of_cancelling_a_wrong_texture_flip(self):
  from native_static_mesh import find_lods
  raw,_=self.assets.get('/Game/Assets/bg/AdditionalAsset/Entrance/Choreography/SM_choreography')
  lod=find_lods(raw)[0];index=lod['indices'][0]
  indices=np.frombuffer(index['data'],dtype='<u4'if index['width']==4 else'<u2')
  section=next(s for s in lod['sections']if s[0]==1)
  used=np.unique(indices[section[1]:section[1]+section[2]*3])
  native_uv=np.frombuffer(lod['uv'],dtype='<f4'if lod['full_uv']else'<f2').reshape(lod['vertices'],lod['nuv'],2)[used,0]
  g=Glb(stand_preview(self.assets,self.image))
  np.testing.assert_array_equal(g.read(g.head()['attributes']['TEXCOORD_0']),native_uv.astype('<f4'))


if __name__=='__main__':unittest.main()
