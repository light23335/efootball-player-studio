"""Real generator/SQLite fixtures; no application launch or user's databases."""
import copy
import json
import random
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tournament_eligibility as eligibility
from tournament_squads import export_fallback_standard_cards, standard_bench_cards, person, APTITUDE_INDEX
from tournament_sim_strength import ratings, snapshot_for_ratings
from test_tournament_sim_strength import generator_fixture, team_snapshot


class Borrowed:
    def __init__(self, db, calls=None): self.db, self.calls = db, calls
    def execute(self, *args):
        if self.calls is not None: self.calls.append(args[0])
        return self.db.execute(*args)
    def close(self): pass


def native_card(cid, role=1, team=121, keeper=False, no_backs=False):
    player = copy.deepcopy(team_snapshot()['player_list'][0])
    player['gameplayer_id'] = {'id': cid, 'serial': 0}
    player['parameters'] = player['parameters'][:147]
    player['parameters'][0] = 0 if keeper else role
    player['parameters'][1:14] = [0] * 13
    for pos, index in enumerate(APTITUDE_INDEX):
        player['parameters'][index] = 2 if (pos == 0) == keeper else 0
        if no_backs and pos in (2, 3): player['parameters'][index] = 0
    player['parameters'][144:147] = [0, 136, 0]
    player['initial_base_team_id'] = team
    player['_nation_id'] = 7
    player['level_info'] = {'level': 1, 'level_limit': 3}
    return player


class FallbackSquadTests(unittest.TestCase):
    def fixture(self, count, keepers=0, no_backs=False):
        g, db, doc, proto = generator_fixture()
        self.addCleanup(db.close)
        db.execute('delete from managed_cards')
        original = []
        for i in range(count):
            card = native_card(1000+i, keeper=i < keepers, no_backs=no_backs)
            original.append(copy.deepcopy(card))
            raw = json.dumps(card)
            db.execute('insert into managed_cards values(?,?,?)', (str(1000+i), raw, raw))
        payload = copy.deepcopy(doc['division_squads']['coaches'][0]['payload'])
        db.execute('insert into coaches values(?,?,?)', (payload['coach_id']['id'], 0, json.dumps(payload)))
        standards = {}
        for i in range(32):
            card = native_card(8000+i, team=999, keeper=i < 2)
            card['level_info'] = {'level': 1, 'level_limit': 35}
            card['_studio_tournament_source_card_type'] = 'Standard'
            # Foreign high abilities must never win an initial XI cost.
            for stat in range(14, 41):
                if stat != 33: card['parameters'][stat] = 100
            standards[str(8000+i)] = card
        duplicate = copy.deepcopy(standards['8010'])
        duplicate['gameplayer_id']['id'] = (1 << 28) + 1000
        standards[str(duplicate['gameplayer_id']['id'])] = duplicate
        doc['tournament_fallback_standard_cards'] = standards
        db.commit()
        return g, db, doc, proto, original

    def build(self, g, db, proto, seed=17, cpu=True, real_coach=False):
        if real_coach:
            return g.build_club(db, proto, 121, rng=random.Random(seed), cpu=cpu)
        with patch('ai_match_manager.prepare_strategies', return_value=None):
            return g.build_club(db, proto, 121, rng=random.Random(seed), cpu=cpu)

    def assert_private_contract(self, result, original, cpu):
        players = result['player_list']; fallback = result['_studio_tournament_squad']['fallback']
        self.assertEqual(len(players), 23)
        self.assertEqual(len({person(p) for p in players}), 23)
        source = {p['gameplayer_id']['id']: p for p in original}
        self.assertTrue(all(p['gameplayer_id']['id'] in source for p in players[:11]))
        self.assertTrue(all(p['level_info']['level'] == p['level_info']['level_limit'] for p in players))
        self.assertEqual(fallback['original_person_count'], len(original))
        self.assertEqual(len(fallback['added_standard_card_ids']), max(0, 23-len(original)))
        self.assertTrue(all(p['parameters'][1:14] == source[p['gameplayer_id']['id']]['parameters'][1:14]
                            for p in players if p['gameplayer_id']['id'] in source))
        self.assertTrue(all(p['gameplayer_id']['serial'] != 0 if cpu else p['gameplayer_id']['serial'] == 0 and p['type'] == 'RENTAL'
                            for p in players))
        for row in fallback['players']:
            self.assertEqual(row['aptitudes'], [players[row['roster_index']]['parameters'][i] for i in APTITUDE_INDEX])

    def test_eleven_twelve_and_twenty_two_real_people_zero_or_one_keeper_both_sides(self):
        for count, keepers in ((11, 0), (12, 1), (22, 1)):
            for cpu in (True, False):
                with self.subTest(count=count, keepers=keepers, cpu=cpu):
                    g, db, doc, proto, original = self.fixture(count, keepers)
                    before = list(db.iterdump())
                    result = self.build(g, db, proto, cpu=cpu)
                    self.assert_private_contract(result, original, cpu)
                    goalie = next(r for r in result['_studio_tournament_squad']['fallback']['players'][:11] if r['attack_role'] == 0)
                    self.assertEqual(goalie['attack_aptitude'], 2 if keepers else 0)
                    self.assertEqual(list(db.iterdump()), before)
                    score = ratings(snapshot_for_ratings(result, g, db))
                    self.assertTrue(score['audit']['all_max_level'])
                    self.assertEqual(score['audit']['players'][0]['ability_formula_applications'], 1)

    def test_strict_legal_twenty_three_never_enables_fallback_or_adds_foreign_people(self):
        g, db, doc, proto, original = self.fixture(23, 2)
        result = self.build(g, db, proto)
        self.assertNotIn('fallback', result['_studio_tournament_squad'])
        self.assertEqual({person(p) for p in result['player_list']}, {person(p) for p in original})
        for i, p in enumerate(result['player_list'][:11]):
            meta = result['_studio_tournament_squad']
            self.assertEqual(p['parameters'][APTITUDE_INDEX[meta['attack_roles'][i]]], 2)
            self.assertEqual(p['parameters'][APTITUDE_INDEX[meta['defence_roles'][i]]], 2)

    def test_twenty_three_with_single_keeper_or_missing_backs_relaxes_only_when_needed(self):
        for keepers, no_backs in ((1, False), (2, True)):
            with self.subTest(keepers=keepers, no_backs=no_backs):
                g, db, doc, proto, original = self.fixture(23, keepers, no_backs)
                result = self.build(g, db, proto)
                self.assert_private_contract(result, original, True)
                self.assertEqual(result['_studio_tournament_squad']['fallback']['added_standard_card_ids'], [])
                if no_backs:
                    self.assertTrue(any(row['attack_role'] in (2, 3) or row['defence_role'] in (2, 3)
                                        for row in result['_studio_tournament_squad']['fallback']['out_of_position_starters']))

    def test_strict_reserve_keeper_can_use_a_lower_ovr_variant_of_the_same_real_person(self):
        g, db, doc, proto, original = self.fixture(23, 2)
        for source in original[:2]:
            variant = copy.deepcopy(source)
            variant['gameplayer_id']['id'] += 1 << 28
            variant['parameters'][0] = 12
            variant['parameters'][1:14] = [2] * 13
            variant['parameters'][APTITUDE_INDEX[0]] = 0
            for stat in range(14, 41):
                if stat != 33: variant['parameters'][stat] = 100
            raw = json.dumps(variant)
            db.execute('insert into managed_cards values(?,?,?)', (str(variant['gameplayer_id']['id']), raw, raw))
        result = self.build(g, db, proto)
        self.assertNotIn('fallback', result['_studio_tournament_squad'])
        self.assertEqual(len({person(p) for p in result['player_list']}), 23)
        self.assertTrue(any(p['parameters'][APTITUDE_INDEX[0]] == 2 for p in result['player_list'][11:]))

    def test_familiar_position_wins_over_high_ability_out_of_position_player(self):
        g, db, doc, proto, original = self.fixture(11)
        for _, raw in list(db.execute('select card_id,payload from managed_cards')):
            player = json.loads(raw)
            player['parameters'][APTITUDE_INDEX[2]] = 2 if player['gameplayer_id']['id'] == 1000 else 0
            for stat in range(14, 41):
                if stat != 33: player['parameters'][stat] = 40 if player['gameplayer_id']['id'] == 1000 else 100
            db.execute('update managed_cards set payload=? where card_id=?', (json.dumps(player), str(player['gameplayer_id']['id'])))
        result = self.build(g, db, proto)
        left_back = [row for row in result['_studio_tournament_squad']['fallback']['players'][:11]
                     if row['attack_role'] == 2 or row['defence_role'] == 2]
        self.assertEqual(len(left_back), 1)
        self.assertEqual(left_back[0]['gameplayer_id']['id'], 1000)

    def test_partial_goalkeeper_is_preferred_without_rewriting_aptitude_to_full(self):
        g, db, doc, proto, original = self.fixture(11)
        partial = copy.deepcopy(original[-1])
        partial['parameters'][APTITUDE_INDEX[0]] = 1
        db.execute('update managed_cards set payload=? where card_id=?', (json.dumps(partial), str(partial['gameplayer_id']['id'])))
        result = self.build(g, db, proto)
        keeper = next(row for row in result['_studio_tournament_squad']['fallback']['players'][:11] if row['attack_role'] == 0)
        self.assertEqual(keeper['gameplayer_id']['id'], partial['gameplayer_id']['id'])
        self.assertEqual(keeper['attack_aptitude'], 1)
        self.assertEqual(result['player_list'][keeper['roster_index']]['parameters'][APTITUDE_INDEX[0]], 1)

    def test_seeded_reentry_and_json_snapshot_keep_exact_bench_abilities_and_effects(self):
        g, db, doc, proto, original = self.fixture(11)
        before = copy.deepcopy(doc)
        first = self.build(g, db, proto, seed=70)
        second = self.build(g, db, proto, seed=70)
        self.assertEqual(first, second)
        different = self.build(g, db, proto, seed=71)
        self.assertNotEqual(first['_studio_tournament_squad']['fallback']['added_standard_card_ids'],
                            different['_studio_tournament_squad']['fallback']['added_standard_card_ids'])
        self.assertEqual(doc, before)
        snapshot = snapshot_for_ratings(first, g, db)
        self.assertEqual(ratings(snapshot), ratings(json.loads(json.dumps(snapshot))))
        for player in snapshot['player_list']:
            self.assertEqual(len(player['parameters']), 149)
            self.assertEqual(len(set(player['parameters'][144:147]) - {0, 136}), 1)

    def test_fewer_than_eleven_distinct_team_people_rejects_despite_foreign_standard_pool(self):
        g, db, doc, proto, original = self.fixture(10)
        duplicate = copy.deepcopy(original[0]); duplicate['gameplayer_id']['id'] += 1 << 28
        db.execute('insert into managed_cards values(?,?,?)', (str(duplicate['gameplayer_id']['id']), 'variant', json.dumps(duplicate)))
        for cpu in (True, False):
            with self.subTest(cpu=cpu), self.assertRaisesRegex(ValueError, '10.*11人首发'):
                self.build(g, db, proto, cpu=cpu)

    def test_missing_verified_standard_pool_rejects_without_fabricating_cards(self):
        g, db, doc, proto, original = self.fixture(11)
        doc.pop('tournament_fallback_standard_cards')
        with self.assertRaisesRegex(ValueError, '有效Standard普卡不足'):
            self.build(g, db, proto)

    def test_same_country_cards_form_the_real_xi_even_when_club_ids_differ(self):
        g, db, doc, proto, original = self.fixture(12, 1)
        doc['tournament_national_team_nations'] = {'121': 7, '50121': 7}
        for _, raw in list(db.execute('select card_id,payload from managed_cards')):
            p = json.loads(raw);p['initial_base_team_id'] = 333
            db.execute('update managed_cards set payload=? where card_id=?', (json.dumps(p), str(p['gameplayer_id']['id'])))
        result = self.build(g, db, proto)
        self.assert_private_contract(result, original, True)
        self.assertTrue(all(p['_nation_id'] == 7 for p in result['player_list'][:11]))

    def test_actual_coaching_preflight_carries_only_tournament_flag_without_aptitude_rewrite(self):
        g, db, doc, proto, original = self.fixture(11)
        result = self.build(g, db, proto, real_coach=True)
        spec = result['_studio_tournament_squad']['tactical_spec']
        self.assertTrue(spec['tournament_fallback']['allow_incomplete_aptitude'])
        self.assertEqual(spec['tournament_fallback']['original_person_count'], 11)
        for i, player in enumerate(spec['players']):
            self.assertEqual(player['parameters'][1:14], result['player_list'][i]['parameters'][1:14])
            self.assertTrue(all(value > 0 for value in player['ratings']))
        saved = copy.deepcopy(result['player_list'])
        result['_studio_tournament_squad'].pop('booster_revision')
        self.assertTrue(g.repair_cpu_boosters(result, 71, db))
        self.assertEqual(result['player_list'], saved)
        self.assertTrue(all(value > 0 for p in spec['players'] for value in p['ratings']))
        self.assertFalse(g.repair_cpu_boosters(result, 72, db))


class EligibilityInspectionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table players(id,payload,card_type)')
        for i in range(10):
            p = native_card(1000+i)
            self.db.execute('insert into players values(?,?,?)', (str(1000+i), json.dumps(p), 'Standard'))
        self.calls = []
        self.library = types.SimpleNamespace(db=lambda: Borrowed(self.db, self.calls), identities=lambda: {
            'team': [{'id': 121}, {'id': 999}], 'nation': [{'id': 7, 'name': 'Country'}]})
        self.doc = {'players': []}

    def project(self, package='one', **identity):
        return {'package_id': package, 'identity': {'team_id': 121, 'nation_id': 7, **identity},
                'position_aptitudes': dict.fromkeys(eligibility.ROLE_NAMES, 2)}

    def test_insufficient_manual_and_export_allowed_but_random_needs_eleven(self):
        status = eligibility.eligible_teams(self.library, self.doc)['121']
        self.assertEqual(status['source_people'], 10)
        self.assertFalse(status['random_eligible'])
        self.assertTrue(status['manual_allowed']);self.assertTrue(status['export_allowed'])
        self.assertTrue(status['warning'])

    def test_pending_local_projects_dedupe_packages_original_binding_and_diy_switch(self):
        project = self.project()
        self.doc['tournament_local_projects'] = [project, copy.deepcopy(project)]
        index = eligibility.load_eligibility_index(self.library, self.doc)
        for cpu in (True, False):
            current = eligibility.eligible_teams(self.library, self.doc, cpu=cpu, index=index)['121']
            no_diy = eligibility.eligible_teams(self.library, self.doc, cpu=cpu, include_diy=False, index=index)['121']
            self.assertEqual((current['source_people'], current['current_people'], current['local_pending_export']), (10, 11, 1))
            self.assertTrue(current['random_eligible']);self.assertFalse(no_diy['random_eligible'])
        self.assertEqual(len(self.calls), 1, 'four catalogue modes reuse one parsed library')
        self.doc['tournament_local_projects'] = [project]
        project['identity'].update(bind_original_player=True, original_player_id='1000')
        bound = eligibility.eligible_teams(self.library, self.doc)['121']
        self.assertEqual(bound['current_people'], 10)
        project['identity'].pop('original_player_id');project['source_player'] = {'id': '1000'}
        self.assertEqual(eligibility.eligible_teams(self.library, self.doc)['121']['current_people'], 10)

    def test_edited_compiled_package_replaces_its_old_inspection_membership(self):
        owned = native_card(999000, team=999)
        self.doc['players'] = [{'identity': {'package_id': 'one', 'card_id': 999000}, 'owned': owned}]
        self.doc['tournament_local_projects'] = [self.project()]
        result = eligibility.eligible_teams(self.library, self.doc)
        self.assertEqual(result['121']['current_people'], 11)
        self.assertEqual(result['999']['current_people'], 0)
        self.assertEqual(self.doc['players'][0]['owned']['initial_base_team_id'], 999)

    def test_country_aliases_and_unknown_local_nation_use_real_country_lookup(self):
        self.doc['tournament_national_team_nations'] = {'999': 7}
        project = self.project();project['identity'].pop('nation_id');project['identity']['nationality'] = 'Country'
        self.doc['tournament_local_projects'] = [project]
        result = eligibility.eligible_teams(self.library, self.doc)
        self.assertEqual(result['999']['current_people'], 11)
        self.assertTrue(result['999']['random_eligible'])

    def test_global_standard_export_uses_real_kind_native_id_and_caps_once_without_source_writes(self):
        p = native_card(2000, team=999);p['level_info']['level_limit'] = None
        epic = native_card(3000, team=999)
        self.db.execute('insert into players values(?,?,?)', ('2000', json.dumps(p), 'Standard'))
        self.db.execute('insert into players values(?,?,?)', ('3000', json.dumps(epic), 'Epic'))
        document = {'players': [], 'tournaments': [{'team_ids': [121]}],
                    'native_player_catalogue': {'version': 1, 'card_ids': [*range(1000, 1010), 2000, 3000]}}
        before = list(self.db.iterdump())
        pool = export_fallback_standard_cards(self.library, document)
        self.assertIn('2000', pool);self.assertNotIn('3000', pool)
        self.assertEqual(pool['2000']['level_info']['level_limit'], 35)
        self.assertEqual(pool['2000']['parameters'], p['parameters'])
        self.assertTrue(all(p['_studio_tournament_source_card_type'] == 'Standard' for p in pool.values()))
        self.assertEqual(list(self.db.iterdump()), before)

    def test_global_pool_reuses_existing_standard_payloads_without_repeating_them(self):
        document = {'players': [], 'tournaments': [{'team_ids': [121]}]}
        full = export_fallback_standard_cards(self.library, document)
        existing = {cid: copy.deepcopy(full[cid]) for cid in ('1000', '1001')}
        for p in existing.values():p.pop('_studio_tournament_source_card_type')
        document['tournament_standard_cards'] = existing
        document['tournament_fallback_standard_cards'] = export_fallback_standard_cards(self.library, document)
        self.assertEqual(set(document['tournament_fallback_standard_cards']), set(full)-set(existing))
        before = copy.deepcopy(document)
        candidates = standard_bench_cards(self.db, document)
        self.assertEqual({str(p['gameplayer_id']['id']) for p in candidates}, set(full))
        self.assertEqual(document, before)
        document['tournament_standard_cards'] = copy.deepcopy(full)
        self.assertEqual(export_fallback_standard_cards(self.library, document), {})


if __name__ == '__main__':unittest.main()
