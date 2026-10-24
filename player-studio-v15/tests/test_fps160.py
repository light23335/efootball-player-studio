from pathlib import Path
import copy,json,struct,sys,tempfile,types,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_fps import fps_module,verify_fps160
from personal_runtime import prepare_fps160,install_fps_options

class StopWorker(BaseException):pass

class Fps160Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.apk=Path(__file__).resolve().parents[2].parent/'73efootball安装包及资源/73efootball-V16(1).apk'
  if not cls.apk.is_file():raise unittest.SkipTest('requires original V16 APK')
 def test_original_engine_and_five_hook_sites_verify_without_writing(self):
  with zipfile.ZipFile(self.apk) as z,z.open('lib/arm64-v8a/libUE4.so') as engine:report=verify_fps160(self.apk,engine)
  self.assertEqual(report['native_hooks_verified'],5);self.assertTrue(report['engine_instructions_verified'])
 def test_disabled_option_does_not_import_or_alter_original_fps(self):
  with tempfile.TemporaryDirectory() as folder:
   original=fps_module(self.apk);before=copy.deepcopy(original.PAYLOAD)
   with patch.dict(sys.modules,{'fps120_runtime':original}):
    install_fps_options({},folder);install_fps_options({'frame_rate':{'force_160':False}},folder)
   self.assertEqual(original.PAYLOAD,before);self.assertFalse(hasattr(original,'_studio_fps160'));self.assertFalse(list(Path(folder).iterdir()))
 def test_config_is_idempotent_and_does_not_modify_frame_table_or_native_sites(self):
  module=fps_module(self.apk);before=copy.deepcopy(module.PAYLOAD);report=prepare_fps160(module)
  self.assertEqual(prepare_fps160(module),report)
  for key in before:
   if key!='blob_hex':self.assertEqual(before[key],module.PAYLOAD[key])
  a=bytes.fromhex(before['blob_hex']);b=bytes.fromhex(module.PAYLOAD['blob_hex'])
  self.assertEqual([n for n,(x,y) in enumerate(zip(a,b)) if x!=y],[621,1106])
  self.assertEqual(b[620:624],bytes.fromhex('17148052'));self.assertEqual(b[1104:1110],'160'.encode('utf-16le'))
  self.assertEqual(module.display_refresh_for_enum(5),160)
  for desired in range(6):self.assertEqual(module.sticky_fps_target(desired,True),5);self.assertIsNone(module.sticky_fps_target(desired,False))
 def test_unknown_runtime_fails_before_mutation_and_does_not_block_game_startup(self):
  module=fps_module(self.apk);module.PAYLOAD['blob_hex']='00';before=copy.deepcopy(module.PAYLOAD)
  with self.assertRaises(ValueError):prepare_fps160(module)
  self.assertEqual(module.PAYLOAD,before)
  with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'fps120_runtime':module}):
   install_fps_options({'frame_rate':{'force_160':True}},folder)
   result=json.loads((Path(folder)/'outputs/efootball/personal-fps160-status.json').read_text())
   self.assertEqual(result['status'],'not_applied')
 def test_real_worker_overrides_user_lower_selection_and_leaves_background_unlocked(self):
  module=fps_module(self.apk);prepare_fps160(module);cells={};state={'mailbox':0x300000,'base':0,'memory':None};observed={'selected':0,'saved':1};reports=[];restores=[]
  class Cell:
   def __init__(self,address):self.address=address
   @classmethod
   def from_address(cls,address):return cls(address)
   @property
   def value(self):return cells.get(self.address,0)
   @value.setter
   def value(self,value):cells[self.address]=value
  module.ctypes=types.SimpleNamespace(c_uint32=Cell)
  state['memory']=types.SimpleNamespace(read=lambda address,size:struct.pack('<I',observed['selected']))
  module._await_native_ready=lambda root,result:(state['memory'],0)
  module.backup_settings=lambda root:{'status':'simulated'}
  def install(memory,base):module._installed=state;return {'status':'menu_hooks_installed'}
  module.install=install;module._hooks_intact=lambda state:True
  module._read_saved_fps=lambda state:observed['saved'];module._read_mailbox=lambda state:(1,0,1)
  def restore(state,desired):restores.append(desired);observed.update(selected=desired,saved=desired);return True
  module._restore_fps=restore;module._request_display_refresh=lambda hz:{'requested_hz':hz}
  module.time=types.SimpleNamespace(monotonic=lambda:10,sleep=lambda seconds:(_ for _ in ()).throw(StopWorker()))
  module._report=lambda root,value:reports.append(copy.deepcopy(value));module._activity_focused=lambda:True
  with self.assertRaises(StopWorker):module._worker('unused')
  self.assertEqual(restores,[5]);self.assertEqual(cells[0x300000],5);self.assertEqual(cells[0x300004],1)
  self.assertEqual(reports[-1]['engine_target_fps'],160)
  module._activity_focused=lambda:False
  with self.assertRaises(StopWorker):module._worker('unused')
  self.assertEqual(cells[0x300004],0)
 def test_arm64_frame_hook_returns_160_and_background_keeps_native_table(self):
  try:
   from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
   from unicorn.arm64_const import UC_ARM64_REG_W20,UC_ARM64_REG_W23,UC_ARM64_REG_X8
  except ImportError:self.skipTest('requires Unicorn ARM64 emulator')
  page=0x100000;mailbox=0x300000;table=0x400000
  original=fps_module(self.apk);fixed=fps_module(self.apk);prepare_fps160(fixed)
  def run(module,desired,allow,selected):
   uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
   for address in (page,mailbox,table):uc.mem_map(address,4096)
   uc.mem_write(page,module.native_payload(0x7000000,mailbox));uc.mem_write(mailbox,struct.pack('<III',desired,allow,0));uc.mem_write(table,bytes.fromhex(module.PAYLOAD['frame_table_hex']))
   uc.reg_write(UC_ARM64_REG_X8,table);uc.reg_write(UC_ARM64_REG_W20,selected)
   uc.emu_start(page+576,page+896,count=100)
   return uc.reg_read(UC_ARM64_REG_W23)
  self.assertEqual(run(original,5,1,0),120)
  for selected in range(6):self.assertEqual(run(fixed,5,1,selected),160)
  self.assertEqual(run(fixed,5,0,0),60);self.assertEqual(run(fixed,5,0,1),30);self.assertEqual(run(fixed,5,0,3),15)

if __name__=='__main__':unittest.main()
