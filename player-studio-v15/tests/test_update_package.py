from pathlib import Path
import tempfile
import unittest
import zipfile
import hashlib
import io
import json
import os
from unittest.mock import patch

from update_package import stage_package, install_staged, download_package, recover_update, cleanup_completed_updates


class UpdatePackageTests(unittest.TestCase):
    def test_cleanup_keeps_latest_backup_and_unowned_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tmp=root/'tmp';tmp.mkdir()
            def completed(name, ver, stamp):
                work=tmp/name;work.mkdir();(work/'backup').mkdir()
                (work/'backup/球员工坊.exe').write_bytes(ver.encode())
                (work/'package.zip').write_bytes(b'zip')
                for marker in ('studio-update-owned.json','studio-update-installed.json'):
                    (work/marker).write_text(json.dumps({'version':ver}),encoding='utf8')
                os.utime(work/'studio-update-installed.json',ns=(stamp,stamp))
                return work
            old=completed('studio-update-old','v2.0.0',1_000_000_000)
            new=completed('studio-update-new','v2.1.0',2_000_000_000)
            legacy=tmp/'studio-update-abcdefgh';legacy.mkdir();(legacy/'backup').mkdir();(legacy/'stage').mkdir()
            (legacy/'backup/球员工坊.exe').write_bytes(b'old');(legacy/'package.zip').write_bytes(b'zip');(legacy/'updater.exe').write_bytes(b'helper')
            os.utime(legacy,ns=(1_000_000_000,1_000_000_000))
            other=tmp/'studio-update-unowned';other.mkdir();(other/'private').write_text('keep')
            self.assertFalse(cleanup_completed_updates(root,'2.0.9')['confirmed'])
            self.assertTrue(old.exists())
            self.assertTrue(cleanup_completed_updates(root,'2.1.0')['confirmed'])
            self.assertFalse(old.exists())
            self.assertFalse(legacy.exists())
            self.assertEqual((new/'backup/球员工坊.exe').read_bytes(),b'v2.1.0')
            self.assertFalse((new/'package.zip').exists())
            self.assertTrue((other/'private').exists())

    def test_interrupted_update_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); home = root / 'home'; stage = root / 'stage'
            home.mkdir(); stage.mkdir()
            (home / '球员工坊.exe').write_bytes(b'old')
            (stage / '球员工坊.exe').write_bytes(b'new')
            original = Path.replace
            def interrupted(path, target):
                result = original(path, target)
                if path == stage / '球员工坊.exe':
                    raise KeyboardInterrupt()
                return result
            with patch.object(Path, 'replace', interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    install_staged(stage, home, root / 'backup')
            journal = home / '.studio-update-recovery.json'
            self.assertTrue(journal.is_file())
            recover_update(home, journal)
            self.assertEqual((home / '球员工坊.exe').read_bytes(), b'old')
            self.assertFalse(journal.exists())

    def test_download_verifies_digest_before_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'update.zip'
            digest = hashlib.sha256(b'package').hexdigest()
            with patch('update_package.urllib.request.urlopen', return_value=io.BytesIO(b'package')):
                self.assertEqual(download_package('https://example.test/file', dest, digest), 7)
            self.assertEqual(dest.read_bytes(), b'package')
            dest.unlink()
            with patch('update_package.urllib.request.urlopen', return_value=io.BytesIO(b'corrupt')):
                with self.assertRaises(ValueError):
                    download_package('https://example.test/file', dest, digest)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name('update.zip.partial').exists())

    def test_failed_replacement_restores_old_program(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home, stage = root / 'home', root / 'stage'
            home.mkdir()
            stage.mkdir()
            (home / '球员工坊.exe').write_bytes(b'old')
            (stage / '球员工坊.exe').write_bytes(b'new')
            original_replace = Path.replace

            def fail_new_program(path, target):
                if path == stage / '球员工坊.exe':
                    raise OSError('simulated replacement failure')
                return original_replace(path, target)

            with patch.object(Path, 'replace', fail_new_program):
                with self.assertRaises(OSError):
                    install_staged(stage, home, root / 'backup')
            self.assertEqual((home / '球员工坊.exe').read_bytes(), b'old')

    def test_install_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home, stage = root / 'home', root / 'stage'
            for directory in (home / 'data', home / 'library', stage / 'tools'):
                directory.mkdir(parents=True)
            (home / '球员工坊.exe').write_bytes(b'old')
            (home / 'data/project').write_bytes(b'project')
            (home / 'library/cache').write_bytes(b'cache')
            (stage / '球员工坊.exe').write_bytes(b'new')
            (stage / 'tools/tool').write_bytes(b'tool')
            install_staged(stage, home, root / 'backup')
            self.assertEqual((home / '球员工坊.exe').read_bytes(), b'new')
            self.assertEqual((home / 'data/project').read_bytes(), b'project')
            self.assertEqual((home / 'library/cache').read_bytes(), b'cache')
            self.assertEqual((root / 'backup/球员工坊.exe').read_bytes(), b'old')

    def test_only_program_files_are_staged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'release.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('release/球员工坊.exe', b'new program')
                package.writestr('release/tools/tool.exe', b'new tool')
                package.writestr('release/data/project.json', b'user data')
                package.writestr('release/library/cache', b'user library')
            self.assertEqual(stage_package(archive, root / 'stage'), 2)
            self.assertEqual((root / 'stage/球员工坊.exe').read_bytes(), b'new program')
            self.assertFalse((root / 'stage/data').exists())
            self.assertFalse((root / 'stage/library').exists())

    def test_rejects_unsafe_and_duplicate_paths(self):
        for name in ('release/../outside', 'release/C:/outside'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with zipfile.ZipFile(root / 'bad.zip', 'w') as package:
                    package.writestr('release/球员工坊.exe', b'exe')
                    package.writestr(name, b'bad')
                with self.assertRaises(ValueError):
                    stage_package(root / 'bad.zip', root / 'stage')
                self.assertFalse((root / 'stage').exists())

    def test_rejects_multiple_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with zipfile.ZipFile(root / 'bad.zip', 'w') as package:
                package.writestr('one/球员工坊.exe', b'exe')
                package.writestr('two/tools/tool.exe', b'tool')
            with self.assertRaises(ValueError):
                stage_package(root / 'bad.zip', root / 'stage')


if __name__ == '__main__':
    unittest.main()
