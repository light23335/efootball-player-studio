from pathlib import Path
from types import SimpleNamespace
import json,sys,tempfile,unittest,urllib.error
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from updates import repository,version,release_result,UpdateChecker

class UpdateTests(unittest.TestCase):
 def release(self):return {'tag_name':'v1.9.5','html_url':'https://github.com/light23335/efootball-player-studio/releases/tag/v1.9.5','body':'optional','assets':[{'name':'球员工坊-V16-安卓版.apk','browser_download_url':'https://github.com/light23335/efootball-player-studio/releases/download/v1.9.5/android.apk'},{'name':'球员工坊-V16-免安装分享版.zip','browser_download_url':'https://github.com/light23335/efootball-player-studio/releases/download/v1.9.5/windows.zip'}],'mandatory':True}
 def test_repository_is_public_github_identity_not_arbitrary_url_or_credential(self):
  self.assertEqual(repository('https://github.com/light23335/efootball-player-studio'),'light23335/efootball-player-studio')
  for value in ('https://evil.example/a/b','owner/repo?token=secret','owner/repo/extra','http://github.com/a/b','name@host/repo'):
   with self.assertRaises(ValueError):repository(value)
 def test_versions_compare_numerically_and_channels_are_separate(self):
  self.assertLess(version('v1.9.3.2'),version('V16-v1.9.4'));self.assertGreater(version('v1.10.0'),version('v1.9.99'));self.assertIsNone(version('V15-v9.9.9'))
 def test_new_version_is_optional_and_download_matches_platform(self):
  for platform,suffix in [('pc','windows.zip'),('android','android.apk')]:
   result=release_result(self.release(),'1.9.4','light23335/efootball-player-studio',platform);self.assertEqual(result['phase'],'available');self.assertFalse(result['mandatory']);self.assertTrue(result['download_url'].endswith(suffix))
 def test_prerelease_old_version_and_other_repository_do_not_become_updates(self):
  data=self.release();data['prerelease']=True;self.assertEqual(release_result(data,'1.9.4','light23335/efootball-player-studio','pc')['phase'],'current')
  data=self.release();data['tag_name']='v1.9.3.2';self.assertEqual(release_result(data,'1.9.4','light23335/efootball-player-studio','pc')['phase'],'current')
  data=self.release();data['html_url']='https://github.com/other/repo/releases/tag/v1.9.5'
  with self.assertRaises(ValueError):release_result(data,'1.9.4','light23335/efootball-player-studio','pc')
 def test_offline_and_missing_release_do_not_require_update_or_block_editor(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);checker=UpdateChecker(SimpleNamespace(root=root),root,'1.9.4')
   checker.settings({'repository':'light23335/efootball-player-studio','enabled':False})
   with patch('updates.urllib.request.urlopen',side_effect=TimeoutError),patch('updates.native_fetch',side_effect=TimeoutError):checker._check('light23335/efootball-player-studio')
   self.assertEqual(checker.status()['phase'],'offline');self.assertFalse(checker.status()['prompt'])
   with patch('updates.urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://api.github.com',404,'no release',None,None)):checker._check('light23335/efootball-player-studio')
   self.assertEqual(checker.status()['phase'],'current');self.assertFalse(checker.status()['prompt'])
 def test_missing_frozen_ssl_context_uses_verified_system_https(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);checker=UpdateChecker(SimpleNamespace(root=root),root,'1.9.4')
   with patch('updates.urllib.request.urlopen',side_effect=FileNotFoundError(2,'SSL context unavailable')),patch('updates.native_fetch',return_value=json.dumps(self.release()).encode()) as native:
    checker._check('light23335/efootball-player-studio')
   self.assertEqual(checker.status()['phase'],'available');self.assertTrue(checker.status()['prompt']);self.assertEqual(checker.status()['transport'],'system-https');native.assert_called_once()
 def test_native_transport_size_and_failure_do_not_fake_a_new_release(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);checker=UpdateChecker(SimpleNamespace(root=root),root,'1.9.4')
   with patch('updates.urllib.request.urlopen',side_effect=FileNotFoundError),patch('updates.native_fetch',return_value=b'x'*(256*1024+1)):checker._check('light23335/efootball-player-studio')
   self.assertEqual(checker.status()['phase'],'offline');self.assertFalse(checker.status()['prompt'])
 def test_reminder_can_be_dismissed_without_installing_and_auto_check_disabled(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);checker=UpdateChecker(SimpleNamespace(root=root),root,'1.9.4');checker.settings({'repository':'light23335/efootball-player-studio','enabled':False})
   checker.state=release_result(self.release(),'1.9.4','light23335/efootball-player-studio','pc');self.assertTrue(checker.status()['prompt']);self.assertFalse(checker.dismiss()['prompt'])
   with patch('updates.threading.Thread') as thread:checker.start();thread.assert_not_called()

if __name__=='__main__':unittest.main()
