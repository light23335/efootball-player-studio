from pathlib import Path
import io,json,struct,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from game_settings import DEFAULTS,BUTTONS,normalize,preset,legacy_preset,controller_hooks,settings,schema,ai_decision_options
import copy

class GameSettingsTests(unittest.TestCase):
 def test_diy_pool_preference_is_boolean_and_defaults_to_previous_behaviour(self):
  self.assertTrue(normalize({})['ai_division_squads']['include_diy'])
  self.assertFalse(normalize({'ai_division_squads':{'include_diy':False}})['ai_division_squads']['include_diy'])
  for bad in (0,1,'false',None):
   with self.assertRaises(ValueError):normalize({'ai_division_squads':{'include_diy':bad}})
 def test_ai_master_off_also_disables_lone_wolf_without_erasing_player_style(self):
  player={'ai_playing_styles':['lone_wolf','cut_in']};before=copy.deepcopy(player)
  for selected in ([],[player]):
   for enabled in (False,True):
    result=ai_decision_options({'ai_cut_in_shots':{'enabled':enabled}},selected)
    self.assertEqual(result['ordinary_enabled'],enabled)
    self.assertEqual(result['lone_wolf_enabled'],enabled and bool(selected))
    self.assertEqual(result['lone_wolf_configured'],bool(selected))
  self.assertEqual(player,before)
 def test_division_opponents_can_be_disabled_independently_without_losing_preferences(self):
  old=normalize({'frame_rate':{'enabled':True,'target':240}})
  self.assertTrue(old['ai_division_squads']['enabled'])
  old['ai_division_squads']['enabled']=False
  saved=normalize(old)
  self.assertFalse(saved['ai_division_squads']['enabled']);self.assertTrue(saved['ai_cut_in_shots']['enabled'])
  self.assertEqual(saved['frame_rate'],{'enabled':True,'target':240})
  with tempfile.TemporaryDirectory() as folder:
   store=type('Store',(),{'root':Path(folder)})()
   self.assertEqual(settings(store,saved),settings(store))
  for bad in (0,1,'false',None):
   with self.assertRaises(ValueError):normalize({'ai_division_squads':{'enabled':bad}})
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
 def test_defensive_cancel_removed_and_old_custom_bindings_preserved(self):
  for name in ('default','fc'):
   ids={r['id'] for r in preset(name)}
   self.assertIn('attack.cancel',ids);self.assertNotIn('defense.cancel',ids)
  v=copy.deepcopy(DEFAULTS);c=v['controller'];c.update(enabled=True,preset='custom',bindings=preset('fc'))
  for row in c['bindings']:
   if row['id']=='defense.B':row['input']=['X']
   elif row['id']=='defense.X':row['input']=['B']
  expected=copy.deepcopy(c['bindings'])
  c['bindings'].append({'id':'defense.cancel','scope':'defense','label':'超级取消','input':['LT','RT'],'output':['RB','RT']})
  got=normalize(v)['controller'];self.assertEqual(got['bindings'],expected);self.assertEqual(got['preset'],'custom')
  self.assertEqual(normalize({'controller':got})['controller'],got)
  c['bindings'].append(copy.deepcopy(c['bindings'][-1]))
  with self.assertRaisesRegex(ValueError,'动作重复'):normalize(v)
 def test_save_roundtrip_and_validation(self):
  with tempfile.TemporaryDirectory() as folder:
   store=type('Store',(),{'root':Path(folder)})();v=settings(store);v['frame_rate']={'enabled':True,'target':240};v['display']={'enabled':True,'height':2160};self.assertEqual(settings(store,v),settings(store))
   for target in (0,1000,True):
    bad=copy.deepcopy(v);bad['frame_rate']['target']=target
    with self.assertRaises(ValueError):settings(store,bad)
 def test_independent_combo_metadata_survives_save_and_legacy_custom_detection(self):
  v=copy.deepcopy(DEFAULTS);c=v['controller'];c.update(preset='custom',bindings=preset('fc'))
  next(r for r in c['bindings'] if r['id']=='attack.finesse')['input']=['LS','B']
  del c['manual_shortcuts']
  got=normalize(v);self.assertIn('attack.finesse',got['controller']['manual_shortcuts'])
  self.assertEqual(normalize(got),got)
  got['controller']['manual_shortcuts']=['attack.X']
  with self.assertRaisesRegex(ValueError,'独立组合键'):normalize(got)
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
 def machine(self,buttons=(),preset_name='fc',triggers=(0.,0.),node=0x300000,options=None,mode=1,port=0,user=0,valid=True,missing=None,relocation=0,reset=None):
  c=copy.deepcopy(DEFAULTS['controller']);c.update(enabled=True,preset=preset_name,bindings=preset(preset_name));c.update(options or {})
  p=self.profile
  class Engine:
   def seek(self,at):self.at=at
   def read(self,size):return bytes.fromhex(next(h['expected_hex'] for h in [p['hook'],p['key_hook'],*p['context_probes']] if h['file_offset']==self.at))[:size]
  engine=Engine()
  hook=controller_hooks(c,engine)[0]
  u=self.u;r=self.r;vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
  for base in (0x100000,0x200000,0x300000,(hook['address']+relocation)&~4095,(0xa58de28+relocation)&~4095):vm.mem_map(base,0x10000 if base<0x1000000 else 4096)
  for entry in hook['extra_entries']:vm.mem_map((entry['address']+relocation)&~4095,4096)
  vm.mem_map(0x400000,0x100000)
  body=bytearray.fromhex(hook['body_hex'])
  for at,value in hook['absolute_fixups']:struct.pack_into('<Q',body,at,value+relocation)
  for at,size in hook['writable_fixups']:struct.pack_into('<Q',body,at,0x4f0000)
  def q(at,n):vm.mem_write(at,struct.pack('<Q',n))
  def w(at,n):vm.mem_write(at,struct.pack('<I',n))
  q(0xa58de28+relocation,0 if missing=='world' else 0x400000)
  q(0x400340,0 if missing=='users' else 0x460000);w(0x400054,3 if missing=='handler_type' else 0)
  # Reproduce the real MuMu crash: this scene field contains two floats, not
  # a command-manager pointer. The input hook must never dereference it.
  q(0x400070,0 if missing=='handler' else 0x410000);q(0x410180,0x3ec2d7c53e269b6b)
  for i in range(24):w(0x460008+i*0xd0,255)
  w(0x460004+user*0xd0,16 if valid else 0);w(0x460008+user*0xd0,port if missing!='port' else 255)
  w(0x420000+0x2b4ec+user*0x2c,mode)
  vm.mem_write(0x100000,bytes(body));vm.mem_protect(0x100000,0x10000,u.UC_PROT_READ|u.UC_PROT_EXEC);vm.mem_write(node,bytes(96))
  if not missing:
   entry=next(e for e in hook['extra_entries'] if e['name']=='studio_controller_mode_mode')
   vm.reg_write(r.UC_ARM64_REG_SP,0x208000);vm.reg_write(r.UC_ARM64_REG_X20,0x460000+user*0xd0);vm.reg_write(r.UC_ARM64_REG_X19,0x420000+0x2b4ec+user*0x2c)
   vm.reg_write(r.UC_ARM64_REG_W0,2)
   vm.emu_start(0x100000+entry['entry_offset'],entry['address']+16+relocation,count=1000)
   self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W8),2)
   self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV),0x20000000)
  if reset:
   entry=next(e for e in hook['extra_entries'] if e['name']=='studio_controller_mode_'+reset)
   vm.reg_write(r.UC_ARM64_REG_SP,0x208000)
   vm.emu_start(0x100000+entry['entry_offset'],entry['address']+16+relocation,count=1000)
   self.assertEqual(bytes(vm.mem_read(0x4f0000,64)),bytes(64))
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
 def test_unlisted_two_tap_and_fake_sequences_preserve_native_button_edges(self):
  # Long pass is X in FC. Nothing in the shortcut table names these gestures:
  # the game must receive B down/up/down, and B then B+A, with the same frames.
  physical=[[],['X'],[],['X'],[],['X'],['X','A'],['A'],[]]
  native=[set(),{'B'},set(),{'B'},set(),{'B'},{'B','A'},{'A'},set()]
  self.assertEqual([self.machine(keys)[0] for keys in physical],native)
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
  self.assertEqual(self.machine(['B'],mode=0xffffffff)[0],{'B'})
 def test_command_lifetime_clears_cached_banks_before_menus(self):
  for reset in ('create','destroy'):
   self.assertEqual(self.machine(['B'],mode=1,reset=reset)[0],{'B'})
 def test_native_port_lookup_does_not_require_unrelated_user_flag(self):
  # Execute the original APK's lookup, including its stride/port helpers.
  # It must select the same record with flags either cleared or set.
  p=self.profile;u=self.u;r=self.r
  for flags in (0,16):
   vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
   for base,size in ((0x698f000,4096),(0x460000,0x2000),(0x500000,4096),(0x200000,4096)):vm.mem_map(base,size)
   for probe in p['context_probes']:
    if probe['name'] in ('user_lookup','user_stride','user_port'):vm.mem_write(probe['address'],bytes.fromhex(probe['expected_hex']))
   for i in range(24):vm.mem_write(0x460008+i*0xd0,struct.pack('<I',255))
   vm.mem_write(0x460004+9*0xd0,struct.pack('<II',flags,2))
   vm.reg_write(r.UC_ARM64_REG_X0,0x460000);vm.reg_write(r.UC_ARM64_REG_W1,2)
   vm.reg_write(r.UC_ARM64_REG_X30,0x500000);vm.reg_write(r.UC_ARM64_REG_SP,0x200ff0)
   vm.emu_start(0x698f7f8,0x500000,count=1000)
   self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0),9)
   self.assertEqual(self.machine(['B'],mode=1,port=2,user=9,valid=bool(flags))[0],{'X'})
 def test_fc_with_only_defensive_b_x_swapped_retains_attack_mapping(self):
  rows=preset('fc')
  for row in rows:
   if row['id']=='defense.B':row['input']=['X']
   elif row['id']=='defense.X':row['input']=['B']
  for mode in (1,2,3,4,5,6,7,8):
   for flags in (False,True):
    self.assertEqual(self.machine(['B'],mode=mode,valid=flags,options={'bindings':rows,'preset':'custom'})[0],{'X'})
    self.assertEqual(self.machine(['X'],mode=mode,valid=flags,options={'bindings':rows,'preset':'custom'})[0],{'B'})
  self.assertEqual(self.machine(['B'],mode=0,valid=False,options={'bindings':rows,'preset':'custom'})[0],{'B'})
 def test_defence_mapping_is_independent_including_combinations(self):
  self.assertEqual(self.machine(['RB','B'],mode=5)[0],{'RB','B'})
  rows=preset('fc');next(r for r in rows if r['id']=='defense.RB')['input']=['A','RB']
  self.assertEqual(self.machine(['RB'],mode=5,options={'bindings':rows})[0],set())
  self.assertEqual(self.machine(['RB','A'],mode=5,options={'bindings':rows})[0],{'RB'})
  self.assertEqual(self.machine(['RB','B'],mode=1,options={'bindings':rows})[0],{'RB','X'})
 def test_defence_matchup_and_sprint_stay_independent_with_legacy_cancel(self):
  rows=preset('fc')+[{'id':'defense.cancel','scope':'defense','input':['LT','RT'],'output':['RB','RT']}]
  for mode in (5,7,8):
   self.assertEqual(self.machine(['LT','RT'],mode=mode,options={'bindings':rows})[0],{'LT','RT'})
   got,raw=self.machine([],mode=mode,triggers=(.8,.9),options={'bindings':rows})
   self.assertEqual(got,{'LT','RT'})
   self.assertAlmostEqual(struct.unpack_from('<f',raw,0x4c)[0],.8,places=6)
   self.assertAlmostEqual(struct.unpack_from('<f',raw,0x50)[0],.9,places=6)
  self.assertEqual(self.machine(['LT','RT'],mode=1,options={'bindings':rows})[0],{'RB','RT'})
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
