import copy,json,sys,tempfile,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,packs

class PlayerDeleteTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=app.Store(Path(self.tmp.name));self.p=app.default_project()
  self.p['identity']['name']='待删除';self.store.save_player(self.p);self.store.save(self.p)
  self.other=copy.deepcopy(self.p);self.other['package_id']=str(uuid.uuid4());self.other['identity']['name']='保留'
  self.store.save_player(self.other)
 def test_confirmation_required_and_invalid_identity_cannot_delete(self):
  before=self.store.project_path.read_bytes()
  for confirm in (False,'true',1,None):
   with self.assertRaises(ValueError):self.store.delete_player(self.p['package_id'],confirm)
  with self.assertRaises(ValueError):self.store.delete_player('../current-project',True)
  self.assertEqual(self.store.project_path.read_bytes(),before);self.assertEqual(self.store.list_players()['total'],2)
 def test_current_delete_resets_slot_removes_only_matching_pack_member_and_keeps_assets(self):
  asset=self.store.root/'assets/untouched.png';asset.write_bytes(b'asset retained')
  row={'name':'测试卡包','members':[{'kind':'custom','id':self.p['package_id'],'weight':1},{'kind':'custom','id':self.other['package_id'],'weight':1},{'kind':'original','id':'7511','weight':1}]}
  packs.save(self.store,row);result=self.store.delete_player(self.p['package_id'],True)
  self.assertTrue(result['current_cleared']);self.assertEqual(result['removed_pack_members'],1)
  self.assertNotEqual(self.store.project['package_id'],self.p['package_id']);self.assertFalse(self.store.project['identity']['name'])
  self.assertEqual([r['id'] for r in packs.load(self.store)[0]['members']],[self.other['package_id'],'7511'])
  self.assertEqual(asset.read_bytes(),b'asset retained');self.assertTrue(Path(result['backup']).is_file())
  self.store.new_player_slot();self.assertFalse(self.store._player_path(self.p['package_id']).exists())
 def test_other_delete_keeps_current_player(self):
  result=self.store.delete_player(self.other['package_id'],True)
  self.assertFalse(result['current_cleared']);self.assertEqual(self.store.project['package_id'],self.p['package_id'])
  self.assertEqual(self.store.list_players()['total'],1)

if __name__=='__main__':unittest.main()
