import copy,json,tempfile,unittest
from pathlib import Path
import app
from base_abilities import normalize

class BaseAbilityBoundsTests(unittest.TestCase):
    def test_old_out_of_range_values_align_to_nearest_endpoint_not_default(self):
        for value,expected in [(-100,40),(0,40),(1,40),(39,40),(40,40),(65,65),(103,103),(104,103),(105,103),(999,103),('105',103),('0',40)]:
            self.assertEqual(normalize(value),expected,(value,expected))
        for value in (None,True,False,'',{},float('nan'),float('inf')):self.assertEqual(normalize(value),65)
    def test_all_26_old_abilities_are_repaired_without_changing_identity_training_or_assets(self):
        p=app.default_project();values=[0,105,39,104,40,103,65]
        for i,key in enumerate(app.CATALOG['ABILITIES']):p['base_abilities'][key]=values[i%len(values)]
        before=copy.deepcopy(p);result=app.normalize_project(p)
        self.assertEqual(p,before)
        for i,key in enumerate(app.CATALOG['ABILITIES']):self.assertEqual(result['base_abilities'][key],max(40,min(103,values[i%len(values)])))
        for field in ('package_id','identity','training','appearance','model','source_player'):
            self.assertEqual(result.get(field),before.get(field))
    def test_current_autosave_and_saved_player_open_use_the_same_limits(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);store=app.Store(root);p=copy.deepcopy(store.project);p['identity']['name']='Legacy QA'
            p['base_abilities'].update({'14':0,'20':105});store.project_path.write_text(json.dumps(p),'utf8')
            restored=app.Store(root)
            self.assertEqual(restored.project['package_id'],p['package_id'])
            self.assertEqual((restored.project['base_abilities']['14'],restored.project['base_abilities']['20']),(40,103))
            persisted=json.loads(restored.project_path.read_text('utf8'))
            self.assertEqual(persisted['base_abilities']['20'],103)
            restored.save_player(p);opened=restored.saved_player(p['package_id'])['project']
            self.assertEqual((opened['base_abilities']['14'],opened['base_abilities']['20']),(40,103))

if __name__=='__main__':unittest.main()
