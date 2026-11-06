"""Only isolated synthetic/in-memory fixtures; no workshop/game or user save."""
import copy
import json
from pathlib import Path
import random
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_tactical_profiles as tactics
from coach_formula import displayed, factor
import tournament_sim_strength as strength


def document():
    coach = {'payload': {'coach_id': {'id': 9, 'serial': 0},
                         **dict.fromkeys(strength.STYLE_WIRE, 90)}, 'effects': {}}
    return {'revision': 'isolated-strength-fixture',
            'division_squads': {'coaches': [coach], 'empty_booster_ids': [136]},
            'preview_boosters': {'7': {'effects': {'20': 4}},
                                 '8': {'effects': {'16': 4}}}}


def team_snapshot(value=70):
    profile = next(p for p in tactics.profiles() if p['family'] == '433')
    roles = [*profile['attack'], 0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 11, 12]
    roster = []
    for index, role in enumerate(roles):
        params = [0] * 149
        params[0] = role
        for r, apt in enumerate(strength.APTITUDE_INDEX):
            params[apt] = 2 if (r == 0) == (role == 0) else 0
        for index_ability in strength.ABILITIES:
            params[index_ability] = value
        params[47] = 185
        params[144:147] = [0, 136, 0]
        roster.append({'gameplayer_id': {'id': 1000 + index, 'serial': 810000001 + index},
                       'parameters': params, 'disp_overall': 99,
                       'level_info': {'level': 35, 'level_limit': 35}})
    plan = {'team_style': 0,
            'formation_offensive': tactics.coordinates(profile, 'attack', 'possession'),
            'formation_defensive': tactics.coordinates(profile, 'defence', 'possession')}
    squad = {'team_id': 121, 'player_list': [{'gameplayer_id': copy.deepcopy(p['gameplayer_id'])} for p in roster],
             'coach': [{'coach_id': {'id': 9, 'serial': 0}}],
             'squad_gameplan': {'formation': [plan, copy.deepcopy(plan)],
                                'match_plan_settings': {'order': list(range(23)) + [255] * 17}}}
    return {'player_list': roster, 'squad_data': squad,
            'coach_data': copy.deepcopy(document()['division_squads']['coaches'][0]['payload']),
            'team_data': {'team_name': 'Any name', 'base_team_id': 121},
            strength.TEAM_MARKER: {'team_id': 121, 'all_max_level': True,
                                   'attack_roles': list(profile['attack']), 'defence_roles': list(profile['defence']),
                                   'style': 'possession'}}


def generator_fixture():
    """Real ClubGenerator, with deterministic isolated native-APK adapters."""
    from tournament_squads import ClubGenerator
    db = sqlite3.connect(':memory:')
    db.executescript('create table meta(key text primary key,value text);'
                     'create table managed_cards(card_id text primary key,fingerprint text,payload text);'
                     'create table coaches(coach_id integer,serial integer,json text);')
    doc = document()
    doc['players'] = []
    doc['division_squads'].update(enabled=True, excluded_ids=[], random_boosters=[
        {'id': 7, 'roles': list(range(1, 13)), 'effects': {'20': 4}},
        {'id': 8, 'roles': [0], 'effects': {'16': 4}}])
    source = team_snapshot()['player_list'][0]
    for role in range(13):
        for index in range(4):
            card = copy.deepcopy(source)
            card['gameplayer_id'] = {'id': 2000 + role * 10 + index, 'serial': 0}
            card['parameters'] = card['parameters'][:147]
            card['parameters'][0] = role
            card['parameters'][1:14] = [2] * 13
            card['level_info'] = {'level': 1, 'level_limit': 3}
            card['initial_base_team_id'] = 121
            raw = json.dumps(card)
            db.execute('insert into managed_cards values(?,?,?)', (str(card['gameplayer_id']['id']), raw, raw))
    db.commit()
    def develop(player, boosts=None):
        out = copy.deepcopy(player)
        for index in strength.ABILITIES:
            out['parameters'][index] += 2
        out['level_info']['level'] = out['level_info']['level_limit']
        return out
    adapter = types.SimpleNamespace(developed=develop)
    g = ClubGenerator(lambda: doc, adapter, lambda p, mode: copy.deepcopy(p), lambda: {},
                      lambda roles: None, lambda: {'121': {}},
                      lambda p, team_id: dict(p, team_data={'base_team_id': team_id}))
    plan = {'formation_offensive': [], 'formation_defensive': [], 'team_style': 0, 'coach_link_data': []}
    proto = {'team_data': {}, 'user_info': [], 'player_list': [],
             'squad_data': {'coach': [], 'player_list': [], 'squad_gameplan': {
                 'formation': [plan, copy.deepcopy(plan)], 'match_plan_settings': {}}}}
    return g, db, doc, proto


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.team = team_snapshot()
        self.doc = document()

    def rate(self, team=None, doc=None):
        return strength.ratings(self.team if team is None else team,
                                document=self.doc if doc is None else doc)

    def test_layout_and_weights_are_bound_to_verified_native_catalogue(self):
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads((root / 'resources/catalog.json').read_text('utf8'))
        evidence = json.loads((root / 'resources/native-coach-attributes.json').read_text('utf8'))
        self.assertEqual(set(strength.ABILITIES), set(map(int, catalog['ABILITIES'])))
        self.assertEqual(set(strength.ABILITIES), {row['parameter'] for row in evidence['rows']})
        self.assertEqual(list(strength.APTITUDE_INDEX),
                         [catalog['APTITUDES'].index(pos) + 1 for pos in catalog['POSITIONS']])
        for weights in strength.METRIC_FIELDS.values():
            self.assertAlmostEqual(sum(weights.values()), 1)

    def test_enhancing_front_line_raises_attack_without_raising_defence_or_keeper(self):
        before = self.rate()
        for player in self.team['player_list'][:11]:
            if player['parameters'][0] in (9, 10, 12):
                for field in strength.METRIC_FIELDS['attack']:
                    player['parameters'][field] += 25
        after = self.rate()
        self.assertGreater(after['attack'], before['attack'] + 15)
        self.assertEqual(after['defence'], before['defence'])
        self.assertEqual(after['goalkeeping'], before['goalkeeping'])

    def test_enhancing_defenders_and_keeper_changes_their_own_components(self):
        before = self.rate()
        for player in self.team['player_list'][:11]:
            if player['parameters'][0] in (1, 2, 3, 4):
                for field in strength.METRIC_FIELDS['defence']:
                    player['parameters'][field] += 25
        defence = self.rate()
        self.assertGreater(defence['defence'], before['defence'] + 15)
        self.assertEqual(defence['attack'], before['attack'])
        self.assertEqual(defence['goalkeeping'], before['goalkeeping'])
        for field in strength.METRIC_FIELDS['goalkeeping']:
            self.team['player_list'][0]['parameters'][field] += 25
        keeper = self.rate()
        self.assertGreater(keeper['goalkeeping'], defence['goalkeeping'] + 20)
        self.assertEqual(keeper['defence'], defence['defence'])

    def test_coach_float32_and_duplicate_booster_slots_are_applied_once(self):
        self.doc['division_squads']['coaches'][0]['effects'] = {'20': 2, '15': 1}
        for player in self.team['player_list']:
            player['parameters'][20] = 85
            player['parameters'][144:147] = [7, 7, 0]
        result = self.rate()
        p = result['audit']['players'][0]
        self.assertEqual(p['effective'][20], displayed(85, 4, 2, factor(90)))
        self.assertEqual(p['effective'][15], displayed(70, 0, 1, factor(90)))
        self.assertEqual(len(p['player_boosters']), 1)
        self.assertEqual(p['ability_formula_applications'], 1)
        self.assertEqual(self.team['player_list'][0]['parameters'][20], 85)

    def test_non_max_owned_entry_uses_actual_parameters_without_training(self):
        player = self.team['player_list'][-1]
        player['level_info'] = {'level': 3, 'level_limit': 35}
        player['parameters'][20] = 51
        result = self.rate()
        self.assertFalse(result['audit']['all_max_level'])
        self.assertTrue(result['audit']['actual_non_max_level'])
        self.assertEqual(result['audit']['players'][-1]['effective'][20], displayed(51, 0, 0, factor(90)))
        self.assertEqual(player['parameters'][20], 51)

    def test_actual_high_trained_values_are_preserved_and_final_ability_caps_at_120(self):
        self.team['player_list'][10]['parameters'][20] = 105
        self.team['player_list'][10]['parameters'][144] = 7
        result = self.rate()
        self.assertEqual(result['audit']['players'][10]['effective'][20], displayed(105, 4, 0, factor(90)))
        self.assertGreater(result['audit']['players'][10]['effective'][20], 105)
        self.doc['division_squads']['coaches'][0]['effects'] = {'20': 20}
        self.assertEqual(self.rate()['audit']['players'][10]['effective'][20], 120)

    def test_out_of_position_loses_task_value_but_fully_apt_secondary_role_does_not(self):
        before = self.rate()
        striker = self.team['player_list'][10]
        striker['parameters'][0] = 11
        self.assertEqual(self.rate()['attack'], before['attack'])
        striker['parameters'][strength.APTITUDE_INDEX[12]] = 1
        partial = self.rate()
        striker['parameters'][strength.APTITUDE_INDEX[12]] = 0
        absent = self.rate()
        self.assertLess(partial['attack'], before['attack'])
        self.assertLess(absent['attack'], partial['attack'])
        row = absent['audit']['contributions']['attack'][10]
        self.assertEqual(row['fit_multiplier'], .70)
        self.assertEqual(absent['audit']['players'][10]['effective'][20], before['audit']['players'][10]['effective'][20])

    def test_defensive_phase_aptitude_is_checked_independently(self):
        before = self.rate()
        # A LWF occupies LMF in the actual defensive formation.
        self.team['player_list'][8]['parameters'][strength.APTITUDE_INDEX[6]] = 0
        after = self.rate()
        self.assertEqual(after['attack'], before['attack'])
        self.assertLess(after['defence'], before['defence'])

    def test_stacked_bench_only_has_bounded_depth_effect(self):
        before = self.rate()
        for player in self.team['player_list'][11:]:
            for field in strength.ABILITIES:
                player['parameters'][field] = 120
            player['disp_overall'] = 127
        after = self.rate()
        for key in strength.METRIC_FIELDS:
            self.assertEqual(after[key], before[key])
        self.assertGreater(after['depth'], before['depth'])
        self.assertLessEqual(after['depth'] - before['depth'], 2.000001)
        replacements = after['audit']['depth']['replacements']
        self.assertEqual(len(replacements), 5)
        self.assertEqual(len({r['bench_order'] for r in replacements}), 5)
        self.assertEqual(len({r['slot'] for r in replacements}), 5)

    def test_illegal_bench_coverage_cannot_be_replaced_by_ovr(self):
        before = self.rate()
        for player in self.team['player_list'][11:]:
            player['parameters'][1:14] = [0] * 13
            player['disp_overall'] = 127
        after = self.rate()
        self.assertEqual(after['audit']['depth']['covered_replacements'], 0)
        self.assertLess(after['depth'], before['depth'])
        self.assertEqual(after['attack'], before['attack'])

    def test_team_name_and_displayed_overall_never_affect_ratings(self):
        before = self.rate()
        self.team['team_data'].update(team_name='Famous club', base_team_id=999)
        self.team[strength.TEAM_MARKER]['team_id'] = 999
        for player in self.team['player_list']:
            player['disp_overall'] = 1
            player['_overall'] = 127
        after = self.rate()
        for key in (*strength.METRIC_FIELDS, 'depth'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after['audit']['snapshot_sha256'], before['audit']['snapshot_sha256'])

    def test_actual_order_and_formation_coordinates_drive_task_contribution(self):
        self.team['player_list'][22]['parameters'][20] = 105
        before = self.rate()
        order = self.team['squad_data']['squad_gameplan']['match_plan_settings']['order']
        order[10], order[22] = order[22], order[10]
        after = self.rate()
        self.assertGreater(after['attack'], before['attack'])
        self.assertEqual(after['audit']['starting_order'][-1], 22)
        attack = self.team['squad_data']['squad_gameplan']['formation'][0]['formation_offensive']
        attack[10]['position_x'] -= 12
        shifted = self.rate()
        self.assertLess(shifted['attack'], after['attack'])
        self.assertEqual(shifted['audit']['contributions']['attack'][10]['coordinates']['position_x'], attack[10]['position_x'])

    def test_conditionals_are_explicit_and_unknown_boosters_fail_closed(self):
        self.doc['preview_boosters']['7'] = {'conditional': True, 'effects': {'20': 4, '15': -2}}
        self.team['player_list'][10]['parameters'][144] = 7
        result = self.rate()
        player = result['audit']['players'][10]
        self.assertEqual(player['effective'][20], displayed(70, 0, 0, factor(90)))
        self.assertEqual(player['effective'][15], displayed(70, -2, 0, factor(90)))
        self.assertFalse(player['player_boosters'][0]['active'])
        self.team['player_list'][10]['parameters'][144] = 999
        with self.assertRaisesRegex(ValueError, '真实增能定义'):
            self.rate()

    def test_native_first_penalty_taker_maps_physical_roster_to_actual_xi_without_reordering(self):
        settings = self.team['squad_data']['squad_gameplan']['match_plan_settings']
        settings['set_piece_taker'] = [4, 5, 6, 7, 8, 22]
        before = self.rate()
        self.assertEqual(before['audit']['penalty_plan']['native_first_taker_roster_index'], 22)
        self.assertFalse(before['audit']['penalty_plan']['native_first_taker_on_field'])
        self.assertIsNone(before['audit']['penalty_plan']['native_first_taker_starting_order'])
        settings['order'][3], settings['order'][22] = settings['order'][22], settings['order'][3]
        actual_order = copy.deepcopy(settings['order'])
        after = self.rate()
        plan = after['audit']['penalty_plan']
        self.assertEqual(plan['native_first_taker_starting_order'], 3)
        self.assertTrue(plan['native_first_taker_on_field'])
        self.assertEqual(plan['native_first_taker_gameplayer_id'], self.team['player_list'][22]['gameplayer_id'])
        self.assertEqual(after['audit']['starting_order'], actual_order[:11])
        self.assertEqual(settings['order'], actual_order)
        self.assertIsNone(plan['native_full_order'])
        self.assertFalse(plan['full_order_decoded'])
        settings['set_piece_taker'][5] = 10
        self.assertNotEqual(self.rate()['audit']['snapshot_sha256'], after['audit']['snapshot_sha256'])

    def test_missing_or_invalid_native_first_penalty_taker_remains_unknown(self):
        settings = self.team['squad_data']['squad_gameplan']['match_plan_settings']
        for value in (None, [], [0] * 5, [0] * 5 + [255], [0] * 5 + [True]):
            settings['set_piece_taker'] = value
            plan = self.rate()['audit']['penalty_plan']
            self.assertIsNone(plan['native_first_taker_roster_index'])
            self.assertFalse(plan['native_first_taker_on_field'])
            self.assertFalse(plan['full_order_decoded'])

    def test_scoring_never_mutates_inputs_and_is_replayable_after_json_roundtrip(self):
        before_team, before_doc = copy.deepcopy(self.team), copy.deepcopy(self.doc)
        result = self.rate()
        self.assertEqual(self.team, before_team)
        self.assertEqual(self.doc, before_doc)
        again = strength.ratings(json.loads(json.dumps(self.team)), document=json.loads(json.dumps(self.doc)))
        self.assertEqual(again, result)
        result['audit']['players'][0]['effective'][20] = -1
        self.assertEqual(self.rate()['audit']['players'][0]['effective'][20], 72)

    def test_invalid_or_incomplete_entry_snapshot_is_rejected(self):
        mutations = [
            lambda t: t['squad_data']['player_list'].pop(),
            lambda t: t['squad_data']['squad_gameplan']['match_plan_settings']['order'].__setitem__(0, 1),
            lambda t: t['player_list'][0]['parameters'].__setitem__(13, 3),
            lambda t: t['player_list'][0].pop('level_info'),
            lambda t: t['squad_data']['squad_gameplan']['formation'][0]['formation_defensive'].pop(),
            lambda t: t['squad_data']['squad_gameplan']['formation'][0].__setitem__('team_style', 99)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                team = copy.deepcopy(self.team)
                mutate(team)
                with self.assertRaises(ValueError):
                    self.rate(team)
        with self.assertRaisesRegex(ValueError, '真实增能上下文'):
            strength.ratings(self.team)


class GeneratorSnapshotTests(unittest.TestCase):
    def setUp(self):
        # Use the real ClubGenerator/Hungarian selection/training/assembly,
        # replacing only unavailable native-APK adapters.
        self.g, self.db, self.doc, proto = generator_fixture()
        self.addCleanup(self.db.close)
        with patch('ai_match_manager.prepare_strategies', return_value=None):
            self.team = self.g.build_club(self.db, proto, 121, rng=random.Random(19), cpu=True)

    def test_real_generator_snapshot_is_legal_and_freezes_effects_without_library_writes(self):
        before = list(self.db.iterdump())
        team_before = copy.deepcopy(self.team)
        with patch.object(self.g, 'prepared', side_effect=AssertionError('entry must never be retrained')):
            snapshot = strength.snapshot_for_ratings(self.team, self.g, self.db)
            result = strength.ratings(snapshot)
        self.assertEqual(len(snapshot['player_list']), 23)
        self.assertTrue(result['audit']['all_max_level'])
        self.assertTrue(all(row['fit_multiplier'] == 1 for rows in result['audit']['contributions'].values() for row in rows))
        for row in result['audit']['players']:
            self.assertEqual(row['ability_formula_applications'], 1)
            self.assertEqual(len(row['player_boosters']), 1)
        self.assertEqual(self.team, team_before)
        self.assertEqual(list(self.db.iterdump()), before)
        self.doc['preview_boosters']['7']['effects']['20'] = 20
        self.doc['division_squads']['coaches'][0]['effects'] = {'20': 20}
        self.assertEqual(strength.ratings(snapshot), result)
        self.assertEqual(strength.snapshot_for_ratings(snapshot, self.g, self.db), snapshot)
        self.assertEqual(strength.ratings(json.loads(json.dumps(snapshot))), result)
        with self.assertRaisesRegex(ValueError, '不能再覆盖'):
            strength.ratings(snapshot, document=self.doc)

    def test_accepted_owned_plan_and_actual_non_max_player_are_snapshotted_exactly(self):
        squad = copy.deepcopy(self.team['squad_data'])
        replacement = copy.deepcopy(self.team['player_list'][-1])
        replacement['gameplayer_id'] = {'id': 987654321, 'serial': 123}
        replacement['level_info'] = {'level': 4, 'level_limit': 35}
        replacement['parameters'][20] = 53
        squad['player_list'][-1]['gameplayer_id'] = copy.deepcopy(replacement['gameplayer_id'])
        order = squad['squad_gameplan']['match_plan_settings']['order']
        order[10], order[22] = order[22], order[10]
        saved_team = copy.deepcopy(self.team)
        snapshot = strength.snapshot_for_ratings(self.team, self.g, self.db, squad=squad,
                                                player_pool={(987654321, 123): replacement})
        result = strength.ratings(snapshot)
        self.assertEqual(result['audit']['players'][10]['gameplayer_id'], replacement['gameplayer_id'])
        self.assertEqual(result['audit']['players'][10]['base'][20], 53)
        self.assertTrue(result['audit']['actual_non_max_level'])
        self.assertEqual(snapshot[strength.CONTEXT]['parameters_stage'], 'trained-wire')
        self.assertEqual(self.team, saved_team)

    def test_effective_parameter_stage_prevents_reapplying_boosts(self):
        snapshot = strength.snapshot_for_ratings(self.team, self.g, self.db)
        original = strength.ratings(snapshot)
        for row in original['audit']['players']:
            player = snapshot['player_list'][row['roster_index']]
            for index, value in row['effective'].items():
                player['parameters'][index] = value
        snapshot[strength.CONTEXT]['parameters_stage'] = 'effective-abilities'
        replay = strength.ratings(snapshot)
        for metric in (*strength.METRIC_FIELDS, 'depth'):
            self.assertEqual(replay[metric], original[metric])
        self.assertTrue(all(row['ability_formula_applications'] == 0 for row in replay['audit']['players']))


if __name__ == '__main__':
    unittest.main()
