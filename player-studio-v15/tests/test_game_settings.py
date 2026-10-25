from pathlib import Path
import io,json,struct,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_settings import DEFAULTS,BUTTONS,normalize,preset,legacy_preset,controller_hooks,settings,schema
import copy

class GameSettingsTests(unittest.TestCase):
 def test_default_and_fc_are_valid_and_conflicts_are_per_context(self):
  for name in ('default','fc'):
   value=copy.deepcopy(DEFAULTS);value['controller'].update(preset=name,bindings=preset(name));self.assertEqual(normalize(value),value)
  value['controller']['bindings'][0]['input']=['X']
  with self.assertRaisesRegex(ValueError,'按键冲突'):normalize(value)
 def test_fc_reuses_rb_without_coupling_tight_dribble_and_pressure(self):
  rows={r['id']:r['input'] for r in preset('fc')}
  self.assertEqual(rows['attack.LT'],['RB']);self.assertEqual(rows['defense.RB'],['RB'])
  self.assertEqual(rows['defense.LT'],['LT']);self.assertEqual(rows['attack.finesse'],['RB','B'])
  self.assertEqual([s['id'] for s in schema()['scopes']],['attack','defense','common'])
 def test_common_commands_conflict_with_both_contexts(self):
  for source in ('B','RB','LT'):
   v=copy.deepcopy(DEFAULTS);next(r for r in v['controller']['bindings'] if r['id']=='common.START')['input']=[source]
   with self.assertRaisesRegex(ValueError,'按键冲突'):normalize(v)
 def test_save_roundtrip_and_validation(self):
  with tempfile.TemporaryDirectory() as folder:
   store=type('Store',(),{'root':Path(folder)})();v=settings(store);v['frame_rate']={'enabled':True,'target':240};v['display']={'enabled':True,'height':2160};self.assertEqual(settings(store,v),settings(store))
   for target in (0,1000,True):
    bad=copy.deepcopy(v);bad['frame_rate']['target']=target
    with self.assertRaises(ValueError):settings(store,bad)
 def test_legacy_fc_preset_migrates_to_mobile_shoulder_layout(self):
  value=copy.deepcopy(DEFAULTS);value['controller'].update(preset='fc',bindings=legacy_preset('default'));value['controller'].pop('mapping_revision')
  self.assertEqual(normalize(value)['controller']['bindings'],preset('fc'))
 def test_legacy_custom_bindings_migrate_without_reset(self):
  v=copy.deepcopy(DEFAULTS);c=v['controller'];c.update(preset='custom',mapping_revision=2,bindings=legacy_preset())
  c['bindings'][0]['input']=['RS'];c['bindings'][9]['input']=['A']
  c['bindings'][-1]['input']=[]
  migrated=normalize(v)['controller'];rows={r['id']:r for r in migrated['bindings']}
  self.assertEqual(migrated['mapping_revision'],3)
  self.assertEqual(rows['attack.A']['input'],['RS']);self.assertEqual(rows['defense.A']['input'],['RS'])
  self.assertEqual(rows['common.RS']['input'],['A']);self.assertEqual(rows['attack.chip']['input'],[])
  self.assertEqual(normalize({'controller':migrated})['controller'],migrated)

class NativeControllerTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  try:
   import unicorn
   from unicorn import arm64_const
  except ImportError:raise unittest.SkipTest('ARM64 emulator unavailable')
  cls.u=unicorn;cls.r=arm64_const;cls.root=Path(__file__).resolve().parents[1];cls.profile=json.loads((cls.root/'resources/native-controller.json').read_text())
 def machine(self,buttons=(),preset_name='fc',triggers=(0.,0.),node=0x300000,options=None,mode=1,port=0,user=0,valid=True,missing=None,relocation=0):
  c=copy.deepcopy(DEFAULTS['controller']);c.update(enabled=True,preset=preset_name,bindings=preset(preset_name));c.update(options or {})
  p=self.profile
  class Engine:
   def seek(self,at):self.at=at
   def read(self,size):return bytes.fromhex(next(h['expected_hex'] for h in [p['hook'],p['key_hook'],*p['context_probes']] if h['file_offset']==self.at))[:size]
  engine=Engine()
  hook=controller_hooks(c,engine)[0]
  u=self.u;r=self.r;vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
  for base in (0x100000,0x200000,0x300000,(hook['address']+relocation)&~4095,(0xa58de28+relocation)&~4095):vm.mem_map(base,0x10000 if base<0x1000000 else 4096)
  vm.mem_map(0x400000,0x100000)
  body=bytearray.fromhex(hook['body_hex'])
  for at,value in hook['absolute_fixups']:struct.pack_into('<Q',body,at,value+relocation)
  def q(at,n):vm.mem_write(at,struct.pack('<Q',n))
  def w(at,n):vm.mem_write(at,struct.pack('<I',n))
  q(0xa58de28+relocation,0 if missing=='world' else 0x400000)
  q(0x400340,0 if missing=='users' else 0x460000);w(0x400054,3 if missing=='handler_type' else 0)
  q(0x400070,0 if missing=='handler' else 0x410000);q(0x410180,0 if missing=='commands' else 0x420000)
  for i in range(24):w(0x460008+i*0xd0,255)
  w(0x460004+user*0xd0,16 if valid else 0);w(0x460008+user*0xd0,port if missing!='port' else 255)
  w(0x420000+0x2b4ec+user*0x2c,mode)
  vm.mem_write(0x100000,bytes(body));vm.mem_write(node,bytes(96))
  for key in buttons:
   index=BUTTONS.index(key)
   vm.mem_write(node+p['digital_offsets'][index],b'\1')
  vm.mem_write(node+0x4c,struct.pack('<ff',*triggers));vm.mem_write(node+0x3c,struct.pack('<ffff',.2,-.4,.6,-.8))
  original=bytes(vm.mem_read(node,96));vm.reg_write(r.UC_ARM64_REG_SP,0x208000)
  for n in range(31):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),0x100+n)
  vm.reg_write(r.UC_ARM64_REG_X28,node);vm.reg_write(r.UC_ARM64_REG_X23,0x302000);vm.reg_write(r.UC_ARM64_REG_W8,port);vm.reg_write(r.UC_ARM64_REG_W27,160)
  for n in range(32):vm.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(n)),0xabc000+n)
  vm.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000);vm.emu_start(0x100000,hook['address']+16+relocation,count=4000)
  self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),hook['address']+16+relocation);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x208000);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV),0xa0000000)
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
  rows=preset('fc');next(r for r in rows if r['id']=='attack.finesse')['input']=['RT','B']
  output,raw=self.machine(['B'],triggers=(0,.8),options={'bindings':rows})
  self.assertEqual(output,{'RB','X'});self.assertEqual(struct.unpack_from('<f',raw,0x50)[0],0.)
 def test_original_preset_identity_and_custom_unbound(self):
  for key in BUTTONS:self.assertEqual(self.machine([key],'default')[0],{key})
  rows=preset('fc');next(r for r in rows if r['id']=='attack.X')['input']=[]
  self.assertEqual(self.machine(['B'],options={'bindings':rows})[0],set())
 def test_native_modes_select_context_for_each_port_and_user(self):
  for mode in range(15):
   expected={'LT'} if mode in (1,2,3,4,6) else {'RB'}
   self.assertEqual(self.machine(['RB'],mode=mode)[0],expected)
   expected={'RB'} if mode in (1,2,3,4,6) else {'LT'}
   self.assertEqual(self.machine(['LT'],mode=mode)[0],expected)
  for port,user in ((1,0),(2,9),(3,23)):
   self.assertEqual(self.machine(['RB'],mode=2,port=port,user=user)[0],{'LT'})
   self.assertEqual(self.machine(['RB'],mode=5,port=port,user=user)[0],{'RB'})
  self.assertEqual(self.machine(['RB'],mode=1,relocation=0x10000000)[0],{'LT'})
 def test_missing_or_non_match_state_retains_stock_controls(self):
  for missing in ('world','users','handler_type','handler','commands','port'):
   self.assertEqual(self.machine(['RB','B'],missing=missing)[0],{'RB','B'})
  self.assertEqual(self.machine(['RB'],valid=False)[0],{'RB'})
  self.assertEqual(self.machine(['B'],mode=0xffffffff)[0],{'B'})
 def test_defence_mapping_is_independent_including_combinations(self):
  self.assertEqual(self.machine(['RB','B'],mode=5)[0],{'RB','B'})
  rows=preset('fc');next(r for r in rows if r['id']=='defense.RB')['input']=['A','RB']
  self.assertEqual(self.machine(['RB'],mode=5,options={'bindings':rows})[0],set())
  self.assertEqual(self.machine(['RB','A'],mode=5,options={'bindings':rows})[0],{'RB'})
  self.assertEqual(self.machine(['RB','B'],mode=1,options={'bindings':rows})[0],{'RB','X'})
 def test_stunning_shortcuts_preserve_trigger_pressure_and_do_not_force_full_power(self):
  for mode in (1,2,3,4,6):
   for amount in (.31,.6,1.):
    got,raw=self.machine(['B'],triggers=(0,amount),mode=mode)
    self.assertEqual(got,{'RT','X'});self.assertAlmostEqual(struct.unpack_from('<f',raw,0x50)[0],amount,places=6)
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
