"""Contract trajectory-based miss errors against a zero-error native solve.

The original contact solver is deterministic and leaves its input vectors
unchanged. A second solve uses zero angular/contact offsets and speed ratio 1,
with private outputs. This preserves its reference frame and systematic math;
only the difference caused by sampled miss inputs is contracted. No RNG or
match-state routine is replayed, and the actual spin output is left untouched.
"""
import struct
from skill_hook_ir import call,jump


def add_trajectory(builder):
    builder.helper('studio_vector_polar',f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
mov x19,x0
mov x20,x1
{call('yaw')}
str s0,[x20]
ldr s8,[x19,#4]
mov x0,x19
{call('horizontal')}
fmov s1,s0
fmov s0,s8
{call('inclination')}
{call('degrees')}
str s0,[x20,#4]
mov x0,x19
{call('magnitude')}
str s0,[x20,#8]
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''',{'yaw':0x6910428,'horizontal':0x6aedd24,'inclination':0x6d4e5a4,
     'degrees':0x6910b50,'magnitude':0x6acd624},
     evidence=['same yaw, inclination and magnitude conversion as 0x6d52b14..0x6d52b54'])

    builder.helper('studio_contract_vector_error',f'''
stp x19,x20,[sp,#-160]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
stp d10,d11,[sp,#48]
mov x19,x1
mov x20,x0
fmov s8,s0
fmov s9,s1
fmov s10,s2
add x1,sp,#80
bl shared_studio_vector_polar
mov x0,x19
add x1,sp,#96
bl shared_studio_vector_polar
ldr d0,[sp,#96]
ldr w8,[sp,#104]
str d0,[sp,#112]
str w8,[sp,#120]
mov w8,#0
finite:
add x9,sp,#80
ldr w9,[x9,w8,uxtw #2]
ubfx w9,w9,#23,#8
cmp w9,#255
b.eq no
add w8,w8,#1
cmp w8,#3
b.ne finite
mov w8,#0
finite_actual:
add x9,sp,#96
ldr w9,[x9,w8,uxtw #2]
ubfx w9,w9,#23,#8
cmp w9,#255
b.eq no
add w8,w8,#1
cmp w8,#3
b.ne finite_actual
fmov s0,#1.0
fcmp s8,s0
b.eq pitch
ldr s0,[sp,#96]
ldr s1,[sp,#80]
fsub s2,s0,s1
ldr s3,half_turn
ldr s4,full_turn
fcmp s2,s3
b.le lower
fsub s2,s2,s4
lower:
fneg s3,s3
fcmp s2,s3
b.ge wrapped
fadd s2,s2,s4
wrapped:
fmul s2,s2,s8
fadd s0,s1,s2
fcmp s0,s4
b.lt below
fsub s0,s0,s4
below:
fcmp s0,#0.0
b.ge yaw_done
fadd s0,s0,s4
yaw_done:
str s0,[sp,#112]
pitch:
fmov s0,#1.0
fcmp s9,s0
b.eq speed
ldr s0,[sp,#100]
ldr s1,[sp,#84]
fsub s0,s0,s1
fmul s0,s0,s9
fadd s0,s1,s0
str s0,[sp,#116]
speed:
fmov s0,#1.0
fcmp s10,s0
b.eq changed
ldr s0,[sp,#104]
ldr s1,[sp,#88]
fsub s0,s0,s1
fmul s0,s0,s10
fadd s0,s1,s0
str s0,[sp,#120]
changed:
mov w8,#0
compare:
add x9,sp,#96
add x10,sp,#112
ldr s0,[x9,w8,uxtw #2]
ldr s1,[x10,w8,uxtw #2]
fcmp s0,s1
b.ne render
add w8,w8,#1
cmp w8,#3
b.ne compare
b no
render:
ldr s8,[sp,#120]
ldr s9,[sp,#116]
fmov s0,s9
fmov s1,#1.0
{call('pitch_cos')}
fmul s10,s8,s0
add x0,sp,#112
fmov s0,#1.0
{call('yaw_sin')}
fmul s0,s10,s0
str s0,[x19]
fmov s0,s9
fmov s1,#1.0
{call('pitch_sin')}
fmul s0,s8,s0
str s0,[x19,#4]
add x0,sp,#112
fmov s0,#1.0
{call('yaw_cos')}
fmul s0,s10,s0
str s0,[x19,#8]
mov w0,#1
b done
no:
mov w0,#0
done:
ldp d10,d11,[sp,#48]
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#160
ret
''',{'pitch_cos':0x6ae6be0,'pitch_sin':0x7360d24,
     'yaw_sin':0x6ae6bbc,'yaw_cos':0x6ae6b98},
     {'half_turn':180.,'full_turn':360.},
     ['shortest signed yaw and complete inclination difference from the zero-error native result',
      'speed is contracted only if its component factor is below one',
      'no selected difference means no output write, preserving an exact zero error'])

    address=0x6d4e948
    displaced=struct.unpack_from('<I',builder.engine,address-16384)[0]
    code=f'''
stp x19,x20,[sp,#-256]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
stp d8,d9,[sp,#64]
stp d10,d11,[sp,#80]
mov x20,x0
mov x21,x1
mov x22,x2
mov x23,x3
mov x24,x4
ldr d16,[x0]
ldr w8,[x0,#8]
str d16,[sp,#112]
str w8,[sp,#120]
ldr d16,[x1]
ldr w8,[x1,#8]
str d16,[sp,#128]
str w8,[sp,#136]
bl original
str x0,[sp,#192]
ldr x8,[sp,#56]
ldr x9,actual_call_a
cmp x8,x9
b.eq qualified_caller
ldr x9,actual_call_b
cmp x8,x9
b.ne done
qualified_caller:
ldr w8,[sp,#{256+0x134}]
cmp w8,#2
b.hi done
mov x0,x19
bl shared_studio_committed_error_factors
fmov s8,s0
fmov s9,s1
fmov s10,s2
fmov s3,#1.0
fcmp s0,s3
b.ne baseline
fcmp s1,s3
b.ne baseline
fcmp s2,s3
b.eq done
baseline:
str xzr,[sp,#144]
str wzr,[sp,#152]
add x0,sp,#112
add x1,sp,#128
add x2,sp,#144
add x3,sp,#160
add x4,sp,#176
fmov s0,wzr
fmov s1,wzr
fmov s2,#1.0
bl original
add x0,sp,#160
mov x1,x23
fmov s0,s8
fmov s1,s9
fmov s2,s10
bl shared_studio_contract_vector_error
done:
ldr x0,[sp,#192]
ldp d10,d11,[sp,#80]
ldp d8,d9,[sp,#64]
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#256
ret
original:
.word {displaced}
{jump('resume')}
'''
    builder.add('studio_trajectory_miss_scatter',address,code,
        {'actual_call_a':0x6d535bc,'actual_call_b':0x6d53694,'resume':address+4},
        evidence=['only the two actual miss-category contact-solver calls are eligible',
                  'caller category must be 0..2; generators 3/4 cannot be contracted twice',
                  'private zero-error solve; no RNG or player state is replayed',
                  'actual spin output and original input vectors remain unchanged'])
