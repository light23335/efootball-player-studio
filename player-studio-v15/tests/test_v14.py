from pathlib import Path
import copy,json,sys,tempfile,types,unittest,sqlite3,contextlib,uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from user_data_upgrade import import_v13_data,refresh_v13_designs
from player_package import compatible_engine,PROFILE
from personal_runtime import sanitize_draw_effects,install_display_previews
from native_live import reserve_shared
import player_package as snapshots


class V14Tests(unittest.TestCase):
    def test_later_v13_design_sync_preserves_v14_edits_and_version_local_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,new=Path(tmp)/'v13',Path(tmp)/'v14';old.mkdir();(old/'players').mkdir()
            (old/'current-project.json').write_bytes(b'initial')
            (old/'players/one.json').write_bytes(b'first')
            import_v13_data(old,new)
            (new/'current-project.json').write_bytes(b'V14 edit')
            (new/'native-player-registry.json').write_bytes(b'keep native identity')
            (old/'current-project.json').write_bytes(b'new V13 current')
            (old/'players/one.json').write_bytes(b'updated')
            (old/'players/two.json').write_bytes(b'new saved player')
            (old/'assets').mkdir();(old/'assets/face.glb').write_bytes(b'new model')
            result=refresh_v13_designs(old,new)
            self.assertTrue(result['verified'])
            self.assertEqual((new/'players/one.json').read_bytes(),b'updated')
            self.assertEqual((new/'players/two.json').read_bytes(),b'new saved player')
            self.assertEqual((new/'assets/face.glb').read_bytes(),b'new model')
            self.assertEqual((new/'current-project.json').read_bytes(),b'V14 edit')
            self.assertEqual((new/'native-player-registry.json').read_bytes(),b'keep native identity')
            self.assertIn('current-project.json',result['preserved_v14_edits'])
            self.assertEqual((old/'players/one.json').read_bytes(),b'updated')
            self.assertFalse(refresh_v13_designs(old,new)['copied'])

    def test_special_walkout_and_preview_hooks_keep_original_prefix_and_separate_diagnostics(self):
        from personal_binding import compose
        import struct
        r=Path(__file__).resolve().parents[1]/'resources'
        original=json.loads((r/'native-binding-profile.json').read_text())
        profile=json.loads((r/'native-route-templates.json').read_text());profile['external_routes']=True
        for name in ('position','acquisition','rarity','overall'):profile[name+'_hook']=json.loads((r/('native-'+name+'-hook.json')).read_text())
        route={'cardId':95012443,'suiteDonorId':89135161919067,'portraitKey':'8012443','modelFaceKey':'8012443','club_id':108,'position':11,'maximum_overall':96,'presentation_rarity':10}
        result=compose(original,[route],profile)
        prefix=bytes.fromhex(original['blob_hex']);root=bytes.fromhex(result['blob_hex'])
        kept=result.get('root_prefix_bytes',len(prefix));self.assertEqual(root[:kept],prefix[:kept]);self.assertLessEqual(len(root),4096)
        self.assertEqual(result['route_header_bytes'],144)
        self.assertEqual(struct.unpack_from('<II',bytes.fromhex(result['route_table_hex']),136),(96,10))
        names={h['name'] for h in result['hooks']}
        self.assertTrue({'personal_v14_walkout_rarity','pack_preview_overall'}<=names)
        self.assertTrue(result['extension_native_fixups'])

    def test_snapshots_keep_two_draw_copies_and_released_initial_registration(self):
        with tempfile.TemporaryDirectory() as tmp,patch('player_package.native_fingerprint',return_value={'native_engine_sha256':'same-engine','release_id':'test'}):
            root=Path(tmp);db=root/'source.sqlite3';uid=str(uuid.uuid4());cid=99
            with contextlib.closing(sqlite3.connect(db)) as c, c:
                c.executescript('''create table meta(key text primary key,value text);
                    create table gameplayers(id integer,serial integer,json text,source text,acquired_at text,primary key(id,serial));
                    create table careerplan(id integer,serial integer,category text,points integer,at text);
                    create table squads(squad_id integer,json text);create table warehouse(id integer,serial integer);
                    create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
                    create table managed_serials(card_id text primary key,next_serial integer);
                    create table owned_identity_aliases(id integer,old_serial integer,new_serial integer,primary key(id,old_serial));''')
                reg={uid:{'card_id':cid,'serial':7,'design_revision':'original','future_metadata':{'keep':True}}}
                c.execute('insert into meta values(?,?)',(snapshots.REGISTRY_KEY,json.dumps(reg)))
                for serial,experience in ((8,200),(9,300)):
                    player={'gameplayer_id':{'id':cid,'serial':serial},'_personal_player_uuid':uid,'parameters':[40]*147,
                            'level_info':{'level':2,'level_limit':35,'exp_total':experience,'exp_current_level':0,'exp_to_next_level':100,'customize_point':2}}
                    c.execute('insert into gameplayers values(?,?,?,?,?)',(cid,serial,json.dumps(player),'personal','now'))
                c.execute('insert into managed_cards values(?,?,?,?,?,?)',(str(cid),'hash','{}','BigTime','','personal-player-studio:'+uid))
            previous=db
            for serial in (8,9):
                package=root/f'copy-{serial}.efplayer';output=root/f'copy-{serial}.sqlite3'
                snapshots.export_player(db,'unused.apk',cid,serial,package)
                snapshots.migration(previous,package,'unused.apk',output,'target');previous=output
            with contextlib.closing(snapshots.connect(previous,True)) as c:
                result=snapshots.registry(c)[uid]
                self.assertEqual(result['serial'],7);self.assertEqual(result['design_revision'],'original')
                self.assertEqual(result['future_metadata'],{'keep':True})
                self.assertTrue(snapshots.instance_binding(result,cid,8));self.assertTrue(snapshots.instance_binding(result,cid,9))
                self.assertEqual([row[0] for row in c.execute('select serial from gameplayers order by serial')],[8,9])
            with contextlib.closing(sqlite3.connect(previous)) as c, c:
                player=json.loads(c.execute('select json from gameplayers where serial=9').fetchone()[0]);player['level_info']['exp_total']+=1
                c.execute('update gameplayers set json=? where serial=9',(json.dumps(player),))
            with self.assertRaisesRegex(snapshots.PackageError,'更新的进度'):
                snapshots.migration(previous,root/'copy-9.efplayer','unused.apk',prefer='package')

    def test_versions_advance_across_v13_v14_and_concurrent_builds(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shared=root/'shared.json';old=root/'v13.json';local=root/'v14.json'
            old.write_text(json.dumps({'V13':{'last':120,'hashes':{'old':120}}}))
            t=lambda version:{'version_file':{'version':version}}
            first,_=reserve_shared(shared,local,'V14',t(80),'v14',(old,));self.assertEqual(first,121)
            back,_=reserve_shared(shared,old,'V13',t(100),'old');self.assertEqual(back,122)
            self.assertEqual(reserve_shared(shared,old,'V13',t(100),'old')[0],122)
            def reserve(i):return reserve_shared(shared,local,'V14' if i%2 else 'V13',t(80),'different-'+str(i))[0]
            with ThreadPoolExecutor(max_workers=8) as pool:versions=list(pool.map(reserve,range(16)))
            self.assertEqual(sorted(versions),list(range(123,139)))

    def test_import_keeps_ids_signing_and_assets_and_never_overwrites_v14_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'v13';new=root/'v14';old.mkdir()
            files={'current-project.json':b'{"package_id":"same","training":{"shooting":8}}',
                   'players/saved.json':b'{"uuid":"player"}','signing/key.pem':b'signing-key',
                   'assets/face.glb':b'face','packs.json':b'[{"uuid":"pack"}]',
                   'exports/progress.efplayer':b'progress','exports/old.apk':b'apk',
                   'runtime.json':b'stale-session','tmp/build.tmp':b'partial'}
            for rel,data in files.items():
                p=old/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            report=import_v13_data(old,new);self.assertTrue(report['verified'])
            for rel in ('current-project.json','players/saved.json','signing/key.pem','assets/face.glb','packs.json','exports/progress.efplayer'):
                self.assertEqual((new/rel).read_bytes(),files[rel])
            self.assertFalse((new/'runtime.json').exists());self.assertFalse((new/'exports/old.apk').exists())
            (new/'current-project.json').write_bytes(b'new-edit')
            self.assertIsNone(import_v13_data(old,new));self.assertEqual((new/'current-project.json').read_bytes(),b'new-edit')
            self.assertEqual((old/'current-project.json').read_bytes(),files['current-project.json'])

    def test_import_checksum_failure_leaves_source_and_destination_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            old,new=Path(tmp)/'v13',Path(tmp)/'v14';old.mkdir();(old/'current-project.json').write_bytes(b'original')
            def corrupt(source,target):Path(target).write_bytes(b'corrupt')
            with patch('user_data_upgrade.shutil.copy2',corrupt),self.assertRaisesRegex(ValueError,'校验失败'):
                import_v13_data(old,new)
            self.assertFalse(new.exists());self.assertEqual((old/'current-project.json').read_bytes(),b'original')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),['v13'])

    def test_migration_accepts_only_the_verified_forward_engine_pair(self):
        resource=Path(__file__).resolve().parents[1]/'resources'
        row=json.loads((resource/'migration-compatibility.json').read_text())['verified_upgrades'][0]
        a,b=row['source_engine'],row['target_engine']
        self.assertTrue(compatible_engine(a,b,PROFILE));self.assertTrue(compatible_engine(a,a,PROFILE))
        self.assertFalse(compatible_engine(b,a,PROFILE));self.assertFalse(compatible_engine(a,'unknown',PROFILE))
        self.assertFalse(compatible_engine(a,b,'unknown-layout'))

    def test_v14_big_time_scene_keeps_exact_owned_identity_and_training(self):
        response={'effect_list':[],'gameplayer_list':[{'gameplayer':{'gameplayer_id':{'id':99,'serial':7},'level_info':{'level':1},'parameters':[11]}}],
                  'special_gacha_effect_player_id':{'id':99,'serial':7}}
        doc={'game_version':'V14','players':[{'identity':{'previous_card_ids':[99]},'card_type':'BigTime'}],
             'draw_profiles':{'BigTime':['WIN_SCREEN','SPOTLIGHT_BIGWIN','RED_CARPET','PROMOTION_DRIBBLE']}}
        before=copy.deepcopy(response);sanitize_draw_effects(response,doc)
        self.assertEqual(response['effect_list'],doc['draw_profiles']['BigTime'])
        self.assertEqual(response['gameplayer_list'],before['gameplayer_list'])
        self.assertEqual(response['special_gacha_effect_player_id'],before['special_gacha_effect_player_id'])
        foreign=copy.deepcopy(before);foreign['gameplayer_list'][0]['gameplayer']['gameplayer_id']['id']=100
        saved=copy.deepcopy(foreign);sanitize_draw_effects(foreign,doc);self.assertEqual(foreign,saved)

    def test_custom_level_limit_reaches_existing_progression_aliases(self):
        def module(name,**values):m=types.ModuleType(name);vars(m).update(values);return m
        progression=module('editor_progression',card_level_cap=lambda c,p:40,state=lambda c,p:{'level_cap':40,'counts':{'shooting':8}})
        aliases=module('qa_cap_alias',cap=progression.card_level_cap,state=progression.state)
        gateway=type('Gateway',(),{'_use_agent':lambda self,resp,req:resp})
        modules={'editor_progression':progression,'developed_preview':module('developed_preview',developed=lambda p,b=None:p),
                 'club_store':module('club_store',wire_player=lambda p,*a,**k:copy.deepcopy(p)),
                 'gate_logic':module('gate_logic',GateLogic=gateway),'qa_cap_alias':aliases}
        doc={'players':[{'identity':{'package_id':'own','previous_card_ids':[99]},'owned':{'level_info':{'level_limit':75}}}]}
        with patch.dict(sys.modules,modules):
            install_display_previews(lambda:doc)
            p={'gameplayer_id':{'id':99,'serial':7},'level_info':{'level':20}}
            self.assertEqual(aliases.cap(None,p),75);self.assertEqual(aliases.state(None,p)['level_cap'],75)
            self.assertEqual(aliases.state(None,p)['counts'],{'shooting':8})
            self.assertEqual(aliases.cap(None,{'gameplayer_id':{'id':100}}),40)
            self.assertEqual(p['level_info'],{'level':20})


if __name__=='__main__':unittest.main()
