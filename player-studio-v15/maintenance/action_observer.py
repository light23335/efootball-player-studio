"""Read-only native action/motion observation with a bounded private ring."""
from skill_hook_ir import call,jump,save_all,restore_all,FRAME

BUFFER_BYTES=528384


def add_observer(b):
    b.helper('studio_action_trace_fence','dmb ish\nret\n')
    b.helper('studio_trace_actor',f'''
sub sp,sp,#304
stp x19,x20,[sp]
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
stp x27,x28,[sp,#64]
str x30,[sp,#80]
mov x19,x0
mov w20,w1
mov w21,w2
mov w22,w3
mov x23,x4
mov x24,x5
ldr x25,trace_ring
ldr w8,[x25,#4]
cbz w8,done
cbz x19,done
mov w8,#0x2a38
ldrb w26,[x19,x8]
cmp w26,#22
b.hs done
ldr x27,[x19,#0x4620]
cbz x27,done
mov x0,x27
mov w1,w26
{call('current_actor')}
cmp x0,x19
b.ne done
mov x0,x27
{call('game_info')}
cbz x0,done
mov x28,x0
{call('phase')}
cmp w0,#16
b.hi done
str w0,[sp,#108]
mov x0,x28
{call('clock')}
str w0,[sp,#104]
add x8,sp,#128
mov w9,#8
clear_event:
stp xzr,xzr,[x8],#16
subs w9,w9,#1
b.ne clear_event
str x27,[sp,#136]
str x19,[sp,#144]
ldp w8,w9,[sp,#104]
stp w8,w9,[sp,#152]
str w26,[sp,#160]
ldrb w8,[x19,#0xad0]
str w8,[sp,#164]
mov w0,w26
{call('action')}
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
ldr w8,[x19,#0x4f4]
ldr w9,[x19,#0x4f8]
ldr w10,[x19,#0x4fc]
str w8,[sp,#180]
str w9,[sp,#184]
str w10,[sp,#188]
mov w8,#0x7fc00000
str w8,[sp,#204]
str w8,[sp,#208]
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
identity_done:
mov x0,x27
mov w1,w26
{call('player_state')}
cbz x0,lock_ring
{call('abilities')}
cbz x0,lock_ring
mov x28,x0
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
cmp w8,w9
b.hs unlock
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
b.eq unlock
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
add x10,x10,x9,lsl #7
str xzr,[x10]
add x11,sp,#136
add x12,x10,#8
mov w13,#15
copy_event:
ldr x14,[x11],#8
str x14,[x12],#8
subs w13,w13,#1
b.ne copy_event
dmb ish
str x8,[x10]
dmb ish
str x8,[x25,#16]
unlock:
add x8,x25,#8
stlr wzr,[x8]
b done
busy:
clrex
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
done:
ldr x30,[sp,#80]
ldp x27,x28,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#304
ret
''',{'current_actor':0x72c408c,'game_info':0x72c3e80,'phase':0x697b60c,'clock':0x6a4bd08,
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
cbz x19,restore
ldr x0,[x19,#0x138]
mov w1,#4
mov w2,w20
ldr w3,[sp]
mov x4,x19
mov x5,x21
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
