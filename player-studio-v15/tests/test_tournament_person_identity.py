"""Real native registration keys and isolated generator/SQLite regressions."""
import copy
import json
import random
import unittest
from unittest.mock import patch

import division_squads
import tournament_eligibility as eligibility
from tournament_identity import native_person_key, person, personal_identities
import test_tournament_fallback_squads as fallback_fixtures
from test_tournament_entry_qualification_native import native_person_key as native_instruction_key


class TournamentPersonIdentityTests(unittest.TestCase):
    def test_helper_matches_original_instruction_for_card_license_agent_and_namespace_bits(self):
        ids=(8496452,50439492,8491306,16879914,50434346,105644719968441,
             89137029898200,90000001,(0xabc<<52)|(0x45<<40)|(4000<<28)|50434346)
        for cid in ids:
            with self.subTest(card=cid):self.assertEqual(native_person_key(cid),native_instruction_key(cid))
        self.assertEqual(native_person_key(8496452),native_person_key(50439492))
        self.assertEqual(native_person_key(8491306),native_person_key(16879914))
        self.assertEqual(division_squads.person({'gameplayer_id':{'id':50439492}}),50439492)

    def test_private_metadata_and_wrong_binding_claim_cannot_split_native_duplicates(self):
        card={'gameplayer_id':{'id':50439492},'_studio_squad_person_id':999}
        self.assertEqual(person(card),107844)
        bound=(0x51<<40)|(4090<<28)|50439492
        doc={'players':[{'identity':{'card_id':bound,'bound_original_player_id':8496452,
                                     'independent_person_id':90000001,'previous_card_ids':[6]},
                         'owned':{'gameplayer_id':{'id':bound}}}]}
        out=personal_identities(doc)
        self.assertEqual(out[bound],native_instruction_key(bound));self.assertEqual(out[bound],107844)
        self.assertEqual(out[6],6,'metadata cannot make native card 6 become native person 1 or 107844')

    def test_variant_cards_do_not_turn_ten_people_into_eleven_random_candidates(self):
        fixtures=fallback_fixtures.FallbackSquadTests();g,db,doc,proto,cards=fixtures.fixture(10,2)
        try:
            expanded=[]
            for card in cards:
                for variant in(0,1<<23,3<<23):
                    c=copy.deepcopy(card);c['gameplayer_id']['id']+=variant;expanded.append(c)
                    raw=json.dumps(c);db.execute('insert or replace into managed_cards values(?,?,?)',(str(c['gameplayer_id']['id']),raw,raw))
            status=eligibility.inspect_cards(expanded)
            self.assertEqual(status['real_people'],10);self.assertFalse(status['random_eligible'])
            with self.assertRaisesRegex(ValueError,'10 名'):
                g.build_club(db,proto,121,rng=random.Random(9),cpu=False)
        finally:fixtures.doCleanups()

    def test_real_generator_deduplicates_license_variants_for_both_cpu_and_player(self):
        fixtures=fallback_fixtures.FallbackSquadTests();g,db,doc,proto,cards=fixtures.fixture(23,2)
        try:
            for card in cards:
                c=copy.deepcopy(card);c['gameplayer_id']['id']|=1<<23
                raw=json.dumps(c);db.execute('insert into managed_cards values(?,?,?)',(str(c['gameplayer_id']['id']),raw,raw))
            for cpu in(False,True):
                with patch('ai_match_manager.prepare_strategies',return_value=None):
                    out=g.build_club(db,proto,121,rng=random.Random(19),cpu=cpu)
                keys=[native_instruction_key(p['gameplayer_id']['id'])for p in out['player_list']]
                self.assertEqual(len(keys),23);self.assertEqual(len(set(keys)),23)
                self.assertEqual(out['_studio_tournament_squad']['native_person_keys'],keys)
        finally:fixtures.doCleanups()

if __name__=='__main__':unittest.main()
