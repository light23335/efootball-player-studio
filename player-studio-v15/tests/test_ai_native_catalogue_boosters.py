import copy,json,random,sqlite3,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import division_squads as ds
from personal_runtime import sync_native_catalogue,apply_definitions
from test_division_squads import DivisionSquadTests,card,template


class NativeCatalogueTests(unittest.TestCase):
    def test_empty_and_malformed_private_snapshots_are_backed_up_once_without_touching_progress(self):
        values=(None,'null','{}','[]','{"opponent":null}','{"opponent":[]}','not json')
        for raw in values:
            with self.subTest(raw=raw):
                db=sqlite3.connect(':memory:');db.execute('create table meta(key primary key,value)')
                db.executemany('insert into meta values(?,?)',[('ai_division_active_match',raw),('ai_division_state','{"division":3,"points":1448}')])
                doc={'native_player_catalogue':{'version':1,'card_ids':[1]}}
                self.assertTrue(ds.discard_invalid_snapshot(db,doc))
                self.assertIsNone(db.execute("select value from meta where key='ai_division_active_match'").fetchone())
                backup=db.execute("select value from meta where key like 'personal_ai_catalogue_snapshot_backup_v1:%'").fetchall()
                self.assertEqual(backup,[(raw if raw is not None else 'null',)])
                self.assertFalse(ds.discard_invalid_snapshot(db,doc))
                self.assertEqual(db.execute("select value from meta where key='ai_division_state'").fetchone()[0],'{"division":3,"points":1448}')
                db.close()

    def test_invalid_opponent_entries_and_repeated_game_ids_keep_each_original_backup(self):
        db=sqlite3.connect(':memory:');db.execute('create table meta(key primary key,value)')
        doc={'native_player_catalogue':{'version':1,'card_ids':[1]}}
        for players in(None,[None],[{'gameplayer_id':None}]):
            raw=json.dumps({'game_id':17,'opponent':{ds.MARKER:{'revision':ds.REVISION},'player_list':players}})
            db.execute('insert or replace into meta values(?,?)',('ai_division_active_match',raw))
            self.assertTrue(ds.discard_invalid_snapshot(db,doc))
        backups=[r[0]for r in db.execute("select value from meta where key like 'personal_ai_catalogue_snapshot_backup_v1:%'")]
        self.assertEqual(len(backups),3);self.assertEqual(len(set(backups)),3);db.close()

    def test_valid_original_and_workshop_snapshots_are_not_discarded(self):
        db=sqlite3.connect(':memory:');db.execute('create table meta(key primary key,value)')
        doc={'native_player_catalogue':{'version':1,'card_ids':[1]}}
        for opponent in({'player_list':[card(1,12)]},{ds.MARKER:{'revision':ds.REVISION},'player_list':[card(1,12)]}):
            raw=json.dumps({'game_id':17,'opponent':opponent})
            db.execute('insert or replace into meta values(?,?)',('ai_division_active_match',raw))
            self.assertFalse(ds.discard_invalid_snapshot(db,doc))
            self.assertEqual(db.execute("select value from meta where key='ai_division_active_match'").fetchone()[0],raw)
        self.assertIsNone(ds.native_card_ids({}));self.assertIsNone(ds.native_card_ids({'native_player_catalogue':None}))
        with self.assertRaises(ValueError):ds.native_card_ids({'native_player_catalogue':[]})
        db.close()

    def test_invalid_catalogue_payloads_are_quarantined_even_if_the_native_id_still_exists(self):
        db=sqlite3.connect(':memory:')
        db.executescript('create table meta(key primary key,value);create table managed_cards(card_id primary key,payload);'
                        'create table managed_members(agent_id,card_id,weight);create table gameplayers(id,serial,json);')
        bad=(None,'null','{}','[]','not json',b'null');normal=card(500,12)
        db.execute('insert into managed_cards values(?,?)',('500',json.dumps(normal)))
        db.execute('insert into gameplayers values(1,8,?)',('{"keep":"owned progress"}',))
        before=list(db.execute('select *from gameplayers'))
        for cid,raw in enumerate(bad,1):
            db.execute('insert into managed_cards values(?,?)',(str(cid),raw));db.execute('insert into managed_members values(7,?,1)',(str(cid),))
        doc={'native_player_catalogue':{'version':1,'card_ids':[500,*range(1,7)]},'players':[]}
        with db:sync_native_catalogue(db,doc)
        self.assertEqual(list(db.execute('select card_id from managed_cards')),[('500',)])
        self.assertFalse(list(db.execute('select *from managed_members')))
        self.assertEqual(list(db.execute('select *from gameplayers')),before)
        backups=[json.loads(r[0])for r in db.execute("select value from meta where key like 'personal_catalogue_invalid_v1:%'")]
        self.assertEqual(len(backups),len(bad));self.assertEqual(next(b for b in backups if b['card_id']=='6')['raw_payload'],b'null'.hex())
        with db:sync_native_catalogue(db,doc)
        self.assertEqual(db.execute("select count(*)from meta where key like 'personal_catalogue_invalid_v1:%'").fetchone()[0],len(bad))
        self.assertEqual(list(db.execute('select *from gameplayers')),before);db.close()

    def test_startup_reimport_repairs_selected_null_card_without_duplicate_owned_instances(self):
        for raw in(None,'null'):
            with self.subTest(raw=raw):
                db=sqlite3.connect(':memory:')
                db.executescript('''create table meta(key text primary key,value text);
                create table gameplayers(id integer,serial integer unique,json text,source text,acquired_at text,primary key(id,serial));
                create table careerplan(id integer,serial integer,category text,points integer,at text);
                create table owned_identity_aliases(id integer,old_serial integer,new_serial integer,primary key(id,old_serial));
                create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
                create table managed_serials(card_id text primary key,next_serial integer);''')
                cid=90000001;uid='startup-null-card'
                owned={'gameplayer_id':{'id':cid,'serial':1},'parameters':[0]*147,'level_info':{'level':1,'level_limit':35,'exp_total':0},'_personal_player_uuid':uid,'_personal_design_revision':uid}
                definition={'identity':{'package_id':uid,'card_id':cid,'previous_card_ids':[cid]},'owned':owned,'base_parameters':[0]*147,'allocation':{},'card_type':'Epic','card_series':'Epic'}
                doc={'format':'personal-player-native-v1','revision':'same-revision','players':[definition],'training_groups':[],
                     'native_player_catalogue':{'version':1,'card_ids':[cid]}}
                apply_definitions(db,doc);before=list(db.execute('select *from gameplayers'))
                db.execute('create table if not exists managed_members(agent_id,card_id,weight)')
                db.execute('insert into managed_members values(7,?,3)',(str(cid),))
                db.execute('update managed_cards set payload=?where card_id=?',(raw,str(cid)))
                db.execute('insert or replace into meta values(?,?)',('ai_division_active_match','null'));db.commit()
                apply_definitions(db,doc);apply_definitions(db,doc)
                self.assertEqual(list(db.execute('select *from gameplayers')),before)
                self.assertEqual(list(db.execute('select *from managed_members')),[(7,str(cid),3)])
                self.assertEqual(json.loads(db.execute('select payload from managed_cards').fetchone()[0])['_personal_player_uuid'],uid)
                self.assertEqual(db.execute("select count(*)from meta where key like 'personal_catalogue_invalid_v1:%'").fetchone()[0],1)
                self.assertIsNone(db.execute("select value from meta where key='ai_division_active_match'").fetchone());db.close()

    def test_empty_slot_records_use_native_kind_and_zero_effects_not_a_fixed_id(self):
        raw=bytes.fromhex('00000000000000000400000000008800000000000000000000001000000000000000000000040000')
        # Another package may use a different number for the same native marker.
        n=int.from_bytes(raw,'little');other=((n&~(1023<<112))|(201<<112)).to_bytes(40,'little')
        data=raw+other
        with patch('native_cpk.Cpk',return_value=types.SimpleNamespace(read=lambda name:data)),patch('native_cpk.unwrap',side_effect=lambda value:value):
            self.assertEqual(ds.empty_booster_ids(b'unused'),[136,201])
            self.assertEqual(ds.empty_booster_ids(b'unused',[136,201]),[])
        positive=bytearray(raw);positive[18]=1
        conditional=bytearray(raw);conditional[8]=5;conditional[37]=5
        blank_custom=bytearray(raw);blank_custom[8]=0;blank_custom[37]=0
        mismatch=bytearray(raw);mismatch[8]=5
        for data in(positive,conditional,blank_custom,mismatch):
            with patch('native_cpk.Cpk',return_value=types.SimpleNamespace(read=lambda name:data)),patch('native_cpk.unwrap',side_effect=lambda value:value):
                self.assertEqual(ds.empty_booster_ids(b'unused'),[])
    def test_retired_diy_migrates_pack_links_but_owned_cards_and_progress_are_preserved(self):
        db=sqlite3.connect(':memory:')
        db.executescript('create table meta(key text primary key,value text);create table managed_cards(card_id text primary key,payload text);'
                        'create table managed_members(agent_id integer,card_id text,weight integer,primary key(agent_id,card_id));'
                        'create table gameplayers(id integer,serial integer,json text);')
        current=card(102,12);current['_personal_player_uuid']='same'
        old=card(101,12);old['_personal_player_uuid']='same'
        missing=card(103,12);missing['_personal_player_uuid']='absent'
        for p in(current,old,missing):db.execute('insert into managed_cards values(?,?)',(str(p['gameplayer_id']['id']),json.dumps(p)))
        db.execute('insert into gameplayers values(101,8,?)',(json.dumps(old),))
        db.execute('insert into managed_members values(7,"101",3)')
        db.execute('insert into managed_members values(8,"103",1)')
        active={'game_id':17,'opponent':{ds.MARKER:{'revision':ds.REVISION},'player_list':[old]}}
        db.executemany('insert into meta values(?,?)',[('ai_division_active_match',json.dumps(active)),('ai_division_state','{"points":1573,"division":2}')]);db.commit()
        owned=list(db.execute('select *from gameplayers'))
        doc={'native_player_catalogue':{'version':1,'card_ids':[102]},'players':[{'identity':{'package_id':'same','card_id':102}}]}
        with db:sync_native_catalogue(db,doc)
        self.assertEqual(list(db.execute('select card_id from managed_cards')),[('102',)])
        self.assertEqual(list(db.execute('select *from managed_members')),[(7,'102',3)])
        self.assertIsNone(db.execute("select value from meta where key='ai_division_active_match'").fetchone())
        self.assertIsNotNone(db.execute("select value from meta where key='personal_ai_catalogue_snapshot_backup_v1:17'").fetchone())
        self.assertEqual(list(db.execute('select *from gameplayers')),owned)
        self.assertEqual(db.execute("select value from meta where key='ai_division_state'").fetchone()[0],'{"points":1573,"division":2}')
        with db:sync_native_catalogue(db,doc)
        self.assertEqual(list(db.execute('select *from managed_members')),[(7,'102',3)])
        db.close()

    def test_pool_contains_only_existing_matching_constant_original_boosters(self):
        from custom_boosters import BOOSTER_BITS
        rows=[]
        specs=[(1,{'20':1,'35':1}),(2,{'29':2,'30':2}),(3,{'20':1,'35':1}),
               (4,{'20':1,'35':1}),(5,{'20':1,'35':1})]
        for bid,effects in specs:
            n=bid<<112
            for k,v in effects.items():n|=v<<BOOSTER_BITS[k]
            rows.append(n.to_bytes(40,'little'))
        catalogue={'boosters':[{'id':bid,'category':0,'conditional':False,'effects':effects}for bid,effects in specs]}
        catalogue['boosters'][2]['conditional']=True
        catalogue['boosters'][3]['effects']={'20':9,'35':1}
        with patch('native_cpk.Cpk',return_value=types.SimpleNamespace(read=lambda name:b''.join(rows))),patch('native_cpk.unwrap',side_effect=lambda raw:raw):
            result=ds.random_booster_pool(catalogue,b'unused',[5])
        self.assertEqual({b['id']for b in result},{1,2})
        self.assertNotIn(0,result[0]['roles']);self.assertEqual(result[1]['roles'],[0])


class BoosterAssignmentTests(unittest.TestCase):
    setUp=DivisionSquadTests.setUp
    tearDown=DivisionSquadTests.tearDown
    put_card=DivisionSquadTests.put_card
    def test_existing_placeholder_is_filled_once_and_conditionals_are_preserved_on_snapshot_repair(self):
        out=self.g.build(self.db,template(),3,random.Random(81))
        self.doc['division_squads'].update(empty_booster_ids=[136],random_boosters=[{'id':7,'roles':list(range(13)),'effects':{'20':1,'35':1}}])
        self.doc['preview_boosters']={'7':{'conditional':False,'effects':{'20':1,'35':1}},'258':{'conditional':True,'effects':{'23':6}}}
        roster=out['player_list'];ids=copy.deepcopy(out[ds.MARKER]['card_ids'])
        roster[1]['parameters'][144:147]=[9,136,0]
        roster[2]['parameters'][144:147]=[9,258,0]
        roster[3]['parameters'][144:147]=[7,136,0]
        out[ds.MARKER]['random_boosters']=[{'card_id':roster[3]['gameplayer_id']['id'],'slot':0,'id':7,'role':1}]
        self.assertTrue(self.g.repair_snapshot(self.db,out))
        self.assertEqual(roster[1]['parameters'][144:147],[9,7,0])
        self.assertEqual(roster[1]['initial_booster_id_list'],[9,7,0])
        self.assertEqual(roster[2]['parameters'][144:147],[9,258,0])
        self.assertEqual(roster[3]['parameters'][144:147],[7,136,0])
        self.assertEqual(out[ds.MARKER]['card_ids'],ids)
        self.assertEqual(out[ds.MARKER]['tactical_spec']['players'][1]['parameters'][144:147],[9,7,0])
        before=copy.deepcopy(roster);self.assertFalse(self.g.repair_snapshot(self.db,out));self.assertEqual(roster,before)
        roster[1]['parameters'][14:41]=[0]*27
        self.assertTrue(self.g.repair_snapshot(self.db,out))
        self.assertEqual(roster[1]['parameters'][145],7,'attribute recovery must retain the assigned constant booster')
        self.assertEqual(out[ds.MARKER]['tactical_spec']['players'][1]['parameters'],roster[1]['parameters'][:147])
    def test_exact_native_membership_filters_even_good_old_110_payload(self):
        self.doc['native_player_catalogue']={'version':1,'card_ids':[1000]}
        self.assertEqual([p['gameplayer_id']['id']for p in self.g.cards(self.db)],[1000])
        self.assertEqual(self.db.execute('select count(*)from managed_cards').fetchone()[0],91)

    def test_one_empty_slot_only_constant_position_appropriate_booster_and_real_rating(self):
        self.doc['division_squads']['random_boosters']=[{'id':7,'roles':[12],'effects':{'20':4,'35':4}},
                                                      {'id':300,'roles':[0],'effects':{'29':4,'30':4}}]
        self.doc['preview_boosters']={'7':{'conditional':False,'effects':{'20':4,'35':4}},
                                      '9':{'conditional':False,'effects':{'18':2}},
                                      '300':{'conditional':False,'effects':{'29':4,'30':4}}}
        source=card(1000,12);source['_studio_fingerprint']='fixture';before=copy.deepcopy(source)
        p=self.g.fill_booster(source,random.Random(1));wire=self.g.prepared(p)
        self.assertEqual(wire['parameters'][144:147],[7,0,0])
        self.assertEqual(wire['initial_booster_id_list'],[7,0,0]);self.assertEqual(source,before)
        coach=self.doc['division_squads']['coaches'][0]
        self.assertGreater(self.g.rating(p,coach,'possession'),self.g.rating(source,coach,'possession'))
        self.assertEqual(self.g.rating(p,coach,'possession'),self.g.payload_rating(wire['parameters'],coach,'possession'))
        source['parameters'][144:146]=[9,0]
        p=self.g.fill_booster(source,random.Random(2));self.assertEqual(p['_studio_ai_booster'],{'slot':1,'id':7,'role':12})
        source['parameters'][145]=7;self.assertIs(self.g.fill_booster(source,random.Random(2)),source)
        keeper=card(1001,0);keeper['_studio_fingerprint']='keeper'
        self.assertIs(self.g.fill_booster(keeper,random.Random(2)),keeper,'first slot is 8 bits')
        keeper['parameters'][144]=9
        self.assertEqual(self.g.fill_booster(keeper,random.Random(2))['_studio_ai_booster']['id'],300)

    def test_outgoing_roster_tactical_scores_and_retry_all_use_same_drawn_boosters(self):
        self.doc['division_squads']['random_boosters']=[{'id':7,'roles':list(range(13)),'effects':{'20':1,'35':1}}]
        self.doc['preview_boosters']={'7':{'conditional':False,'effects':{'20':1,'35':1}}}
        before=list(self.db.execute('select payload from managed_cards'))
        out=self.g.build(self.db,template(),3,random.Random(81));report=out[ds.MARKER]
        self.assertEqual(len(report['random_boosters']),23)
        self.assertTrue(all(p['parameters'][144:147]==[7,0,0]for p in out['player_list']))
        self.assertTrue(all(p['initial_booster_id_list']==[7,0,0]for p in out['player_list']))
        self.assertTrue(all(p['parameters'][144]==7 for p in report['tactical_spec']['players']))
        slots=[p['parameters'][144:147]for p in out['player_list']]
        self.g.repair_snapshot(self.db,out)
        self.assertEqual(slots,[p['parameters'][144:147]for p in out['player_list']])
        self.assertEqual(list(self.db.execute('select payload from managed_cards')),before)


del DivisionSquadTests

if __name__=='__main__':unittest.main()
