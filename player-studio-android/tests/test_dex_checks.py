from pathlib import Path
import hashlib,struct,sys,unittest,zlib,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dex_checks import inspect_dex,inspect_runtime

def fixture(strings):
    raw=bytearray(112+len(strings)*4);raw[:8]=b'dex\n038\0'
    struct.pack_into('<II',raw,56,len(strings),112)
    for i,s in enumerate(strings):
        encoded=s.encode('utf8');struct.pack_into('<I',raw,112+i*4,len(raw));raw.extend(bytes([len(s)])+encoded+b'\0')
    struct.pack_into('<III',raw,32,len(raw),112,0x12345678)
    raw[12:32]=hashlib.sha1(raw[32:]).digest();struct.pack_into('<I',raw,8,zlib.adler32(raw[12:])&0xffffffff)
    return bytes(raw)

class DexChecks(unittest.TestCase):
 def test_class_name_byte_replacement_is_rejected_even_with_correct_checksums(self):
    with self.assertRaisesRegex(ValueError,'string_ids out of order'):inspect_dex(fixture(['ExportProvider','BaseActivity']))
 def test_sorted_strings_and_checksum_validation(self):
    raw=fixture(['BaseActivity','ExportProvider']);self.assertEqual(inspect_dex(raw)['strings'],2)
    changed=bytearray(raw);changed[-2]^=1
    with self.assertRaisesRegex(ValueError,'checksum'):inspect_dex(changed)
 def test_empty_dex_cannot_pass_editor_component_check(self):
    with self.assertRaisesRegex(ValueError,'Missing compiled Android components'):inspect_runtime({'classes.dex':fixture([])})
 def test_rebuilt_release_contains_valid_runtime(self):
    apk=Path(__file__).resolve().parents[2]/'.work/release198/android-fixed.apk'
    if not apk.is_file():self.skipTest('local rebuilt release unavailable')
    with zipfile.ZipFile(apk) as z:
        report=inspect_runtime({n:z.read(n) for n in z.namelist() if n.startswith('classes') and n.endswith('.dex')})
    self.assertTrue(report['required_components_present']);self.assertTrue(report['ordered_string_tables'])

if __name__=='__main__':unittest.main()
