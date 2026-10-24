from pathlib import Path
import copy,json,sqlite3,struct,sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from native_tables import weekly_table
from personal_runtime import apply_weekly_condition

class PlayerOptionTests(unittest.TestCase):
    def test_per_player_settings_round_trip_and_reject_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=app.Store(Path(tmp));first=app.default_project();first['identity']['name']='Example';second=copy.deepcopy(first);second['package_id']=str(uuid.uuid4())
            first['model'].update(preserve_expression=False,binding_handles={'head':[1,-2,3],'neck_root':[0,1,0]});first['weekly_condition']='A'
            second['model']['preserve_expression']=True;second['weekly_condition']='D'
            store.save_player(first);store.save_player(second)
            a=store.saved_player(first['package_id'])['project'];b=store.saved_player(second['package_id'])['project']
            self.assertFalse(a['model']['preserve_expression']);self.assertTrue(b['model']['preserve_expression'])
            self.assertEqual(a['model']['binding_handles']['head'],[1,-2,3]);self.assertEqual(a['weekly_condition'],'A');self.assertEqual(b['weekly_condition'],'D')
            for invalid in (True,15,float('nan')):
                p=copy.deepcopy(first);p['model']['binding_handles']['head'][0]=invalid
                with self.assertRaises(ValueError):app.normalize_project(p)
            for value in ('F','a',3):
                p=copy.deepcopy(first);p['weekly_condition']=value
                with self.assertRaises(ValueError):app.normalize_project(p)
    def test_manual_grade_overrides_default_B_and_updates_runtime_without_progress_edits(self):
        source=struct.pack('<QII',8,1,3)
        identity={'package_id':str(uuid.uuid4()),'card_id':90000001,'person_id':90000001,'previous_card_ids':[90000001]};d={'identity':identity}
        for label,grade in [('A',4),('B',3),('C',2),('D',1),('E',0)]:
            raw,count=weekly_table(source,[{'card_type':'Standard','weekly_condition':label}],[d])
            self.assertEqual(count,1);self.assertEqual(raw[:16],source);self.assertEqual(struct.unpack('<QII',raw[16:])[2],grade)
        c=sqlite3.connect(':memory:');c.execute('create table meta(key text primary key,value text)');c.execute('insert into meta values("progress","keep")')
        apply_weekly_condition(c,{**d,'weekly_condition':'A'});self.assertEqual(c.execute('select value from meta where key="editor_live_condition:90000001"').fetchone()[0],'4')
        apply_weekly_condition(c,{**d,'weekly_condition':'D'});self.assertEqual(c.execute('select value from meta where key="editor_live_condition:90000001"').fetchone()[0],'1')
        apply_weekly_condition(c,{**d,'weekly_condition':'auto'});self.assertIsNone(c.execute('select value from meta where key="editor_live_condition:90000001"').fetchone())
        self.assertEqual(c.execute('select value from meta where key="progress"').fetchone()[0],'keep');c.close()

if __name__=='__main__':unittest.main()
