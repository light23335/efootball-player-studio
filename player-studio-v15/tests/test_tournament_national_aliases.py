"""National reference IDs and same-country preset IDs share tournament pools."""
import copy,json,sqlite3,types,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import world_workspace as world
from tournament_squads import belongs_to_team,club_cards,national_family,export_standard_cards
from tournament_runtime import Service

class NationalAliasTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table players(id,card_type,payload)')
        self.db.execute('create table managed_cards(card_id,fingerprint,payload)')
        self.db.execute('create table gameplayers(id,serial,json)')
        self.identities={'nation':[{'id':7,'name':'中国','name_en':'China PR'},{'id':8,'name':'日本','name_en':'Japan'}],
            'team':[{'kind':'team','id':54,'name':'中国','name_en':'China PR'},
                    {'kind':'team','id':49206,'name':'中国','name_en':'China PR'},
                    {'kind':'team','id':52,'name':'日本','name_en':'Japan'},
                    {'kind':'team','id':101,'name':'俱乐部','name_en':'Club'}]}
        self.cards=[self.card(1,native=54),self.card(2,base=49206),self.card(3,nation=7,base=101),
                    self.card(4,nation=8,native=52),self.card(5,base=101)]
        for p in self.cards:
            raw=json.dumps(p)
            self.db.execute('insert into players values(?,?,?)',(str(p['gameplayer_id']['id']),'Standard',raw))
            self.db.execute('insert into managed_cards values(?,?,?)',(str(p['gameplayer_id']['id']),'same',raw))
            self.db.execute('insert into gameplayers values(?,?,?)',(p['gameplayer_id']['id'],p['gameplayer_id']['serial'],raw))
        parent=self
        class Borrowed:
            def execute(self,*a):return parent.db.execute(*a)
            def close(self):pass
        self.library=types.SimpleNamespace(db=Borrowed,identities=lambda:copy.deepcopy(self.identities))
        self.doc={'players':[],'tournament_national_team_nations':world.national_teams(self.library),
                  'native_player_catalogue':{'version':1,'card_ids':list(range(1,6))}}

    def card(self,cid,nation=0,native=0,base=0):
        return {'gameplayer_id':{'id':cid,'serial':100+cid},'parameters':[0]*147,'_nation_id':nation,
                'initial_base_national_team_id':native,'initial_base_team_id':base,'level_info':{'level_limit':35}}

    def test_exact_name_family_joins_both_china_ids_without_using_club_country(self):
        self.assertEqual(self.doc['tournament_national_team_nations'],{'54':7,'49206':7,'52':8})
        self.assertEqual(national_family(self.doc,54),{54,49206})
        self.assertEqual(national_family(self.doc,49206),{54,49206})
        self.assertEqual(national_family(self.doc,101),set())

    def test_catalogue_distinguishes_same_name_ids_without_rewriting_team_records(self):
        before=copy.deepcopy(self.identities)
        with tempfile.TemporaryDirectory()as temp:
            self.library.resources=Path(temp)
            (Path(temp)/'team-leagues.json').write_text('{"competitions":{}}','utf8')
            catalogue=world.team_catalogue(self.library,None)
        china=[r for r in catalogue['teams']if r['id']in(54,49206)]
        self.assertEqual([r['name']for r in china],['中国','中国'])
        self.assertEqual([r['selection_label']for r in china],['中国（国家队编号）','中国（队套编号，同国家球员池）'])
        self.assertEqual(catalogue['leagues'][0]['team_ids'],[52,54])
        self.assertEqual(china[0]['national_team_kind'],'native')
        self.assertEqual(china[1]['national_team_kind'],'squad_alias')
        self.assertEqual([r['national_team_nation_id']for r in china],[7,7])
        self.assertEqual([r['random_national_team_id']for r in china],[54,54])
        self.assertEqual(self.identities,before)

    def catalogue(self):
        with tempfile.TemporaryDirectory()as temp:
            self.library.resources=Path(temp)
            (Path(temp)/'team-leagues.json').write_text(json.dumps({'competitions':{
                'club':{'name':'English League','team_ids':[101]},
                'mixed':{'name':'Imported mixed','team_ids':[49206,54,101,52]}}}),'utf8')
            return world.team_catalogue(self.library,None)

    def test_random_national_ids_follow_exact_native_references_not_numeric_or_chinese_label(self):
        self.identities['nation'].append({'id':9,'name':'显示名称可变','name_en':'Exact country'})
        self.identities['team'].extend([
            {'kind':'team','id':90001,'name':'原生的不同中文名','name_en':'Exact country'},
            {'kind':'team','id':3,'name':'低编号队套','name_en':'Exact country'}])
        payload=json.dumps(self.card(99,nation=9,native=90001))
        self.db.execute('insert into players values(?,?,?)',('99','Standard',payload))
        catalogue=self.catalogue();rows={r['id']:r for r in catalogue['teams']}
        self.assertEqual(catalogue['leagues'][0]['team_ids'],[52,54,90001])
        self.assertEqual(rows[90001]['national_team_kind'],'native')
        self.assertEqual(rows[3]['national_team_kind'],'squad_alias')
        self.assertEqual(rows[3]['random_national_team_id'],90001)
        self.assertNotIn('national_team_kind',rows[101])
        self.assertEqual(catalogue['leagues'][1]['team_ids'],[101])
        self.assertEqual(catalogue['national_team_nations']['3'],9)

    def test_ambiguous_native_reference_is_not_guessed_or_replaced_with_alias(self):
        self.db.execute('insert into players values(?,?,?)',('99','Standard',json.dumps(self.card(99,native=49206))))
        catalogue=self.catalogue();rows={r['id']:r for r in catalogue['teams']}
        self.assertEqual(catalogue['leagues'][0]['team_ids'],[52])
        self.assertIsNone(rows[54]['random_national_team_id'])
        self.assertIsNone(rows[49206]['random_national_team_id'])
        self.assertEqual(catalogue['national_team_nations'],{'54':7,'49206':7,'52':8})

    def test_catalogue_refresh_preserves_manual_alias_ids_and_existing_saved_competition(self):
        import tournament_runtime as runtime
        import uuid
        self.db.execute('create table meta(key primary key,value)')
        definition=runtime.configuration([dict(uuid=str(uuid.uuid4()),name='Existing manual IDs',enabled=True,
            team_ids=[54,49206],player_team_id=49206,stages=[dict(type='knockout')])])[0]
        before=runtime.state(self.db,definition)
        self.catalogue()
        after=runtime.state(self.db,definition)
        self.assertEqual(after,before)
        self.assertEqual(after['definition']['team_ids'],[54,49206])
        self.assertEqual(after['definition']['player_team_id'],49206)

    def test_both_cpu_pools_contain_the_same_native_preset_and_country_members(self):
        before=list(self.db.execute('select *from managed_cards'))
        for cpu in (False,True):
            pools=[{p['gameplayer_id']['id']for p in club_cards(self.db,self.doc,team,cpu=cpu)}for team in(54,49206)]
            self.assertEqual(pools,[{1,2,3},{1,2,3}])
        self.assertEqual(list(self.db.execute('select *from managed_cards')),before)

    def test_same_exclusions_diy_and_recycle_scope_are_respected_for_both_ids(self):
        self.doc['division_squads']={'excluded_ids':['2']}
        self.doc['players']=[{'identity':{'card_id':3}}]
        for team in(54,49206):
            self.assertEqual({p['gameplayer_id']['id']for p in club_cards(self.db,self.doc,team,False)},{1})

    def test_missing_standard_exports_use_same_family_without_retraining_originals(self):
        before=list(self.db.execute('select *from players'))
        for team in(54,49206):
            self.doc['tournaments']=[{'team_ids':[team]}]
            self.assertEqual(set(export_standard_cards(self.library,self.doc)),{'1','2','3'})
        self.assertEqual(list(self.db.execute('select *from players')),before)

    def test_owned_players_can_be_used_with_either_represented_id(self):
        service=Service(lambda:self.doc,'.',None)
        active={'player_side':'HOME','home':{'player_list':[]}}
        fake=types.SimpleNamespace(players=lambda c:copy.deepcopy(self.cards),wire_player=copy.deepcopy)
        before=list(self.db.execute('select *from gameplayers'))
        with patch.dict('sys.modules',{'club_store':fake}):
            for team in(54,49206):
                self.assertEqual(set(service.player_pool(self.db,{'player_team_id':team},active)),{(1,101),(2,102),(3,103)})
        self.assertEqual(list(self.db.execute('select *from gameplayers')),before)

    def test_ambiguous_country_name_does_not_guess(self):
        self.identities['nation'].append({'id':99,'name':'同名','name_en':'China PR'})
        self.assertNotIn('54',world.national_teams(self.library))
        self.assertNotIn('49206',world.national_teams(self.library))

    def test_unreferenced_country_and_alias_share_real_nationality_pool_but_are_not_native_random_ids(self):
        self.identities['nation'].append({'id':9,'name':'斯洛伐克','name_en':'Slovakia'})
        self.identities['team'].extend([{'kind':'team','id':20,'name':'斯洛伐克','name_en':'Slovakia'},
                                       {'kind':'team','id':82020,'name':'斯洛伐克','name_en':'Slovakia'}])
        mapping=world.national_teams(self.library)
        self.assertEqual(mapping['20'],9);self.assertEqual(mapping['82020'],9)
        catalogue=self.catalogue();rows={r['id']:r for r in catalogue['teams']}
        for team in(20,82020):
            self.assertEqual(rows[team]['national_team_kind'],'country_mapped')
            self.assertEqual(rows[team]['national_mapping_source'],'exact_unique_country_name')
            self.assertIsNone(rows[team]['random_national_team_id'])
            self.assertNotIn(team,catalogue['leagues'][0]['team_ids'])
        self.assertIn('未验证原生引用',rows[20]['selection_label'])

if __name__=='__main__':unittest.main()
