from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio_resources import bundled_resources


class DeployedResourcesTests(unittest.TestCase):
    def virtual_module(self,name):
        scope={'__file__':'/data/data/com.playerstudio.editor/files/chaquopy/AssetFinder/app/'+name+'.py','__name__':'test_virtual_'+name}
        exec(compile((ROOT/(name+'.py')).read_bytes(),scope['__file__'],'exec'),scope)
        return scope

    def test_chaquopy_virtual_sources_load_actual_bundled_resources(self):
        with patch.object(sys,'_MEIPASS',str(ROOT),create=True):
            self.assertEqual(bundled_resources(),ROOT/'resources')
            skill=self.virtual_module('native_skill_effects')
            self.assertEqual(skill['RESOURCE'],ROOT/'resources')
            bits=skill['skill_bits'](ROOT/'resources')
            self.assertTrue(all(str(k) in bits for k in (14,25,43,51,52,63,68,70)))
            self.assertTrue(skill['text_groups']())
            self.assertTrue(self.virtual_module('native_coach_links')['schema']()['effect_by_template'])
            self.assertEqual(self.virtual_module('card_motion')['ROOT'],ROOT/'resources')

    def test_imported_database_can_merge_verified_skill_bits_on_android(self):
        with patch.object(sys,'_MEIPASS',str(ROOT),create=True),tempfile.TemporaryDirectory() as folder:
            data=json.loads((ROOT/'resources/native-skill-bits.json').read_text())
            for k in ('25','43','51','52','68'):data.pop(k,None)
            data['1']={'preserved_imported_mapping':True}
            Path(folder,'native-skill-bits.json').write_text(json.dumps(data))
            merged=self.virtual_module('native_skill_effects')['skill_bits'](folder)
            self.assertEqual(merged['1'],data['1'])
            self.assertTrue(all(k in merged for k in ('25','43','51','52','68')))

    def test_source_checkout_fallback_without_bundle_override(self):
        with patch.dict(sys.__dict__,{},clear=False):
            old=sys.__dict__.pop('_MEIPASS',None)
            try:self.assertEqual(bundled_resources(),ROOT/'resources')
            finally:
                if old is not None:sys._MEIPASS=old


if __name__=='__main__':unittest.main()
