from pathlib import Path
import copy,json,sys,tempfile,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,coach_deletion


class CoachDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=app.Store(Path(self.temp.name))
        self.coach=self.store.coaches.save({'name':'Delete me','effects':{'20':2}})['coach']
        self.other=self.store.coaches.save({'name':'Keep me','effects':{}})['coach']
        self.project=app.default_project();self.project['identity']['name']='Player one';self.project['display_name']='Player one'
        self.project['custom_coaches']=[self.coach,self.other];self.project['preview']['coach_id']=self.coach['id']
        self.store.save(self.project);self.store.save_player(self.project)
        self.second=copy.deepcopy(self.project);self.second['package_id']=str(uuid.uuid4());self.second['preview']['coach_id']=self.other['id']
        self.store.save_player(self.second)

    def test_local_and_all_embedded_copies_are_removed_and_backed_up(self):
        result=coach_deletion.delete_coach(self.store,self.coach['uuid'],True)
        self.assertEqual(result['affected_projects'],2)
        self.assertEqual([c['id'] for c in self.store.coaches.list()['rows']],[self.other['id']])
        self.assertIsNone(self.store.project['preview']['coach_id'])
        for p in (self.project,self.second):
            saved=self.store.saved_player(p['package_id'])['project']
            self.assertEqual([c['id'] for c in saved['custom_coaches']],[self.other['id']])
        self.assertEqual(self.store.saved_player(self.second['package_id'])['project']['preview']['coach_id'],self.other['id'])
        backup=Path(result['backup']);self.assertTrue((backup/'coaches'/(self.coach['uuid']+'.json')).is_file())
        self.assertEqual(json.loads((backup/'current-project.json').read_text(encoding='utf8'))['preview']['coach_id'],self.coach['id'])
        reloaded=app.Store(self.store.root)
        self.assertNotIn(self.coach['id'],[c['id'] for c in reloaded.project['custom_coaches']])

    def test_imported_only_coach_can_be_removed_without_local_catalogue_file(self):
        (self.store.coaches.root/(self.coach['uuid']+'.json')).unlink()
        result=coach_deletion.delete_coach(self.store,self.coach['uuid'],True)
        self.assertTrue(result['deleted']);self.assertEqual(result['affected_projects'],2)

    def test_confirmation_and_native_coach_protection(self):
        with self.assertRaises(ValueError):coach_deletion.delete_coach(self.store,self.coach['uuid'])
        for value in ('437','../coaches',None):
            with self.assertRaises(ValueError):coach_deletion.delete_coach(self.store,value,True)
        self.assertTrue((self.store.coaches.root/(self.coach['uuid']+'.json')).exists())

    def test_failed_project_update_restores_all_live_files(self):
        files=[self.store.project_path,*self.store.coaches.root.glob('*.json'),*(self.store.root/'players').glob('*.json')]
        before={p:p.read_bytes() for p in files};original=coach_deletion.atomic;calls=[]
        def fail_second(path,data):
            calls.append(path)
            if len(calls)==2:raise OSError('simulated write failure')
            return original(path,data)
        with patch.object(coach_deletion,'atomic',side_effect=fail_second):
            with self.assertRaises(OSError):coach_deletion.delete_coach(self.store,self.coach['uuid'],True)
        self.assertEqual({p:p.read_bytes() for p in files},before)
        self.assertEqual(self.store.project['preview']['coach_id'],self.coach['id'])


if __name__=='__main__':unittest.main()
