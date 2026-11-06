"""Independent entry validation probes over the immutable V17 instructions.

No event/mode/user getter, special-mode predicate, player resolver, registered
counter or main validator result is replaced. The fixture supplies native bank
records and ordinary allocation/copy services; it never launches the client.
"""
import hashlib
import json
import struct
import unittest
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=1)
def engine():
    raw=(ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    return raw

def native_person_key(card_id):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    import unicorn.arm64_const as R
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);page=0x6774000;u.mem_map(page,4096)
    u.mem_write(page,engine()[page-0x4000:page-0x4000+4096]);u.mem_map(0x100000,4096)
    u.mem_write(0x100000,struct.pack('<QQ',0,card_id));u.reg_write(R.UC_ARM64_REG_X0,0x100000)
    u.reg_write(R.UC_ARM64_REG_W1,1);u.reg_write(R.UC_ARM64_REG_X30,0x100100)
    u.emu_start(0x6774f54,0x100100,count=100)
    return u.reg_read(R.UC_ARM64_REG_X0)

def native_icon_type(*,rental=True,alert=False):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    import unicorn.arm64_const as R
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);page=0x3314000;u.mem_map(page,8192)
    u.mem_write(page,engine()[page-0x4000:page-0x4000+8192]);u.mem_map(0x100000,0x10000)
    own=0x100000;row=0x101000;sp=0x10f000;stop=0x102000
    u.mem_write(own+0x64,struct.pack('<I',0xffffffff))
    u.mem_write(row+0x44,bytes([int(rental)]));u.mem_write(row+0x3a,bytes([int(alert)]))
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x103000)
    u.reg_write(R.UC_ARM64_REG_X0,own);u.reg_write(R.UC_ARM64_REG_X1,row);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x3314e78,stop,count=500)
    return u.reg_read(R.UC_ARM64_REG_W0)

def qualify(*,custom_team=True,missing_profile=False,missing_rental=False,unavailable=False,
            duplicate=False,registered=23,resolve_only=False,native_mode=0x2b,
            selected_event=205060988,current_event=205060988,payload=None,name_only=False,
            entity_id=7,entry_type=4,patched_popup=False,popup_team=54,popup_policy=None,
            published_event=205060988,publish_ready=1,publish_sequence=2,race_popup=False,
            received_special_team=None):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);raw=engine();u.mem_map(0x100000,0x700000)
    sp=0x7f0000;stop=0x150000;user=0x600000;event=0x610000;special=user+0x19e0
    context=0x670000;manager=0x680000;ordinary=0x6c0000;heap=[0x200000]
    refs=[(p['gameplayer_id']['id'],p['gameplayer_id'].get('serial',0))for p in payload['squad_data']['player_list']]if payload else[(1000+i,0)for i in range(23)]
    trace=[];profile=0x160000;bank=0x170000;requested_teams=[]
    if duplicate:refs[-1]=refs[0]
    def put(at,fmt,*v):u.mem_write(at,struct.pack(fmt,*v))
    def rd(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    def alloc(n):a=heap[0];heap[0]+=(n+31)&~31;return a
    def sso(at,v):b=v.encode();u.mem_write(at,bytes([2*len(b)])+b+b'\0'+bytes(22-len(b)))
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096);off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    for at in(0xa5bb000,0xa5bd000,0xa5fb000,0x99e6000,0xa5a4000,0xa5a6000):memory(u,0,at,0,0,None)
    put(0xa5bb7c8,'<Q',user);put(0xa5bb7c0,'<Q',0x690000)
    put(0x690000+0x20,'<QQ',event,event+0x3878);put(user+0xb8,'<II',current_event,selected_event)
    put(0xa5bd678,'<Q',context);put(0xa5fb028,'<Q',manager);put(manager,'<B',native_mode)
    put(context+0x28,'<Q',0x6b0000);put(0x6b0000+8,'<Q',ordinary)
    put(ordinary+0x20,'<I4xQQ',0xffffffff,0,0) # Native ordinary cache fallback.
    put(event,'<I',205060988);put(event+0x38,'<I',2);put(event+0x60,'<I',entry_type)
    put(0x6e0000,'<I',entity_id);put(event+0x68,'<QQQ',0x6e0000,0x6e0004,0x6e0004)
    put(0xa5a4f68,'<B',1)
    for at,v in((0xa5a6068,'NO'),(0xa5a6080,'YES'),(0x6d0068,'YES'if custom_team else'NO')):sso(at,v)
    put(0x99e6928,'<Q',0x130000);put(0x130000,'<I4xQQ',0xffffffff,0,0)
    put(0x99e6930,'<Q',0x130020);put(0x130020,'<H6xQQ',0xffff,0,0)
    put(0x99e6850,'<Q',0x130040);put(0x130040,'<I',0xffffffff)
    put(bank+0x40,'<Q',0x180000)
    team=payload['rental_team_id']if payload else 54
    put(special+0xc64,'<I',(team if received_special_team is None else received_special_team)<<14)
    put(special+0x350,'<I',team)
    put(special,'<H6xQQ',0,1,1) # Valid coach reference, supplied separately below.
    u.mem_write(special+0x318,bytes(range(23)))
    for i,(cid,serial)in enumerate(refs):
        put(special+0x18+i*0x18,'<I4xQQ',0 if i<registered else 0xffffffff,cid if i<registered else 0,serial)
    start=0x650000;n=22 if missing_rental else 23
    put(special+0xc68,'<QQQ',start,start+n*0xf0,start+n*0xf0)
    for i,(cid,serial)in enumerate(refs[:n]):
        p=start+i*0xf0;put(p,'<I4xQQ',0,cid,serial);put(p+0x40,'<I',2)
        put(p+0xc4,'<I',1 if unavailable and i==0 else 0);put(p+0xd8,'<II',65590<<14,0)
    code=0x400000;bus=0x500000;body=b''
    if patched_popup:
        import tournament_home as home
        hook=json.loads((ROOT/'resources/tournament_schedule_ui/native-home.json').read_text('utf8'))
        body=bytearray.fromhex(hook['body_hex'])
        for at,target in hook['absolute_fixups']:struct.pack_into('<Q',body,at,target)
        for at,size in hook['writable_fixups']:struct.pack_into('<Q',body,at,bus)
        u.mem_write(code,bytes(body))
        row={k:''for k in home.TEXTS};row.update(rental_team_id=popup_team,rental_emblem_ids=[],
            membership=popup_policy or{'kind':'national','entity_id':7})
        u.mem_write(bus,struct.pack('<III',publish_ready,1,publish_sequence))
        u.mem_write(bus+64,bytes(home.encode({published_event:row})))
        entry=next(e for e in hook['extra_entries']if e['name']=='tournament_entry_popup_team_identity')
        memory(u,0,entry['address'],0,0,None)
        u.mem_write(entry['address'],struct.pack('<I',0x14000000|(((code+entry['entry_offset']-entry['address'])//4)&0x3ffffff)))
    calls=[]
    def ret(v=None):
        if v is not None:u.reg_write(R.UC_ARM64_REG_X0,v)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if at in(0x7babf1c,0x7a81758,0x7baac3c,0x7b7d95c,0x7b806ac,0x7a81ef8,0x7a87eec,0x7bac140):trace.append(hex(at))
        if at in(0x2f37644,0x8c1bbd0):ret(alloc(x(0)))
        elif at in(0x2f376d4,0x2ff85e8,0x82a84c0,0x82a907c,0x321beb8):ret()
        elif at==0x6774740:ret(0)
        elif at==0x8c1bc70:
            u.mem_write(x(0),bytes(u.mem_read(x(1),x(2))));ret(x(0))
        elif at==0x8c1bc80:ret(1) # libc++ one-time initialization guard.
        elif at==0x8c1bc90:put(x(0),'<B',1);ret()
        elif at==0x8c1bca0:ret(len(bytes(u.mem_read(x(0),128)).split(b'\0')[0]))
        elif at==0x8c1c1f0:ret(0 if bytes(u.mem_read(x(0),x(2)))==bytes(u.mem_read(x(1),x(2)))else 1)
        elif at==0x82468d4:ret(bank)
        elif at==0x823c9d4:
            requested_teams.append(x(1));put(0x1c0000,'<I',x(1));ret(0x1c0000)
        elif at==0x82b4a74:
            cid=rd(x(0),'<I')[0]>>14;s={7:'Spain',54:'China',49206:'China alias'}.get(cid,'Team '+str(cid))
            u.mem_write(0x1c1000,s.encode()+b'\0');ret(0x1c1000)
        elif at==0x2f46d10:
            s=bytes(u.mem_read(x(1),x(2))).decode();sso(x(0),s);ret(x(0))
        elif at==0x823c8d4:
            # Real bank-service boundary: native resolver/profile validity and
            # Country getter execute from this typed expanded-profile record.
            u.mem_write(profile,bytes(0x1d0));put(profile+0x38,'<I4xQ',x(1),0 if missing_profile else x(2))
            put(profile+0x198,'<H',7);ret(profile)
        elif at==0x7a81d40:
            # Deep copy service only; identical native special memory layout.
            u.mem_write(x(0),bytes(u.mem_read(x(1),0xc88)));ret(x(0))
        elif at==0x2fdf960:
            a,b,e=x(0),x(1),x(2);n=alloc(e-b+16);u.mem_write(n,bytes(u.mem_read(b,e-b)));put(a,'<QQQ',n,n+e-b,n+e-b);ret(a)
        elif at==0x7baab1c:
            u.mem_write(x(8),bytes(0x70));put(x(8),'<H6xQQ',0,1,1);ret()
        elif at==0x7b907a4:put(x(1),'<I',x(0));ret()
        elif at==0x82a84d4:ret(0)
        elif at==0x7b7b020:ret(user)
        elif race_popup and code<=at<code+len(body)and bytes(u.mem_read(at,4))==bytes.fromhex('bf3b03d5'):
            put(bus+8,'<I',publish_sequence+2)
        elif at==stop:u.emu_stop()
        elif at==0x8c1bb80:raise AssertionError(f'unresolved libc caller LR={x(30):x} service={x(16):x}')
        elif at in(0x7bac124,0x7bac230,0x7bac178):calls.append(hex(at))
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x1a0000)
    u.reg_write(R.UC_ARM64_REG_X28,event);u.reg_write(R.UC_ARM64_REG_X20,0x6d0000);u.reg_write(R.UC_ARM64_REG_W0,1)
    u.emu_start(0x7697768,0x76977f0,count=1000)
    u.reg_write(R.UC_ARM64_REG_X20,event);put(sp+8,'<Q',event+0x60)
    u.emu_start(0x769b2d8,0x769b460,count=2000)
    u.reg_write(R.UC_ARM64_REG_X0,0x1b0000 if name_only else special+0x18 if resolve_only else special)
    u.reg_write(R.UC_ARM64_REG_X8,0x190000);u.reg_write(R.UC_ARM64_REG_X30,stop)
    try:u.emu_start(0x7b839c8 if name_only else 0x7baac3c if resolve_only else 0x7babf1c,stop,count=1500000)
    except Exception as error:raise AssertionError(f'PC={u.reg_read(R.UC_ARM64_REG_PC):x} trace={trace[-12:]}: {error}')from error
    assert u.reg_read(R.UC_ARM64_REG_PC)==stop,hex(u.reg_read(R.UC_ARM64_REG_PC))
    return dict(result=u.reg_read(R.UC_ARM64_REG_W0),resolved=rd(0x190000+8,'<QQ'),trace=trace,
                errors=calls,custom=rd(event+0x3d,'<B')[0],special=rd(event+0x149,'<B')[0],
                team_bank_requests=requested_teams,name=bytes(u.mem_read(0x1b0001,22)).split(b'\0')[0].decode(),
                entry_entity=rd(0x6e0000,'<I')[0],stored_special_team=rd(special+0xc64,'<I')[0]>>14)

class EntryQualificationNativeTests(unittest.TestCase):
    def test_native_person_identity_merges_real_and_unlicensed_variants(self):
        self.assertEqual(native_person_key(8496452),107844)
        self.assertEqual(native_person_key(50439492),107844)
        self.assertEqual({native_person_key(v)for v in(8491306,16879914,50434346)},{102698})
        self.assertNotEqual(native_person_key(8496452),native_person_key(8491306))

    def test_plain_rental_icon_is_distinct_from_rental_with_alert(self):
        # Values are from the original enum relocation table, not guessed labels:
        # NONE=0, RENTAL=1, ALERT=2, RENTAL_AND_ALERT=4.
        self.assertEqual(native_icon_type(),1)
        self.assertEqual(native_icon_type(alert=True),4)
        self.assertEqual(native_icon_type(rental=False,alert=True),2)
        self.assertEqual(native_icon_type(rental=False),0)
    def test_resolver_requires_real_custom_event_scope(self):
        a=qualify(custom_team=False,resolve_only=True);b=qualify(custom_team=True,resolve_only=True)
        self.assertEqual(a['resolved'],(0,0));self.assertEqual(b['resolved'],(1000,0))
        self.assertEqual((a['custom'],a['special']),(0,0));self.assertEqual((b['custom'],b['special']),(1,1))

    def test_complete_original_validator_not_only_nonempty_counter(self):
        self.assertEqual(qualify()['result'],0)
        out=qualify(custom_team=False)
        self.assertEqual(out['result'],3)
        self.assertIn('0x7a81758',out['trace']);self.assertIn('0x7bac230',out['errors'])
        self.assertNotIn('0x7bac140',out['trace'])

    def test_real_master_identity_rental_availability_and_duplicate_gates_survive(self):
        for options,reason in(({'missing_profile':True},3),({'missing_rental':True},3),
                               ({'unavailable':True},2),({'duplicate':True},3),({'registered':22},3)):
            with self.subTest(options=options):self.assertEqual(qualify(**options)['result'],reason)

    def test_single_team_popup_uses_country_as_team_bank_id_in_original_client(self):
        # The blueprint passes this exact string into both confirmation formatters.
        # This test records original behavior, not the desired patched behavior.
        out=qualify(name_only=True,entity_id=7)
        self.assertEqual(out['result'],1)
        self.assertEqual(out['team_bank_requests'],[7<<14]);self.assertEqual(out['name'],'Spain')
        self.assertEqual(qualify(name_only=True,entity_id=54,entry_type=3)['name'],'China')

    def test_popup_hook_repairs_actual_team_bank_key_before_special_reply(self):
        for team,name in((54,'China'),(49206,'China alias')):
            out=qualify(name_only=True,patched_popup=True,popup_team=team,received_special_team=0)
            self.assertEqual(out['result'],1);self.assertEqual(out['name'],name)
            self.assertEqual(out['team_bank_requests'],[team<<14])
            self.assertEqual(out['entry_entity'],7,'Country restriction must stay Country 7')
            self.assertEqual(out['stored_special_team'],0,'popup cannot require or fabricate a received special plan')

    def test_popup_hook_keeps_native_behavior_outside_exact_published_country_scope(self):
        cases=({'published_event':205060989},{'entry_type':3},{'publish_ready':0},
               {'publish_sequence':3},{'race_popup':True},{'popup_team':0},
               {'popup_team':2**18},{'popup_policy':{'kind':'national','entity_id':108}},
               {'popup_policy':{'kind':'club','entity_id':7}})
        for options in cases:
            with self.subTest(options=options):
                out=qualify(name_only=True,patched_popup=True,**options)
                self.assertEqual(out['team_bank_requests'],[7<<14]);self.assertEqual(out['name'],'Spain')

    def test_actual_old_china_special_reproduces_duplicate_person_error_three(self):
        folder=ROOT.parent/'.work/tournament-roster-isolation-20261105'
        path=folder/'china-54-duplicate-person-regression.json'
        if not path.is_file():self.skipTest('frozen generated China DTO proof is unavailable')
        payload=json.loads(path.read_text('utf8'))
        out=qualify(payload=payload)
        self.assertEqual(out['result'],3)
        self.assertEqual((out['custom'],out['special']),(1,1))
        self.assertIn('0x7a81ef8',out['trace'])
        self.assertIn('0x7bac230',out['errors'])

    def test_actual_regenerated_china_and_alias_have_twenty_three_native_people_and_pass(self):
        folder=ROOT.parent/'.work/tournament-roster-isolation-20261105'
        for team in(54,49206):
            path=folder/f'china-{team}-special.json'
            if not path.is_file():self.skipTest('read-only regenerated China DTO proof is unavailable')
            payload=json.loads(path.read_text('utf8'))
            ids=[p['gameplayer_id']['id']for p in payload['squad_data']['player_list']]
            self.assertEqual(len(ids),23);self.assertEqual(len({native_person_key(cid)for cid in ids}),23)
            out=qualify(payload=payload)
            self.assertEqual(out['result'],0)
            self.assertEqual(out['trace'].count('0x7a87eec'),23)

if __name__=='__main__':unittest.main()
