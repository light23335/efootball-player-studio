"""Build the scoped native homepage text adapter; no process/APK mutation."""
from pathlib import Path
import hashlib,json,struct,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maintenance.skill_hook_ir import Hooks,save_all,restore_all,FRAME
from tournament_home import SCHEMA,REVISION

EXPECTED='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
SITE=0x40e54a8
PATHS=[('MatchMainMenuInformation','Text_Item'),
       ('MatchMainMenuInformation','MatchMainMenuReward_1','Text_Item'),
       ('MatchMainMenuInformation','MatchMainMenuReward_1','Text_Value_1'),
       ('MatchMainMenuInformation','MatchMainMenuReward_1','Text_Value_2'),
       ('MatchMainMenuCell_1','Text_Item'),('MatchMainMenuCell_1','Text_Value'),
       ('MatchMainMenuCell_2','Text_Item'),('MatchMainMenuCell_2','Text_Value')]


def build(engine_path,output):
    engine=Path(engine_path).read_bytes()
    if hashlib.sha256(engine).hexdigest()!=EXPECTED:raise ValueError('Wrong source engine')
    names=['BP_MenuEvCompeEventMainMenu_C','Widget',*dict.fromkeys(p for path in PATHS for p in path)]
    labels={name:'name_'+str(i)for i,name in enumerate(names)}
    code=save_all()+'''
    sub sp,sp,#0x1000
    sub sp,sp,#0x200
    bl shared_home_control
    mov x24,x0
    ldr w9,[x24,#24]
    add w9,w9,#1
    str w9,[x24,#24]
    ldar w9,[x24]
    cmp w9,#1
    b.ne done
    ldr x9,[sp,#4760]
    cbz x9,done
    ldr x19,[x9,#0x18]
    cbz x19,done
    ldr x9,[sp,#4840]
    ldur w21,[x9,#-12]
    str w21,[x24,#28]
    add x9,x24,#8
    ldar w25,[x9]
    tbnz w25,#0,done
    ldr w22,[x24,#4]
    cmp w22,#32
    b.hi done
    cbz w22,done
    add x23,x24,#64
row_loop:
    ldr w9,[x23]
    cmp w9,w21
    b.eq row_found
    add x23,x23,#4096
    subs w22,w22,#1
    b.ne row_loop
    b done
row_found:
    mov x10,sp
    mov w11,#256
copy_loop:
    ldp x12,x13,[x23],#16
    stp x12,x13,[x10],#16
    subs w11,w11,#1
    b.ne copy_loop
    dmb ish
    ldr w9,[x24,#8]
    cmp w9,w25
    b.ne done
    ldr x20,[x19,#0x10]
    cbz x20,done
    adr x0,CLASS_NAME
    bl name_id
    ldr x9,[x20,#0x18]
    cmp x0,x9
    b.ne done
    mov x0,x19
    adr x1,WIDGET_NAME
    bl object_field
    cbz x0,missing
    mov x26,x0
    str x19,[sp,#4184]
'''.replace('CLASS_NAME',labels[names[0]]).replace('WIDGET_NAME',labels['Widget'])
    for i,path in enumerate(PATHS):
        code+='    mov x0,x26\n'
        for name in path:
            code+=f'    adr x1,{labels[name]}\n    bl object_field\n    cbz x0,missing\n'
        code+=f'    str x0,[sp,#{4096+i*8}]\n'
    for i in range(8):
        code+=f'''
    ldr x19,[sp,#{4096+i*8}]
    add x20,sp,#{16+i*256}
    mov w22,#0
length_{i}:
    ldrh w9,[x20,x22,lsl #1]
    cbz w9,length_ok_{i}
    add w22,w22,#1
    cmp w22,#127
    b.lo length_{i}
    b missing
length_ok_{i}:
    add w22,w22,#1
    str x20,[sp,#4160]
    str w22,[sp,#4168]
    str w22,[sp,#4172]
    mov x0,x19
    add x1,sp,#4096
    add x1,x1,#64
    mov w2,#0
    ldr x16,set_text
    blr x16
'''
    code+='''
    ldr w9,[x24,#16]
    add w9,w9,#1
    str w9,[x24,#16]
    str w21,[x24,#32]
    ldr w9,[x24,#36]
    add w9,w9,#1
    cbnz w9,render_sequence_ready
    mov w9,#1
render_sequence_ready:
    add x10,x24,#36
    stlr w9,[x10]
    ldr x0,[sp,#4184]
    mov w1,w21
    bl shared_promotion_observe
    b done
missing:
    ldr w9,[x24,#20]
    add w9,w9,#1
    str w9,[x24,#20]
done:
    add sp,sp,#0x1000
    add sp,sp,#0x200
'''+restore_all()+'''
    add x0,sp,#0x10
    ldr x16,resume
    br x16

name_id:
    stp x29,x30,[sp,#-32]!
    mov x9,x0
    mov w10,#0
name_length:
    ldrh w11,[x9,x10,lsl #1]
    add w10,w10,#1
    cbnz w11,name_length
    str x9,[sp,#16]
    str w10,[sp,#24]
    str w10,[sp,#28]
    add x0,sp,#16
    ldr x16,string_to_name
    blr x16
    ldp x29,x30,[sp],#32
    ret

object_field:
    stp x29,x30,[sp,#-64]!
    stp x19,x20,[sp,#16]
    stp x21,x22,[sp,#32]
    stp x23,x24,[sp,#48]
    mov x19,x0
    mov x0,x1
    bl name_id
    mov x20,x0
    ldr x21,[x19,#0x10]
    mov w22,#32
class_loop:
    cbz x21,field_missing
    ldr x23,[x21,#0x50]
    mov w24,#512
field_loop:
    cbz x23,parent_class
    ldr x9,[x23,#0x28]
    cmp x9,x20
    b.eq field_found
    ldr x23,[x23,#0x20]
    subs w24,w24,#1
    b.ne field_loop
    b field_missing
parent_class:
    mov x0,x21
    ldr x9,[x21]
    ldr x16,[x9,#0x280]
    blr x16
    mov x21,x0
    subs w22,w22,#1
    b.ne class_loop
    b field_missing
field_found:
    ldrsw x9,[x23,#0x4c]
    cmp x9,#0x28
    b.lo field_missing
    mov x10,#0x10000
    cmp x9,x10
    b.hs field_missing
    tst x9,#7
    b.ne field_missing
    ldr x0,[x19,x9]
    b field_end
field_missing:
    mov x0,#0
field_end:
    ldp x19,x20,[sp,#16]
    ldp x21,x22,[sp,#32]
    ldp x23,x24,[sp,#48]
    ldp x29,x30,[sp],#64
    ret
studio_home_fence:
    dmb ish
    ret
'''
    for name,label in labels.items():
        raw=name.encode('utf-16le')+b'\0\0'
        code+='\n.align 1\n'+label+': .hword '+','.join(str(i)for i in struct.unpack('<'+'H'*(len(raw)//2),raw))+'\n'
    code+='\n.align 2\n'
    builder=Hooks(engine)
    builder.add('tournament_native_home',SITE,code,
          {'string_to_name':0x5de3160,'set_text':0x3bd1b10,'resume':SITE+4})
    # This is inside the ORIGINAL emblem getter, after the ordinary/custom
    # binding has delegated. Use the projected club only for serial-zero rows
    # whose card AND represented team match a published tournament allowlist.
    # Never rewrite the shared native card's national flag or catalogue row.
    builder.add('tournament_rental_card_emblem',0x7a883b0,save_all()+'''
    ldr w9,[x19]
    cbnz w9,emblem_fallback
    ldr x9,[x19,#0x10]
    cbnz x9,emblem_fallback
    ldr w21,[x19,#0xd8]
    cbz w21,emblem_fallback
    ldr x22,[x19,#8]
    bl shared_home_control
    mov x20,x0
    ldar w9,[x20]
    cmp w9,#1
    b.ne emblem_fallback
    add x9,x20,#8
    ldar w23,[x9]
    tbnz w23,#0,emblem_fallback
    ldr w24,[x20,#4]
    cbz w24,emblem_fallback
    cmp w24,#32
    b.hi emblem_fallback
    add x25,x20,#64
emblem_row:
    ldr w9,[x25,#4]
    cmp w9,w21
    b.ne emblem_next_row
    ldr w26,[x25,#8]
    cbz w26,emblem_next_row
    cmp w26,#118
    b.hi emblem_fallback
    add x27,x25,#2080
emblem_card:
    ldr x9,[x27],#8
    cmp x9,x22
    b.eq emblem_found
    subs w26,w26,#1
    b.ne emblem_card
emblem_next_row:
    add x25,x25,#4096
    subs w24,w24,#1
    b.ne emblem_row
    b emblem_fallback
emblem_found:
    dmb ish
    ldr w9,[x20,#8]
    cmp w9,w23
    b.ne emblem_fallback
'''+restore_all()+'''
    ldr w0,[x19,#0xd8]
    b emblem_return
emblem_fallback:
'''+restore_all()+'''
    ldr x8,[sp,#0x1a0]
    tbnz x8,#53,emblem_national
    ldr w0,[x19,#0xd8]
    b emblem_return
emblem_national:
    ldr w0,[x19,#0xdc]
emblem_return:
    ldr x16,emblem_resume
    br x16
''',{'emblem_resume':0x7a883c4})
    # The native special-plan entry replaces the received team identity with
    # the user's ordinary club at this point (77f2bec..77f2c58). Preserve the
    # roster/coach, but bind its badge/name/kit lookup to the represented team.
    # Require both the exact published event and the parsed rental_team_id;
    # unrelated modes and the user's ordinary saved squad are untouched.
    builder.add('tournament_own_team_identity',0x77f2c58,save_all()+f'''
    ldr x16,current_event
    blr x16
    cbz x0,identity_done
    ldr w21,[x0]
    bl shared_home_control
    mov x20,x0
    ldar w9,[x20]
    cmp w9,#1
    b.ne identity_done
    add x9,x20,#8
    ldar w23,[x9]
    tbnz w23,#0,identity_done
    ldr w24,[x20,#4]
    cbz w24,identity_done
    cmp w24,#32
    b.hi identity_done
    add x25,x20,#64
identity_row:
    ldr w9,[x25]
    cmp w9,w21
    b.eq identity_found
    add x25,x25,#4096
    subs w24,w24,#1
    b.ne identity_row
    b identity_done
identity_found:
    ldr w22,[x25,#4]
    cbz w22,identity_done
    lsr w9,w22,#18
    cbnz w9,identity_done
    ldr w9,[sp,#{FRAME+0x30+0xc64}]
    lsl w10,w22,#14
    cmp w9,w10
    b.ne identity_done
    dmb ish
    ldr w9,[x20,#8]
    cmp w9,w23
    b.ne identity_done
    lsl w9,w22,#14
    str x9,[sp,#{19*8}]
identity_done:
'''+restore_all()+'''
    mov w20,w19
    ldr x16,identity_resume
    br x16
''',{'current_event':0x7b7b478,'identity_resume':0x77f2c5c})
    # EventList.CheckAndSpawnConfirmAlert obtains its teamName through
    # IsSelectedEventTeamSelectOnlyOne -> 7b839c8. The stock NATIONALITY
    # branch treats Country 7 as Team 7 (Spain) before any special reply.
    # Repair the actual TeamBank argument, leaving the native Country entry
    # restriction and subsequent native bank/name/formatter code intact.
    assert engine[0x7b83b40-0x4000:0x7b83b40-0x4000+4]==bytes.fromhex('080140b9')
    builder.add('tournament_entry_popup_team_identity',0x7b83b40,save_all()+f'''
    ldr x9,[sp,#{8*8}]
    ldr w9,[x9]
    str x9,[sp,#{8*8}]
    ldr x19,[sp,#{21*8}]
    cbz x19,popup_done
    ldrb w9,[x19,#0x3d]
    cbz w9,popup_done
    ldr w9,[x19,#0x60]
    cmp w9,#4
    b.ne popup_done
    ldr w21,[x19]
    bl shared_home_control
    mov x20,x0
    ldar w9,[x20]
    cmp w9,#1
    b.ne popup_done
    add x9,x20,#8
    ldar w23,[x9]
    tbnz w23,#0,popup_done
    ldr w24,[x20,#4]
    cbz w24,popup_done
    cmp w24,#32
    b.hi popup_done
    add x25,x20,#64
popup_row:
    ldr w9,[x25]
    cmp w9,w21
    b.eq popup_found
    add x25,x25,#4096
    subs w24,w24,#1
    b.ne popup_row
    b popup_done
popup_found:
    ldr w9,[x25,#3024]
    cmp w9,#1
    b.ne popup_done
    ldr w9,[x25,#3028]
    cbz w9,popup_done
    lsr w10,w9,#9
    cbnz w10,popup_done
    ldr w10,[sp,#{8*8}]
    cmp w9,w10
    b.ne popup_done
    ldr w22,[x25,#4]
    cbz w22,popup_done
    lsr w9,w22,#18
    cbnz w9,popup_done
    dmb ish
    ldr w9,[x20,#8]
    cmp w9,w23
    b.ne popup_done
    str x22,[sp,#{8*8}]
popup_done:
'''+restore_all()+'''
    ldr x16,popup_resume
    br x16
''',{'popup_resume':0x7b83b44})
    # The original League tile reads this native UI model, independently of
    # the gateway response object. Refresh its cached deadline before the
    # original interval predicate; do not bypass support or clock checks.
    from league_availability import NATIVE_MAGIC,NATIVE_OFFSET,RUNTIME_REVISION
    assert SCHEMA['header_bytes']==64 and NATIVE_OFFSET==40
    assert engine[0x74a4ad0-0x4000:0x74a4ad0-0x4000+4]==bytes.fromhex('fd7bbea9')
    builder.add('original_league_native_availability',0x74a4ad0,save_all()+f'''
    ldr x9,[sp,#240]
    ldr x10,league_caller
    cmp x9,x10
    b.ne league_cache_done
    bl shared_home_control
    add x20,x0,#{NATIVE_OFFSET}
    ldar w21,[x20]
    cbz w21,league_cache_done
    tbnz w21,#0,league_cache_done
    ldr w9,[x20,#4]
    ldr w10,league_magic
    cmp w9,w10
    b.ne league_cache_done
    ldp x22,x23,[x20,#8]
    cbz x22,league_cache_done
    cmp x23,x22
    b.ls league_cache_done
    sub x9,x23,x22
    ldr w10,league_duration
    cmp x9,x10
    b.ne league_cache_done
    dmb ish
    ldr w9,[x20]
    cmp w9,w21
    b.ne league_cache_done
    ldr x19,[sp]
    cbz x19,league_cache_done
    ldr x9,[x19,#0x60]
    cbz x9,league_cache_done
    ldr x10,[x19,#0x68]
    cbz x10,league_cache_done
    cmp x9,x22
    csel x22,x9,x22,lo
    stp x22,x23,[x19,#0x60]
    ldur w9,[x20,#-28]
    add w9,w9,#1
    stur w9,[x20,#-28]
league_cache_done:
'''+restore_all()+'''
    stp x29,x30,[sp,#-0x20]!
    ldr x16,league_resume
    br x16
''',{'league_resume':0x74a4ad4,'league_caller':0x37c7190},
      constants={name:struct.unpack('<f',struct.pack('<I',value))[0]for name,value in
                 (('league_magic',NATIVE_MAGIC),('league_duration',2500*86400))},
      evidence=['League kind 3: 37c62f8 -> 37c7170 -> 37c718c -> 74a4ad0',
                '74a4718 copies cache b8/c0 to model 60/68; 74a4ad0 keeps native interval predicate'])
    # The single-choice event initializer independently treats NATIONALITY's
    # Country as a Team ID. Its w23 feeds both 7b7ee24's match identity and
    # user.selected_team. Repair that common source before either write;
    # the event's Country list and player eligibility remain untouched.
    assert engine[0x7b7eda8-0x4000:0x7b7eda8-0x4000+4]==bytes.fromhex('170140b9')
    builder.add('tournament_match_initialization_team_identity',0x7b7eda8,
'''    ldr w23,[x8]
'''+save_all()+f'''
    ldr x19,[sp,#{22*8}]
    cbz x19,match_identity_done
    ldrb w9,[x19,#0x3d]
    cbz w9,match_identity_done
    ldr w9,[x19,#0x60]
    cmp w9,#4
    b.ne match_identity_done
    ldr w21,[x19]
    bl shared_home_control
    mov x20,x0
    ldar w9,[x20]
    cmp w9,#1
    b.ne match_identity_done
    add x9,x20,#8
    ldar w24,[x9]
    tbnz w24,#0,match_identity_done
    ldr w26,[x20,#4]
    cbz w26,match_identity_done
    cmp w26,#32
    b.hi match_identity_done
    add x25,x20,#64
match_identity_row:
    ldr w9,[x25]
    cmp w9,w21
    b.eq match_identity_found
    add x25,x25,#4096
    subs w26,w26,#1
    b.ne match_identity_row
    b match_identity_done
match_identity_found:
    ldr w9,[x25,#3024]
    cmp w9,#1
    b.ne match_identity_done
    ldr w9,[x25,#3028]
    cbz w9,match_identity_done
    lsr w10,w9,#9
    cbnz w10,match_identity_done
    ldr w10,[sp,#{23*8}]
    cmp w9,w10
    b.ne match_identity_done
    ldr w22,[x25,#4]
    cbz w22,match_identity_done
    lsr w9,w22,#18
    cbnz w9,match_identity_done
    dmb ish
    ldr w9,[x20,#8]
    cmp w9,w24
    b.ne match_identity_done
    str x22,[sp,#{23*8}]
match_identity_done:
'''+restore_all()+'''
    ldr x16,match_identity_resume
    br x16
''',{'match_identity_resume':0x7b7edac},evidence=[
        '7b7ec94 callers: 7ae84bc and 812a760; native custom single-choice initialization',
        '7b7eda8 w23 -> 7b7edbc 7b7ee24 -> 7b7efec match header; 7b7edc0 selected team',
        'Country restriction remains event+68; published event/Country/seqlock gate only'])
    builder.helper('home_control','ldr x0,control\nret',writable={'control':SCHEMA['bytes']})
    from maintenance.tournament_roster_hook import append as append_roster,evidence as roster_evidence
    append_roster(builder)
    from maintenance.tournament_promotion_hook import append,finalize
    promotion_helper=append(builder)
    hook=builder.bundle('tournament-native-home-v1',builder.rows+builder.helpers)
    finalize(hook,promotion_helper)
    body=bytes.fromhex(hook['body_hex'])
    hook.update(address=SITE,file_offset=SITE-0x4000,expected_hex=engine[SITE-0x4000:SITE-0x4000+64].hex(),
          revision=REVISION,source_engine_sha256=EXPECTED,body_sha256=hashlib.sha256(body).hexdigest(),
          tournament_home_channel=SCHEMA,helper_entries={'studio_home_fence':body.index(bytes.fromhex('bf3b03d5c0035fd6'))},
          native_probes=[{'name':name,'file_offset':addr-0x4000,'expected_hex':engine[addr-0x4000:addr-0x4000+n].hex()}
              for name,addr,n in [('reflected-reward-exec',0x40e5498,56),('ui-text-setstr-exec',0x4181158,32),
                 ('text-native',0x3bd1b10,64),('super-class-getter',0x5df0c68,32),('property-layout',0x5de8150,28),
                 ('card-emblem-original-selection',0x7a88370,128),
                 ('special-plan-original-team-override',0x77f2bec,0x150),
                 ('special-plan-rental-team-field',0x7a81d40,76),
                 ('special-plan-rental-team-key-setter',0x7a81db4,24),
                 ('special-plan-dto-converter',0x7655704,0x100),
                 ('special-plan-registered-slot-counter',0x7a81758,108),
                 ('ordinary-player-candidate-loop',0x70b4038,188),
                 ('special-rental-candidate-loop',0x70b3d7c,240),
                 ('native-player-membership-predicate',0x7b824e0,0x1b0),
                 ('native-player-country-getter',0x7a88414,92),
                 ('native-entry-popup-single-team-source',0x7b839c8,472),
                 ('native-entry-popup-country-as-team-bank',0x7b83b40,64),
                 ('native-event-match-team-initializer',0x7b7ec94,0x190),
                 ('native-event-match-team-identity-source',0x7b7eda8,48),
                 ('native-event-match-team-first-caller',0x7ae8438,164),
                 ('native-event-match-team-second-caller',0x812a6ec,128),
                 ('native-match-team-header-overwrite',0x7b7efe8,32),
                 ('native-start-keeps-initialized-team-header',0x77c801c,0x160),
                 ('native-registered-player-person-identity',0x6774f54,44),
                 ('native-complete-entry-validator',0x7babf1c,2016),
                 ('native-player-club-getter',0x7a883ec,20),
                 ('original-league-availability-predicate',0x74a4ad0,80),
                 ('original-league-model-cache-copy',0x74a48d8,40),
                 ('original-league-topmatch-gate-call',0x37c7170,36),
                 ('original-league-topmatch-support-thunk',0x38c8280,4),
                 ('original-league-topmatch-support-adapter',0x74f1ee0,4),
                 ('original-league-topmatch-support-predicate',0x7b0a62c,104),
                 ('original-league-topmatch-model-getter',0x302b6d4,8),
                 ('current-event-accessor',0x7b7b478,96),
                 ('promotion-original-factory',0x333b1f0,124),('promotion-original-setup',0x33401d4,372),
                 ('promotion-generic-child-factory',0x302d514,456),('promotion-original-button-dispatch',0x3bba208,80),
                 ('promotion-original-confirm-virtual',0x3336440,124),('promotion-original-frame',0x3bf87a0,16),
                 ('promotion-original-fadeout-finished',0x302e978,136),
                 ('promotion-original-weak-identity',0x45ee3f8,76),
                 ('promotion-original-numbered-slot-binding',0x333ffac,0x228),
                 ('promotion-original-widget-opacity',0x54c7964,0x188),
                 ('promotion-original-widget-find',0x54f0ce4,64),('promotion-original-fname',0x4414bec,64)]],
          execution_proof={'independent_instruction_probe':True,'original_league_exact_caller_probe':True,
              'original_league_native_support_branch_probe':True,'device_validated':False},
          scope='Published tournament snapshots; original League model only from exact TopMatch caller 0x37c7190')
    hook['special_plan_team_identity']={'rental_field_offset':0xc64,'rental_field_encoding':'native-team-id-shift-left-14',
        'native_setter':0x7a81db4,'hook_site':0x77f2c58,'team_id_bits':18,
        'requires_event_and_rental_match':True,'unrelated_squads_unchanged':True,'device_validated':False}
    hook['special_plan_roster_membership']=roster_evidence()
    hook['entry_popup_team_identity']={'hook_site':0x7b83b40,'resume':0x7b83b44,
        'native_team_bank':0x823c9d4,'native_team_name':0x82b4a74,
        'selected_event_record':'native-user-selected-event-BC -> 7a41d64',
        'requires_published_event':True,'requires_nationality_entry_type':4,
        'requires_country_metadata_match':True,'special_reply_required':False,
        'country_entry_restriction_unchanged':True,'ordinary_modes_unchanged':True,
        'blueprint_consumer':'BP_MenuEvCompeEventList.CheckAndSpawnConfirmAlert',
        'device_validated':False}
    hook['match_initialization_team_identity']={'hook_site':0x7b7eda8,'resume':0x7b7edac,
        'native_initializer':0x7b7ec94,'direct_callers':[0x7ae84bc,0x812a760],
        'native_match_initializer':0x7b7ee24,'shared_source_register':'w23',
        'requires_native_custom_team':True,'requires_nationality_entry_type':4,
        'requires_published_event':True,'requires_country_metadata_match':True,
        'requires_consistent_seqlock':True,'special_reply_required':False,
        'country_entry_restriction_unchanged':True,'ordinary_modes_unchanged':True,
        'device_validated':False}
    hook['original_league_availability']={'revision':RUNTIME_REVISION,'header_offset':NATIVE_OFFSET,
        'header_bytes':24,'sync_counter_offset':12,'magic':NATIVE_MAGIC,'days':2500,'site':0x74a4ad0,
        'exact_caller':0x37c7190,'other_callers_keep_original_model':True,
        'model_start':0x60,'model_end':0x68,'original_predicate_preserved':True,
        'native_clock_unchanged':True,'saved_phase_and_sporting_state_unchanged':True,'device_validated':False}
    # .rodata uses VA==file offset; executable probes above use VA-0x4000.
    hook['native_probes'].append({'name':'original-league-topmatch-support-table',
        'file_offset':0xc9f944,'expected_hex':engine[0xc9f944:0xc9f944+0x38c].hex()})
    menu=Path(__file__).resolve().parents[2]/'.work/tournament-schedule-ui-20261103/BP_MenuEvCompeEventMainMenu.uasset'
    hook['menu_source_sha256']=hashlib.sha256(menu.read_bytes()).hexdigest()
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(hook,ensure_ascii=False,indent=2),'utf8')
    print('Homepage adapter compiled:',len(body),'code bytes;',SCHEMA['bytes'],'data bytes')


if __name__=='__main__':build(*sys.argv[1:])
