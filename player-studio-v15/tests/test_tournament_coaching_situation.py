import copy,unittest
from unittest.mock import patch
from ai_match_manager import Manager,match_situation
from test_ai_match_manager import fixture
import tournament_runtime as runtime

def context(**kw):
    return dict(first_leg=False,second_leg=True,deciding=True,cpu_home=True,
        prior_score=[0,2],away_goals=False,away_goals_extra_time=False,extra_time=True,penalties=True,**kw)

class SituationTests(unittest.TestCase):
    def test_draw_and_current_win_still_chase_aggregate_deficit(self):
        spec,snap=fixture();spec['advancement']=context()
        for score in ([0,0],[1,0]):
            snap.update(score=score,minute=86,period=3)
            s=match_situation(spec,snap);self.assertEqual(s['mode'],'last_push');self.assertTrue(s['must_win'])
        snap.update(score=[2,0],minute=86)
        self.assertEqual(match_situation(spec,snap)['mode'],'base')

    def test_losing_this_leg_can_protect_aggregate_lead(self):
        spec,snap=fixture();c=context();c['prior_score']=[3,0];spec['advancement']=c
        snap.update(score=[0,2],minute=80)
        s=match_situation(spec,snap);self.assertEqual(s['mode'],'protect');self.assertEqual(s['difference'],1)

    def test_away_goal_deficit_and_advantage_both_venues(self):
        spec,snap=fixture();c=context();c.update(away_goals=True,prior_score=[0,1]);spec['advancement']=c
        snap.update(score=[2,1],minute=88,period=3)
        self.assertEqual(match_situation(spec,snap)['mode'],'last_push')
        c.update(cpu_home=False,prior_score=[1,0]);snap['score']=[1,2]
        self.assertEqual(match_situation(spec,snap)['mode'],'protect')
        c['away_goals']=False
        self.assertEqual(match_situation(spec,snap)['mode'],'base')

    def test_extra_time_rules_and_tied_penalty_path(self):
        spec,snap=fixture();c=context();c.update(away_goals=True,prior_score=[0,1]);spec['advancement']=c
        snap.update(score=[2,1],minute=116,period=7,period_end=120)
        self.assertEqual(match_situation(spec,snap)['mode'],'base')
        c['away_goals_extra_time']=True
        self.assertEqual(match_situation(spec,snap)['mode'],'last_push')
        c.update(away_goals=False,prior_score=[0,2]);snap['score']=[1,0]
        snap['minute']=114;self.assertEqual(match_situation(spec,snap)['mode'],'chase')
        snap['minute']=115;self.assertEqual(match_situation(spec,snap)['mode'],'last_push')

    def test_first_leg_does_not_go_all_out_and_other_modes_keep_score_policy(self):
        spec,snap=fixture();c=context();c.update(first_leg=True,second_leg=False,deciding=False);spec['advancement']=c
        snap.update(score=[0,2],minute=88)
        self.assertEqual(match_situation(spec,snap)['mode'],'chase')
        del spec['advancement'];self.assertEqual(match_situation(spec,snap)['mode'],'last_push')

    def test_runtime_handoff_orients_prior_goals_to_cpu_club(self):
        spec,_=fixture();spec['style']='possession';service=runtime.Service(lambda:{},'.',None)
        for side,expected in [('HOME',[2,1]),('AWAY',[1,2])]:
            native=dict(two_leg=True,first_leg=False,second_leg=True,prior_goals=[1,2],
                away_goals=True,away_goals_extra_time=False,extra_time=True,penalties=True)
            team={'_studio_tournament_squad':dict(tactical_spec=spec,team_id=1)}
            active=dict(player_side=side,home=team,away=team,game_id=5,fixture_id=7,
                        native_rules=native,match_env={'cpu_level':'HARDEST'})
            with patch('ai_match_runtime.activate',return_value={})as activate:
                service.activate_coaching({},dict(run_id='edition'),active)
            handed=activate.call_args.args[0];self.assertEqual(handed['advancement']['prior_score'],expected)
            self.assertEqual(handed['advancement']['cpu_home'],side=='AWAY')
            self.assertEqual(handed['native_identity']['cpu_serial'],-3 if side=='AWAY'else -2)

    def test_independent_attack_chases_aggregate_even_with_pending_substitution(self):
        spec,snap=fixture();spec['advancement']=context();snap.update(score=[0,0],minute=72,current_attack_level=2)
        manager=Manager(spec);manager.state['pending']={'kind':'substitution','id':99}
        p=manager.propose_attack(snap)
        self.assertEqual((p['kind'],p['attack_level']),('attack_level',4))
        self.assertEqual(manager.state['pending']['id'],99)

    def test_attack_retries_are_bounded_and_do_not_wait_until_halftime(self):
        spec,snap=fixture();snap.update(score=[0,2],minute=30,current_attack_level=2,period=1)
        manager=Manager(spec);p=manager.propose_attack(snap);self.assertEqual(p['attack_level'],3)
        for minute in (31,33,35):
            snap.update(minute=minute,attack_ack_id=p['id'],attack_ack_status='rejected',attack_rejection_reason=5)
            self.assertIsNone(manager.propose_attack(snap))
            snap['minute']+=.5
            retry=manager.propose_attack(snap)
            if minute<35:self.assertIsNotNone(retry);p=retry
            else:self.assertIsNone(retry)
        snap.update(minute=70,attack_ack_id=0)
        self.assertEqual(manager.propose_attack(snap)['attack_level'],4)

    def test_attack_ack_never_claims_a_shape_change(self):
        spec,snap=fixture();snap.update(score=[0,1],minute=60,current_attack_level=2)
        manager=Manager(spec);before=copy.deepcopy(manager.state);p=manager.propose_attack(snap)
        snap.update(minute=60.1,current_attack_level=3,attack_ack_id=p['id'],attack_ack_status='applied')
        self.assertIsNone(manager.propose_attack(snap))
        self.assertEqual(manager.state['profile_id'],before['profile_id'])
        self.assertEqual(manager.state['last_tactic_minute'],before['last_tactic_minute'])

    def test_expired_formation_retries_before_halftime_but_stops_after_three(self):
        spec,snap=fixture();snap.update(score=[0,2],minute=30,period=1)
        manager=Manager(spec);p=manager.propose(snap);self.assertIsNotNone(p)
        for minute in (31,33,35):
            snap.update(minute=minute,sequence=snap['sequence']+2,ack_id=p['id'],ack_status='stale')
            self.assertIsNone(manager.propose(snap))
            snap['minute']+=.5;snap['sequence']+=2
            retry=manager.propose(snap)
            if minute<35:self.assertIsNotNone(retry);p=retry
            else:self.assertIsNone(retry)

if __name__=='__main__':unittest.main()
