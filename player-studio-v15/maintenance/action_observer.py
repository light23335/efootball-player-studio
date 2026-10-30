"""Read-only native action/motion observation with a bounded private ring."""
from skill_hook_ir import call,jump,save_all,restore_all,FRAME
from action_trace import COUNTERS

BUFFER_BYTES=790528


def add_observer(b):
    serial=iter(range(1000))
    def count(reason):
        label='count_'+str(next(serial));offset=COUNTERS.index(reason)*8
        return f'''sub w14,w20,#1
add x15,x25,#3072
add x15,x15,x14,lsl #7
add x15,x15,#{offset}
mov w12,#4
{label}:
ldaxr x9,[x15]
add x9,x9,#1
stxr w10,x9,[x15]
cbz w10,{label}_done
subs w12,w12,#1
b.ne {label}
clrex
mov w10,#1
str w10,[x25,#40]
{label}_done:
'''
    b.helper('studio_action_trace_fence','dmb ish\nret\n')
    b.helper('studio_trace_resolve',f'''
stp x19,x20,[sp,#-64]!
stp x21,x22,[sp,#16]
stp x23,x30,[sp,#32]
mov x19,x0
mov x20,x2
mov w22,w1
mov w23,w3
cmp w23,#1
b.eq game_actor_index
cmp w23,#4
b.eq game_actor_index
b info_root
game_actor_index:
mov x0,x19
{call('actor_index')}
mov w22,w0
cmp w22,#22
b.hs invalid_game_slot
add w22,w22,#1
info_root:
{call('root')}
mov x21,x0
cbz x21,no_root
cbz w22,cached
sub w22,w22,#1
cmp w23,#1
b.eq validate_index
cmp w23,#4
b.eq validate_index
mov x0,x21
mov w1,w22
bl resolve_actor
cmp x0,x19
b.eq found
b absent
cached:
mov w22,#0
cache_loop:
add x8,x20,#64
add x8,x8,x22,lsl #7
ldp x9,x10,[x8]
cmp x9,x21
b.ne next_cache
cmp x10,x19
b.ne next_cache
mov x0,x21
mov w1,w22
bl resolve_actor
cmp x0,x19
b.eq found
next_cache:
add w22,w22,#1
cmp w22,#22
b.lo cache_loop
mov w22,#0
scan:
mov x0,x21
mov w1,w22
bl resolve_actor
cmp x0,x19
b.eq found
add w22,w22,#1
cmp w22,#22
b.lo scan
b absent
validate_index:
mov x0,x21
mov w1,w22
{call('actor')}
cbnz x0,found
b absent
invalid_game_slot:
mov x21,xzr
mov w2,#3
b missing
absent:
mov w2,#15
b missing
no_root:
mov w2,#4
missing:
mov w1,#-1
b finish
found:
mov w1,w22
mov w2,#0
finish:
mov x0,x21
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#64
ret
resolve_actor:
cmp w23,#1
b.eq physical_actor
cmp w23,#4
b.eq physical_actor
{jump('actor')}
physical_actor:
{jump('physical')}
''',{'root':0x698f7e0,'actor':0x72c1a14,'physical':0x72c19f8,'actor_index':0x6d3ea38},evidence=['Typed GameActor callbacks use original native index getter 6d3ea38, never AnimeInfo pointer equality',
        'AI contexts are checked against current PlayerInfo; GameActor index alone does not certify card identity',
        'cached addresses compared as values and verified by the current native getter'])
    b.helper('studio_trace_actor',f'''
sub sp,sp,#352
stp x19,x20,[sp]
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
stp x27,x28,[sp,#64]
str x30,[sp,#80]
str w8,[sp,#96]
mov x19,x0
mov w20,w1
mov w21,w2
mov w22,w3
mov x23,x4
mov x24,x5
ldr x25,trace_ring
{count('entered')}
// Minimal diagnostic: no unconfirmed identity, position, or skills.
add x8,sp,#128
mov w9,#12
clear_event:
stp xzr,xzr,[x8],#16
subs w9,w9,#1
b.ne clear_event
str x19,[sp,#144]
str x24,[sp,#240]
str w6,[sp,#224]
mov w8,#-1
str w8,[sp,#164]
str w8,[sp,#152]
str w8,[sp,#156]
str w8,[sp,#160]
cmp w20,#1
b.ne read_enabled
str w21,[sp,#164]
read_enabled:
ldr w8,[x25,#4]
cbz w8,reject_disabled
tbz w7,#31,check_actor
and w8,w7,#0xff
cmp w8,#13
b.eq reject_context_invalid_slot
cmp w8,#14
b.eq reject_context_missing
b reject_null_root
check_actor:
cbz x19,reject_null_actor
mov x0,x19
mov w1,w7
mov x2,x25
mov w3,w20
bl shared_studio_trace_resolve
cmp w2,#3
b.eq reject_invalid_slot
cmp w2,#4
b.eq reject_null_root
cbnz w2,reject_actor_not_in_current_match
mov x27,x0
mov w26,w1
mov x0,x27
{call('game_info')}
cbz x0,reject_missing_game_info
mov x28,x0
{call('phase')}
cmp w0,#16
b.hi reject_invalid_phase
str w0,[sp,#108]
mov x0,x28
{call('clock')}
str w0,[sp,#104]
str x27,[sp,#136]
str x19,[sp,#144]
ldp w8,w9,[sp,#104]
stp w8,w9,[sp,#152]
str w26,[sp,#160]
mov w8,#2
str w8,[sp,#228]
cmp w20,#1
b.eq actual_game_actor
cmp w20,#4
b.eq actual_game_actor
// PlayerInfo is not GameActor. Copy a recent state VALUE only; never read
// a retained entity pointer, nor interpret AnimeInfo as an entity.
str xzr,[sp,#304]
mov w8,#-1
add x9,x25,#64
add x9,x9,x26,lsl #7
ldr x10,[x9]
cmp x10,x27
b.ne have_actual_state
ldr w10,[x9,#32]
cbz w10,have_actual_state
ldr w10,[x9,#36]
ldr w11,[sp,#104]
sub w10,w11,w10
cmp w10,#30
b.hi have_actual_state
ldr x10,[x9,#8]
str x10,[sp,#304]
ldr w8,[x9,#16]
b have_actual_state
actual_game_actor:
str x19,[sp,#304]
mov w8,#4
str w8,[sp,#228]
ldrb w8,[x19,#0xad0]
have_actual_state:
str w8,[sp,#164]
mov w0,w26
{call('action')}
cmp w20,#2
b.ne current_request
mov x0,x23
current_request:
cbz x0,no_request
ldr w8,[x0,#4]
ldr w9,[x0,#8]
stp w8,w9,[sp,#168]
cmp w8,#25
b.ne no_request
ldr w8,[x0,#0xc]
ldr w9,[x0,#0x10]
ldr w10,[x0,#0x14]
str w8,[sp,#192]
str w9,[sp,#196]
str w10,[sp,#200]
no_request:
mov x0,x27
mov w1,w26
{call('player_info')}
str x0,[sp,#312]
cmp w20,#1
b.eq actual_position
cmp w20,#4
b.eq actual_position
cbz x0,no_position
ldr w8,[x0,#0x4f4]
ldr w9,[x0,#0x4f8]
ldr w10,[x0,#0x4fc]
b have_position
actual_position:
ldr w8,[x19,#8]
ldr w9,[x19,#12]
ldr w10,[x19,#16]
b have_position
no_position:
mov w8,#0x7fc00000
mov w9,w8
mov w10,w8
have_position:
str w8,[sp,#180]
str w9,[sp,#184]
str w10,[sp,#188]
mov w8,#0x7fc00000
str w8,[sp,#204]
str w8,[sp,#208]
cmp w20,#3
b.ne motion_power
cbz x23,motion_power
ldr w8,[x23]
ldr w9,[x23,#4]
str w8,[sp,#204]
str w9,[sp,#208]
ldr w8,[x23,#8]
str w8,[sp,#256]
ldr w8,[sp,#172]
stp w8,w8,[sp,#216]
motion_power:
cmp w20,#4
b.ne state_power
cbz x23,state_power
ldr w8,[x23,#0xc]
str w8,[sp,#208]
state_power:
str w20,[sp,#212]
str w21,[sp,#216]
str w22,[sp,#220]
str x24,[sp,#240]
cmp w20,#6
b.ne candidate_done
cbz x23,candidate_done
ldp w8,w9,[x23,#8]
str w8,[sp,#256]
str w9,[sp,#260]
candidate_done:
cmp w20,#3
b.ne power_type_done
ldr w8,[sp,#172]
stp w8,w8,[sp,#216]
power_type_done:
cmp w20,#1
b.eq identity_done
cmp w20,#4
b.eq identity_done
// First eleven native roster entries are current on-field slots, as in the
// independently audited coaching observer. Preserve the native serial32 ABI.
mov w8,#11
udiv w1,w26,w8
mov x0,x27
{call('players')}
cbz x0,identity_done
mov x28,x0
{call('count')}
cmp w0,#11
b.lo identity_done
cmp w0,#40
b.hi identity_done
mov x0,x28
mov w8,#11
udiv w9,w26,w8
msub w1,w9,w8,w26
{call('entry')}
cbz x0,identity_done
{call('identity')}
str x1,[sp,#232]
mov w0,w0
str x0,[sp,#248]
ldr w8,[sp,#228]
orr w8,w8,#1
str w8,[sp,#228]
identity_done:
mov x0,x27
mov w1,w26
{call('player_state')}
cbz x0,lock_ring
{call('abilities')}
cbz x0,lock_ring
mov x28,x0
ldr w8,[x28,#0xd4]
str w8,[sp,#276]
mov w1,#51
{call('skill')}
and w8,w0,#1
str w8,[sp,#176]
mov x0,x28
mov w1,#58
{call('skill')}
ldr w8,[sp,#176]
and w9,w0,#1
orr w8,w8,w9,lsl #1
str w8,[sp,#176]
mov x0,x28
mov w1,#74
{call('skill')}
ldr w8,[sp,#176]
and w9,w0,#1
orr w8,w8,w9,lsl #2
str w8,[sp,#176]
lock_ring:
add x8,x25,#8
ldaxr w9,[x8]
cbnz w9,busy
mov w10,#1
stxr w9,w10,[x8]
cbnz w9,busy
cmp w20,#2
b.eq publish
cmp w20,#3
b.eq publish
cmp w20,#6
b.eq publish
// Every retained address is compared as a value, never dereferenced.
add x28,x25,#64
add x28,x28,x26,lsl #7
ldp x8,x9,[x28]
cmp x8,x27
b.ne new_actor
cmp x9,x19
b.eq cached_actor
new_actor:
stp xzr,xzr,[x28]
stp xzr,xzr,[x28,#16]
stp xzr,xzr,[x28,#32]
stp xzr,xzr,[x28,#48]
stp xzr,xzr,[x28,#64]
stp xzr,xzr,[x28,#80]
stp xzr,xzr,[x28,#96]
stp xzr,xzr,[x28,#112]
stp x27,x19,[x28]
cached_actor:
ldp x8,x9,[x28,#64]
ldr x10,[sp,#232]
ldr x11,[sp,#248]
cmp x8,x10
b.ne changed_identity
cmp x9,x11
b.eq identity_cached
changed_identity:
stp x10,x11,[x28,#64]
str wzr,[x28,#32]
str wzr,[x28,#56]
identity_cached:
cmp w20,#4
b.eq motion_cache
ldr w8,[x28,#32]
cbz w8,save_state
ldp x8,x9,[x28,#16]
ldur x10,[sp,#164]
ldur x11,[sp,#172]
cmp x8,x10
b.ne save_state
cmp x9,x11
b.ne save_state
ldr w8,[sp,#104]
ldr w9,[x28,#36]
sub w10,w8,w9
cmp w8,w9
b.lo save_state
cmp w10,#30
b.lo duplicate
mov w8,#7
str w8,[sp,#212]
save_state:
ldur x8,[sp,#164]
ldur x9,[sp,#172]
stp x8,x9,[x28,#16]
mov w8,#1
str w8,[x28,#32]
ldr w8,[sp,#104]
str w8,[x28,#36]
b publish
motion_cache:
ldr w8,[x28,#56]
cbz w8,save_motion
ldr w8,[sp,#104]
ldr w9,[x28,#40]
cmp w8,w9
b.ne save_motion
ldr w8,[x28,#44]
cmp w8,w21
b.ne save_motion
ldr w8,[x28,#48]
cmp w8,w22
b.ne save_motion
ldr w8,[x28,#52]
ldr w9,[sp,#208]
cmp w8,w9
b.eq duplicate
save_motion:
ldr w8,[sp,#104]
str w8,[x28,#40]
stp w21,w22,[x28,#44]
ldr w8,[sp,#208]
str w8,[x28,#52]
mov w8,#1
str w8,[x28,#56]
publish:
ldr x8,[x25,#16]
add x8,x8,#1
and x9,x8,#0xfff
add x10,x25,#1,lsl #12
mov x11,#192
madd x10,x9,x11,x10
str xzr,[x10]
add x11,sp,#136
add x12,x10,#8
mov w13,#23
copy_event:
ldr x14,[x11],#8
str x14,[x12],#8
subs w13,w13,#1
b.ne copy_event
dmb ish
str x8,[x10]
dmb ish
str x8,[x25,#16]
{count('published')}
unlock:
add x8,x25,#8
stlr wzr,[x8]
b done
duplicate:
{count('deduplicated')}
b unlock
busy:
clrex
{count('contention')}
add x8,x25,#24
mov w12,#4
drop_retry:
ldaxr x9,[x8]
add x9,x9,#1
stxr w10,x9,[x8]
cbz w10,done
subs w12,w12,#1
b.ne drop_retry
clrex
mov w9,#1
str w9,[x25,#32]
b done
reject_disabled:
{count('disabled')}
b done
{''.join('reject_'+reason+':\n'+count(reason)+'mov w8,#'+str(COUNTERS.index(reason))+'\nb minimal_diagnostic\n' for reason in ('null_actor','invalid_slot','null_root','identity_mismatch','invalid_phase','missing_game_info','root_mismatch','context_invalid_slot','context_missing','actor_not_in_current_match'))}
minimal_diagnostic:
// First four failures and powers of two; counters retain every failure.
cmp x9,#4
b.ls diagnostic_publish
sub x10,x9,#1
tst x9,x10
b.ne done
diagnostic_publish:
str w8,[sp,#224]
cmp w8,#13
b.ne diagnostic_no_raw_slot
ldr w9,[sp,#96]
str w9,[sp,#216]
diagnostic_no_raw_slot:
str w20,[sp,#220]
mov w8,#5
str w8,[sp,#212]
add x8,x25,#8
ldaxr w9,[x8]
cbnz w9,busy
mov w10,#1
stxr w9,w10,[x8]
cbnz w9,busy
b publish
done:
ldr x30,[sp,#80]
ldp x27,x28,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#352
ret
''',{'game_info':0x72c3e80,'phase':0x697b60c,'clock':0x6a4bd08,
      'physical':0x72c19f8,'player_info':0x72c1a14,
      'action':0x72d7dc8,'player_state':0x72c40b0,'abilities':0x7301ef8,'skill':0x72b39c4,
      'players':0x72c404c,'count':0x68fb5fc,'entry':0x72f2d04,'identity':0x72f29e0},
      writable={'trace_ring':BUFFER_BYTES},evidence=['native callbacks only, actor supplied by the original getter/selector',
      'private RW ring only; no game object writes, allocation, file IO or Python calls',
      'state changes and one unique motion attempt per actor/frame/family/result/power',
      'failed try-lock increments dropped events; never spin waiting on a game thread'])
    b.add('studio_player_action_state',0x6d3d9dc,save_all()+'''
mov w1,#1
ldrb w2,[x0,#0xad0]
mov w3,w2
mov x4,xzr
mov x5,x30
mov w6,#0
mov w7,#0
bl shared_studio_trace_actor
'''+restore_all()+'''
add x0,x0,#0xad0
'''+jump('resume'),{'resume':0x6d3d9e0})
    b.add('studio_player_motion_selection',0x6d5f2f0,'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
mov x19,x2
mov w20,w0
mov x21,x30
bl original
'''+save_all()+'''
mov x0,xzr
cbz x19,observe
ldr x0,[x19,#0x138]
observe:
mov w1,#4
mov w2,w20
ldr w3,[sp]
mov x4,x19
mov x5,x21
mov w6,#0
mov w7,#0
bl shared_studio_trace_actor
restore:
'''+restore_all()+'''
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
original:
stp d15,d14,[sp,#-0xa0]!
'''+jump('resume'),{'resume':0x6d5f2f4},evidence=['original selector consumes request+138 actor and request+c shot power',
    'execute original selector unchanged, preserve its returned outcome and entire post-call register state'])


def add_shot_observation(b,ai=False):
    """Observe existing request/power boundaries; never change shot policy."""
    b.helper('studio_trace_ai',f'''
stp x19,x20,[sp,#-80]!
stp x21,x30,[sp,#16]
mov x19,x0
mov x20,x1
mov w21,w2
str w3,[sp,#32]
str x4,[sp,#40]
mov w8,#-1
str w8,[sp,#48]
mov x0,xzr
mov w7,#14
orr w7,w7,#0x80000000
cbz x19,emit
cmp w21,#4
b.hi request_context
cmp w21,#2
b.hi power_context
request_context:
ldr x8,[x19]
cbz x8,emit
ldr w9,[x8]
b validate
power_context:
ldr w9,[x19,#4]
validate:
str w9,[sp,#48]
mov w7,#13
orr w7,w7,#0x80000000
cmp w9,#22
b.hs emit
{call('root')}
mov w7,#4
orr w7,w7,#0x80000000
cbz x0,unknown
ldr w1,[sp,#48]
{call('actor')}
ldr w7,[sp,#48]
add w7,w7,#1
b emit
unknown:
mov x0,xzr
emit:
mov w6,w21
ldr x5,[sp,#40]
cmp w21,#4
b.hi candidate_emit
cmp w21,#2
b.hi power_emit
mov w1,#2
ldr w2,[sp,#32]
mov w3,w2
cbz x20,request_emit
ldr w3,[x20,#8]
request_emit:
mov x4,x20
b record
power_emit:
mov w1,#3
ldr w8,[sp,#32]
str w8,[sp,#64]
cbz x20,no_power
ldr w8,[x20,#0xe7c]
b have_power
no_power:
mov w8,#0x7fc00000
have_power:
str w8,[sp,#68]
cbz x20,no_control_word
ldr w8,[x20,#0xff8]
b have_control_word
no_control_word:
mov w8,#0
have_control_word:
str w8,[sp,#72]
add x4,sp,#64
mov w2,#0
mov w3,#0
b record
candidate_emit:
mov w1,#6
ldp w2,w3,[x20]
mov x4,x20
record:
ldr w8,[sp,#48]
bl shared_studio_trace_actor
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#80
ret
''',{'root':0x698f7e0,'actor':0x72c1a14},evidence=['context and actor getters use original native ABI; unconfirmed objects publish only diagnostics'])
    # Replace only the two entry wrappers in the combined bundle. The existing
    # AI helpers remain byte-for-byte generated from their current policy.
    b.rows[:]=[row for row in b.rows if row['address']not in (0x70e7430,0x71a27f0,0x70e57a0)]
    def observe(stage,kind):
        return save_all()+f'''
mov x0,x20
mov x1,x19
mov w2,#{stage}
mov w3,w21
mov x4,x22
bl shared_studio_trace_ai
'''+restore_all() if kind==2 else save_all()+f'''
mov x0,x19
mov x1,x20
mov w2,#{stage}
mov w3,w21
mov x4,x22
bl shared_studio_trace_ai
'''+restore_all()
    address=0x70e7430;word=int.from_bytes(b.engine[address-0x4000:address-0x4000+4],'little')
    b.add('studio_observed_ai_shot_request',address,f'''
stp x19,x20,[sp,#-64]!
stp x21,x22,[sp,#16]
str x30,[sp,#32]
mov x19,x0
mov x20,x1
mov x22,x30
bl original
ldr w21,[x19,#8]
'''+observe(1,2)+('mov x0,x19\nmov x1,x20\nbl shared_studio_ai_prefer_curled_shot\n'if ai else '')+observe(2,2)+f'''
ldr x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#64
ret
original:
.word {word}
'''+jump('resume'),{'resume':address+4})
    b.add('studio_observed_ai_shot_power',0x71a27f0,'''
stp x19,x20,[sp,#-96]!
stp x21,x22,[sp,#16]
str x30,[sp,#32]
mov x19,x1
mov x20,x2
mov x22,x30
bl original
str x0,[sp,#40]
str q0,[sp,#48]
ldr w21,[x20,#0xe7c]
'''+observe(3,3)+('mov x0,x19\nmov x1,x20\nbl shared_studio_ai_bound_shot_power\n'if ai else '')+observe(4,3)+'''
ldr x0,[sp,#40]
ldr q0,[sp,#48]
ldr x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#96
ret
original:
sub sp,sp,#0x110
'''+jump('resume'),{'resume':0x71a27f4})
    # Observe the native result once. Never rerun an evaluator for logging.
    def candidate_observe(stage):
        return save_all()+f'''
ldr x0,[x19,#0x10]
add x1,sp,#{FRAME+48}
mov w2,#{stage}
mov w3,w20
mov x4,x22
bl shared_studio_trace_ai
'''+restore_all()
    address=0x70e57a0
    word=int.from_bytes(b.engine[address-0x4000:address-0x4000+4],'little')
    b.add('studio_observed_ai_candidate_choice',address,f'''
stp x19,x20,[sp,#-96]!
stp x21,x22,[sp,#16]
str x30,[sp,#32]
mov x19,x0
mov x22,x30
bl original
mov w20,w0
mov w21,w0
stp w20,w21,[sp,#48]
mov w8,#-1
stp w8,w8,[sp,#56]
cmp w20,#30
b.hs original_class_done
ldr x8,[x19]
cbz x8,original_class_done
mov w9,#0x49c8
add x8,x8,x9
mov w9,#80
umaddl x8,w20,w9,x8
ldr w8,[x8]
stp w8,w8,[sp,#56]
original_class_done:
'''+candidate_observe(5)+('mov x0,x19\nmov w1,w20\nbl shared_studio_ai_select_cut_in_candidate\nmov w21,w0\n'if ai else '')+'''
str w21,[sp,#52]
cmp w21,#30
b.hs selected_class_done
ldr x8,[x19]
cbz x8,selected_class_done
mov w9,#0x49c8
add x8,x8,x9
mov w9,#80
umaddl x8,w21,w9,x8
ldr w8,[x8]
str w8,[sp,#60]
selected_class_done:
'''+candidate_observe(6)+f'''
mov w0,w21
ldr x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#96
ret
original:
.word {word}
'''+jump('resume'),{'resume':address+4})
