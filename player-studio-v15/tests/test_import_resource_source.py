import hashlib,json,struct,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from import_resource_source import CachedCompanion,companion_archive,select_delta_sources


class DeltaResourceSourceTests(unittest.TestCase):
 def sources(self,root):
  def apk(name,marker):
   p=root/name
   with zipfile.ZipFile(p,'w')as z:z.writestr(marker,b'{}')
   return p
  main=apk('current.apk','assets/gateway-release/release-manifest.json')
  resource=apk('resource.apk','assets/resource-bootstrap/resources.zip')
  library=types.SimpleNamespace(profile={'game_version':'V17'},home=root)
  store=types.SimpleNamespace(root=root)
  (root/'active-game.json').write_text(json.dumps({'apk':str(main),'companion':str(resource)}),'utf8')
  return library,store,main,resource

 def test_current_library_paths_win_over_stale_form_paths(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);lib,store,main,resource=self.sources(root)
   selected=select_delta_sources(lib,store,{'apk':str(root/'old.apk'),'companion':str(root/'old-resource.apk')})
   self.assertEqual(selected,(main,resource))

 def test_missing_companion_uses_complete_prepared_library(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);lib,store,main,resource=self.sources(root);resource.unlink()
   cached=object()
   with patch('import_resource_source.CachedCompanion',return_value=cached)as build:
    selected=select_delta_sources(lib,store,{})
   self.assertEqual(selected,(main,cached));build.assert_called_once_with(lib,str(resource))

 def test_missing_main_has_specific_message_and_never_substitutes_resource_apk(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);lib,store,main,resource=self.sources(root);main.unlink()
   with self.assertRaisesRegex(ValueError,'主程序 APK 已移动'):select_delta_sources(lib,store,{'apk':str(resource)})

 def test_selected_main_can_replace_moved_recorded_source(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);lib,store,main,resource=self.sources(root);moved=root/'moved.apk';main.rename(moved)
   self.assertEqual(select_delta_sources(lib,store,{'apk':str(moved)}),(moved,resource))

 def test_cached_archive_excludes_old_main_patch_and_rejects_truncated_ucas(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);folder=root/'containers';folder.mkdir();key=bytes(range(32))
   (root/'ready.json').write_text(json.dumps({'release_id':'v17'}),'utf8');(folder/'resource-key.bin').write_bytes(key)
   for n in ('global','pc3600_mobile_and','pc3700_mobile_and_10_P'):
    (folder/(n+'.utoc')).write_bytes(b'index');(folder/(n+'.ucas')).write_bytes(bytes(16))
   lib=types.SimpleNamespace(root=root,containers=folder,state={'phase':'ready'},
       profile={'release_id':'v17','resource_key_sha256':hashlib.sha256(key).hexdigest()})
   def container(path,key):return types.SimpleNamespace(blocks=[bytes(5)+(16).to_bytes(3,'little')+bytes(4)],flags=0)
   with patch('native_iostore.Container',side_effect=container):
    source=CachedCompanion(lib)
    with companion_archive(source)as archive:
     self.assertEqual(len(archive.namelist()),4)
     self.assertEqual(archive.getinfo('global.ucas').file_size,16)
     with archive.open('global.ucas')as f:self.assertEqual(f.read(),bytes(16))
    (folder/'pc3600_mobile_and.ucas').write_bytes(bytes(15))
    with self.assertRaisesRegex(ValueError,'截断'):CachedCompanion(lib)

if __name__=='__main__':unittest.main()
