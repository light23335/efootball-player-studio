"""A persisted competition must still initialize the client's special slot."""
import copy,struct,types,unittest
import tournament_home as home
import tournament_runtime as runtime
import test_tournament_sim_lifecycle as fixtures
from unittest.mock import patch

class NativeEntryRegistrationTests(unittest.TestCase):
 def setUp(self):
  fixture=fixtures.SimulationLifecycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  mock=patch.dict('sys.modules',{'cup16_mode':types.SimpleNamespace(game_id=lambda req:req.get('game_id'))})
  mock.start();self.addCleanup(mock.stop)
  self.s=fixture;self.db=fixture.db;self.current=fixture.current
  runtime.put(self.db,runtime.PREFIX+fixture.definition['uuid'],self.current)
  self.channel=home.Channel(bytearray(home.SCHEMA['bytes']),0,lambda:None)
  patcher=patch.object(home,'_CHANNEL',self.channel);patcher.start();self.addCleanup(patcher.stop)

 def events(self):
  response={'result':'NOERR','event_list':[{'event_id':1120005,'ch_event_type':'CHALLENGE',
            'is_custom_team':'YES','is_vsai_custom_team':'YES','is_vsai_gameplan_disp':'YES','match_env':{'match_time':10}}],
            'event_log_list':[{'event_id':1120005,'entry_status':'ENTRY','ch_mission_log':[]}]}
  out=runtime.project_events(self.s.logic,response,self.s.document['tournaments'],nations={'121':7},service=self.s.service)
  self.current=runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid'])
  return out

 def test_fresh_event_requires_the_native_entry_response_instead_of_reusing_ordinary_slot(self):
  out=self.events();self.assertEqual(out['event_log_list'][0]['entry_status'],'NO_ENTRY')
  self.assertEqual(out['event_list'][0]['match_entry']['entry_type'],'NATIONALITY')
  self.assertEqual(struct.unpack_from('<II',self.channel.buffer,64+home.SCHEMA['membership_offset']),(1,7))
  self.assertNotIn('active',self.current)

 def test_entry_installs_all_23_and_reentry_keeps_progress_and_valid_user_plan(self):
  run=self.current['run_id'];self.events()
  command='CMD_SET_EVENT_ENTER'
  out=self.s.service.handle(self.s.logic,command,{'event_id':self.s.definition['event_id'],'rqid':5},lambda *a:self.fail('ordinary entry'))
  data=out['special_dream_squad_data']
  self.assertEqual(len(data['squad_data']['player_list']),23);self.assertEqual(len(data['rental_gameplayer_list']),23)
  self.assertEqual(data['initial_settings'],'YES')
  self.current=runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid']);saved=copy.deepcopy(self.current)
  repeated=self.events();self.assertEqual(repeated['event_log_list'][0]['entry_status'],'ENTRY')
  self.assertEqual(self.current['run_id'],run);self.assertEqual(self.current['fixtures'],saved['fixtures'])
  self.assertEqual(self.current['active'],saved['active'])

 def test_issued_resume_reenters_cold_native_slot_without_replacing_frozen_contract(self):
  active=self.s.service.prepare(self.db,self.s.definition,self.current,{})
  self.s.service.start(self.s.logic,self.s.definition,self.current,{'game_id':active['game_id']})
  issued=copy.deepcopy(self.current['active']);runtime.put(self.db,runtime.PREFIX+self.s.definition['uuid'],self.current)
  out=self.events();self.assertEqual(out['event_log_list'][0]['entry_status'],'NO_ENTRY')
  self.assertEqual(self.current['active'],issued)
  self.s.service.handle(self.s.logic,'CMD_SET_EVENT_ENTER',{'event_id':self.s.definition['event_id']},lambda *a:self.fail('ordinary entry'))
  resumed=runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid'])
  self.assertEqual(resumed['active'],issued)
  self.assertEqual(self.events()['event_log_list'][0]['entry_status'],'ENTRY')

 def test_saved_home_refresh_publishes_same_membership_policy_for_both_aliases(self):
  for team in(54,49206):
   self.current['definition']['player_team_id']=team
   runtime.put(self.db,runtime.PREFIX+self.s.definition['uuid'],self.current)
   runtime.publish_saved_home(self.db,[self.s.definition],{},nations={'54':7,'49206':7})
   self.assertEqual(struct.unpack_from('<II',self.channel.buffer,64+home.SCHEMA['membership_offset']),(1,7))
  self.assertEqual(runtime.team_membership({'player_team_id':121},{}),{'kind':'club','entity_id':121})

if __name__=='__main__':unittest.main()
