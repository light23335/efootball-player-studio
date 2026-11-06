"""Authoritative club/country sources, never the client's painted team fields."""
import copy
import json
import sqlite3
import unittest

from tournament_squads import (authoritative_membership, belongs_to_team,
                               membership_evidence, membership_index)


def source(cid, nation=7, club=103, national=0):
    return {'gameplayer_id': {'id': cid, 'serial': 0}, 'parameters': [0] * 147,
            '_nation_id': nation, 'initial_base_team_id': club,
            'initial_base_national_team_id': national}


class MembershipAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table managed_cards(card_id text primary key,payload text)')
        self.doc = {'players': [], 'native_player_catalogue': {'version': 1, 'card_ids': list(range(1, 12))},
                    'tournament_national_team_nations': {'54': 7, '49206': 7, '7': 16, '50007': 16,
                                                       '20': 9, '82020': 9}}
        for p in (source(1), source(2, 16, 108), source(3, 16, 54, 49206), source(9, 0, 0, 54)):
            self.put(p)

    def put(self, p):
        self.db.execute('insert or replace into managed_cards values(?,?)',
                        (str(p['gameplayer_id']['id']), json.dumps(p)))

    def painted(self, cid, nation=7):
        return dict(source(cid, nation, 54, 49206), type='RENTAL')

    def test_wire_country_loss_and_wrong_display_club_do_not_reject_actual_chinese_card(self):
        wire = self.painted(1);wire.pop('_nation_id');wire['initial_base_team_id'] = 7
        index = membership_index(self.doc)
        for team in (54, 49206):
            self.assertTrue(authoritative_membership(self.db, self.doc, wire, team, index=index))
            evidence = membership_evidence(self.db, self.doc, wire, team, index=index)
            self.assertEqual((evidence['source'], evidence['nation_id'], evidence['club_id']), ('managed_cards', 7, 103))

    def test_painted_foreign_owned_and_rental_fields_cannot_make_a_chinese_candidate(self):
        for cid in (2, 3):
            for team in (54, 49206):
                wire = self.painted(cid)
                self.assertFalse(authoritative_membership(self.db, self.doc, wire, team))
                self.assertEqual(membership_evidence(self.db, self.doc, wire, team)['reason'], 'source_country_mismatch')
        self.assertFalse(belongs_to_team(source(3, 16, 54, 49206), 54, 7, {54, 49206}))

    def test_all_country_alias_families_use_the_same_real_country_without_cross_leak(self):
        self.doc['tournament_standard_cards'] = {'5': source(5, 9, 999)}
        index = membership_index(self.doc)
        countries = {1: 7, 2: 16, 5: 9}
        for team, nation in self.doc['tournament_national_team_nations'].items():
            accepted = {cid for cid in countries if authoritative_membership(self.db, self.doc, self.painted(cid), int(team), index=index)}
            self.assertEqual(accepted, {cid for cid, country in countries.items() if country == nation})

    def test_both_real_standard_containers_resolve_wire_only_cards(self):
        self.doc['tournament_standard_cards'] = {'4': source(4)}
        self.doc['tournament_fallback_standard_cards'] = {'5': source(5, 9)}
        self.assertTrue(authoritative_membership(self.db, self.doc, self.painted(4, 16), 54))
        self.assertTrue(authoritative_membership(self.db, self.doc, self.painted(5, 16), 82020))
        self.assertEqual(membership_evidence(self.db, self.doc, self.painted(5), 82020)['source'], 'native_standard_extension')

    def test_original_standard_country_fills_only_missing_managed_country(self):
        self.put(source(4, 0, 103))
        self.doc['tournament_standard_cards'] = {'4': source(4, 7, 103), '2': source(2, 7, 108)}
        self.assertTrue(authoritative_membership(self.db, self.doc, self.painted(4, 16), 54))
        self.assertEqual(membership_evidence(self.db, self.doc, self.painted(4), 54)['source'], 'managed_cards+standards_country')
        self.assertFalse(authoritative_membership(self.db, self.doc, self.painted(2), 54), 'explicit source Country is never overwritten')

    def test_current_compiled_diy_precedes_stale_source_and_respects_include_switch_and_binding(self):
        self.put(source(6, 16))
        self.put(source(7, 7))
        self.doc['players'] = [{'identity': {'card_id': 6, 'previous_card_ids': [6, 7],
                                           'package_id': 'current-diy', 'bound_original_player_id': 1},
                                'owned': dict(source(6), _personal_player_uuid='current-diy')}]
        index = membership_index(self.doc)
        evidence = membership_evidence(self.db, self.doc, self.painted(6, 16), 54, index=index)
        self.assertTrue(evidence['belongs']);self.assertEqual(evidence['source'], 'compiled_diy')
        # A stale binding claim cannot override the actual compiled card's
        # native person key. Card 6 is not an actual native binding to person 1.
        self.assertEqual(evidence['person_id'], 6)
        for cid in (6, 7):
            self.assertFalse(authoritative_membership(self.db, self.doc, self.painted(cid), 54, False, index=index))
            self.assertEqual(membership_evidence(self.db, self.doc, self.painted(cid), 54, False, index=index)['reason'], 'diy_disabled')

    def test_current_native_index_with_missing_or_invalid_source_fails_closed(self):
        for raw in ('bad-json', '[]', json.dumps(source(999))):
            self.db.execute('insert or replace into managed_cards values(?,?)', ('8', raw))
            evidence = membership_evidence(self.db, self.doc, self.painted(8), 54)
            self.assertFalse(evidence['belongs']);self.assertEqual(evidence['reason'], 'source_missing')
        self.doc['native_player_catalogue']['card_ids'] = [2]
        self.assertEqual(membership_evidence(self.db, self.doc, self.painted(1), 54)['reason'], 'not_in_current_native_catalogue')

    def test_legacy_without_source_needs_actual_country_not_just_representative_club(self):
        legacy = {'players': [], 'tournament_national_team_nations': self.doc['tournament_national_team_nations']}
        wire = self.painted(8);wire.pop('_nation_id')
        self.assertFalse(authoritative_membership(self.db, legacy, wire, 54))
        self.assertEqual(membership_evidence(self.db, legacy, wire, 54)['reason'], 'unproven_nationality')
        wire['_nation_id'] = 16
        self.assertFalse(authoritative_membership(self.db, legacy, wire, 54))
        wire['_nation_id'] = 7
        self.assertTrue(authoritative_membership(self.db, legacy, wire, 54))

    def test_native_national_reference_is_only_a_trusted_missing_country_fallback(self):
        for team in (54, 49206):
            self.assertTrue(authoritative_membership(self.db, self.doc, self.painted(9, 16), team))
        self.put(source(9, 16, 0, 54))
        self.assertFalse(authoritative_membership(self.db, self.doc, self.painted(9), 54))

    def test_club_membership_uses_source_team_and_projection_never_mutates_any_input(self):
        wire = self.painted(1)
        before = copy.deepcopy((self.doc, wire));rows = list(self.db.iterdump())
        self.assertTrue(authoritative_membership(self.db, self.doc, wire, 103))
        self.assertFalse(authoritative_membership(self.db, self.doc, wire, 108))
        self.assertEqual((self.doc, wire), before)
        self.assertEqual(list(self.db.iterdump()), rows)


if __name__ == '__main__':unittest.main()
