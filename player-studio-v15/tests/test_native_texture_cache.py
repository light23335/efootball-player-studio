"""A valid skeletal cache must still refresh after a texture decoder repair."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_library import NativeLibrary
from native_skeletal import FACE_DECODER_REVISION
from native_texture import TEXTURE_DECODER_REVISION


class TextureCacheTests(unittest.TestCase):
    def test_old_textures_refresh_once_even_when_skeletal_revision_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir();old=root/'assets/old.glb';old.write_bytes(b'old')
            fresh=root/'fresh.glb';fresh.write_bytes(b'new');db=root/'index.sqlite3'
            with sqlite3.connect(db) as conn:
                conn.execute('create table assets(id text,path text,name text,kind text)')
                conn.execute("insert into assets values('face','SK_56329_Face.uasset','SK_56329_Face','model')")
            conn.close()
            library=object.__new__(NativeLibrary)
            library.state={'phase':'ready'};library.convert_lock=threading.Lock();library.converted=root
            library.cache_path=root/'cache.json'
            library.cache={'face':{'asset_id':'old.glb','decoder_revision':FACE_DECODER_REVISION}}
            def database():
                conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row;return conn
            def imported(path,kind):
                key=hashlib.sha256(Path(path).read_bytes()).hexdigest()+'.glb'
                (root/'assets'/key).write_bytes(Path(path).read_bytes())
                return {'id':key,'url':'/assets/'+key}
            library.db=database;library.store=SimpleNamespace(root=root,import_asset=imported)
            library.convert_face=Mock(return_value=(fresh,{'decoder_revision':FACE_DECODER_REVISION}))
            library.texture_model=Mock(return_value=(fresh,{'texture_decoder_revision':TEXTURE_DECODER_REVISION}))
            library.convert({'ids':['face']})
            self.assertEqual(library.convert_face.call_count,1)
            self.assertEqual(library.cache['face']['texture_decoder_revision'],TEXTURE_DECODER_REVISION)
            library.convert({'ids':['face']})
            self.assertEqual(library.convert_face.call_count,1)
            self.assertEqual(old.read_bytes(),b'old')


if __name__=='__main__':unittest.main()
