from pathlib import Path
from types import SimpleNamespace
import json,sys,tempfile,threading,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coach_portraits import original_portraits

PREFIX='../../../PesMobile/Content/Assets/ui/Data/Symbol/Coach/'

class CoachPortraitTests(unittest.TestCase):
 def library(self,folder,paths):
  root=Path(folder);assets=root/'assets';assets.mkdir();converted=root/'converted';converted.mkdir()
  calls=[]
  def run(paths):
   calls.append(paths)
   for path in paths:
    output=converted/Path(path).with_suffix('.png');output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'portrait:'+path.encode())
  def asset(path,kind):
   name=path.name;(assets/name).write_bytes(path.read_bytes());return {'id':name}
  return SimpleNamespace(state={'phase':'ready'},convert_lock=threading.Lock(),face_assets=lambda:SimpleNamespace(files=set(paths)),cache={},cache_path=root/'cache.json',store=SimpleNamespace(root=root,import_asset=asset),converted=converted,run=run,calls=calls)
 def test_exact_variant_and_base_portraits_are_cached_without_reconversion(self):
  with tempfile.TemporaryDirectory() as folder:
   library=self.library(folder,[PREFIX+'coach_8_.uasset',PREFIX+'coach_99_.uasset',PREFIX+'Variation/coach_99_.uasset'])
   rows=[{'id':'8'},{'id':'99'}];result=original_portraits(library,rows,['8','99'])
   self.assertEqual(result['portraits']['8']['asset_id'],'coach_8_.png')
   self.assertIn('/Variation/',result['portraits']['99']['native_path'])
   self.assertEqual(len(library.calls),1);original_portraits(library,rows,['8','99']);self.assertEqual(len(library.calls),1)
   self.assertEqual(json.loads(library.cache_path.read_text())['coach:99'],result['portraits']['99'])
 def test_missing_portrait_never_substitutes_another_coach(self):
  with tempfile.TemporaryDirectory() as folder:
   library=self.library(folder,[PREFIX+'coach_8_.uasset']);result=original_portraits(library,[{'id':'9'}],['9'])
   self.assertTrue(result['portraits']['9']['missing']);self.assertNotIn('asset_id',result['portraits']['9']);self.assertFalse(library.calls)
   for ids in ([],['8'],['../8'],[str(i) for i in range(25)],'9'):
    with self.assertRaises(ValueError):original_portraits(library,[{'id':'9'}],ids)
 def test_not_ready_and_conversion_failure_can_be_retried(self):
  with tempfile.TemporaryDirectory() as folder:
   library=self.library(folder,[PREFIX+'coach_8_.uasset']);rows=[{'id':'8'}]
   library.state={'phase':'missing'};self.assertFalse(original_portraits(library,rows,['8'])['ready']);self.assertFalse(library.calls)
   library.state={'phase':'ready'};run=library.run
   def fail(paths):raise OSError('decoder unavailable')
   library.run=fail;self.assertTrue(original_portraits(library,rows,['8'])['portraits']['8']['unavailable']);self.assertFalse(library.cache)
   library.run=run;self.assertIn('asset_id',original_portraits(library,rows,['8'])['portraits']['8'])

if __name__=='__main__':unittest.main()
