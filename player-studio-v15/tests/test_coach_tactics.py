from pathlib import Path
import copy,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from coaches import normalize_coach,CoachStore
from native_coaches import TACTICS,COACH,BOOSTER,compile_coaches
from native_cpk import wrap,unwrap
from coach_tactics import read_rows,repair_catalogue,REVISION

class SixCoachTacticsTests(unittest.TestCase):
 def coach(self,overload=92):
  return normalize_coach({'name':'压上进攻测试','name_en':'Overload test','tactics':{**dict.fromkeys(TACTICS,72),'overload':overload},'effects':{}},app.CATALOG['ABILITIES'])
 def test_save_and_project_roundtrip_keep_sixth_proficiency(self):
  with tempfile.TemporaryDirectory() as folder:
   store=app.Store(Path(folder));row=store.coaches.save(self.coach())['coach']
   self.assertEqual(store.coaches.list()['rows'][0]['tactics']['overload'],92)
   p=app.default_project();p['custom_coaches']=[row];p['preview']={'coach_id':row['id'],'team_style':'overload'}
   saved=app.normalize_project(p);self.assertEqual(saved['custom_coaches'][0]['tactics']['overload'],92)
   self.assertEqual(saved['preview']['team_style'],'overload')
 def test_legacy_coach_gets_zero_without_changing_five_existing_proficiencies(self):
  row=self.coach();del row['tactics']['overload'];old=copy.deepcopy(row['tactics']);saved=normalize_coach(row,app.CATALOG['ABILITIES'])
  self.assertEqual(saved['tactics']['overload'],0)
  self.assertEqual({k:v for k,v in saved['tactics'].items() if k!='overload'},old)
  for value in (-1,101,True):
   row['tactics']['overload']=value
   with self.assertRaises(ValueError):normalize_coach(row,app.CATALOG['ABILITIES'])
 def test_compile_native_record_and_owned_payload_agree_preserving_original(self):
  template=(8).to_bytes(8,'little')+bytes(168);header=bytes.fromhex('ff218357455359530000000000000000')
  source={COACH:wrap(template,header),BOOSTER:wrap(bytes(4),header)}
  class Archive:
   def read(self,key):return source[key]
  for proficiency in (0,70,100):
   row=self.coach(proficiency);changed,owned=compile_coaches(Archive(),[row],[{'id':'8','age':40,'raw_payload':{}}],{})
   raw=unwrap(changed[COACH]);self.assertEqual(raw[:176],template)
   native=read_rows(raw)[str(owned[0]['id'])]
   self.assertEqual(native,row['tactics']);self.assertEqual(owned[0]['payload']['overload'],proficiency)
 def test_same_release_fallback_repairs_old_database_without_rewriting_it(self):
  root=Path(__file__).resolve().parents[1]/'resources'
  original=json.loads((root/'coaches.json').read_text(encoding='utf8'));row=next(c for c in original['coaches'] if c['tactics']['overload']>0)
  with tempfile.TemporaryDirectory() as folder:
   resources=Path(folder);(resources/'native-resource-profile.json').write_bytes((root/'native-resource-profile.json').read_bytes())
   legacy=copy.deepcopy(row);del legacy['tactics']['overload'];legacy['raw_payload']['overload']=0;doc={'coaches':[legacy]};before=copy.deepcopy(doc)
   repaired=repair_catalogue(doc,resources,root)
   self.assertEqual(repaired['coaches'][0]['tactics']['overload'],row['tactics']['overload']);self.assertEqual(doc,before)
 def test_existing_game_coach_update_keeps_ownership_and_updates_overload(self):
  import sqlite3
  from personal_runtime import apply_coaches
  conn=sqlite3.connect(':memory:');conn.executescript('create table meta(key text primary key,value text);create table coaches(coach_id integer,serial integer,json text);')
  payload={'name':'Coach','name_en':'Coach','age':40,'ability_id':[0]*4,**dict.fromkeys(TACTICS,70),'_personal_coach_revision':'first','is_lock':'YES'}
  definition={'uuid':'test','id':600001,'payload':payload};first=apply_coaches(conn,[definition]);serial=first[0]['serial']
  incoming=copy.deepcopy(definition);incoming['payload']['overload']=99;incoming['payload']['_personal_coach_revision']='second'
  second=apply_coaches(conn,[incoming]);saved=json.loads(conn.execute('select json from coaches').fetchone()[0])
  self.assertEqual(second[0]['serial'],serial);self.assertEqual(saved['overload'],99);self.assertEqual(saved['is_lock'],'YES');conn.close()

if __name__=='__main__':unittest.main()
