from pathlib import Path
import hashlib,json,sys,tempfile,types,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apk_database import GameImport,active_resources

class ApkDatabaseTests(unittest.TestCase):
    def test_unknown_engine_cannot_change_active_database_or_personal_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'base';base.mkdir();(base/'game-adapters.json').write_text('{"engines":{}}')
            data=root/'data';data.mkdir();pointer=data/'active-game.json';pointer.write_bytes(b'{"database":"'+b'a'*24+b'"}');personal=data/'current-project.json';personal.write_bytes(b'personal current project')
            apk=root/'new.apk'
            with zipfile.ZipFile(apk,'w') as z:z.writestr('assets/gateway-release/release-manifest.json','{"release_id":"new"}');z.writestr('lib/arm64-v8a/libUE4.so',b'unknown engine')
            server=types.SimpleNamespace(store=types.SimpleNamespace(root=data),library=types.SimpleNamespace(resources=base))
            job=GameImport(server,base);job._work(apk,root/'resource.apk')
            self.assertEqual(job.status()['phase'],'error');self.assertIn('引擎',job.status()['message']);self.assertEqual(pointer.read_bytes(),b'{"database":"'+b'a'*24+b'"}');self.assertEqual(personal.read_bytes(),b'personal current project');self.assertFalse((data/'game-databases').exists())
    def test_active_pointer_cannot_escape_the_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.assertEqual(active_resources(root/'base',root),root/'base')
            (root/'active-game.json').write_text('{"database":"../../external"}')
            with self.assertRaises(ValueError):active_resources(root/'base',root)

if __name__=='__main__':unittest.main()
