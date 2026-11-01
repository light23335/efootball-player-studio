from pathlib import Path
import contextlib,copy,hashlib,json,sqlite3,sys,tempfile,types,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import write_modes as w
import test_container_compaction as container_fixture
from native_iostore import append_container
from personal_runtime import apply_write_selection,backup_write_selection

class WriteModesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.store=types.SimpleNamespace(root=self.root);(self.root/'assets').mkdir()
  self.project={'package_id':str(uuid.uuid4()),'studio_version':'2.1.5','abilities':{'20':80},'identity':{'name':'A'},'booster_ids':[],'custom_boosters':[]}
  self.old={'players':[{'identity':{'package_id':self.project['package_id'],'card_id':123,'previous_card_ids':[122]},'owned':{}}],'coaches':[],'packs':[]}
 def test_design_ignores_editor_version_but_tracks_abilities_and_actual_assets(self):
  p=copy.deepcopy(self.project);p['studio_version']='99';p['status']='saved'
  self.assertEqual(w.design('players',p,self.store),w.design('players',self.project,self.store))
  p['abilities']['20']=81;self.assertNotEqual(w.design('players',p,self.store),w.design('players',self.project,self.store))
  name=hashlib.sha256(b'original').hexdigest()+'.png';(self.root/'assets'/name).write_bytes(b'original');p['portrait']=name
  a=w.design('players',p,self.store);(self.root/'assets'/name).write_bytes(b'edited');self.assertNotEqual(a,w.design('players',p,self.store))
 def test_status_positive_only_and_reload_is_stable(self):
  self.assertEqual(w.statuses('players',[self.project],self.old,self.store)[self.project['package_id']],'unverified')
  self.old['write_designs']=w.designs([self.project],[],[],self.store)
  self.assertEqual(w.statuses('players',[self.project],self.old,self.store)[self.project['package_id']],'unchanged')
  changed=copy.deepcopy(self.project);changed['abilities']['20']=81
  self.assertEqual(w.statuses('players',[changed],self.old,self.store)[self.project['package_id']],'modified')
  changed['package_id']=str(uuid.uuid4());self.assertEqual(w.statuses('players',[changed],self.old,self.store)[changed['package_id']],'new')
 def test_exact_legacy_design_is_unchanged_but_any_edit_is_unverified(self):
  self.old['players'][0]['owned']['_personal_design_revision']=hashlib.sha256(w.encoded(self.project)+b':v16-compiler-1.9.2').hexdigest()
  p=copy.deepcopy(self.project);p['studio_version']='2.1.6'
  self.assertTrue(w.legacy_unchanged(p,self.old['players'][0],self.store))
  p['abilities']['20']=81;self.assertFalse(w.legacy_unchanged(p,self.old['players'][0],self.store))
 def test_retained_and_tombstones_use_exact_ownership_not_player_names(self):
  selected=dict(players=set(),coaches=set(),packs=set());compiled=copy.deepcopy(selected)
  self.assertEqual(w.retained(self.old,'incremental',selected,compiled)['players'],self.old['players'])
  full=w.retained(self.old,'full',selected,compiled);self.assertEqual(full['players'],[])
  self.assertEqual(w.removals(self.old,full)['player_ids'],[122,123])
  full['write_selection']={'removed':w.removals(self.old,full)}
  self.assertEqual(w.removals(full,self.old)['player_ids'],[])
 def test_carried_full_selected_player_and_preview_booster_survive(self):
  self.old['players'][0]['base_parameters']=[0]*144+[1000,76,0];self.old['preview_boosters']={'1000':{'effects':{'20':2}},'1001':{}}
  uid=self.project['package_id'];keep=w.retained(self.old,'full',{'players':{uid},'coaches':set(),'packs':set()},{k:set()for k in ('players','coaches','packs')})
  self.assertEqual(len(keep['players']),1);self.assertIn('1000',keep['preview_boosters']);self.assertNotIn('1001',keep['preview_boosters'])
 def test_retained_pack_refreshes_changed_identity_and_requires_full_dependencies(self):
  new=copy.deepcopy(self.old['players'][0]);new['identity']['card_id']=124;new.update(owned={'level_info':{}},base_parameters=[80],card_type='Epic',card_series='Epic')
  pack={'uuid':'pack','name':'P','members':[{'card_id':'122','payload':{},'weight':2}]}
  refreshed=w.refresh_packs([pack],self.old['players'],[new]);self.assertEqual(refreshed[0]['members'][0]['card_id'],'124');self.assertEqual(refreshed[0]['members'][0]['weight'],2)
  with self.assertRaisesRegex(ValueError,'P.*未勾选'):w.refresh_packs([pack],self.old['players'],[])
 def test_derived_release_and_content_requirements(self):
  from content_delta import CONTENT
  path=self.root/'game.apk'
  with zipfile.ZipFile(path,'w')as z:
   z.writestr(w.RELEASE,json.dumps({'release_id':'v17-studio-new','base_release_id':'v17'}))
   z.writestr(CONTENT,json.dumps({'format':'studio-content-catalogue-v1','packages':[{'package_id':'delta','manifest_sha256':'abc'}]}))
  required={'release_id':'v17-studio-old','packages':[{'package_id':'delta','manifest_sha256':'abc'}]}
  doc,meta=w.source(path,required);self.assertEqual(doc,{});self.assertTrue(meta['token'])
  required['packages'][0]['manifest_sha256']='different'
  with self.assertRaisesRegex(ValueError,'增量'):w.source(path,required)
  with self.assertRaisesRegex(ValueError,'不兼容'):w.source(path,'v16')
 def test_latest_export_uses_successful_report_and_actual_compatible_main(self):
  folder=self.root/'exports';folder.mkdir();path=folder/'good.apk'
  with zipfile.ZipFile(path,'w')as z:z.writestr(w.RELEASE,json.dumps({'release_id':'v17-studio-2','base_release_id':'v17'}))
  (folder/'good.report.json').write_text(json.dumps({'signature':{'verified_v2':True},'output':str(path),'resource_release':'v17-studio-2'}))
  self.assertEqual(w.latest_export(self.store,'v17')['path'],str(path.absolute()))
  with zipfile.ZipFile(path,'w')as z:z.writestr('assets/resource-bootstrap/resources.zip',b'not game')
  self.assertIsNone(w.latest_export(self.store,'v17'))
 def test_direct_source_container_keeps_indirect_chunks_in_stored_and_deflated_apk(self):
  fixture=container_fixture.ContainerCompactionTests('test_shared_live_blocks_and_empty_chunks_survive');fixture.setUp();self.addCleanup(fixture.doCleanups)
  src=fixture.rewrite(fixture.source,True)
  stem='assets/gateway-release/custom-resources/legends-v10/pc3700_mobile_and'
  for method in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
   work=self.root/str(method);work.mkdir();apk=work/'game.apk'
   with zipfile.ZipFile(apk,'w')as z:
    z.writestr(stem+'.utoc',src.path.read_bytes());z.writestr(stem+'.ucas',src.path.with_suffix('.ucas').read_bytes(),compress_type=method)
   with zipfile.ZipFile(apk)as z:container=w.source_container(z,work,src.key)
   self.assertEqual((work/'write-source.ucas').exists(),method!=zipfile.ZIP_STORED)
   result=append_container(container,work/'out.utoc',[],{},[])
   for i,value in enumerate(fixture.values):self.assertEqual(result.read_chunk(i+1),value)
 def test_full_removal_preserves_original_and_unaffected_progress_and_makes_backup(self):
  conn=sqlite3.connect(self.root/'save.db');self.addCleanup(conn.close)
  conn.executescript("""create table meta(key text primary key,value text);create table gameplayers(id integer,serial integer,json text,source text,acquired_at text);
  create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
  create table managed_members(agent_id integer,card_id text);create table managed_agents(agent_id integer);create table agents(agent_id integer);
  create table coaches(coach_id integer,serial integer,json text);create table squads(squad_id integer,json text);""")
  for cid in (123,7511):conn.execute('insert into gameplayers values(?,?,?,?,?)',(cid,cid,json.dumps({'gameplayer_id':{'id':cid,'serial':cid},'level_info':{'level':35,'exp_total':9999}}),'source','now'))
  conn.execute('insert into coaches values(?,?,?)',(600001,1,'{}'));conn.execute('insert into coaches values(?,?,?)',(8,1,'{}'))
  conn.execute('insert into squads values(?,?)',(1,json.dumps({'coach_id':{'id':600001,'serial':1},'player_list':[]})))
  for table in ('managed_agents','agents'):conn.execute('insert into '+table+' values(?)',(600002,))
  conn.execute('insert into managed_members values(?,?)',(600002,'123'));conn.commit()
  doc={'players':[],'coaches':[],'packs':[],'write_selection':{'removed':{'player_ids':[123],'coach_ids':[600001],'pack_ids':[600002]}}};registry={'gone':{'card_id':123},'keep':{'card_id':7511}}
  backup_write_selection(conn,doc)
  with conn:apply_write_selection(conn,doc,registry)
  self.assertEqual([r[0]for r in conn.execute('select id from gameplayers')],[7511]);self.assertEqual(json.loads(conn.execute('select json from gameplayers').fetchone()[0])['level_info']['exp_total'],9999)
  self.assertEqual(json.loads(conn.execute('select json from squads').fetchone()[0])['coach_id']['id'],8);self.assertEqual(registry,{'keep':{'card_id':7511}})
  self.assertEqual(conn.execute('select count(*)from managed_members').fetchone()[0],0)
  backups=list((self.root/'studio-write-backups').glob('*.sqlite3'));self.assertEqual(len(backups),1)
  with contextlib.closing(sqlite3.connect(backups[0]))as c:self.assertEqual(c.execute('select count(*)from gameplayers').fetchone()[0],2)
  with conn:apply_write_selection(conn,doc,registry)
  self.assertEqual(conn.execute('pragma quick_check').fetchone()[0],'ok')

if __name__=='__main__':unittest.main()
