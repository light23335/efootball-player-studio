from pathlib import Path
import io,json,struct,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_settings import DEFAULTS,BUTTONS,normalize,preset,controller_hooks,settings
import copy

class GameSettingsTests(unittest.TestCase):
 def test_default_and_fc_are_valid_and_shared_bindings_reject_conflicts(self):
  for name in ('default','fc'):
   value=copy.deepcopy(DEFAULTS);value['controller'].update(preset=name,bindings=preset(name));self.assertEqual(normalize(value),value)
  value['controller']['bindings'][0]['input']=['B']
  with self.assertRaisesRegex(ValueError,'按键冲突'):normalize(value)
 def test_save_roundtrip_and_validation(self):
  with tempfile.TemporaryDirectory() as folder:
   store=type('Store',(),{'root':Path(folder)})();v=settings(store);v['frame_rate']={'enabled':True,'target':240};v['display']={'enabled':True,'height':2160};self.assertEqual(settings(store,v),settings(store))
   for target in (0,1000,True):
    bad=copy.deepcopy(v);bad['frame_rate']['target']=target
    with self.assertRaises(ValueError):settings(store,bad)
 def test_legacy_fc_preset_migrates_to_mobile_shoulder_layout(self):
  value=copy.deepcopy(DEFAULTS);value['controller'].update(preset='fc',bindings=preset('default'));value['controller'].pop('mapping_revision')
  self.assertEqual(normalize(value)['controller']['bindings'],preset('fc'))

class NativeControllerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:
   import unicorn
   from unicorn import arm64_const
  except ImportError:raise unittest.SkipTest('ARM64 emulator unavailable')
  cls.u=unicorn;cls.r=arm64_const;cls.root=Path(__file__).resolve().parents[1];cls.profile=json.loads((cls.root/'resources/native-controller.json').read_text())
 def machine(self,buttons=(),preset_name='fc',triggers=(0.,0.),node=0x300000,options=None):
  c=copy.deepcopy(DEFAULTS['controller']);c.update(enabled=True,preset=preset_name,bindings=preset(preset_name));c.update(options or {})
  p=self.profile;engine=io.BytesIO(bytes(p['hook']['file_offset']+64))
  for h in (p['hook'],p['key_hook']):engine.seek(h['file_offset']);engine.write(bytes.fromhex(h['expected_hex']))
  hook=controller_hooks(c,engine)[0]
  u=self.u;r=self.r;vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
  for base in (0x100000,0x200000,0x300000,hook['address']&~4095):vm.mem_map(base,0x10000 if base<0x1000000 else 4096)
  body=bytearray.fromhex(hook['body_hex'])
  for at,value in hook['absolute_fixups']:struct.pack_into('<Q',body,at,value)
  vm.mem_write(0x100000,bytes(body));vm.mem_write(node,bytes(96))
  for key in buttons:
   index=BUTTONS.index(key)
   vm.mem_write(node+p['digital_offsets'][index],b'\1')
  vm.mem_write(node+0x4c,struct.pack('<ff',*triggers));vm.mem_write(node+0x3c,struct.pack('<ffff',.2,-.4,.6,-.8))
  original=bytes(vm.mem_read(node,96));vm.reg_write(r.UC_ARM64_REG_SP,0x208000)
  for n in range(31):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),0x100+n)
  vm.reg_write(r.UC_ARM64_REG_X28,node);vm.reg_write(r.UC_ARM64_REG_X23,0x302000);vm.reg_write(r.UC_ARM64_REG_W8,0);vm.reg_write(r.UC_ARM64_REG_W27,160)
  for n in range(32):vm.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(n)),0xabc000+n)
  vm.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000);vm.emu_start(0x100000,hook['address']+16,count=4000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),hook['address']+16);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x208000);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV),0xa0000000)
  for n in (0,1,2,10,11,12,13,14,15,17,18,19,20,27):self.assertEqual(vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(n))),160 if n==27 else 0x100+n)
  for n in range(1,32):self.assertEqual(vm.reg_read(getattr(r,'UC_ARM64_REG_Q'+str(n))),0xabc000+n)
  raw=bytes(vm.mem_read(node,96));self.assertEqual(raw[:32],original[:32]);self.assertEqual(raw[0x3c:0x4c],original[0x3c:0x4c]) if not options else None
  result={BUTTONS[n] for n,off in enumerate(p['digital_offsets']) if raw[off]}
  return result,raw
 def test_fc_physical_single_buttons_and_press_release(self):
  for source,target in [('B','X'),('X','B'),('RB','LT'),('RT','RT'),('A','A'),('Y','Y'),('LB','LB'),('LT','RB'),('START','START'),('SELECT','SELECT')]:
   got,_=self.machine([source]);self.assertEqual(got,{target})
   self.assertEqual(self.machine([])[0],set())
 def test_fc_combos_suppress_single_actions_and_accept_trigger_axes(self):
  self.assertEqual(self.machine(['RB','B'])[0],{'RB','X'})
  self.assertEqual(self.machine(['LT','RT'])[0],{'RB','RT'})
  self.assertEqual(self.machine(['LB','B'])[0],{'LB','X'})
  self.assertEqual(self.machine([],triggers=(.8,.9))[0],{'RB','RT'})
  self.assertEqual(self.machine([],triggers=(0,.8))[0],{'RT'})
  self.assertEqual(self.machine(['RT','B'])[0],{'RT','X'})
 def test_sprint_trigger_pressure_survives_but_key_only_triggers_still_work(self):
  for amount in (.05,.15,.29,.31,.5,.8,1.):
   _,raw=self.machine([],triggers=(0,amount));self.assertAlmostEqual(struct.unpack_from('<f',raw,0x50)[0],amount,places=6)
  _,raw=self.machine(['RT']);self.assertEqual(struct.unpack_from('<f',raw,0x50)[0],1.)
  rows=preset('fc');next(r for r in rows if r['id']=='finesse')['input']=['RT','B']
  output,raw=self.machine(['B'],triggers=(0,.8),options={'bindings':rows})
  self.assertEqual(output,{'RB','X'});self.assertEqual(struct.unpack_from('<f',raw,0x50)[0],0.)
 def test_original_preset_identity_and_custom_unbound(self):
  for key in BUTTONS:self.assertEqual(self.machine([key],'default')[0],{key})
  rows=preset('fc');next(r for r in rows if r['id']=='X')['input']=[]
  self.assertEqual(self.machine(['B'],options={'bindings':rows})[0],set())
 def test_native_hook_rejects_changed_engine(self):
  c=copy.deepcopy(DEFAULTS['controller']);c['enabled']=True
  with self.assertRaises(ValueError):controller_hooks(c,io.BytesIO(b''))
 def test_key_only_direction_pads_record_and_release_without_changing_other_keys(self):
  hook=self.profile['key_hook'];body=bytearray.fromhex(hook['body_hex']);r=self.r;u=self.u
  for at,value in hook['absolute_fixups']:struct.pack_into('<Q',body,at,value)
  for key in (19,20,21,22,96,109,110):
   for action in (0,1):
    vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
    for base in (0x100000,0x200000,hook['address']&~4095):vm.mem_map(base,4096)
    vm.mem_write(0x100000,bytes(body));vm.mem_write(0x200000,bytes(96));vm.reg_write(r.UC_ARM64_REG_X20,0x200000);vm.reg_write(r.UC_ARM64_REG_W21,key);vm.reg_write(r.UC_ARM64_REG_W0,action)
    ends=(0x677290c,0x677278c)
    def stop(vm,pc,size,user):
     if pc in ends:vm.emu_stop()
    vm.hook_add(u.UC_HOOK_CODE,stop);vm.emu_start(0x100000,0x110000,count=100)
    if 19<=key<=22:
     self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),ends[0]);self.assertEqual(vm.mem_read(0x20002a+key-19,1)[0],int(action==0))
    else:self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),ends[1] if key<=109 else ends[0]);self.assertEqual(bytes(vm.mem_read(0x200000,96)),bytes(96))

if __name__=='__main__':unittest.main()
