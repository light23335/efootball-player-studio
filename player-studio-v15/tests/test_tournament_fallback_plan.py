"""Auto-added Standard copies stay on the initial bench, not a live-match ban."""
import copy
import json
import types
import unittest
import uuid
from unittest.mock import patch

import tournament_rules as rules
import tournament_runtime as runtime
import test_tournament_fallback_squads as fixtures


class FallbackPlanTests(unittest.TestCase):
    def setUp(self):
        source=fixtures.FallbackSquadTests();self.addCleanup(source.doCleanups)
        self.generator,self.db,self.document,self.proto,original=source.fixture(11)
        for row in original:
            card=copy.deepcopy(row);card['gameplayer_id']['id']+=10000;card['initial_base_team_id']=122
            raw=json.dumps(card)
            self.db.execute('insert into managed_cards values(?,?,?)',(str(card['gameplayer_id']['id']),raw,raw))
        self.definition=runtime.configuration([dict(uuid=str(uuid.uuid4()),name='Fallback initial XI',enabled=True,
            team_ids=[121,122],player_team_id=121,stages=[dict(type='knockout')])])[0]
        self.document['tournaments']=[self.definition]
        self.service=runtime.Service(lambda:self.document,'.',self.generator)
        self.current=rules.start(self.definition,51)
        self.logic=types.SimpleNamespace(conn=self.db,responses={'CMD_START_GAME':{
            'uniform_list_home':{},'uniform_list_away':{}}},templates={})
        modules={'ziru_data':types.SimpleNamespace(vscom_opponent=lambda:copy.deepcopy(self.proto)),
                 'ai_match_manager':types.SimpleNamespace(prepare_strategies=lambda *a,**k:None,
                                                          prepare_tournament_fallback=lambda *a,**k:None),
                 'custom_stadium':types.SimpleNamespace(apply=lambda *a:None),
                 'club_store':types.SimpleNamespace(default_uniforms=lambda team:[team])}
        self.addCleanup(patch.stopall);patch.dict('sys.modules',modules).start()
        patch.object(self.service,'activate_coaching').start()
        patch.object(self.service,'reinforcements',return_value=[]).start()
        self.active=self.service.prepare(self.db,self.definition,self.current,{})
        self.own=self.active[self.active['player_side'].lower()]

    def invalid_plan(self):
        plan=copy.deepcopy(self.active.get('own_plan')or self.own['squad_data'])
        order=plan['squad_gameplan']['match_plan_settings']['order']
        order[0],order[11]=order[11],order[0]
        return plan

    def test_move_auto_added_copy_to_initial_xi_returns_success_notice_and_keeps_old_legal_plan(self):
        before=copy.deepcopy(self.active)
        out=self.service.save_plan(self.db,self.definition,self.current,
            {'special_squad_data':{'squad_data':self.invalid_plan()}})
        self.assertEqual(out['result'],'NOERR');self.assertIn('只用于初始替补',out['studio_notice'])
        self.assertEqual(self.active,before)
        self.assertFalse(runtime.borrowed_standard_in_initial_xi(self.own,self.own['squad_data']))

    def test_valid_captain_edit_survives_and_first_start_rejects_old_bad_plan_with_explicit_notice(self):
        out=self.service.save_plan(self.db,self.definition,self.current,
            {'special_squad_data':{'squad_data':{'squad_gameplan':{'match_plan_settings':{'captain':2}}}}})
        self.assertEqual(out,{'result':'NOERR'})
        retained=copy.deepcopy(self.active['own_plan'])
        self.active['own_plan']=self.invalid_plan()
        out=self.service.start(self.logic,self.definition,self.current,{'game_id':self.active['game_id']})
        self.assertEqual(out['result'],'NOERR');self.assertIn('只用于初始替补',out['studio_notice'])
        self.assertEqual(out['squad_data_home']['squad_gameplan'],retained['squad_gameplan'])
        self.assertEqual(self.active['own_plan'],retained)
        order=out['squad_data_home']['squad_gameplan']['match_plan_settings']['order']
        added=set(self.own['_studio_tournament_squad']['fallback']['added_standard_card_ids'])
        self.assertTrue(all(out['squad_data_home']['player_list'][i]['gameplayer_id']['id']not in added for i in order[:11]))

    def test_owned_instance_of_same_card_and_normal_team_are_not_mistaken_for_auto_added_copy(self):
        plan=self.invalid_plan();order=plan['squad_gameplan']['match_plan_settings']['order']
        plan['player_list'][order[0]]['gameplayer_id']['serial']=12345
        self.assertFalse(runtime.borrowed_standard_in_initial_xi(self.own,plan))
        normal=copy.deepcopy(self.own);normal['_studio_tournament_squad'].pop('fallback')
        self.assertFalse(runtime.borrowed_standard_in_initial_xi(normal,self.invalid_plan()))

    def test_started_resume_does_not_revalidate_in_match_substitutions(self):
        issued=self.service.start(self.logic,self.definition,self.current,{'game_id':self.active['game_id']})
        self.active['own_plan']=self.invalid_plan()
        with patch.object(runtime,'borrowed_standard_in_initial_xi',side_effect=AssertionError('live/resume guard')):
            resumed=self.service.start(self.logic,self.definition,self.current,{'game_id':self.active['game_id']})
        self.assertEqual(resumed,issued)


if __name__=='__main__':unittest.main()
