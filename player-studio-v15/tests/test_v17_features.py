from pathlib import Path
import copy,io,json,sqlite3,struct,sys,tempfile,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from native_coach_links import schema,decode,encode,normalize,compile_links,repair_legacy,TABLE
from native_coaches import ATTRIBUTES,compile_coaches,COACH,BOOSTER,TACTICS
from native_cpk import Cpk,wrap,unwrap
from native_extensions import link_hooks
from native_player import reserve_identity
from player_identity_binding import owned_person_aliases
from native_numbers import assignments,restore as restore_number,TABLE as NUMBER_TABLE

RESOURCE=Path(__file__).resolve().parents[1]/'resources'
APK=Path('C:/Users/1/Downloads/73efootball-V17.apk')
HEADER=struct.pack('<BBB5sII',255,0x21,0x83,b'WESYS',0,0)


class MemoryArchive:
 def __init__(self,files):self.files={key:wrap(value,HEADER) for key,value in files.items()}
 def read(self,name):return self.files[name]


class CoachLinkTests(unittest.TestCase):
 def test_legacy_import_reads_two_boosters_and_two_links(self):
  document={'coaches':[{'id':'19','name':'Klopp','ability_ids':[11,20,18,22],'effects':{'14':99}}]}
  fixed=repair_legacy(document)
  expected=schema()['booster_records'];self.assertEqual(fixed['coaches'][0]['effects'],{expected['11']['parameter']:1,expected['20']['parameter']:1})
  self.assertEqual([c['template_id'] for c in fixed['coaches'][0]['linkups']],[18,22])
  self.assertFalse(fixed['coaches'][0]['unmapped_abilities'])

 def test_condition_edit_preserves_type_and_unrelated_bits(self):
  info=schema();config=copy.deepcopy(info['templates'][7]);row=encode(bytes.fromhex('083f811000000000'),config,8,info)
  changed=dict(config,source_positions=[0],target_positions=[9,10],source_style=15,target_style=22)
  raw=encode(row,changed,256,info);decoded=decode(raw,info)
  self.assertEqual(decoded,dict(changed,template_id=256))
  self.assertEqual(int.from_bytes(row,'little')>>50,int.from_bytes(raw,'little')>>50)
  with self.assertRaises(ValueError):normalize(dict(config,template_id=999))
  with self.assertRaises(ValueError):normalize(dict(config,target_positions=[]))

 def test_two_custom_coaches_do_not_change_a_shared_original_condition(self):
  info=schema();original=encode(bytes(8),info['templates'][7],8,info)
  config=dict(info['templates'][7],source_positions=[0],target_positions=[9,10])
  a={'uuid':str(uuid.uuid4()),'linkups':[config,None]};b={'uuid':str(uuid.uuid4()),'linkups':[dict(config,target_positions=[12]),None]}
  archive=MemoryArchive({TABLE:original});registry={}
  files,ids,routes=compile_links(archive,[a,b],registry,info);raw=unwrap(files[TABLE])
  rows={int.from_bytes(raw[i:i+8],'little')&1023:raw[i:i+8] for i in range(0,len(raw),8)}
  self.assertEqual(rows[8],original);self.assertNotEqual(ids[a['uuid']][0],ids[b['uuid']][0])
  self.assertEqual(len(routes),2);self.assertEqual([r['template_id'] for r in routes],[8,8])

 def test_all_native_coach_attributes_compile_and_ability_slots_remain_separate(self):
  template=bytearray(176);struct.pack_into('<Q',template,0,8)
  archive=MemoryArchive({COACH:bytes(template),BOOSTER:bytes(4)})
  for index,enum in ATTRIBUTES.items():
   coach={'uuid':str(uuid.uuid4()),'name':'Coach','tactics':dict.fromkeys(TACTICS,88),'effects':{index:20},'_compiled_link_ids':[18,22]}
   files,owned=compile_coaches(archive,[coach],[{'id':'8','age':40,'raw_payload':{}}],{})
   bid=owned[0]['payload']['ability_id'][0];self.assertEqual(owned[0]['payload']['ability_id'][2:],[18,22])
   values=[int.from_bytes(unwrap(files[BOOSTER])[i:i+4],'little') for i in range(0,len(unwrap(files[BOOSTER])),4)]
   word=next(v for v in values if v&1023==bid);self.assertEqual((word>>15)&31,enum);self.assertEqual((word>>10)&31,20)


class PlayerIdentityAndNumberTests(unittest.TestCase):
 def project(self):
  p=app.default_project();p['native_card']={'native_style':'0501','native_agent':123,'source_id':'7511'}
  p['identity'].update(bind_original_player=True,original_player_id='7511')
  return p

 def test_bound_cards_share_original_person_and_keep_distinct_stable_card_ids(self):
  first=self.project();second=self.project();registry={};occupied={7511}
  a=reserve_identity(first,occupied,registry);b=reserve_identity(second,occupied|{a['card_id']},registry)
  self.assertEqual(a['card_id']&0xfffffff,7511);self.assertEqual(b['card_id']&0xfffffff,7511)
  self.assertNotEqual(a['card_id'],b['card_id']);self.assertFalse(owned_person_aliases(a))
  self.assertEqual(reserve_identity(second,occupied,registry)['card_id'],b['card_id'])
  self.assertEqual(reserve_identity(first,occupied,registry)['card_id'],a['card_id'])
  first['identity']['bind_original_player']=False
  unbound=reserve_identity(first,occupied,registry)
  self.assertEqual(unbound['person_id'],a['independent_person_id']);self.assertNotEqual(unbound['card_id']&0xfffffff,7511)
  self.assertTrue(owned_person_aliases(unbound))

 def test_absent_original_id_rejected(self):
  p=self.project();p['identity']['original_player_id']='999999'
  with self.assertRaisesRegex(ValueError,'数据库'):reserve_identity(p,{7511},{})

 def test_bound_players_keep_their_reserved_independent_identity(self):
  import hashlib
  p=self.project();p['identity']['bind_original_player']=False
  start=90000000+int(hashlib.sha256(p['package_id'].encode()).hexdigest()[:12],16)%9000000
  registry={str(uuid.uuid4()):{'person_id':7511,'independent_person_id':start,'card_ids':[]}}
  new=reserve_identity(p,{7511},registry)
  self.assertNotEqual(new['independent_person_id'],start)

 def test_bound_and_unbound_manifest_history_reseed_without_claiming_original(self):
  import personal_source
  p=self.project();registry={};assets={};current=reserve_identity(p,{7511},registry)
  def document(identity):
   return {'players':[{'identity':identity,'base_parameters':[0]*147}],
           'native_binding':{'routes':[{'cardId':identity['card_id'],'portraitKey':'8000001'}]}}
  old=document(current);owners=personal_source.seed(old,registry,assets)
  self.assertNotIn(7511,owners[p['package_id']]['aliases']);self.assertEqual(assets[p['package_id']],8000001)
  p['identity']['bind_original_player']=False
  unbound=reserve_identity(p,{7511},registry);owners=personal_source.seed(document(unbound),registry,assets)
  self.assertNotIn(7511,owners[p['package_id']]['aliases']);self.assertIn(current['card_id'],owners[p['package_id']]['aliases'])
  p['identity']['bind_original_player']=True
  rebound=reserve_identity(p,{7511},registry);personal_source.seed(document(rebound),registry,assets)
  self.assertEqual(rebound['person_id'],7511)

 def test_shirt_number_uses_assignment_and_does_not_keep_previous_player_default(self):
  row=struct.pack('<QQII',1,7511,5738,9|(8<<10)|(63<<16))
  by_player=assignments([MemoryArchive({NUMBER_TABLE:row})]);p={'uniform_number':0}
  restore_number(p,7511,5738,by_player);self.assertEqual(p['uniform_number'],10)
  self.assertIn('5738',p['_studio_number_source'])
  p={'uniform_number':0};restore_number(p,1234,1,by_player);self.assertIsNone(p['uniform_number'])

 def test_project_share_preserves_links_number_and_optional_original_binding(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);first=app.Store(root/'first');p=self.project();p.pop('native_card',None);p['identity']['name']='Shared player';p['identity']['number']=99
   config=dict(schema()['templates'][7],source_positions=[0],target_positions=[9,10])
   coach=first.coaches.save({'name':'Shared coach','nation_id':210,'team_id':103,'native_source_id':'17605071047055','linkups':[config,None]})['coach'];p['custom_coaches']=[coach]
   exported=first.export_project(p);second=app.Store(root/'second');imported=second.import_project(exported['path'])
   self.assertEqual(imported['identity']['number'],99);self.assertTrue(imported['identity']['bind_original_player'])
   self.assertEqual(imported['identity']['original_player_id'],'7511');self.assertEqual(imported['custom_coaches'][0]['linkups'],[config,None])
   self.assertEqual((imported['custom_coaches'][0]['nation_id'],imported['custom_coaches'][0]['team_id']),(210,103))


@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class NativeV17InstructionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:import unicorn
  except ImportError:raise unittest.SkipTest('requires isolated ARM64 test dependency')
  cls.unicorn=unicorn
  with zipfile.ZipFile(APK) as z:cls.engine=z.read('lib/arm64-v8a/libUE4.so')

 def test_cloned_link_effects_and_labels_execute_native_adapters(self):
  from unicorn import arm64_const as r
  routes=[{'id':256,'template_id':8},{'id':257,'template_id':18}]
  hooks=link_hooks(routes,io.BytesIO(self.engine),schema())
  for hook in hooks:
   vm=self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64,self.unicorn.UC_MODE_ARM)
   vm.mem_map(0x100000,0x10000);vm.mem_map(0x200000,0x10000)
   va=hook['address']&~4095;vm.mem_map(va,4096);vm.mem_write(va,self.engine[va-16384:va-16384+4096])
   vm.mem_map(0xcd4000,4096);vm.mem_write(0xcd4000,self.engine[0xcd4000:0xcd5000])
   body=bytearray.fromhex(hook['body_hex'])
   for at,target in hook['absolute_fixups']:struct.pack_into('<Q',body,at,target)
   vm.mem_write(0x100000,bytes(body));vm.reg_write(r.UC_ARM64_REG_SP,0x208000);vm.reg_write(r.UC_ARM64_REG_X30,0x300000)
   if hook['name'].endswith('effect'):
    for ident,expected in ((1,0),(8,3),(18,6),(256,3),(257,6),(511,7)):
     vm.reg_write(r.UC_ARM64_REG_X0,ident);vm.emu_start(0x100000,0x300000,count=200)
     self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0),expected)
   else:
    vm.mem_write(0x20802c,struct.pack('<I',256));vm.emu_start(0x100000,hook['address']+4,count=200)
    self.assertEqual(struct.unpack('<I',vm.mem_read(0x20802c,4))[0],8)
    self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X8),0xcd4000)

 def test_native_assignment_getter_and_native_person_key(self):
  from unicorn import arm64_const as r
  vm=self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64,self.unicorn.UC_MODE_ARM)
  for va in (0x8251000,0x81c0000):vm.mem_map(va,4096);vm.mem_write(va,self.engine[va-16384:va-16384+4096])
  vm.mem_map(0x100000,4096)
  for number in (1,10,99,999):
   row=struct.pack('<QQII',1,7511,5738,number-1|(73<<10))
   vm.mem_write(0x100000,row);vm.reg_write(r.UC_ARM64_REG_X0,0x100000);vm.reg_write(r.UC_ARM64_REG_X1,0);vm.reg_write(r.UC_ARM64_REG_X30,0x200000)
   vm.emu_start(0x8251910,0x200000,count=50);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0),number)
  for ident in (7511,(0x51<<40)|(4095<<28)|7511):
   vm.reg_write(r.UC_ARM64_REG_X0,ident);vm.reg_write(r.UC_ARM64_REG_X30,0x200000)
   vm.emu_start(0x81c084c,0x200000,count=20);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0),7511)

 def test_bound_card_compilation_preserves_original_player_art_and_equipment(self):
  from native_player import compile_player
  from native_tables import compile_tables,PLAYER,APPEARANCE,ALIASES,rows
  with zipfile.ZipFile(APK) as archive:original=archive.read('assets/gateway-release/custom-resources/legends-v10/dt870_mobile_and.cpk')
  source=Cpk(original);players=rows(unwrap(source.read(PLAYER)),400,8)
  with sqlite3.connect(RESOURCE/'library.sqlite3') as db:template=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
  p=app.default_project();p['identity'].update(name='Bound Messi',bind_original_player=True,original_player_id='7511',number=10)
  p['native_card']={'native_style':'0501','native_agent':123,'source_id':'7511'};p['booster_ids']=[0,0]
  identity=reserve_identity(p,set(players)|{i&0xfffffff for i in players},{})
  catalog=copy.deepcopy(app.CATALOG);costs=json.loads((RESOURCE/'native-progression.json').read_text())['costs']
  definition=compile_player(p,catalog,costs,identity,template,50,5738,players[7511])
  binding={'asset_key':'8000001','portrait_name':'8000001_','appearance_id':7511}
  result,report=compile_tables(original,[p],[definition],RESOURCE,[binding]);compiled=Cpk(result)
  result_players=rows(unwrap(compiled.read(PLAYER)),400,8)
  self.assertEqual(result_players[7511],players[7511]);self.assertIn(identity['card_id'],result_players)
  before=rows(unwrap(source.read(APPEARANCE)),64);after=rows(unwrap(compiled.read(APPEARANCE)),64)
  self.assertEqual(after[7511],before[7511]);self.assertNotIn('7511',report['native_person_aliases'][p['package_id']])


if __name__=='__main__':unittest.main()
