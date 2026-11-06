import copy,json,random,types,unittest
from unittest.mock import patch
from test_division_squads import DivisionSquadTests,template
from tournament_squads import ClubGenerator,BOOSTER_REVISION,RENTAL_BOOSTER_REVISION


class TournamentBoosterTests(unittest.TestCase):
    def setUp(self):
        self.fixture=DivisionSquadTests('test_native_strength_examples');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.addCleanup(self.fixture.tearDown)
        self.g=self.fixture.g;self.g.__class__=ClubGenerator;self.db=self.fixture.db;self.doc=self.fixture.doc
        for cid,raw in list(self.db.execute('select card_id,payload from managed_cards')):
            p=json.loads(raw);p['initial_base_team_id']=121;p['parameters'][145]=136
            self.fixture.put_card(p)
        self.doc['division_squads'].update(empty_booster_ids=[136],random_boosters=[
            {'id':7,'roles':list(range(1,13)),'effects':{'20':4,'35':4}},
            {'id':8,'roles':[0],'effects':{'18':4,'39':4}}])
        self.doc['preview_boosters']={'7':{'effects':{'20':4,'35':4}},'8':{'effects':{'18':4,'39':4}}}

    def build(self,cpu=True):
        # Native tactical preflight has its own complete instruction tests.
        # Here retain its actual rating/formation inputs and isolate persistence.
        with patch('ai_match_manager.prepare_strategies',return_value=None):
            return self.g.build_club(self.db,template(),121,rng=random.Random(19),cpu=cpu)

    def test_cpu_fills_one_slot_by_position_before_selection_and_rating_without_db_writes(self):
        before=list(self.db.execute('select *from managed_cards'))
        result=self.build();meta=result['_studio_tournament_squad']
        self.assertEqual(meta['booster_revision'],BOOSTER_REVISION);self.assertEqual(len(meta['random_boosters']),23)
        for p in result['player_list']:
            self.assertEqual(p['parameters'][144],8 if p['parameters'][0]==0 else 7)
            self.assertEqual(p['parameters'][145],136,'only one extra booster per card')
            self.assertEqual(p['initial_booster_id_list'],p['parameters'][144:147])
            coach={'payload':result['coach_data'],'effects':{}}
            self.assertEqual(p['disp_overall'],self.g.payload_rating(p['parameters'][:147],coach,meta['style']))
        self.assertEqual(list(self.db.execute('select *from managed_cards')),before)

    def test_cached_opponent_upgrade_is_idempotent_and_does_not_redraw_team(self):
        pool=self.doc['division_squads'].pop('random_boosters');old=self.build()
        self.doc['division_squads']['random_boosters']=pool
        meta=old['_studio_tournament_squad'];meta.pop('booster_revision')
        ids=[p['gameplayer_id'].copy()for p in old['player_list']];formation=copy.deepcopy(old['squad_data'])
        self.assertTrue(self.g.repair_cpu_boosters(old,18,self.db))
        self.assertEqual(ids,[p['gameplayer_id']for p in old['player_list']]);self.assertEqual(formation,old['squad_data'])
        saved=copy.deepcopy(old);self.assertFalse(self.g.repair_cpu_boosters(old,99,self.db));self.assertEqual(old,saved)

    def owned_coach(self):
        coach=copy.deepcopy(self.doc['division_squads']['coaches'][0]['payload']);coach['coach_id']['serial']=23
        self.db.execute('insert into coaches values(?,?,?)',(coach['coach_id']['id'],23,json.dumps(coach)))
    def test_player_rentals_fill_one_position_matched_slot_without_source_writes(self):
        self.owned_coach();before=list(self.db.execute('select *from managed_cards'))
        result=self.build(False)
        self.assertEqual(result['_studio_tournament_squad']['booster_revision'],RENTAL_BOOSTER_REVISION)
        self.assertEqual(len(result['_studio_tournament_squad']['random_boosters']),23)
        for p in result['player_list']:
            self.assertEqual(p['parameters'][144],8 if p['parameters'][0]==0 else 7)
            self.assertEqual(p['parameters'][145],136)
            self.assertEqual(p['initial_booster_id_list'],p['parameters'][144:147])
            self.assertEqual(p['gameplayer_id']['serial'],0);self.assertEqual(p['type'],'RENTAL')
        self.assertEqual(list(self.db.execute('select *from managed_cards')),before)
    def test_cached_player_rentals_upgrade_without_redrawing_or_changing_progress(self):
        self.owned_coach();pool=self.doc['division_squads'].pop('random_boosters');old=self.build(False)
        self.doc['division_squads']['random_boosters']=pool;old['_studio_tournament_squad'].pop('booster_revision')
        ids=[p['gameplayer_id'].copy()for p in old['player_list']];formation=copy.deepcopy(old['squad_data'])
        levels=[copy.deepcopy(p['level_info'])for p in old['player_list']];before=list(self.db.iterdump())
        self.assertTrue(self.g.repair_rental_boosters(old,18,self.db))
        self.assertEqual(ids,[p['gameplayer_id']for p in old['player_list']]);self.assertEqual(formation,old['squad_data'])
        self.assertEqual(levels,[p['level_info']for p in old['player_list']]);self.assertEqual(list(self.db.iterdump()),before)
        saved=copy.deepcopy(old);self.assertFalse(self.g.repair_rental_boosters(old,99,self.db));self.assertEqual(old,saved)
    def test_full_original_slots_are_preserved_for_rentals(self):
        self.owned_coach()
        for cid,raw in list(self.db.execute('select card_id,payload from managed_cards')):
            p=json.loads(raw);p['parameters'][144:146]=[7,8];self.fixture.put_card(p)
        result=self.build(False)
        self.assertEqual(result['_studio_tournament_squad']['random_boosters'],[])
        self.assertTrue(all(p['parameters'][144:146]==[7,8]for p in result['player_list']))
    def test_reinforcement_booster_is_stable_and_never_mutates_source_card(self):
        card=json.loads(self.db.execute('select payload from managed_cards order by card_id limit 1').fetchone()[0]);card['_studio_fingerprint']='rental-reward'
        before=copy.deepcopy(card);a=self.g.rental_prepared(card,33);b=self.g.rental_prepared(card,33)
        self.assertEqual(a,b);self.assertEqual(card,before)
        self.assertEqual(a['parameters'][144],8 if card['parameters'][0]==0 else 7)
        self.assertEqual(a['initial_booster_id_list'],a['parameters'][144:147])
    def test_runtime_repairs_only_unstarted_rentals_and_keeps_owned_plan_replacements(self):
        from tournament_runtime import Service
        self.owned_coach()
        for started in (False,True):
            with self.subTest(started=started):
                pool=self.doc['division_squads'].pop('random_boosters');old=self.build(False)
                self.doc['division_squads']['random_boosters']=pool;old['_studio_tournament_squad'].pop('booster_revision')
                plan=copy.deepcopy(old['squad_data']);replacement={'id':999,'serial':1234};plan['player_list'][2]['gameplayer_id']=replacement.copy()
                active={'game_id':111,'fixture_id':7,'player_side':'HOME','started':started,'home':old,'away':{'CPU':'keep'},
                        'own_plan':plan}
                if started:active.update(start_reply={'keep':True},start_contract=5)
                before=list(self.db.iterdump());ids=copy.deepcopy(plan['player_list'])
                Service(lambda:self.doc,'.',self.g).repair_rentals(self.db,{'seed':45},active)
                self.assertEqual(list(self.db.iterdump()),before);self.assertEqual(plan['player_list'],ids)
                self.assertEqual(active['away'],{'CPU':'keep'})
                self.assertEqual('start_reply'in active,started)
                self.assertEqual(old['_studio_tournament_squad'].get('booster_revision'),None if started else RENTAL_BOOSTER_REVISION)
                self.assertTrue(all((p['parameters'][144]==0)==started for p in old['player_list']))

    def test_saved_started_match_keeps_exact_boosters_and_reply_at_entry_and_start(self):
        from tournament_runtime import Service
        self.owned_coach()
        for side,boundary in ((s,b)for s in ('HOME','AWAY')for b in ('entry','start')):
            with self.subTest(side=side,boundary=boundary):
                pool=self.doc['division_squads'].pop('random_boosters');old=self.build(False)
                self.doc['division_squads']['random_boosters']=pool;old['_studio_tournament_squad'].pop('booster_revision')
                plan=copy.deepcopy(old['squad_data']);replacement={'id':999,'serial':1234}
                plan['player_list'][2]['gameplayer_id']=replacement.copy()
                wire=[dict(gameplayer_id=p['gameplayer_id'].copy(),parameters=p['parameters'][:147],averaged_overall=0)
                      for p in old['player_list']]
                wire[2]=dict(gameplayer_id=replacement.copy(),parameters=[53]*147,averaged_overall=104)
                native={'player_list':wire,'coach':'original-coach','formation':'original-layout'}
                reply={'game_id':111,'random_seed':345678,'squad_data_'+side.lower():native,
                       'squad_data_'+('away'if side=='HOME'else'home'):{'CPU':'unchanged'}}
                active=dict(game_id=111,fixture_id=7,player_side=side,started=True,
                    own_plan=plan,start_reply=copy.deepcopy(reply),start_contract=5)
                active[side.lower()]=old;active['away'if side=='HOME'else'home']={'CPU':'keep'}
                current={'seed':45,'run_id':'same-edition','fixtures':[{'id':7,'played':False}],
                         'receipts':{},'active':active};before_db=list(self.db.iterdump())
                before_plan=copy.deepcopy(plan);service=Service(lambda:self.doc,'.',self.g)
                modules={'custom_stadium':types.SimpleNamespace(apply=lambda *_:None)}
                with patch.dict('sys.modules',modules),patch.object(service,'activate_coaching'),\
                     patch.object(service,'prepare',return_value=active),patch.object(service,'reinforcements',return_value=[]):
                    if boundary=='entry':
                        special=service.special(self.db,{'player_team_id':121},current,{})
                        self.assertTrue(all(p['parameters'][144]==0 for p in special['rental_gameplayer_list']))
                    out=service.start(types.SimpleNamespace(conn=self.db),{},current,{'game_id':111,'side':side})
                    saved=copy.deepcopy(current)
                    self.assertEqual(service.start(types.SimpleNamespace(conn=self.db),{},current,{'game_id':111,'side':side}),out)
                    self.assertEqual(current,saved,'repeated START must not reroll additions')
                expected=copy.deepcopy(reply)
                self.assertEqual(out,expected,'an issued START must preserve every saved ability slot')
                self.assertEqual(active['own_plan'],before_plan)
                self.assertEqual(current['fixtures'],[{'id':7,'played':False}]);self.assertEqual(current['receipts'],{})
                self.assertEqual(current['run_id'],'same-edition');self.assertEqual(active['game_id'],111)
                self.assertEqual(list(self.db.iterdump()),before_db)


if __name__=='__main__':unittest.main()
