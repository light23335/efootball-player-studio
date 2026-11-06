"""One private70% style ticket per individual possession, including handoffs."""
import struct
from skill_hook_ir import call,jump,save_all,restore_all


def add_possession_helpers(b):
    b.helper('studio_ai_possession_draw','''
eor x8,x0,x0,lsr #32
eor w8,w8,w1
mov w10,#0x9e37
madd w8,w4,w10,w8
eor w8,w8,w2
eor w8,w8,w3
eor w8,w8,w8,lsr #16
mov w10,#0x7feb
movk w10,#0x352d,lsl #16
mul w8,w8,w10
eor w8,w8,w8,lsr #15
mov w10,#0x846c
movk w10,#0x68b9,lsl #16
mul w8,w8,w10
eor w8,w8,w8,lsr #16
mov w10,#10
udiv w11,w8,w10
msub w0,w11,w10,w8
ret
''',evidence=['private roll0..9;0..6 enables the possession; no native RNG',
              'leaf contract preserves X9 and X12 used by the locked ticket store'])
    # x0 live ball manager, w1 actual owner, w2 observe/decide, w3 query slot,
    # x4 live actor, w5 native clock, x6 current root. No cached pointer is read.
    b.helper('studio_ai_possession_state','''
stp x19,x20,[sp,#-80]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
mov x19,x0
mov w20,w1
mov w21,w2
mov w22,w3
mov x23,x4
mov w24,w5
mov x25,x6
cbz x19,quiet_unlocked
ldr x9,records
mov w17,#64
lock_try:
ldaxr w8,[x9]
cbnz w8,lock_retry
mov w11,#1
stxr w10,w11,[x9]
cbz w10,lock_held
lock_retry:
clrex
subs w17,w17,#1
b.ne lock_try
b busy_unlocked
lock_held:
ldr w16,[x9,#8]
add w16,w16,#1
str w16,[x9,#8]
eor x8,x19,x19,lsr #32
lsr x8,x8,#4
and w11,w8,#255
mov w13,#256
mov x15,xzr
mov w17,#0
lookup:
add x12,x9,#64
add x12,x12,x11,lsl #6
ldr x14,[x12]
cmp x14,x19
b.eq found
cbz x14,empty
ldr w8,[x12,#60]
sub w8,w16,w8
cmp w8,w17
csel x15,x12,x15,hi
csel w17,w8,w17,hi
add w11,w11,#1
and w11,w11,#255
subs w13,w13,#1
b.ne lookup
cbz w21,quiet_locked
cbz x15,busy_locked
mov x12,x15
b initialize
empty:
cbz w21,quiet_locked
initialize:
stp xzr,xzr,[x12]
stp xzr,xzr,[x12,#16]
stp xzr,xzr,[x12,#32]
stp xzr,xzr,[x12,#48]
mov w8,#-1
str w8,[x12,#12]
str x25,[x12,#48]
str w24,[x12,#24]
str x19,[x12]
found:
str w16,[x12,#60]
cbz w21,observe_owner
ldr x8,[x12,#48]
cmp x8,x25
b.ne reset_context
ldr w8,[x12,#24]
cmp w24,w8
b.hs context_ready
reset_context:
ldr w8,[x9,#16]
add w8,w8,#1
str w8,[x9,#16]
str w8,[x12,#8]
str wzr,[x12,#16]
str xzr,[x12,#32]
str xzr,[x12,#40]
context_ready:
str x25,[x12,#48]
str w24,[x12,#24]
observe_owner:
ldr w8,[x12,#12]
cmp w8,w20
b.eq decide
str w20,[x12,#12]
ldr w8,[x9,#16]
add w8,w8,#1
str w8,[x9,#16]
str w8,[x12,#8]
str wzr,[x12,#16]
str xzr,[x12,#32]
str xzr,[x12,#40]
cmp w20,#22
b.lo draw
decide:
cbz w21,quiet_locked
cmp w20,#22
b.hs quiet_locked
cmp w20,w22
b.ne quiet_locked
ldr w8,[x12,#8]
ldr w10,[x12,#16]
cmp w8,w10
b.ne draw
ldr w8,[x12,#20]
cmp w8,w20
b.ne draw
ldr x8,[x12,#40]
cbz x8,bind_actor
cmp x8,x23
b.eq ticket_ready
// A different player/actor reusing the slot cannot inherit its predecessor.
ldr w8,[x9,#16]
add w8,w8,#1
str w8,[x9,#16]
str w8,[x12,#8]
str xzr,[x12,#40]
draw:
cmp w20,#22
b.hs quiet_locked
ldr w4,[x9,#12]
add w4,w4,#1
str w4,[x9,#12]
str w4,[x12,#28]
mov x0,x19
ldr w1,[x12,#8]
mov w2,w20
ldr w3,[x12,#24]
bl shared_studio_ai_possession_draw
str w0,[x12,#36]
cmp w0,#7
cset w8,lo
str w8,[x12,#32]
ldr w8,[x12,#8]
str w8,[x12,#16]
str w20,[x12,#20]
cbz w21,quiet_locked
cmp w20,w22
b.ne quiet_locked
bind_actor:
str x23,[x12,#40]
ticket_ready:
ldr w0,[x12,#32]
ldr w1,[x12,#8]
ldr w8,[x12,#36]
orr w1,w8,w1,lsl #4
mov w2,#2
mov w8,#1
cmp w0,#0
csel w2,w8,w2,ne
b unlock
quiet_locked:
mov w0,#0
mov w1,#0
mov w2,#0
b unlock
busy_locked:
mov w0,#0
mov w1,#0
mov w2,#3
unlock:
stlr wzr,[x9]
b done
busy_unlocked:
mov w0,#0
mov w1,#0
mov w2,#3
b done
quiet_unlocked:
mov w0,#0
mov w1,#0
mov w2,#0
done:
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#80
ret
''',writable={'records':64+256*64},evidence=[
        'registered live ball managers have independent bounded possession records',
        'every native holder change advances an epoch, including teammate/unknown owners',
        'one stored roll per epoch; rejected rolls remain rejected until a new possession',
        'bounded atomic lock; no native call inside the locked mutation except the pure private roll',
        'root/clock rewind and actor replacement invalidate prior tickets; no saved pointer dereference'])
    at=0x6acd550;original=b.engine[at-0x4000:at-0x4000+20]
    if struct.unpack_from('<I',original,16)[0]!=0xd65f03c0:
        raise ValueError('Native ball-holder setter no longer has its audited five-instruction layout')
    original_words='\n'.join('.word '+str(w)for w in struct.unpack('<5I',original))
    b.add('studio_ai_possession_holder_changed',at,f'''
sub sp,sp,#16
str x30,[sp]
bl original
'''+save_all()+'''
mov w1,w9
mov w2,#0
mov w3,#0
mov x4,xzr
mov w5,#0
mov x6,xzr
bl shared_studio_ai_possession_state
'''+restore_all()+f'''
ldr x30,[sp]
add sp,sp,#16
ret
original:
{original_words}
''',evidence=[
        '6acd550..560 copies the new holder into live ball-manager+28780',
        '733d574 ->72c3ddc ->6b60a00 reads that exact field',
        'observe AFTER original store; preserve original outputs and all saved GPR/SIMD/NZCV'])
    b.helper('studio_ai_possession_profile',f'''
stp x19,x20,[sp,#-96]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
str x30,[sp,#64]
str xzr,[sp,#72]
mov w8,#-1
str w8,[sp,#88]
mov w24,#0
mov w8,#1
str w8,[sp,#80]
cbz x0,profile_done
mov x19,x0
ldr x8,[x0]
cbz x8,profile_done
ldr w21,[x8]
ldr x19,[x19,#0x18]
cbz x19,profile_done
mov w8,#3
str w8,[sp,#80]
cmp w21,#22
b.hs profile_done
{call('root')}
mov x20,x0
cbz x20,profile_done
{call('game_info')}
mov x26,x0
mov w8,#4
str w8,[sp,#80]
cbz x26,profile_done
{call('phase')}
mov w8,#5
str w8,[sp,#80]
cmp w0,#1
b.ne profile_done
mov x0,x20
mov w1,w21
{call('player_state')}
mov x22,x0
mov w8,#6
str w8,[sp,#80]
cbz x22,profile_done
{call('abilities')}
mov x23,x0
cbz x23,profile_done
ldr w25,[x23,#0xd4]
tbnz w25,#7,profile_skills
mov w8,#16
str w8,[sp,#80]
tbz w25,#4,profile_done
bl shared_studio_ai_preference_enabled
mov w8,#7
str w8,[sp,#80]
cbz w0,profile_done
profile_skills:
mov w24,#1
mov x0,x23
mov w1,#51
{call('skill')}
tbz w0,#0,profile_curler
mov w24,#3
b profile_gate
profile_curler:
mov x0,x23
mov w1,#7
{call('skill')}
tbz w0,#0,profile_gate
mov w24,#2
profile_gate:
mov w8,#19
str w8,[sp,#80]
ldr x8,[x19,#0x10]
cbz x8,profile_off
mov x0,x26
{call('clock')}
str w0,[sp,#84]
mov x0,x19
{call('holder')}
mov w1,w0
str w0,[sp,#88]
ldr x0,[x19,#0x10]
mov w2,#1
mov w3,w21
mov x4,x22
ldr w5,[sp,#84]
mov x6,x20
bl shared_studio_ai_possession_state
mov w8,#17
str w8,[sp,#80]
cbz w2,profile_off
cmp w2,#3
b.ne profile_trial
mov w8,#20
str w8,[sp,#80]
b profile_off
profile_trial:
str w1,[sp,#72]
mov w8,#0x1000
cbz w0,profile_rejected
orr w8,w8,#0x2000
str w8,[sp,#76]
str wzr,[sp,#80]
b profile_done
profile_rejected:
str w8,[sp,#76]
mov w8,#18
str w8,[sp,#80]
profile_off:
mov w24,#0
profile_done:
mov w0,w24
ldr w4,[sp,#80]
ldr w5,[sp,#72]
ldr w6,[sp,#76]
ldr w7,[sp,#88]
ldr x30,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#96
ret
''',{'root':0x698f7e0,'game_info':0x6a64350,'phase':0x697b60c,
      'player_state':0x72c1a30,'abilities':0x7301ef8,'skill':0x72b39c4,
      'clock':0x6a4bd08,'holder':0x733d574},evidence=[
        'style bit4/7 suffices; candidate decisions no longer require a shooting skill or range',
        'one common70% ticket for Incisive, Lone Wolf and their combination',
        '733d574 takes the live AI GameContext at player-context+18, not the global GameModel',
        'normal shot skill subtype/power logic is a separate feature'])
