import copy,json,sqlite3,sys,unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SOURCE))
import app
from native_player import compile_player
from overall import auto_allocate_training,training_cost

class TrainingBudgetRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with sqlite3.connect(app.RESOURCE/'library.sqlite3')as db:
            cls.template=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
        cls.costs=json.loads((app.RESOURCE/'native-progression.json').read_text('utf8'))['costs']
    def project(self,level,cap):
        p=app.default_project();p['initial_level']=level;p['max_level']=cap
        return p
    def compile(self,p):
        identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
        result=compile_player(p,app.CATALOG,self.costs,identity,self.template,18,103,bytes.fromhex(self.template['_studio_client_record']))
        info=result['owned']['level_info'];spent=sum(result['allocation'].values())
        self.assertLessEqual(info['level'],info['level_limit'])
        self.assertGreaterEqual(info['customize_point'],0)
        self.assertLessEqual(spent,2*(info['level']-1)if p['card_type']!='Trending'else 0)
        return result
    def test_old_level_over_cap_is_repaired_to_maximum_level_allocation(self):
        p=self.project(60,25);original=copy.deepcopy(p)
        fixed=app.normalize_project(p)
        self.assertEqual(fixed['initial_level'],25)
        self.assertEqual(fixed['training'],auto_allocate_training(fixed,app.CATALOG))
        self.assertEqual(p,original)
        self.assertEqual(self.compile(p)['owned']['level_info']['level'],25)
    def test_points_over_current_budget_promote_to_max_without_export_error(self):
        p=self.project(2,35);p['training']['SHOOT']=12
        fixed=app.normalize_project(p)
        self.assertEqual(fixed['initial_level'],35)
        self.assertEqual(self.compile(p)['owned']['level_info']['level'],35)
    def test_allocation_over_even_max_budget_is_reallocated_within_cap(self):
        for cap in (1,10,35,100):
            p=self.project(cap,cap);p['training']={g['id']:40 for g in app.CATALOG['training_groups']}
            fixed=app.normalize_project(p)
            spent=sum(training_cost(fixed['training'][g['id']])for g in app.CATALOG['training_groups'])
            self.assertLessEqual(spent,2*(cap-1))
            self.assertEqual(self.compile(p)['owned']['level_info']['level'],cap)
    def test_valid_manual_training_and_unknown_project_fields_are_preserved(self):
        p=self.project(15,35);p['training']['SHOOT']=4;p['training']['future_group']=7
        fixed=app.normalize_project(p)
        self.assertEqual(fixed['initial_level'],15);self.assertEqual(fixed['training'],p['training'])
        self.compile(p)
    def test_nontraining_card_and_selected_training_position_repair(self):
        p=self.project(55,25);p['preview']['training_position']='GK'
        fixed=app.normalize_project(p)
        self.assertGreater(sum(fixed['training'][k]for k in('GK1','GK2','GK3')),0)
        p['card_type']='Trending';p['training']['SHOOT']=40
        fixed=app.normalize_project(p)
        self.assertFalse(any(fixed['training'].values()));self.compile(p)
