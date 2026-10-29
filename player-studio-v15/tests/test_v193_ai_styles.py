from pathlib import Path
import copy,json,sqlite3,sys,tempfile,types,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from ai_playing_styles import FIELDS,from_record,project_value,restore_payload
from native_player import compile_player
from native_tables import player_record


class AIStyleTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with sqlite3.connect(app.RESOURCE/'library.sqlite3') as db:cls.source=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
  cls.costs=json.loads((app.RESOURCE/'native-progression.json').read_text(encoding='utf8'))['costs']
  cls.fields=json.loads((app.RESOURCE/'native-player-fields.json').read_text(encoding='utf8'))
  cls.abilities=json.loads((app.RESOURCE/'native-ability-bits.json').read_text(encoding='utf8'));cls.skills=json.loads((app.RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))

 def test_stock_record_hydrates_old_projects_and_explicit_clear_takes_priority(self):
  source=copy.deepcopy(self.source);expected=from_record(bytes.fromhex(source['_studio_client_record']))
  source['parameters'][63:70]=[0]*7
  self.assertEqual(restore_payload(source)['ai_playing_styles'],expected)
  p=app.default_project();p.pop('ai_playing_styles');p['source_player']={'original_payload':source}
  self.assertEqual(app.normalize_project(p)['ai_playing_styles'],expected)
  p['ai_playing_styles']=[]
  self.assertEqual(project_value(p,source),[])
  for invalid in ('trickster',['unmapped'],[1],{'trickster':True}):
   p['ai_playing_styles']=invalid
   with self.assertRaises(ValueError):app.normalize_project(p)

 def test_each_flag_reaches_owned_maximum_and_native_rows_without_neighbour_damage(self):
  p=app.default_project();p['identity']['name']='AI Test'
  identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
  template=bytes.fromhex(self.source['_studio_client_record']);mask=sum(1<<f['bit'] for f in FIELDS.values())
  rows=[]
  for selected in ([],*([k] for k in FIELDS),list(FIELDS)):
   p['ai_playing_styles']=selected;definition=compile_player(p,app.CATALOG,self.costs,identity,self.source,18,103,template)
   row=player_record(template,p,definition,self.fields,self.abilities,self.skills);rows.append(row)
   self.assertEqual(set(from_record(row)),set(selected))
   for key,f in FIELDS.items():
    for params in (definition['base_parameters'],definition['owned']['parameters'],definition['owned']['_careerplan_base_parameters'],definition['maximum_development']['parameters']):self.assertEqual(params[f['parameter']],int(key in selected))
  original=int.from_bytes(rows[0],'little')
  for row in rows:self.assertEqual(int.from_bytes(row,'little')&~mask,original&~mask)

 def test_project_share_roundtrip_keeps_choices_and_empty_selection(self):
  with tempfile.TemporaryDirectory() as tmp:
   one=app.Store(Path(tmp)/'one');two=app.Store(Path(tmp)/'two')
   for selected in (['trickster','long_ranger'],[]):
    p=app.default_project();p['identity']['name']='AI Test';p['ai_playing_styles']=selected
    result=two.import_project(one.export_project(p)['path'])
    self.assertEqual(result['package_id'],p['package_id']);self.assertEqual(result['ai_playing_styles'],selected)

 def test_native_mapping_matches_original_apk_reader(self):
  from apk_literals import module_reader,literal_assignments
  apk=Path(__file__).resolve().parents[2].parent/'73efootball安装包及资源/73efootball-V16(1).apk'
  if not apk.is_file():self.skipTest('requires original V16 APK')
  code=module_reader(apk)('export_ai_playing_styles');fields=literal_assignments(code,{'FIELDS'})['FIELDS']
  read=types.FunctionType(next(c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name=='bin_vector'),{'FIELDS':fields})
  for record in (bytes.fromhex(self.source['_studio_client_record']),bytes([255])*400,bytes(400)):
   self.assertEqual(set(from_record(record))&set(FIELDS),{k for k,v in read(record).items() if v})
  self.assertEqual({k:f['bit'] for k,f in FIELDS.items()},{name:byte*8+bit for name,_,byte,bit in fields})

if __name__=='__main__':unittest.main()
