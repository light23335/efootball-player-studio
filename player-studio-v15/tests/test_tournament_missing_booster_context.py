"""Match native missing-record fallback only with compiled-table evidence."""
import copy,hashlib,types,unittest
from unittest.mock import patch
import division_squads
import tournament_sim_strength as strength
from test_tournament_sim_strength import document,team_snapshot,generator_fixture

def presence(ids=(7,8,136,258)):
    return {'revision':'v17-compiled-booster-presence-v1','ids':list(ids),
            'source_sha256':'1'*64,'missing_record_policy':'native-zero-record-0x823dfe4'}

class MissingBoosterContextTests(unittest.TestCase):
    def test_compiled_presence_uses_real_record_id_bits_and_digest(self):
        raw=b''.join((bid<<112).to_bytes(40,'little')for bid in(7,136,258))
        with patch('native_cpk.Cpk',return_value=types.SimpleNamespace(read=lambda _:raw)),patch('native_cpk.unwrap',side_effect=lambda x:x):
            out=division_squads.booster_catalogue(b'isolated CPK reader')
        self.assertEqual(out['ids'],[7,136,258]);self.assertEqual(out['source_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertNotIn(257,out['ids'])

    def test_proven_absent_native_record_does_not_block_start_ratings_or_change_player(self):
        doc=document();doc['native_booster_catalogue']=presence()
        team=team_snapshot();team['player_list'][10]['parameters'][145]=257;before=copy.deepcopy(team)
        baseline=team_snapshot();out=strength.ratings(team,document=doc);expected=strength.ratings(baseline,document=doc)
        for metric in ('attack','creation','defence','goalkeeping','depth'):self.assertEqual(out[metric],expected[metric])
        audit=out['audit']['players'][10]['player_boosters']
        self.assertTrue(next(b for b in audit if b['id']==257)['missing_native_record'])
        self.assertEqual(next(b for b in audit if b['id']==257)['applied_effects'],{})
        self.assertEqual(team,before)

    def test_present_record_missing_definition_and_unproven_absence_still_fail_closed(self):
        team=team_snapshot();team['player_list'][10]['parameters'][145]=257
        for catalogue in(None,presence((7,8,136,257)),dict(presence(),source_sha256=''),dict(presence(),ids=[])):
            with self.subTest(catalogue=catalogue):
                doc=document();doc['native_booster_catalogue']=catalogue
                with self.assertRaisesRegex(ValueError,'真实增能定义'):strength.ratings(team,document=doc)

    def test_actual_generator_freezes_presence_with_accepted_plan_and_keeps_original_tables(self):
        g,db,doc,proto=generator_fixture();self.addCleanup(db.close)
        doc['native_booster_catalogue']=presence();before=list(db.iterdump())
        with patch('ai_match_manager.prepare_strategies',return_value=None):team=g.build_club(db,proto,121,rng=__import__('random').Random(19),cpu=True)
        team['player_list'][0]['parameters'][145]=257
        frozen=strength.snapshot_for_ratings(team,g,db)
        self.assertEqual(frozen[strength.CONTEXT]['native_booster_catalogue'],presence())
        doc['native_booster_catalogue']['ids'].append(257)
        strength.ratings(frozen)
        self.assertNotIn(257,frozen[strength.CONTEXT]['native_booster_catalogue']['ids'])
        self.assertEqual(list(db.iterdump()),before)

if __name__=='__main__':unittest.main()
