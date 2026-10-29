from pathlib import Path
from types import SimpleNamespace
import copy,json,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from workspace_tools import game_options,clear_exports,export_file
from project_sharing import export_selected
from personal_runtime import apply_game_options

class WorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.store=app.Store(self.root/'data')
 def test_export_cleanup_is_limited_to_generated_files_and_refuses_traversal(self):
  (self.store.root/'exports/test.apk').write_bytes(b'generated');(self.store.root/'keep.json').write_text('project')
  server=SimpleNamespace(store=self.store,native_package=SimpleNamespace(status=lambda:{'phase':'idle'}),game_import=SimpleNamespace(status=lambda:{'phase':'idle'}))
  self.assertEqual(clear_exports(server)['deleted'],1);self.assertTrue((self.store.root/'keep.json').exists())
  with self.assertRaises(ValueError):export_file(self.store,'../keep.json')
 def test_multi_player_package_import_preserves_existing_slots_and_data(self):
  p=app.default_project();p['identity']['name']='First';p['identity']['shirt_name']='SHIRT';p['display_name']='Card';p['celebration']=123
  q=app.default_project();q['identity']['name']='Second';self.store.save_player(p);self.store.save_player(q)
  result=export_selected(self.store,[p['package_id'],q['package_id']],p)
  other=app.Store(self.root/'other');conflict=copy.deepcopy(p);conflict['identity']['name']='Existing';other.save_player(conflict);before=other._player_path(p['package_id']).read_bytes()
  imported=other.import_project(result['path']);self.assertNotEqual(imported['package_id'],p['package_id']);self.assertEqual(imported['identity']['shirt_name'],'SHIRT');self.assertEqual(imported['display_name'],'Card');self.assertEqual(imported['celebration'],123)
  self.assertEqual(other._player_path(p['package_id']).read_bytes(),before);self.assertEqual(len(other.list_players()['rows']),3)
 def test_division_changes_apply_once_and_do_not_overwrite_later_progress(self):
  settings=game_options(self.store,{'enabled':True,'division':2,'points':1900})
  c=sqlite3.connect(':memory:');c.execute('create table meta(key text primary key,value text)')
  state={'division':10,'best':10,'points':0,'matches':0,'wins':0,'draws':0,'losses':0,'round':1,'rule_version':3}
  native=SimpleNamespace(state=lambda conn:copy.deepcopy(state),save=lambda conn,s:state.update(s))
  with patch.dict(sys.modules,{'ai_division':native}):
   apply_game_options(c,settings);self.assertEqual(state['points'],1900);state['points']=1950;apply_game_options(c,settings);self.assertEqual(state['points'],1950)
  with self.assertRaises(ValueError):game_options(self.store,{'division':5,'points':6,'wins':1,'matches':1})
 def test_shirt_name_and_celebration_validation(self):
  p=app.default_project();p['identity']['name']='Card Name';p['identity']['shirt_name']='SHIRT';p['celebration']=511
  normalized=app.normalize_project(p);self.assertEqual(normalized['identity']['shirt_name'],'SHIRT');self.assertEqual(normalized['celebration'],511)
  for n in (-1,512,65535,True):
   p['celebration']=n
   with self.assertRaises(ValueError):app.normalize_project(p)
 def test_style_rotation_change_does_not_reset_saved_division_progress(self):
  first=game_options(self.store,{'enabled':True,'division':2,'points':1900})
  second=game_options(self.store,{**first,'style_mode':'independent'})
  self.assertEqual(first['revision'],second['revision'])
  with self.assertRaises(ValueError):game_options(self.store,{**second,'style_mode':'unknown'})

if __name__=='__main__':unittest.main()
