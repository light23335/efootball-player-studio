"""Run the emitted hook AND the original native League interval predicate."""
import hashlib,json,struct,unittest
from pathlib import Path
import league_availability as availability
from tournament_home import SCHEMA,Channel,encode

PROFILE=Path(__file__).resolve().parents[1]/'resources/tournament_schedule_ui/native-home.json'
NOW=1793872800
OPENING=1791424800
EXPIRED=1793843999


def native_probe(*,now=NOW,start=OPENING,end=EXPIRED,enabled=True,seq=2,magic=None,duration=None,caller=0x37c7190,top_support=None):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    import unicorn.arm64_const as regs
    p=json.loads(PROFILE.read_text('utf8'));body=bytearray.fromhex(p['body_hex'])
    assert hashlib.sha256(body).hexdigest()==p['body_sha256']
    row=next(r for r in p['extra_entries']if r['name']=='original_league_native_availability')
    original=next(r for r in p['native_probes']if r['name']=='original-league-availability-predicate')
    address=0x74a4ad0;clock=0x7eb4288;code=0x200000;control=0x300000;model=0x400000;stack=0x5f0000;done=caller
    for at,target in p['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    for at,size in p['writable_fixups']:struct.pack_into('<Q',body,at,control)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,size in ((code,0x10000),(control,0x30000),(model,0x1000),(0x5d0000,0x30000),
                    (done&~4095,0x1000),(address&~4095,0x2000),(clock&~4095,0x1000)):uc.mem_map(at,size)
    uc.mem_write(code,bytes(body));uc.mem_write(address,bytes.fromhex(original['expected_hex']))
    start_pc=code+row['entry_offset'];blocked=None
    if top_support is not None:
        # Execute the original TopMatch support predicate, capability lookup,
        # model getter and BL, with a fixture for native world/global state.
        probes={v['name']:v for v in p['native_probes']}
        for page in (0x38c8000,0x74f1000,0x7b0a000,0xc9f000,0xa5c6000,0x410000,0x420000,0x421000,0x430000):
            uc.mem_map(page,0x1000)
        for name,where in (('original-league-topmatch-support-thunk',0x38c8280),
                           ('original-league-topmatch-support-adapter',0x74f1ee0),
                           ('original-league-topmatch-support-predicate',0x7b0a62c),
                           ('original-league-topmatch-support-table',0xc9f944),
                           ('original-league-topmatch-model-getter',0x302b6d4)):
            if name.endswith('model-getter'):uc.mem_map(where&~4095,0x1000)
            uc.mem_write(where,bytes.fromhex(probes[name]['expected_hex']))
        table=bytes.fromhex(probes['original-league-topmatch-support-table']['expected_hex'])
        states=[]
        for index in range(56):
            displacement=struct.unpack_from('<i',table,0x2ac+index*4)[0]
            location=0x2ac+displacement
            if 0<=location+10<len(table)and bool(table[location+10])==top_support:states.append(index+1)
        assert states,'Original support table has no requested capability'
        uc.mem_write(0xa5c6e10,struct.pack('<Q',0x410000))
        uc.mem_write(0x410070,struct.pack('<I',states[0]))
        uc.mem_write(0x421180,struct.pack('<Q',model))
        uc.mem_write(0x37c7170,bytes.fromhex(probes['original-league-topmatch-gate-call']['expected_hex']))
        branch=0x14000000|(((start_pc-address)//4)&0x3ffffff)
        uc.mem_write(address,struct.pack('<I',branch));start_pc=0x37c7170;blocked=0x37c82fc
        uc.mem_map(blocked&~4095,0x1000)
    before=bytearray([0x53])*256;struct.pack_into('<QQ',before,0x60,start,end);uc.mem_write(model,bytes(before))
    buffer=bytearray(SCHEMA['bytes']);channel=Channel(buffer,0,lambda:None)
    if enabled:
        availability._publish_native(channel,{'start':NOW,'end':NOW+(duration or availability.DURATION)})
        struct.pack_into('<II',buffer,40,seq,availability.NATIVE_MAGIC if magic is None else magic)
    # Clearing/rebuilding tournament rows must preserve the League lease.
    snapshot=bytes(buffer[40:64]);channel.publish(encode({}),0)
    assert bytes(buffer[40:64])==snapshot;uc.mem_write(control,bytes(buffer))
    registers={i:0x780000+i*91 for i in range(1,30)}
    for i,value in registers.items():uc.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
    if top_support is not None:
        registers[19]=0x430000;registers[20]=0x420000
        uc.reg_write(regs.UC_ARM64_REG_X19,registers[19]);uc.reg_write(regs.UC_ARM64_REG_X20,registers[20])
    uc.reg_write(regs.UC_ARM64_REG_X0,model);uc.reg_write(regs.UC_ARM64_REG_X30,done)
    uc.reg_write(regs.UC_ARM64_REG_SP,stack)
    stopped=[]
    def callback(u,at,size,data):
        if at==clock:
            u.reg_write(regs.UC_ARM64_REG_X0,now)
            u.reg_write(regs.UC_ARM64_REG_PC,u.reg_read(regs.UC_ARM64_REG_X30))
        elif at==done or at==blocked:stopped.append(at);u.emu_stop()
    uc.hook_add(UC_HOOK_CODE,callback)
    uc.emu_start(start_pc,0,count=100000)
    assert stopped and uc.reg_read(regs.UC_ARM64_REG_SP)==stack
    for i in range(19,30):assert uc.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(i)))==registers[i]
    after=bytes(uc.mem_read(model,256))
    assert after[:0x60]==before[:0x60]and after[0x70:]==before[0x70:]
    return uc.reg_read(regs.UC_ARM64_REG_W0),struct.unpack_from('<QQ',after,0x60)


class OriginalNativeLeagueAvailabilityTests(unittest.TestCase):
    def test_original_deadline_reproduces_user_date_dependency(self):
        self.assertEqual(native_probe(enabled=False)[0],0)
        self.assertEqual(native_probe(enabled=False,now=1793491200)[0],1)  # November 1 UTC.

    def test_old_cached_model_is_refreshed_then_original_predicate_accepts_today(self):
        result,dates=native_probe();self.assertEqual(result,1)
        self.assertEqual(dates,(OPENING,NOW+availability.DURATION))

    def test_original_opening_and_both_inclusive_native_boundaries_are_preserved(self):
        for now,wanted in ((OPENING-1,0),(OPENING,1),(NOW+availability.DURATION,1),
                           (NOW+availability.DURATION+1,0)):
            with self.subTest(now=now):self.assertEqual(native_probe(now=now)[0],wanted)

    def test_unpublished_torn_foreign_or_wrong_duration_lease_keeps_original_behavior(self):
        for options in ({'enabled':False},{'seq':0},{'seq':3},{'magic':0},{'duration':12345}):
            with self.subTest(options=options):
                self.assertEqual(native_probe(**options),(0,(OPENING,EXPIRED)))

    def test_uninitialized_native_cache_remains_unavailable(self):
        for start,end in ((0,0),(0,EXPIRED),(OPENING,0)):
            with self.subTest(start=start,end=end):
                self.assertEqual(native_probe(start=start,end=end),(0,(start,end)))

    def test_support_gate_and_global_clock_are_not_hooked(self):
        p=json.loads(PROFILE.read_text('utf8'))
        sites={r['address']for r in p['extra_entries']}|{p['address']}
        self.assertNotIn(0x38c8280,sites);self.assertNotIn(0x37c7170,sites)
        self.assertNotIn(0x7eb4288,sites);self.assertNotIn(0x74a4b20,sites)

    def test_other_callers_keep_native_model_and_original_expiry_result(self):
        for caller in (0x600000,0x37c7194,0x37c718c):
            with self.subTest(caller=caller):
                self.assertEqual(native_probe(caller=caller),(0,(OPENING,EXPIRED)))

    def test_actual_topmatch_support_allows_league_cache_sync_and_still_blocks_unsupported_flow(self):
        self.assertEqual(native_probe(top_support=True),(1,(OPENING,NOW+availability.DURATION)))
        self.assertEqual(native_probe(top_support=False),(0,(OPENING,EXPIRED)))


if __name__=='__main__':unittest.main()
