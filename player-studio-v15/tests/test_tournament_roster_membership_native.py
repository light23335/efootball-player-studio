"""Original UI append/registration consumers with the scoped emitted hooks."""
import hashlib
import json
import struct
import unittest
import mmap
from pathlib import Path
from functools import lru_cache
import tournament_home as home

ROOT=Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def engine():
    source=(ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so').open('rb')
    raw=mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ);source.close()
    assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    return raw


def probe(*,country=7,club=65590,rental=False,serial=None,card=1000,team=54,
          policy=None,event=205060988,mode=True,special_team=None,rental_ids=None,
          ready=1,sequence=2,race=False,register=False,dummy=False,invalid=False,
          native_context=False,custom_team=True,native_mode=0x2b,current_event_id=None,
          published_event=205060988,native_entry_type=4,squad_refs=None,source_row=None,
          registration_wrapper=False,entry_status=1,pending_event_id=None,entry_reply=None):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=engine()
    profile=json.loads((ROOT/'resources/tournament_schedule_ui/native-home.json').read_text('utf8'))
    body=bytearray.fromhex(profile['body_hex']);code,bus,sp,user,ev,player=0x200000,0x300000,0x4f0000,0x600000,0x610000,0x620000
    special=user+0x19e0;stop=0x160000;u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,n in((0x100000,0x130000),(bus,0x30000),(0x4d0000,0x30000),(user,0x100000)):
        u.mem_map(at,n)
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096);off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    def put(at,fmt,*values):u.mem_write(at,struct.pack(fmt,*values))
    def rd(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    for at,target in profile['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    for at,size in profile['writable_fixups']:struct.pack_into('<Q',body,at,bus)
    u.mem_write(code,bytes(body))
    name='tournament_roster_register'if register else'tournament_roster_candidate'
    entry=next(e for e in profile['extra_entries']if e['name']==name)
    # Actual original body is executed after the hook prologue/cleanup jumps.
    memory(u,0,entry['address'],0,0,None)
    u.mem_write(entry['address'],struct.pack('<I',0x14000000|(((code+entry['entry_offset']-entry['address'])//4)&0x3ffffff)))
    text={k:''for k in home.TEXTS};text.update(rental_team_id=team,rental_emblem_ids=[],membership=policy or{'kind':'national','entity_id':7})
    u.mem_write(bus,struct.pack('<III',ready,1,sequence));u.mem_write(bus+64,bytes(home.encode({published_event:text})))
    put(ev,'<I',event);put(user+0x28,'<Q',0x660000);put(ev+0x60,'<I',native_entry_type)
    # An ordinary Spain team remains present, and is never rewritten.
    put(user+0x20+8,'<I',7)
    put(special+0xc64,'<I',(team if special_team is None else special_team)<<14)
    identities=rental_ids if rental_ids is not None else[(1000+i,0)for i in range(23)]
    start=0x650000;put(special+0xc68,'<QQQ',start,start+len(identities)*0xf0,start+len(identities)*0xf0)
    for i,(cid,ser)in enumerate(identities):put(start+i*0xf0,'<I4xQQ',0,cid,ser)
    for i in range(23):put(special+0x18+i*0x18,'<I4xQQ',0xffffffff,0,0)
    for i,(cid,ser)in enumerate(squad_refs or[]):put(special+0x18+i*0x18,'<I4xQQ',0,cid,ser)
    serial=(0 if rental else 999)if serial is None else serial
    put(player,'<I4xQQ',0xffffffff if invalid else 0,0 if invalid else card,0 if invalid else serial)
    put(player+0x40,'<I',3 if dummy else 2 if rental else 0)
    put(player+0xd8,'<II',club<<14,0) # Missing native-national-team reference is intentional.
    # Real data accessor tests resolve the loader's global-user pointer.
    memory(u,0,0xa5bb000,0,0,None);put(0xa5bb7c8,'<Q',user)
    memory(u,0,0x99e6000,0,0,None);put(0x99e6928,'<Q',0x180000);put(0x180000,'<I4xQQ',0xffffffff,0,0)
    if native_context:
        # Model the actual global object graph, not predicate/getter results.
        # Context -> manager.mode; event bank -> record; user.current_event;
        # user -> special slot. These getters/lookup/mode branches all execute.
        put(0xa5bb7c0,'<Q',0x690000);put(0x690000+0x20,'<QQ',ev,ev+0x3878)
        put(user+0xb8,'<I',event if current_event_id is None else current_event_id)
        put(user+0xbc,'<I',event if pending_event_id is None else pending_event_id)
        put(ev+0x20b8,'<II',event,entry_status)
        memory(u,0,0xa5bd000,0,0,None);put(0xa5bd678,'<Q',0x670000)
        memory(u,0,0xa5fb000,0,0,None);put(0xa5fb028,'<Q',0x680000)
        put(0x680000,'<B',native_mode if mode else 0)
        # Native event+3d is is_custom_team, NOT is_vsai_custom_team nor
        # is_vsai_gameplan_disp. Execute its bool conversion and flag derivation.
        memory(u,0,0xa5a4000,0,0,None);memory(u,0,0xa5a6000,0,0,None)
        put(0xa5a4f68,'<B',1)
        for at,s in((0xa5a6068,'NO'),(0xa5a6080,'YES')):
            b=s.encode();u.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
        source_row=source_row if source_row is not None else{'is_custom_team':'YES'if custom_team else'NO'}
        u.mem_write(0x6d3000,str(source_row.get('is_custom_team','')).encode()+b'\0')
        for page in(0xbb5000,0x9d8000,0xaaa000,0xabd000):memory(u,0,page,0,0,None)
        for page in(0xa5a5000,0xa5a9000,0xa5aa000):memory(u,0,page,0,0,None)
        put(0xa5a54c8,'<B',1);put(0xa5a54e8,'<B',1)
        for at,s in((0x6d0038,'CHALLENGE'),(0x6d0090,'NATIONALITY'if native_entry_type==4 else'CLUB')):
            b=s.encode();u.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
    appended=[];calls=[];used_hooks=[];native_returns=[];pending_returns=[];native_services=set()
    missing=object();json_handles={0x6d1000:source_row,0x6e1000:entry_reply};next_json=[0x6e2000]
    entry_log_update=None
    def ret(value=None):
        if value is not None:u.reg_write(R.UC_ARM64_REG_X0,value)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        for callee,lr in pending_returns[:]:
            if at==lr:native_returns.append((hex(callee),x(0)));pending_returns.remove((callee,lr))
        if native_context and at in(0x7b7d95c,0x7b7d4e8,0x7b7b478,0x7a41d64,0x7a3fc3c,0x7a3e34c,0x7a3e2b4,0x7a438d4,
                                      0x7a87db8,0x82262b0,0x822884c,0x82289e0,0x8228bd8,0x7b82a5c,0x7b7bdd4,0x7b7b564,0x7a41cc0):
            native_services.add(hex(at))
            pending_returns.append((at,x(30)))
        if at==code+entry['entry_offset']:used_hooks.append(name)
        if at==0x7b7d95c and not native_context:ret(int(mode))
        elif at==0x7b7b478 and not native_context:ret(ev)
        elif at==0x8c1bca0:ret(len(bytes(u.mem_read(x(0),128)).split(b'\0')[0]))
        elif at==0x8c1c1f0:ret(0 if bytes(u.mem_read(x(0),x(2)))==bytes(u.mem_read(x(1),x(2)))else 1)
        elif native_context and at==0x2f3877c:
            b=bytes(u.mem_read(x(1),x(2)));assert len(b)<=22
            u.mem_write(x(0),bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)));ret(x(0))
        elif native_context and at==0x2f49320:ret()
        elif native_context and at in(0x2fccaf0,0x2fcc828):
            key=bytes(u.mem_read(x(1),64)).split(b'\0')[0].decode()
            obj=json_handles[x(0)];assert isinstance(obj,dict),(key,obj)
            h=next_json[0];next_json[0]+=0x20;json_handles[h]=obj.get(key,missing);ret(h)
        elif native_context and at==0x2fcbaec:ret(int(json_handles[x(0)]is not missing))
        elif native_context and at==0x2fcbce4:
            value=json_handles[x(0)];assert isinstance(value,str),value
            u.mem_write(0x6d3000,value.encode()+b'\0');ret(0x6d3000)
        elif native_context and at==0x2fcbde8:ret(int(json_handles[x(0)]))
        elif at==0x7a87f44:
            # Explicit native player-bank fixture; the original Country
            # accessor (7a88414) executes, rather than replacing its result.
            put(x(8)+0x198,'<H',country);calls.append('native_profile_country');ret()
        elif at==0x70ba454:put(0x190000,'<Q',1);ret(0x190000)
        elif at in(0x70ba51c,0x30403a0):
            appended.append(rd(x(1)+8,'<QQ'));ret()
        elif at==0x7a87db8 and not native_context:ret(0x670000)
        elif at==0x7a3e2b4 and not native_context:ret(user)
        elif at==0x7b7b020:ret(user)
        elif at==0x82468d4:put(0x6a0000+0x40,'<Q',0x6b0000);ret(0x6a0000)
        elif at==0x823c9d4:
            calls.append(('native_team_bank',x(1)));put(0x6c0000+0x3f4,'<H',108);ret(0x6c0000)
        elif at==0x82262b0 and not native_context:ret(0x680000)
        elif at in(0x82289e0,0x8228bd8)and not native_context:ret(1)
        elif at==0x7a41d64 and not native_context:ret(ev)
        elif at==0x323afb0:u.mem_write(x(0),bytes(u.mem_read(ev,0x20b8)));ret()
        elif at==0x323bed4:ret()
        elif native_context and at==0x7a40d34:u.mem_write(x(0),bytes(0x3878));ret()
        elif native_context and at==0x73aab54:u.mem_write(x(0),bytes(u.mem_read(x(1),0x20b8)));ret()
        elif native_context and at==0x7a40bc8:u.mem_write(x(0),bytes(u.mem_read(x(1),0x17c0)));ret()
        elif at==0x7baac3c:u.mem_write(x(8),bytes(u.mem_read(player,0xf0)));ret()
        elif at in(0x300eac0,0x300ebd4,0x2f376d4):ret()
        elif race and code<=at<code+len(body)and bytes(u.mem_read(at,4))==bytes.fromhex('bf3b03d5'):
            put(bus+8,'<I',sequence+2)
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x1a0000)
    if native_context:
        # Actual enum initializers/getters/converters; CHALLENGE is 2, not 3.
        u.reg_write(R.UC_ARM64_REG_X23,0xa5a54c8);u.reg_write(R.UC_ARM64_REG_W20,0x454e4f4e)
        u.emu_start(0x76260e0,0x76261e0,count=1000)
        u.reg_write(R.UC_ARM64_REG_X23,0xa5a54e8);u.reg_write(R.UC_ARM64_REG_W20,0x454e4f4e)
        u.reg_write(R.UC_ARM64_REG_W24,0x42554c43);u.reg_write(R.UC_ARM64_REG_X26,int.from_bytes(b'NATIONAL','little'))
        u.emu_start(0x762687c,0x7626a30,count=2000)
        u.reg_write(R.UC_ARM64_REG_X19,0x6d0000);u.reg_write(R.UC_ARM64_REG_X28,ev)
        u.emu_start(0x76975f0,0x76976e8,count=2000)
        u.reg_write(R.UC_ARM64_REG_SP,sp)
        u.reg_write(R.UC_ARM64_REG_X0,ev+0x60);u.reg_write(R.UC_ARM64_REG_X1,0x6d0090)
        u.emu_start(0x7694cf8,0x769512c,count=3000)
        u.reg_write(R.UC_ARM64_REG_SP,sp)
        u.reg_write(R.UC_ARM64_REG_X26,0x6d1000);u.reg_write(R.UC_ARM64_REG_X28,0x6d0000)
        u.emu_start(0x75be4b8,0x75be538,count=2000)
        u.reg_write(R.UC_ARM64_REG_X28,ev);u.reg_write(R.UC_ARM64_REG_X20,0x6d0000)
        u.reg_write(R.UC_ARM64_REG_W0,1)
        u.emu_start(0x7697768,0x76977f0,count=1000)
        u.reg_write(R.UC_ARM64_REG_X20,ev)
        put(sp+8,'<Q',ev+0x60)
        u.emu_start(0x769b2d8,0x769b460,count=2000)
        if entry_reply is not None:
            # Original response JSON parser: absent event_log skips its DTO;
            # present log parses its ID/status through the genuine field loop.
            u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_X19,0x6e8000)
            u.reg_write(R.UC_ARM64_REG_X20,0x6e1000)
            stop_json=0x75b4c50 if'event_log'in entry_reply else 0x77f992c
            u.emu_start(0x77f98f8,stop_json,count=3000)
            u.reg_write(R.UC_ARM64_REG_SP,sp)
            put(0xa5a5290,'<B',1)
            u.emu_start(0x761cd00,0x761ce20,count=1000)
            u.reg_write(R.UC_ARM64_REG_X0,0x6f0000);u.reg_write(R.UC_ARM64_REG_X1,0x6e8960)
            u.emu_start(0x769ca34,0x769cbd4,count=3000)
            u.reg_write(R.UC_ARM64_REG_SP,sp)
            u.reg_write(R.UC_ARM64_REG_X0,0x690000);u.reg_write(R.UC_ARM64_REG_X1,0x6f0000)
            u.reg_write(R.UC_ARM64_REG_X30,stop);u.emu_start(0x7a41dc0,stop,count=1000)
            entry_log_update=u.reg_read(R.UC_ARM64_REG_W0)
            # The original entry consumer separately sets the selected event.
            u.reg_write(R.UC_ARM64_REG_X0,user);u.reg_write(R.UC_ARM64_REG_W1,event)
            u.reg_write(R.UC_ARM64_REG_X30,stop);u.emu_start(0x7a42ba4,stop,count=100)
    u.reg_write(R.UC_ARM64_REG_X30,stop)
    if register:
        if registration_wrapper:
            u.reg_write(R.UC_ARM64_REG_X0,player);u.reg_write(R.UC_ARM64_REG_X1,0x1b0000)
            begin=0x7b82a5c
        else:
            u.reg_write(R.UC_ARM64_REG_W0,event);u.reg_write(R.UC_ARM64_REG_X1,player)
            u.reg_write(R.UC_ARM64_REG_W2,0);u.reg_write(R.UC_ARM64_REG_X3,0x1b0000)
            begin=0x7b824e0
    else:
        put(0x1b0000,'<QQ',0,0)
        u.reg_write(R.UC_ARM64_REG_X0,0x1b0000);u.reg_write(R.UC_ARM64_REG_X1,player)
        begin=entry['address']
    try:u.emu_start(begin,stop,count=50000)
    except Exception as error:raise AssertionError(f'native PC={u.reg_read(R.UC_ARM64_REG_PC):x}: {error}')from error
    assert u.reg_read(R.UC_ARM64_REG_PC)==stop
    assert u.reg_read(R.UC_ARM64_REG_SP)==sp
    registered=u.reg_read(R.UC_ARM64_REG_W0)if register else None
    u.reg_write(R.UC_ARM64_REG_X0,special);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x7a81758,stop,count=1000)
    registered_slots=u.reg_read(R.UC_ARM64_REG_W0)
    return dict(visible=bool(appended),registered=registered,registered_slots=registered_slots,
                appended=appended,calls=calls,hooks=used_hooks,ordinary_team=rd(user+0x28,'<I')[0],
                native_returns=native_returns,native_services_executed=sorted(native_services),
                native_event_type=rd(ev+0x38,'<I')[0],native_entry_type=rd(ev+0x60,'<I')[0],
                native_entry_status=rd(ev+0x20bc,'<I')[0],entry_log_update=entry_log_update,
                custom_team_flag=rd(ev+0x3d,'<B')[0],special_event_flag=rd(ev+0x149,'<B')[0])


def mode_probe(row,*,special=None,native_mode=0x2b,current_event_id=None,event_log=None,
               entry_reply=None,registration_wrapper=False,pending_event_id=None):
    """Replay a projected CHALLENGE row through real native context branches.

    No mode/current-event/event-lookup/user/slot getter is replaced. The row's
    is_custom_team is compared by the original DTO bool converter and original
    special-flag derivation. A full special response may supply actual 23 IDs.
    This is an independent instruction fixture, not a device/UI observation.
    """
    if row.get('ch_event_type')!='CHALLENGE':raise ValueError('mode_probe expects the actual projected CHALLENGE row')
    entry=row['match_entry'];kind=entry['entry_type'];entity=entry['entity_id_list'][0]
    if kind not in('NATIONALITY','CLUB'):raise ValueError('mode_probe needs an explicit Country or club policy')
    team=special['rental_team_id']if special else row['useable_team_list'][0]
    refs=[(p['gameplayer_id']['id'],p['gameplayer_id'].get('serial',0))for p in special['squad_data']['player_list']]if special else[(1000+i,0)for i in range(23)]
    rentals=[(p['gameplayer_id']['id'],p['gameplayer_id'].get('serial',0))for p in special['rental_gameplayer_list']]if special else refs
    options=dict(native_context=True,custom_team=row.get('is_custom_team')=='YES',native_mode=native_mode,
        current_event_id=current_event_id,event=row['event_id'],published_event=row['event_id'],
        team=team,policy={'kind':'national'if kind=='NATIONALITY'else'club','entity_id':entity},
        native_entry_type=4 if kind=='NATIONALITY'else 3,rental_ids=rentals,squad_refs=refs,source_row=row,
        registration_wrapper=registration_wrapper,pending_event_id=pending_event_id,entry_reply=entry_reply,
        entry_status={'NO_ENTRY':0,'ENTRY':1,'CLEARED':2}.get((event_log or{}).get('entry_status'),0)if event_log is not None else 1)
    own_country=entity if kind=='NATIONALITY'else 7
    rental_results=[probe(**options,card=cid,serial=serial,rental=True,country=own_country,register=True)for cid,serial in rentals]
    first=rental_results[0]
    values={callee:value for callee,value in first['native_returns']}
    same=probe(**options,country=own_country,club=entity if kind=='CLUB'else 65590,register=True)
    foreign=probe(**options,country=108 if own_country!=108 else 7,club=7 if entity!=7 else 108,register=True)
    return {'native_context_services_executed':first['native_services_executed'],
        'native_json_custom_team_parser':'0x75be4b8..0x75be538',
        'native_event_type':first['native_event_type'],'native_entry_type':first['native_entry_type'],
        'native_entry_status':first['native_entry_status'],'entry_log_update':first['entry_log_update'],
        'registration_entry':'0x7b82a5c'if registration_wrapper else'0x7b824e0',
        'membership_hook_entered':bool(first['hooks']),
        'predicate_results':values,'special_mode':values.get('0x7b7d95c'),
        'custom_team_flag':first['custom_team_flag'],'special_event_flag':first['special_event_flag'],
        'registered_slots':first['registered_slots'],'rental_count':len(rentals),
        'rental_registration_results':[r['registered']for r in rental_results],
        'same_membership_owned_registration':same['registered'],'foreign_owned_registration':foreign['registered'],
        'ordinary_team':first['ordinary_team'],'device_validated':False,
        'fixture_services':'Native profile-bank contents, DTO full-player resolver, string/memory/vector services are explicit fixtures; this is not the full match validator.'}


class RosterMembershipNativeTests(unittest.TestCase):
    def test_ui_collection_rejects_foreign_owned_and_allows_real_country_without_native_national_ref(self):
        self.assertFalse(probe(country=108,club=7)['visible'])
        self.assertTrue(probe(country=7,club=65590)['visible'])
        self.assertIn('native_profile_country',probe(country=7)['calls'])

    def test_registration_uses_special_country_and_preserves_original_invalid_dummy_checks(self):
        self.assertEqual(probe(register=True,country=108,club=7)['registered'],0)
        self.assertEqual(probe(register=True,country=7,club=65590)['registered'],1)
        for options in({'dummy':True},{'invalid':True}):
            result=probe(register=True,**options)
            self.assertEqual(result['registered'],0)
            self.assertEqual(result['hooks'],[])

    def test_exact_special_rentals_including_explicit_standard_bench_are_allowed(self):
        identities=[(1000+i,0)for i in range(23)]+[(90000,0)]
        for register in(False,True):
            for cid in(1000,1022,90000):
                out=probe(card=cid,country=108,rental=True,rental_ids=identities,register=register)
                self.assertTrue(out['registered']if register else out['visible'])
            out=probe(card=88888,country=108,rental=True,rental_ids=identities,register=register)
            self.assertFalse(out['registered']if register else out['visible'])
        # A same-card owned copy receives the normal source-country check.
        self.assertFalse(probe(card=90000,country=108,rental=False,rental_ids=identities)['visible'])

    def test_no_reward_list_capacity_limit_and_club_membership(self):
        ids=[(1000+i,0)for i in range(250)]
        self.assertTrue(probe(card=1249,rental=True,country=108,rental_ids=ids)['visible'])
        policy={'kind':'club','entity_id':65590}
        self.assertTrue(probe(policy=policy,club=65590)['visible'])
        self.assertFalse(probe(policy=policy,club=7)['visible'])

    def test_other_event_exit_missing_or_mismatched_snapshot_keep_original_candidate_behavior(self):
        for options in({'event':1120005},{'event':205060989},{'mode':False},{'special_team':108},{'ready':0},{'sequence':3}):
            with self.subTest(options=options):
                self.assertTrue(probe(country=108,**options)['visible'])
        self.assertFalse(probe(country=108,race=True)['visible'])

    def test_alias_and_event_team_switches_do_not_change_ordinary_spain(self):
        for team in(54,49206):
            result=probe(team=team,country=7)
            self.assertTrue(result['visible'])
            self.assertEqual(result['ordinary_team'],7)

    def test_registration_after_ordinary_exit_uses_original_spain_membership(self):
        spanish=probe(register=True,mode=False,country=108,club=7)
        chinese=probe(register=True,mode=False,country=7,club=65590)
        self.assertEqual((spanish['registered'],chinese['registered']),(1,0))
        self.assertIn(('native_team_bank',7<<14),spanish['calls'])


class RealNativeScopeContextTests(unittest.TestCase):
    def row(self,**values):
        return dict(event_id=202765127,ch_event_type='CHALLENGE',useable_team_list=[54],
            match_entry={'entry_type':'NATIONALITY','entity_id_list':[7]},**values)

    def test_player_custom_team_flag_enables_real_native_scope_and_all_registered_rentals(self):
        result=mode_probe(self.row(is_custom_team='YES',is_vsai_custom_team='NO',is_vsai_gameplan_disp='YES'))
        self.assertEqual((result['custom_team_flag'],result['special_event_flag'],result['special_mode']),(1,1,1))
        self.assertEqual(result['registered_slots'],23)
        self.assertEqual(result['rental_registration_results'],[1]*23)
        self.assertEqual((result['same_membership_owned_registration'],result['foreign_owned_registration']),(1,0))
        self.assertEqual(result['ordinary_team'],7)
        for service in('0x7b7d95c','0x7b7d4e8','0x82262b0','0x822884c','0x7b7b478','0x7a41d64','0x7a3e2b4','0x7a3e34c','0x7a438d4'):
            self.assertIn(service,result['native_context_services_executed'])

    def test_missing_or_no_player_flag_reproduces_inactive_filter_despite_cpu_display_flags(self):
        for flags in({},dict(is_custom_team='NO'),dict(is_vsai_custom_team='YES',is_vsai_gameplan_disp='YES')):
            result=mode_probe(self.row(**flags))
            self.assertEqual((result['custom_team_flag'],result['special_event_flag'],result['special_mode']),(0,0,0))
            self.assertEqual((result['same_membership_owned_registration'],result['foreign_owned_registration']),(0,1))
            self.assertNotIn('0x7a438d4',result['native_context_services_executed'])

    def test_real_current_event_lookup_and_mode_boundaries_cannot_activate_from_stale_special(self):
        row=self.row(is_custom_team='YES')
        missing=mode_probe(row,current_event_id=0)
        self.assertEqual(missing['special_mode'],0)
        for native_mode in(0x22,0x27,0x28,0x2b,0x2c):
            self.assertEqual(mode_probe(row,native_mode=native_mode)['special_mode'],1)
        ordinary=mode_probe(row,native_mode=0)
        self.assertNotIn('0x7a438d4',ordinary['native_context_services_executed'])
        self.assertIsNone(ordinary['special_mode']) # Native registration exits before the hook.

    def test_real_picker_wrapper_requires_successful_matching_entry_log_response(self):
        row=self.row(is_custom_team='YES')
        pending={'event_id':row['event_id'],'entry_status':'NO_ENTRY'}
        for reply in({}, {'event_log':{'event_id':1120005,'entry_status':'ENTRY'}}):
            out=mode_probe(row,event_log=pending,entry_reply=reply,registration_wrapper=True)
            self.assertEqual((out['registered_slots'],out['native_entry_status']),(23,0))
            self.assertEqual(out['entry_log_update'],0)
            self.assertFalse(out['membership_hook_entered'])
            self.assertEqual(out['rental_registration_results'],[0]*23)
        reply={'event_log':{'event_id':row['event_id'],'entry_status':'ENTRY'}}
        out=mode_probe(row,event_log=pending,entry_reply=reply,registration_wrapper=True)
        self.assertEqual((out['registered_slots'],out['native_entry_status']),(23,1))
        self.assertEqual(out['entry_log_update'],1)
        self.assertTrue(out['membership_hook_entered'])
        self.assertEqual(out['rental_registration_results'],[1]*23)
        self.assertEqual((out['same_membership_owned_registration'],out['foreign_owned_registration']),(1,0))

    def test_real_picker_wrapper_checks_its_selected_event_separately_from_current_event(self):
        out=mode_probe(self.row(is_custom_team='YES'),registration_wrapper=True,pending_event_id=0)
        self.assertFalse(out['membership_hook_entered'])
        self.assertEqual(out['rental_registration_results'],[0]*23)


if __name__=='__main__':unittest.main()
