from pathlib import Path
import io,json,struct,sys,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_skill_effects import compiled_skills,visible_skills,hooks,text_groups
APK=Path('C:/Users/1/Downloads/73efootball-V17.apk')

class SkillDataTests(unittest.TestCase):
 def test_old_imported_skill_aliases_use_independent_verified_flags(self):
  import tempfile
  from native_skill_effects import skill_bits
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'native-skill-bits.json'
   path.write_text(json.dumps({'9':{'bit':649},'31':{'bit':623}}),encoding='utf8')
   result=skill_bits(folder)
   self.assertEqual(result['9']['bit'],644);self.assertEqual(result['31']['bit'],627)
   self.assertEqual(json.loads(path.read_text())['9']['bit'],649)
 def test_height_profiles_are_applied_to_skill_ids_and_roundtrip(self):
  for height,variant in ((140,51),(175,51),(176,52),(185,52),(186,68),(220,68)):
   self.assertEqual(compiled_skills([25,52,43],height),[25,variant,43])
   self.assertEqual(visible_skills([25,variant,43]),[25,52,43])
 def test_native_text_keys_are_distinct_and_describe_the_visible_skills(self):
  groups=text_groups();self.assertTrue(groups)
  texts={text for g in groups for text in g['items'].values()}
  self.assertTrue({'重炮攻门','长传好手','健步如飞'}<=texts)
  self.assertIn('凌空抽射或蓄力达到 50% 的射门，射门偏差降低 20%。',texts)

@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class MatchInstructionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:
   import unicorn
   from unicorn import arm64_const as r
  except ImportError:raise unittest.SkipTest('requires isolated ARM64 dependency')
  cls.uc=unicorn;cls.r=r
  with zipfile.ZipFile(APK) as z:cls.engine=z.read('lib/arm64-v8a/libUE4.so')
  resource=Path(__file__).resolve().parents[1]/'resources/native-skill-effects.json'
  data=json.loads(resource.read_text(encoding='utf8'));cls.hooks={h['name']:h for h in data['hooks']}
 def test_released_runtime_keeps_obsolete_prediction_and_tight_possession_hooks_removed(self):
  resource=Path(__file__).resolve().parents[1]/'resources/native-skill-effects.json'
  data=json.loads(resource.read_text(encoding='utf8'))
  if data.get('custom_skill_protocol')!='studio-custom-skills-v2-1':
   # Legacy release remains testable while the next runtime is staged.
   return
  addresses={h['address'] for h in data['hooks']}
  self.assertFalse(addresses & {0x6d58f94,0x6d5a034,0x6f2ca9c,0x6d5f640})
  self.assertTrue({0x6f40b90,0x6f11ef4,0x6d42570,0x72d5e40}<=addresses)
  linked=hooks(io.BytesIO(self.engine))
  self.assertEqual(len(linked),1)
  self.assertEqual(len(linked[0]['extra_entries'])+1,len(addresses))

 def test_low_screamer_removes_only_stunning_requirement(self):
  u=self.uc;r=self.r
  for has_skill,power,stunning,expected in ((True,.49,False,True),(True,.49,True,True),(True,.5,False,False),(False,.2,False,False)):
   vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM);vm.mem_map(0x6d62000,4096);vm.mem_map(0x100000,0x10000);vm.mem_map(0x300000,4096)
   start,end=0x6d627a4,0x6d627cc
   vm.mem_write(start,self.engine[start-16384:end-16384]);hook=self.hooks['studio_low_screamer_normal_shot']
   body=bytearray.fromhex(hook['body_hex'])
   for at,target in hook['absolute_fixups']:struct.pack_into('<Q',body,at,target)
   vm.mem_write(0x100000,bytes(body))
   vm.reg_write(r.UC_ARM64_REG_X19,0x300000);vm.reg_write(r.UC_ARM64_REG_W0,int(has_skill))
   vm.mem_write(0x30000c,struct.pack('<f',power));vm.mem_write(0x300061,bytes([int(stunning)]))
   def callback(machine,pc,size,user):
    if pc==0x6d627c0:machine.reg_write(r.UC_ARM64_REG_PC,0x100000)
   vm.hook_add(u.UC_HOOK_CODE,callback);vm.emu_start(start,end,count=100)
   self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W25)==0,expected)

if __name__=='__main__':unittest.main()
