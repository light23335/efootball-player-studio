import struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app/src/main/python'),str(Path(__file__).resolve().parents[2]/'player-studio-v15')]
import portable_decode
from portable_assets import PortableAssets

class OptionalBulkTests(unittest.TestCase):
    def test_high_resolution_optional_payload_does_not_read_the_low_mip_file(self):
        fmt=b'PF_ETC2_RGB\0';raw=bytearray(64)
        raw.extend(struct.pack('<4I',512,512,1,len(fmt))+fmt)
        raw.extend(struct.pack('<6Iq',0,1,1,0x10d01,131072,131072,0))
        raw.extend(struct.pack('<3I',512,512,1));calls=[]
        class Assets:
            def raw(self,path):
                calls.append(path)
                if path.endswith('.uasset'):return bytes(raw)
                if path.endswith('.uptnl'):return b'x'*163840
                raise AssertionError('Wrong bulk file '+path)
        with patch.object(portable_decode,'package_names',return_value=['PF_ETC2_RGB']),patch.object(portable_decode,'block_image',side_effect=lambda data,w,h,fmt:(len(data),w,h)):
            self.assertEqual(portable_decode.texture_image(Assets(),'/Game/T_7511_Face_D.uasset'),(131072,512,512))
        self.assertEqual(calls[-1],'/Game/T_7511_Face_D.uptnl')
        self.assertTrue(PortableAssets.normalize(calls[-1]).endswith('.uptnl'))

if __name__=='__main__':unittest.main()
