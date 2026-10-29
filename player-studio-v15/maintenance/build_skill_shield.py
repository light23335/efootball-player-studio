"""Opponent-specific resistance in an already selected native shield contest.

The native contact selector 0x6ed9cd8 classifies a rear opponent as relation 2.
0x6ed9ea0 uses that relation for contact variants 11..15; 0x72d5864 already
gives those selected variants a local resistance bonus. We extend that local
input, only for the live settlement caller, with possession, the same contact
opponent, distance and body-facing checked again at settlement.
"""
from skill_hook_ir import call, jump, save_all, restore_all, FRAME, SIMD


def add_shield(builder):
    # ctx, first ID, second ID, holder ID, first/second state, first/second
    # PlayerInfo. Returns 1/2 for the eligible holder, otherwise zero.
    builder.helper('studio_shield_contest_side',f'''
stp x19,x20,[sp,#-112]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
mov x21,x0
mov w19,w1
mov w20,w2
mov x22,x4
mov x23,x6
mov x24,x7
mov w25,#1
cmp w3,w1
b.eq holder
cmp w3,w2
b.ne no
mov w19,w2
mov w20,w1
mov x22,x5
mov x23,x7
mov x24,x6
mov w25,#2
holder:
cbz x21,no
cbz x22,no
cbz x23,no
cbz x24,no
cmp w19,#22
b.hs no
cmp w20,#22
b.hs no
mov w0,w19
{call('team')}
str w0,[sp,#64]
mov w0,w20
{call('team')}
ldr w8,[sp,#64]
cmp w0,w8
b.eq no
ldrb w8,[x22]
cmp w8,#0x54
b.ne no
ldrb w8,[x22,#0x38]
cmp w8,#15
b.hi no
mov w9,#0xd800
lsr w9,w9,w8
tbz w9,#0,no
{call('root')}
cbz x0,no
{call('game_info')}
cbz x0,no
mov w8,#0x4202
add x8,x0,x8
ldrb w9,[x8,w19,uxtw]
cbz w9,no
ldrb w9,[x8,w20,uxtw]
cbz w9,no
mov x0,x21
mov w1,w19
{call('data')}
cbz x0,no
{call('parameters')}
cbz x0,no
mov w1,#78
{call('flag')}
tbz w0,#0,no
mov x0,x23
mov w1,#0
{call('interaction')}
ldrb w8,[x0,#0x55]
cbz w8,no
ldr w8,[x0]
cmp w8,w20
b.ne no
ldr s0,[x24,#0x4f4]
ldr s1,[x23,#0x4f4]
fsub s0,s0,s1
ldr s2,[x24,#0x4fc]
ldr s3,[x23,#0x4fc]
fsub s2,s2,s3
str s0,[sp,#80]
str wzr,[sp,#84]
str s2,[sp,#88]
fmul s0,s0,s0
fmul s2,s2,s2
fadd s0,s0,s2
ldr s1,shield_distance_squared
fcmp s0,s1
b.vs no
b.gt no
fcmp s0,#0.0
b.le no
ldr w8,[x23,#0x4ec]
ubfx w8,w8,#23,#8
cmp w8,#255
b.eq no
add x0,sp,#80
{call('yaw')}
str s0,[sp,#96]
add x0,x23,#0x4ec
add x1,sp,#96
{call('angle_difference')}
ldr s1,rear_angle
fcmp s0,s1
b.vs no
b.lt no
mov w0,w25
b done
no:
mov w0,#0
done:
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#112
ret
''',{'team':0x697d0f8,'root':0x698f7e0,'game_info':0x6a64350,
     'data':0x72c40b0,'parameters':0x7301ef8,'flag':0x72b39c4,
     'interaction':0x6ae8604,'yaw':0x6910428,'angle_difference':0x6ad3e50},
     {'rear_angle':120.,'shield_distance_squared':3.24},evidence=[
        '0x6ed9cd8: body heading +0x4ec, actual counterpart, native rear relation 2',
        '0x6ed9ea0: rear-contact variants 11/12/14/15; 0x72d5dd0..0x72d5e3c: local resistance',
        'requires an already committed native contact variant, current holder and same contact opponent',
        'both in-field, opposing teams, ground distance <=1.8 m and body rear cone +/-60 degrees',
        'no panel writes, no persistent rate state and no random draws'])

    code=save_all()+f'''
ldr x8,[sp,#{FRAME+0x78}]
ldr x9,live_contact_return
cmp x8,x9
b.ne done
mov x0,x22
mov w1,w23
mov w2,w21
mov w3,w20
mov x4,x19
mov x5,x26
mov x6,x25
mov x7,x24
bl shared_studio_shield_contest_side
cmp w0,#1
b.eq first
cmp w0,#2
b.ne done
add x8,sp,#{SIMD+9*16}
b resistance
first:
add x8,sp,#{SIMD+8*16}
resistance:
ldr w9,[x8]
ubfx w9,w9,#23,#8
cmp w9,#255
b.eq done
ldr s0,[x8]
fcmp s0,#0.0
b.le done
ldr s1,resistance_factor
fmul s0,s0,s1
str s0,[x8]
done:
'''+restore_all()+f'''
ldr w8,[sp,#0x1c]
{jump('resume')}
'''
    builder.add('studio_shield_local_contest_resistance',0x72d5e40,code,
                {'live_contact_return':0x6ddaca4,'resume':0x72d5e44},
                {'resistance_factor':1.5},evidence=[
                    'live 0x6ddab4c -> 0x72d5864 settlement only; prediction calls are unchanged',
                    'multiply only the qualified holder local S8/S9 resistance before the original ratio',
                    'the original collision matrix, ball-holder priority and displacement calculation remain native'])
