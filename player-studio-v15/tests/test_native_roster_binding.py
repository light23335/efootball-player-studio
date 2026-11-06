"""Execute original roster getters, rather than stubbing their return values."""
import json,struct,unittest
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X30,UC_ARM64_REG_SP

RESOURCE=Path(__file__).resolve().parents[1]/'resources/native-ai-match-adapter.json'


class RosterBindingTests(unittest.TestCase):
    def test_original_getter_resolves_both_native_rosters_and_identities(self):
        data=json.loads(RESOURCE.read_text('utf8'))
        targets={address for _,address in data['absolute_fixups']}
        self.assertIn(0x72c404c,targets);self.assertNotIn(0x72c19dc,targets)
        probes={r['address']:bytes.fromhex(r['expected_hex'])for r in data['native_import_probes']}
        addresses=(0x72c19dc,0x69922e8,0x68fb5fc,0x72f2d04,0x72f2ca8,0x72f29e0,0x72f3174,0x6905d9c)
        vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        for page in sorted({address&~4095 for address in addresses}):vm.mem_map(page,4096)
        for address in addresses:vm.mem_write(address,probes[address])
        root,home,away,dummy,stop=0x20000000,0x21000000,0x21010000,0x22000000,0x30000000
        for address,size in((root,0x10000),(home,0x5000),(away,0x5000),(dummy,0x5000),(stop,4096)):
            vm.mem_map(address,size)
        vm.mem_map(0x31000000,0x10000);vm.reg_write(UC_ARM64_REG_SP,0x3100f000)
        def put(at,fmt,*values):vm.mem_write(at,struct.pack(fmt,*values))
        def call(address,*args):
            for reg,value in zip((UC_ARM64_REG_X0,UC_ARM64_REG_X1),args):vm.reg_write(reg,value)
            vm.reg_write(UC_ARM64_REG_X30,stop);vm.emu_start(address,stop,count=1000)
            return vm.reg_read(UC_ARM64_REG_X0),vm.reg_read(UC_ARM64_REG_X1)
        for side,players in enumerate((home,away)):
            put(root+0x30d0+side*0x50,'<Q',players)
            # This is a global query fixture, not a coaching callback root.
            put(root+0x3630+side*0x50,'<Q',dummy)
            put(dummy+0x406c,'<I',16384)
            put(players+0x406c,'<I',23)
            for i in range(23):
                physical=(i+7)%23;put(players+4+i*4,'<I',physical)
                put(players+0xa8+physical*0x198+0x30,'<IIQ',0xfffffffe if side else 0xfffffffd,0xa5a5a5a5,1000+side*100+i)
            actual,_=call(0x72c19dc,root,side);self.assertEqual(actual,players)
            self.assertEqual(call(0x68fb5fc,actual)[0],23)
            for i in(0,10,11,22):
                entry,_=call(0x72f2d04,actual,i)
                serial,cid=call(0x72f29e0,entry)
                self.assertEqual(serial&0xffffffff,0xfffffffe if side else 0xfffffffd)
                self.assertEqual(cid,1000+side*100+i)

    def test_original_coach_initializer_uses_its_callback_roster_not_global_getter(self):
        data=json.loads(RESOURCE.read_text('utf8'))
        probes={r['address']:bytes.fromhex(r['expected_hex'])for r in data['native_import_probes']}
        addresses=(0x6ce2d94,0x72c404c,0x72c19dc,0x72c3f2c,0x69922e8,0x68fb5fc)
        vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        for page in sorted({at&~4095 for at in addresses}):vm.mem_map(page,4096)
        for at in addresses:vm.mem_write(at,probes[at])
        callback,global_root,players,dummy,self_at,team,stack,stop=(0x20000000,0x20010000,0x21000000,
            0x21010000,0x22000000,0x22010000,0x30000000,0x31000000)
        for at,size in ((callback,0x10000),(global_root,0x10000),(players,0x5000),(dummy,0x5000),
                        (self_at,4096),(team,4096),(stack,0x10000),(stop,4096)):vm.mem_map(at,size)
        def put(at,fmt,*values):vm.mem_write(at,struct.pack(fmt,*values))
        put(self_at+8,'<I',1)
        put(callback+0x3620+0x50+0x10,'<Q',players)
        put(callback+0x30c0+0x50+0x10,'<Q',dummy)
        put(global_root+0x30c0+0x50+0x10,'<Q',players)
        put(players+0x406c,'<I',23);put(dummy+0x406c,'<I',16384)
        def frame_input(uc,at,size,_):
            if at==0x72c3f2c:
                uc.reg_write(UC_ARM64_REG_X0,0)
                from unicorn.arm64_const import UC_ARM64_REG_PC
                uc.reg_write(UC_ARM64_REG_PC,uc.reg_read(UC_ARM64_REG_X30))
        vm.hook_add(UC_HOOK_CODE,frame_input)
        vm.reg_write(UC_ARM64_REG_SP,stack+0xf000)
        for reg,value in ((UC_ARM64_REG_X0,self_at),(UC_ARM64_REG_X1,team),(UC_ARM64_REG_X2,callback)):
            vm.reg_write(reg,value)
        vm.emu_start(0x6ce2d94,0x6ce2dd0,count=500)
        self.assertEqual(vm.reg_read(UC_ARM64_REG_X0),players)
        self.assertEqual(struct.unpack('<QQ',vm.mem_read(self_at+0x370,16)),(callback,team))
        for root,expected in ((global_root,players),(callback,dummy)):
            vm.reg_write(UC_ARM64_REG_X0,root);vm.reg_write(UC_ARM64_REG_X1,1);vm.reg_write(UC_ARM64_REG_X30,stop)
            vm.emu_start(0x72c19dc,stop,count=500)
            self.assertEqual(vm.reg_read(UC_ARM64_REG_X0),expected)


if __name__=='__main__':unittest.main()
