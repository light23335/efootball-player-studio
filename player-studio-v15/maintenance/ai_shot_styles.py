"""Equal skill-style tickets after a native CPU has already chosen a shot.

The request retains the native target. The native power handler and native
motion/foot/geometry checks run before our bounded power preference. A short
actor/root/frame permission lets Low Screamer coexist with Blitz Curler; no
stored pointer is ever dereferenced.
"""
from skill_hook_ir import call,jump,save_all,restore_all


def add_shot_styles(b):
    b.helper('studio_ai_preference_enabled','ldr w0,ordinary_switch\nret\n.align 2\nordinary_switch: .word 0x58414931\n')
    b.helper('studio_ai_preferred_shot_style',f'''
sub sp,sp,#480
stp x19,x20,[sp]
stp x21,x22,[sp,#16]
stp x23,x30,[sp,#32]
mov x19,x0
mov w23,#0
bl shared_studio_ai_preference_enabled
cbz w0,done
cbz x19,done
ldr x8,[x19]
ldr x20,[x19,#0x18]
cbz x8,done
cbz x20,done
ldr w21,[x8]
cmp w21,#22
b.hs done
mov x0,x20
{call('game_info')}
cbz x0,done
{call('phase')}
cmp w0,#1
b.ne done
mov x0,x20
mov w1,w21
{call('player_state')}
cbz x0,done
{call('abilities')}
cbz x0,done
mov x22,x0
mov w1,#51
{call('skill')}
tst w0,#1
cset w23,ne
lsl w23,w23,#1
mov x0,x22
mov w1,#58
{call('skill')}
tbz w0,#0,heavy
orr w23,w23,#4
heavy:
mov x0,x22
mov w1,#74
{call('skill')}
tbz w0,#0,snapshot
orr w23,w23,#8
snapshot:
cbz w23,done
// Skill-style choice is AFTER native shooting has been selected. Unrelated
// players crossing a touchline must never veto the current player's style.
cmp w23,#2
b.eq only_blitz
cmp w23,#4
b.eq only_low
cmp w23,#8
b.eq only_heavy
add x8,sp,#64
mov w9,#24
clear_draw:
stp xzr,xzr,[x8],#16
subs w9,w9,#1
b.ne clear_draw
str w21,[sp,#64]
str w23,[sp,#92]
mov x0,x20
mov w1,w21
{call('player_info')}
cbz x0,none
add x8,sp,#96
add x8,x8,w21,uxtw #4
ldr s0,[x0,#0x4f4]
ldr s1,[x0,#0x4fc]
fcmp s0,s0
b.vs none
fcmp s1,s1
b.vs none
str s0,[x8]
str s1,[x8,#8]
ldr w9,[x0,#0x4ec]
str w9,[x8,#4]
mov w9,#1
str w9,[x8,#12]
add x0,sp,#64
mov w1,w23
mov w2,#2
mov x3,x20
bl shared_studio_ai_equal_action_draw
mov w23,w0
b done
only_blitz:
mov w23,#1
b done
only_low:
mov w23,#2
b done
only_heavy:
mov w23,#3
b done
none:
mov w23,#0
done:
mov w0,w23
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#480
ret
''',{'player_state':0x72c40b0,'abilities':0x7301ef8,'skill':0x72b39c4,
      'game_info':0x72c3e80,'phase':0x697b60c,'player_info':0x72c408c},
      evidence=['effective match skills 51 Blitz / 58 Low Screamer / 74 Heavy Shot',
                'one equal ticket per available skill style, separate RNG domain 2',
                'single style needs no geometry snapshot; multiple styles hash only the acting player',
                'only a native shot request is modified; no pass/dribble selection changes'])

    b.helper('studio_ai_low_shot_permission',f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
mov x19,x0
mov w20,w1
mov w21,w2
cbz x19,none
cbz x3,none
cmp w20,#22
b.hs none
ldr x8,rows
mov w9,#24
umaddl x8,w20,w9,x8
cmp w21,#1
b.ne check
stp x19,x3,[x8]
str w4,[x8,#16]
mov w9,#1
str w9,[x8,#20]
mov w0,#1
b done
check:
ldp x9,x10,[x8]
cmp x9,x19
b.ne none
cmp x10,x3
b.ne none
ldr w9,[x8,#20]
cbz w9,none
ldr w9,[x8,#16]
sub w9,w4,w9
cmp w9,#2
b.hi none
mov w0,#1
b done
none:
mov w0,#0
done:
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''',writable={'rows':22*24},evidence=['values only: current root, current actor, native frame counter; never dereference retained pointers',
                                    'permission is valid for at most two native simulation ticks'])

    b.helper('studio_ai_bound_shot_power',f'''
stp x19,x20,[sp,#-112]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
str x30,[sp,#64]
stp d8,d9,[sp,#80]
mov x19,x0
mov x20,x1
bl shared_studio_ai_preference_enabled
cbz w0,done
cbz x19,done
cbz x20,done
ldr w21,[x19,#4]
cmp w21,#22
b.hs done
ldr x22,[x19,#0x30]
cbz x22,done
mov x0,x22
{call('game_info')}
cbz x0,done
mov x25,x0
{call('phase')}
cmp w0,#1
b.ne done
mov w0,w21
{call('action')}
cbz x0,done
ldr w8,[x0,#4]
cmp w8,#25
b.ne done
ldr w24,[x0,#8]
cmp w24,#2
b.hi done
mov x0,x22
mov w1,w21
{call('player_state')}
cbz x0,done
{call('abilities')}
cbz x0,done
mov x23,x0
ldr s8,[x20,#0xe7c]
fcmp s8,#0.0
b.vs done
b.le done
fmov s0,#1.0
fcmp s8,s0
b.gt done
ldrb w8,[x20,#0xffa]
cmp w24,#1
b.eq controlled
cmp w24,#2
b.eq heavy_power
cbnz w8,done
mov w1,#58
{call('skill')}
tbz w0,#0,done
ldr s0,low_ceiling
fmin s8,s8,s0
str s8,[x20,#0xe7c]
mov x0,x25
{call('clock')}
mov w26,w0
mov x0,x22
mov w1,w21
{call('actor')}
cbz x0,done
mov x3,x0
mov x0,x22
mov w1,w21
mov w2,#1
mov w4,w26
bl shared_studio_ai_low_shot_permission
b done
controlled:
cmp w8,#2
b.ne done
mov w1,#51
{call('skill')}
tbz w0,#0,done
ldr s0,controlled_floor
fmax s8,s8,s0
str s8,[x20,#0xe7c]
b done
heavy_power:
cmp w8,#3
b.ne done
mov w1,#74
{call('skill')}
tbz w0,#0,done
ldr s0,heavy_floor
fmax s8,s8,s0
str s8,[x20,#0xe7c]
done:
ldp d8,d9,[sp,#80]
ldr x30,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#112
ret
''',{'game_info':0x72c3e80,'phase':0x697b60c,'action':0x72d7dc8,
      'player_state':0x72c40b0,'abilities':0x7301ef8,'skill':0x72b39c4,
      'clock':0x6a4bd08,'actor':0x72c1a14},
      {'low_ceiling':.49,'controlled_floor':.55,'heavy_floor':.65},
      ['run after the entire original native AI behavior 25 power handler',
       'native final control mode must match the registered request subtype',
       'bounded preference only: low <50%, Blitz >=50%, heavy >=65%; native motion gates remain'])

    b.add('studio_ai_shot_style_power',0x71a27f0,'''
stp x19,x20,[sp,#-80]!
stp x21,x30,[sp,#16]
mov x19,x1
mov x20,x2
bl original
str x0,[sp,#32]
str q0,[sp,#48]
mov x0,x19
mov x1,x20
bl shared_studio_ai_bound_shot_power
ldr x0,[sp,#32]
ldr q0,[sp,#48]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#80
ret
original:
sub sp,sp,#0x110
'''+jump('resume'),{'resume':0x71a27f4})

    # The stock normal-shot selector excludes Low Screamer whenever Blitz is
    # also owned. Permit only the current, just-produced native CPU low shot.
    b.helper('studio_ai_allow_low_with_blitz',f'''
stp x19,x20,[sp,#-48]!
stp x21,x30,[sp,#16]
mov x19,x0
cbz x19,none
bl shared_studio_ai_preference_enabled
cbz w0,none
mov w8,#0x2a38
ldrb w20,[x19,x8]
cmp w20,#22
b.hs none
ldr x21,[x19,#0x4620]
cbz x21,none
mov x0,x21
{call('game_info')}
cbz x0,none
{call('clock')}
mov w4,w0
mov x0,x21
mov w1,w20
mov w2,#0
mov x3,x19
bl shared_studio_ai_low_shot_permission
b done
none:
mov w0,#0
done:
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#48
ret
''',{'game_info':0x72c3e80,'clock':0x6a4bd08})
    b.add('studio_ai_low_and_blitz_coexist',0x6d62870,save_all()+'''
ldr x0,[x29,#-0x18]
bl shared_studio_ai_allow_low_with_blitz
cbz w0,restore
str xzr,[sp]
restore:
'''+restore_all()+'''
tbz w0,#0,continue_low
'''+jump('skip_low')+'''
continue_low:
'''+jump('resume'),{'skip_low':0x6d628e0,'resume':0x6d62874},
      evidence=['preserve the original Blitz exclusion except a current CPU low-shot permission',
                'all original Low Screamer skill/power/foot/geometry checks remain'])
