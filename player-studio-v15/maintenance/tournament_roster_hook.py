"""Scoped candidate visibility and registration for native special squads.

The original candidate builder combines ordinary owned cards with special
rentals. Its membership checker may derive the destination from the ordinary
team. Use the exact published event's explicit Country/club, while preserving
the original behavior outside that event and the native invalid-player checks.
"""
from maintenance.skill_hook_ir import save_all,restore_all,FRAME


def append(builder):
    # This append is reached both by the owned loop (70b40e4) and rental loop
    # (70b3e64). Reject before the candidate reaches the actual UI collection.
    builder.add('tournament_roster_candidate',0x70b3f70,save_all()+'''
    mov x0,x1
    bl shared_tournament_membership
    cbz w0,candidate_reject
'''+restore_all()+'''
    stp x29,x30,[sp,#-0x30]!
    ldr x16,candidate_resume
    br x16
candidate_reject:
'''+restore_all()+'''
    ret
''',{'candidate_resume':0x70b3f74})
    # The actual registration predicate has already resolved a native full
    # player, rejected invalid/DUMMY identities, and retains its cleanup path.
    # Its ordinary-team-derived membership branches are replaced only when
    # the same scoped candidate policy is active.
    builder.add('tournament_roster_register',0x7b82630,save_all()+'''
    mov x0,x25
    bl shared_tournament_membership
    cmn w0,#1
    b.eq register_native
    str x0,[sp,#184]
'''+restore_all()+'''
    ldr x16,register_cleanup
    br x16
register_native:
'''+restore_all()+'''
    cmp w26,#7
    ldr x16,register_resume
    br x16
''',{'register_cleanup':0x7b82a28,'register_resume':0x7b82634})
    builder.helper('tournament_membership','''
    stp x29,x30,[sp,#-96]!
    stp x19,x20,[sp,#16]
    stp x21,x22,[sp,#32]
    stp x23,x24,[sp,#48]
    stp x25,x26,[sp,#64]
    stp x27,x28,[sp,#80]
    mov x19,x0
    ldr x16,special_mode
    blr x16
    cbz w0,membership_inactive
    ldr x16,current_event
    blr x16
    cbz x0,membership_inactive
    ldr w21,[x0]
    bl shared_home_control
    mov x20,x0
    ldar w9,[x20]
    cmp w9,#1
    b.ne membership_inactive
    add x9,x20,#8
    ldar w24,[x9]
    tbnz w24,#0,membership_inactive
    ldr w26,[x20,#4]
    cbz w26,membership_inactive
    cmp w26,#32
    b.hi membership_inactive
    add x27,x20,#64
membership_row:
    ldr w9,[x27]
    cmp w9,w21
    b.eq membership_row_found
    add x27,x27,#4096
    subs w26,w26,#1
    b.ne membership_row
    b membership_inactive
membership_row_found:
    ldr w22,[x27,#3024]
    ldr w23,[x27,#3028]
    cbz w23,membership_inactive
    cmp w22,#1
    b.eq membership_national_valid
    cmp w22,#2
    b.ne membership_inactive
    lsr w9,w23,#18
    cbnz w9,membership_inactive
    b membership_policy_valid
membership_national_valid:
    lsr w9,w23,#9
    cbnz w9,membership_inactive
membership_policy_valid:
    ldr x16,user_data
    blr x16
    cbz x0,membership_inactive
    ldr x16,special_squad
    blr x16
    mov x25,x0
    ldr w9,[x27,#4]
    cbz w9,membership_inactive
    lsr w10,w9,#18
    cbnz w10,membership_inactive
    lsl w9,w9,#14
    ldr w10,[x25,#0xc64]
    cmp w9,w10
    b.ne membership_inactive
    mov x0,x19
    ldr x16,is_rental
    blr x16
    cbz w0,membership_owned
    // Only received special rentals are exceptions. This includes explicit
    // Standard bench reinforcement, never arbitrary foreign rental cards.
    ldr x10,[x25,#0xc68]
    ldr x11,[x25,#0xc70]
    ldp x12,x13,[x19,#8]
membership_rental_loop:
    cmp x10,x11
    b.hs membership_deny
    ldp x14,x15,[x10,#8]
    cmp x12,x14
    ccmp x13,x15,#0,eq
    b.eq membership_allow
    add x10,x10,#0xf0
    b membership_rental_loop
membership_owned:
    mov x0,x19
    cmp w22,#1
    b.ne membership_club
    ldr x16,player_country
    blr x16
    cmp w0,w23
    cset w28,eq
    b membership_consistent
membership_club:
    ldr x16,player_club
    blr x16
    lsl w9,w23,#14
    cmp w0,w9
    cset w28,eq
    b membership_consistent
membership_allow:
    mov w28,#1
    b membership_consistent
membership_deny:
    mov w28,#0
membership_consistent:
    dmb ish
    ldr w9,[x20,#8]
    cmp w9,w24
    csel w0,w28,wzr,eq
    b membership_return
membership_inactive:
    mov w0,#-1
membership_return:
    ldp x27,x28,[sp,#80]
    ldp x25,x26,[sp,#64]
    ldp x23,x24,[sp,#48]
    ldp x21,x22,[sp,#32]
    ldp x19,x20,[sp,#16]
    ldp x29,x30,[sp],#96
    ret
''',{'special_mode':0x7b7d95c,'current_event':0x7b7b478,'user_data':0x7a3e34c,
     'special_squad':0x7a438d4,'is_rental':0x7a88330,'player_country':0x7a88414,
     'player_club':0x7a883ec})


def evidence():
    return {'candidate_site':0x70b3f70,'registration_site':0x7b82630,
        'ordinary_candidate_loop':0x70b4038,'rental_candidate_loop':0x70b3d7c,
        'native_country_getter':0x7a88414,'native_country_profile_offset':0x198,
        'native_club_getter':0x7a883ec,'policy_offset':3024,'policy_entity_offset':3028,
        'requires_event_special_team_match':True,'rental_exception':'exact-received-special-identity',
        'unrelated_modes_keep_native':True,'original_invalid_player_checks_preserved':True,
        'device_validated':False}
