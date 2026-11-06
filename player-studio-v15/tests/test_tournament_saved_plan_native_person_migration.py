"""Legacy private plans cannot reintroduce two cards for one native person."""
import copy
import json
import unittest
from unittest.mock import patch

import tournament_runtime as runtime
from tournament_identity import native_person_key
import test_tournament_cached_roster_repair as fixtures


class SavedPlanNativePersonMigrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.CachedRosterRepairTests();self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.own=copy.deepcopy(self.f.active['home'])
        variant=copy.deepcopy(self.own['player_list'][0])
        variant['gameplayer_id']['id']|=1<<23
        cid=variant['gameplayer_id']['id'];raw=json.dumps(variant)
        self.f.db.execute('insert into managed_cards values(?,?,?)',(str(cid),raw,raw))
        self.f.doc['native_player_catalogue']['card_ids'].append(cid)
        self.f.owned=[variant]
        self.f.protected=(list(self.f.db.execute('select *from managed_cards')),
                          list(self.f.db.execute('select *from gameplayers')))
        self.bad=copy.deepcopy(self.own['squad_data'])
        self.bad['player_list'][1]['gameplayer_id']=variant['gameplayer_id'].copy()
        keys=[(p['gameplayer_id']['id'],p['gameplayer_id']['serial'])for p in self.bad['player_list']]
        self.assertEqual(len(set(keys)),23)
        self.assertEqual(len({native_person_key(cid)for cid,_ in keys}),22)
        self.assertTrue(set(keys)<=self.f.service.player_pool(self.f.db,self.f.definition,self.f.active).keys())

    def assert_repaired(self,active,game,run):
        self.assertEqual(active['home'],self.own)
        self.assertEqual(active['own_plan'],self.own['squad_data'])
        self.assertEqual((active['game_id'],self.f.current['run_id']),(game,run))
        backup=self.f.current['private_roster_repair_backups_v1'][str(game)+':own_plan']
        self.assertEqual(backup['original'],self.bad)
        self.assertEqual(backup['reasons'],['foreign_or_incomplete_saved_plan'])
        self.f.assert_protected()

    def test_active_legacy_duplicate_plan_repairs_without_redrawing_valid_private_team(self):
        self.f.active['own_plan']=copy.deepcopy(self.bad)
        game=self.f.active['game_id'];run=self.f.current['run_id']
        cpu=copy.deepcopy(self.f.active['away'])
        with patch.object(self.f.g,'build_club',side_effect=AssertionError('valid team redrawn')):
            reply=self.f.service.special(self.f.db,self.f.definition,self.f.current,{})
        self.assert_repaired(self.f.active,game,run)
        self.assertEqual(self.f.active['away'],cpu)
        self.assertEqual(reply['squad_data']['player_list'],self.own['squad_data']['player_list'])
        self.assertEqual(self.f.current['team_plans_v1']['54']['squad'],self.own['squad_data'])

    def test_saved_legacy_duplicate_plan_is_validated_after_restore_before_entry(self):
        runtime.remember_plan(self.f.current,self.f.active)
        self.f.current['team_plans_v1']['54']['squad']=copy.deepcopy(self.bad)
        game=self.f.active['game_id'];run=self.f.current['run_id']
        self.f.current.pop('active')
        with patch.object(self.f.g,'build_club',side_effect=AssertionError('valid saved team redrawn')):
            self.f.service.special(self.f.db,self.f.definition,self.f.current,{})
        self.assert_repaired(self.f.current['active'],game,run)
        self.assertEqual(self.f.current['team_plans_v1']['54']['squad'],self.own['squad_data'])


if __name__=='__main__':unittest.main()
