from pathlib import Path
import struct,sys,tempfile,unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_appearance import compact_table,original_face_skin,patch


def face_package(with_skin=False):
    names=['None','IntProperty']+(['SkinColor'] if with_skin else [])
    header=[0]*16;header[6]=64;header[9]=(len(names)+1)*8
    batch=b''.join(len(n).to_bytes(2,'big')+n.encode() for n in names)
    prop=struct.pack('<6IBi',2,0,1,0,4,0,0,4) if with_skin else b'original mesh and materials'
    return struct.pack('<16I',*header)+batch+prop+b'KEEP-ORIGINAL-GEOMETRY'


class NativeSkinTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.resources=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        records={}
        for ident,tone in ((105029,4),(123,0)):
            row=bytearray(64);struct.pack_into('<Q',row,0,ident)
            records[ident]=patch(row,{'skin_tone':tone}) if tone else bytes(row)
        (self.resources/'native-appearance.bin').write_bytes(compact_table(records))

    def test_unedited_original_without_skin_property_is_byte_identical(self):
        raw=face_package()
        result,report=original_face_skin(raw,{'skin_tone':4,'appearance_source_id':'105029'},self.resources)
        self.assertEqual(result,raw)
        self.assertEqual(report,{'mode':'preserved-original','requested':4,'original':4})

    def test_default_tone_display_and_legacy_player_reference_keep_original(self):
        raw=face_package()
        result,_=original_face_skin(raw,{'skin_tone':1},self.resources,123)
        self.assertEqual(result,raw)
        result,_=original_face_skin(raw,{'skin_tone':4},self.resources,105029)
        self.assertEqual(result,raw)

    def test_changed_unsupported_tone_fails_with_original_tone(self):
        with self.assertRaisesRegex(ValueError,'原版档位 4'):
            original_face_skin(face_package(),{'skin_tone':3,'appearance_source_id':'105029'},self.resources)
        with self.assertRaisesRegex(ValueError,'无法确认原版肤色'):
            original_face_skin(face_package(),{'skin_tone':3},self.resources)

    def test_supported_edit_changes_only_skin_value(self):
        raw=face_package(True)
        result,report=original_face_skin(raw,{'skin_tone':6,'appearance_source_id':'105029'},self.resources)
        changed=[i for i,(a,b) in enumerate(zip(raw,result)) if a!=b]
        self.assertEqual(len(raw),len(result));self.assertEqual(len(changed),1)
        self.assertEqual((raw[changed[0]],result[changed[0]]),(4,6))
        self.assertEqual(report['mode'],'modified')
        for value in (True,0,7):
            with self.assertRaises(ValueError):
                original_face_skin(raw,{'skin_tone':value},self.resources)


if __name__=='__main__':unittest.main()
