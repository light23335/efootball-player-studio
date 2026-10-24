from pathlib import Path
from types import SimpleNamespace
import copy,hashlib,json,struct,sys,tempfile,unittest,zipfile,zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apk_installation import coexist_entries,identity,patch_dex,plan,COEXIST_GAME,COEXIST_RESOURCES,remember_resource,resources_needed,local_certificate
from android_manifest import Manifest
from onboarding import Setup,preferences

class CoexistTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.root=Path(__file__).resolve().parents[2];cls.game=cls.root.parent/'73efootball安装包及资源/73efootball-V16(1).apk';cls.resources=cls.root/'球员工坊-V15/原始APK/73efootball-离线资源包-V9+.apk'
  if not cls.game.is_file() or not cls.resources.is_file():raise unittest.SkipTest('requires original APKs')
 def test_coexist_main_and_resources_have_independent_authorities_and_matching_routes(self):
  changed=[]
  for path,package in ((self.game,COEXIST_GAME),(self.resources,COEXIST_RESOURCES)):
   with zipfile.ZipFile(path) as z:
    original=z.read('AndroidManifest.xml');changes,report=coexist_entries(z,'coexist');after=Manifest(changes['AndroidManifest.xml']);info=after.info()
    self.assertEqual(info['package'],package);self.assertEqual(info['version_code'],Manifest(original).info()['version_code']);self.assertTrue(all(a.startswith(package+'.') for a in info['authorities']))
    self.assertNotEqual(original,changes['AndroidManifest.xml']);self.assertFalse(any(n.endswith('.so') or n.startswith('assets/') for n in changes))
    for name,raw in changes.items():
     if name.endswith('.dex'):
      self.assertEqual(len(raw),len(z.read(name)));self.assertEqual(raw[12:32],hashlib.sha1(raw[32:]).digest());self.assertEqual(struct.unpack_from('<I',raw,8)[0],zlib.adler32(raw[12:])&0xffffffff)
      self.assertIn(b'com.efootball.revival.diyassets',raw)
    self.assertGreater(report['rewritten_dex_strings'],0);changed.append(changes)
  self.assertIn(b'com.efootball.revival.diyer',changed[1]['classes.dex'])
 def test_update_preserves_all_apk_entries(self):
  with zipfile.ZipFile(self.game) as z:
   changes,report=coexist_entries(z,'update');self.assertEqual(changes,{});self.assertEqual(report['mode'],'update')
 def test_manifest_visibility_roundtrip_preserves_existing_typed_attributes(self):
  with zipfile.ZipFile(self.game) as z:raw=z.read('AndroidManifest.xml')
  original=Manifest(raw);before=original.info();original.add_queries([COEXIST_GAME,COEXIST_RESOURCES],True);after=Manifest(original.bytes());self.assertEqual(after.info(),before)
  packages=[a['value'] for _,name,attrs in after.nodes() if name=='package' for a in attrs if a['name']=='name'];self.assertIn(COEXIST_GAME,packages)
  actions=[a['value'] for _,name,attrs in after.nodes() if name=='action' for a in attrs];self.assertIn('android.intent.action.MAIN',actions)
 def test_signing_plan_does_not_claim_original_save_can_be_imported_or_arbitrary_signed(self):
  info=identity(self.game);r=plan(self.game,'coexist','0'*64);self.assertFalse(r['source_signer_matches']);self.assertFalse(r['existing_save_shared']);self.assertEqual(r['package'],COEXIST_GAME)
  r=plan(self.game,'update',info['signers'][0]);self.assertTrue(r['source_signer_matches']);self.assertIn('签名',r['message'])
  with self.assertRaises(ValueError):plan(self.game,'force-update')
 def test_installed_discovery_selects_supported_games_without_touching_data(self):
  with tempfile.TemporaryDirectory() as folder:
   store=SimpleNamespace(root=Path(folder));library=SimpleNamespace(summary=lambda:{'phase':'missing'})
   server=SimpleNamespace(store=store,home=Path(folder),library=library,installed_sources=lambda:{'rows':[{'path':str(self.game),'label':'已安装原版'},{'path':str(self.resources),'label':'资源'}]})
   setup=Setup(server);result=setup.status();self.assertEqual(setup.status(),result);self.assertEqual(len(result['rows']),2);self.assertTrue(result['installed_discovery']);self.assertEqual(result['recommended_mode'],'coexist');self.assertFalse(list(Path(folder).iterdir()))
   self.assertEqual(result['selected']['apk'],str(self.game));self.assertIn('私有存档',result['save_notice'])
 def test_preferences_preserve_other_configuration(self):
  with tempfile.TemporaryDirectory() as folder:
   store=SimpleNamespace(root=Path(folder));path=store.root/'workspace-preferences.json';path.write_text(json.dumps({'navigation':'simple','unknown':'keep'}))
   self.assertEqual(preferences(store,{'navigation':'full'})['unknown'],'keep');self.assertEqual(preferences(store)['navigation'],'full')
   with self.assertRaises(ValueError):preferences(store,{'navigation':'bad'})
 def test_resources_generated_once_and_invalidated_when_signer_changes(self):
  with tempfile.TemporaryDirectory() as folder:
   store=SimpleNamespace(root=Path(folder));(store.root/'signing').mkdir();certificate=store.root/'signing/personal-apk-signing-cert.der';certificate.write_bytes(b'first')
   self.assertTrue(resources_needed(store,[])['coexist']);remember_resource(store,'coexist',COEXIST_RESOURCES,local_certificate(store));self.assertFalse(resources_needed(store,[])['coexist']);self.assertTrue(resources_needed(store,[])['update'])
   certificate.write_bytes(b'second');self.assertTrue(resources_needed(store,[])['coexist'])

if __name__=='__main__':unittest.main()
