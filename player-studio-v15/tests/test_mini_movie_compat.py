import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mini_movie_compat import MiniMovieCompatibility
from card_motion import MiniTextures

class MiniCompatibilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  source=Path(__file__).resolve().parents[1]/'resources/card-mini-compat/0500-317-m02.usm'
  raw=source.read_bytes();(self.root/'mini.usm').write_bytes(raw)
  self.row={'label':'family','mini_names':['0500_317_f02','smi_585b07692ee8'],'source_package':'/Game/Movies/PlayerCard/0500_317_f02_v',
   'source_package_sha256':hashlib.sha256(b'source').hexdigest(),'file':'mini.usm','sha256':hashlib.sha256(raw).hexdigest()}
  self.write()
 def write(self):(self.root/'card-mini-compat.json').write_text(json.dumps({'movies':[self.row]}),'utf8')
 def test_only_inspected_family_redirects_and_repeated_import_reuses_one_movie(self):
  class Assets:
   def get(self,path):return b'source',{}
  compat=MiniMovieCompatibility(Assets(),self.root)
  with patch('private_card_motion.movie_packages',return_value=[('/Game/private',b'raw',{})])as build:
   mini=MiniTextures(None,lambda x:x,compat)
   target=mini.isolate('0500_317_f02');self.assertEqual(target,mini.isolate('smi_585b07692ee8'))
   self.assertEqual(build.call_count,1);self.assertEqual(len(compat.movies),1);self.assertEqual(len(compat.art),1)
   self.assertIsNone(compat.redirect('0500_316_f02'));self.assertTrue(compat.reports[0]['large_movie_unchanged'])
 def test_unknown_native_movie_is_not_silently_replaced(self):
  class Assets:
   def get(self,path):return b'different-update',{}
  compat=MiniMovieCompatibility(Assets(),self.root)
  self.assertIsNone(compat.redirect('0500_317_f02'));self.assertFalse(compat.art);self.assertFalse(compat.movies)
  self.assertFalse(compat.reports[0]['applied'])
 def test_damaged_packaged_video_is_reported_before_export(self):
  class Assets:
   def get(self,path):return b'source',{}
  (self.root/'mini.usm').write_bytes(b'corrupted')
  with self.assertRaisesRegex(ValueError,'兼容视频损坏'):MiniMovieCompatibility(Assets(),self.root).redirect('0500_317_f02')

 def test_full_movie_metadata_repair_preserves_source_video_and_is_idempotent(self):
  self.row.update(large_info={'width':480,'height':678,'frames':217,'duration':217/30},
                  repaired_package_sha256=[hashlib.sha256(b'repaired').hexdigest()]);self.write()
  class Assets:
   raw=b'source'
   def get(self,path):return self.raw,{}
  assets=Assets();compat=MiniMovieCompatibility(assets,self.root)
  packages=[(self.row['source_package'],b'repaired',{})]
  with patch('private_card_motion.movie_metadata_packages',return_value=packages)as build:
   compat.prepare_large(['PesMobile/Content/Movies/PlayerCard/0500_317_f02_v.usm'])
   self.assertEqual(build.call_count,1);self.assertTrue(compat.reports[-1]['source_video_unchanged'])
   self.assertFalse(compat.movies)
   assets.raw=b'repaired';again=MiniMovieCompatibility(assets,self.root)
   again.prepare_large(['PesMobile/Content/Movies/PlayerCard/0500_317_f02_v.usm'])
   self.assertEqual(build.call_count,1);self.assertTrue(again.reports[-1]['already_repaired'])
   with patch('private_card_motion.movie_packages',return_value=[]):self.assertTrue(again.redirect('0500_317_f02'))

 def test_full_movie_repair_never_modifies_an_unknown_update_or_absent_series(self):
  self.row.update(large_info={'width':480,'height':678,'frames':217,'duration':217/30},
                  repaired_package_sha256=[hashlib.sha256(b'repaired').hexdigest()]);self.write()
  class Assets:
   def get(self,path):return b'future-update',{}
  compat=MiniMovieCompatibility(Assets(),self.root)
  with patch('private_card_motion.movie_metadata_packages')as build:
   compat.prepare_large([]);build.assert_not_called()
   compat.prepare_large(['PesMobile/Content/Movies/PlayerCard/0500_317_f02_v.usm']);build.assert_not_called()
  self.assertFalse(compat.art);self.assertFalse(compat.reports[-1]['applied'])

 def test_audited_native_video_is_mounted_without_transcoding_and_rejects_changed_payload(self):
  payload=b'CRID original video'
  self.row.update(large_info={'width':480,'height':678,'frames':217,'duration':217/30},
                  repaired_package_sha256=[hashlib.sha256(b'source').hexdigest()],
                  source_movie_sha256=hashlib.sha256(payload).hexdigest());self.write()
  class Assets:
   def get(self,path):return b'source',{}
  compat=MiniMovieCompatibility(Assets(),self.root)
  paths=['PesMobile/Content/Movies/PlayerCard/0500_317_f02_v.usm']
  compat.prepare_large(paths,lambda name:payload)
  self.assertEqual(compat.native_movies,{'PlayerCard/0500_317_f02_v.usm':payload})
  with self.assertRaisesRegex(ValueError,'原始资源不一致'):
   MiniMovieCompatibility(Assets(),self.root).prepare_large(paths,lambda name:b'changed')

 def test_native_movie_pak_requires_explicit_native_name_admission(self):
  from private_card_motion import write_movie_pak,read_movie_pak
  path=self.root/'native.pak';payload=b'CRID original video'
  movies={'PlayerCard/0500_317_f02_v.usm':payload};write_movie_pak(path,movies)
  with self.assertRaisesRegex(ValueError,'文件名无效'):read_movie_pak(path.read_bytes())
  self.assertEqual(read_movie_pak(path.read_bytes(),allow_native=True),movies)

if __name__=='__main__':unittest.main()
