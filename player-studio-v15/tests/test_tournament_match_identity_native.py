"""Read-only reproduction of the native event-team initialization identity.

Original enum/flag conversion, global mode/user/event lookup, event selection,
and match-team initialization branches run. Allocators, object copying, strings,
and roster-to-match conversion are fixture services. No bank asset initialization
or on-device observation is claimed by these identity traces.
"""
import json
import struct
import unittest
from pathlib import Path
import tournament_home as home

from test_tournament_roster_membership_native import engine

ROOT=Path(__file__).resolve().parents[1]


def initialization_probe(row,*,special_team=None,native_mode=0x2b,repeats=1,notice_on_change=1,
                         patched=False,published_event=None,policy=None,ready=1,sequence=2,count=1,
                         race=False,published_team=None,caller='initializer'):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=engine();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(0x100000,0x700000)
    sp=0x7f0000;stop=0x150000;user=0x600000;event=0x610000
    context=0x670000;manager=0x680000;special=user+0x19e0
    team=row['useable_team_list'][0]if special_team is None else special_team
    def put(at,fmt,*v):u.mem_write(at,struct.pack(fmt,*v))
    def rd(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    def sso(at,s):b=s.encode();assert len(b)<=22;u.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096);off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    for at in(0xa5bb000,0xa5bd000,0xa5fb000,0xa5a4000,0xa5a5000,0xa5a6000,0xa5a9000,0xa5aa000):memory(u,0,at,0,0,None)
    put(0xa5bb7c8,'<Q',user);put(0xa5bb7c0,'<Q',0x690000)
    put(0x690020,'<QQ',event,event+0x3878)
    put(user+0xb8,'<II',row['event_id'],row['event_id'])
    put(user+0x28,'<I',7)
    put(0xa5bd678,'<Q',context);put(0xa5fb028,'<Q',manager);put(manager,'<B',native_mode)
    put(event,'<I',row['event_id']);put(event+0x20b8,'<III',row['event_id'],1,team)
    country=row['match_entry']['entity_id_list'][0]
    put(0x6e0000,'<I',country);put(event+0x68,'<QQQ',0x6e0000,0x6e0004,0x6e0004)
    put(0x6e0020,'<I',row['useable_team_list'][0]);put(event+0x1250,'<QQQ',0x6e0020,0x6e0024,0x6e0024)
    put(0xa5a4f68,'<B',1);sso(0xa5a6068,'NO');sso(0xa5a6080,'YES')
    put(0xa5a54c8,'<B',1);put(0xa5a54e8,'<B',1)
    sso(0x6d0038,row['ch_event_type']);sso(0x6d0090,row['match_entry']['entry_type'])
    sso(0x6d0068,row['is_custom_team'])
    calls=[];game_records=[];abi=[];hook_frames=[];code=0x400000;bus=0x500000;hook_at=None;hook_end=None
    if patched:
        profile=json.loads((ROOT/'resources/tournament_schedule_ui/native-home.json').read_text('utf8'))
        body=bytearray.fromhex(profile['body_hex'])
        for at,target in profile['absolute_fixups']:struct.pack_into('<Q',body,at,target)
        for at,size in profile['writable_fixups']:struct.pack_into('<Q',body,at,bus)
        u.mem_write(code,bytes(body))
        entry=next(x for x in profile['extra_entries']if x['name']=='tournament_match_initialization_team_identity')
        hook_at=code+entry['entry_offset'];hook_end=code+len(body)
        memory(u,0,entry['address'],0,0,None)
        u.mem_write(entry['address'],struct.pack('<I',0x14000000|(((hook_at-entry['address'])//4)&0x3ffffff)))
        text={k:''for k in home.TEXTS}
        text.update(rental_team_id=row['useable_team_list'][0]if published_team is None else published_team,
                    rental_emblem_ids=[],membership=policy or{'kind':'national','entity_id':country})
        put(bus,'<III',ready,count,sequence)
        u.mem_write(bus+64,bytes(home.encode({row['event_id']if published_event is None else published_event:text})))
    def registers():
        return ([u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(i)))for i in range(31)],
                [u.reg_read(getattr(R,'UC_ARM64_REG_Q'+str(i)))for i in range(32)],
                u.reg_read(R.UC_ARM64_REG_SP),u.reg_read(R.UC_ARM64_REG_NZCV))
    def ret(value=None):
        if value is not None:u.reg_write(R.UC_ARM64_REG_X0,value)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if patched and at==hook_at:hook_frames.append(registers())
        elif patched and at==0x7b7edac:
            before=hook_frames.pop();after=registers()
            expected_source=rd(before[0][8],'<I')[0]
            same=all(before[0][i]==after[0][i]for i in range(31)if i not in(16,23))
            abi.append(dict(preserved=same and before[1:]==after[1:],original_source=expected_source,result=after[0][23]))
        if patched and race and hook_at<=at<hook_end and bytes(u.mem_read(at,4))==bytes.fromhex('bf3b03d5'):
            put(bus+8,'<I',rd(bus+8,'<I')[0]+2)
        if at in(0x7b7ec94,0x7b7d60c,0x7b7b3e4,0x7a41cc0,0x7a41d64,0x7a87db8,
                  0x82262b0,0x822884c,0x7a3e34c,0x7b7ee24,0x7b7ef80,0x7b7b478,0x7a438d4):
            calls.append((hex(at),x(0)))
        if at==0x8c1bca0:ret(len(bytes(u.mem_read(x(0),128)).split(b'\0')[0]))
        elif at==0x8c1c1f0:ret(0 if bytes(u.mem_read(x(0),x(2)))==bytes(u.mem_read(x(1),x(2)))else 1)
        elif at==0x2f3877c:sso(x(0),bytes(u.mem_read(x(1),x(2))).decode());ret(x(0))
        elif at==0x2f49320:ret()
        elif at==0x7a40d34:u.mem_write(x(0),bytes(0x3878));ret()
        elif at in(0x323afb0,0x73aab54):u.mem_write(x(0),bytes(u.mem_read(x(1),0x20b8)));ret()
        elif at in(0x323bed4,0x7a40bc8):u.mem_write(x(0),bytes(u.mem_read(x(1),0x17c0)));ret()
        elif at==0x7a81c34:u.mem_write(x(0),bytes(0xc88));ret()
        elif at==0x7a81d40:u.mem_write(x(0),bytes(u.mem_read(x(1),0xc88)));ret()
        elif at==0x6a9b204:u.mem_write(x(0),bytes(0x2100));ret()
        elif at==0x7b8f2f4:
            # Explicit conversion service: valid special header reaches the
            # native caller; the subsequent native overwrite is under test.
            put(x(0),'<I',rd(x(1)+0xc64,'<I')[0]);ret()
        elif at==0x82468d4:put(0x6a0000+0x40,'<Q',0x1000000);ret(0x6a0000)
        elif at==0x82a0150:
            game_records.append(rd(x(1),'<I')[0]);ret()
        elif at in(0x300eac0,0x300ebd4,0x321beb8,0x2f376d4,0x82d664c,0x7abdc74):ret()
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x170000)
    u.reg_write(R.UC_ARM64_REG_X23,0xa5a54c8);u.reg_write(R.UC_ARM64_REG_W20,0x454e4f4e)
    u.emu_start(0x76260e0,0x76261e0,count=1000)
    u.reg_write(R.UC_ARM64_REG_X23,0xa5a54e8);u.reg_write(R.UC_ARM64_REG_W20,0x454e4f4e)
    u.reg_write(R.UC_ARM64_REG_W24,0x42554c43);u.reg_write(R.UC_ARM64_REG_X26,int.from_bytes(b'NATIONAL','little'))
    u.emu_start(0x762687c,0x7626a30,count=2000)
    u.reg_write(R.UC_ARM64_REG_X19,0x6d0000);u.reg_write(R.UC_ARM64_REG_X28,event)
    u.emu_start(0x76975f0,0x76976e8,count=2000)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_X0,event+0x60);u.reg_write(R.UC_ARM64_REG_X1,0x6d0090)
    u.emu_start(0x7694cf8,0x769512c,count=3000)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_X28,event);u.reg_write(R.UC_ARM64_REG_X20,0x6d0000);u.reg_write(R.UC_ARM64_REG_W0,1)
    u.emu_start(0x7697768,0x76977f0,count=1000)
    u.reg_write(R.UC_ARM64_REG_X20,event);put(sp+8,'<Q',event+0x60)
    u.emu_start(0x769b2d8,0x769b460,count=2000)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_X0,special);u.reg_write(R.UC_ARM64_REG_W1,team);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x7a81db4,stop,count=100)
    for i in range(32):u.reg_write(getattr(R,'UC_ARM64_REG_Q'+str(i)),((i+1)<<96)|(0x123456789abcdef+i))
    for _ in range(repeats):
        u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_W0,notice_on_change);u.reg_write(R.UC_ARM64_REG_X30,stop)
        begin,end=0x7b7ec94,stop
        if caller=='post_entry':begin=0x7ae8438
        elif caller=='event_menu':
            # Resolve the event by its original getter, then execute the
            # menu's genuine custom/entry-type/one-choice/owned-mode branch.
            u.emu_start(0x7b7b5e4,stop,count=3000)
            u.reg_write(R.UC_ARM64_REG_X21,u.reg_read(R.UC_ARM64_REG_X0))
            u.reg_write(R.UC_ARM64_REG_X19,0x620000)
            begin,end=0x812a660,0x812a780
        elif caller!='initializer':raise ValueError('Unknown caller')
        try:u.emu_start(begin,end,count=20000)
        except Exception as exc:raise AssertionError('native PC='+hex(u.reg_read(R.UC_ARM64_REG_PC)))from exc
        assert u.reg_read(R.UC_ARM64_REG_PC)==end
    return dict(event_type=rd(event+0x38,'<I')[0],entry_type=rd(event+0x60,'<I')[0],
        custom=rd(event+0x3d,'<B')[0],special_flag=rd(event+0x149,'<B')[0],
        received_special_team=rd(special+0xc64,'<I')[0]>>14,
        selected_team_after=rd(user+0x28,'<I')[0],
        initializer_team_arguments=[value>>14 for address,value in calls if address=='0x7b7ee24'],
        match_record_team_ids=[v>>14 for v in game_records],calls=calls,hook_abi=abi,
        country_after=rd(0x6e0000,'<I')[0])


def start_header_probe(*,local_side=0,selected_team=7,received_team=54,opponent=108):
    """Original START physical-slot branches preserve the pre-existing header.

The two native squad conversion services are supplied data fixtures; each
attempts to write its actual response team. Original caller instructions then
restore the old header before submitting the resulting physical match slot.
"""
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=engine();u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x100000,0x700000)
    dto=0x610000;bank=0x1000000;sp=0x7f0000
    cache0=bank+0x318e790;cache1=bank+0x3190890;target=bank+0x318da00
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096);off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    def put(at,fmt,*v):u.mem_write(at,struct.pack(fmt,*v))
    def rd(at):return struct.unpack('<I',u.mem_read(at,4))[0]
    for base in(cache0,cache1):
        for page in range(base&~4095,(base+0x2100+4095)&~4095,4096):
            try:u.mem_map(page,4096)
            except Exception:pass
    put(cache0,'<I',(selected_team if local_side==0 else opponent)<<14)
    put(cache1,'<I',(selected_team if local_side==1 else opponent)<<14)
    put(dto+0x968,'<I',received_team<<14);put(dto+0xaf8,'<I',opponent<<14)
    put(sp+0xf0,'<Q',cache1);put(sp+0xf8,'<Q',cache0);put(sp+0x100,'<Q',target)
    put(sp+0xe0,'<Q',dto)
    writes=[];converted=[]
    def ret():u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if at==0x6a9b204:u.mem_write(x(0),bytes(0x2100));ret()
        elif at in(0x8c1bc70,0x69c3894):
            size=x(2)if at==0x8c1bc70 else 0x2100
            u.mem_write(x(0),bytes(u.mem_read(x(1),size)));ret()
        elif at==0x7bcb930:
            converted.append(rd(x(0))>>14);put(x(1),'<I',rd(x(0)));ret()
        elif at in(0x82a0150,0x82a04f0):
            physical=0 if at==0x82a0150 else 1
            writes.append((physical,rd(x(1))>>14));ret()
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_X9,dto)
    u.reg_write(R.UC_ARM64_REG_W25,local_side)
    u.emu_start(0x77c801c,0x77c80c0,count=1000)
    u.reg_write(R.UC_ARM64_REG_X9,dto)
    u.emu_start(0x77c80d4,0x77c817c,count=1000)
    return dict(converted_response_ids=converted,physical_slot_writes=writes)


class MatchIdentityNativeTests(unittest.TestCase):
    def row(self,team=54,country=7):
        return dict(event_id=202765127,ch_event_type='CHALLENGE',is_custom_team='YES',useable_team_list=[team],
                    match_entry=dict(entry_type='NATIONALITY',entity_id_list=[country]))

    def test_original_event_initializer_confuses_country_with_team_after_valid_special(self):
        for team in(54,49206):
            row=dict(event_id=202765127,ch_event_type='CHALLENGE',is_custom_team='YES',useable_team_list=[team],
                     match_entry=dict(entry_type='NATIONALITY',entity_id_list=[7]))
            out=initialization_probe(row)
            self.assertEqual((out['event_type'],out['entry_type'],out['custom'],out['special_flag']),(2,4,1,1))
            self.assertEqual(out['received_special_team'],team)
            self.assertEqual(out['initializer_team_arguments'],[7])
            self.assertEqual(out['selected_team_after'],7)
            self.assertEqual(out['match_record_team_ids'],[7])

    def test_repeat_initialization_and_both_notice_call_patterns_repeat_country_identity(self):
        for mode in(0x2b,0x2c):
            for notice in(0,1):
                row=dict(event_id=202765127,ch_event_type='CHALLENGE',is_custom_team='YES',useable_team_list=[54],
                         match_entry=dict(entry_type='NATIONALITY',entity_id_list=[7]))
                out=initialization_probe(row,native_mode=mode,repeats=3,notice_on_change=notice)
                self.assertEqual(out['initializer_team_arguments'],[7]*3)
                self.assertEqual(out['match_record_team_ids'],[7]*3)
                self.assertEqual(out['received_special_team'],54)

    def test_club_initialization_uses_club_id_without_country_alias_collision(self):
        row=dict(event_id=202765127,ch_event_type='CHALLENGE',is_custom_team='YES',useable_team_list=[108],
                 match_entry=dict(entry_type='CLUB',entity_id_list=[108]))
        out=initialization_probe(row)
        self.assertEqual(out['entry_type'],3)
        self.assertEqual(out['initializer_team_arguments'],[108])
        self.assertEqual(out['match_record_team_ids'],[108])

    def test_start_keeps_wrong_initialized_header_for_both_local_physical_sides(self):
        for team in(54,49206):
            for side in(0,1):
                out=start_header_probe(local_side=side,received_team=team)
                self.assertEqual(out['converted_response_ids'],[team,108])
                self.assertEqual(dict(out['physical_slot_writes'])[side],7)
                self.assertEqual(dict(out['physical_slot_writes'])[1-side],108)

    def test_emitted_hook_fixes_both_china_ids_modes_notice_paths_and_repeat_initialization(self):
        for team in(54,49206):
            for mode in(0x2b,0x2c):
                for notice in(0,1):
                    with self.subTest(team=team,mode=mode,notice=notice):
                        out=initialization_probe(self.row(team),patched=True,native_mode=mode,
                                                 notice_on_change=notice,repeats=3)
                        self.assertEqual(out['initializer_team_arguments'],[team]*3)
                        self.assertEqual(out['match_record_team_ids'],[team]*3)
                        self.assertEqual(out['selected_team_after'],team)
                        self.assertEqual(out['received_special_team'],team)
                        self.assertEqual(out['country_after'],7)
                        self.assertEqual(len(out['hook_abi']),3)
                        self.assertTrue(all(x['preserved']and x['original_source']==7 and x['result']==team for x in out['hook_abi']))

    def test_fixed_init_reaches_start_header_for_both_physical_sides(self):
        for team in(54,49206):
            initialized=initialization_probe(self.row(team),patched=True)
            for side in(0,1):
                out=start_header_probe(local_side=side,selected_team=initialized['match_record_team_ids'][0],received_team=team)
                self.assertEqual(dict(out['physical_slot_writes'])[side],team)
                self.assertEqual(dict(out['physical_slot_writes'])[1-side],108)

    def test_both_real_callers_reach_fixed_match_record_and_same_selection(self):
        for caller in('post_entry','event_menu'):
            for team in(54,49206):
                for patched,expected in((False,7),(True,team)):
                    with self.subTest(caller=caller,team=team,patched=patched):
                        out=initialization_probe(self.row(team),caller=caller,patched=patched)
                        self.assertEqual(out['initializer_team_arguments'],[expected])
                        self.assertEqual(out['match_record_team_ids'],[expected])
                        self.assertEqual(out['selected_team_after'],expected)

    def test_publication_country_and_seqlock_guards_keep_original_native_behavior(self):
        for options in(dict(policy={'kind':'national','entity_id':108}),
                       dict(policy={'kind':'club','entity_id':7}),dict(published_event=202765128),
                       dict(ready=0),dict(sequence=3),dict(count=0),dict(count=33),
                       dict(race=True),dict(published_team=0),dict(published_team=2**18)):
            with self.subTest(options=options):
                out=initialization_probe(self.row(),patched=True,**options)
                self.assertEqual(out['initializer_team_arguments'],[7])
                self.assertEqual(out['match_record_team_ids'],[7])
                self.assertEqual(out['country_after'],7)
                self.assertTrue(all(x['preserved']and x['result']==7 for x in out['hook_abi']))

    def test_noncustom_club_and_ordinary_mode_are_unchanged_and_pre_entry_needs_no_rental(self):
        row=self.row();row['is_custom_team']='NO'
        out=initialization_probe(row,patched=True)
        self.assertEqual(out['initializer_team_arguments'],[54])
        self.assertTrue(all(x['preserved']and x['result']==54 for x in out['hook_abi']))
        row=self.row(108,108);row['match_entry']['entry_type']='CLUB'
        out=initialization_probe(row,patched=True,policy={'kind':'club','entity_id':108})
        self.assertEqual(out['initializer_team_arguments'],[108])
        self.assertEqual(out['match_record_team_ids'],[108])
        self.assertTrue(all(x['preserved']and x['result']==108 for x in out['hook_abi']))
        out=initialization_probe(self.row(),patched=True,native_mode=0)
        self.assertEqual(out['initializer_team_arguments'],[])
        self.assertEqual(out['hook_abi'],[])
        self.assertEqual(out['selected_team_after'],7)
        out=initialization_probe(self.row(),patched=True,special_team=0)
        self.assertEqual(out['received_special_team'],0)
        self.assertEqual(out['initializer_team_arguments'],[54])
        self.assertEqual(out['match_record_team_ids'],[54])

    def test_current_253_mapped_nation_ids_keep_country_restrictions_and_selected_team(self):
        path=ROOT.parent/'.work/tournament-match-identity-audit-20261105/latest-country-as-team-proof.json'
        mappings=json.loads(path.read_text('utf8'))['mapped_nations']
        self.assertEqual(len(mappings),253)
        for item in mappings:
            team,country=item['team'],item['country']
            with self.subTest(team=team,country=country):
                out=initialization_probe(self.row(team,country),patched=True)
                self.assertEqual(out['initializer_team_arguments'],[team])
                self.assertEqual(out['selected_team_after'],team)
                self.assertEqual(out['match_record_team_ids'],[team])
                self.assertEqual(out['country_after'],country)
                self.assertTrue(all(x['preserved']for x in out['hook_abi']))


if __name__=='__main__':unittest.main()
