"""Direct install must work without a scanned/installed resource companion."""
from pathlib import Path
from types import SimpleNamespace
import sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'player-studio-v15'),str(Path(__file__).resolve().parents[1]/'app/src/main/python')]
from android_backend import install_exported_apk


class OptionalInstallPairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=SimpleNamespace(root=Path(self.tmp.name));(self.store.root/'exports').mkdir()
        self.path=self.store.root/'exports/game.apk';self.path.write_bytes(b'generated-apk')
        self.calls=[]
        def scan():raise AssertionError('Direct install must not scan or require resource companions')
        self.games=SimpleNamespace(scan=scan,validateInstall=lambda path:self.calls.append(('identity',path)))
        self.files=SimpleNamespace(install=lambda path:self.calls.append(('install',path)) or 'installer')

    def test_game_without_an_installed_resource_opens_installer(self):
        self.assertEqual(install_exported_apk(self.store,'game.apk',self.files,self.games),{'opened':True,'action':'installer'})
        self.assertEqual(self.calls,[('identity',str(self.path)),('install',str(self.path))])

    def test_signature_version_precheck_failure_still_preserves_existing_app(self):
        def mismatch(path):raise ValueError('签名不同')
        self.games.validateInstall=mismatch
        with self.assertRaisesRegex(ValueError,'签名不同'):install_exported_apk(self.store,'game.apk',self.files,self.games)
        self.assertEqual(self.calls,[])

    def test_only_existing_exported_apks_can_be_installed(self):
        (self.store.root/'exports/note.txt').write_text('note')
        for name in ('note.txt','missing.apk','../game.apk'):
            with self.assertRaises(ValueError):install_exported_apk(self.store,name,self.files,self.games)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
