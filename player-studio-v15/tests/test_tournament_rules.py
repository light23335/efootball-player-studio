import copy,random,sys,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tournament_rules as r
from tournament_squads import assignment

def definition(n=8,stages=None):
 return {'uuid':str(uuid.uuid4()),'name':'Cup','enabled':True,'team_ids':list(range(1,n+1)),
  'player_team_id':1,'stages':stages or[{'type':'knockout','legs':1,'advance':1}]}

def play_all(s):
 while not s['completed']:
  pending=r.due(s)
  if not pending:r.advance(s);continue
  f=pending[0];score=[2,1]
  p=[5,4]if r.needs_decision(s,f,score)else None
  r.record(s,f['id'],*score,penalties=p)
 return s

class TournamentRulesTests(unittest.TestCase):
 def test_knockout_all_sizes_byes_and_receipts(self):
  for n in(2,3,5,8,16,31,64,128):
   s=play_all(r.start(definition(n),123))
   self.assertIn(s['champion'],range(1,n+1))
   self.assertEqual(sum(not f.get('bye')for f in s['fixtures']),n-1)
   f=next(f for f in s['fixtures']if not f.get('bye'))
   self.assertFalse(r.record(s,f['id'],*f['score'],penalties=f['penalties']))
   with self.assertRaises(ValueError):r.record(s,f['id'],9,9)
 def test_group_playoff_bypass_and_final(self):
  d=definition(12,[{'type':'groups','groups':4,'advance_per_group':1,'playoff_per_group':2},
                    {'type':'playoff','advance':4},{'type':'knockout','advance':1}])
  n=r.normalize(d);self.assertEqual([s['input_count']for s in n['stages']],[12,8,8])
  s=play_all(r.start(n,4));self.assertTrue(s['completed']);self.assertEqual(len(s['stage_history'][0]['tables']),4)
 def test_odd_league_has_byes_and_no_duplicate_pair(self):
  rounds=r.round_robin([1,2,3,4,5],2)
  self.assertEqual(len(rounds),10);seen=[]
  for games in rounds:
   people=[v for game in games for v in game];self.assertEqual(len(set(people)),len(people));seen.extend(games)
  self.assertEqual(len(set(seen)),20)
 def test_group_round_zero_means_complete_and_does_not_mutate_input(self):
  d=definition(6,[{'type':'league','rounds':0,'advance_per_group':1}]);old=copy.deepcopy(d)
  self.assertEqual(r.normalize(d)['stages'][0]['rounds'],5);self.assertEqual(d,old)
  s=play_all(r.start(d,0));self.assertEqual(len(s['fixtures']),15)
 def test_two_legs_away_goals_and_penalties(self):
  for away,needs in((False,True),(True,False)):
   s=r.start(definition(2,[{'type':'knockout','legs':2,'away_goals':away}]),0)
   f=r.due(s)[0];r.record(s,f['id'],2,1);last=r.due(s)[0]
   self.assertEqual(r.needs_decision(s,last,[1,0]),needs)
   r.record(s,last['id'],1,0,penalties=[4,5]if needs else None)
   self.assertTrue(s['completed'])
   if away:self.assertEqual(s['champion'],f['away'])
 def test_round_specific_single_leg_final(self):
  d=definition(8,[{'type':'knockout','legs':2,'round_overrides':{'2':{'legs':1}}}])
  s=play_all(r.start(d,7));self.assertEqual(len(s['fixtures']),13)
  final=s['fixtures'][-1];self.assertEqual(final['legs'],1);self.assertFalse(final['away_goals'])
 def test_invalid_out_of_order_score_and_unknown_fixture(self):
  s=r.start(definition(),2);f=r.due(s)[0]
  for args in((999,0,0),(f['id'],True,0),(f['id'],-1,0)):
   with self.assertRaises(ValueError):r.record(s,*args)
  with self.assertRaises(ValueError):r.record(s,f['id'],0,0)
 def test_preview_matches_actual_and_is_deterministic(self):
  d=definition(12,[{'type':'groups','groups':3,'advance_per_group':2},{'type':'knockout','advance':1}])
  a=r.preview(d);b=r.preview(d);self.assertEqual(a,b);self.assertEqual(a['matches'],23)
 def test_assignment_is_globally_optimal_unique_and_rejects_invalid_roles(self):
  self.assertEqual(assignment([[1,2],[2,100]]),[1,0])
  self.assertIsNone(assignment([[100000,100000],[1,2]]))
  self.assertIsNone(assignment([[1],[2]]))
  import itertools
  rng=random.Random(0)
  for _ in range(40):
   costs=[[rng.randrange(-120,-40)for _ in range(6)]for _ in range(4)]
   found=assignment(costs);best=min(sum(costs[i][j]for i,j in enumerate(p))for p in itertools.permutations(range(6),4))
   self.assertEqual(sum(costs[i][j]for i,j in enumerate(found)),best)

if __name__=='__main__':unittest.main()
