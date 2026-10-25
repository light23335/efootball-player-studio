from pathlib import Path
import copy,json,sqlite3,struct,sys,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from personal_binding import compose,reserve_asset_key,_BindingCtypes,relocate_code
from native_strings import read,write,wrap,unwrap,merge,booster_rows
from personal_runtime import apply_coaches,apply_definitions,training_hash
from native_tables import weekly_table
from personal_runtime import developed_personal,sanitize_draw_effects,draw_response_fields
from overall import maximum_development
RESOURCE=Path(__file__).resolve().parents[1]/'resources'

class PersonalResourceTests(unittest.TestCase):
    def test_coach_text_matches_native_getter_offsets_and_keeps_legacy_id(self):
        from native_cpk import wrap,unwrap
        from native_coaches import compile_coaches,COACH,BOOSTER,TACTICS
        empty=struct.pack('<BBB5sII',255,0x21,0x83,b'WESYS',0,0)
        template=bytearray(176);struct.pack_into('<Q',template,0,8)
        template[170:176]=b'KEEPME'
        files={COACH:wrap(bytes(template),empty),BOOSTER:wrap(bytes(4),empty)}
        class Archive:
            def read(self,name):return files[name]
        coach={'uuid':'existing-personal-coach','name':'自建教练','name_en':'Personal Coach',
               'tactics':dict.fromkeys(TACTICS,88),'effects':{}}
        registry={'coaches':{coach['uuid']:96916098}}
        resources,owned=compile_coaches(Archive(),[coach],[{'id':'8','age':40,'raw_payload':{}}],registry)
        raw=unwrap(resources[COACH]);self.assertEqual(len(raw),352)
        self.assertEqual(raw[:176],bytes(template))
        row=raw[176:];self.assertEqual(struct.unpack_from('<Q',row)[0],96916098)
        # Native code: add x0,x0,#0x20 / add x0,x0,#0x4e.
        self.assertEqual(row[0x20:].split(b'\0',1)[0].decode(),'自建教练')
        self.assertEqual(row[0x4e:].split(b'\0',1)[0].decode(),'Personal Coach')
        self.assertEqual(row[170:],b'KEEPME')
        self.assertEqual(owned[0]['id'],96916098)
        with self.assertRaisesRegex(ValueError,'45'):
            compile_coaches(Archive(),[dict(coach,name_en='a'*46)],[{'id':'8','age':40,'raw_payload':{}}],registry)

    def test_global_preview_scores_survive_hash_collisions_updates_and_relocation(self):
        import ctypes
        import personal_binding as binding
        old_tables=list(binding._PREVIEW_TABLES);old_scores=dict(binding._PREVIEW_SCORES)
        try:
            binding._PREVIEW_TABLES.clear();binding._PREVIEW_SCORES.clear()
            original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
            profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
            profile.update(external_routes=True,overall_hook=json.loads((RESOURCE/'native-overall-hook.json').read_text()))
            payload=compose(original,[{'cardId':90000001,'suiteDonorId':90000001,'portraitKey':'8012443','modelFaceKey':'8012443'}],profile)
            binding.set_preview_score(65535,96)
            memory=_BindingCtypes(ctypes,payload);table=binding._PREVIEW_TABLES[-1]
            # Both keys start at the last slot and force a wrap to slot zero.
            binding.set_preview_score(131071,102);binding.set_preview_score(65535,97)
            self.assertEqual(struct.unpack_from('<QI',table,65535*16),(65535,97))
            self.assertEqual(struct.unpack_from('<QI',table,0),(131071,102))
            self.assertEqual(struct.unpack_from('<Q',memory.table,40)[0],ctypes.addressof(table))
            self.assertEqual(payload['hooks'][-1]['name'],'pack_preview_overall')
            with self.assertRaises(ValueError):binding.set_preview_score(5,0)
        finally:
            binding._PREVIEW_TABLES[:]=old_tables;binding._PREVIEW_SCORES.clear();binding._PREVIEW_SCORES.update(old_scores)

    def test_v14_bt_series_precedes_shared_legendary_type_and_retains_owned_identity(self):
        profiles=json.loads((RESOURCE/'native-draw-profiles.json').read_text())
        profiles['player_selection']='explicit'
        bt={'gameplayer_id':{'id':123,'serial':987},'type':'LEGENDARY',
            '_draw_gacha_v1':{'card_type':'Big Time','pickup':True}}
        before=copy.deepcopy(bt);result=draw_response_fields([bt],profiles)
        self.assertIn('OPENING_BIGTIME',result['effect_list'])
        self.assertNotIn('OPENING_EPIC',result['effect_list'])
        self.assertEqual(result['special_gacha_effect_player_id'],bt['gameplayer_id'])
        self.assertEqual(bt,before)
        epic=copy.deepcopy(bt);epic['_draw_gacha_v1']['card_type']='Epic'
        self.assertIn('OPENING_EPIC',draw_response_fields([epic],profiles)['effect_list'])
        # Original managed-card categories can say Epic for a dated BT card.
        self.assertIn('OPENING_BIGTIME',draw_response_fields([epic],profiles,{'123':'BigTime'})['effect_list'])
        show=copy.deepcopy(bt);show['_draw_gacha_v1']['card_type']='ShowTime'
        self.assertIn('OPENING_SHOWTIME',draw_response_fields([show],profiles)['effect_list'])
        standard=copy.deepcopy(bt);standard['_draw_gacha_v1']['card_type']='Standard';standard['type']='NORMAL'
        self.assertEqual(draw_response_fields([standard],profiles)['effect_list'],[])
        self.assertEqual(draw_response_fields([standard,bt,bt],profiles)['pickup_cardtype_list'],[{'id':123,'serial':0}])

    def test_single_walkout_native_selection_keeps_actual_owned_player_and_series(self):
        profiles=json.loads((RESOURCE/'native-draw-profiles.json').read_text())
        profiles['player_selection']='auto'
        player={'gameplayer_id':{'id':123,'serial':987},'_draw_gacha_v1':{'card_type':'BigTime','pickup':True}}
        before=copy.deepcopy(player)
        result=draw_response_fields([player],profiles)
        self.assertEqual(result['special_gacha_effect_player_id'],{'id':0,'serial':0})
        self.assertIn('OPENING_BIGTIME',result['effect_list'])
        self.assertEqual(player,before)

    def test_failed_apk_build_removes_only_its_own_scratch_folder(self):
        import tempfile,types
        from native_package import NativePackage
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'tmp').mkdir();(root/'tmp/unrelated.txt').write_bytes(b'keep')
            (root/'assets').mkdir();(root/'assets/original.glb').write_bytes(b'keep model')
            package=NativePackage(types.SimpleNamespace(store=types.SimpleNamespace(root=root)),root,'')
            package._worker({'projects':[{'identity':{'name':'QA draft'}}],'apk':'missing.apk'})
            self.assertEqual(package.status()['phase'],'error')
            self.assertEqual([p.name for p in (root/'tmp').iterdir()],['unrelated.txt'])
            self.assertEqual((root/'assets/original.glb').read_bytes(),b'keep model')

    def test_multi_walkout_uses_scene_selection_without_reordering_or_editing_receipts(self):
        profiles=json.loads((RESOURCE/'native-draw-profiles.json').read_text())
        for series in ('BigTime','Epic','ShowTime'):
            players=[{'gameplayer_id':{'id':123+i%3,'serial':987+i},'level_info':{'level':1},
                      '_draw_gacha_v1':{'card_type':series,'pickup':True}} for i in range(10)]
            before=copy.deepcopy(players);result=draw_response_fields(players,profiles)
            self.assertEqual(result['special_gacha_effect_player_id'],{'id':0,'serial':0})
            self.assertEqual(result['effect_list'],profiles[series])
            self.assertEqual(result['pickup_cardtype_list'],[{'id':123+i,'serial':0} for i in range(3)])
            self.assertEqual(players,before)

    def test_custom_booster_summary_tracks_effects_instead_of_template_value(self):
        from native_tables import booster_table,BOOSTER_BITS
        donor=(76<<112)|(3<<212)|(3<<BOOSTER_BITS['14'])
        raw=donor.to_bytes(40,'little')
        project={'booster_ids':[1000],'custom_boosters':[{'id':1000,'effects':{'14':4,'20':7}}]}
        result=booster_table(raw,[project])
        row=next(int.from_bytes(result[i:i+40],'little') for i in range(0,len(result),40) if (int.from_bytes(result[i:i+40],'little')>>112)&1023==1000)
        self.assertEqual((row>>212)&31,7)
        self.assertEqual((row>>BOOSTER_BITS['14'])&31,4)
        self.assertEqual((row>>BOOSTER_BITS['20'])&31,7)
        self.assertEqual(result[:40],raw)

    def test_special_card_cannot_export_without_acquisition_portrait_directory(self):
        from native_art import verify_portrait_locations
        binding={'asset_key':'8123456','card_aliases':{'0501_f09_99_':'8123456_date'}}
        base='/Game/Assets/ui/Data/Thumbnail/Player/'
        names=['8123456_','8123456f','8123456_date']
        root=[(base+n,b'',{}) for n in names]
        with self.assertRaisesRegex(ValueError,'Variation2022'):verify_portrait_locations(root,binding)
        complete=root+[(base+'Variation2022/'+n,b'',{}) for n in names]
        self.assertEqual(verify_portrait_locations(complete,binding)['textures_per_location'],3)
        with self.assertRaisesRegex(ValueError,'date'):verify_portrait_locations(complete[:-1],binding)

    def test_game_thumbnail_browser_resolves_small_alias_without_large_art(self):
        import tempfile,types,contextlib
        from native_library import NativeLibrary
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);db=folder/'library.sqlite3'
            with contextlib.closing(sqlite3.connect(db)) as c, c:
                c.executescript('''create table assets(id text,kind text,name text,path text,player_key text);
                    create table players(id text,base_id text,name text,name_en text,search text);
                    create table card_aliases(before text,after text);''')
                c.executemany('insert into assets values(?,?,?,?,?)',[
                    ('small','portrait','56321_','PesMobile/small','56321'),
                    ('duplicate','portrait','56321_','IDSPUCL27/small','56321'),
                    ('large','portrait','56321_l','PesMobile/large','56321')])
                c.execute('insert into players values(?,?,?,?,?)',('89135111111111','7','测试球员','Test Player','测试球员 test player'))
                c.execute('insert into card_aliases values(?,?)',('89135111111111_','56321_'))
            library=NativeLibrary.__new__(NativeLibrary);library.resources=folder;library.cache={};library.store=types.SimpleNamespace(root=folder)
            with contextlib.closing(library.db()) as c:self.assertEqual(library._thumbnail(c,'89135111111111','7'),'small')
            result=library.assets({'kind':'thumbnail','query':'test player'})
            self.assertEqual([r['id'] for r in result['rows']],['small'])

    def test_personal_single_draw_does_not_inherit_captured_revival_pair(self):
        doc={'players':[{'identity':{'previous_card_ids':[99]}}]}
        original={'effect_list':['WIN_SCREEN','SPOTLIGHT_BIGWIN','RED_CARPET','PROMOTION_DRIBBLE','REVIVAL_SOLO'],
                  'gameplayer_list':[{'gameplayer':{'gameplayer_id':{'id':99,'serial':5},'parameters':[11]}}]}
        response=copy.deepcopy(original);sanitize_draw_effects(response,doc)
        self.assertEqual(response['effect_list'],original['effect_list'][:-1])
        self.assertEqual(response['gameplayer_list'],original['gameplayer_list'])
        foreign=copy.deepcopy(original);foreign['gameplayer_list'][0]['gameplayer']['gameplayer_id']['id']=100
        saved=copy.deepcopy(foreign);sanitize_draw_effects(foreign,doc);self.assertEqual(foreign,saved)

    def test_match_lod_folds_removed_face_bones_and_preserves_geometry(self):
        import numpy as np
        from native_mesh import head_arrays,retained_bone_map,make_lod,read_lod
        class Head:
            doc={'skins':[{'joints':list(range(16))}],
                 'nodes':[{'children':[i+1]} if i<7 else ({'children':list(range(8,16))} if i==7 else {}) for i in range(16)]}
            arrays={'p':np.arange(300,dtype=float).reshape(100,3)*.001,
                    'n':np.tile([0.,1.,0.],(100,1)),'uv':np.zeros((100,2)),
                    'j':np.tile([4,7,8,14],(100,1)),'w':np.tile([.1,.2,.3,.4],(100,1)),
                    'i':np.arange(99).reshape(-1,1)}
            def head(self):return {'attributes':dict(POSITION='p',NORMAL='n',TEXCOORD_0='uv',JOINTS_0='j',WEIGHTS_0='w'),'indices':'i'}
            def read(self,key):return self.arrays[key].copy()
        g=Head();before=head_arrays(g,16);mapping=retained_bone_map(g,range(8))
        result=head_arrays(g,16,bone_remap=mapping)
        self.assertEqual(result['bones'],[4,7]);self.assertEqual(mapping[8:],[7]*8)
        self.assertTrue(np.array_equal(before['positions'],result['positions']))
        self.assertTrue(np.array_equal(before['faces'],result['faces']))
        self.assertTrue(np.all(result['skin'][:,4:].sum(axis=1)==255))
        self.assertTrue(np.allclose(result['skin'][0,4:6],[26,229],atol=1))
        template={'required':np.arange(16,dtype='<u2').tobytes(),'active':np.arange(8,dtype='<u2').tobytes(),'nuv':1}
        lod=read_lod(make_lod(template,result),0)
        self.assertEqual(set(lod['sections'][0]['bones']),{4,7})
        self.assertEqual(np.frombuffer(lod['active'],dtype='<u2').tolist(),list(range(8)))

    def test_multiple_ids_share_art_without_changing_original_hooks(self):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile['boosters']=[{'id':1000,'name':74860000,'description':74860001}]
        profile['text_hooks']=json.loads((RESOURCE/'native-text-hooks.json').read_text())
        routes=[{'cardId':95012443,'suiteDonorId':89135161919067,'portraitKey':'8012443','modelFaceKey':'8012443'},
                {'cardId':89135161919067,'suiteDonorId':89135161919067,'portraitKey':'8012443','modelFaceKey':'8012443'}]
        result=compose(original,routes,profile);blob=bytes.fromhex(result['blob_hex'])
        self.assertTrue(blob.startswith(bytes.fromhex(original['blob_hex'])[:profile.get('root_prefix_bytes',len(bytes.fromhex(original['blob_hex'])))]))
        self.assertEqual(len(result['hooks']),9);self.assertLessEqual(len(blob),8192)
        self.assertEqual(len(result['absolute_fixups']),6)
        many=[dict(routes[0],cardId=i+90000000) for i in range(800)]
        self.assertGreater(len(bytes.fromhex(compose(original,many,profile)['blob_hex'])),4096)
        with self.assertRaises(ValueError):compose(original,routes+routes,profile)

    def test_native_absolute_pointers_are_relocated_from_verified_base(self):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        original['absolute_fixups']=[[len(bytes.fromhex(original['blob_hex'])),123456]]
        original['blob_hex']+='00'*8
        source=bytearray.fromhex(original['blob_hex']);base=0x7000000000
        struct.pack_into('<Q',source,original['back_fixup'],base+original['hooks'][0]['address']+4)
        class Memory:
            def memmove(self,dest,src,size):return src
        result=_BindingCtypes(Memory(),original).memmove(5,bytes(source),len(source))
        self.assertEqual(struct.unpack_from('<Q',result,len(source)-8)[0],base+123456)

    def test_art_key_is_separate_stable_and_collision_checked(self):
        registry={};key=reserve_asset_key('permanent-player',set(),registry)
        self.assertEqual(len(key),7);self.assertEqual(key,reserve_asset_key('permanent-player',set(),registry))
        with self.assertRaises(ValueError):reserve_asset_key('permanent-player',{int(key)},registry)

    def test_club_hooks_keep_original_fallback_and_use_extended_rows(self):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile['club_emblems']=True
        routes=[{'cardId':pid,'suiteDonorId':89135161919067,'portraitKey':'8012443',
                 'modelFaceKey':'8012443','club_id':108} for pid in
                (8012443,95012443,89135161919067,105816546461275)]
        result=compose(original,routes,profile);blob=bytes.fromhex(result['blob_hex'])
        self.assertTrue(blob.startswith(bytes.fromhex(original['blob_hex'])[:profile.get('root_prefix_bytes',len(bytes.fromhex(original['blob_hex'])))]))
        for name in ('henry_arsenal_card_emblem','henry_arsenal_squad_emblem'):
            old=next(h for h in original['hooks'] if h['name']==name)
            new=next(h for h in result['hooks'] if h['name']==name)
            self.assertGreater(new['offset'],len(bytes.fromhex(original['blob_hex'])))
            self.assertNotEqual(old['offset'],new['offset'])
        for row in routes:
            at=blob.index(struct.pack('<QQ',row['cardId'],row['suiteDonorId']))
            self.assertEqual(struct.unpack_from('<II',blob,at+128),(108<<14,13))
        profile['boosters']=[{'id':1000,'name':74860000,'description':74860001}]
        profile['text_hooks']=json.loads((RESOURCE/'native-text-hooks.json').read_text())
        self.assertLessEqual(len(bytes.fromhex(compose(original,routes,profile)['blob_hex']))-len(bytes.fromhex(original['blob_hex'])),2048)
        with self.assertRaises(ValueError):compose(original,[dict(routes[0],club_id=65536)],profile)

    def test_fixed_B_preserves_original_weekly_rows_including_duplicates(self):
        source=struct.pack('<QIIQII',7511,1,2,7511,2,1)
        cid=(0x51<<40)|95012443;previous=(0x10<<40)|95012443
        definition={'identity':{'card_id':cid,'person_id':95012443,'previous_card_ids':[previous,cid]}}
        result,count=weekly_table(source,[{'card_type':'BigTime'}],[definition],[{'asset_key':'8012443'}])
        self.assertTrue(result.startswith(source));self.assertEqual(count,4)
        added=list(struct.iter_unpack('<QII',result[len(source):]))
        self.assertEqual({r[0] for r in added},{cid,previous,95012443,8012443})
        self.assertEqual([r[1] for r in added],[3,4,5,6]);self.assertEqual({r[2] for r in added},{3})
        for kind in ('Epic','Legendary'):
            self.assertEqual(weekly_table(source,[{'card_type':kind}],[definition])[1],3)
        self.assertEqual(weekly_table(source,[{'card_type':'Standard'}],[definition]),(source,0))
        with self.assertRaises(ValueError):weekly_table(source+b'x',[],[])

    def test_position_hook_uses_native_enum_and_preserves_foreign_players(self):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile['position_hook']=json.loads((RESOURCE/'native-position-hook.json').read_text())
        result=compose(original,[{'cardId':95012443,'suiteDonorId':89135161919067,
                       'portraitKey':'8012443','modelFaceKey':'8012443','club_id':108,'position':11}],profile)
        h=result['hooks'][-1];self.assertEqual(h['name'],'personal_walkout_position')
        blob=bytes.fromhex(result['blob_hex']);self.assertEqual(blob[h['offset']+76:h['offset']+84],bytes.fromhex('00d440b9c0035fd6'))
        at=blob.index(struct.pack('<QQ',95012443,89135161919067))
        self.assertEqual(struct.unpack_from('<II',blob,at+128),(108<<14,11))

    def test_large_batch_keeps_native_code_in_one_page_and_relocates_data_table(self):
        import ctypes
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile.update(club_emblems=True,external_routes=True,position_hook=json.loads((RESOURCE/'native-position-hook.json').read_text()))
        routes=[{'cardId':90000000+i,'suiteDonorId':89135161919067,'portraitKey':'8012443',
                 'modelFaceKey':'8012443','club_id':108,'position':11} for i in range(1000)]
        payload=compose(original,routes,profile);blob=bytearray.fromhex(payload['blob_hex'])
        self.assertLessEqual(len(blob),8192);self.assertEqual(len(bytes.fromhex(payload['route_table_hex'])),1001*136)
        class Memory:
            create_string_buffer=staticmethod(ctypes.create_string_buffer)
            addressof=staticmethod(ctypes.addressof)
            def memmove(self,dest,source,size):return source
        memory=_BindingCtypes(Memory(),payload)
        struct.pack_into('<Q',blob,payload['back_fixup'],0x7000000000+payload['hooks'][0]['address']+4)
        if payload.get('extension_blob_hex'):
            prefix,extension=relocate_code(payload,bytes(blob),0x7100000000,0x7300000000,ctypes.addressof(memory.table)+payload['route_header_bytes'])
            pointer=struct.unpack_from('<Q',extension,payload['extension_route_pointer_fixup'])[0]
            self.assertEqual(prefix[:payload.get('root_prefix_bytes',len(bytes.fromhex(original['blob_hex'])))],bytes(blob[:payload.get('root_prefix_bytes',len(bytes.fromhex(original['blob_hex'])))]))
            for at,relative in payload['extension_entry_fixups']:self.assertEqual(struct.unpack_from('<Q',prefix,at)[0],0x7300000000+relative)
            for at,relative in payload['extension_prefix_fixups']:self.assertEqual(struct.unpack_from('<Q',extension,at)[0],0x7100000000+relative)
        else:
            result=memory.memmove(0,bytes(blob),len(blob))
            pointer=struct.unpack_from('<Q',result,payload['route_pointer_fixup'])[0]
        self.assertEqual(ctypes.string_at(pointer,len(bytes.fromhex(payload['route_table_hex']))),bytes.fromhex(payload['route_table_hex']))

    def test_draw_rating_binding_contains_maximum_and_keeps_owned_state_separate(self):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile.update(external_routes=True,acquisition_hook=json.loads((RESOURCE/'native-acquisition-hook.json').read_text()))
        route={'cardId':90000001,'suiteDonorId':90000001,'portraitKey':'8012443',
               'modelFaceKey':'8012443','club_id':108,'position':11,'maximum_overall':96}
        result=compose(original,[route],profile)
        table=bytes.fromhex(result['route_table_hex'])
        self.assertEqual(struct.unpack_from('<III',table,128),(108<<14,11,96))
        self.assertEqual(result['hooks'][-1]['address'],profile['acquisition_hook']['address'])
        fixups=result['extension_native_fixups'] if result.get('extension_blob_hex') else result['absolute_fixups']
        self.assertEqual(fixups[-1][1],profile['acquisition_hook']['converter'])
        with self.assertRaises(ValueError):compose(original,[dict(route,maximum_overall=0)],profile)

    def test_thumbnail_crop_is_independent_and_uses_selected_source(self):
        import tempfile
        from PIL import Image
        from native_thumbnail import render
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);Image.new('RGBA',(10,20),(255,0,0,255)).save(root/'red.png')
            Image.new('RGBA',(20,10),(0,0,255,255)).save(root/'blue.png')
            p={'appearance':{'portrait':'red.png','thumbnail_image':'blue.png','thumbnail_mode':'portrait'}}
            fallback=Image.new('RGBA',(20,30),(0,255,0,255))
            self.assertEqual(render(p,root,fallback).getpixel((256,256)),(255,0,0,255))
            p['appearance']['thumbnail_mode']='image'
            self.assertEqual(render(p,root,fallback).getpixel((256,256)),(0,0,255,255))
            p['appearance']['thumbnail_mode']='card'
            self.assertEqual(render(p,root,fallback).getpixel((256,256)),(0,255,0,255))

    def test_maximum_rating_uses_level_cap_and_never_mutates_owned_training(self):
        catalog={'ABILITIES':{'14':'A','20':'B'},'stat_keys':['a','b'],'POSITIONS':['SS'],
                 'training_groups':[{'id':'a','indices':[14]},{'id':'b','indices':[20]}],
                 'boosters':[],'ovr_weights':{'SS':{'intercept':0,'abilities':{'a':.6,'b':.4}}}}
        p={'identity':{'position':'SS'},'base_abilities':{'14':70,'20':80},'training':{'a':1,'b':0},
           'max_level':5,'initial_level':1,'card_type':'BigTime','booster_ids':[],'preview':{}}
        before=copy.deepcopy(p);maximum=maximum_development(p,catalog)
        brute=max(.6*(70+a)+.4*(80+b) for a in range(9) for b in range(9)
                  if sum(1+i//4 for i in range(a))+sum(1+i//4 for i in range(b))<=8)
        self.assertEqual(maximum['overall'],round(brute));self.assertLessEqual(maximum['spent'],8);self.assertEqual(p,before)
        owned={'parameters':[0]*147,'level_info':{'level':2,'exp_total':123},'additional_skill_id':[3]}
        maximum['parameters']=[80]*147;old=copy.deepcopy(owned)
        display=developed_personal(owned,{'maximum_development':maximum,'base_parameters':[70]*147})
        self.assertEqual(display['level_info']['level'],5);self.assertEqual(display['overall'],maximum['overall']);self.assertEqual(owned,old)

    def test_custom_booster_strings_keep_original_rows_and_exact_effects(self):
        groups=[{'name':'Any3W','id':1142,'items':{62:'射手本能'}},
                {'name':'Any10T','id':1157,'items':{954:'原有文字'}}]
        source=wrap(write(groups));self.assertEqual(read(unwrap(source)),groups)
        projects=[{'booster_ids':[76,1000],'custom_boosters':[{'id':1000,'label':'我的增能','effects':{'20':4,'24':1}}]}]
        texts,routes=booster_rows(projects,{'20':'射门','24':'防守意识'})
        updated=read(unwrap(merge(source,texts)))
        self.assertEqual(updated[0]['items'][62],'射手本能')
        self.assertEqual(updated[0]['items'][60000],'我的增能')
        self.assertEqual(updated[0]['items'][60001],'射门 +4、防守意识 +1。')
        self.assertEqual(updated[1],groups[1]);self.assertEqual(routes[0]['id'],1000)
        with self.assertRaises(ValueError):merge(merge(source,texts),texts)

    def test_reimport_coach_updates_definition_and_preserves_owned_state(self):
        conn=sqlite3.connect(':memory:');conn.executescript('create table meta(key text primary key,value text);create table coaches(coach_id integer,serial integer,json text,primary key(coach_id,serial));')
        p={'name':'我的教练','name_en':'My Coach','age':40,'ability_id':[256,0,0,0],
           'possession':89,'short_counter':88,'long_counter':70,'side_attack':70,'long_ball':70,'_personal_coach_revision':'v1'}
        definition={'uuid':str(uuid.uuid4()),'id':95000001,'payload':p}
        apply_coaches(conn,[definition]);cid,serial,payload=conn.execute('select * from coaches').fetchone()
        saved=json.loads(payload);saved['is_lock']='YES';saved['future_progress']={'games':5}
        conn.execute('update coaches set json=?',(json.dumps(saved),));conn.commit()
        newer=copy.deepcopy(definition);newer['payload'].update(possession=92,_personal_coach_revision='v2')
        apply_coaches(conn,[newer]);after=json.loads(conn.execute('select json from coaches').fetchone()[0])
        self.assertEqual(after['possession'],92);self.assertEqual(after['is_lock'],'YES');self.assertEqual(after['future_progress'],{'games':5})
        self.assertEqual(after['coach_id'],{'id':cid,'serial':serial})
        conn.execute('delete from coaches');conn.commit();apply_coaches(conn,[newer]);self.assertEqual(conn.execute('select count(*) from coaches').fetchone()[0],0)

    def test_drawn_copies_keep_independent_progress_when_initial_copy_was_released(self):
        c=sqlite3.connect(':memory:');c.executescript('''
        create table meta(key text primary key,value text);
        create table gameplayers(id integer,serial integer unique,json text,source text,acquired_at text,primary key(id,serial));
        create table careerplan(id integer,serial integer,category text,points integer,at text);
        create table owned_identity_aliases(id integer,old_serial integer,new_serial integer,primary key(id,old_serial));
        create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
        create table managed_serials(card_id text primary key,next_serial integer);
        insert into meta values('personal_pack_revision_v1','same-packs');''')
        uid=str(uuid.uuid4());cid=90000001;params=[70]*147
        owned={'gameplayer_id':{'id':cid,'serial':1},'parameters':params[:],
               'level_info':{'level':1,'level_limit':35,'exp_total':0},
               '_personal_player_uuid':uid,'_personal_design_revision':'v1',
               'additional_skill_id':[2],'additional_position':[],
               'name':'Original','name_en':'Original','player_name':'Original','_nation_id':1,
               'initial_base_team_id':108,'initial_base_national_team_id':0,'uniform_number':9,
               'play_style':[1,1],'initial_booster_id_list':[76,1000,0],'default_rarity':4}
        d={'identity':{'package_id':uid,'card_id':cid,'previous_card_ids':[cid]},'owned':owned,
           'base_parameters':params[:],'allocation':{},'card_type':'Epic','card_series':'Epic'}
        doc={'format':'personal-player-native-v1','revision':'same-packs','players':[d],
             'training_groups':[{'id':'shooting','indices':[20]}]}
        apply_definitions(c,doc)
        for serial,spent in ((2,1),(3,3)):
            p=copy.deepcopy(owned);p['gameplayer_id']['serial']=serial
            p['level_info'].update(level=serial,exp_total=serial*100);p['future_field']={'games':serial}
            c.execute('insert into gameplayers values(?,?,?,?,?)',(cid,serial,json.dumps(p),'personal-pack','1'))
            c.execute('insert into careerplan values(?,?,?,?,?)',(cid,serial,'shooting',spent,'earned'))
        c.execute('delete from gameplayers where serial=1');c.commit()
        before={s:training_hash(c,json.loads(raw),pid,s) for pid,s,raw in c.execute('select id,serial,json from gameplayers')}
        d['base_parameters'][20]=75;d['owned'].update(name='Updated',_personal_design_revision='v2')
        apply_definitions(c,doc)
        for pid,s,raw in c.execute('select id,serial,json from gameplayers'):
            p=json.loads(raw);self.assertEqual(training_hash(c,p,pid,s),before[s])
            self.assertEqual(p['parameters'][20],75+(1 if s==2 else 3))
            self.assertEqual(p['future_field'],{'games':s});self.assertEqual(p['name'],'Updated')
        c.execute('delete from gameplayers');c.commit()
        d['owned'].update(name='Catalogue updated',_personal_design_revision='v3');apply_definitions(c,doc)
        self.assertEqual(c.execute('select count(*) from gameplayers').fetchone()[0],0)
        self.assertEqual(json.loads(c.execute('select payload from managed_cards').fetchone()[0])['name'],'Catalogue updated')

if __name__=='__main__':unittest.main()
