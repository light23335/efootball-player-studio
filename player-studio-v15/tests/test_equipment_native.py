"""Run the actual V17 appearance and BootsList consumers, not a mirrored mask."""
import io,struct,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).parent)]
from native_equipment import patch_sleeves
ENGINE=Path(__file__).resolve().parents[2]/'.work/xi-v17-gameplay-compare/v17-engine.so'

@unittest.skipUnless(ENGINE.is_file(),'requires audited original V17 engine')
class NativeEquipmentTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import unicorn
  from unicorn import arm64_const
  from elftools.elf.elffile import ELFFile
  from test_skill_effects_v2 import NativeSkillV2Tests
  cls.u,cls.r=unicorn,arm64_const;cls.engine=ENGINE.read_bytes()
  elf=ELFFile(io.BytesIO(cls.engine));cls.segments=[(s['p_vaddr'],s['p_offset'],s['p_filesz'],s['p_memsz'])for s in elf.iter_segments()if s['p_type']=='PT_LOAD']
  cls.machine=NativeSkillV2Tests.machine

 def decode(self,row,season):
  vm=self.machine({});r=self.r
  for at in(0x42000000,0x43000000,0x44000000):vm.mem_map(at,0x10000)
  vm.mem_write(0x43000000,row)
  for reg,value in((r.UC_ARM64_REG_X0,0x42000000),(r.UC_ARM64_REG_X1,0x43000008),(r.UC_ARM64_REG_X2,season),(r.UC_ARM64_REG_X25,0x44000000)):
   vm.reg_write(reg,value)
  vm.emu_start(0x68d200c,0x68d2088,count=1000)
  sleeve=struct.unpack('<I',vm.mem_read(0x40008000+0x14,4))[0]
  skin=struct.unpack('<I',vm.mem_read(0x42000000+0x1e8,4))[0]
  return sleeve,skin

 def test_original_decoder_observes_correct_sleeves_and_preserves_skin(self):
  row=((4<<292)|(1<<134)).to_bytes(64,'little')
  for season in(0,1):
   for name,expected in(('seasonal',season),('short',0),('long',1)):
    self.assertEqual(self.decode(patch_sleeves(row,{'sleeves':name}),season),(expected,4))

 def test_legacy_134_mask_changes_no_sleeve_in_the_native_reader(self):
  short=(1<<126).to_bytes(64,'little')
  wrong=(int.from_bytes(short,'little')|(2<<134)).to_bytes(64,'little')
  self.assertEqual(self.decode(wrong,0)[0],0)
  self.assertEqual(self.decode(patch_sleeves(wrong,{'sleeves':'long'}),0)[0],1)

 def test_original_boots_reader_handles_full_card_and_private_alias_without_changing_stock(self):
  vm=self.machine({});r=self.r;table=0x42000000;data=0x43000000
  vm.mem_map(table,0x10000);vm.mem_map(data,0x10000)
  rows={33702:52,8632601:5031,89060173448102:5031}
  vm.mem_write(data,b''.join(struct.pack('<QQ',k,v)for k,v in sorted(rows.items())))
  vm.mem_write(table+0x10,struct.pack('<QHHI',data,62,0,len(rows)))
  for key,want in [*rows.items(),(777,62)]:
   vm.reg_write(r.UC_ARM64_REG_X0,table);vm.reg_write(r.UC_ARM64_REG_X1,key);vm.reg_write(r.UC_ARM64_REG_X30,0x2003f000)
   vm.emu_start(0x8245178,0x2003f000,count=5000)
   self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0),want)

if __name__=='__main__':unittest.main()
