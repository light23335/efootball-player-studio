"""Original native TeamID variant and uniform-path resolution, no renderer."""
from functools import lru_cache
from pathlib import Path
import hashlib,struct,unittest

ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=1)
def engine():
    b=(ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
    assert hashlib.sha256(b).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    return b

def native_uniform_probe(team,slot=0,real=True):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);b=engine();u.mem_map(0x100000,0x400000)
    sp=0x4f0000;stop=0x110000;out=0x120000;heap=[0x200000]
    def memory(_u,access,address,size,value,data):
        p=address&~4095;u.mem_map(p,4096)
        delta=0x8000 if p>=0x8c5b000 else 0x4000 if p>=0x2866000 else 0
        off=p-delta
        if 0<=off<len(b):u.mem_write(p,b[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    # Actual Android RELATIVE relocation values for these constant tables,
    # validated against the immutable ELF's decoded APS2 relocation stream.
    tables={0x98901a0:[0xa36d02,0xa2405d,0x9ea958,0xb67998,0xabbff2,0xb2ef7b],
            0x98901d0:[0xa8a233,0xb08664],
            0x98901e0:[0xbb4841,0xb67994,0xb2ef77,0xabbff7,0xa5c10b,0xabbffb,0xae23bb,0xb4237e,0xc28946]}
    memory(u,0,0x9890000,0,0,None)
    for at,values in tables.items():u.mem_write(at,struct.pack('<'+'Q'*len(values),*values))
    def rd(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    def alloc(n):p=heap[0];heap[0]+=(n+31)&~31;return p
    def string(at):
        flag=rd(at,'<B')[0]
        if flag&1:n,p=rd(at+8,'<QQ');return bytes(u.mem_read(p,n))
        return bytes(u.mem_read(at+1,flag>>1))
    def sso(at,value):
        if len(value)<=22:u.mem_write(at,bytes([len(value)*2])+value+b'\0'+bytes(22-len(value)))
        else:
            p=alloc(len(value)+1);u.mem_write(p,value+b'\0');u.mem_write(at,struct.pack('<QQQ',(len(value)+2)|1,len(value),p))
    def ret(v=None):
        if v is not None:u.reg_write(R.UC_ARM64_REG_X0,v)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def readmem(at,n):
        for page in range(at&~4095,(at+n+4095)&~4095,4096):
            try:u.mem_read(page,1)
            except Exception:memory(u,0,page,0,0,None)
        return bytes(u.mem_read(at,n))
    def cstr(at):return readmem(at,256).split(b'\0')[0]
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if at==0x82468d4:ret(0) # No master-bank initialization claimed; exercise original path fallback.
        elif at==0x8c1bca0:ret(len(cstr(x(0))))
        elif at==0x2f51de8:
            assert cstr(x(2))in(b'%d',b'%u')
            value=str(x(3)).encode();u.mem_write(x(0),value+b'\0');ret(len(value))
        elif at in(0x2f3877c,0x2f4f724):
            value=readmem(x(1),x(2))
            if at==0x2f4f724:value=string(x(0))+value
            sso(x(0),value);ret(x(0))
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x130000)
    def call(at,value):
        u.reg_write(R.UC_ARM64_REG_W0,value);u.reg_write(R.UC_ARM64_REG_X30,stop)
        u.emu_start(at,stop,count=1000);assert u.reg_read(R.UC_ARM64_REG_PC)==stop
        return u.reg_read(R.UC_ARM64_REG_W0)
    base=call(0x82446d8,team);variant=call(0x8244740,team)
    u.reg_write(R.UC_ARM64_REG_W0,(team<<14)|slot);u.reg_write(R.UC_ARM64_REG_W1,int(real))
    u.reg_write(R.UC_ARM64_REG_X8,out);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x68e6b38,stop,count=5000);assert u.reg_read(R.UC_ARM64_REG_PC)==stop
    return {'team_id':team,'base_team':base,'variant':variant,'native_uniform_key':(team<<14)|slot,
            'path':string(out).decode()}

class NativeUniformPathTests(unittest.TestCase):
    def test_china_base_and_world_cup_variant_use_actual_distinct_native_paths(self):
        self.assertEqual(native_uniform_probe(54)['path'],'cpk_dat/common/etc/uniform/team/54/54_DEF_1st_realUni.bin')
        self.assertEqual(native_uniform_probe(49206)['path'],'cpk_dat/common/etc/uniform/team/54/54_WCA_1st_realUni.bin')
        self.assertEqual(native_uniform_probe(49206,1)['path'],'cpk_dat/common/etc/uniform/team/54/54_WCA_2nd_realUni.bin')
        self.assertEqual(native_uniform_probe(49206,0x80)['path'],'cpk_dat/common/etc/uniform/team/54/54_WCA_GK1st_realUni.bin')
        self.assertEqual(native_uniform_probe(7)['path'],'cpk_dat/common/etc/uniform/team/7/7_DEF_1st_realUni.bin')

    def test_original_variant_decoder_preserves_each_native_variant(self):
        tags=('_DEF_','_ACL_','_ACN_','_WCA_','_AC_','_ANC_')
        for variant,tag in enumerate(tags):
            out=native_uniform_probe(54+(variant<<14))
            self.assertEqual((out['base_team'],out['variant']),(54,variant))
            self.assertIn('/54/54'+tag,out['path'])

if __name__=='__main__':unittest.main()
