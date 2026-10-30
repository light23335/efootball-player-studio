import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_symbols import resolve_club,merged_symbols,converted_symbol,informative_symbol
class SymbolTests(unittest.TestCase):
    def test_plain_colour_placeholder_is_not_a_crest(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'badge.png';im=Image.new('RGBA',(8,8),'red');im.save(path)
            self.assertFalse(informative_symbol(path));im.putpixel((4,4),(255,255,255,255));im.save(path)
            self.assertTrue(informative_symbol(path))
    def test_manchester_colour_variant_is_recognised(self):
        symbols={'e_000100_r_w_l':'white','e_000100_r_b_l':'black','e_000100_r_e_l':'colour'}
        self.assertEqual(resolve_club(symbols,100),'colour')
    def test_patch_mount_overrides_unlicensed_original(self):
        old={'e_000132_r_l':'PesMobile/old'}
        patched=merged_symbols(old,['../../../IDSPUCL27/Content/Assets/ui/Data/Symbol/Emblem/e_000132_r_l.uasset'])
        self.assertTrue(resolve_club(patched,132).startswith('IDSPUCL27/'))
        self.assertIsNone(resolve_club({'e_000200_f_l':'fake'},200))
        self.assertEqual(resolve_club({'e_000200_f_l':'IDSPUCL27/patched.uasset'},200),'IDSPUCL27/patched.uasset')
    def test_pc_mounted_badge_is_materialized_under_selected_patch_path(self):
        with tempfile.TemporaryDirectory() as root:
            ref='IDSPUCL27/Content/Assets/ui/Data/Symbol/Emblem/e_000132_r_l.uasset'
            actual=Path(root)/ref.replace('IDSPUCL27','PesMobile').replace('.uasset','.png')
            actual.parent.mkdir(parents=True);actual.write_bytes(b'licensed colour badge')
            chosen=converted_symbol(root,ref)
            self.assertEqual(chosen.read_bytes(),actual.read_bytes())
            chosen.write_bytes(b'android decoder direct output')
            self.assertEqual(converted_symbol(root,ref).read_bytes(),b'android decoder direct output')
