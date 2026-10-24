from pathlib import Path
import io,json,struct,sys,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_skill_effects import compiled_skills,visible_skills,hooks,text_groups
APK=Path('C:/Users/1/Downloads/73efootball-V17.apk')

class SkillDataTests(unittest.TestCase):
 def test_height_profiles_are_applied_to_skill_ids_and_roundtrip(self):
  for height,variant in ((140,51),(175,51),(176,52),(185,52),(186,68),(220,68)):
   self.assertEqual(compiled_skills([25,52,43],height),[25,variant,43])
   self.assertEqual(visible_skills([25,variant,43]),[25,52,43])
 def test_native_text_keys_are_distinct_and_describe_the_visible_skills(self):
  groups=text_groups();self.assertTrue(groups)
  self.assertEqual({text for g in groups for text in g['items'].values()},{'重炮攻门','长传好手','健步如飞'})

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
  cls.hooks={h['name']:h for h in hooks(io.BytesIO(cls.engine))}
 def machine(self,name,flags=(),kind=8,power=.7,category=0,speed=10,coefficient=.5):
  u=self.uc;r=self.r;vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM);hook=self.hooks[name]
  for address in (0x100000,0x200000,0x300000,0x400000):vm.mem_map(address,0x10000)
  body=bytearray.fromhex(hook['body_hex']);pages=set()
  for at,target in hook['absolute_fixups']:
   struct.pack_into('<Q',body,at,target);pages.add(target&~4095)
  for page in pages:vm.mem_map(page,4096);vm.mem_write(page,bytes.fromhex('c0035fd6')*1024)
  vm.mem_write(0x100000,bytes(body));vm.reg_write(r.UC_ARM64_REG_SP,0x208000)
  for i in range(31):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),0x100+i)
  vm.reg_write(r.UC_ARM64_REG_X20,0x300000);vm.reg_write(r.UC_ARM64_REG_X21,0x400000);vm.reg_write(r.UC_ARM64_REG_X27,0x400000);vm.reg_write(r.UC_ARM64_REG_X26,category)
  vm.reg_write(r.UC_ARM64_REG_X30,0x500000)
  for i in range(32):vm.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(i)),0xabc000+i)
  def f(value):return struct.unpack('<I',struct.pack('<f',value))[0]
  vm.reg_write(r.UC_ARM64_REG_S8,f(coefficient));vm.reg_write(r.UC_ARM64_REG_S9,f(coefficient));vm.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000)
  vm.mem_write(0x300004,struct.pack('<I',kind));vm.mem_write(0x30000c,struct.pack('<f',power));vm.mem_write(0x400344,struct.pack('<f',speed));vm.mem_write(0x402a38,b'\x07')
  state={'flags':set(flags),'sets':[]}
  def callback(machine,pc,size,user):
   if pc==hook['address']+4:machine.emu_stop();return
   if pc==0x6dcd87c:machine.reg_write(r.UC_ARM64_REG_W0,int(machine.reg_read(r.UC_ARM64_REG_W1) in state['flags']))
   elif pc in (0x6d3d9cc,0x72c40b0,0x7301ef8):machine.reg_write(r.UC_ARM64_REG_X0,0x400000)
   elif pc==0x72b3a38:
    key=machine.reg_read(r.UC_ARM64_REG_W1);value=machine.reg_read(r.UC_ARM64_REG_W2);state['sets'].append((key,value))
    if value:state['flags'].add(key)
    else:state['flags'].discard(key)
   else:return
   # Native helpers may clobber caller-saved registers and SIMD values.
   for i in range(1,19):machine.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),0xdef000+i)
   for i in range(8):machine.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(i)),0xdef000+i)
   machine.reg_write(r.UC_ARM64_REG_PC,machine.reg_read(r.UC_ARM64_REG_X30))
  vm.hook_add(u.UC_HOOK_CODE,callback)
  vm.emu_start(0x100000,0x500000,count=3000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x208000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV),0xa0000000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X1),0x101)
  return vm,state
 def value(self,vm,register):return struct.unpack('<f',struct.pack('<I',vm.reg_read(register)))[0]
 def test_marker_tracks_power_or_volley_and_is_cleared_on_non_shots(self):
  name='studio_shot_marker_and_lofted_windup'
  for kind,power,category,expected in ((8,.5,0,1),(8,.49,0,0),(8,.2,5,1),(8,.2,6,1),(7,.9,5,0),(4,.9,0,0)):
   vm,state=self.machine(name,[74],kind,power,category);self.assertEqual(state['sets'],[(71,expected)])
  vm,state=self.machine(name,[],8,.9);self.assertFalse(state['sets'])
 def test_lofted_windup_changes_only_lofted_passes_with_the_skill(self):
  for flags,kind,expected in (([72],4,.5/.88),([72],5,.5/.88),([72],6,.5/.88),([72],7,.5),([72],8,.5),([],4,.5)):
   vm,state=self.machine('studio_shot_marker_and_lofted_windup',flags,kind)
   self.assertAlmostEqual(self.value(vm,self.r.UC_ARM64_REG_S8),expected,places=6)
 def test_acceleration_profiles_have_different_low_and_high_speed_curves(self):
  for flag,speed,expected in ((69,10,.62),(69,25,.53),(70,10,.56),(70,25,.56),(73,10,.53),(73,25,.62),(None,10,.5)):
   vm,state=self.machine('studio_height_acceleration',[] if flag is None else [flag],speed=speed)
   self.assertAlmostEqual(self.value(vm,self.r.UC_ARM64_REG_S9),expected,places=6)
  vm,_=self.machine('studio_height_acceleration',[69],coefficient=1.05)
  self.assertAlmostEqual(self.value(vm,self.r.UC_ARM64_REG_S9),1.1,places=6)

 def test_shot_error_wrappers_preserve_original_arguments_and_only_scale_eligible_shots(self):
  u=self.uc;r=self.r
  for address,frame in ((0x6d58f94,0xa0),(0x6d5a034,0x50)):
   for flags,expected in ((set(),.6),({74},.6),({71},.6),({71,74},.48)):
    hook=self.hooks['studio_heavy_shot_error_'+hex(address)]
    vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
    for page,size in ((0x100000,0x10000),(0x200000,0x10000),(address&~4095,4096),(0x6dcd000,4096)):
     vm.mem_map(page,size)
    body=bytearray.fromhex(hook['body_hex'])
    for at,target in hook['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    vm.mem_write(0x100000,bytes(body));vm.reg_write(r.UC_ARM64_REG_SP,0x208000);vm.reg_write(r.UC_ARM64_REG_X30,0x500000)
    for index in range(4):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(index)),0x700+index)
    vm.reg_write(r.UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',.9))[0]);vm.reg_write(r.UC_ARM64_REG_D8,0xabcdef)
    def callback(machine,pc,size,user):
     if pc==address+4:
      self.assertEqual([machine.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(4)],[0x700+i for i in range(4)])
      self.assertAlmostEqual(self.value(machine,r.UC_ARM64_REG_S0),.9,places=6)
      machine.reg_write(r.UC_ARM64_REG_SP,machine.reg_read(r.UC_ARM64_REG_SP)+frame)
      machine.reg_write(r.UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',.6))[0])
     elif pc==0x6dcd87c:machine.reg_write(r.UC_ARM64_REG_W0,int(machine.reg_read(r.UC_ARM64_REG_W1) in flags))
     else:return
     machine.reg_write(r.UC_ARM64_REG_PC,machine.reg_read(r.UC_ARM64_REG_X30))
    vm.hook_add(u.UC_HOOK_CODE,callback);vm.emu_start(0x100000,0x500000,count=300)
    self.assertAlmostEqual(self.value(vm,r.UC_ARM64_REG_S0),expected,places=6)
    self.assertEqual(vm.reg_read(r.UC_ARM64_REG_D8),0xabcdef);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x208000)

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
