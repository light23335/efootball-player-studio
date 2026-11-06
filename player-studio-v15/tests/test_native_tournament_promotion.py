"""Actual emitted bridge and original factory/setup/button instructions.

World spawning, reflection, UObject registry, input activation and allocation
are fixtures; this is not a UE rendering or device gameplay test.
"""
from pathlib import Path
import copy,hashlib,json,os,struct,unittest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
import unicorn.arm64_const as R
import tournament_home as home

ROOT=Path(__file__).resolve().parents[2]
PROFILE=Path(os.environ.get('STUDIO_TEST_HOME_ADAPTER',str(ROOT/'player-studio-v15/resources/tournament_schedule_ui/native-home.json')))
CODE,CONTROL,DATA,STACK,TLS,STOP=0x10000000,0x20000000,0x21000000,0x22000000,0x23000000,0x24000000
PARENT,ACTOR,ITEMS,CHUNKS,CLASS,VT,WORLD,HEAP=tuple(DATA+i*0x10000 for i in range(8))
BUS=CONTROL+home.SCHEMA['promotion_offset']


class VM:
    def __init__(self):
        self.profile=json.loads(PROFILE.read_text('utf8'));self.uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        self.pages=set();self.calls=[];self.heap=HEAP;self.stubs={}
        engine=(ROOT/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
        self.assert_engine=hashlib.sha256(engine).hexdigest()
        for address,size in ((CODE,0x10000),(CONTROL,0x30000),(DATA,0x90000),(STACK,0x20000),(TLS,4096),(STOP,4096)):
            self.map(address,size)
        for a,n in ((0x333b1f0,0x7c),(0x33401d4,0x174),(0x302d514,0x1c8),(0x3027818,12),
                    (0x3336440,0x7c),(0x3bba208,0x20),(0x45ee3f8,76),(0x54c7964,0x188)):
            self.map(a,n);self.uc.mem_write(a,engine[a-16384:a-16384+n])
        for a in (0x3d82d3c,0x3cb87f0,0x5d17c48,0x5d17e08,0x3bfe274,0x2870f08,0x8c1bc70,0x8c1bc00,0x302b488,0x302788c,0x45c17e4,0x4414bec,0x54f0ce4):self.map(a,4)
        self.map(0x9fe79b8,32);self.map(0x99e5918,8);self.map(0x74b290,16);self.map(0x99e4ed8,8)
        self.write(0x99e4ed8,'Q',0x9fe79b8)
        body=bytearray.fromhex(self.profile['body_hex'])
        for at,target in self.profile['absolute_fixups']:struct.pack_into('<Q',body,at,target)
        for at,size in self.profile['writable_fixups']:struct.pack_into('<Q',body,at,CONTROL)
        self.uc.mem_write(CODE,bytes(body));self.entry=CODE+self.profile['promotion_native']['helper_entry']
        self.uc.reg_write(R.UC_ARM64_REG_TPIDR_EL0,TLS);self.write(TLS+0x28,'Q',0x11223344)
        self.write(0x9fe79b8+16,'Q',CHUNKS);self.write(CHUNKS,'Q',ITEMS)
        self.object(PARENT,1,11);self.object(ACTOR,2,22)
        self.write(PARENT+0x226,'B',3);self.write(PARENT,'Q',VT);self.write(VT+0x160,'Q',STOP+0x100)
        self.write(CLASS+0x38,'I',0);self.write(CLASS+0x30,'Q',CLASS+0x100);self.write(CLASS+0x100,'Q',CLASS+0x30)
        self.write(ACTOR+0x10,'Q',CLASS)
        self.write(0x99e5918,'Q',CLASS+0x200)
        self.write(BUS+912,'I',1)
        self.stubs.update({0x3d82d3c:lambda:CLASS,0x3cb87f0:lambda:CLASS,STOP+0x100:lambda:WORLD,
            0x5d17c48:self.spawn,0x5d17e08:lambda:0,0x3bfe274:self.parent,
            0x2870f08:self.resize,0x8c1bc70:self.memcpy,0x302b488:lambda:0,0x302788c:lambda:0,0x45c17e4:self.serial})
        self.uc.hook_add(UC_HOOK_CODE,self.hook)

    def map(self,address,size):
        for at in range(address&~4095,(address+size+4095)&~4095,4096):
            if at not in self.pages:self.uc.mem_map(at,4096);self.pages.add(at)
    def write(self,at,fmt,*v):self.uc.mem_write(at,struct.pack('<'+fmt,*v))
    def read(self,at,fmt):return struct.unpack('<'+fmt,self.uc.mem_read(at,struct.calcsize('<'+fmt)))
    def reg(self,i):return self.uc.reg_read(getattr(R,'UC_ARM64_REG_X'+str(i)))
    def object(self,actor,index,serial):
        self.write(actor+12,'I',index);self.write(ITEMS+index*24,'Q',actor);self.write(ITEMS+index*24+16,'I',serial)
    def spawn(self):
        assert self.reg(0)==WORLD and self.reg(1)==CLASS
        self.calls.append('original_child_factory_spawn');return ACTOR
    def parent(self):
        assert self.reg(0)==ACTOR and self.reg(1)==PARENT
        self.calls.append('native_set_parent');return 0
    def serial(self):
        index=self.reg(1);value=self.read(ITEMS+index*24+16,'I')[0]or 100+index
        self.write(ITEMS+index*24+16,'I',value);self.calls.append('native_weak_serial');return value
    def resize(self):
        at=self.reg(0);count=self.reg(1);self.write(at,'QII',self.heap,count,count)
        self.heap+=0x400;return 0
    def memcpy(self):
        self.uc.mem_write(self.reg(0),bytes(self.uc.mem_read(self.reg(1),self.reg(2))));return self.reg(0)
    def hook(self,uc,at,size,_):
        if at==STOP:uc.emu_stop()
        elif at in self.stubs:
            value=self.stubs[at]();uc.reg_write(R.UC_ARM64_REG_X0,value);uc.reg_write(R.UC_ARM64_REG_PC,self.reg(30))
        elif at==0x8c1bc00:raise AssertionError('native stack protector')
    def call(self,action,self_actor=PARENT,event=205060988,caller=0):
        self.uc.reg_write(R.UC_ARM64_REG_SP,STACK+0x1f000)
        for i,value in enumerate((action,BUS,self_actor,event,caller)):self.uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),value)
        self.uc.reg_write(R.UC_ARM64_REG_X30,STOP)
        self.uc.emu_start(self.entry,STOP,count=100000)
    def channel(self):return home.Channel(self.uc_buffer,0,lambda:None)
    def request(self,generation=1,token=b'A'*16,sequence=2):
        raw=bytearray(808);struct.pack_into('<IIQ16sII',raw,0,sequence,205060988,generation,token,1,7)
        for i,text in enumerate(('晋级下一轮','测试锦标赛','确认')):raw[40+i*256:40+(i+1)*256]=home._text(text)
        self.uc.mem_write(BUS+40,bytes(raw))
    def status(self):return self.read(BUS+852,'I')[0]
    def native_button(self):
        offset=next(h['entry_offset']for h in self.profile['extra_entries']if h['name']=='tournament_promotion_confirm_button')
        self.write(ACTOR,'Q',VT);self.write(VT+0x888,'Q',CODE+offset)
        self.uc.reg_write(R.UC_ARM64_REG_SP,STACK+0x1e000);self.uc.reg_write(R.UC_ARM64_REG_X29,STACK+0x1f000)
        self.uc.reg_write(R.UC_ARM64_REG_X20,ACTOR)
        self.uc.emu_start(0x3bba208,0x3bba220,count=10000)


class NativePromotionTests(unittest.TestCase):
    def test_original_factory_setup_and_real_button_dispatch_reach_scoped_receipt(self):
        v=VM();v.call(1);v.request();v.call(2)
        self.assertEqual(v.status(),1);self.assertEqual(v.calls.count('original_child_factory_spawn'),1)
        self.assertEqual(v.read(ACTOR+0x12f8,'BBBB'),(7,0,0,1))
        for i,text in enumerate(('晋级下一轮','测试锦标赛','确认')):
            ptr,count,_=v.read(ACTOR+0x12c8+i*16,'QII')
            self.assertEqual(bytes(v.uc.mem_read(ptr,count*2)).decode('utf-16le').rstrip('\0'),text)
        v.native_button();self.assertEqual(v.status(),2)
        v.call(5,ACTOR);self.assertEqual(v.status(),5)
        v.call(2);self.assertEqual(v.read(CONTROL+32,'II'),(205060988,1))

    def test_duplicate_sequences_and_confirmed_tokens_never_spawn_twice(self):
        v=VM();v.call(1);v.request();v.call(2)
        for _ in range(5):v.call(2)
        self.assertEqual(v.calls.count('original_child_factory_spawn'),1)
        v.call(3,ACTOR,caller=0x3bba220);v.call(5,ACTOR)
        v.request(sequence=4);v.call(2)
        self.assertEqual(v.status(),5);self.assertEqual(v.calls.count('original_child_factory_spawn'),1)

    def test_wrong_event_generation_actor_caller_and_reused_object_cannot_confirm(self):
        v=VM();v.call(1);v.request(generation=99);v.call(2)
        self.assertEqual(v.status(),3);self.assertNotIn('original_child_factory_spawn',v.calls)
        v.request(sequence=4);v.call(2);self.assertEqual(v.status(),1)
        v.call(3,PARENT,caller=0x3bba220);v.call(3,ACTOR,caller=0x3d32c38)
        self.assertEqual(v.status(),1)
        v.object(ACTOR,2,23);v.call(3,ACTOR,caller=0x3bba220)
        self.assertEqual(v.status(),1)

    def test_loading_or_closing_parent_defers_and_unconfirmed_destruction_is_not_consent(self):
        v=VM();v.call(1);v.request()
        for state in (0,1,2,4,5):
            v.write(PARENT+0x226,'B',state);v.call(2);self.assertEqual(v.calls,[])
        v.write(PARENT+0x226,'B',3);v.call(2);v.call(4,ACTOR)
        self.assertEqual(v.status(),4)

    def test_foreign_menu_and_generation_change_never_reuse_an_old_delivery(self):
        v=VM();v.call(1);v.request();v.call(2)
        v.object(PARENT,1,12);v.call(1)
        self.assertEqual(v.status(),4);self.assertEqual(v.read(BUS+24,'Q')[0],2)
        v.call(3,ACTOR,caller=0x3bba220);self.assertNotEqual(v.status(),2)

    def test_original_weak_identity_assignment_stabilizes_initial_zero_serials(self):
        v=VM();v.object(PARENT,1,0);v.object(ACTOR,2,0)
        v.call(1);v.request();v.call(2);self.assertEqual(v.status(),1)
        self.assertEqual(v.calls.count('native_weak_serial'),2)
        v.native_button();self.assertEqual(v.status(),2)

    def test_all_native_entry_wrappers_preserve_registers_simd_flags_and_original_prologues(self):
        for hook in self._entries():
            with self.subTest(hook=hook['name']):
                v=VM();site=hook['address'];v.map(site,8)
                v.uc.reg_write(R.UC_ARM64_REG_SP,STACK+0x1e000)
                registers={i:(PARENT if i==0 else STOP if i==30 else 0x50000000+i*0x100)for i in range(31)}
                for i,value in registers.items():v.uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),value)
                for i in range(32):v.uc.reg_write(getattr(R,'UC_ARM64_REG_Q'+str(i)),i*93+31)
                v.uc.reg_write(R.UC_ARM64_REG_NZCV,0xa0000000)
                v.uc.emu_start(CODE+hook['entry_offset'],site+4,count=10000)
                for i,value in registers.items():
                    if i!=16:self.assertEqual(v.reg(i),value,(hook['name'],i))
                for i in range(32):self.assertEqual(v.uc.reg_read(getattr(R,'UC_ARM64_REG_Q'+str(i))),i*93+31)
                self.assertEqual(v.uc.reg_read(R.UC_ARM64_REG_NZCV),0xa0000000)
                delta=0 if hook['name'].endswith('badges_post')else 0x70 if hook['name'].endswith('menu_frame')else 0x50 if hook['name'].endswith(('confirm_button','numbered_badges'))else 0x20
                self.assertEqual(v.uc.reg_read(R.UC_ARM64_REG_SP),STACK+0x1e000-delta)

    def test_owned_window_hides_both_numbered_slots_before_original_binding_only(self):
        v=VM();v.call(1);v.request();v.call(2)
        old,new,oldslot,newslot=DATA+0x81000,DATA+0x82000,DATA+0x83000,DATA+0x84000
        v.write(oldslot+0xc4,'f',1.);v.write(newslot+0xc4,'f',1.)
        looked=[]
        def name():
            at=v.reg(1);text=bytes(v.uc.mem_read(at,16)).split(b'\0')[0]
            self.assertEqual(text,b'NamedSlotCustom');v.write(v.reg(0),'Q',0x777);return 0
        def find():
            self.assertEqual(v.read(v.reg(1),'Q')[0],0x777)
            looked.append(v.reg(0));return {old:oldslot,new:newslot}.get(v.reg(0),0)
        v.stubs.update({0x4414bec:name,0x54f0ce4:find})
        v.call(6,PARENT,event=old,caller=new)
        self.assertEqual(looked,[]);self.assertEqual(v.read(oldslot+0xc4,'f')[0],1.)
        hook=next(h for h in v.profile['extra_entries']if h['name']=='tournament_promotion_numbered_badges')
        v.map(hook['address'],8)
        v.uc.reg_write(R.UC_ARM64_REG_SP,STACK+0x1e000)
        for i,value in enumerate((ACTOR,old,new)):v.uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),value)
        v.uc.reg_write(R.UC_ARM64_REG_X30,STOP)
        v.uc.emu_start(CODE+hook['entry_offset'],hook['address']+4,count=10000)
        self.assertEqual(looked,[old,new]);self.assertEqual(v.read(oldslot+0xc4,'f')[0],0.)
        self.assertEqual(v.read(newslot+0xc4,'f')[0],0.)
        # Even if binding resets a slot's opacity, the verified return point
        # masks it again before the native initialization can fade in.
        v.write(oldslot+0xc4,'f',1.);v.write(newslot+0xc4,'f',1.)
        post=next(h for h in v.profile['extra_entries']if h['name']=='tournament_promotion_numbered_badges_post')
        v.map(0x333fd10,4);v.uc.reg_write(R.UC_ARM64_REG_SP,STACK+0x1e000)
        for i,value in ((19,ACTOR),(20,old),(21,new),(30,0x333fd10)):v.uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),value)
        v.uc.emu_start(CODE+post['entry_offset'],0x333fd10,count=10000)
        self.assertEqual(v.read(oldslot+0xc4,'f')[0],0.);self.assertEqual(v.read(newslot+0xc4,'f')[0],0.)

    @staticmethod
    def _entries():return [h for h in json.loads(PROFILE.read_text('utf8'))['extra_entries']if h['name'].startswith('tournament_promotion_')]

if __name__=='__main__':unittest.main()
