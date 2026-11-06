"""Only unissued private tournament caches migrate; owned saves are immutable."""
import copy,json,types,unittest,uuid
from unittest.mock import patch
import tournament_runtime as runtime
import tournament_rules as rules
from test_tournament_sim_strength import generator_fixture

class CachedRosterRepairTests(unittest.TestCase):
 def setUp(self):
  self.g,self.db,self.doc,self.proto=generator_fixture();self.addCleanup(self.db.close)
  originals=[json.loads(r[0])for r in self.db.execute('select payload from managed_cards')]
  self.db.execute('delete from managed_cards')
  for team,nation in((54,7),(122,14)):
   for original in originals:
    p=copy.deepcopy(original);p['gameplayer_id']['id']+=team*10000
    p.update(initial_base_team_id=team,_nation_id=nation,initial_base_national_team_id=49206 if team==54 else 7)
    raw=json.dumps(p);self.db.execute('insert into managed_cards values(?,?,?)',(str(p['gameplayer_id']['id']),raw,raw))
  self.doc['native_player_catalogue']={'version':1,'card_ids':[int(r[0])for r in self.db.execute('select card_id from managed_cards')]}
  self.doc['tournament_national_team_nations']={'54':7,'49206':7}
  coach=copy.deepcopy(self.doc['division_squads']['coaches'][0]['payload'])
  self.db.execute('insert into coaches values(?,?,?)',(coach['coach_id']['id'],0,json.dumps(coach)))
  self.db.execute('create table gameplayers(marker)');self.db.execute('insert into gameplayers values(12345)')
  self.definition=runtime.configuration([dict(uuid=str(uuid.uuid4()),name='China cache',enabled=True,
       team_ids=[54,122],player_team_id=54,stages=[dict(type='knockout')])])[0]
  self.doc['tournaments']=[self.definition];self.current=rules.start(self.definition,63)
  f=rules.due(self.current)[0];f.update(home=54,away=122)
  self.owned=[]
  modules={'ziru_data':types.SimpleNamespace(vscom_opponent=lambda:copy.deepcopy(self.proto)),
   'ai_match_manager':types.SimpleNamespace(prepare_strategies=lambda *a,**kw:None),
   'club_store':types.SimpleNamespace(players=lambda c:copy.deepcopy(self.owned),wire_player=copy.deepcopy,default_uniforms=lambda t:[t]),
   'custom_stadium':types.SimpleNamespace(apply=lambda *a:None)}
  self.addCleanup(patch.stopall);patch.dict('sys.modules',modules).start()
  self.service=runtime.Service(lambda:self.doc,'.',self.g)
  patch.object(self.service,'reinforcements',return_value=[]).start()
  patch.object(self.service,'activate_coaching').start()
  self.active=self.service.prepare(self.db,self.definition,self.current,{})
  self.logic=types.SimpleNamespace(conn=self.db,responses={'CMD_START_GAME':{'uniform_list_home':{},'uniform_list_away':{}}},templates={})
  self.protected=list(self.db.execute('select *from managed_cards')),list(self.db.execute('select *from gameplayers'))

 def foreign(self):
  p=copy.deepcopy(self.active['away']['player_list'][3])
  p.update(initial_base_team_id=54,initial_base_national_team_id=54,_nation_id=7,type='RENTAL')
  p['gameplayer_id']['serial']=0
  return p

 def assert_protected(self):
  self.assertEqual(self.protected,(list(self.db.execute('select *from managed_cards')),list(self.db.execute('select *from gameplayers'))))

 def test_outgoing_team_paint_cannot_make_foreign_cached_or_owned_player_eligible(self):
  foreign=self.foreign();self.active['home']['player_list'].append(foreign)
  owned=copy.deepcopy(foreign);owned['gameplayer_id']['serial']=999;self.owned=[owned]
  pool=self.service.player_pool(self.db,self.definition,self.active)
  self.assertNotIn((foreign['gameplayer_id']['id'],0),pool)
  self.assertNotIn((foreign['gameplayer_id']['id'],999),pool);self.assert_protected()

 def test_wrong_cached_rental_is_reissued_under_same_game_and_fixture_without_touching_cpu(self):
  own=self.active['home'];foreign=self.foreign()
  own['player_list'][3]=foreign;own['squad_data']['player_list'][3]['gameplayer_id']=foreign['gameplayer_id'].copy()
  gid=self.active['game_id'];fixture=self.active['fixture_id'];run=self.current['run_id'];cpu=copy.deepcopy(self.active['away'])
  special=self.service.special(self.db,self.definition,self.current,{})
  self.assertEqual((self.active['game_id'],self.active['fixture_id'],self.current['run_id']),(gid,fixture,run))
  self.assertEqual(self.active['away'],cpu);self.assertEqual(len(special['squad_data']['player_list']),23)
  self.assertNotIn(foreign['gameplayer_id'],[r['gameplayer_id']for r in special['squad_data']['player_list']])
  self.assertIn('private_roster_repair_backups_v1',self.current);self.assertIn('赛程',self.current['plan_notice']);self.assert_protected()

 def test_polluted_own_plan_only_is_repaired_and_valid_private_team_is_unchanged(self):
  own=copy.deepcopy(self.active['home']);plan=copy.deepcopy(own['squad_data'])
  plan['player_list'][2]['gameplayer_id']=self.foreign()['gameplayer_id'].copy();self.active['own_plan']=plan
  self.service.special(self.db,self.definition,self.current,{})
  self.assertEqual(self.active['home'],own);self.assertEqual(self.active['own_plan'],own['squad_data']);self.assert_protected()

 def test_distinct_card_variants_of_one_native_person_repair_only_unissued_private_roster(self):
  from tournament_identity import native_person_key
  own=self.active['home'];variant=copy.deepcopy(own['player_list'][0])
  variant['gameplayer_id']['id']|=1<<23
  cid=variant['gameplayer_id']['id'];raw=json.dumps(variant)
  self.db.execute('insert into managed_cards values(?,?,?)',(str(cid),raw,raw))
  self.doc['native_player_catalogue']['card_ids'].append(cid)
  self.protected=list(self.db.execute('select *from managed_cards')),list(self.db.execute('select *from gameplayers'))
  own['player_list'][1]=variant;own['squad_data']['player_list'][1]['gameplayer_id']=variant['gameplayer_id'].copy()
  self.assertIn('duplicate_private_person',self.service.cached_roster_errors(self.db,self.definition,own,54))
  game,run=self.active['game_id'],self.current['run_id'];cpu=copy.deepcopy(self.active['away'])
  self.service.special(self.db,self.definition,self.current,{})
  self.assertEqual(len({native_person_key(p['gameplayer_id']['id'])for p in self.active['home']['player_list']}),23)
  self.assertEqual((self.active['game_id'],self.current['run_id']),(game,run));self.assertEqual(self.active['away'],cpu)
  self.assert_protected()

 def test_saved_plan_native_duplicate_cannot_be_accepted_despite_23_different_card_ids(self):
  own=self.active['home'];variant=copy.deepcopy(own['player_list'][0]);variant['gameplayer_id']['id']|=1<<23
  cid=variant['gameplayer_id']['id'];raw=json.dumps(variant)
  self.db.execute('insert into managed_cards values(?,?,?)',(str(cid),raw,raw))
  self.doc['native_player_catalogue']['card_ids'].append(cid)
  self.owned=[variant];before=copy.deepcopy(self.active);plan=copy.deepcopy(own['squad_data'])
  plan['player_list'][1]['gameplayer_id']=variant['gameplayer_id'].copy()
  out=self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':plan}})
  self.assertEqual(out['result'],'NOERR');self.assertIn('合法阵容',out['studio_notice']);self.assertEqual(self.active,before)

 def test_issued_match_and_receipt_are_never_redrawn_by_the_repair(self):
  issued=self.service.start(self.logic,self.definition,self.current,{'game_id':self.active['game_id']})
  self.active['home']['player_list'][3]=self.foreign();before=copy.deepcopy(self.current)
  with patch.object(self.g,'build_club',side_effect=AssertionError('issued roster redrawn')):
   self.service.prepare(self.db,self.definition,self.current,{})
   repeated=self.service.start(self.logic,self.definition,self.current,{'game_id':self.active['game_id']})
  self.assertEqual(repeated,issued);self.assertEqual(self.current,before);self.assert_protected()

if __name__=='__main__':unittest.main()
