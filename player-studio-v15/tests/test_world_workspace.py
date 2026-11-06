import copy,hashlib,json,sqlite3,tempfile,threading,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import world_workspace as world
import stadium_runtime
from tournament_runtime import native_rules,configuration,state,Service,project_events,export_selection,mainmenu,ENTRY_IMAGE
import tournament_rules as rules

class WorkspaceTests(unittest.TestCase):
 def test_native_events_tile_enabled_image_updated_and_other_native_tiles_preserved(self):
  original={'result':'NOERR','event_info_list':[{'event_info_type':'AI_MATCH','event_banner':'keep'},{'event_info_type':'BOTH','event_end_time':1,'event_banner':'old'}],'league_info':{'keep':1}}
  out=mainmenu(copy.deepcopy(original));self.assertEqual(out['event_info_list'][0]['event_banner'],ENTRY_IMAGE)
  self.assertGreater(out['event_info_list'][0]['event_end_time'],1900000000)
  child=next(r for r in out['event_info_list']if r['event_info_type']=='AI_MATCH')
  self.assertEqual(child['event_banner'],ENTRY_IMAGE);self.assertGreater(child['event_end_time'],1900000000)
  self.assertEqual(out['league_info'],original['league_info'])
  self.assertEqual(mainmenu(copy.deepcopy(out)),out);self.assertEqual(mainmenu({'result':'ERROR'}),{'result':'ERROR'})
 def test_parent_and_ai_child_available_and_other_activities_removed(self):
  now=1793620800
  original={'result':'NOERR','event_info_list':[{'event_info_type':'BOTH','event_end_time':1792634399},
   {'event_info_type':'AI_MATCH','event_end_time':1792634399},{'event_info_type':'USER_MATCH','event_end_time':1792634399,'keep':True}]}
  out=mainmenu(copy.deepcopy(original))
  self.assertTrue(all(r['event_end_time']>now for r in out['event_info_list']if r['event_info_type']in('BOTH','AI_MATCH')))
  self.assertEqual([r['event_info_type']for r in out['event_info_list']],['BOTH','AI_MATCH'])
 def test_removed_mosaic_migrates_to_whole_poster_without_losing_source(self):
  from stadium_assets import stand_image
  im=Image.new('RGB',(1024,512),'red');im.paste((0,0,255),(512,0,1024,512));path=self.store.root/'sample.png';im.save(path)
  mosaic=stand_image(path,'mosaic')
  self.assertEqual(mosaic.getpixel((8,10)),(255,0,0,255));self.assertEqual(mosaic.getpixel((1000,10)),(0,0,255,255))
  self.assertEqual(mosaic.tobytes(),stand_image(path,'poster').tobytes())
  document=world.default();obj={'kind':'stand','asset':'a'*64+'.png','preview_asset':'b'*64+'.glb','name':'Keep','layout':'mosaic','preview_revision':'old:mosaic'}
  document['stadium']['slots'][0]['stand_tifo']=obj
  migrated=world.normalize(document)['stadium']['slots'][0]['stand_tifo']
  self.assertEqual(migrated['layout'],'poster');self.assertEqual(migrated['asset'],obj['asset']);self.assertEqual(migrated['name'],'Keep')
  self.assertNotIn('preview_revision',migrated);self.assertEqual(obj['layout'],'mosaic')
 def test_only_custom_events_typed_phase_and_readable_player_summary(self):
  from tournament_runtime import summary,overview_html
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.execute('create table meta(key primary key,value)')
  d=configuration([{'uuid':str(uuid.uuid4()),'name':'League','enabled':True,'team_ids':[101,108,103,100],'player_team_id':101,'stages':[{'type':'league'}]}])
  proto={'event_id':1120005,'match_env':{},'ch_event_type':'TOURNAMENT','ch_mission_info_list':[{}],
         'is_vsai_custom_team':'YES','is_vsai_force_no_substitute':'YES','is_vsai_gameplan_disp':'NO'}
  response={'result':'NOERR','event_list':[proto,{'event_id':90002}],'event_log_list':[{'event_id':1120005,'ch_mission_log':[{}]},{'event_id':90002}]}
  names={'101':'阿森纳','108':'利物浦','103':'曼联','100':'切尔西'}
  out=project_events(types.SimpleNamespace(conn=conn),response,d,ENTRY_IMAGE,names,'wide','http://127.0.0.1:1234/player-studio/tournaments')
  self.assertEqual(len(out['event_list']),1);self.assertEqual(len(out['event_log_list']),1);row=out['event_list'][0]
  self.assertIsInstance(row['ch_mission_info_list'][0]['compe_phase_info'],dict)
  self.assertEqual(row['announce_banner_file_name'],'');self.assertEqual(row['event_menu_banner_file_name'],'wide')
  self.assertIn('阿森纳',row['description_text']);self.assertNotIn('101',row['description_text']);self.assertIn('本阶段剩余 3 场',row['description_text'])
  html=overview_html(state(conn,d[0]),names).decode();self.assertIn('积分榜',html);self.assertIn('利物浦',html)
  self.assertEqual(len(row['link_title_list']),1)
  self.assertEqual(row['ch_event_type'],'CHALLENGE')
  self.assertEqual(row['match_entry']['entry_type'],'CLUB')
  self.assertEqual(row['match_entry']['entity_id_list'],[101])
  self.assertEqual(row['match_entry']['player_num'],23)
  self.assertEqual(row['is_vsai_custom_team'],'NO')
  self.assertEqual(row['is_vsai_force_no_substitute'],'NO')
  self.assertEqual(row['is_vsai_gameplan_disp'],'YES')
  native_nation=project_events(types.SimpleNamespace(conn=conn),{'result':'NOERR','event_list':[proto]},d,nations={'101':7})['event_list'][0]['match_entry']
  self.assertEqual(native_nation['entry_type'],'NATIONALITY');self.assertEqual(native_nation['entity_id_list'],[7])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=types.SimpleNamespace(root=Path(self.tmp.name),lock=threading.RLock());(self.store.root/'assets').mkdir()
 def test_partial_design_durable_and_invalid_resource_cannot_escape_assets(self):
  doc=world.default();doc['tournaments']=[{'uuid':str(uuid.uuid4()),'enabled':False,'name':'Incomplete'}]
  saved=world.save(self.store,doc)['document'];self.assertEqual(world.load(self.store),saved)
  obj={'kind':'model','asset':'../outside.glb'};doc['stadium']['slots'][0]['objects'][0]=obj
  with self.assertRaisesRegex(ValueError,'引用'):world.save(self.store,doc)
  self.assertIsNone(world.load(self.store)['stadium']['slots'][0]['objects'][0])
 def test_stadium_revision_seeds_once_preserves_game_edits_and_backs_up(self):
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.execute('create table meta(key primary key,value)')
  native={'slots':[{'stadium_id':i,'name':'old'}for i in(101,102,103)],'selected':101}
  fake=types.SimpleNamespace(state=lambda c:copy.deepcopy(native),validate_slot=lambda s:copy.deepcopy(s),
                            save=lambda c,v:native.update(copy.deepcopy(v)))
  document={'stadium':{'enabled':True,'selected':102,'slots':[{'stadium_id':i,'name':'new'}for i in(101,102,103)]}}
  with patch.dict('sys.modules',{'custom_stadium':fake}):
   self.assertTrue(stadium_runtime.apply(conn,document));native['slots'][0]['name']='Game edit'
   self.assertFalse(stadium_runtime.apply(conn,document));self.assertEqual(native['slots'][0]['name'],'Game edit')
   document['stadium']['unlock_all']=True;document['stadium']['unlock_catalogue']={'assets':[]}
   self.assertFalse(stadium_runtime.apply(conn,document));self.assertEqual(native['slots'][0]['name'],'Game edit')
  self.assertEqual(conn.execute('select count(*)from meta').fetchone()[0],2)
 def test_unlock_all_72_typed_assets_default_on_idempotent_no_currency_change(self):
  self.assertTrue(world.default()['stadium']['unlock_all']);catalog=world.unlock_catalogue()
  self.assertEqual(len(catalog['assets']),72);self.assertEqual(len(catalog['anchors']),6)
  self.assertEqual(len({stadium_runtime.asset_key(a)for a in catalog['assets']}),72)
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.execute('create table meta(key primary key,value)')
  conn.execute('insert into meta values(?,?)',('coins','987'))
  original=copy.deepcopy(catalog['assets'][0]);original['player_note']='preserve'
  conn.execute('insert into meta values(?,?)',(catalog['owned_key'],json.dumps([original])))
  value={'unlock_all':True,'unlock_catalogue':catalog};owned=stadium_runtime.unlock(conn,value)
  self.assertEqual(len(owned),72);self.assertEqual(owned[0],original)
  before=conn.total_changes;self.assertEqual(stadium_runtime.unlock(conn,value),owned);self.assertEqual(conn.total_changes,before)
  self.assertEqual(conn.execute('select value from meta where key="coins"').fetchone()[0],'987')
  value['unlock_all']=False;self.assertIsNone(stadium_runtime.unlock(conn,value));self.assertEqual(conn.total_changes,before)
  value['unlock_all']=True;value['unlock_catalogue']=copy.deepcopy(catalog);value['unlock_catalogue']['assets'].append({'stadium_asset_id':-1})
  with self.assertRaises(ValueError):stadium_runtime.unlock(conn,value)
  self.assertEqual(json.loads(conn.execute('select value from meta where key=?',(catalog['owned_key'],)).fetchone()[0]),owned)
 def test_login_unlock_updates_native_entry_after_original_and_only_on_success(self):
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.execute('create table meta(key primary key,value)')
  class Logic:
   def __init__(self):self.conn=conn
   def handle(self,cmd,req):return {'result':'NOERR'if req.get('ok')else'ERROR','entry_info':{'stadium_asset_unlocked_list':[]}}
  document={'stadium':{'enabled':False,'unlock_all':True,'unlock_catalogue':world.unlock_catalogue()}}
  logic=Logic()
  with patch.dict('sys.modules',{'custom_stadium':types.SimpleNamespace()}):
   stadium_runtime.install(lambda:document,logic)
   self.assertEqual(logic.handle('CMD_LOGIN',{})['entry_info']['stadium_asset_unlocked_list'],[])
   self.assertEqual(len(logic.handle('CMD_LOGIN',{'ok':True})['entry_info']['stadium_asset_unlocked_list']),72)
   document['stadium']['unlock_all']=False
   self.assertEqual(len(logic.handle('CMD_GET_CUSTOM_STADIUM',{'ok':True})['entry_info']['stadium_asset_unlocked_list']),72)
 def test_image_tifo_has_real_thickness_and_opaque_texture(self):
  from stadium_assets import tifo,preview_glb,flatten
  from native_glb import Glb
  values=tifo(Image.new('RGBA',(16,8),(250,50,60,128)),12,8)
  self.assertEqual(len(values[0]),24);self.assertEqual(len(values[3]),12)
  raw=preview_glb(*values);glb=Glb(raw)
  self.assertNotEqual(max(v[2]for v in values[0]),min(v[2]for v in values[0]))
  self.assertTrue(all(m.get('alphaMode','OPAQUE')=='OPAQUE'and not m.get('doubleSided',False)for m in glb.doc['materials']))
  self.assertEqual(len(flatten(raw)[3]),12)
 def test_two_leg_prior_goals_follow_current_home_away(self):
  d={'uuid':str(uuid.uuid4()),'name':'Two legs','team_ids':[101,108],'player_team_id':101,'stages':[{'type':'knockout','legs':2,'away_goals':True}]}
  s=rules.start(d,1);first=rules.due(s)[0];self.assertTrue(native_rules(s,first)['first_leg'])
  self.assertFalse(native_rules(s,first)['penalties']);rules.record(s,first['id'],3,1)
  second=rules.due(s)[0];n=native_rules(s,second)
  self.assertTrue(n['second_leg']);self.assertEqual(n['prior_goals'],[1,3]);self.assertTrue(n['away_goals'])
 def test_definition_update_backs_up_progress_and_keeps_stable_event_id(self):
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.execute('create table meta(key primary key,value)')
  d={'uuid':str(uuid.uuid4()),'name':'Cup','enabled':True,'team_ids':[101,108],'player_team_id':101,'stages':[{'type':'knockout'}]}
  one=configuration([d])[0];a=state(conn,one);self.assertEqual(state(conn,one)['run_id'],a['run_id'])
  d['difficulty']='VERYHARD';two=configuration([d])[0];b=state(conn,two)
  self.assertEqual(a['run_id'],b['run_id'])
  d['stages'][0]['legs']=2;two=configuration([d])[0];b=state(conn,two)
  self.assertEqual(one['event_id'],two['event_id']);self.assertNotEqual(a['run_id'],b['run_id'])
  self.assertTrue(conn.execute("select 1 from meta where key like '%:backup:%'").fetchone())
 def test_disk_reopen_resumes_fixtures_and_only_changed_tournament_resets(self):
  path=self.store.root/'save.sqlite';conn=sqlite3.connect(path);conn.execute('create table meta(key primary key,value)')
  definitions=[{'uuid':str(uuid.uuid4()),'name':name,'enabled':True,'team_ids':[101,108,103,100],'player_team_id':101,'stages':[{'uuid':str(uuid.uuid4()),'type':'knockout'}]}for name in ('Cup A','Cup B')]
  a,b=configuration(definitions);first=state(conn,a);second=state(conn,b);fixture=rules.due(first)[0];rules.record(first,fixture['id'],2,0)
  from tournament_runtime import put,PREFIX
  put(conn,PREFIX+a['uuid'],first);conn.commit();conn.close()
  conn=sqlite3.connect(path);self.addCleanup(conn.close)
  self.assertEqual(state(conn,a),first);self.assertEqual(state(conn,b),second)
  definitions[0]['name']='Cup A changed';renamed,unchanged=configuration(definitions)
  self.assertEqual(state(conn,renamed)['run_id'],first['run_id']);self.assertEqual(state(conn,unchanged),second)
  definitions[0]['stages'][0]['legs']=2;changed,unchanged=configuration(definitions)
  self.assertNotEqual(state(conn,changed)['run_id'],first['run_id']);self.assertEqual(state(conn,unchanged),second)
 def test_export_selection_respects_full_incremental_and_revision_is_stable(self):
  a={'uuid':str(uuid.uuid4()),'name':'Old A','enabled':True,'team_ids':[101,108],'player_team_id':101,'stages':[{'type':'knockout'}]}
  b=copy.deepcopy(a);b['uuid']=str(uuid.uuid4());b['name']='New B'
  source=configuration([a]);self.assertEqual(configuration(source),source)
  self.assertEqual(export_selection([b],source,[],'full'),[])
  self.assertEqual(export_selection([b],source,[],'incremental'),source)
  result=export_selection([b],source,[b['uuid']],'incremental');self.assertEqual({r['uuid']for r in result},{a['uuid'],b['uuid']})
  a['name']='Edited A';result=export_selection([a],source,[a['uuid']],'incremental');self.assertEqual(len(result),1);self.assertEqual(result[0]['name'],'Edited A')
  with self.assertRaisesRegex(ValueError,'不存在'):export_selection([b],source,['unknown'],'full')

 def test_tournament_can_use_owned_same_team_without_granting_or_retraining(self):
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
  conn.execute('create table gameplayers(id,serial,json)')
  rows=[{'gameplayer_id':{'id':cid,'serial':100+cid},'initial_base_team_id':team,
         'parameters':[rating]*147}for cid,team,rating in((1,101,75),(2,108,88),(3,101,95))]
  for p in rows:conn.execute('insert into gameplayers values(?,?,?)',(p['gameplayer_id']['id'],p['gameplayer_id']['serial'],json.dumps(p)))
  document={'players':[{'identity':{'card_id':3}}]}
  service=Service(lambda:document,self.store.root,None);active={'player_side':'HOME','home':{'player_list':[]}}
  fake=types.SimpleNamespace(players=lambda c:[json.loads(r[0])for r in c.execute('select json from gameplayers')],wire_player=copy.deepcopy)
  with patch.dict('sys.modules',{'club_store':fake}):
   before=conn.total_changes
   pool=service.player_pool(conn,{'player_team_id':101,'include_diy':True},active)
   self.assertEqual(set(pool),{(1,101),(3,103)});self.assertEqual(pool[(1,101)]['parameters'],[75]*147)
   self.assertEqual(set(service.player_pool(conn,{'player_team_id':101,'include_diy':False},active)),{(1,101)})
   self.assertEqual(conn.total_changes,before)

 def test_completed_or_running_plan_flush_does_not_prepare_next_opponent(self):
  service=Service(lambda:{},self.store.root,None)
  request={'special_squad_data':{'squad_data':{'player_list':[]}}}
  for current in ({'receipts':{'123':{'result':'NOERR'}}},
                  {'active':{'started':True,'game_id':123}}):
   before=copy.deepcopy(current)
   with patch.object(service,'prepare',side_effect=AssertionError('must not redraw')):
    self.assertEqual(service.save_plan(None,{},current,request)['result'],'NOERR')
   self.assertEqual(current,before)
  with self.assertRaisesRegex(ValueError,'先进入'):
   service.save_plan(None,{}, {},request)

 def test_cached_start_rearms_same_shared_ai_entry_after_process_restart(self):
  service=Service(lambda:{},self.store.root,None)
  spec={'players':[{'id':i}for i in range(23)],'style':'possession','base_profile':{'id':'442'},'prepared':{}}
  active={'player_side':'AWAY','game_id':123,'fixture_id':7,'native_rules':{},'start_contract':4,'match_env':{'cpu_level':'HARDEST'},
          'start_reply':{'result':'NOERR','game_id':123},
          'home':{'_studio_tournament_squad':{'team_id':102,'tactical_spec':spec}}}
  active['native_rules']={'prior_goals':[0,0],'first_leg':False,'second_leg':False,'extra_time':False,
                          'penalties':False,'away_goals':False,'away_goals_extra_time':False}
  current={'active':active,'run_id':'same-run'}
  fake=types.SimpleNamespace(activate=lambda *args:None,deactivate=lambda *args:None)
  modules={'ai_match_runtime':fake,'custom_stadium':types.SimpleNamespace(apply=lambda conn,out:out)}
  with patch.dict('sys.modules',modules),patch.object(service,'repair_rentals'),patch.object(fake,'activate',return_value={'channels':1,'execution_enabled':True})as activate:
   out=service.start(types.SimpleNamespace(conn=None),{'auto_coaching':True},current,{'game_id':123,'side':'AWAY'})
  self.assertEqual(out,active['start_reply']);self.assertEqual(activate.call_count,1)
  handed=activate.call_args.args[0]
  self.assertEqual(handed['entry_id'],'tournament:same-run:7')
  self.assertEqual(handed['players'],spec['players']);self.assertTrue(handed['auto_coaching'])
  self.assertEqual(active['coaching'],{'channels':1,'execution_enabled':True})

 def test_owned_national_member_uses_catalogue_nationality_and_rejects_stale_ids(self):
  conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
  conn.execute('create table gameplayers(id,serial,json)');conn.execute('create table managed_cards(card_id,payload)')
  rows=[{'gameplayer_id':{'id':cid,'serial':cid},'initial_base_team_id':101,'parameters':[75]*147}for cid in(1,2,3)]
  for p in rows:
   conn.execute('insert into gameplayers values(?,?,?)',(p['gameplayer_id']['id'],p['gameplayer_id']['serial'],json.dumps(p)))
   conn.execute('insert into managed_cards values(?,?)',(str(p['gameplayer_id']['id']),json.dumps(dict(p,_nation_id=7 if p['gameplayer_id']['id']!=2 else 8))))
  document={'tournament_national_team_nations':{'900':7},'native_player_catalogue':{'version':1,'card_ids':[1,2]}}
  service=Service(lambda:document,self.store.root,None);active={'player_side':'HOME','home':{'player_list':[]}}
  fake=types.SimpleNamespace(players=lambda c:copy.deepcopy(rows),wire_player=copy.deepcopy)
  with patch.dict('sys.modules',{'club_store':fake}):
   self.assertEqual(set(service.player_pool(conn,{'player_team_id':900},active)),{(1,1)})

if __name__=='__main__':unittest.main()
