"""Active-player position and team-side predicates for match skill effects.

Native field convention is X along the pitch and Z across it. PenaltyAreaX is
the inner longitudinal line, not the box depth. Team +0x28c supplies the current
sign, so the opponent's box follows a half-time side switch.
"""
from skill_hook_ir import call


def add_conditions(builder):
    builder.helper('studio_classify_committed_kick_request', f'''
stp x19,x20,[sp,#-32]!
stp x21,x30,[sp,#16]
mov x19,x0
mov w21,#20
mov w20,#0
cbz x19,done
ldr x0,[x19,#8]
cbz x0,done
ldr w1,[x19]
ldr w2,[x19,#0x1c]
{call('native_kind')}
mov w21,w0
ldr w8,[x19]
cmp w8,#10
b.eq shot
cmp w8,#8
b.eq air
cmp w8,#9
b.ne done
ldr w8,[x19,#0x1c]
cmp w8,#24
b.ne regular
sub w8,w21,#1
cmp w8,#3
b.hi done
cmp w21,#4
mov w20,#2
cinc w20,w20,eq
b done
regular:
cmp w8,#22
b.eq regular_pass
cmp w8,#23
b.ne done
regular_pass:
sub w8,w21,#1
cmp w8,#1
b.hi air
mov w20,#1
b done
air:
sub w8,w21,#4
cmp w8,#2
b.hi done
mov w20,#4
b done
shot:
sub w8,w21,#9
cmp w8,#2
b.hi done
mov w20,#5
done:
mov w0,w20
mov w1,w21
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#32
ret
''', {'native_kind': 0x6d45fc4}, evidence=[
        'original request header state and subtype consumed by 0x6d5a7fc',
        'original 0x6d45fc4 converts packed motion mode into final kick kind',
        'native relative enum table 0xc91308: 22 SHORT_PASS, 23 POST_PLAY_PASS, 24 THROUGH_PASS',
        '0x70e74d0 maps input pass type 3 to behavior 24 and retains the loft flag',
        'ordinary short passes require behavior 22/23; unknown types never inherit this bonus',
        'state 9 mode 3 is native kind 4; behavior 24 retains lofted-through identity',
        'result: 0 unsupported, 1 short, 2 ground through, 3 lofted through, 4 air, 5 shot',
        'caller must compare expected native kind with the committed final action to reject fallback'])

    builder.helper('studio_nearest_live_opponent', f'''
stp x19,x20,[sp,#-96]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
stp d8,d9,[sp,#64]
str d10,[sp,#80]
mov x19,x0
mov x24,#0
ldr s10,infinity
cbz x19,done
mov w8,#0x2a38
ldrb w0,[x19,x8]
cmp w0,#22
b.hs done
{call('team')}
mov w22,w0
ldr s8,[x19,#8]
ldr s9,[x19,#16]
fcmp s8,s8
b.vs done
fcmp s9,s9
b.vs done
{call('root')}
cbz x0,done
mov x20,x0
{call('game_info')}
cbz x0,done
mov x21,x0
mov w23,#0
loop:
mov w0,w23
{call('team')}
cmp w0,w22
b.eq next
mov w8,#0x4202
add x8,x21,x8
ldrb w8,[x8,w23,uxtw]
cbz w8,next
mov x0,x20
mov w1,w23
{call('actor')}
cbz x0,next
ldr s0,[x0,#0x4f4]
ldr s1,[x0,#0x4fc]
fsub s0,s0,s8
fsub s1,s1,s9
fmul s0,s0,s0
fmul s1,s1,s1
fadd s0,s0,s1
fcmp s0,s10
b.vs next
b.ge next
mov x24,x0
fmov s10,s0
next:
add w23,w23,#1
cmp w23,#22
b.lo loop
done:
mov x0,x24
fmov s0,s10
ldr d10,[sp,#80]
ldp d8,d9,[sp,#64]
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#96
ret
''', {'root': 0x698f7e0, 'team': 0x697d0f8, 'game_info': 0x6a64350, 'actor': 0x72c1a14},
        {'infinity': float('inf')},
        ['source render actor +8/+16; opposing PlayerInfo snapshot +0x4f4/+0x4fc',
         '0x72c19f8 returns state info, not a render actor; never read +0x2a38 from it',
         'native in-field mask GameInfo+0x4202; opposing team only; goalkeeper included',
         '0x818b1f4 and 0x6f5000c use the PlayerInfo position getter 0x6a9d2ac'])

    builder.helper('studio_in_opposing_penalty_area', f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
mov x19,x0
mov w21,#0
cbz x19,done
mov w8,#0x2a38
ldrb w0,[x19,x8]
cmp w0,#22
b.hs done
{call('team')}
mov w20,w0
{call('root')}
cbz x0,done
mov w1,w20
mov x20,x0
{call('team_data')}
cbz x0,done
ldrsb w8,[x0,#0x28c]
cmp w8,#1
b.eq side_ok
cmn w8,#1
b.ne done
side_ok:
mov w21,w8
mov x0,x20
{call('geometry')}
cbz x0,no
ldr s0,[x19,#8]
scvtf s1,w21
fmul s0,s0,s1
ldr s1,[x0,#0x18]
ldr s2,[x0]
fcmp s1,#0.0
b.le no
fcmp s2,s1
b.le no
fcmp s0,s1
b.vs no
b.lt no
fcmp s0,s2
b.gt no
ldr s0,[x19,#16]
fabs s0,s0
ldr s1,[x0,#0x1c]
fcmp s1,#0.0
b.le no
fcmp s0,s1
b.vs no
b.gt no
mov w21,#1
b done
no:
mov w21,#0
done:
mov w0,w21
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''', {'root': 0x698f7e0, 'team': 0x697d0f8, 'team_data': 0x72c19c0, 'geometry': 0x6b96b38},
        evidence=['native geometry FieldX +0 / PenaltyAreaX +0x18 / PenaltyAreaZ +0x1c',
                  'current signed team direction +0x28c', 'penalty and goal lines inclusive'])
