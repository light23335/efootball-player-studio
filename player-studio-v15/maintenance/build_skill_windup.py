"""Per-actor motion-scoped pre-contact rate state.

No motion pointer is retained: state transitions may recycle state handlers.
The caller supplies the native base rate, and commits the returned rate through
the native animation start. Release/cancel restores the saved rate only while
the same actor/context still owns the applied fast rate. A new native rate is
never overwritten by a stale callback.
"""
from skill_hook_ir import call


def add_windup_state(builder):
    builder.helper('studio_windup_slot', '''
cbz x0,none
mov w8,#0x2a38
ldrb w8,[x0,x8]
cmp w8,#22
b.hs none
ldr x9,rows
add x0,x9,x8,lsl #6
ret
none:
mov x0,#0
ret
''', evidence=['22 slots x 64 bytes in separate RW memory', 'slot owns actor pointer, context, motion and generation'],writable={'rows':1408})

    builder.helper('studio_begin_windup', f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
mov x19,x0
fmov s8,s0
fmov s9,s1
bl shared_studio_windup_slot
cbz x0,done
mov x20,x0
str wzr,[x20,#20]
fmov s0,s8
fmov s1,s9
fmov w8,s0
ubfx w8,w8,#23,#8
cmp w8,#255
b.eq done
fmov w8,s1
ubfx w8,w8,#23,#8
cmp w8,#255
b.eq done
fcmp s0,#0.0
b.le done
fcmp s1,#0.0
b.le done
fmov s2,#1.0
fcmp s1,s2
b.gt done
fdiv s0,s8,s9
fmov w8,s0
ubfx w8,w8,#23,#8
cmp w8,#255
b.eq done
str x19,[x20]
ldr x8,[x19,#0x4620]
str x8,[x20,#8]
mov w8,#0x2dce
ldrh w8,[x19,x8]
str w8,[x20,#16]
mov w8,#1
str w8,[x20,#20]
str s8,[x20,#24]
str s0,[x20,#28]
str s9,[x20,#32]
ldr x8,[x20,#40]
add x8,x8,#1
str x8,[x20,#40]
fmov s8,s0
done:
fmov s0,s8
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''', evidence=['base rate saved exactly', 'fast rate = R / duration factor', 'no repeated multiplier on current rate'])

    builder.helper('studio_windup_original_clip_rate', '''
stp x19,x30,[sp,#-16]!
mov x19,x0
bl shared_studio_windup_slot
cbz x0,done
ldr w8,[x0,#20]
cbz w8,done
ldr x8,[x0]
cmp x8,x19
b.ne done
ldr x8,[x0,#8]
ldr x9,[x19,#0x4620]
cmp x8,x9
b.ne done
ldr w8,[x0,#16]
mov w9,#0x2dce
ldrh w9,[x19,x9]
cmp w8,w9
b.ne done
fmov w8,s0
ldr w9,[x0,#28]
cmp w8,w9
b.ne done
ldr s0,[x0,#24]
done:
ldp x19,x30,[sp],#16
ret
''', evidence=['use saved R only for the same prepared motion and its fast-rate input',
               'native start-offset compensation must not cancel the intended pre-contact speed-up'])

    builder.helper('studio_restore_windup', f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
mov x19,x0
mov w21,w1
bl shared_studio_windup_slot
cbz x0,no
mov x20,x0
ldr x8,[x20]
cmp x8,x19
b.ne no
ldr w8,[x20,#20]
cbz w8,no
str wzr,[x20,#20]
ldr x8,[x19,#0x4620]
ldr x9,[x20,#8]
cmp x8,x9
b.ne no
cbnz w21,check_rate
mov w8,#0x2dce
ldrh w8,[x19,x8]
ldr w9,[x20,#16]
cmp w8,w9
b.ne no
check_rate:
mov w8,#0x4244
ldr w8,[x19,x8]
ldr w9,[x20,#28]
cmp w8,w9
b.ne no
mov x0,x19
ldr s0,[x20,#24]
{call('native_rate')}
mov w0,#1
b done
no:
mov w0,#0
done:
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''', {'native_rate': 0x6ddbf6c}, evidence=[
        'reason 0: release requires the same motion; reason 1: cancellation may change motion',
        'clear active phase before native call', 'restore original R, never literal 1.0',
        'do not overwrite changed native rate or context'])
