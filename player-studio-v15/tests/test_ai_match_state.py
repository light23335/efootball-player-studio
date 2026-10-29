import copy
import unittest
from ai_match_state import decode_normal,decode_match


class StateTests(unittest.TestCase):
    def departed(self,indices=(8,),reason='direct_red'):
        raw=copy.deepcopy(self.raw)
        for p in raw['live']:p.update(yellow_count=0,direct_red=0,injury_state=0)
        for i in indices:raw['live'][i].update({reason:2 if reason=='yellow_count' else 1,'native_flag_4202':0,'stamina':-1})
        return raw

    def test_confirmed_native_departures_keep_actual_seven_to_ten(self):
        for count in range(7,11):
            for reason in ('yellow_count','direct_red','injury_state'):
                raw=self.departed(range(count,11),reason)
                state=decode_match(self.spec,raw)
                self.assertIsNotNone(state,(count,reason))
                self.assertEqual(state['on_field'],list(range(count)))
                self.assertTrue(set(range(count,11))<=set(state['unavailable']))
                self.assertEqual(state['state_source'],'v17_scoped_confirmed_reduced_lineup')
                self.assertIsNone(decode_normal(self.spec,raw))

    def test_departure_waits_for_original_emergency_and_never_invents_keeper(self):
        raw=self.departed()
        cases=[('still_active',lambda r:r['live'][8].update(native_flag_4202=1)),
               ('native_queue',lambda r:r.update(native_pending=1)),
               ('unknown_health',lambda r:r['live'][21].pop('injury_state')),
               ('below_seven',lambda r:[r['live'][i].update(direct_red=1,native_flag_4202=0)for i in range(6,11)]),
               ('keeper_departure',lambda r:r['live'][0].update(direct_red=1,native_flag_4202=0)),
               ('unknown_inactive',lambda r:r['live'][7].update(native_flag_4202=0)),
               ('unknown_flag',lambda r:r['live'][8].update(native_flag_4218=3))]
        for name,change in cases:
            r=copy.deepcopy(raw);change(r)
            self.assertIsNone(decode_match(self.spec,r),name)

    def setUp(self):
        self.spec={'entry_id':'A','game_id':123,'players':[{} for _ in range(23)]}
        self.raw={'entry_id':'A','game_id':123,'sequence':2,'team':1,'period':3,'phase':1,
                  'clock_frames':36000.,'score':[2,1],'substitutions_left':5,'windows_left':3,
                  'native_pending':0,'live':[{'expected_index':i,'lineup_slot':i,'physical_index':i,
                    'stamina':80 if i<11 else 100,'native_flag_4202':1 if i<11 else 0,
                    'native_flag_4218':0,'eligible':1,'attack_role':0 if i==0 else 5 if i<11 else 255,
                    'defence_role':0 if i==0 else 5 if i<11 else 255}for i in range(23)]}

    def test_normal_play_and_stoppage_have_separate_permissions(self):
        state=decode_normal(self.spec,self.raw)
        self.assertEqual((state['minute'],state['period_end']),(55.,90))
        self.assertTrue(state['safe_to_queue']);self.assertFalse(state['safe_to_change'])
        self.assertTrue(state['native_formation_window'])
        self.raw['phase']=2;state=decode_normal(self.spec,self.raw)
        self.assertEqual(state['phase'],'stoppage');self.assertTrue(state['safe_to_change'])

    def test_breaks_use_verified_boundary_and_no_play_counter(self):
        self.raw.update(phase=2,clock_frames=0.,windows_left=0)
        for period,minute in ((2,45),(4,90),(6,105)):
            self.raw['period']=period;state=decode_normal(self.spec,self.raw)
            self.assertEqual((state['phase'],state['minute']),('halftime',minute))
            self.assertTrue(state['safe_to_queue'])
        self.raw['clock_frames']=3600;self.assertIsNone(decode_normal(self.spec,self.raw))

    def test_demo_pause_replay_unknown_and_penalties_stay_undecoded(self):
        for phase in (0,3,4,5,99):
            self.raw['phase']=phase;self.assertIsNone(decode_normal(self.spec,self.raw))
        self.raw['phase']=1
        for period in (0,2,4,6,8,9,10,99):
            self.raw['period']=period;self.assertIsNone(decode_normal(self.spec,self.raw))

    def test_abnormal_field_yields_without_guessing_discipline(self):
        for key,value in (('native_flag_4202',0),('native_flag_4218',1)):
            raw=copy.deepcopy(self.raw);raw['live'][5][key]=value
            self.assertIsNone(decode_normal(self.spec,raw))
        state=decode_normal(self.spec,self.raw)
        self.assertNotIn('yellow_risk',state)
        self.assertIn('unknown',state['discipline_source'])

    def test_original_substitute_remains_active_with_candidate_flag_zero(self):
        self.raw['live'][7].update(expected_index=18,physical_index=18,eligible=0)
        self.raw['live'][18].update(expected_index=7,physical_index=7,eligible=0,stamina=-1)
        state=decode_normal(self.spec,self.raw)
        self.assertIsNotNone(state);self.assertIn(18,state['on_field'])
        self.assertEqual(state['stamina']['18'],80);self.assertEqual(state['unavailable'],[7])

    def test_bench_unavailable_and_physical_reordering(self):
        self.raw['live'][15].update(eligible=0,stamina=-1)
        self.raw['live'][7]['expected_index']=18;self.raw['live'][18]['expected_index']=7
        self.raw['live'][7]['physical_index']=18;self.raw['live'][18]['physical_index']=7
        state=decode_normal(self.spec,self.raw)
        self.assertIn(18,state['on_field']);self.assertIn(7,state['bench'])
        self.assertNotIn(15,state['bench']);self.assertEqual(state['unavailable'],[15])
        self.assertEqual(state['roles']['18'],5)

    def test_stale_entry_duplicates_and_nonfinite_energy_rejected(self):
        for alter in (lambda r:r.update(entry_id='old'),lambda r:r.update(game_id=999),
                      lambda r:r['live'][15].update(expected_index=1),
                      lambda r:r['live'][15].update(physical_index=1),
                      lambda r:r['live'][5].update(stamina=float('nan'))):
            raw=copy.deepcopy(self.raw);alter(raw);self.assertIsNone(decode_normal(self.spec,raw))

    def test_native_pending_and_budget_are_not_overridden(self):
        self.raw.update(native_pending=1)
        self.assertFalse(decode_normal(self.spec,self.raw)['safe_to_queue'])
        self.assertFalse(decode_normal(self.spec,self.raw)['native_formation_window'])
        self.raw.update(native_pending=0,substitutions_left=0)
        self.assertFalse(decode_normal(self.spec,self.raw)['safe_to_queue'])
        self.raw.update(substitutions_left=5,windows_left=0)
        self.assertFalse(decode_normal(self.spec,self.raw)['safe_to_queue'])

    def test_receipt_keeps_accepted_distinct_from_applied(self):
        self.raw.update(ack_id=6,ack_status='accepted',rejection_reason=0)
        state=decode_normal(self.spec,self.raw)
        self.assertEqual(state['ack_status'],'accepted');self.assertEqual(state['ack_id'],6)

    def test_verified_card_fields_distinguish_yellow_risk_from_native_emergency(self):
        for p in self.raw['live']:p.update(yellow_count=0,direct_red=0,injury_state=0)
        self.raw['clock_frames']=25*3600.
        actor=self.raw['live'][5];actor.update(yellow_count=1,stamina=50,attack_role=4)
        state=decode_normal(self.spec,self.raw)
        self.assertEqual(state['yellow_risk'],{'5':'high'})
        self.assertFalse(state['discipline']['5']['dismissed'])
        # One yellow alone is not a forced-substitution rule.
        actor['stamina']=90;self.assertNotIn('yellow_risk',decode_normal(self.spec,self.raw))
        for key,value in (('yellow_count',2),('direct_red',1),('injury_state',1)):
            raw=copy.deepcopy(self.raw);raw['live'][5][key]=value
            self.assertIsNone(decode_normal(self.spec,raw))
        self.raw['live'][15]['injury_state']=1
        self.assertNotIn(15,decode_normal(self.spec,self.raw)['bench'])

    def test_invalid_discipline_never_falls_back_to_normal(self):
        for p in self.raw['live']:p.update(yellow_count=0,direct_red=0,injury_state=0)
        for key,value in (('yellow_count',255),('direct_red',2),('injury_state',-1),('yellow_count',None)):
            raw=copy.deepcopy(self.raw);raw['live'][5][key]=value
            self.assertIsNone(decode_normal(self.spec,raw))


if __name__=='__main__':unittest.main()
