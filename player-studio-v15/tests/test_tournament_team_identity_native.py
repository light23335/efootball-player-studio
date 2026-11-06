"""Scoped special-plan identity override; execute emitted AArch64 and consumer."""
import copy,hashlib,json,os,struct,unittest
from pathlib import Path
from functools import lru_cache
import tournament_home as home

ROOT=Path(__file__).resolve().parents[1]
PROFILE=Path(os.environ.get('STUDIO_TEST_HOME_PROFILE',ROOT/'resources/tournament_schedule_ui/native-home.json'))

@lru_cache(maxsize=1)
def engine():
    raw=(ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    return raw

def probe(event=205060988,team=54,rental=54,ready=1,seq=2,count=1,race=False,old=7,consumer=False,raw_field=False,rows=None):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    import unicorn.arm64_const as R
    p=json.loads(PROFILE.read_text('utf8'));body=bytearray.fromhex(p['body_hex'])
    entry=next(e for e in p['extra_entries']if e['name']=='tournament_own_team_identity')
    code,bus,sp,obj,bank=0x200000,0x300000,0x4f0000,0x600000,0x610000
    native_event=0x7b7b478;resume=0x77f2c5c;stop=0x77f2d34
    for at,target in p['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    for at,size in p['writable_fixups']:struct.pack_into('<Q',body,at,bus)
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,size in ((code,0x10000),(bus,0x30000),(0x4d0000,0x30000),(obj,0x20000),
                    (native_event&~4095,4096),(0x77f2000,4096)):
        u.mem_map(at,size)
    u.mem_write(code,bytes(body));u.mem_write(0x77f2000,engine()[0x77ee000:0x77ef000])
    for at in (0x823c9d4,0x7a81db0,0x7a81858,0x82b4a74,0x82b4a7c,0x2f9f3dc,0x7a81864,0x7a818c4,0x2f376d4,0x7a81924):
        page=at&~4095
        try:u.mem_map(page,4096)
        except Exception:pass
    # The genuine parser-side setter stores a native team key (ID << 14),
    # not a bare JSON ID. The old probe inserted a bare ID and hid the bug.
    u.mem_write(0x7a81000,engine()[0x7a7d000:0x7a7e000])
    setter_stop=code+len(body)+32
    u.reg_write(R.UC_ARM64_REG_X0,sp+0x30);u.reg_write(R.UC_ARM64_REG_W1,rental)
    u.reg_write(R.UC_ARM64_REG_X30,setter_stop)
    u.emu_start(0x7a81db4,setter_stop,count=100)
    stored=struct.unpack('<I',u.mem_read(sp+0x30+0xc64,4))[0]
    assert stored==(rental<<14 if rental<2**18 else 0xffffffff)
    if raw_field:u.mem_write(sp+0x30+0xc64,struct.pack('<I',rental))
    texts={key:''for key in home.TEXTS};texts.update(rental_team_id=team,rental_emblem_ids=[])
    u.mem_write(bus,struct.pack('<III',ready,count,seq));u.mem_write(bus+64,bytes(home.encode(rows or{205060988:texts})))
    u.mem_write(obj,struct.pack('<I',event))
    u.mem_write(bank,struct.pack('<I',(team<<14)&0xffffffff));u.mem_write(bank+0x3fc,struct.pack('<I',0x400))
    registers={i:0x700000+i*0x100 for i in range(31)};registers[19]=old<<14
    for i,v in registers.items():u.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),v)
    for i in range(32):u.reg_write(getattr(R,'UC_ARM64_REG_Q'+str(i)),i*71+91)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_NZCV,0xa0000000)
    calls=[];stopped=[];applied={}
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
    barriers=[i.address for i in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(bytes(body[entry['entry_offset']:]),code+entry['entry_offset'])if i.mnemonic=='dmb']
    def callback(u,at,size,_):
        if at==native_event:
            for i in range(18):u.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),0x800000+i)
            u.reg_write(R.UC_ARM64_REG_X0,obj)
        elif at==resume:
            if not consumer:stopped.append(True);u.emu_stop();return
            calls.append(('identity_lookup',u.reg_read(R.UC_ARM64_REG_X20)))
            return
        elif at==stop:stopped.append(True);u.emu_stop();return
        elif at==0x823c9d4:
            requested=u.reg_read(R.UC_ARM64_REG_X1)
            calls.append(('native_team_bank',requested))
            u.mem_write(bank,struct.pack('<I',requested));u.reg_write(R.UC_ARM64_REG_X0,bank)
        elif at==0x7a81db0:u.reg_write(R.UC_ARM64_REG_X0,sp+0x30)
        elif at==0x7a81858:applied['team_id']=u.reg_read(R.UC_ARM64_REG_W8)
        elif at in (0x82b4a74,0x82b4a7c):
            u.reg_write(R.UC_ARM64_REG_X0,obj+0x100)
        elif at==0x2f9f3dc:pass
        elif at in (0x7a81864,0x7a818c4):
            calls.append(('native_name_binding',u.reg_read(R.UC_ARM64_REG_W1)))
        elif at in (0x2f376d4,0x7a81924):pass
        elif race and at==barriers[0]:u.mem_write(bus+8,struct.pack('<I',4));return
        else:return
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    u.hook_add(UC_HOOK_CODE,callback);u.emu_start(code+entry['entry_offset'],code+len(body),count=50000)
    assert stopped
    if not consumer:
        assert u.reg_read(R.UC_ARM64_REG_SP)==sp
        for i,v in registers.items():
            if i in(16,19,20):continue
            assert u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(i)))==v,('GPR',i)
        for i in range(32):assert u.reg_read(getattr(R,'UC_ARM64_REG_Q'+str(i)))==i*71+91
        assert u.reg_read(R.UC_ARM64_REG_NZCV)==0xa0000000
    return u.reg_read(R.UC_ARM64_REG_X19)>>14,u.reg_read(R.UC_ARM64_REG_X20)>>14,calls,applied

class TeamIdentityNativeTests(unittest.TestCase):
    def test_native_team_identity_overrides_ordinary_club_only_for_matching_event_and_rental(self):
        for team in (54,49206,20,81956,7,108):
            self.assertEqual(probe(team=team,rental=team)[:2],(team,team))

    def test_other_modes_mismatch_incomplete_or_raced_snapshots_keep_native_identity(self):
        for options in ({'event':1120005},{'rental':108},{'ready':0},{'seq':3},{'count':0},{'count':33},{'race':True},{'rental':0},{'raw_field':True},{'team':2**18,'rental':2**18}):
            with self.subTest(options=options):self.assertEqual(probe(**options)[:2],(7,7))

    def test_original_consumer_uses_china_bank_and_name_bindings_after_hook(self):
        for team in(54,49206,20,81956):
            result=probe(team=team,rental=team,consumer=True)
            self.assertIn(('native_team_bank',team<<14),result[2])
            self.assertEqual([v for k,v in result[2]if k=='native_name_binding'],[team,team])

    def test_event_switch_and_home_away_labels_keep_selected_identity_then_exit_restores_ordinary(self):
        def row(team,home_text,away_text):
            r={k:''for k in home.TEXTS};r.update(rental_team_id=team,rental_emblem_ids=[],home=home_text,away=away_text)
            return r
        rows={205060988:row(54,'中国','西班牙'),205060989:row(49206,'日本','中国')}
        for event,team in((205060988,54),(205060989,49206)):
            self.assertEqual(probe(event=event,team=team,rental=team,count=2,rows=rows,consumer=True)[:2],(team,team))
        self.assertEqual(probe(event=1120005,team=54,rental=54,count=2,rows=rows)[:2],(7,7))
        self.assertEqual(probe(event=205060989,team=54,rental=54,count=2,rows=rows)[:2],(7,7))

if __name__=='__main__':unittest.main()
