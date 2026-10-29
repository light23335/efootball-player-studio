import collections
import random
import unittest

import ai_tactical_profiles as t


class TacticalProfilesTests(unittest.TestCase):
    def test_all_eighteen_real_shapes_and_all_style_phase_layouts(self):
        seen = set()
        for p in t.profiles():
            self.assertEqual(len(p['attack']),11)
            self.assertEqual(len(p['defence']),11)
            self.assertEqual(p['attack'].count(0),1)
            seen.add(p['family'])
            for style in ('possession','short_counter','long_counter','side_attack','long_ball','overload'):
                a=t.coordinates(p,'attack',style);d=t.coordinates(p,'defence',style)
                t.validate(a);t.validate(d)
                self.assertEqual([r['role'] for r in a],list(p['attack']))
                self.assertEqual([r['role'] for r in d],list(p['defence']))
                self.assertNotEqual(a,d)
                for row in a+d:self.assertTrue(0<=row['position_x']<=48 and 0<=row['position_y']<=104)
        self.assertEqual(seen,{b[0] for b in t.BASES})

    def test_phase_pairs_change_lines_not_just_depth(self):
        for family in ('433','343','3421','424'):
            p=next(p for p in t.profiles() if p['family']==family)
            self.assertNotEqual(p['attack'],p['defence'])
        p=next(p for p in t.profiles() if p['family']=='3421')
        self.assertEqual(p['defence'].count(1)+p['defence'].count(2)+p['defence'].count(3),5)
        self.assertEqual(p['defence'].count(6)+p['defence'].count(7)+p['defence'].count(4)+p['defence'].count(5),4)

    def test_draw_family_and_midfield_odds_not_template_multiplicity(self):
        rng=random.Random(191514);families=collections.Counter();middle=collections.Counter()
        rows=t.profiles()
        for _ in range(3600):
            p=t.draw_order(rng,rows)[0];families[p['family']]+=1
            if p['family']=='442':middle[p['midfield_group']]+=1
        self.assertEqual(len(families),18)
        self.assertTrue(all(140<count<260 for count in families.values()),families)
        self.assertEqual(len(middle),3)
        self.assertTrue(all(40<count<100 for count in middle.values()),middle)

    def test_adjacent_draw_avoids_identical_variant(self):
        rng=random.Random(8);rows=t.profiles();previous=rows[0]['id']
        for _ in range(100):
            p=t.draw_order(rng,rows,previous)[0]
            self.assertNotEqual(p['id'],previous);previous=p['id']

    def test_structure_drives_substitute_coverage(self):
        for p in t.profiles():
            bench=t.bench_roles(p)
            self.assertEqual(len(bench),12);self.assertEqual(bench.count(0),1)
            if p['attack'].count(1)==3:
                self.assertGreaterEqual(bench.count(1),2)
                self.assertIn(8,bench,'Three-CB teams retain an attacking transition option instead of a mandatory third reserve CB')
            if p['attack'].count(12)+p['attack'].count(11)>=2:self.assertGreaterEqual(bench.count(12),2)

    def test_duties_use_abilities_strong_foot_and_only_actual_field(self):
        players=[{'parameters':[70]*147}for _ in range(23)]
        for i,p in enumerate(players):p['parameters'][0]=0 if i==0 else 5
        players[1]['parameters'][43]=0;players[2]['parameters'][43]=1
        # Same best crossing ability; corners prefer opposite strong feet.
        for i in (1,2):
            for k in (22,27,28):players[i]['parameters'][k]=90
        result=t.duties(players)
        self.assertEqual(result['set_piece_taker'][3:5],[1,2])
        self.assertNotEqual(result['set_piece_taker'][1],result['set_piece_taker'][2])
        self.assertEqual(len(set(result['df_overlap_setplay'])),3)
        # A departed first-choice kicker cannot retain the assignment.
        on=[0,2,3,4,5,6,7,8,9,10,12]
        result=t.duties(players,on)
        self.assertNotIn(1,result['set_piece_taker'])
        self.assertTrue(set(result['set_piece_taker'])<=set(on))
        self.assertNotIn(0,result['set_piece_taker'])


if __name__=='__main__':unittest.main()
