"""Ranked league/group direct entrants bypass only the playoff phase."""
import json,sqlite3,unittest,uuid
import tournament_rules as rules
import tournament_runtime as runtime

def result(s,f):
    score=(2,0)if f['home']<f['away']else(0,2)
    rules.record(s,f['id'],*score,penalties=[5,4]if rules.needs_decision(s,f,score)else None)

class RankedPlayoffTests(unittest.TestCase):
    def stage_end(self,s):
        stage=s['stage_index']
        while not s['completed']and s['stage_index']==stage:
            f=rules.due(s)[0];result(s,f)

    def test_36_team_league_top8_bypass_ranks9_to24_playoff_then_join_last16(self):
        for legs in(1,2):
            with self.subTest(legs=legs):
                d={'uuid':str(uuid.uuid4()),'name':'36队','team_ids':list(range(1,37)),'player_team_id':1,
                    'stages':[{'type':'league','advance_per_group':8,'playoff_per_group':16},
                              {'type':'playoff','advance':8,'legs':legs},{'type':'knockout','advance':1}]}
                s=rules.start(d,17);self.stage_end(s)
                self.assertEqual(s['stage_index'],1);self.assertEqual(s['bypass'],list(range(1,9)))
                fixtures=[f for f in s['fixtures']if f['stage']==1]
                self.assertEqual({v for f in fixtures for v in(f['home'],f['away'])},set(range(9,25)))
                first_legs=[(f['home'],f['away'])for f in fixtures if f['leg']==1]
                self.assertEqual(first_legs,[(i,33-i)for i in range(9,17)])
                # The same edition survives JSON persistence before playoffs.
                run=s['run_id'];s=rules.State(json.loads(json.dumps(s)))
                self.stage_end(s)
                self.assertEqual(s['run_id'],run);self.assertEqual(s['stage_index'],2)
                self.assertEqual(set(s['entrants']),set(range(1,17)));self.assertEqual(s['bypass'],[])
                while not s['completed']:result(s,rules.due(s)[0])
                self.assertEqual(s['champion'],1)

    def test_group_rank_intervals_and_direct_entrants_rejoin_after_playoff(self):
        d={'uuid':str(uuid.uuid4()),'name':'分组','team_ids':list(range(1,13)),'player_team_id':1,
           'stages':[{'type':'groups','groups':4,'advance_per_group':1,'playoff_per_group':2},
                     {'type':'playoff','advance':4,'legs':2},{'type':'knockout','advance':1}]}
        s=rules.start(d,29);self.stage_end(s)
        tables=s['stage_history'][0]['tables']
        direct={t[0]['team']for t in tables};play={r['team']for t in tables for r in t[1:3]}
        self.assertEqual(set(s['bypass']),direct)
        self.assertEqual(set(s['entrants']),play);self.assertFalse(direct&play)
        self.assertEqual({v for f in s['fixtures']if f['stage']==1 for v in(f['home'],f['away'])},play)
        self.stage_end(s)
        self.assertTrue(direct<=set(s['entrants']));self.assertEqual(len(s['entrants']),8)
        while not s['completed']:result(s,rules.due(s)[0])
        self.assertEqual(s['champion'],1)

    def test_native_entry_routing_skips_cpu_playoffs_for_direct_entrant_only(self):
        for player in(1,9,24):
            d={'uuid':str(uuid.uuid4()),'name':'入口线路','team_ids':list(range(1,37)),'player_team_id':player,
               'stages':[{'type':'league','advance_per_group':8,'playoff_per_group':16},
                         {'type':'playoff','advance':8,'legs':2},{'type':'knockout'}]}
            s=rules.start(d,17);self.stage_end(s)
            fixture=runtime.next_fixture(s,lambda f:result(s,f))
            self.assertIn(player,(fixture['home'],fixture['away']))
            self.assertEqual(fixture['stage'],2 if player==1 else 1)
            if player==1:self.assertTrue(all(f['played']for f in s['fixtures']if f['stage']==1))

if __name__=='__main__':unittest.main()
