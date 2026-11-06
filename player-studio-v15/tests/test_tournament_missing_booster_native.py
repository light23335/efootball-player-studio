"""Original V17 absent-booster lookup returns a constructed zero-effect record.

The bank storage contains explicit native records 87 and 258. Constructor,
binary search, exact-ID check, fallback selection, setters and all 26 ability
getters execute unchanged. No native function result is mocked. A final signed
APK audit can pass its engine bytes to native_booster_lookup_probe().
"""
import hashlib
import mmap
import struct
import unittest
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ENGINE_SHA256='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'


@lru_cache(maxsize=1)
def _engine():
    with (ROOT/'.work/xi-v17-gameplay-compare/v17-engine.so').open('rb')as source:
        return mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ)


def native_booster_lookup_probe(query_ids=(257,87),*,engine_bytes=None):
    """Run original lookup and getters over a native bank with a gap at 257.

    engine_bytes accepts the original engine bytes extracted from the signed
    APK. The engine fingerprint is checked before executing any instruction.
    Explicit fixtures supply bank memory and the loader's invalid-ID constant;
    the default record is first poisoned and initialized by its real constructor.
    """
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=_engine()if engine_bytes is None else engine_bytes
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=ENGINE_SHA256:raise ValueError('Missing-booster probe requires the verified original V17 engine')
    if any(type(bid)is not int or not 0<=bid<1024 for bid in query_ids):
        raise ValueError('Native booster IDs must be unsigned ten-bit integers')
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x100000,0x100000)

    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096)
        offset=page if page<0x2e00000 else page-0x4000
        if 0<=offset<len(raw):u.mem_write(page,raw[offset:offset+4096])
        return True

    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)

    def put(address,fmt,*values):u.mem_write(address,struct.pack(fmt,*values))
    def read(address,fmt):return struct.unpack(fmt,u.mem_read(address,struct.calcsize(fmt)))
    def mapped(address,size):
        for page in range(address&~4095,(address+size+4095)&~4095,4096):
            try:u.mem_map(page,4096)
            except Exception:pass

    u.reg_write(R.UC_ARM64_REG_SP,0x1f0000)
    u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x170000)
    stop=0x150000
    memory(u,0,0x99e6000,0,0,None)
    put(0x99e6850,'<Q',0x140000);put(0x140000,'<I',0xffffffff)

    def call(address,x0,w1=0,x2=0):
        u.reg_write(R.UC_ARM64_REG_X0,x0)
        u.reg_write(R.UC_ARM64_REG_W1,w1)
        u.reg_write(R.UC_ARM64_REG_X2,x2)
        u.reg_write(R.UC_ARM64_REG_X30,stop)
        u.emu_start(address,stop,count=20000)
        if u.reg_read(R.UC_ARM64_REG_PC)!=stop:
            raise AssertionError('Native booster probe did not return from '+hex(address))
        return u.reg_read(R.UC_ARM64_REG_X0)

    bank=0x1000000;fallback=bank+0x2685fbc;table=bank+0x30f18f4
    mapped(fallback,36);mapped(table,72);mapped(bank+0x30f8974,4)
    # This is the real bank's default-record constructor, not a zero fixture.
    u.mem_write(fallback,b'\xa5'*36)
    call(0x8239794,fallback)
    constructed_effect_bytes=bytes(u.mem_read(fallback,20))
    for i,bid in enumerate((87,258)):
        address=table+i*36;u.mem_write(address,b'\xa5'*36)
        call(0x8239794,address);call(0x82acf20,address,bid)
    call(0x82adc7c,table,0,2)  # Native setter: first ability +2 on record 87.
    put(bank+0x30f8974,'<I',2)
    rows=[]
    for bid in query_ids:
        pointer=call(0x823dfe4,bank,bid);values=[]
        native_id=call(0x82acf14,pointer)
        for i in range(26):
            call(0x82ad9a4,pointer,i,0x180000)
            values.append(read(0x180000,'<I')[0])
        rows.append(dict(booster_id=bid,returned_fallback=pointer==fallback,
                         native_record_id=native_id,effects=values))
    return dict(engine_sha256=digest,rows=rows,bank_fixture_ids=[87,258],
                constructed_effect_bytes=constructed_effect_bytes.hex(),
                native_default_constructor=0x8239794,native_lookup=0x823dfe4,
                native_search=0x823e040,native_ability_getter=0x82ad9a4,
                instruction_results_mocked=False,device_validated=False)


class MissingBoosterNativeTests(unittest.TestCase):
    def test_missing_ids_use_original_constructed_zero_record_for_all_26_effects(self):
        result=native_booster_lookup_probe((0,257,1023))
        self.assertEqual(result['constructed_effect_bytes'],'00'*20)
        self.assertFalse(result['instruction_results_mocked'])
        for row in result['rows']:
            with self.subTest(booster=row['booster_id']):
                self.assertTrue(row['returned_fallback'])
                self.assertEqual(row['native_record_id'],0)
                self.assertEqual(row['effects'],[0]*26)

    def test_present_87_control_keeps_native_lookup_and_positive_effect(self):
        result=native_booster_lookup_probe((87,))
        row=result['rows'][0]
        self.assertFalse(row['returned_fallback'])
        self.assertEqual(row['native_record_id'],87)
        self.assertEqual(row['effects'],[2]+[0]*25)


if __name__=='__main__':unittest.main()
