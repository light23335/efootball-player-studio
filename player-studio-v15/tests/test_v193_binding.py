from pathlib import Path
import copy,dis,json,marshal,re,struct,sys,types,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apk_literals import module_reader,literal_assignments
from native_binding_source import read_installer,verify_installer
from native_diy_binding import literal_routes,code_fingerprint
from personal_binding import capture,fingerprint,prepare,compose,relocate_code


class V193BindingTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.root=Path(__file__).resolve().parents[2];cls.apk=getattr(cls,'original_apk',cls.root.parent/'73efootball安装包及资源/73efootball-V16(1).apk')
  if not cls.apk.is_file():raise unittest.SkipTest('requires original V16 APK')
  cls.reader=staticmethod(module_reader(cls.apk));cls.payload,cls.installer=read_installer(cls.apk)
  res=cls.root/'player-studio-v15/resources';cls.profile=json.loads((res/'native-route-templates.json').read_text());cls.profile.update(external_routes=True,club_emblems=True)
  for name in ('position','acquisition','overall','thumbnail'):cls.profile[name+'_hook']=json.loads((res/('native-'+name+'-hook.json')).read_text())
  cls.route={'cardId':990001,'suiteDonorId':990001,'portraitKey':'8900001','modelFaceKey':'8900001','club_id':108,'position':1,'maximum_overall':99,'presentation_rarity':10}
  cls.binding={'original_fingerprint':fingerprint(cls.payload),'routes':[cls.route],'profile':cls.profile,'source':cls.installer.proof}

 def actual_loader(self,allocator=None):
  """Run only the inspected pure composition functions, never APK modules."""
  def function(module,name,namespace):
   def find(code):
    direct=next((c for c in code.co_consts if isinstance(c,types.CodeType) and c.co_name==name),None)
    if direct:return direct
    for value in code.co_consts:
     if not isinstance(value,bytes) or value[:1] not in (b'c',b'\xe3'):continue
     try:child=marshal.loads(value)
     except (ValueError,TypeError,EOFError):continue
     if isinstance(child,types.CodeType) and child.co_name=='<module>':
      match=find(child)
      if match:return match
   return types.FunctionType(find(self.reader(module)),namespace)
  def require(ok,message):
   if not ok:raise ValueError(message)
  def forbidden(*args):raise AssertionError('No native allocation during preflight')
  templates=literal_assignments(self.reader('diy_route_templates'),{'TEMPLATES'})['TEMPLATES'];sites=literal_assignments(self.reader('diy_routes'),{'SITES'})['SITES']
  ns={'copy':copy,'re':re,'struct':struct,'TEMPLATES':templates,'SITES':sites}
  ns['_sso']=function('diy_routes','_sso',ns);real_compose=function('diy_routes','compose',ns)
  ns={'dis':dis,'types':types,'capture':capture,'compose':real_compose,'CAPACITY':65536,'require':require}
  ns['sized_worker']=function('diy_runtime','sized_worker',ns);real_prepare=function('diy_runtime','prepare_binding',ns)
  outer=types.ModuleType('diy_binding_outer');outer._start_legend_portrait_binding=function('diy_binding_outer','_start_legend_portrait_binding',{})
  raw=types.FunctionType(self.installer.raw_code,{'allocate_portrait_pages':allocator or forbidden});raw.__globals__['_start_legend_portrait_binding']=raw
  actual=raw
  with patch.dict(sys.modules,{'diy_binding_outer':outer}):
   for layer in self.installer.route_layers:actual,payload,_=real_prepare(actual,layer)
  return actual,payload

 def test_preflight_uses_actual_v16_loader_and_resizes_only_our_entry_span(self):
  actual,payload=self.actual_loader()
  self.assertEqual(payload,self.payload);self.assertNotEqual(fingerprint(payload),fingerprint(self.installer.raw_payload))
  before=capture(actual);modified,report=prepare(actual,self.binding)
  self.assertEqual(capture(actual),before);self.assertEqual(report['stock_routes_preserved'],len(self.installer.routes));self.assertEqual(report['page_bytes'],4096)
  worker=next(c for c in modified.__code__.co_consts if isinstance(c,types.CodeType) and c.co_name=='worker')
  self.assertEqual(code_fingerprint(worker),self.installer.proof['raw_worker_fingerprint'])
  checked=verify_installer(self.installer,self.binding)
  self.assertTrue(checked.pop('allocator_contract_verified'));self.assertEqual(checked,report)
  bad=copy.deepcopy(self.binding);bad['original_fingerprint']='0'*64
  with self.assertRaisesRegex(ValueError,'指纹'):prepare(actual,bad)
  bad=copy.deepcopy(self.binding);bad['source']['raw_worker_fingerprint']='0'*64
  with self.assertRaisesRegex(ValueError,'工作器'):prepare(actual,bad)

 def test_v16_prepared_allocator_rejects_4k_but_restored_pair_accepts_it(self):
  calls=[]
  def raw_allocator(libc,rows,base,size,*args):calls.append(size);return 0x100000,'original_4k'
  def forbidden(*args):raise AssertionError('no native memory calls')
  actual,_=self.actual_loader(raw_allocator)
  wrapped=actual.__globals__['allocate_portrait_pages']
  args=(None,[],0,4096,forbidden,forbidden,forbidden,[])
  with self.assertRaisesRegex(ValueError,'DIY allocation size changed'):wrapped(*args)
  self.assertEqual(calls,[])
  modified,report=prepare(actual,self.binding)
  self.assertEqual(modified.__globals__['allocate_portrait_pages'](*args),(0x100000,'original_4k'))
  self.assertEqual(calls,[4096]);self.assertEqual(report['page_bytes'],4096)

 def test_desktop_preflight_exercises_real_allocator_size_guard(self):
  def forbidden(*args):raise AssertionError('no native memory calls')
  actual,_=self.actual_loader()
  raw=actual.__globals__['_start_legend_portrait_binding']
  descriptor=types.SimpleNamespace(proof=self.installer.proof,function=lambda stub:actual)
  # Model the old bug: the restored worker still calls the sized allocator.
  with patch.dict(raw.__globals__,{'allocate_portrait_pages':actual.__globals__['allocate_portrait_pages']}):
   with self.assertRaisesRegex(ValueError,'DIY allocation size changed'):verify_installer(descriptor,self.binding)
  self.assertTrue(verify_installer(self.installer,self.binding)['allocator_contract_verified'])

 def test_stock_native_model_routes_survive_personal_dispatch_and_relocation(self):
  try:
   from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
   from unicorn import arm64_const as r
  except ImportError:self.skipTest('requires optional ARM64 emulator')
  out=compose(self.payload,[self.route],self.profile);root_addr,ext_addr,table_addr=0x100000,0x300000,0x500000;stop=0x600000
  data=bytearray.fromhex(out['blob_hex']);struct.pack_into('<Q',data,out['back_fixup'],0x7000000000+out['hooks'][0]['address']+4)
  data,extension=relocate_code(out,bytes(data),root_addr,ext_addr,table_addr+144)
  face=next(h for h in out['hooks'] if h['address']==self.profile['sites']['face'])
  original=next(h['offset'] for h in self.installer.raw_payload['hooks'] if h['address']==self.profile['sites']['face'])
  original_pc=root_addr+original if original<out['root_prefix_bytes'] else ext_addr+original-out['root_prefix_bytes']
  for route in self.installer.routes:
   vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
   for addr,size,raw in ((root_addr,0x10000,data),(ext_addr,0x10000,extension),(table_addr,0x10000,bytes(144)+bytes.fromhex(out['route_table_hex'])),(stop,0x1000,b''),(0x800000,0x10000,b'')):
    vm.mem_map(addr,size)
    if raw:vm.mem_write(addr,raw)
   vm.reg_write(r.UC_ARM64_REG_SP,0x808000);vm.reg_write(r.UC_ARM64_REG_X1,route['cardId']);vm.reg_write(r.UC_ARM64_REG_X30,stop)
   handed_off=[]
   def handoff(machine,pc,size,user):
    if pc==original_pc:handed_off.append(machine.reg_read(r.UC_ARM64_REG_X1));machine.emu_stop()
   vm.hook_add(UC_HOOK_CODE,handoff)
   # Both layers preserve the stock lookup's native-model argument (x1).
   vm.emu_start(root_addr+face['offset'],stop,count=2000)
   self.assertEqual(handed_off,[route['modelNativeId']]);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x808000)

 def test_changed_preparation_call_cannot_be_silently_treated_as_legacy(self):
  code=compile("def unused(): pass\n_start_legend_portrait_binding=prepare_binding(_start_legend_portrait_binding, [{'cardId':1}])[1]\n",'bad.py','exec')
  with self.assertRaises(ValueError):literal_routes(code)

class V17BindingTests(V193BindingTests):
 original_apk=Path('C:/Users/1/Downloads/73efootball-V17.apk')
 if not original_apk.is_file():
  original_apk=Path(__file__).resolve().parents[2].parent/'73efootball安装包及资源/73efootball-V17.apk'

 def test_two_stock_preparation_layers_and_isolated_native_worker(self):
  self.assertEqual([len(layer) for layer in self.installer.route_layers],[4,6])
  actual,payload=self.actual_loader(lambda *args:(0x7000000000+0x6000000,'isolated'))
  self.assertEqual(payload,self.payload)
  modified,_=prepare(actual,self.binding)
  from native_worker_sim import run
  import zipfile
  with zipfile.ZipFile(self.apk) as archive:engine=archive.read('lib/arm64-v8a/libUE4.so')
  report=run(modified,capture(modified),engine)
  self.assertEqual(report['status'],'binding_installed',report)

 def test_coaches_only_binding_installs_custom_link_adapters(self):
  import io,zipfile
  from native_extensions import link_hooks
  from native_coach_links import schema
  from native_worker_sim import run
  with zipfile.ZipFile(self.apk) as archive:engine=archive.read('lib/arm64-v8a/libUE4.so')
  binding=copy.deepcopy(self.binding);binding['routes']=[]
  binding['profile']['native_hooks']=link_hooks([{'id':256,'template_id':8}],io.BytesIO(engine),schema())
  from native_skill_effects import hooks as skill_hooks
  binding['profile']['native_hooks']+=skill_hooks(io.BytesIO(engine))
  actual,_=self.actual_loader(lambda *args:(0x7000000000+0x6000000,'isolated'))
  modified,_=prepare(actual,binding)
  report=run(modified,capture(modified),engine)
  self.assertEqual(report['status'],'binding_installed',report)
  self.assertEqual(report['patched_hooks'],report['total_hooks'])

 def test_cpu_coaching_observer_installs_through_actual_v17_worker_without_personal_cards(self):
  import io,zipfile
  from native_ai_match import hooks as match_hooks
  from native_worker_sim import run
  with zipfile.ZipFile(self.apk) as archive:engine=archive.read('lib/arm64-v8a/libUE4.so')
  binding=copy.deepcopy(self.binding);binding['routes']=[]
  binding['profile']['native_hooks']=match_hooks(io.BytesIO(engine))
  actual,_=self.actual_loader(lambda *args:(0x7000000000+0x6000000,'isolated'))
  modified,_=prepare(actual,binding);payload=capture(modified)
  self.assertIn('ai_match_channel',payload)
  with patch('ai_match_runtime.register_channel',return_value=object()) as register:
   report=run(modified,payload,engine)
  self.assertEqual(report['status'],'binding_installed',report)
  self.assertEqual(report['patched_hooks'],report['total_hooks'])
  register.assert_called_once()
  self.assertGreaterEqual(len(register.call_args.args[0]),32768)
  self.assertEqual(register.call_args.args[1],payload['ai_match_channel']['data_offset'])
  self.assertEqual(register.call_args.args[4],payload['ai_match_channel']['proof'])

if __name__=='__main__':unittest.main()
