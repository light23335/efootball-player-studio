from pathlib import Path
import copy,io,json,struct,sys,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from ai_playing_styles import FIELDS
from native_coach_links import schema,decode,encode,repair_legacy
from native_skill_effects import text_groups

APK=Path('C:/Users/1/Downloads/73efootball-V17.apk')
class SavedCustomPlayerTests(unittest.TestCase):
 def test_authored_custom_player_is_not_treated_as_an_empty_slot(self):
  p=app.default_project();p['identity']['name']='Adam Lallana';p['identity']['shirt_name']='Adam Lallana';p['status']='new-player-slot';p['model']['asset']='a'*64+'.glb'
  before=copy.deepcopy(p);after=app.normalize_project(p)
  self.assertEqual(after['status'],'draft');self.assertTrue(after['editor_ready'])
  for key in ('package_id','identity','model','appearance','base_abilities','training','booster_ids'):self.assertEqual(after[key],before[key])
  empty=app.default_project();empty['identity']['name']='新建球员 1';empty['status']='new-player-slot';empty=app.normalize_project(empty)
  self.assertEqual(empty['status'],'new-player-slot');self.assertFalse(empty.get('editor_ready'))

 def test_native_coach_styles_and_delta_names_match_the_reported_game_conditions(self):
  info=schema();press=info['templates'][17];passing=info['templates'][10]
  self.assertEqual((press['source_positions'],press['source_style'],press['target_positions'],press['target_style']),([5],9,[5],9))
  self.assertEqual(info['style_labels_en']['9'],'The Destroyer');self.assertEqual(info['style_labels_en']['14'],'Creative Playmaker')
  self.assertEqual((passing['source_positions'],passing['source_style'],passing['target_positions'],passing['target_style']),([9,10],14,[12],1))
  self.assertEqual(info['template_labels']['18'],'双人逼抢A');self.assertEqual(info['template_labels']['11'],'突破传球D')
  document={'coach_options_revision':'native-boosters-2-and-links-2-v1','linkup_types':[{'template_id':18,'label':'old'}],'coaches':[]}
  self.assertEqual(repair_legacy(document)['linkup_types'][0]['label'],'双人逼抢A')

@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class NativeUiProtocolTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:
   import unicorn
   from unicorn import arm64_const as r
  except ImportError:raise unittest.SkipTest('requires isolated ARM64 dependency')
  cls.u=unicorn;cls.r=r
  with zipfile.ZipFile(APK) as z:cls.engine=z.read('lib/arm64-v8a/libUE4.so')
  cls.vm=unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM)
  for page in range(0x8230000,0x82c0000,4096):cls.vm.mem_map(page,4096);cls.vm.mem_write(page,cls.engine[page-16384:page-16384+4096])
  for page in range(0xcd4000,0xcd9000,4096):cls.vm.mem_map(page,4096);cls.vm.mem_write(page,cls.engine[page:page+4096])
  cls.vm.mem_map(0x100000,0x10000);cls.vm.mem_map(0x300000,0x10000);cls.vm.mem_map(0x400000,4096)
  cls.vm.reg_write(r.UC_ARM64_REG_TPIDR_EL0,0x400000)
 def call(self,address,*args):
  vm=self.vm;r=self.r
  for i,value in enumerate(args):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
  vm.reg_write(r.UC_ARM64_REG_X30,0x200000);vm.reg_write(r.UC_ARM64_REG_SP,0x30fff0);vm.emu_start(address,0x200000,count=30000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),0x200000);return vm.reg_read(r.UC_ARM64_REG_X0)
 def test_each_ai_checkbox_reaches_the_exact_native_parameter_and_message(self):
  labels=json.loads((app.RESOURCE/'native-ai-style-labels.json').read_text(encoding='utf8'))['rows']
  for selected,field in FIELDS.items():
   self.vm.mem_write(0x100000,bytes(512));self.vm.mem_write(0x101000,(1<<field['bit']).to_bytes(400,'little'))
   self.call(0x82aa124,0x100000,0x101000,0)
   for key,f in FIELDS.items():
    self.call(0x82a84d4,0x100000,f['parameter'],0x102000)
    self.assertEqual(struct.unpack('<I',self.vm.mem_read(0x102000,4))[0],int(key==selected))
   self.vm.mem_write(0x103000,struct.pack('<I',field['parameter']));message=self.call(0x82bb60c,0x103000)
   proof=next(row for row in labels if row['key']==selected)
   self.assertEqual(message,proof['message']);self.assertEqual(field['label'],proof['label']);self.assertEqual(field['english'],proof['english'])
 def test_game_skill_name_getter_and_description_table_resolve_patched_text(self):
  metadata=json.loads((app.RESOURCE/'native-skill-ui.json').read_text(encoding='utf8'))['rows']
  for locale,names in (('zha',{25:'重炮攻门',43:'长传好手',51:'健步如飞',52:'健步如飞',68:'健步如飞'}),('eng',{25:'Power Strike',43:'Lofted Pass Specialist',51:'Quick Stride',52:'Quick Stride',68:'Quick Stride'})):
   texts={(g['id']<<16)|k:v for g in text_groups(locale=locale) for k,v in g['items'].items()}
   for row in metadata:
    self.assertEqual(struct.unpack_from('<III',self.engine,row['address']), (row['id'],row['name_msg'],row['description_msg']))
    self.vm.mem_write(0x103000,struct.pack('<I',row['id']));message=self.call(0x82bb658,0x103000)
    self.assertEqual(message,row['name_msg'])
    if row['id']!=24:self.assertEqual(texts[message],names[row['id']])
    self.assertTrue(texts[row['description_msg']]);self.assertNotEqual(texts[row['description_msg']].lower(),'dummy')

 def test_four_coach_slots_use_the_native_ten_bit_layout(self):
  from native_coaches import ability_ids,ABILITY_BITS,bitfield
  value=int.from_bytes(bytes([0xa5])*176,'little')
  for bit,ident in zip(ABILITY_BITS,(511,512,1023,11)):value=bitfield(value,bit,10,ident)
  raw=value.to_bytes(176,'little');self.vm.mem_write(0x100000,raw)
  getters=(0x8236464,0x823648c,0x82364b4,0x82364dc)
  self.assertEqual([self.call(g,0x100000,0) for g in getters],[511,512,1023,11])
  self.assertEqual(ability_ids(raw),[511,512,1023,11])
  document=json.loads((app.RESOURCE/'coaches.json').read_text(encoding='utf8'))
  coach=next(c for c in document['coaches'] if c['id']=='17609902885263')
  self.assertEqual(coach['ability_ids'],[11,20,18,11]);self.assertEqual([v['template_id'] for v in coach['linkups']],[18,11])

if __name__=='__main__':unittest.main()
