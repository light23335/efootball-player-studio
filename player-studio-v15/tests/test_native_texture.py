"""Regression cases for stale name-map formats and actual cooked mip storage."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_texture import cooked_mip


def texture(fmt='PF_ETC2_RGBA', data=bytes(16), external=None, wide=False):
    raw=bytearray(64)
    # A name-map string is deliberately different from the platform stream.
    raw.extend(b'PF_ETC2_RGB\0');raw.extend(bytes(80-len(raw)))
    struct.pack_into('<II',raw,52,80,0)
    name=fmt.encode()+b'\0'
    raw.extend(struct.pack('<4I',4,4,1,len(name))+name)
    flags=(0x100|0x800 if external else 0x40)|(0x2000 if wide else 0)
    raw.extend(struct.pack('<4I',0,1,1,flags))
    raw.extend(struct.pack('<QQq' if wide else '<IIq',len(data),len(data),0))
    if not external:raw.extend(data)
    raw.extend(struct.pack('<3I',4,4,1))
    return bytes(raw)


class CookedTextureTests(unittest.TestCase):
    def test_cooked_rgba_overrides_stale_rgb_name_map(self):
        mip=cooked_mip(texture())
        self.assertEqual((mip['format'],mip['width'],mip['height']),('PF_ETC2_RGBA',4,4))
        self.assertEqual(len(mip['data']),16)

    def test_optional_bulk_uses_uptnl_and_preserves_rgba(self):
        calls=[]
        mip=cooked_mip(texture(external=True,wide=True),lambda suffix:calls.append(suffix)or bytes(16))
        self.assertEqual(calls,['.uptnl'])
        self.assertEqual(mip['storage'],'.uptnl')
        self.assertEqual(mip['format'],'PF_ETC2_RGBA')

    def test_rgb_keeps_its_eight_byte_block_layout(self):
        self.assertEqual(cooked_mip(texture('PF_ETC2_RGB',bytes(8)))['format'],'PF_ETC2_RGB')

    def test_rgba_with_rgb_block_length_fails_instead_of_showing_corruption(self):
        with self.assertRaises(ValueError):cooked_mip(texture(data=bytes(8)))

    def test_truncated_inline_and_external_data_fail(self):
        with self.assertRaises(ValueError):cooked_mip(texture()[:-8])
        with self.assertRaises(ValueError):cooked_mip(texture(external=True),lambda suffix:bytes(8))


if __name__=='__main__':unittest.main()
