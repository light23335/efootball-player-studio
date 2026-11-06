"""Execute original Android ComLevel getters/setters against private fixtures.

Only original engine instructions and the production adapter run in Unicorn.
The native world selector, score clock and other unrelated dependencies are
explicit fixture inputs. No game or workshop is started.
"""
import hashlib,io,json,os,struct,unittest,zipfile
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
SOURCE=Path(__file__).resolve().parents[1]
APK=Path(os.environ.get('STUDIO_TEST_APK',str(SOURCE.parent.parent/'73efootball安装包及资源/73efootball-V17.apk')))
raw=b'';bundle={};layout={}
EXT,DATA,STACK,TLS,BUS,STOP=0x10000538,0x20000000,0x30000000,0x31000000,0x32000000,0x40000000
SELF,ROOT,COMMON,PLAYERS,INFO,TEAM,EVENT,FRAME,STATE=tuple(DATA+i*0x10000 for i in range(9))
KEY=0x73455abc
XREG=[UC_ARM64_REG_X0+i for i in range(29)]+[UC_ARM64_REG_X29,UC_ARM64_REG_X30]


class VM:
 def __init__(self):
  self.uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
  self.wall_seconds=1.
  lo,hi=0x6700000,0x7360000
  self.uc.mem_map(lo,hi-lo);self.uc.mem_write(lo,raw[lo-16384:hi-16384])
  for address,size in ((EXT&~4095,0x20000),(DATA,0x200000),(STACK,0x20000),(TLS,0x1000),(BUS,32768),(STOP,4096)):
   self.uc.mem_map(address,size)
  self.uc.mem_map(0x8c1b000,4096)
  body=bytearray.fromhex(bundle['body_hex'])
  for at,size in bundle['writable_fixups']:struct.pack_into('<Q',body,at,BUS)
  self.uc.mem_write(EXT,bytes(body));self.uc.reg_write(UC_ARM64_REG_TPIDR_EL0,TLS)
  self.uc.reg_write(UC_ARM64_REG_SP,STACK+0x1f000)
  self.u64(SELF+0x370,ROOT);self.u64(SELF+0x378,TEAM);self.u32(SELF+8,1)
  # Execute the original callback roster getter. A global getter on this
  # context deliberately resolves a different, invalid holder.
  for side in (0,1):
   self.u64(ROOT+0x3630+side*0x50,PLAYERS)
   self.u64(ROOT+0x30d0+side*0x50,DATA+0x190000)
  self.u32(DATA+0x190000+0x406c,16384)
  self.u32(PLAYERS+0x406c,23)
  self.u32(INFO+0x3310,1);self.u32(INFO+0x3314,2);self.u32(INFO+0x34cc,5)
  self.u32(INFO+0x3320,struct.unpack('<I',struct.pack('<f',60*3600.0))[0]^KEY)
  self.uc.mem_write(INFO+0x4202,bytes([1])*22)
  self.u32(TEAM,0) # Not the plan; actual plan begins at +0x8078.
  self.uc.mem_write(TEAM+0xa5,b'\5\3')
  self.u32(EVENT,8)
  for i in range(23):
   self.u32(PLAYERS+4+i*4,i)
   self.u32(PLAYERS+0xa8+i*0x198+0x30,810000001+i)
   self.u32(PLAYERS+0xa8+i*0x198+0x34,0xa5a5a5a5) # Real ABI padding is not identity.
   self.u64(PLAYERS+0xa8+i*0x198+0x38,1000+i)
   self.uc.mem_write(PLAYERS+0xa8+i*0x198+0x30+0x109,bytes((63,)))
   self.u64(BUS+layout['expected']+i*16,1000+i)
   self.u64(BUS+layout['expected']+i*16+8,810000001+i)
   for axis in (1,2):self.u32(TEAM+0x8078+0x1c+i*12+axis*4,0 if i==0 else 5)
  for i in range(22):
   self.u32(STATE+i*0x1000+0x490,(37+i)^KEY)
   self.u32(STATE+i*0x1000+0x494,100^KEY)
  self.u32(BUS+layout['configuration_sequence'],2);self.u32(BUS+layout['enabled'],1)
  if 'state_healthy'in layout:self.u32(BUS+layout['state_healthy'],1)
  if 'state_field_mask'in layout:
   self.u32(BUS+layout['state_field_mask'],(1<<11)-1)
   self.u32(BUS+layout['state_period'],1);self.u64(BUS+layout['state_epoch'],456)
  self.u64(BUS+layout['epoch'],456);self.u64(BUS+layout['game_id'],789)
  self.human=False;self.pending=0;self.calls=[];self.queued=[];self.capture_queue_entry=False
  self.stubs={0x72c3e28:lambda:COMMON,0x72c3e80:lambda:INFO,0x72c4028:lambda:TEAM,
   0x72c3f2c:lambda:FRAME,0x73044a0:lambda:FRAME,0x6991db8:lambda:2 if self.reg(1)==1 else 1,
   0x72e1478:lambda:int(self.human),0x72c40b0:lambda:STATE+self.reg(1)*0x1000,
   0x6ce6ef0:lambda:1,0x6774740:lambda:KEY,0x68fbf34:lambda:self.pending,
   0x72eb1d8:lambda:0,0x72eb0ec:lambda:0,0x72eb25c:self.queue,0x8c1bc40:self.monotonic_clock}
  self.uc.hook_add(UC_HOOK_CODE,self.hook)
 def reg(self,i):return self.uc.reg_read(XREG[i])
 def u32(self,at,value):self.uc.mem_write(at,struct.pack('<I',value))
 def u64(self,at,value):self.uc.mem_write(at,struct.pack('<Q',value))
 def read32(self,at):return struct.unpack('<I',self.uc.mem_read(at,4))[0]
 def monotonic_clock(self):
  assert self.reg(0)==1
  sec=int(self.wall_seconds);ns=round((self.wall_seconds-sec)*1e9)
  self.uc.mem_write(self.reg(1),struct.pack('<qq',sec,ns));return 0
 def hook(self,uc,address,size,data):
  if address==0x6ce6108 and self.capture_queue_entry:
   self.captured=[self.reg(i) for i in range(4)];uc.emu_stop();return
  if address in self.stubs:
   self.calls.append(address);value=self.stubs[address]()
   uc.reg_write(UC_ARM64_REG_X0,value);uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_X30))
 def queue(self):
  self.queued.append([self.reg(i) for i in range(4)]);self.pending+=1;return 1
 def call(self,address,*args):
  for i,value in enumerate(args):self.uc.reg_write(XREG[i],value)
  self.uc.reg_write(UC_ARM64_REG_X30,STOP)
  self.uc.emu_start(address,STOP,count=100000)
  return self.reg(0)
 def snap(self,key):return self.read32(BUS+layout['snapshot']+layout['snapshot.'+key])



@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class DifficultyNativeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  global raw,bundle,layout
  with zipfile.ZipFile(APK)as z:raw=z.read('lib/arm64-v8a/libUE4.so')
  assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
  bundle=json.loads((SOURCE/'resources/native-ai-match-adapter.json').read_text('utf8'));layout=bundle['channel_schema']
 def test_both_native_comlevel_caches_follow_all_seven_levels_and_keep_keys(self):
  CPU=DATA+0x180000;OTHER=DATA+0x1a0000
  for team in (0,1):
   for level in range(7):
    v=VM();v.u32(SELF+8,team);v.stubs[0x698f7e0]=lambda:ROOT;v.u64(ROOT+0x480,CPU)
    for at in (CPU,CPU+12,TEAM+0x8f2c,TEAM+0x8f38):
     v.u32(at,0x12345678);v.u32(at+4,0x12345678);v.u32(at+8,0)
    v.uc.mem_write(OTHER,bytes([0xa5])*64);outside=bytes(v.uc.mem_read(OTHER,64))
    v.u32(BUS+layout['rules_enabled'],1);v.u32(BUS+layout['difficulty_enabled'],1);v.u32(BUS+layout['difficulty_requested'],level)
    v.stubs[0x72c3eb0]=lambda:0
    assert v.call(EXT+bundle['helper_entries']['studio_observe'],SELF,EVENT,1)==1
    assert v.read32(BUS+layout['difficulty_applied'])==1
    assert v.read32(BUS+layout['difficulty_after_offense'])==level
    assert v.read32(BUS+layout['difficulty_after_defense'])==level
    for at in (CPU,CPU+12,TEAM+0x8f2c,TEAM+0x8f38):
     assert v.read32(at)^v.read32(at+4)==level
     assert v.read32(at+4)==0x12345678
     assert v.read32(at+8)==0
    assert bytes(v.uc.mem_read(OTHER,64))==outside
  
 def test_human_mismatched_roster_division_and_invalid_level_never_write(self):
  CPU=DATA+0x180000
  for reason in ('disabled','human','roster_mismatch','division','invalid_level'):
   v=VM();v.stubs[0x698f7e0]=lambda:ROOT;v.u64(ROOT+0x480,CPU);v.stubs[0x72c3eb0]=lambda:0
   v.u32(BUS+layout['rules_enabled'],1);v.u32(BUS+layout['difficulty_enabled'],1);v.u32(BUS+layout['difficulty_requested'],5)
   if reason=='disabled':v.u32(BUS+layout['enabled'],0)
   if reason=='human':v.human=True
   if reason=='roster_mismatch':v.u64(BUS+layout['expected'],999)
   if reason=='division':v.u32(BUS+layout['rules_enabled'],0)
   if reason=='invalid_level':v.u32(BUS+layout['difficulty_requested'],7)
   before=bytes(v.uc.mem_read(TEAM+0x8f2c,24));v.call(EXT+bundle['helper_entries']['studio_observe'],SELF,EVENT,1)
   assert bytes(v.uc.mem_read(TEAM+0x8f2c,24))==before
   assert v.read32(BUS+layout['difficulty_applied'])==0

if __name__=='__main__':unittest.main()
