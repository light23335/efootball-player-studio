from pathlib import Path
from types import SimpleNamespace
import copy,hashlib,json,sqlite3,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from card_motion import prepare,replacement_indices,MiniTextures

ROOT=Path(__file__).resolve().parents[2]
CACHE=ROOT/'球员工坊-V17/library/versions/V17-1f38a585/containers'

class MiniIsolationValidation(unittest.TestCase):
 def test_empty_or_invalid_names_do_not_load_any_assets(self):
  mini=MiniTextures(None,lambda n:n)
  self.assertEqual(mini.isolate(''),'')
  for name in ('../foreign','UPPER','a'*23):
   with self.assertRaises(ValueError):mini.isolate(name)
  self.assertFalse(mini.art)
 def test_only_exact_compiled_paths_can_be_replaced(self):
  container=SimpleNamespace(paths={'../../../PesMobile/Content/owned.uasset':2,'../../../PesMobile/Content/other.uasset':3})
  self.assertEqual(replacement_indices(container,[('/Game/owned',b'',{})]),{2})

@unittest.skipUnless(CACHE.is_dir(),'requires original card resources')
class NativeMiniIsolationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from native_art import Assets
  from native_library import NativeLibrary
  cls.assets=Assets(CACHE)
  cls.library=SimpleNamespace(face_assets=lambda:cls.assets,
   db=lambda:sqlite3.connect('file:'+str(ROOT/'player-studio-v15/resources/library.sqlite3').replace('\\','/')+'?mode=ro',uri=True))
  cls.library._alias=lambda db,name:NativeLibrary._alias(cls.library,db,name)
  cls.library.card_media=json.loads((ROOT/'player-studio-v15/resources/native-card-media.json').read_text(encoding='utf8'))
 def test_selected_and_inherited_routes_get_private_yuv_packages_without_mutation(self):
  from native_iostore import package_names
  bindings=[{'asset_key':'8000001','thumbnail_names':['8000001_b','0501_278_f02','','8000001_m','','0501_m06']}]
  prior=[{'cardId':29,**bindings[0]}];before=copy.deepcopy((bindings,prior))
  result=prepare(self.library,bindings,prior,{},False)
  self.assertEqual((bindings,prior),before)
  values=result['bindings'][0]['thumbnail_names'];self.assertEqual(values[0],bindings[0]['thumbnail_names'][0]);self.assertEqual(values[3],bindings[0]['thumbnail_names'][3])
  self.assertEqual(values,result['routes'][0]['thumbnail_names']);self.assertNotEqual(values[1],bindings[0]['thumbnail_names'][1])
  self.assertFalse(result['stock_routes']);self.assertEqual(len(result['packages']),6)
  for path,raw,meta in result['packages'][2:]:
   self.assertIn('/Game/Movies/PlayerCard/'+('0501_m06_v' if values[5]+'_v' in path else '0501_278_f02_v'),package_names(raw))
   self.assertEqual(meta['exports'],4)
 def test_disabled_movies_do_not_generate_movie_packages(self):
  b={'thumbnail_names':['8000001_b','','','8000001_m','','']}
  result=prepare(self.library,[b],[],{},False)
  self.assertEqual(result['bindings'],[b]);self.assertEqual(len(result['packages']),2)
 def test_alias_without_a_matching_texture_resolves_the_exact_original_alias(self):
  values=['8000001_b','0601_481_f02','','8000001_m','','']
  result=prepare(self.library,[{'thumbnail_names':values}],[],{},False)
  from native_iostore import package_names
  self.assertEqual(len(result['packages']),4)
  for _,raw,_ in result['packages'][2:]:self.assertIn('/Game/Movies/PlayerCard/0601_480_f02_v',package_names(raw))
 def test_reexport_reuses_private_names_and_package_bytes(self):
  values=['8000001_b','0501_278_f02','','8000001_m','','0501_m06']
  first=prepare(self.library,[{'thumbnail_names':values}],[],{},False)
  art={p:(raw,meta) for p,raw,meta in first['packages']}
  original=self.assets
  class Overlay:
   def get(self,path):return art[path] if path in art else original.get(path)
  lib=copy.copy(self.library);lib.face_assets=lambda:Overlay()
  second=prepare(lib,first['bindings'],[],{},False)
  self.assertEqual(first['bindings'],second['bindings'])
  self.assertEqual({p:(r,m) for p,r,m in first['packages']},{p:(r,m) for p,r,m in second['packages']})
 def test_compiler_output_matches_successful_trial3(self):
  record=ROOT/'球员工坊-V15/诊断记录/MuMu抽卡与比赛计划闪退-20261025/独立视频纹理测试3/package-verification.json'
  if not record.is_file():self.skipTest('private trial verification receipt unavailable')
  import zipfile
  proof=json.loads(record.read_text(encoding='utf8'))
  if not Path(proof['source']).is_file():self.skipTest('private trial source APK was removed from the export cache')
  with zipfile.ZipFile(proof['source']) as archive:doc=json.loads(archive.read('assets/gateway-release/custom-resources/personal-player-studio/players.json'))
  source=doc['native_binding'];records={r['key']<<28:b'' for r in source['profile']['thumbnail_hook']['stock_routes']}
  original=copy.deepcopy(source)
  result=prepare(self.library,[],source['routes'],records,True)
  self.assertEqual(source,original)
  expected={r['new_path']:r['output_sha256'] for r in proof['texture_packages']}
  actual={p:hashlib.sha256(raw).hexdigest() for p,raw,_ in result['packages'][2:]}
  self.assertEqual(actual,expected)
  self.assertEqual(len(result['stock_routes']),proof['stock_mini_routes'])
  self.assertEqual(result['reports'][-1]['mini_video_textures_isolated'],56)

if __name__=='__main__':unittest.main()
