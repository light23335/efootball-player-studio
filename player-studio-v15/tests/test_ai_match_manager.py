import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_match_manager import Manager, strategy, assignment, legal_assignment, substitution_pairs, APTITUDE_INDEX
from division_squads import Generator


def fixture():
    profiles = Generator.profiles()
    base = next(p for p in profiles if p['family'] == '442' and p['midfield_group'] == 'anchor_link')
    players = []
    for i in range(23):
        params = [0]*147; params[0] = 0 if i in (0,11) else 5
        params[1:14] = [2]*13; params[14:41] = [90]*27
        params[APTITUDE_INDEX[0]] = 2 if i in (0,11) else 0
        if i in (0,11):
            params[1:13] = [0]*12
        players.append({'id':1000+i,'serial':810000001+i,'parameters':params,'ratings':[110]*13,'bench_rating':110})
    spec = {'game_id':123,'players':players,'profiles':profiles,'base_profile':base,'minimum':3300}
    snapshot = {'game_id':123,'human_controlled':False,'coherent':True,'paused':False,'replay':False,
                'phase':'stoppage','minute':80.,'sequence':8,'on_field':list(range(11)),
                'bench':list(range(11,23)),'stamina':{str(i):95 for i in range(23)},
                'roles':{str(i):r for i,r in enumerate(base['attack'])},'score':[1,0],
                'safe_to_change':True,'substitutions_left':5,'windows_left':3}
    return spec,snapshot


class MatchManagerTests(unittest.TestCase):
    def test_unsafe_best_shape_does_not_hide_other_legal_substitutions(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=70,score=[0,0])
        anchor=spec['base_profile']['attack'].index(4)
        link=spec['base_profile']['attack'].index(5)
        for i in range(11,23):spec['players'][i]['parameters'][1:14]=[0]*13
        spec['players'][anchor]['ratings'][5]=130
        snap['stamina'][str(link)]=20
        for index,role,rating in ((18,4,125),(19,5,124)):
            spec['players'][index]['parameters'][APTITUDE_INDEX[role]]=2
            spec['players'][index]['ratings'][role]=rating
        unconstrained=assignment(spec,snap,spec['base_profile'],1)
        self.assertIsNone(substitution_pairs(spec,snap,unconstrained['incoming'],unconstrained['outgoing']))
        found=legal_assignment(spec,snap,spec['base_profile'],1)
        self.assertTrue(found['incoming'])
        self.assertEqual(found['pairs'],substitution_pairs(spec,snap,found['incoming'],found['outgoing']))
        self.assertEqual(found['incoming'],[19]);self.assertEqual(found['outgoing'],[link])

    def test_fatigue_search_must_include_the_player_that_triggered_it(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=70,score=[0,0])
        snap['stamina']['7']=25
        spec['players'][12]['ratings']=[150]*13
        found=legal_assignment(spec,snap,spec['base_profile'],1,required_outgoing=[7])
        self.assertIn(7,found['outgoing'])
        self.assertTrue(found['pairs'])

    def test_foreign_native_substitution_refreshes_legal_shape_and_duties(self):
        spec,snap=fixture();snap.update(minute=40,score=[0,0]);m=Manager(spec)
        self.assertIsNone(m.propose(snap))
        snap['on_field'][7]=17;snap['bench'].remove(17);snap['bench'].append(7)
        snap['roles']['17']=snap['roles'].pop('7');snap.update(minute=41,sequence=10)
        p=m.propose(snap);self.assertIsNotNone(p);self.assertEqual(p['kind'],'formation')
        self.assertEqual(p['incoming'],[]);self.assertNotIn(7,p['mapping'].values())
        self.assertNotIn(7,[p['duties']['captain'],*p['duties']['set_piece_taker'],*p['duties']['df_overlap_setplay']])

    def test_post_sub_refresh_survives_delayed_native_budget_rejection(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
        m=Manager(spec);p=m.propose(snap)
        for incoming,outgoing in p['pairs']:
            snap['on_field'][snap['on_field'].index(outgoing)]=incoming
            snap['bench'].remove(incoming);snap['bench'].append(outgoing)
            snap['roles'][str(incoming)]=snap['roles'].pop(str(outgoing))
        snap.update(ack_id=p['id'],ack_status='applied',minute=60.6,sequence=10)
        refresh=m.propose(snap);self.assertEqual(refresh['kind'],'formation')
        snap.update(ack_id=refresh['id'],ack_status='rejected',minute=60.7,sequence=12)
        self.assertIsNone(m.propose(snap));self.assertTrue(m.state['rebuild_due'])
        snap.update(substitutions_left=3,windows_left=2,minute=61.3,sequence=14)
        retry=m.propose(snap);self.assertEqual(retry['kind'],'formation')

    def test_rejected_request_waits_for_real_window_change_not_frame_or_energy(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0],phase='play',safe_to_change=False,safe_to_queue=True,period=3)
        snap['stamina']['7']=20;m=Manager(spec);p=m.propose(snap)
        self.assertEqual(p['kind'],'substitution')
        snap.update(ack_id=p['id'],ack_status='stale',minute=64,sequence=10)
        self.assertIsNone(m.propose(snap))
        snap['stamina']['7']=15;snap.update(minute=65,sequence=12)
        self.assertIsNone(m.propose(snap))
        snap.update(phase='stoppage',safe_to_change=True,minute=66,sequence=14)
        self.assertIsNotNone(m.propose(snap))

    def test_verified_native_tactical_callback_accepts_play_time_proposal(self):
        spec,snap=fixture();snap.update(phase='play',safe_to_change=False,native_formation_window=True)
        p=Manager(spec).propose(snap)
        self.assertIsNotNone(p);self.assertEqual(p['kind'],'formation')
        snap['native_formation_window']=False
        self.assertIsNone(Manager(spec).propose(snap))

    def test_reduced_shape_waits_for_stoppage_and_uses_no_fictional_floor(self):
        spec,snap=fixture();snap.update(minute=40,score=[0,0],phase='play',safe_to_change=False,safe_to_queue=True)
        m=Manager(spec);self.assertIsNone(m.propose(snap))
        snap['on_field'].remove(8);snap['unavailable']=[8];snap['sequence']+=2;snap['minute']+=1
        self.assertIsNone(m.propose(snap));self.assertTrue(m.state['rebuild_due'])
        snap.update(phase='stoppage',safe_to_change=True,minute=42);snap['sequence']+=2
        p=m.propose(snap);self.assertIsNotNone(p)
        self.assertEqual(p['active_count'],10);self.assertEqual(len(p['mapping']),10)
        self.assertNotIn(8,p['mapping'].values());self.assertIsNone(p['native_lower_bound_strength'])
        snap.update(ack_id=p['id'],ack_status='applied');m.observe(snap)
        self.assertFalse(m.state['rebuild_due'])

    def test_score_time_policy_has_deliberate_early_restraint(self):
        self.assertEqual(strategy(20,-1),'base')
        self.assertEqual(strategy(29,-2),'base')
        self.assertEqual(strategy(30,-2),'chase')
        self.assertEqual(strategy(60,-1),'chase')
        self.assertEqual(strategy(80,1),'protect')
        self.assertEqual(strategy(88,-1),'last_push')
        self.assertEqual(strategy(88,0),'base')
        self.assertEqual(strategy(88,0,True),'chase')

    def test_extra_time_last_push_uses_actual_period_end(self):
        self.assertEqual(strategy(95,-1,False,120),'chase')
        self.assertEqual(strategy(114,-1,False,120),'chase')
        self.assertEqual(strategy(116,-1,False,120),'last_push')
        self.assertEqual(strategy(116,0,False,120),'base')

    def test_rejected_plan_does_not_blindly_resubmit_same_context(self):
        spec,snap=fixture();m=Manager(spec);proposal=m.propose(snap)
        snap.update(ack_id=proposal['id'],ack_status='rejected',minute=81.)
        self.assertIsNone(m.propose(snap))
        snap.update(score=[0,1],minute=88.)
        self.assertIsNotNone(m.propose(snap))

    def test_old_entry_with_same_game_number_is_not_accepted(self):
        spec,snap=fixture();spec['entry_id']='new-round';snap['entry_id']='old-round'
        self.assertIsNone(Manager(spec).propose(snap))

    def test_secondary_full_aptitudes_allow_joint_assignment(self):
        spec,snap=fixture()
        # All outfield players have CMF as their main position.
        result=assignment(spec,snap,spec['base_profile'])
        self.assertIsNotNone(result)
        self.assertEqual(len(set(result['mapping'].values())),11)
        self.assertEqual(result['incoming'],[])

    def test_unknown_bench_stamina_does_not_block_legal_formation_or_get_guessed(self):
        spec,snap=fixture()
        for i in snap['bench']:snap['stamina'].pop(str(i))
        result=assignment(spec,snap,spec['base_profile'],2)
        self.assertIsNotNone(result);self.assertEqual(result['incoming'],[])

    def test_missing_defensive_aptitude_blocks_a_slot(self):
        spec,snap=fixture()
        for p in spec['players']:
            p['parameters'][APTITUDE_INDEX[6]]=0
        profile=next(p for p in spec['profiles']if p['family']=='433')
        self.assertIsNone(assignment(spec,snap,profile,2))

    def test_proposal_needs_native_acknowledgement(self):
        spec,snap=fixture(); m=Manager(spec)
        p=m.propose(snap)
        self.assertEqual(p['kind'],'formation')
        self.assertEqual(m.state['mode'],'base')
        self.assertIsNone(m.propose(snap))
        snap.update(ack_id=p['id'],ack_status='applied')
        m.observe(snap)
        self.assertEqual(m.state['mode'],'protect')

    def test_tired_outfield_player_gets_fresh_legal_replacement(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=25
        m=Manager(spec);p=m.propose(snap)
        self.assertEqual(p['kind'],'substitution');self.assertIn(7,p['outgoing'])
        self.assertNotIn(0,p['outgoing']);self.assertNotIn(11,p['incoming'])
        self.assertEqual(m.state['last_sub_minute'],-100)

    def test_no_substitution_without_native_slots_or_windows(self):
        for key in ('substitutions_left','windows_left'):
            spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20;snap[key]=0
            self.assertIsNone(Manager(spec).propose(snap))

    def test_pause_replay_human_and_wrong_match_are_ignored(self):
        for update in ({'paused':True},{'replay':True},{'human_controlled':True},{'game_id':456},
                       {'coherent':False},{'minute':float('nan')},{'safe_to_change':False},{'phase':'play'}):
            spec,snap=fixture();snap.update(update)
            self.assertIsNone(Manager(spec).propose(snap),update)

    def test_live_lineup_change_is_required_for_a_substitution_ack(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
        m=Manager(spec);p=m.propose(snap);snap.update(ack_id=p['id'],ack_status='applied')
        m.observe(snap);self.assertIsNotNone(m.state['pending'])
        for a,b in zip(p['outgoing'],p['incoming']):
            snap['on_field'].remove(a);snap['on_field'].append(b);snap['bench'].remove(b);snap['bench'].append(a)
        m.observe(snap)
        self.assertIsNone(m.state['pending']);self.assertIn(7,m.state['used_out'])

    def test_fatigue_sub_ack_also_refreshes_duties_without_another_substitution(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
        m=Manager(spec);p=m.propose(snap)
        self.assertEqual(p['reason'],'fatigue or disciplinary risk')
        for inc,out in p['pairs']:
            slot=snap['on_field'].index(out);snap['on_field'][slot]=inc
            snap['bench'].remove(inc);snap['bench'].append(out)
            snap['roles'][str(inc)]=snap['roles'].pop(str(out))
        snap.update(ack_id=p['id'],ack_status='applied',sequence=10,minute=60.6,
                    substitutions_left=5-len(p['incoming']),windows_left=2)
        m.observe(snap)
        follow=m.propose(snap)
        self.assertEqual(follow['kind'],'formation')
        self.assertEqual(follow['incoming'],[])
        self.assertFalse(set(follow['duties']['set_piece_taker'])&set(p['outgoing']))
        self.assertTrue(set(follow['duties']['df_overlap_setplay'])<=set(snap['on_field']))

    def test_fatigue_change_preserves_previously_confirmed_protect_shape(self):
        spec,snap=fixture();m=Manager(spec)
        plan=m.propose(snap);self.assertEqual(plan['mode'],'protect')
        snap.update(ack_id=plan['id'],ack_status='applied',minute=80.1)
        m.observe(snap);self.assertEqual(m.state['profile_id'],plan['profile_id'])
        snap.update(minute=86,sequence=10);snap['stamina']['7']=20
        follow=m.propose(snap)
        self.assertEqual(follow['kind'],'substitution')
        self.assertEqual(follow['profile_id'],plan['profile_id'])

    def test_restart_preserves_substituted_out_players(self):
        spec,snap=fixture();m=Manager(spec);m.observe(snap)
        snap['on_field'].remove(7);snap['on_field'].append(12);snap['bench'].remove(12);snap['bench'].append(7)
        m.observe(snap);restored=Manager(spec,json.loads(json.dumps(m.state)))
        snap['stamina']['12']=20
        p=restored.propose(snap)
        if p:self.assertNotIn(7,p['incoming'])
        self.assertIn(7,restored.state['used_out'])

    def test_red_card_assignment_does_not_invent_an_eleventh_player(self):
        spec,snap=fixture();snap['on_field'].remove(10);snap['unavailable']=[10]
        result=assignment(spec,snap,spec['base_profile'])
        self.assertEqual(len(result['mapping']),10)
        self.assertNotIn(10,result['mapping'].values())

    def test_card_aptitudes_and_abilities_are_not_rewritten(self):
        spec,snap=fixture();before=copy.deepcopy(spec)
        Manager(spec).propose(snap)
        self.assertEqual(spec,before)

    def test_rating_floor_is_kept_for_voluntary_full_squad_changes(self):
        spec,snap=fixture();spec['minimum']=3500
        self.assertIsNone(assignment(spec,snap,spec['base_profile'],2))

    def test_score_change_cancels_accepted_request_before_new_plan(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
        m=Manager(spec);p=m.propose(snap)
        snap.update(ack_id=p['id'],ack_status='accepted',score=[0,1],minute=61)
        self.assertIsNone(m.propose(snap))
        self.assertEqual(m.cancellation()['id'],p['id'])
        self.assertEqual(m.cancellation()['reason'],'score changed')
        snap.update(ack_status='cancelled')
        self.assertIsNotNone(m.propose(snap))

    def test_native_lineup_or_injured_bench_invalidates_pending_request(self):
        for mutate,reason in ((lambda s:s['on_field'].remove(8),'native lineup changed'),
                              (lambda s,p=None:None,'substitute unavailable')):
            spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
            m=Manager(spec);p=m.propose(snap)
            if reason=='substitute unavailable':snap['unavailable']=p['incoming']
            else:mutate(snap)
            m.observe(snap)
            self.assertEqual(m.cancellation()['reason'],reason)

    def test_acceptance_and_false_applied_receipt_cannot_stall_forever(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0]);snap['stamina']['7']=20
        m=Manager(spec);p=m.propose(snap)
        snap.update(ack_id=p['id'],ack_status='applied',minute=64)
        m.observe(snap)
        self.assertEqual(m.cancellation()['reason'],'native confirmation timed out')
        self.assertEqual(m.state['last_sub_minute'],-100)

    def test_native_queue_during_play_is_distinct_from_formation_window(self):
        spec,snap=fixture();snap.update(minute=60,score=[0,0],phase='play',safe_to_change=False,safe_to_queue=True)
        snap['stamina']['7']=20
        proposal=Manager(spec).propose(snap)
        self.assertIsNotNone(proposal);self.assertEqual(proposal['kind'],'substitution')
        snap['stamina']['7']=95;snap.update(minute=80,score=[1,0])
        self.assertIsNone(Manager(spec).propose(snap))

    def test_foreign_native_substitutions_are_not_overwritten(self):
        spec,snap=fixture();snap['native_pending_count']=1
        self.assertIsNone(Manager(spec).propose(snap))

    def test_joint_plan_requires_legal_current_roles_until_formation_ack(self):
        spec,snap=fixture();snap['roles']['7']=8;snap['defence_roles']=dict(snap['roles'])
        snap['defence_roles']['7']=5
        spec['players'][12]['parameters'][APTITUDE_INDEX[5]]=0
        self.assertIsNone(substitution_pairs(spec,snap,[12],[7]))
        spec['players'][12]['parameters'][APTITUDE_INDEX[5]]=2
        self.assertEqual(substitution_pairs(spec,snap,[12],[7]),[(12,7)])

    def test_cooldown_survives_native_stage_clock_reset(self):
        spec,snap=fixture();snap.update(minute=44,period=1,score=[0,0])
        m=Manager(spec);m.observe(snap);m.state['last_sub_minute']=44
        snap.update(minute=0,period=3);m.observe(snap)
        self.assertEqual(m.state['elapsed_minute'],44)
        snap.update(minute=6);m.observe(snap)
        self.assertEqual(m.state['elapsed_minute'],50)
        snap.update(minute=2)
        self.assertFalse(m.observe(snap));self.assertEqual(m.state['elapsed_minute'],50)

    def test_same_game_new_entry_does_not_restore_old_pending_or_used_players(self):
        spec,snap=fixture();spec['entry_id']='old';snap['entry_id']='old'
        m=Manager(spec);m.propose(snap);m.state['used_out']=[7]
        spec['entry_id']='new'
        restored=Manager(spec,m.state)
        self.assertIsNone(restored.state['pending']);self.assertEqual(restored.state['used_out'],[])

if __name__=='__main__':unittest.main()
