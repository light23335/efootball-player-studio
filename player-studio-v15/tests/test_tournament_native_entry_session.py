"""Runtime replies must reach the real native entry-log parser and UI wrapper."""
import copy
import sqlite3
import unittest
import uuid
from unittest.mock import patch
import tournament_runtime as runtime
import test_tournament_native_entry_registration as entry_fixtures
from test_tournament_roster_membership_native import mode_probe


class NativeEntrySessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=entry_fixtures.NativeEntryRegistrationTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s=self.fixture.s;self.db=self.fixture.db

    def events(self,service=None):
        if service is None:return self.fixture.events()
        original=self.s.service
        try:
            self.s.service=service
            return self.fixture.events()
        finally:self.s.service=original

    def pair(self,response):
        eid=self.s.definition['event_id']
        return (next(r for r in response['event_list']if r['event_id']==eid),
                next(r for r in response['event_log_list']if r['event_id']==eid))

    def enter(self,service=None):
        return (service or self.s.service).handle(self.s.logic,'CMD_SET_EVENT_ENTER',
            {'event_id':self.s.definition['event_id'],'rqid':17},lambda *a:self.fail('ordinary entry'))

    def native(self,row,log,reply):
        return mode_probe(row,special=reply['special_dream_squad_data'],event_log=log,
                          entry_reply=reply,registration_wrapper=True)

    def fresh_service(self):
        service=runtime.Service(lambda:self.s.document,'.',self.s.generator)
        for name,options in(('activate_coaching',{}),('reinforcements',{'return_value':[]})):
            p=patch.object(service,name,**options);p.start();self.addCleanup(p.stop)
        return service

    def test_runtime_entry_reply_fixes_old_missing_log_failure_in_original_parser_and_ui_wrapper(self):
        row,log=self.pair(self.events());self.assertEqual(log['entry_status'],'NO_ENTRY')
        reply=self.enter();missing=copy.deepcopy(reply);missing.pop('event_log',None)
        failed=self.native(row,log,missing)
        self.assertEqual(failed['registered_slots'],23)
        self.assertEqual(failed['entry_log_update'],0)
        self.assertEqual(failed['rental_registration_results'],[0]*23)
        self.assertFalse(failed['membership_hook_entered'])
        self.assertEqual(reply['event_log']['event_id'],row['event_id'])
        self.assertEqual(reply['event_log']['entry_status'],'ENTRY')
        self.assertEqual(reply['event_log']['use_preset_team_id'],self.s.definition['player_team_id'])
        accepted=self.native(row,log,reply)
        self.assertEqual(accepted['entry_log_update'],1)
        self.assertEqual(accepted['rental_registration_results'],[1]*23)
        self.assertTrue(accepted['membership_hook_entered'])
        self.assertEqual((accepted['same_membership_owned_registration'],accepted['foreign_owned_registration']),(1,0))
        self.assertEqual(accepted['ordinary_team'],7)

    def test_same_session_list_retains_entry_after_successful_native_install(self):
        first_row,first_log=self.pair(self.events());reply=self.enter()
        saved=copy.deepcopy(runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid']))
        row,log=self.pair(self.events())
        self.assertEqual(log['entry_status'],'ENTRY')
        self.assertEqual(log['use_preset_team_id'],self.s.definition['player_team_id'])
        self.assertEqual(runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid'])['fixtures'],saved['fixtures'])
        self.assertEqual(mode_probe(row,special=reply['special_dream_squad_data'],event_log=log,
                                   registration_wrapper=True)['rental_registration_results'],[1]*23)

    def test_cold_service_reenters_native_slot_without_resetting_saved_competition(self):
        self.events();first=self.enter()
        before=copy.deepcopy(runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid']))
        cold=self.fresh_service();row,log=self.pair(self.events(cold))
        self.assertEqual(log['entry_status'],'NO_ENTRY')
        reply=self.enter(cold);after=runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid'])
        self.assertEqual(after['run_id'],before['run_id'])
        self.assertEqual(after['fixtures'],before['fixtures'])
        self.assertEqual(reply['special_dream_squad_data'],first['special_dream_squad_data'])
        self.assertEqual(self.native(row,log,reply)['rental_registration_results'],[1]*23)
        self.assertEqual(self.pair(self.events(cold))[1]['entry_status'],'ENTRY')

    def test_failed_final_persistence_keeps_no_entry_until_successful_retry(self):
        self.events();self.db.commit()
        key=runtime.PREFIX+self.s.definition['uuid']
        before=copy.deepcopy(runtime.get(self.db,key));put=runtime.put

        def fail_final(conn,name,value):
            if name==key and isinstance(value,dict) and value.get('active'):
                raise sqlite3.OperationalError('final entry persistence failed')
            return put(conn,name,value)

        with patch.object(runtime,'put',side_effect=fail_final):
            with self.assertRaisesRegex(sqlite3.OperationalError,'final entry persistence failed'):
                self.enter()
        saved=runtime.get(self.db,key)
        self.assertNotIn('active',saved)
        self.assertEqual(saved['run_id'],before['run_id'])
        self.assertIsNone(self.s.service.entry_binding)
        row,log=self.pair(self.events())
        self.assertEqual(log['entry_status'],'NO_ENTRY')
        reply=self.enter()
        self.assertEqual(self.native(row,log,reply)['rental_registration_results'],[1]*23)
        self.assertIn('active',runtime.get(self.db,key))
        self.assertEqual(self.pair(self.events())[1]['entry_status'],'ENTRY')

    def test_failed_home_publication_keeps_committed_roster_unentered_until_retry(self):
        self.events();first=self.enter()
        self.assertIsNotNone(self.s.service.entry_binding)
        key=runtime.PREFIX+self.s.definition['uuid']
        before=copy.deepcopy(runtime.get(self.db,key))
        with patch.object(runtime,'publish_saved_home',side_effect=ValueError('entry homepage publication failed')):
            with self.assertRaisesRegex(ValueError,'entry homepage publication failed'):
                self.enter()
        saved=runtime.get(self.db,key)
        self.assertIn('active',saved)
        self.assertEqual(saved['run_id'],before['run_id'])
        self.assertEqual(saved['active'],before['active'])
        self.assertIsNone(self.s.service.entry_binding)
        row,log=self.pair(self.events())
        self.assertEqual(log['entry_status'],'NO_ENTRY')
        reply=self.enter()
        self.assertEqual(reply['special_dream_squad_data'],first['special_dream_squad_data'])
        self.assertEqual(self.native(row,log,reply)['rental_registration_results'],[1]*23)
        self.assertEqual(self.pair(self.events())[1]['entry_status'],'ENTRY')

    def test_unstarted_control_team_change_requires_new_native_registration(self):
        self.events();self.enter()
        before=copy.deepcopy(runtime.get(self.db,runtime.PREFIX+self.s.definition['uuid']))
        definition=dict(self.s.definition,player_team_id=122)
        self.s.definition=definition;self.s.document['tournaments']=[definition]
        row,log=self.pair(self.events())
        self.assertEqual(log['entry_status'],'NO_ENTRY')
        reply=self.enter();self.assertEqual(reply['special_dream_squad_data']['rental_team_id'],122)
        self.assertEqual(reply['event_log']['use_preset_team_id'],122)
        after=runtime.get(self.db,runtime.PREFIX+definition['uuid'])
        self.assertEqual(after['run_id'],before['run_id'])
        self.assertEqual([f['played']for f in after['fixtures']],[f['played']for f in before['fixtures']])
        self.assertEqual(self.native(row,log,reply)['rental_registration_results'],[1]*23)
        self.assertEqual(self.pair(self.events())[1]['entry_status'],'ENTRY')

    def test_entering_another_competition_invalidates_single_slot_then_restores_issued_start(self):
        first=self.s.definition
        second=runtime.configuration([dict(first,uuid=str(uuid.uuid4()),name='Second competition',player_team_id=122)])[0]
        self.s.document['tournaments']=[first,second]
        self.events();self.enter()
        current=runtime.get(self.db,runtime.PREFIX+first['uuid'])
        self.s.service.start(self.s.logic,first,current,{'game_id':current['active']['game_id']})
        issued=copy.deepcopy(current['active']);runtime.put(self.db,runtime.PREFIX+first['uuid'],current)
        second_reply=self.s.service.handle(self.s.logic,'CMD_SET_EVENT_ENTER',
            {'event_id':second['event_id']},lambda *a:self.fail('ordinary second entry'))
        response=self.events();row,log=self.pair(response)
        second_log=next(r for r in response['event_log_list']if r['event_id']==second['event_id'])
        self.assertEqual((log['entry_status'],second_log['entry_status']),('NO_ENTRY','ENTRY'))
        self.assertEqual(second_reply['special_dream_squad_data']['rental_team_id'],122)
        self.assertEqual(runtime.get(self.db,runtime.PREFIX+first['uuid'])['active'],issued)
        restored=self.enter()
        self.assertEqual(self.native(row,log,restored)['rental_registration_results'],[1]*23)
        self.assertEqual(runtime.get(self.db,runtime.PREFIX+first['uuid'])['active'],issued)
        response=self.events()
        self.assertEqual(self.pair(response)[1]['entry_status'],'ENTRY')
        self.assertEqual(next(r for r in response['event_log_list']if r['event_id']==second['event_id'])['entry_status'],'NO_ENTRY')


if __name__=='__main__':unittest.main()
