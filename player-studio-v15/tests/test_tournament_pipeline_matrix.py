"""Editor rules -> fixture scheduling -> native rule projection -> advancement."""
import copy,itertools,json,sqlite3,unittest,uuid
import tournament_rules as rules
import tournament_runtime as runtime

def competition(teams=4,stages=None,**options):
    return dict(uuid=str(uuid.uuid4()),name='Pipeline Cup',enabled=True,team_ids=list(range(1,teams+1)),
                player_team_id=1,stages=stages or[{'type':'knockout'}],**options)

class TournamentPipelineMatrixTests(unittest.TestCase):
    projection_cases=0
    def test_knockout_and_playoff_projection_all_legs_extra_time_away_goal_and_difficulty_options(self):
        cases=0
        for kind,legs,extra,away,away_extra,coaching,level in itertools.product(
                ('knockout','playoff'),(1,2),(False,True),(False,True),(False,True),(False,True),rules.DIFFICULTIES):
            stage={'type':kind,'legs':legs,'extra_time':extra,'away_goals':away,'away_goals_extra_time':away_extra}
            stages=[stage]+([{'type':'knockout'}]if kind=='playoff'else[])
            s=rules.start(competition(stages=stages,difficulty=level,auto_coaching=coaching),7)
            first=rules.due(s)[0];native=runtime.native_rules(s,first);env=runtime.match_environment(s,first)
            self.assertEqual(native['prior_goals'],[0,0]);self.assertEqual(env['cpu_level'],level)
            self.assertEqual(native['extra_time'],extra if legs==1 else False)
            self.assertEqual(native['penalties'],legs==1);self.assertEqual(native['first_leg'],legs==2)
            self.assertEqual(native['away_goals'],False)
            self.assertEqual(env['exTime'],'YES'if native['extra_time']else'NO')
            self.assertEqual(env['pk'],'YES'if native['penalties']else'NO')
            if legs==2:
                self.assertFalse(rules.needs_decision(s,first,[0,0]))
                rules.record(s,first['id'],1,0)
                second=next(f for f in s['fixtures']if f.get('tie')==first['tie']and f['leg']==2)
                native=runtime.native_rules(s,second);env=runtime.match_environment(s,second)
                self.assertTrue(native['second_leg']);self.assertFalse(native['first_leg'])
                self.assertEqual(native['prior_goals'],[0,1]);self.assertEqual(native['extra_time'],extra)
                self.assertTrue(native['penalties']);self.assertEqual(native['away_goals'],away)
                self.assertEqual(env['exTime'],'YES'if extra else'NO');self.assertEqual(env['pk'],'YES')
                self.assertTrue(rules.needs_decision(s,second,[1,0]))
            cases+=1
        type(self).projection_cases=cases
        self.assertEqual(cases,448)

    def test_league_and_groups_all_rounds_allow_draw_without_extra_time_or_penalties(self):
        for kind,cycles,level in itertools.product(('league','groups'),(1,2),rules.DIFFICULTIES):
            stage={'type':kind,'cycles':cycles,'advance_per_group':1}
            if kind=='groups':stage.update(groups=2)
            stages=[stage]+([{'type':'knockout'}]if kind=='groups'else[])
            s=rules.start(competition(8,stages,difficulty=level),9)
            for f in list(s['fixtures']):
                native=runtime.native_rules(s,f);env=runtime.match_environment(s,f)
                self.assertFalse(native['extra_time']);self.assertFalse(native['penalties'])
                self.assertEqual((env['exTime'],env['pk']),('NO','NO'))
            while not s['completed']and s['stage_index']==0:
                due=rules.due(s)
                if not due:rules.advance(s);continue
                f=due[0];self.assertFalse(rules.needs_decision(s,f,[0,0]));rules.record(s,f['id'],0,0)
            self.assertTrue(s['completed']if kind=='league'else s['stage_index']==1)

    def test_round_override_final_changes_native_rules_only_for_that_round(self):
        s=rules.start(competition(4,[{'type':'knockout','legs':2,'extra_time':False,
            'round_overrides':{'2':{'legs':1,'extra_time':True,'neutral':True}}}]),5)
        while s['knockout_size']>2:
            f=rules.due(s)[0];score=[2,1]
            self.assertFalse(runtime.native_rules(s,f)['extra_time'])
            rules.record(s,f['id'],*score,penalties=[5,4]if rules.needs_decision(s,f,score)else None)
        final=rules.due(s)[0]
        self.assertEqual(final['legs'],1);self.assertTrue(final['neutral'])
        self.assertTrue(runtime.native_rules(s,final)['extra_time']);self.assertEqual(runtime.match_environment(s,final)['exTime'],'YES')

    def test_full_stage_paths_resume_from_saved_json_and_keep_duplicate_results_idempotent(self):
        paths=[(5,[{'type':'league','cycles':2,'advance_per_group':1}]),
               (12,[{'type':'groups','groups':4,'advance_per_group':1,'playoff_per_group':2},
                    {'type':'playoff','advance':4,'legs':2},{'type':'knockout','legs':1}]),
               (16,[{'type':'groups','groups':4,'advance_per_group':2},{'type':'knockout','legs':2}]),
               (31,[{'type':'knockout','legs':2}]),(128,[{'type':'knockout','legs':1}])]
        for count,stages in paths:
            with self.subTest(count=count,stages=stages):
                db=sqlite3.connect(':memory:')
                try:
                    db.execute('create table meta(key primary key,value)');runtime.put(db,'unrelated',{'wins':8,'XP':90000});db.commit()
                    s=rules.start(competition(count,stages),77);played=0
                    while not s['completed']:
                        due=rules.due(s)
                        if not due:rules.advance(s);continue
                        f=due[0];score=[2,1];pk=[5,4]if rules.needs_decision(s,f,score)else None
                        self.assertTrue(rules.record(s,f['id'],*score,penalties=pk));played+=1
                        before=copy.deepcopy(s)
                        self.assertFalse(rules.record(s,f['id'],*score,penalties=pk));self.assertEqual(s,before)
                        with db:runtime.put(db,'competition',s)
                        s=runtime.get(db,'competition')
                        self.assertEqual(runtime.get(db,'unrelated'),{'wins':8,'XP':90000})
                        self.assertLess(played,3000)
                    self.assertIn(s['champion'],range(1,count+1));self.assertTrue(s['completed'])
                finally:db.close()

    def test_impossible_decider_rules_are_rejected_before_export(self):
        for stage in ({'type':'knockout','penalties':False},{'type':'playoff','extra_time':False,'penalties':False},
                      {'type':'knockout','round_overrides':{'2':{'penalties':False}}}):
            with self.assertRaises(ValueError):rules.normalize(competition(stages=[stage]))

if __name__=='__main__':unittest.main()
