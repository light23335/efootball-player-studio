import hashlib,struct,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app/src/main/python'),str(Path(__file__).resolve().parents[2]/'player-studio-v15')]
from portable_assets import Pak,PortableAssets
from private_card_motion import write_movie_pak
from native_iostore import fstring


def original_pak(path):
    payload=b'original video data';body=bytes(53)+payload
    directory=struct.pack('<I',1)+fstring('Movies/PlayerCard/')+struct.pack('<I',1)+fstring('original_v.usm')+struct.pack('<i',0)
    entry=struct.pack('<III',(1<<31)|(1<<30),0,len(payload))
    index=fstring('../../../PesMobile/Content/')+struct.pack('<IQI',1,0,1)+bytes(36)
    index+=struct.pack('<IQQ',1,len(body),len(directory))+hashlib.sha1(directory).digest()
    index+=struct.pack('<I',len(entry))+entry+struct.pack('<I',0)
    footer=bytes(17)+struct.pack('<IIQQ',0x5a6f12e1,11,len(body)+len(directory),len(index))+hashlib.sha1(index).digest()+bytes(160)
    path.write_bytes(body+directory+index+footer)
    return payload


class WorkshopMoviePakTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.private='PlayerCard/c123456789ab_v.usm';self.native='PlayerCard/0500_317_f02_v.usm'
        self.movies={self.private:b'CRID private video',self.native:b'CRID native video'}
        self.path=self.root/'cardstudio_100_P_10_P.pak';write_movie_pak(self.path,self.movies)
    def test_v3_private_and_native_movies_are_read_with_original_payload_bytes(self):
        pak=Pak(self.path,bytes(32));self.assertEqual(pak.version,3)
        for name,value in self.movies.items():self.assertEqual(pak.read(pak.mount+name),value)
    def test_mixed_original_v11_and_workshop_v3_paks_are_indexed_together(self):
        expected=original_pak(self.root/'original.pak');(self.root/'resource-key.bin').write_bytes(bytes(32))
        assets=PortableAssets.__new__(PortableAssets);assets.folder=self.root;assets.paks=None;assets.files={}
        self.assertEqual(len(assets.raw_paths()),3)
        self.assertEqual(assets.raw('PesMobile/Content/Movies/PlayerCard/original_v.usm'),expected)
        self.assertEqual(assets.raw('PesMobile/Content/Movies/'+self.private),self.movies[self.private])
    def test_damaged_index_payload_and_entry_header_are_rejected(self):
        original=self.path.read_bytes();raw=bytearray(original);raw[-1]^=1;self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'索引校验'):Pak(self.path,bytes(32))
        raw=bytearray(original);raw[53]^=1;self.path.write_bytes(raw);pak=Pak(self.path,bytes(32))
        with self.assertRaisesRegex(ValueError,'视频校验'):pak.read(pak.mount+self.native)
        raw=bytearray(original);raw[20]^=1;self.path.write_bytes(raw);pak=Pak(self.path,bytes(32))
        with self.assertRaisesRegex(ValueError,'条目头'):pak.read(pak.mount+self.native)
    def test_failure_does_not_cache_a_partial_pak_index(self):
        (self.root/'resource-key.bin').write_bytes(bytes(32));bad=self.root/'zz_bad.pak';bad.write_bytes(b'invalid')
        assets=PortableAssets.__new__(PortableAssets);assets.folder=self.root;assets.paks=None
        with self.assertRaises(ValueError):assets.raw_paths()
        self.assertIsNone(assets.paks);bad.unlink();self.assertEqual(len(assets.raw_paths()),2)
    def test_unsupported_v3_paths_are_rejected_even_with_a_valid_index_hash(self):
        self.path.unlink();write_movie_pak(self.path,{'../outside.usm':b'CRID no traversal'})
        with self.assertRaisesRegex(ValueError,'文件名'):Pak(self.path,bytes(32))

if __name__=='__main__':unittest.main()
