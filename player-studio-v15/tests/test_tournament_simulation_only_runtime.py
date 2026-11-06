"""CPU-only runtime omits auxiliary coaching work; actual START remains full."""
import copy
import sys
import unittest
from unittest.mock import patch

import ai_match_manager as manager
import tournament_rules as rules
import tournament_simulation as model
import test_tournament_sim_lifecycle as lifecycle


class SimulationOnlyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.f=lifecycle.SimulationLifecycleTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        # The shared lifecycle fixture normally stubs auxiliary strategy work.
        # These tests execute its actual full preparation as the control.
        patch.dict(sys.modules,{'ai_match_manager':manager}).start()
        self.service=self.f.service;self.conn=self.f.db

    def cpu_fixture(self,current):
        player=current['definition']['player_team_id']
        return next(f for f in rules.due(current)if player not in(f['home'],f['away']))

    def test_cpu_runtime_skips_auxiliary_preflight_with_identical_scores_and_rating_inputs(self):
        full=copy.deepcopy(self.f.current);short=copy.deepcopy(self.f.current)
        full_fixture=self.cpu_fixture(full);short_fixture=self.cpu_fixture(short)
        build=self.service.fixture_teams
        def full_teams(conn,current,fixture,**options):
            return build(conn,current,fixture,simulation_only=False)
        with patch.object(manager,'prepare_strategies',wraps=manager.prepare_strategies)as prepare:
            with patch.object(self.service,'fixture_teams',side_effect=full_teams):
                self.service.simulate_fixture(self.conn,full,full_fixture)
            self.assertEqual(prepare.call_count,2)
            prepare.reset_mock()
            self.service.simulate_fixture(self.conn,short,short_fixture)
            prepare.assert_not_called()
        original=full_fixture['simulation_v1'];optimized=short_fixture['simulation_v1']
        for side in('home','away'):
            first=copy.deepcopy(original['teams'][side]);second=copy.deepcopy(optimized['teams'][side])
            spec=first['_studio_tournament_squad'].pop('tactical_spec')
            self.assertEqual(set(spec['prepared']),{'chase','last_push','protect'})
            self.assertIsNone(second['_studio_tournament_squad'].pop('tactical_spec'))
            self.assertEqual(first,second,'actual 23/coaches/formation/abilities must stay exact')
        for field in('seeds','ratings','form','xg','expected','result','model_version','strength_version'):
            self.assertEqual(original[field],optimized[field],field)
        for field in('score','penalties','extra_time_score','played'):
            self.assertEqual(full_fixture[field],short_fixture[field],field)

    def test_actual_player_start_keeps_complete_cpu_tactical_spec_and_default_generator_api(self):
        build=self.f.generator.build_club
        with patch.object(self.f.generator,'build_club',wraps=build)as generator,\
             patch.object(manager,'prepare_strategies',wraps=manager.prepare_strategies)as prepare:
            active,fixture,reply=self.f.start()
        self.assertEqual(prepare.call_count,1)
        self.assertEqual(generator.call_count,2)
        self.assertTrue(all('simulation_only'not in call.kwargs for call in generator.call_args_list))
        cpu='away'if active['player_side']=='HOME'else'home'
        spec=fixture['simulation_v1']['teams'][cpu]['_studio_tournament_squad']['tactical_spec']
        self.assertEqual(set(spec['prepared']),{'chase','last_push','protect'})
        self.assertEqual(len(spec['players']),23)
        self.assertEqual(len(reply['squad_data_home']['player_list']),23)
        self.assertEqual(len(reply['squad_data_away']['player_list']),23)
        self.assertTrue(active['started']);self.assertTrue(fixture['simulation_v1']['frozen'])

    def test_cached_full_cpu_contract_is_never_rebuilt_or_stripped(self):
        current=self.f.current;fixture=self.cpu_fixture(current)
        self.service.fixture_teams(self.conn,current,fixture)
        contract=self.service.freeze_fixture(self.conn,current,fixture)
        before=copy.deepcopy(contract)
        self.assertTrue(all(contract['teams'][s]['_studio_tournament_squad']['tactical_spec']for s in('home','away')))
        with patch.object(self.f.generator,'build_club',side_effect=AssertionError('cached contract rebuilt')),\
             patch.object(manager,'prepare_strategies',side_effect=AssertionError('cached strategies rebuilt')):
            self.service.simulate_fixture(self.conn,current,fixture)
        for field in('teams','seeds','ratings','form','xg','expected'):
            self.assertEqual(contract[field],before[field],field)
        settled=copy.deepcopy(fixture)
        with patch.object(model,'sample_period',side_effect=AssertionError('settled result redrawn')):
            self.service.simulate_fixture(self.conn,current,fixture)
        self.assertEqual(fixture,settled)


if __name__=='__main__':unittest.main()
