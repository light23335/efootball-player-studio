import copy,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from playing_styles import apply_catalogue,definitions
from native_player import compile_player
from native_tables import player_record


class PlayingStyleCatalogueTests(unittest.TestCase):
    def old_catalogue(self):
        catalog=copy.deepcopy(app.CATALOG)
        catalog['PLAY_STYLES']['attack'].pop('22',None)
        catalog['PLAY_STYLES']['attack'].pop('35',None)
        return catalog

    def test_legacy_catalogue_restores_both_native_options_in_attack_group(self):
        result=apply_catalogue(self.old_catalogue())['PLAY_STYLES']
        self.assertEqual(result['attack']['22'],'站桩式中锋')
        self.assertEqual(result['attack']['35'],'高位防线门将')
        self.assertNotIn('22',result['defense']);self.assertNotIn('35',result['defense'])
        self.assertEqual(set(result['attack'])|set(result['defense']),set(map(str,range(36))))
        self.assertEqual(set(result['attack'])&set(result['defense']),{'0'})

    def test_known_phases_repaired_without_renaming_or_dropping_new_entries(self):
        catalog=self.old_catalogue()
        catalog['PLAY_STYLES']['attack']['13']='保留原库的名称'
        catalog['PLAY_STYLES']['attack']['36']='以后新增的进攻风格'
        catalog['PLAY_STYLES']['defense']['35']='高位防线门将'
        result=apply_catalogue(catalog)
        self.assertEqual(result['PLAY_STYLES']['attack']['13'],'保留原库的名称')
        self.assertEqual(result['PLAY_STYLES']['attack']['36'],'以后新增的进攻风格')
        self.assertIn('35',result['PLAY_STYLES']['attack']);self.assertNotIn('35',result['PLAY_STYLES']['defense'])
        self.assertEqual(apply_catalogue(copy.deepcopy(result)),result)

    def test_all_35_ids_have_a_single_verified_phase_and_position_rule(self):
        rows=definitions()
        self.assertEqual({r['id'] for r in rows},set(range(1,36)))
        self.assertEqual(sum(r['phase']=='attack' for r in rows),21)
        self.assertEqual(sum(r['phase']=='defense' for r in rows),14)
        for row in rows:
            self.assertTrue(row['label']);self.assertTrue(row['english']);self.assertTrue(row['positions'])
            self.assertIn(str(row['id']),app.CATALOG['PLAY_STYLES'][row['phase']])
        target=next(r for r in rows if r['id']==22)
        self.assertEqual((target['english'],target['runtime_id'],target['positions']),('Target Man',4,['CF']))

    def test_malformed_option_groups_raise_an_actionable_error(self):
        for value in ([],{'attack':[]}):
            with self.assertRaisesRegex(ValueError,'比赛风格'):
                apply_catalogue({'PLAY_STYLES':value})

    def test_target_man_and_high_line_keeper_save_and_share_native_parameter_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            store=app.Store(Path(folder)/'data')
            for ident in (22,35):
                p=app.default_project();p['identity']['name']='Style '+str(ident)
                p['play_style']={'attack':ident,'defense':33}
                store.save_player(p);store.save(p)
                self.assertEqual(app.Store(store.root).project['play_style'],p['play_style'])
                exported=store.export_project(p)
                self.assertEqual(store.import_project(exported['path'])['play_style'],p['play_style'])

    @unittest.skipUnless((Path(__file__).resolve().parents[2].parent/'73efootball安装包及资源/73efootball-V17.apk').is_file(),'requires original V17 APK')
    def test_importing_original_apk_cannot_replace_complete_options_with_partial_editor_table(self):
        from apk_literals import update_options
        apk=Path(__file__).resolve().parents[2].parent/'73efootball安装包及资源/73efootball-V17.apk'
        catalog=self.old_catalogue();update_options(apk,catalog)
        self.assertEqual(catalog['PLAY_STYLES']['attack']['22'],'站桩式中锋')
        self.assertEqual(catalog['PLAY_STYLES']['attack']['35'],'高位防线门将')

    def test_all_native_styles_reach_owned_payload_and_both_native_record_fields(self):
        with sqlite3.connect(app.RESOURCE/'library.sqlite3') as db:
            source=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
        load=lambda name:json.loads((app.RESOURCE/name).read_text('utf8'))
        costs=load('native-progression.json')['costs'];fields=load('native-player-fields.json')
        abilities=load('native-ability-bits.json');skills=load('native-skill-bits.json')
        template=bytes.fromhex(source['_studio_client_record'])
        for row in definitions():
            with self.subTest(style=row['id']):
                p=app.default_project();p['identity']['name']='Native Style'
                p['play_style']={'attack':0,'defense':0};p['play_style'][row['phase']]=row['id']
                identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
                result=compile_player(p,app.CATALOG,costs,identity,source,18,103,template)
                expected=[p['play_style']['attack'],p['play_style']['defense']]
                self.assertEqual(result['base_parameters'][61:63],expected)
                self.assertEqual(result['owned']['play_style'],expected)
                raw=int.from_bytes(player_record(template,p,result,fields,abilities,skills),'little')
                for key,value in zip(('style.in_possession','style.out_of_possession'),expected):
                    field=fields[key]
                    self.assertEqual((raw>>field['bit'])&((1<<field['width'])-1),value)


if __name__=='__main__':unittest.main()
