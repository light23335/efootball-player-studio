"""Equal action classes normally; safe shooting/repositioning first for Lone Wolf."""
from skill_hook_ir import call
from ai_opportunity import COMPARISON_WINDOW


def add_selection_helpers(b):
    b.helper('studio_ai_select_cut_in_candidate', f'''
sub sp,sp,#1088
stp x19,x20,[sp]
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
stp x27,x28,[sp,#64]
stp x29,x30,[sp,#80]
stp d8,d9,[sp,#96]
stp d10,d11,[sp,#112]
mov w20,w1
mov w27,w1
cmp w20,#30
b.hs choice_done
ldr x19,[x0]
ldr x21,[x0,#0x10]
cbz x19,choice_done
cbz x21,choice_done
mov w8,#0x49c8
add x22,x19,x8
mov w8,#80
umaddl x8,w20,w8,x22
ldr w9,[x8]
sub w9,w9,#1
cmp w9,#2
b.hi choice_done
ldr w9,[x8]
cmp w9,#1
b.ne choice_profile
ldr w9,[x8,#8]
cmp w9,#1
b.hi choice_done
choice_profile:
mov x0,x21
bl shared_studio_ai_cut_in_profile
cbz w0,choice_done
str w0,[sp,#1032]
add x23,sp,#128
mov x0,x21
mov x1,x23
bl shared_studio_ai_opportunity_snapshot
cbz w0,choice_done
ldr w8,[sp,#1032]
strb w8,[x23,#28]
ldr w8,[x23,#28]
str w8,[sp,#1024]
add x24,sp,#512
mov w8,#0x48a8
add x29,x19,x8
mov x0,x29
{call('begin')}
mov x25,x0
str x25,[sp,#1000]
mov x0,x29
{call('end')}
mov x26,x0
cmp x26,x25
b.lo choice_done
sub x8,x26,x25
cmp x8,#120
b.hi choice_done
tst x8,#3
b.ne choice_done
mov w28,#0
evaluate_loop:
cmp x25,x26
b.hs evaluate_finished
ldr w29,[x25],#4
cmp w29,#30
b.hs evaluate_loop
mov w8,#1
lsl w8,w8,w29
tst w28,w8
b.ne evaluate_loop
orr w28,w28,w8
mov w8,#80
umaddl x1,w29,w8,x22
add x2,x24,w29,uxtw #4
mov x0,x23
bl shared_studio_ai_opportunity_evaluate
ldr w8,[sp,#1024]
tbnz w8,#9,evaluate_loop
add x8,x24,w29,uxtw #4
ldr w8,[x8,#4]
tbnz w8,#1,choice_done
b evaluate_loop
evaluate_finished:
mov w8,#1
lsl w8,w8,w20
tst w28,w8
b.eq choice_done
ldr w8,[sp,#1024]
tbnz w8,#9,lone_start
add x8,x24,w20,uxtw #4
ldr w9,[x8,#4]
tbz w9,#0,choice_done
ldr s8,[x8]
mov w8,#30
str w8,[sp,#1008]
str w8,[sp,#1012]
str w8,[sp,#1016]
mov w8,#80
umaddl x8,w20,w8,x22
ldr w9,[x8]
add x8,sp,#1004
str w20,[x8,w9,uxtw #2]
mov w28,#1
lsl w28,w28,w9
ldr x25,[sp,#1000]
equal_loop:
cmp x25,x26
b.hs equal_draw
ldr w29,[x25],#4
cmp w29,#30
b.hs equal_loop
cmp w29,w20
b.eq equal_loop
add x8,x24,w29,uxtw #4
ldr w9,[x8,#4]
tbz w9,#0,equal_loop
ldr s10,[x8]
fsub s0,s10,s8
fabs s0,s0
ldr s1,comparison_window
fcmp s0,s1
b.vs equal_loop
b.gt equal_loop
mov w8,#80
umaddl x8,w29,w8,x22
ldr w10,[x8]
cmp w10,#3
b.ne equal_class
tbz w9,#2,equal_loop
equal_class:
mov w8,#1
lsl w8,w8,w10
tst w28,w8
b.ne equal_loop
str w10,[sp,#1028]
mov x0,x19
mov x1,x21
mov w2,w29
{call('veto')}
tbnz w0,#0,equal_loop
ldr w10,[sp,#1028]
mov w8,#1
lsl w8,w8,w10
orr w28,w28,w8
add x8,sp,#1004
str w29,[x8,w10,uxtw #2]
b equal_loop
equal_draw:
mov x0,x23
mov w1,w28
mov w2,#0
ldr x3,[x21,#0x18]
bl shared_studio_ai_equal_action_draw
cbz w0,choice_done
add x8,sp,#1004
ldr w27,[x8,w0,uxtw #2]
b choice_done
lone_start:
mov w8,#30
str w8,[sp,#1008]
str w8,[sp,#1012]
ldr s8,negative_score
fmov s9,s8
ldr x25,[sp,#1000]
lone_loop:
cmp x25,x26
b.hs lone_finish
ldr w29,[x25],#4
cmp w29,#30
b.hs lone_loop
add x8,x24,w29,uxtw #4
ldr w9,[x8,#4]
tbz w9,#0,lone_loop
ldr s10,[x8]
ldr s11,[x8,#8]
mov w8,#80
umaddl x8,w29,w8,x22
ldr w10,[x8]
cmp w10,#1
b.eq lone_shot
cmp w10,#3
b.ne lone_loop
tbz w9,#2,lone_loop
// Incisive Run adds inward-route preference; Lone Wolf without it may use
// any safe progress route. Posture quality distinguishes shooting setups.
ldr w8,[sp,#1024]
tbz w8,#8,lone_route_pose
tbz w9,#3,lone_route_pose
fmov s0,#6.0
fadd s10,s10,s0
lone_route_pose:
tbz w9,#4,lone_route_cost
fmov s0,#20.0
fadd s10,s10,s0
lone_route_cost:
ldr s0,route_pose_cost
fmsub s10,s11,s0,s10
fcmp s10,s9
b.le lone_loop
mov w28,#3
b lone_veto
lone_shot:
ldr w8,[sp,#1032]
cmp w8,#3
b.ne lone_shot_score
tbz w9,#4,lone_loop
lone_shot_score:
ldr s0,shot_pose_cost
fmsub s10,s11,s0,s10
fcmp s10,s8
b.le lone_loop
mov w28,#1
lone_veto:
cmp w29,w20
b.eq lone_accept
mov x0,x19
mov x1,x21
mov w2,w29
{call('veto')}
tbnz w0,#0,lone_loop
lone_accept:
cmp w28,#1
b.ne lone_accept_route
fmov s8,s10
str w29,[sp,#1008]
b lone_loop
lone_accept_route:
fmov s9,s10
str w29,[sp,#1012]
b lone_loop
lone_finish:
ldr w8,[sp,#1008]
cmp w8,#30
b.lo lone_selected
ldr w8,[sp,#1012]
cmp w8,#30
b.hs choice_done
lone_selected:
mov w27,w8
choice_done:
mov w0,w27
ldp d10,d11,[sp,#112]
ldp d8,d9,[sp,#96]
ldp x29,x30,[sp,#80]
ldp x27,x28,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#1088
ret
''',{'begin':0x70e63cc,'end':0x70e63d0,'veto':0x70e72a0},
      {'comparison_window':COMPARISON_WINDOW,'negative_score':-1000.,
       'route_pose_cost':.2,'shot_pose_cost':.08},
      ['equal tickets per action class inside estimated window; no native RNG',
       'Lone Wolf: ready safe long shot, otherwise safe route towards shot/stance',
       'one snapshot and cached unique candidates; current player at selector +10'])

    b.helper('studio_ai_prefer_curled_shot', '''
sub sp,sp,#528
stp x19,x20,[sp]
stp x21,x30,[sp,#16]
mov x19,x0
mov x20,x1
ldr w8,[x19,#4]
cmp w8,#25
b.ne request_done
mov x0,x20
bl shared_studio_ai_preferred_shot_style
cbz w0,legacy_request
cmp w0,#1
b.eq prefer_controlled
cmp w0,#2
b.eq prefer_low
mov w8,#2
b store_style
prefer_controlled:
mov w8,#1
b store_style
prefer_low:
mov w8,#0
store_style:
str w8,[x19,#8]
b request_done
legacy_request:
ldr w8,[x19,#8]
cbnz w8,request_done
mov x0,x20
bl shared_studio_ai_cut_in_profile
cmp w0,#2
b.lo request_done
str w0,[sp,#32]
add x21,sp,#48
mov x0,x20
mov x1,x21
bl shared_studio_ai_opportunity_snapshot
cbz w0,request_done
ldr w8,[sp,#32]
strb w8,[x21,#28]
add x1,sp,#432
mov w8,#1
str w8,[x1]
str wzr,[x1,#8]
ldr w8,[x19,#0xc]
str w8,[x1,#0xc]
ldr w8,[x19,#0x14]
str w8,[x1,#0x10]
ldr w8,[x19,#0x10]
str w8,[x1,#0x14]
add x2,sp,#512
mov x0,x21
bl shared_studio_ai_opportunity_evaluate
ldr w8,[sp,#516]
tbz w8,#0,request_done
tbz w8,#4,request_done
ldr w8,[x21,#28]
tbnz w8,#9,request_controlled
mov x0,x21
mov w1,#6
mov w2,#1
ldr x3,[x20,#0x18]
bl shared_studio_ai_equal_action_draw
cmp w0,#2
b.ne request_done
request_controlled:
mov w8,#1
str w8,[x19,#8]
request_done:
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#528
ret
''',evidence=['owned Blitz/Low/Heavy skill styles use equal tickets after a native shot has already been chosen',
       'fallback for other players retains previous Lone Wolf / ordinary curler logic; never force an animation'])
