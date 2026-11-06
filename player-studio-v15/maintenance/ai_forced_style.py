"""Rank native-executable style actions without the former comparison gates."""
from skill_hook_ir import call


def add_forced_style_helpers(b):
    b.helper('studio_ai_forced_style_evaluate',f'''
stp x19,x20,[sp,#-160]!
stp x21,x22,[sp,#16]
stp x23,x30,[sp,#32]
stp d8,d9,[sp,#48]
stp d10,d11,[sp,#64]
stp d12,d13,[sp,#80]
stp d14,d15,[sp,#96]
mov x19,x0
mov x20,x1
mov x21,x2
str xzr,[x21]
str xzr,[x21,#8]
ldr w22,[x20]
ldr w8,[x19]
add x9,x19,#32
add x9,x9,w8,uxtw #4
ldr s8,[x9]
ldr s9,[x9,#8]
mov w23,#1
cmp w22,#3
b.eq route
cmp w22,#1
b.ne done
ldr w8,[x20,#8]
cmp w8,#1
b.hi done
ldr s10,[x20,#0xc]
ldr s0,[x19,#8]
ldr s1,[x19,#12]
fmul s0,s0,s1
fsub s0,s10,s0
fabs s0,s0
fmov s1,#3.0
fcmp s0,s1
b.vs done
b.gt done
ldr s0,[x20,#0x10]
fcmp s0,#0.0
b.vs done
b.lt done
fmov s1,#3.5
fcmp s0,s1
b.gt done
ldr s11,[x20,#0x14]
fabs s0,s11
fmov s1,#4.0
fcmp s0,s1
b.vs done
b.gt done
orr w23,w23,#4
fmov s10,s8
fmov s11,s9
b score
route:
ldr w8,[x20,#0x2c]
sub w8,w8,#2
cmp w8,#1
b.hi done
ldr s0,[x20,#0x30]
fabs s1,s0
ldr s2,heading_limit
fcmp s1,s2
b.vs done
b.gt done
ldr w8,[x19]
add x0,x19,#32
add x0,x0,w8,uxtw #4
fmov s1,#4.0
{call('advance')}
fmov s10,s0
fmov s11,s2
fabs s0,s10
ldr s1,[x19,#12]
fcmp s0,s1
b.vs done
b.gt done
fabs s0,s11
ldr s1,[x19,#16]
fcmp s0,s1
b.vs done
b.gt done
// Forward inward routes implement Incisive without a shooting skill or
// attacking-half gate. Central forward routes stay central.
fsub s0,s10,s8
ldr s1,[x19,#8]
fmul s0,s0,s1
fcmp s0,#0.0
b.le progress
fabs s0,s9
fabs s1,s11
fsub s2,s0,s1
fmov s3,#0.5
fcmp s2,s3
b.ge inward
fmov s2,#1.0
fcmp s0,s2
b.gt progress
fcmp s1,s2
b.gt progress
fsub s0,s10,s8
ldr s1,[x19,#8]
fmul s0,s0,s1
fcmp s0,#0.0
b.le progress
inward:
orr w23,w23,#8
orr w23,w23,#4
progress:
ldr s2,[x19,#8]
ldr s3,[x19,#12]
fmul s0,s8,s2
fsub s0,s3,s0
fmul s0,s0,s0
fmadd s0,s9,s9,s0
fmul s1,s10,s2
fsub s1,s3,s1
fmul s1,s1,s1
fmadd s1,s11,s11,s1
fcmp s1,s0
b.ge score
orr w23,w23,#4
score:
mov x0,x19
fmov s0,s10
fmov s1,s11
bl shared_studio_ai_opportunity_position
str s0,[x21]
ldr w8,[x19,#28]
and w8,w8,#0xff
cmp w8,#3
b.ne ready
fmov s0,s10
fmov s1,s11
cmp w22,#3
b.ne current_heading
ldr s2,[x20,#0x30]
b posture
current_heading:
ldr w8,[x19]
add x9,x19,#32
add x9,x9,w8,uxtw #4
ldr s2,[x9,#4]
posture:
mov x0,x19
bl shared_studio_ai_blitz_posture
cbz w0,unknown
str s0,[x21,#8]
str s1,[x21,#12]
ldr s2,posture_ready_angle
fcmp s0,s2
b.gt publish
ldr s2,foot_space_sq
fcmp s1,s2
b.lt publish
ready:
orr w23,w23,#16
b publish
unknown:
ldr s0,unknown_posture
str s0,[x21,#8]
publish:
str w23,[x21,#4]
done:
ldp d14,d15,[sp,#96]
ldp d12,d13,[sp,#80]
ldp d10,d11,[sp,#64]
ldp d8,d9,[sp,#48]
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#160
ret
''',{'advance':0x6d3a784},
        {'heading_limit':360.,'posture_ready_angle':35.,'foot_space_sq':3.0625,'unknown_posture':180.},
        ['only decoded native shots/moving dribbles; continuation veto remains authoritative',
         'no original-score window, protected passing priority, shot range or pressure-clearance gate',
         'Incisive: inward/central-forward native route; Lone Wolf keeps existing shot/stance priorities'])
