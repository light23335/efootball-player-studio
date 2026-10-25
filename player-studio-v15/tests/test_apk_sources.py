from pathlib import Path
from types import SimpleNamespace
import json,sys,tempfile,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apk_sources import resolve,MARKERS
from onboarding import Setup


class SourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.store=SimpleNamespace(root=self.root/'data');self.store.root.mkdir()
        self.library=SimpleNamespace(home=self.root,root=self.root/'library',resources=self.root/'resources',
                                     profile={'release_id':'current','game_version':'V17'},summary=lambda:{'phase':'ready'})
        self.library.root.mkdir();self.library.resources.mkdir()
    def apk(self,name,key):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(path,'w') as z:z.writestr(MARKERS[key],b'{}')
        return str(path)
    def save(self,path,value):path.write_text(json.dumps(value),encoding='utf8')

    def test_current_imported_paths_beat_installed_base_apks(self):
        selected={'apk':self.apk('picked/我的主程序.apk','apk'),'companion':self.apk('picked/离线包任意名字.apk','companion')}
        installed=[self.apk('installed/game/base.apk','apk'),self.apk('installed/resource/base.apk','companion')]
        self.save(self.store.root/'active-game.json',{'database':'a'*24,**selected})
        def inspect(path):
            if not Path(path).is_file():return None
            return {'path':path,'name':Path(path).name,'kind':'game' if path in (selected['apk'],installed[0]) else 'resource',
                    'package':'test.game' if path in (selected['apk'],installed[0]) else 'test.resource','signers':[]}
        server=SimpleNamespace(store=self.store,home=self.root,library=self.library,
                               installed_sources=lambda:{'rows':[{'path':p} for p in installed],'errors':[]})
        with patch('onboarding.inspect_source',side_effect=inspect):
            result=Setup(server).status()
        self.assertEqual(result['selected'],selected)
        self.assertEqual(len([r for r in result['rows'] if r.get('installed')]),2)
        self.assertEqual(len([r for r in result['rows'] if r.get('imported')]),2)
        self.assertEqual(resolve(self.library,self.store)['errors'],[])

    def test_ready_library_records_restore_inputs_without_database_reimport(self):
        selected={'apk':self.apk('arbitrary-main.apk','apk'),'companion':self.apk('arbitrary-resource.apk','companion')}
        self.save(self.library.root/'ready.json',{'release_id':'current',**selected})
        result=resolve(self.library,self.store)
        self.assertTrue(result['recorded']);self.assertEqual(result['companion'],selected['companion'])
        self.assertEqual(result,resolve(self.library,self.store))

    def test_missing_imported_file_does_not_fall_back_to_an_installed_or_nearby_apk(self):
        missing=str(self.root/'moved-resource.apk');main=self.apk('main.apk','apk')
        self.apk('73efootball-离线资源包-V9+.apk','companion')
        self.save(self.store.root/'active-game.json',{'apk':main,'companion':missing})
        result=resolve(self.library,self.store)
        self.assertEqual(result['companion'],missing);self.assertIn('授权失效',result['errors'][0])

    def test_wrong_apk_kind_is_detected_and_database_change_has_a_new_source_key(self):
        game=self.apk('game.apk','apk');resource=self.apk('resource.apk','companion')
        self.save(self.store.root/'active-game.json',{'database':'a'*24,'apk':game,'companion':game})
        old=resolve(self.library,self.store);self.assertIn('内容与导入记录不符',old['errors'][0])
        self.save(self.store.root/'active-game.json',{'database':'b'*24,'apk':game,'companion':resource})
        new=resolve(self.library,self.store);self.assertNotEqual(new['source_key'],old['source_key']);self.assertFalse(new['errors'])


if __name__=='__main__':unittest.main()
