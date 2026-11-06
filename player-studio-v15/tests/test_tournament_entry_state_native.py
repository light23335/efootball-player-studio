"""Original status enum construction, DTO conversion and fresh-entry branches."""
import struct
import unittest
from pathlib import Path
from test_tournament_team_identity_native import engine


def entry_probe(status):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=engine();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x100000,0x200000)
    def put(at,fmt,*v):u.mem_write(at,struct.pack(fmt,*v))
    def rd(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096);off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    def sso(at,value):
        b=value.encode();u.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
    def text(at):
        n=rd(at,'<B')[0]//2;return bytes(u.mem_read(at+1,n)).decode()
    memory(u,0,0xa5a5000,0,0,None);memory(u,0,0xa5a6000,0,0,None)
    put(0xa5a5290,'<B',1)
    u.reg_write(R.UC_ARM64_REG_SP,0x2f0000);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x1f0000)
    # Execute the actual short-string initializers and ordinal stores.
    u.emu_start(0x761cd00,0x761ce20,count=1000)
    enums=[text(0xa5a6b80+i*24)for i in range(3)]
    ordinals=[rd(0xa5a5688+i*4,'<I')[0]for i in range(3)]
    dto,out,ev,flags,count=0x110000,0x120000,0x130000,0x140000,0x140010
    put(dto,'<I',205060988);sso(dto+8,status)
    branches=[];calls=[];stop=0x150000
    def ret(v=None):
        if v is not None:u.reg_write(R.UC_ARM64_REG_X0,v)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def cb(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if at==0x8c1bca0:ret(len(bytes(u.mem_read(x(0),128)).split(b'\0')[0]))
        elif at==0x2f3877c:sso(x(0),bytes(u.mem_read(x(1),x(2))).decode());ret(x(0))
        elif at==0x8c1c1f0:ret(0 if bytes(u.mem_read(x(0),x(2)))==bytes(u.mem_read(x(1),x(2)))else 1)
        elif at in(0x2f49320,0x2f376d4):ret()
        elif at in(0x812a420,0x812a4ac):branches.append(hex(at));u.emu_stop()
        elif at in(0x82262b0,0x7a3e2b4):ret(0x180000)
        elif at==0x82289e0:ret(1)
        elif at==0x7a41d64:ret(ev)
        elif at==0x7b7b864:ret(0)
        elif at in(0x7b7cbc8,):ret(0)
        elif at in(0x7a81758,0x7babf1c,0x7b824e0):calls.append(hex(at))
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,cb)
    u.reg_write(R.UC_ARM64_REG_X0,out);u.reg_write(R.UC_ARM64_REG_X1,dto)
    u.emu_start(0x769ca34,0x769cbd4,count=5000)
    converted=rd(out+4,'<I')[0]
    # First branch of the actual native event-entry task.
    put(ev,'<I',205060988);put(ev+0x20bc,'<I',converted)
    u.reg_write(R.UC_ARM64_REG_X21,ev)
    u.emu_start(0x812a3ec,0x812a4b0,count=500)
    # Fresh-entry selection counts the permitted entities; it does not inspect
    # or validate the user's ordinary 23-player squad at this stage.
    put(ev+0x38,'<I',2);put(ev+0x3d,'<B',1);put(ev+0x60,'<I',4)
    put(ev+0x68,'<QQ',0x160000,0x160004);put(0x160000,'<I',7)
    u.reg_write(R.UC_ARM64_REG_SP,0x2f0000);u.reg_write(R.UC_ARM64_REG_X0,205060988)
    u.reg_write(R.UC_ARM64_REG_X1,flags);u.reg_write(R.UC_ARM64_REG_X2,count);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x7b85a48,stop,count=3000)
    return dict(enums=enums,ordinals=ordinals,converted=converted,branches=branches,
                selection_required=u.reg_read(R.UC_ARM64_REG_W0),entity_count=rd(count,'<I')[0],squad_checks=calls)


class EntryStateNativeTests(unittest.TestCase):
    def test_original_enum_and_converter_distinguish_unentered_entered_and_cleared(self):
        for ordinal,status in enumerate(('NO_ENTRY','ENTRY','CLEARED')):
            out=entry_probe(status)
            self.assertEqual(out['enums'],['NO_ENTRY','ENTRY','CLEARED'])
            self.assertEqual(out['ordinals'],[0,1,2])
            self.assertEqual(out['converted'],ordinal)
            self.assertEqual(out['branches'],['0x812a420'if ordinal==0 else'0x812a4ac'])

    def test_fresh_challenge_uses_one_explicit_entity_without_validating_ordinary_squad(self):
        out=entry_probe('NO_ENTRY')
        self.assertEqual((out['selection_required'],out['entity_count']),(1,1))
        self.assertEqual(out['squad_checks'],[])
        self.assertEqual(entry_probe('ENTRY')['selection_required'],0)


if __name__=='__main__':unittest.main()
