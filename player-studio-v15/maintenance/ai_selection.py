"""Possession-locked forced Incisive/Lone-Wolf actions over native candidates."""
from skill_hook_ir import call


def add_selection_helpers(b):
    def reason(value):return f'mov w16,#{value}\nstr w16,[sp,#1036]\n'
    def veto_mask():return '''ldr w16,[sp,#1060]
mov w17,#1
lsl w17,w17,w29
orr w16,w16,w17
str w16,[sp,#1060]
'''
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
// Diagnostic values are returned in caller-saved W1..W9 only. No extra
// snapshot, evaluator, native predicate or random draw is performed.
add x16,sp,#1032
stp xzr,xzr,[x16]
stp xzr,xzr,[x16,#16]
str xzr,[x16,#32]
str wzr,[sp,#1020]
{reason(1)}
cmp w20,#30
b.hi choice_done
{reason(2)}
cbz x0,choice_done
ldr x19,[x0]
ldr x21,[x0,#0x10]
cbz x19,choice_done
cbz x21,choice_done
mov w8,#0x49c8
add x22,x19,x8
{reason(5)}
mov x0,x21
bl shared_studio_ai_possession_profile
str w4,[sp,#1040]
str w5,[sp,#1020]
str w6,[sp,#1044]
cbnz w0,profile_accepted
cmp w4,#18
b.eq possession_rejected
cmp w4,#17
b.eq not_holder
cmp w4,#20
b.eq possession_busy
cmp w4,#19
b.eq possession_context_missing
b choice_done
possession_rejected:
{reason(20)}
str w5,[sp,#1040]
b choice_done
not_holder:
{reason(21)}
str w7,[sp,#1040]
b choice_done
possession_context_missing:
{reason(28)}
b choice_done
possession_busy:
{reason(26)}
b choice_done
profile_accepted:
str w0,[sp,#1032]
{reason(6)}
add x23,sp,#128
mov x0,x21
mov x1,x23
bl shared_studio_ai_opportunity_snapshot
str w1,[sp,#1040]
cbz w0,choice_done
ldr w8,[sp,#1032]
strb w8,[x23,#28]
ldr w8,[x23,#28]
ldr w9,[sp,#1044]
orr w8,w8,w9
str w8,[x23,#28]
str w8,[sp,#1024]
str w8,[sp,#1044]
ldr w8,[sp,#1020]
str w8,[sp,#1040]
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
{reason(7)}
cmp x26,x25
b.lo choice_done
sub x8,x26,x25
cmp x8,#120
b.hi choice_done
tst x8,#3
b.ne choice_done
lsr w16,w8,#2
str w16,[sp,#1048]
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
str w28,[sp,#1052]
mov w8,#80
umaddl x1,w29,w8,x22
add x2,x24,w29,uxtw #4
mov x0,x23
bl shared_studio_ai_forced_style_evaluate
add x8,x24,w29,uxtw #4
ldr w9,[x8,#4]
tbz w9,#0,comparable_recorded
ldr w16,[sp,#1056]
mov w17,#1
lsl w17,w17,w29
orr w16,w16,w17
str w16,[sp,#1056]
comparable_recorded:
b evaluate_loop
evaluate_finished:
ldr w8,[sp,#1024]
tbnz w8,#9,lone_start
// An active Incisive possession selects the best executable inward route,
// independently of what the original action was or how it was scored.
{reason(24)}
mov w8,#30
str w8,[sp,#1008]
ldr s8,negative_score
ldr x25,[sp,#1000]
incisive_loop:
cmp x25,x26
b.hs incisive_finish
ldr w29,[x25],#4
cmp w29,#30
b.hs incisive_loop
add x8,x24,w29,uxtw #4
ldr w9,[x8,#4]
tbz w9,#0,incisive_loop
tbz w9,#3,incisive_loop
ldr s10,[x8]
fcmp s10,s8
b.le incisive_loop
cmp w29,w20
b.eq incisive_accept
mov x0,x19
mov x1,x21
mov w2,w29
{call('veto')}
tbz w0,#0,incisive_accept
{veto_mask()}
b incisive_loop
incisive_accept:
fmov s8,s10
str w29,[sp,#1008]
mov w8,#8
str w8,[sp,#1064]
b incisive_loop
incisive_finish:
ldr w8,[sp,#1008]
cmp w8,#30
b.hs choice_done
mov w27,w8
{reason(23)}
b force_commit
lone_start:
{reason(18)}
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
tbz w0,#0,lone_accept
{veto_mask()}
b lone_loop
lone_accept:
ldr w16,[sp,#1064]
mov w17,#1
lsl w17,w17,w28
orr w16,w16,w17
str w16,[sp,#1064]
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
b.lo lone_selected_shot
ldr w8,[sp,#1012]
cmp w8,#30
b.hs choice_done
{reason(17)}
b lone_selected
lone_selected_shot:
{reason(16)}
lone_selected:
mov w27,w8
cmp w27,w20
b.ne force_commit
{reason(15)}
force_commit:
// Reject a snapshot whose possession changed while candidates were checked.
// This re-read consumes the stored ticket, never a new roll in the same epoch.
mov x0,x21
bl shared_studio_ai_possession_profile
cbz w0,possession_changed
ldr w8,[sp,#1020]
cmp w5,w8
b.eq choice_done
possession_changed:
mov w27,w20
{reason(27)}
choice_done:
mov w0,w27
ldr w1,[sp,#1036]
mov w16,#0x5345
orr w1,w1,w16,lsl #16
ldr w2,[sp,#1032]
ldr w3,[sp,#1044]
ldr w4,[sp,#1048]
ldr w5,[sp,#1052]
ldr w6,[sp,#1056]
ldr w7,[sp,#1060]
ldr w8,[sp,#1064]
ldr w9,[sp,#1040]
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
      {'negative_score':-1000.,
       'route_pose_cost':.2,'shot_pose_cost':.08},
      ['one70% ticket per individual possession; active style bypasses original-score/pass-protection gates',
       'Lone Wolf: ready safe long shot, otherwise safe route towards shot/stance',
       'one snapshot and cached unique candidates; current player at selector +10'])

    b.helper('studio_ai_prefer_curled_shot', '''
sub sp,sp,#528
stp x19,x20,[sp]
stp x21,x30,[sp,#16]
mov x19,x0
mov x20,x1
mov x0,x20
mov w1,#0
bl shared_studio_ai_record_shot_style
ldr w8,[x19,#4]
cmp w8,#25
b.ne request_done
mov x0,x20
mov w1,#1
bl shared_studio_ai_probability_gate
cbz w0,request_done
mov x0,x20
bl shared_studio_ai_preferred_shot_style
mov w21,w0
cbz w0,legacy_request
cmp w0,#1
b.eq prefer_controlled
cmp w0,#2
b.eq prefer_low
mov x0,x20
bl shared_studio_ai_outside_penalty_area
cbz w0,request_done
mov w8,#3
b store_style
prefer_controlled:
mov w8,#1
b store_style
prefer_low:
mov w8,#0
store_style:
str w8,[x19,#8]
mov x0,x20
mov w1,w21
bl shared_studio_ai_record_shot_style
b request_done
legacy_request:
ldr w8,[x19,#8]
cbnz w8,request_done
mov x0,x20
bl shared_studio_ai_possession_profile
cbz w0,request_done
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
// The legacy Incisive/Lone-Wolf fallback follows the same zone restriction;
// owned skill-style requests above remain a separate 80-percent feature.
ldr w8,[x21]
add x9,x21,#32
add x9,x9,w8,uxtw #4
ldr s0,[x9]
ldr s1,[x21,#8]
fmul s0,s0,s1
ldr s1,[x21,#12]
fmov s2,#3.0
fdiv s1,s1,s2
fcmp s0,s1
b.vs request_done
b.lt request_done
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
// Legacy long-range curler rewrites use the same spatial power contract.
mov x0,x20
mov w1,#4
bl shared_studio_ai_record_shot_style
request_done:
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp]
add sp,sp,#528
ret
''',evidence=['owned Blitz/Low/Heavy skill styles use equal tickets after a native shot has already been chosen',
       'fallback for other players retains previous Lone Wolf / ordinary curler logic; never force an animation'])
