import copy,json,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ai_match_manager import fixture
from ai_match_manager import Manager,strategy,substitution_budget,tactical_catalogue,tactical_profile,prepare_strategies,pool_can_fill,APTITUDE_INDEX
from division_squads import Generator
import ai_tactical_profiles as templates


class CoachingRevisionTests(unittest.TestCase):
    def test_two_goal_deficit_attacks_earlier_but_not_at_twenty_minutes(self):
        self.assertEqual(strategy(20,-2),'base')
        self.assertEqual(strategy(60,-1),'chase')
        self.assertEqual(strategy(70,-2),'last_push')
        self.assertEqual(strategy(100,-2,False,120),'last_push')
        self.assertEqual(strategy(100,-1,False,120),'chase')

    def test_one_severely_tired_player_does_not_authorize_two_early_subs(self):
        spec,snap=fixture();snap.update(minute=41,score=[0,0])
        snap['stamina']['7']=33;snap['stamina']['8']=39
        self.assertEqual(substitution_budget(snap,'base',[7]),1)
        p=Manager(spec).propose(snap)
        self.assertEqual(len(p['incoming']),1);self.assertEqual(p['outgoing'],[7])

    def test_middle_match_preserves_two_places_and_urgent_chase_can_use_them(self):
        _,snap=fixture();snap.update(minute=65,score=[0,0],substitutions_left=2)
        self.assertEqual(substitution_budget(snap,'base',[]),0)
        self.assertEqual(substitution_budget(snap,'base',[7]),1)
        snap['score']=[0,2]
        self.assertEqual(substitution_budget(snap,'chase',[]),2)

    def test_severe_fatigue_precedes_more_profitable_moderate_change(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=65,score=[0,0],substitutions_left=1)
        snap['stamina']['7']=30;snap['stamina']['8']=45
        # Keeping the exhausted star wins raw utility. A legal replacement
        # still exists; the moderate player's upgrade must not take this slot.
        spec['players'][7]['ratings']=[150]*13
        p=Manager(spec).propose(snap)
        self.assertIsNotNone(p);self.assertEqual(p['outgoing'],[7])

    def test_lowest_energy_severe_player_wins_the_last_legal_slot(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=65,score=[0,0],substitutions_left=1)
        snap['stamina']['7']=30;snap['stamina']['8']=20
        spec['players'][8]['ratings']=[150]*13
        p=Manager(spec).propose(snap);self.assertEqual(p['outgoing'],[8])

    def test_unreplaceable_severe_player_does_not_bypass_aptitude_or_block_other_legal_need(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=65,score=[0,0],substitutions_left=1)
        snap['stamina']['7']=20;snap['stamina']['8']=30
        blocked_role=snap['roles']['7']
        for index in snap['bench']:spec['players'][index]['parameters'][APTITUDE_INDEX[blocked_role]]=0
        manager=Manager(spec);p=manager.propose(snap)
        if p['kind']=='formation':
            # v5 may first confirm a legal new role for the tired player.
            self.assertIn('continuation',p);self.assertEqual(p['incoming'],[])
            profile=manager.profile(p['profile_id'],p['mode'])
            snap['roles']={str(i):profile['attack'][s]for s,i in p['mapping'].items()}
            snap['defence_roles']={str(i):profile['defence'][s]for s,i in p['mapping'].items()}
            snap.update(ack_id=p['id'],ack_status='applied',minute=65.7,sequence=10)
            p=manager.propose(snap)
            self.assertEqual(p['outgoing'],[7])
            from ai_match_manager import substitution_pairs
            self.assertEqual(p['pairs'],substitution_pairs(spec,snap,p['incoming'],p['outgoing']))
        else:self.assertEqual(p['outgoing'],[8])

    def test_ordinary_small_fatigue_gain_is_compared_to_leaving_native_lineup_unchanged(self):
        spec,snap=fixture();spec['minimum']=0;snap.update(minute=65,score=[0,0])
        snap['stamina']['7']=54
        m=Manager(spec);self.assertIsNone(m.propose(snap))
        self.assertEqual(m.state['last_decision']['reason'],'hold_lineup_better_after_change_costs')

    def test_ordinary_change_coverage_includes_future_424_even_when_search_uses_only_current_shape(self):
        spec,snap=fixture();snap.update(minute=65,score=[0,0])
        for index,p in enumerate(spec['players']):
            if index!=7:p['parameters'][APTITUDE_INDEX[9]]=0
        future=next(p for p in spec['profiles']if p['family']=='424')
        spec['prepared']={'chase':{'options':[{'profile_id':future['id']}]},
                          'protect':{'options':[{'profile_id':spec['base_profile']['id']}]}}
        before=snap['on_field']+snap['bench'];after=[i for i in before if i!=7]
        self.assertTrue(pool_can_fill(spec,before,future));self.assertFalse(pool_can_fill(spec,after,future))
        m=Manager(spec)
        self.assertGreater(m.future_coverage_cost(snap,{'outgoing':[7]},[spec['base_profile']]),0)
        self.assertEqual(m.future_coverage_cost(snap,{'outgoing':[8]},[spec['base_profile']]),0)

    def test_catalogue_round_robin_includes_other_families_before_variants(self):
        spec,_=fixture()
        for kind in ('chase','protect'):
            rows=tactical_catalogue(spec['base_profile'],kind,'possession')
            self.assertEqual(len({p['family']for p in rows[:18]}),18)
            self.assertTrue(any(p['family']=='541'for p in rows[:18]))

    def test_chase_actually_switches_family_with_zero_substitutions(self):
        spec,snap=fixture();snap.update(minute=70,score=[0,2],substitutions_left=0,windows_left=0)
        p=Manager(spec).propose(snap)
        self.assertIsNotNone(p);self.assertEqual(p['kind'],'formation')
        self.assertNotEqual(p['profile_id'].split(':')[0],spec['base_profile']['family'])
        self.assertEqual(p['incoming'],[]);self.assertEqual(p['attack_level'],4)

    def test_newly_discovered_formation_is_encoded_with_its_actual_geometry(self):
        from ai_match_channel import encode_command,checksum
        spec,snap=fixture();spec['profiles']=[spec['base_profile']]
        snap.update(minute=70,score=[0,2],substitutions_left=0,windows_left=0,clock_frames=100)
        m=Manager(spec);p=m.propose(snap)
        self.assertNotEqual(p['profile_id'],spec['base_profile']['id'])
        layout=json.loads((Path(__file__).resolve().parents[1]/'resources/native-ai-match-adapter.json').read_text('utf8'))['channel_schema']
        raw=encode_command(layout,spec,snap,p,2,9);target=m.profile(p['profile_id'],p['mode'])
        self.assertEqual(struct.unpack_from('<I',raw,4)[0],checksum(raw))
        for n,(slot,index)in enumerate(sorted(p['mapping'].items())):
            values=struct.unpack_from('<7I',raw,layout['command.placement']+n*28)
            a,d=target['attack_coords'][slot],target['defence_coords'][slot]
            self.assertEqual(values,(index,target['attack'][slot],target['defence'][slot],a['position_x'],a['position_y'],d['position_x'],d['position_y']))

    def test_protect_can_switch_to_a_different_family_and_retains_outlet(self):
        spec,snap=fixture();snap.update(minute=80,score=[1,0],substitutions_left=0,windows_left=0)
        p=Manager(spec).propose(snap);target=Manager(spec).profile(p['profile_id'],'protect')
        self.assertNotEqual(target['family'],spec['base_profile']['family'])
        self.assertTrue(any(r in (11,12)for r in target['attack']))
        self.assertEqual(p['attack_level'],1)

    def test_protecting_two_goals_does_not_automatically_set_lowest_attack(self):
        spec,snap=fixture();snap.update(minute=80,score=[2,0])
        self.assertEqual(Manager(spec).propose(snap)['attack_level'],2)

    def test_actual_role_and_rounded_geometry_valid_for_every_strategy_and_style(self):
        for profile in templates.profiles():
            for kind in ('chase','protect'):
                for style in ('possession','short_counter','long_counter','side_attack','long_ball','overload'):
                    p=tactical_profile(profile,kind,style)
                    for phase in ('attack','defence'):templates.validate(p[phase+'_coords'])

    def test_failed_cross_shape_is_explained_and_abilities_are_unchanged(self):
        spec,snap=fixture();snap.update(minute=70,score=[0,2]);spec['minimum']=4000
        before=copy.deepcopy(spec);m=Manager(spec)
        self.assertIsNone(m.propose(snap));self.assertEqual(spec,before)
        self.assertEqual(m.state['last_decision']['reason'],'no_legal_plan')


if __name__=='__main__':unittest.main()
