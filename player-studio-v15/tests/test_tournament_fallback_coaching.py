"""Off-position tournament coaching never weakens ordinary AI divisions."""
import copy,unittest
from ai_match_manager import assignment,legal_assignment,substitution_pairs,pool_can_fill,prepare_strategies,APTITUDE_INDEX
from test_ai_match_manager import fixture


POLICY={'revision':'tournament-real-xi-fallback-v1','allow_incomplete_aptitude':True,
        'original_person_count':11,'standard_bench_only':True}


class TournamentFallbackCoachTests(unittest.TestCase):
 def shortage(self):
  spec,snapshot=fixture();spec['minimum']=0
  for row in spec['players']:row['parameters'][1:14]=[0]*13
  return spec,snapshot

 def test_only_explicit_tournament_shortage_allows_a_real_unfamiliar_starting_xi(self):
  spec,snapshot=self.shortage();original=copy.deepcopy(spec['players']);base=spec['base_profile']
  self.assertFalse(pool_can_fill(spec,snapshot['on_field'],base));self.assertIsNone(assignment(spec,snapshot,base))
  spec['tournament_fallback']=copy.deepcopy(POLICY)
  self.assertTrue(pool_can_fill(spec,snapshot['on_field'],base))
  found=legal_assignment(spec,snapshot,base)
  self.assertIsNotNone(found);self.assertEqual(set(found['mapping'].values()),set(snapshot['on_field']))
  gk_slot=base['attack'].index(0);self.assertEqual(found['mapping'][gk_slot],0)
  self.assertEqual(spec['players'],original)
  spec.pop('tournament_fallback');self.assertIsNone(assignment(spec,snapshot,base))

 def test_familiar_players_are_preferred_without_upgrading_aptitude(self):
  spec,snapshot=self.shortage();spec['tournament_fallback']=copy.deepcopy(POLICY)
  base=spec['base_profile'];slot=next(i for i,r in enumerate(base['attack'])if r!=0)
  a,d=base['attack'][slot],base['defence'][slot]
  spec['players'][1]['parameters'][APTITUDE_INDEX[a]]=2
  spec['players'][1]['parameters'][APTITUDE_INDEX[d]]=2
  found=assignment(spec,snapshot,base)
  self.assertIn(1,[i for s,i in found['mapping'].items()if base['attack'][s]==a and base['defence'][s]==d])

 def test_member_pairs_and_intermediate_roles_use_the_same_narrow_policy(self):
  spec,snapshot=self.shortage()
  self.assertIsNone(substitution_pairs(spec,snapshot,[12],[2]))
  spec['tournament_fallback']=copy.deepcopy(POLICY)
  self.assertEqual(substitution_pairs(spec,snapshot,[12],[2]),[(12,2)])
  for patch in({'original_person_count':10},{'allow_incomplete_aptitude':False},{'revision':'unknown'},{'standard_bench_only':False}):
   spec['tournament_fallback']={**POLICY,**patch}
   self.assertIsNone(assignment(spec,snapshot,spec['base_profile']))

 def test_preflight_rejects_invalid_or_unscoped_shortage_contract(self):
  with self.assertRaisesRegex(ValueError,'shortage policy'):
   prepare_strategies(None,[],{},'possession',{},0,tournament_fallback={})


if __name__=='__main__':unittest.main()
