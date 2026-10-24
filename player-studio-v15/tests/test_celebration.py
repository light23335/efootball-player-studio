from pathlib import Path
from types import SimpleNamespace
import copy,json,sqlite3,struct,sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,packs
from native_celebration import FIELD,from_record,from_payload,restore_payload,project_value
from native_tables import player_record


class CelebrationTests(unittest.TestCase):
 def test_old_partial_catalogue_reads_native_value_without_touching_saved_zero(self):
  record=bytearray(400);record[44:46]=(141).to_bytes(2,'little')
  payload={'parameters':[0]*147,'_studio_client_record':record.hex()};before=copy.deepcopy(payload)
  self.assertEqual(from_payload(payload),141)
  loaded=restore_payload(copy.deepcopy(payload));self.assertEqual(loaded['parameters'][59],141);self.assertEqual(payload,before)
  p={'source_player':{'original_payload':payload}}
  self.assertEqual(project_value(p,{}),141)
  self.assertEqual(project_value(dict(p,celebration=0),{}),0)
  self.assertEqual(project_value(dict(p,celebration=511),{}),511)
  self.assertEqual(project_value({},payload),141)
  self.assertEqual(project_value({}, {}, record),141)
  for invalid in (-1,512,65535,True,1.5):
   with self.assertRaises(ValueError):project_value(dict(p,celebration=invalid),{})

 def test_library_and_native_export_agree_on_original_card_and_explicit_override(self):
  db=sqlite3.connect(app.RESOURCE/'library.sqlite3')
  raw=db.execute('select payload from players where name_en=? limit 1',('Roberto Firmino',)).fetchone()[0];db.close()
  payload=json.loads(raw);template=bytes.fromhex(payload['_studio_client_record'])
  self.assertEqual(from_record(template),141)
  fields=json.loads((app.RESOURCE/'native-player-fields.json').read_text(encoding='utf8'));fields.pop('celebration') # older imported database
  abilities=json.loads((app.RESOURCE/'native-ability-bits.json').read_text(encoding='utf8'));skills=json.loads((app.RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
  p=app.default_project();p['identity'].update(name='Test',shirt_name='SHIRT');base=restore_payload(payload)['parameters'];base[59]=18
  d={'base_parameters':base,'identity':{'card_id':90000001},'owned':{'initial_base_team_id':103,'_nation_id':18}}
  result=player_record(template,p,d,fields,abilities,skills)
  self.assertEqual(from_record(result),18)
  difference=(int.from_bytes(result,'little')^int.from_bytes(template,'little'))
  # Neighboring fields immediately around the nine celebration bits stay intact.
  mask=((1<<9)-1)<<352
  self.assertEqual((difference&~mask)&(((1<<24)-1)<<344),0)
  base[59]=0;self.assertEqual(from_record(player_record(template,p,d,fields,abilities,skills)),0)

 def test_empty_pack_draft_can_be_saved_but_cannot_generate_game_pool(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=app.Store(Path(tmp)/'data')
   original={'uuid':str(uuid.uuid4()),'name':'Pool','enabled':True,'replacement':True,'description':'Keep','banner':0,'members':[{'kind':'original','id':'7511','name':'Messi','weight':7}]}
   packs.save(store,original);cleared=copy.deepcopy(original);cleared['members']=[];packs.save(store,cleared)
   result=packs.load(store)[0];self.assertEqual(result['members'],[])
   for key in ('uuid','name','description','banner','replacement','enabled'):self.assertEqual(result[key],original[key])
   with self.assertRaisesRegex(ValueError,'空草稿'):packs.compile_packs([result],[],app.RESOURCE)

 def test_all_original_excluded_cards_stay_out_of_random_pools(self):
  from pack_catalogue import exclusions
  blocked=exclusions(app.RESOURCE);self.assertEqual(len(blocked),134)
  eligible={row['id'] for pool in packs._random_pools(app.RESOURCE).values() for row in pool}
  self.assertFalse(eligible&set(blocked))
  raw=json.loads((app.RESOURCE/'pack-exclusions.json').read_text(encoding='utf8'))
  china={cid for cid,row in raw.items() if row['reason']=='China edition'}
  self.assertEqual(len(china),126);self.assertTrue(china<=eligible)

if __name__=='__main__':unittest.main()
