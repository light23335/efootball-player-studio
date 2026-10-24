from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy,json,sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from custom_boosters import CUSTOM_IDS,reserve_booster,text_key
from native_strings import booster_rows
from install_pairs import check,validate_install
from apk_installation import GAME,RESOURCES,COEXIST_GAME,COEXIST_RESOURCES
from library_cleanup import cleanup_old_libraries

class CapacityTests(unittest.TestCase):
 def test_shared_library_stores_10000_definitions_with_paged_search(self):
  from booster_library import BoosterLibrary
  with tempfile.TemporaryDirectory() as folder:
   library=BoosterLibrary(Path(folder));p={'package_id':str(uuid.uuid4()),'custom_boosters':[{'id':1000+i,'uuid':str(uuid.uuid4()),'label':'共享 '+str(i),'effects':{'34':3}} for i in range(10000)]}
   library.sync(p);result=library.list('',9950);self.assertEqual(result['saved_total'],10000);self.assertEqual(len(result['rows']),50)
   p['custom_boosters']=[{'id':1000,'uuid':str(uuid.uuid4()),'label':'溢出','effects':{}}]
   with self.assertRaisesRegex(ValueError,'10000'):library.sync(p)
   self.assertEqual(library.list()['saved_total'],10000)
 def test_first_slot_alias_keeps_historical_second_slot_id(self):
  registry={'shared':1000};before=dict(registry)
  first=reserve_booster('shared',registry,{1,2,1000},first_slot=True)
  self.assertTrue(1<=first<=255);self.assertEqual(registry['shared'],1000)
  self.assertEqual(registry['shared:slot0'],first);self.assertEqual(reserve_booster('shared',registry),1000)
  self.assertEqual(reserve_booster('shared',registry,first_slot=True),first)
  p=app.default_project();p['custom_boosters']=[{'id':10999,'uuid':str(uuid.uuid4()),'label':'共享项','effects':{'34':3}}];p['booster_ids']=[10999,0]
  self.assertEqual(app.normalize_project(p)['booster_ids'],[10999,0])
 def test_shared_library_reuses_identity_without_consuming_new_definition(self):
  with tempfile.TemporaryDirectory() as folder:
   store=app.Store(folder);p=app.default_project();p['identity']['name']='球员甲'
   uid=str(uuid.uuid4());p['custom_boosters']=[{'id':1000,'uuid':uid,'label':'同一共享增能','effects':{'34':3}}];p['booster_ids']=[0,1000]
   store.save(p);q=copy.deepcopy(p);q['package_id']=str(uuid.uuid4());q['identity']['name']='球员乙';q['booster_ids']=[1000,0];store.save(q)
   rows=store.boosters.list();self.assertEqual(rows['capacity'],10000);self.assertEqual(rows['total'],1);self.assertEqual(rows['rows'][0]['uuid'],uid)
   q['custom_boosters'][0]['effects']['34']=5;store.save(q);self.assertEqual(store.boosters.list()['rows'][0]['effects']['34'],5)
   store.save(p);self.assertEqual(store.boosters.list()['rows'][0]['effects']['34'],5)
 def test_boosters_expand_past_24_preserving_every_existing_id_and_text_route(self):
  registry={str(i):1000+i for i in range(24)};before=dict(registry)
  self.assertEqual(reserve_booster('new',registry,{999,998,997}),996)
  self.assertEqual({k:registry[k] for k in before},before)
  self.assertEqual(len(CUSTOM_IDS),1023);self.assertEqual(len({text_key(i) for i in CUSTOM_IDS}),1023)
  self.assertEqual(text_key(1000),60000);self.assertEqual(text_key(1023),60046);self.assertGreater(text_key(999),60046)
  self.assertEqual(reserve_booster('new',registry),996)
  p=app.default_project();p['custom_boosters']=[{'id':996,'uuid':str(uuid.uuid4()),'label':'扩容增能','effects':{'34':3}}];p['booster_ids']=[0,996]
  p=app.normalize_project(p);texts,routes=booster_rows([p],app.CATALOG['ABILITIES']);self.assertEqual(texts[text_key(996)],'扩容增能');self.assertEqual(routes[0]['id'],996)
 def test_10000_capacity_allows_updates_but_rejects_new_identity(self):
  with tempfile.TemporaryDirectory() as folder:
   store=app.Store(folder);p=app.default_project();p['identity']['name']='保留球员';store.save_player(p)
   with patch.object(app,'MAX_PERSONAL_PLAYERS',1):
    store.save_player(p);q=copy.deepcopy(p);q['package_id']=str(uuid.uuid4())
    with self.assertRaisesRegex(ValueError,'10000'):store.save_player(q)
   self.assertEqual(app.MAX_PERSONAL_PLAYERS,10000)
   for i in range(3):p=copy.deepcopy(p);p['package_id']=str(uuid.uuid4());p['identity']['name']='分页 '+str(i);store.save_player(p)
   result=store.list_players('',1,2);self.assertEqual(len(result['rows']),2);self.assertEqual(result['total'],4);self.assertEqual(result['capacity'],10000)

class PairTests(unittest.TestCase):
 def row(self,package,kind,signer):return {'package':package,'kind':kind,'signers':[signer],'authorities':[]}
 def test_original_and_diy_can_coexist_with_separate_signers(self):
  rows=[self.row(GAME,'game','original'),self.row(RESOURCES,'resource','original'),self.row(COEXIST_GAME,'game','diy'),self.row(COEXIST_RESOURCES,'resource','diy')]
  self.assertTrue(check(rows)['passed']);rows[-1]['signers']=['wrong'];self.assertFalse(check(rows)['passed'])
  self.assertTrue(check(rows,target=GAME)['passed']);self.assertFalse(check(rows,target=COEXIST_GAME)['passed'])
 def test_missing_resource_stops_game_install_but_resource_can_install_first(self):
  game=self.row(COEXIST_GAME,'game','diy');resource=self.row(COEXIST_RESOURCES,'resource','diy')
  with patch('install_pairs.inspect',return_value=game):
   with self.assertRaisesRegex(ValueError,'先安装对应资源'):validate_install('game.apk',[])
   self.assertTrue(validate_install('game.apk',[resource])['passed'])
  with patch('install_pairs.inspect',return_value=resource):self.assertTrue(validate_install('resource.apk',[])['passed'])

class CleanupTests(unittest.TestCase):
 def test_only_superseded_owned_databases_and_their_cache_are_removed(self):
  with tempfile.TemporaryDirectory() as folder:
   home=Path(folder);store=SimpleNamespace(root=home/'data');root=store.root/'game-databases';root.mkdir(parents=True)
   ids=['a'*24,'b'*24]
   for key,namespace in zip(ids,['V15-old','V16-current']):
    target=root/key;target.mkdir();(target/'import-report.json').write_text(json.dumps({'format':'player-studio-apk-database-v1'}));(target/'native-resource-profile.json').write_text(json.dumps({'cache_namespace':namespace}))
    cache=home/'library/versions'/namespace;cache.mkdir(parents=True);(cache/'ready.json').write_text('{}')
   assets=store.root/'assets';assets.mkdir();(assets/'personal.png').write_bytes(b'keep')
   (store.root/'active-game.json').write_text(json.dumps({'database':ids[0]}))
   with self.assertRaisesRegex(ValueError,'尚未切换'):cleanup_old_libraries(store,home,root/ids[1])
   self.assertTrue((root/ids[0]).exists())
   (store.root/'active-game.json').write_text(json.dumps({'database':ids[1]}));result=cleanup_old_libraries(store,home,root/ids[1])
   self.assertEqual(result['databases'],1);self.assertEqual(result['cache_versions'],1)
   self.assertTrue((root/ids[1]).exists());self.assertTrue((home/'library/versions/V16-current').exists());self.assertEqual((assets/'personal.png').read_bytes(),b'keep')

class BindingCapacityTests(unittest.TestCase):
 def test_10000_routes_with_thumbnail_records_fit_external_table(self):
  from test_v193_binding import V193BindingTests as Native
  from personal_binding import compose
  Native.setUpClass()
  routes=[dict(Native.route,cardId=990001+i,portraitKey=str(8000000+i),modelFaceKey=str(8000000+i),thumbnail_names=[str(8000000+i)+'f']*6) for i in range(10000)]
  out=compose(Native.payload,routes,Native.profile)
  self.assertEqual(len(bytes.fromhex(out['route_table_hex'])),10001*144)
  self.assertGreater(len(bytes.fromhex(out['extension_blob_hex'])),10000*152)
