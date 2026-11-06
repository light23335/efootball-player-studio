"""Exact club_cards oracle, including cache invalidation and source isolation."""
import copy,json,random,sqlite3,unittest
from tournament_squads import ClubGenerator,club_cards,STOCK_AI_EXCLUDED_CARD_IDS,_copy_player

class ClubPoolCacheTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.executescript('create table managed_cards(card_id text primary key,fingerprint text,payload text);create table excluded_catalog_ids(card_id text,reason text);')
        self.doc={'players':[],'division_squads':{'excluded_ids':[]},'tournament_standard_cards':{},
                  'tournament_national_team_nations':{'54':7,'49206':7,'7':236}}
        for i in range(40):
            self.add(200000+i,club=500+i%2,country=(7,236,0,-1)[i%4],national=(54,7,0)[i%3])
        self.conn.commit();self.g=object.__new__(ClubGenerator);self.g.document=lambda:self.doc
    def card(self,cid,club=500,country=7,national=54):
        return dict(gameplayer_id={'id':cid,'serial':0},parameters=[70]*147,
            initial_base_team_id=club,_nation_id=country,initial_base_national_team_id=national,
            level_info={'level_limit':1,'level':1})
    def add(self,cid,**values):
        card=self.card(cid,**values);card['parameters'][0]=cid%13
        self.conn.execute('insert into managed_cards values(?,?,?)',(str(cid),'unchanged',json.dumps(card)))
        return card
    def compare(self):
        for team in(500,501,54,49206,7):
            for diy in(True,False):
                for cpu in(True,False):
                    with self.subTest(team=team,diy=diy,cpu=cpu):
                        self.assertEqual(self.g._club_cards(self.conn,team,diy,cpu),club_cards(self.conn,self.doc,team,diy,cpu))
    def test_index_preserves_exact_card_order_and_national_aliases_all_modes(self):self.compare()
    def test_payload_change_same_fingerprint_and_same_length_invalidates(self):
        self.compare();raw=self.conn.execute('select payload from managed_cards where card_id="200000"').fetchone()[0]
        changed=raw.replace('"initial_base_team_id": 500','"initial_base_team_id": 501')
        self.assertEqual(len(raw),len(changed))
        self.conn.execute('update managed_cards set payload=? where card_id="200000"',(changed,));self.compare()
    def test_rollback_and_new_transaction_are_not_a_stale_cache_hit(self):
        self.compare();self.conn.execute('begin')
        self.conn.execute('delete from managed_cards where card_id="200000"');self.compare()
        self.conn.rollback();self.conn.execute('begin');self.compare()
    def test_document_in_place_changes_and_output_mutation_are_isolated(self):
        first=self.g._club_cards(self.conn,54,True,True);first[0]['parameters'][14]=-99
        self.compare();self.doc['tournament_national_team_nations']['54']=236;self.compare()
        self.doc['division_squads']['excluded_ids'].append('200001');self.compare()
    def test_source_exclusion_changes_and_removal_invalidate(self):
        self.compare();self.conn.execute('insert into excluded_catalog_ids values("200000","recycled")');self.compare()
        self.conn.execute('delete from excluded_catalog_ids');self.compare()
    def test_standard_level_cap_merge_and_missing_managed_card_match_original(self):
        p=self.card(200000);p['level_info']={}
        self.conn.execute('update managed_cards set payload=? where card_id="200000"',(json.dumps(p),))
        for cid in(200000,200100):
            p=self.card(cid);p['level_info']['level_limit']=35;p['_studio_tournament_level_limit_source']='verified-source'
            p['parameters'][0]=0;self.doc['tournament_standard_cards'][str(cid)]=p
        self.compare();self.doc['tournament_standard_cards']['200100']['_nation_id']=236;self.compare()
    def test_malformed_unused_membership_fields_preserve_original_short_circuit(self):
        values=[dict(_nation_id=7,initial_base_team_id='bad',initial_base_national_team_id='bad'),
                dict(_nation_id='bad',initial_base_team_id=500),
                dict(_nation_id=0,initial_base_team_id='bad',initial_base_national_team_id=54),
                dict(_nation_id=0,initial_base_team_id=54,initial_base_national_team_id='bad')]
        for i,patch in enumerate(values):
            p=self.card(200200+i);p.update(patch);p['parameters'][0]=0
            self.conn.execute('insert into managed_cards values(?,?,?)',(str(200200+i),'same',json.dumps(p)))
        self.compare()
    def test_native_catalogue_and_diy_changes_are_not_hidden_by_same_revision(self):
        self.compare();self.doc['native_player_catalogue']={'version':1,'card_ids':[200000,200001,200002]};self.compare()
        self.doc['native_player_catalogue']['card_ids'].remove(200001);self.compare()
        self.doc['players'].append({'identity':{'card_id':200000},'owned':self.card(200000)})
        self.compare()
    def test_stock_cpu_exclusion_is_preserved_with_diy_exception(self):
        cid=next(iter(STOCK_AI_EXCLUDED_CARD_IDS));p=self.add(cid);self.compare()
        self.doc['players'].append({'identity':{'card_id':cid},'owned':p});self.compare()
    def test_fast_scalar_copy_preserves_deepcopy_alias_and_mutable_semantics(self):
        parameters=list(range(147));nested=[{'mutable':[1,2]}]*13
        source={'parameters':parameters,'base':parameters,'nested':nested,'tuple':(nested,parameters)}
        actual=_copy_player(source);expected=copy.deepcopy(source)
        self.assertEqual(actual,expected);self.assertIs(actual['parameters'],actual['base'])
        self.assertIs(actual['tuple'][1],actual['parameters']);self.assertIs(actual['nested'][0],actual['nested'][1])
        actual['parameters'].append(9);actual['nested'][0]['mutable'].append(3)
        self.assertEqual(len(parameters),147);self.assertEqual(nested[0]['mutable'],[1,2])
    def test_simulation_only_matches_every_entry_input_rating_rng_and_score(self):
        from test_tournament_sim_strength import generator_fixture
        from tournament_sim_strength import snapshot_for_ratings,ratings
        import tournament_simulation as simulation
        g,db,doc,proto=generator_fixture();self.addCleanup(db.close)
        first=random.Random(991);second=random.Random(991)
        full=g.build_club(db,proto,121,rng=first,cpu=True)
        cpu=g.build_club(db,proto,121,rng=second,cpu=True,simulation_only=True)
        self.assertEqual(first.getstate(),second.getstate())
        self.assertIsNotNone(full['_studio_tournament_squad']['tactical_spec'])
        self.assertTrue(full['_studio_tournament_squad']['tactical_spec']['prepared'])
        self.assertIsNone(cpu['_studio_tournament_squad']['tactical_spec'])
        projected=copy.deepcopy(full);projected['_studio_tournament_squad']['tactical_spec']=None
        self.assertEqual(projected,cpu)
        a=ratings(snapshot_for_ratings(full,g,db));b=ratings(snapshot_for_ratings(cpu,g,db))
        self.assertEqual(a,b)
        self.assertEqual(simulation.sample_period(a,a,seed=123),simulation.sample_period(b,b,seed=123))
        self.assertEqual(simulation.penalty_shootout(a,a,seed=456),simulation.penalty_shootout(b,b,seed=456))
        with self.assertRaises(ValueError):g.build_club(db,proto,121,rng=random.Random(991),cpu=False,simulation_only=True)
    def test_coach_transformation_memo_matches_original_formula_every_role(self):
        from division_squads import Generator
        from test_tournament_sim_strength import generator_fixture,team_snapshot
        g,db,doc,proto=generator_fixture();self.addCleanup(db.close)
        coach=doc['division_squads']['coaches'][0];rng=random.Random(222)
        for sample in range(30):
            params=team_snapshot()['player_list'][0]['parameters'][:147]
            for i in range(14,41):
                if i!=33:params[i]=rng.randrange(40,120)
            params[144:147]=[7,7,0];before=list(params)
            for role in range(13):self.assertEqual(g.payload_rating(params,coach,'possession',role),Generator.payload_rating(g,params,coach,'possession',role))
            self.assertEqual(params,before)
        for change in('player_booster','coach','proficiency','conditional','revision'):
            if change=='player_booster':doc['preview_boosters']['7']['effects']['20']+=1
            elif change=='coach':coach['effects']['20']=3
            elif change=='proficiency':coach['payload']['possession']=95
            elif change=='conditional':doc['preview_boosters']['7']['conditional']=True
            else:doc['revision']='changed-with-same-parameters'
            for role in range(13):self.assertEqual(g.payload_rating(params,coach,'possession',role),Generator.payload_rating(g,params,coach,'possession',role))
    def test_coached_parameter_cache_is_bounded(self):
        from test_tournament_sim_strength import generator_fixture,team_snapshot
        g,db,doc,proto=generator_fixture();self.addCleanup(db.close)
        params=team_snapshot()['player_list'][0]['parameters'][:147];coach=doc['division_squads']['coaches'][0]
        for value in range(4100):
            params[100]=value;g.payload_rating(params,coach,'possession',0)
        self.assertEqual(len(g._coached_payloads),4096)

if __name__=='__main__':unittest.main()
