import json,sys,tempfile,threading,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import editor_drafts as d
class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SimpleNamespace(root=Path(self.temp.name),lock=threading.RLock())
    def test_invalid_partial_coach_survives_restart_without_overwriting_valid_record(self):
        calls=[]
        def save(value):calls.append(value);raise ValueError('请填写教练姓名')
        self.store.coaches=SimpleNamespace(save=save)
        value={'uuid':str(uuid.uuid4()),'name':'','tactics':{'possession':90}}
        result=d.update(self.store,'coach',value)
        self.assertTrue(result['saved']);self.assertFalse(result['committed'])
        rows=d.listing(SimpleNamespace(root=self.store.root,lock=threading.RLock()))
        self.assertEqual(next(iter(rows.values()))['value'],value)
    def test_drafts_are_independent_and_removal_does_not_touch_other_data(self):
        values=[{'uuid':str(uuid.uuid4()),'name':str(i)} for i in range(2)]
        for v in values:d.update(self.store,'pack',v,False)
        d.remove(self.store,'pack',values[0]['uuid'])
        self.assertEqual(len(d.listing(self.store)),1)
        self.assertEqual(next(iter(d.listing(self.store).values()))['value'],values[1])
    def test_unknown_draft_and_traversal_are_rejected(self):
        for category,value in [('wrong',{}),('pack',{'uuid':'../project'})]:
            with self.assertRaises(ValueError):d.update(self.store,category,value)
