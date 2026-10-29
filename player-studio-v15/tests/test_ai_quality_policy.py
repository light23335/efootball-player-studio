import copy,json,random,unittest
from unittest.mock import patch
import ai_division_sessions as sessions
import ai_match_manager as policy
import ai_tactical_profiles as shapes
from division_squads import quality_limits,quality_report,strength
from test_ai_match_manager import fixture


class RotationQualityTests(unittest.TestCase):
    def test_ten_thousand_fresh_bags_do_not_put_small_types_first_by_equal_type_odds(self):
        rng=random.Random(198);first={3:0,4:0,5:0};prefix={3:0,4:0,5:0}
        for _ in range(10000):
            kind,state=sessions.preview_formation({},rng);first[kind]+=1
            for n in [kind,*state['formation_bag'][:4]]:prefix[n]+=1
        self.assertGreater(first[4],6000);self.assertLess(first[5],1600)
        self.assertGreater(prefix[4],30000);self.assertLess(prefix[5],8000)

    def test_cached_native_aggregation_is_float32_identical_across_extremes(self):
        from division_squads import f32
        rng=random.Random(197)
        for values in ([[0]*23,[255]*23]+[[rng.randrange(256)for _ in range(23)]for _ in range(10000)]):
            r=sorted(values,reverse=True)
            a=f32(f32(sum(r[:11]))*f32(1.8));b=f32(f32(sum(r[11:14]))*f32(1.4))
            c=f32(sum(r[14:18]));d=f32(f32(sum(r[18:]))*f32(.6))
            self.assertEqual(strength(values),min(9999,int(f32(f32(f32(a+b)+c)+d))))

    def test_one_thousand_successful_draws_obey_bags_and_cross_round_constraints(self):
        rng=random.Random(871);state={};draws=[]
        for _ in range(1000):
            before=copy.deepcopy(state);kind,after=sessions.preview_formation(state,rng)
            self.assertEqual(state,before)
            state=json.loads(json.dumps(after));draws.append(kind)
        for start in range(0,1000,20):
            block=draws[start:start+20]
            self.assertEqual({n:block.count(n)for n in (4,3,5)},{4:14,3:4,5:2})
        for i in range(1,len(draws)):
            self.assertNotEqual(draws[i-1:i+1],[5,5])
            if i>1:self.assertIn(4,draws[i-2:i+1])

    def test_quality_is_separate_for_starters_and_bench(self):
        values=[102]*11+[125]*12
        self.assertGreater(strength(values),3300)
        self.assertFalse(quality_report(values,3300)['passed'])
        values=[120]*11+[100]*12
        self.assertFalse(quality_report(values,3300)['passed'])
        self.assertTrue(quality_report([109]*11+[106]*12,3400)['passed'])
        self.assertEqual(quality_limits(3200),(99,103,97,101))

    def test_single_card_floor_is_not_offset_by_a_star(self):
        values=[110]*23;values[3]=101;values[8]=135
        self.assertFalse(quality_report(values,3300)['passed'])

    def test_broad_fallback_uses_the_actual_strength_tier_quality_rules(self):
        values=[112]*23;values[0]=103
        self.assertGreaterEqual(strength(values),3400)
        self.assertFalse(quality_report(values,3200)['passed'])
        self.assertEqual(quality_report(values,3200)['limits']['starter_min'],104)

    def test_three_back_base_and_five_back_defence_are_reported_separately(self):
        shape=next(p for p in shapes.profiles()if p['family']=='343')
        self.assertEqual(shapes.back_type(shape),3)
        self.assertEqual(shapes.back_type(shape,'defence'),5)


class ContinuousPlanningTests(unittest.TestCase):
    def test_ordinary_substitution_cannot_start_cross_family_plan_during_cooldown(self):
        spec,snap=fixture();snap.update(minute=65.2,score=[0,1]);snap['stamina']['7']=54
        spec['players'][17]['ratings']=[145]*13
        m=policy.Manager(spec);m.state.update(mode='chase',attack_level=3,last_tactic_minute=64,last_sub_minute=50,
            last_score=(0,1),last_full_evaluation=62,last_evaluation_minute=64)
        current=m.profile(m.state['profile_id'],'chase')
        target=next(policy.tactical_profile(p,'chase',None)for p in spec['profiles']if p['family']=='424')
        with patch.object(m,'candidates',return_value=[current,target]):p=m.propose(snap)
        self.assertIsNotNone(p);self.assertEqual(p['kind'],'substitution')
        self.assertEqual(p['profile_id'].split(':')[0],'442')
        for inc,out in p['pairs']:
            snap['on_field'][snap['on_field'].index(out)]=inc;snap['bench'].remove(inc);snap['bench'].append(out)
            snap['roles'][str(inc)]=snap['roles'].pop(str(out))
        snap.update(minute=65.8,sequence=10,ack_id=p['id'],ack_status='applied')
        refresh=m.propose(snap)
        self.assertIsNotNone(refresh);self.assertEqual(refresh['kind'],'formation')
        self.assertEqual(refresh['profile_id'].split(':')[0],'442')
        self.assertFalse(refresh['changes_shape'])
        snap.update(minute=66,sequence=12,ack_id=refresh['id'],ack_status='applied');m.observe(snap)
        self.assertEqual(m.state['last_tactic_minute'],64,'Duty refresh must not reset the actual shape cooldown')

    def test_old_joint_after_sub_plan_is_not_a_cooldown_exception(self):
        spec,snap=fixture();snap.update(minute=65.8,score=[0,1]);m=policy.Manager(spec)
        target=next(p for p in spec['profiles']if p['family']=='424')
        m.state.update(mode='chase',attack_level=3,last_tactic_minute=64,last_score=(0,1),rebuild_due=True)
        m.state['after_sub_plan']={'profile_id':target['id'],'mode':'chase'}
        self.assertIsNone(m.propose(snap))
        self.assertIn('424',m.state['last_decision']['cooldown_rejected'])

    def test_changed_score_after_confirmed_members_replans_even_in_same_mode(self):
        spec,snap=fixture();snap.update(minute=66,score=[0,2]);m=policy.Manager(spec)
        target=next(p for p in spec['profiles']if p['family']=='424')
        m.state.update(mode='chase',attack_level=3,last_tactic_minute=64,last_score=(0,1))
        m.state['after_sub_plan']={'profile_id':target['id'],'mode':'chase','score':[0,1],
                                   'initial_on_field':list(range(11)),'incoming':[],'outgoing':[]}
        with patch.object(m,'candidates',wraps=m.candidates)as compare:m.propose(snap)
        self.assertTrue(compare.called);self.assertIsNone(m.state['after_sub_plan'])
        self.assertTrue(any(e['event']=='after_sub_plan_cancelled'for e in m.state['journal']))

    def test_preflight_uses_actual_defensive_roles(self):
        spec,snap=fixture();base=next(p for p in shapes.profiles()if p['family']=='343')
        class Generator:
            def prepared(self,card):return card
            def rating(self,card,coach,style,role=None):return 110
        selected=[{'gameplayer_id':{'id':1000+i},'parameters':spec['players'][i]['parameters']}for i in range(23)]
        captured=[]
        def inspect(spec,snapshot,*args,**kwargs):captured.append(copy.deepcopy(snapshot));return None
        with patch.object(policy,'legal_assignment',side_effect=inspect):
            policy.prepare_strategies(Generator(),selected,{'payload':{'coach_id':{'id':1}}},'possession',base,3300)
        self.assertTrue(captured)
        self.assertTrue(all(v['defence_roles']=={str(i):r for i,r in enumerate(base['defence'])}for v in captured))
        self.assertNotEqual(captured[0]['roles'],captured[0]['defence_roles'])

    def test_losing_a_formation_family_has_no_cost_when_the_required_task_survives(self):
        spec,snap=fixture();m=policy.Manager(spec)
        future=next(p for p in spec['profiles']if p['family']=='424')
        for i,p in enumerate(spec['players']):
            if i!=7:p['parameters'][policy.APTITUDE_INDEX[9]]=0
        spec['prepared']={'chase':{'options':[{'profile_id':future['id']},{'profile_id':spec['base_profile']['id']}]},
                          'protect':{'options':[{'profile_id':spec['base_profile']['id']}]}}
        self.assertEqual(m.future_coverage_cost(snap,{'outgoing':[7]}),0)

    def test_same_mode_rechecks_every_three_minutes_and_can_hold(self):
        spec,snap=fixture();snap.update(minute=62,score=[0,1]);manager=policy.Manager(spec)
        manager.state.update(mode='chase',last_tactic_minute=50,attack_level=3)
        with patch.object(manager,'candidates',wraps=manager.candidates)as candidates:
            p=manager.propose(snap)
            if p:
                snap.update(ack_id=p['id'],ack_status='applied',minute=62.1,sequence=10);manager.observe(snap)
            count=candidates.call_count
            snap.update(minute=64,sequence=12);manager.propose(snap)
            self.assertEqual(candidates.call_count,count)
            # Recheck even while the 5-minute actual-change cooldown remains.
            manager.state['last_tactic_minute']=64
            snap.update(minute=65.1,sequence=14);manager.propose(snap)
            self.assertGreater(candidates.call_count,count)

    def test_larger_deficit_rechecks_even_if_mode_name_is_unchanged(self):
        spec,snap=fixture();snap.update(minute=62,score=[0,1]);m=policy.Manager(spec)
        m.state.update(mode='chase',attack_level=3,last_score=(0,1),last_tactic_minute=61,
                       last_full_evaluation=61,last_evaluation_minute=61)
        snap.update(minute=62,score=[0,2])
        with patch.object(m,'candidates',wraps=m.candidates)as candidates:m.propose(snap)
        self.assertTrue(candidates.called)

    def test_last_push_has_distinct_weights_and_coordinates(self):
        spec,snap=fixture();base=spec['base_profile']
        chase=policy.tactical_profile(base,'chase','possession')
        last=policy.tactical_profile(base,'last_push','possession')
        self.assertGreater(policy.tactical_value(last,'last_push'),policy.tactical_value(chase,'chase'))
        self.assertNotEqual(chase['attack_coords'],last['attack_coords'])

    def test_formation_first_path_proves_both_intermediate_roles(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=70,score=[0,0])
        anchor=spec['base_profile']['attack'].index(4);link=spec['base_profile']['attack'].index(5)
        for i in range(11,23):spec['players'][i]['parameters'][1:14]=[0]*13
        spec['players'][anchor]['ratings'][5]=130;snap['stamina'][str(link)]=20
        for index,role,rating in ((18,4,125),(19,5,124)):
            spec['players'][index]['parameters'][policy.APTITUDE_INDEX[role]]=2
            spec['players'][index]['ratings'][role]=rating
        found=policy.legal_assignment(spec,snap,spec['base_profile'],1,allow_staging=True)
        self.assertIsNotNone(found.get('pre_formation'))
        pre=found['pre_formation'];profile=policy.resolve_profile(spec,pre['profile_id'],'base')
        interim=dict(snap,roles={str(i):profile['attack'][s]for s,i in pre['mapping'].items()},
                     defence_roles={str(i):profile['defence'][s]for s,i in pre['mapping'].items()})
        self.assertEqual(pre['pairs'],policy.substitution_pairs(spec,interim,found['incoming'],found['outgoing']))
        for slot,index in pre['mapping'].items():
            for role in (profile['attack'][slot],profile['defence'][slot]):self.assertEqual(spec['players'][index]['parameters'][policy.APTITUDE_INDEX[role]],2)

    def test_formation_first_does_not_guess_joint_native_execution(self):
        spec,snap=fixture();snap.update(minute=65,score=[0,1]);m=policy.Manager(spec)
        base=spec['base_profile'];mapping=dict(enumerate(range(11)))
        target=next(p for p in spec['profiles']if p['family']=='424')
        final=policy.assignment(spec,snap,policy.tactical_profile(target,'chase',None),0,'chase')
        final.update(incoming=[17],outgoing=[7],pairs=[(17,7)],utility=3000,
                     mapping={s:17 if i==7 else i for s,i in mapping.items()},
                     pre_formation={'profile_id':base['id'],'mapping':mapping,'pairs':[(17,7)],'native_lower_bound_strength':3410})
        with patch.object(m,'candidates',return_value=[base]),patch.object(policy,'legal_assignment',return_value=final):p=m.propose(snap)
        self.assertEqual(p['kind'],'formation');self.assertEqual(p['incoming'],[])
        self.assertIsNone(m.state['staged_plan'])
        snap.update(ack_id=p['id'],ack_status='accepted',minute=65.1,sequence=10);m.observe(snap)
        self.assertIsNone(m.state['staged_plan'])
        snap.update(ack_status='applied',minute=65.2,sequence=12);m.observe(snap)
        self.assertIsNotNone(m.state['staged_plan']);self.assertIsNone(m.state['pending'])
        after=copy.deepcopy(final);after.pop('pre_formation');snap.update(minute=65.8,sequence=14)
        with patch.object(policy,'legal_assignment',return_value=after):sub=m.propose(snap)
        self.assertEqual(sub['kind'],'substitution');self.assertIn('cooldown_authorized',sub)
        snap['on_field'][7]=17;snap['bench'].remove(17);snap['bench'].append(7)
        snap['roles']['17']=snap['roles'].pop('7')
        snap.update(ack_id=sub['id'],ack_status='applied',minute=66.4,sequence=16)
        finish=m.propose(snap)
        self.assertIsNotNone(finish);self.assertEqual(finish['kind'],'formation')
        self.assertEqual(finish['profile_id'].split(':')[0],'424')

    def test_staged_plan_is_abandoned_when_score_changes(self):
        spec,snap=fixture();snap.update(minute=65,score=[0,2]);m=policy.Manager(spec)
        m.state['staged_plan']={'profile_id':spec['base_profile']['id'],'score':[0,1],'mode':'chase',
                                'initial_on_field':list(range(11)),'created_elapsed':64}
        m.propose(snap)
        self.assertIsNone(m.state['staged_plan'])
        self.assertTrue(any(r['event']=='staged_plan_cancelled'for r in m.state['journal']))

if __name__=='__main__':unittest.main()
