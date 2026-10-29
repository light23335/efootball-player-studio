"""Conservative, local opportunity estimates over one read-only match snapshot.

These are workshop heuristics, not native utility scores or calibrated xG.
Only decoded ground passes, ordinary moving dribbles and native shots can be
compared. Unknown data preserves the original choice. No native action
evaluator or native RNG is called. Estimates stay local; a separate actor
cache stabilises private equal-ticket draws between similar situations.
"""
from skill_hook_ir import call

SNAPSHOT_BYTES = 384  # header 32 + 22 * {x, y, z, active}
COMPARISON_WINDOW = 8.0
PREFERENCE_BONUS = 0.0


def add_opportunity_helpers(b):
    b.helper('studio_ai_opportunity_snapshot', f'''
stp x19,x20,[sp,#-96]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
stp d8,d9,[sp,#64]
str d10,[sp,#80]
mov x19,x0
mov x20,x1
mov w25,#0
cbz x19,snapshot_done
ldr x8,[x19]
ldr x21,[x19,#0x18]
cbz x8,snapshot_done
cbz x21,snapshot_done
ldr w22,[x8]
cmp w22,#22
b.hs snapshot_done
str w22,[x20]
cmp w22,#11
cset w23,hs
str w23,[x20,#4]
mov x0,x21
{call('game_info')}
mov x24,x0
cbz x24,snapshot_done
mov x0,x24
{call('phase')}
cmp w0,#1
b.ne snapshot_done
mov x0,x21
{call('pitch')}
cbz x0,snapshot_done
ldr s8,[x0]
ldr s9,[x0,#8]
ldr s0,min_half_length
fcmp s8,s0
b.vs snapshot_done
b.lt snapshot_done
ldr s0,max_half_length
fcmp s8,s0
b.gt snapshot_done
fmov s0,#20.0
fcmp s9,s0
b.vs snapshot_done
b.lt snapshot_done
ldr s0,max_half_width
fcmp s9,s0
b.gt snapshot_done
stp s8,s9,[x20,#12]
mov x0,x21
mov w1,w23
{call('team_data')}
cbz x0,snapshot_done
ldrsb w8,[x0,#0x28c]
cmp w8,#1
b.eq snapshot_side
cmn w8,#1
b.ne snapshot_done
snapshot_side:
scvtf s10,w8
str s10,[x20,#8]
str xzr,[x20,#20]
str wzr,[x20,#28]
mov w22,#0
snapshot_loop:
add x23,x20,#32
add x23,x23,w22,uxtw #4
str wzr,[x23,#12]
mov x0,x24
mov w1,w22
{call('active')}
cbz w0,snapshot_next
mov x0,x24
mov w1,w22
{call('unavailable')}
cbnz w0,snapshot_next
mov x0,x21
mov w1,w22
{call('player_info')}
cbz x0,snapshot_done
ldr s0,[x0,#0x4f4]
ldr s1,[x0,#0x4fc]
fabs s2,s0
fabs s3,s1
fcmp s2,s8
b.vs snapshot_done
b.gt snapshot_done
fcmp s3,s9
b.vs snapshot_done
b.gt snapshot_done
str s0,[x23]
ldr w8,[x0,#0x4ec]
str w8,[x23,#4]
str s1,[x23,#8]
mov w8,#1
str w8,[x23,#12]
cmp w22,#11
cset w8,hs
add x8,x20,w8,uxtw #2
ldr w9,[x8,#20]
add w9,w9,#1
str w9,[x8,#20]
snapshot_next:
add w22,w22,#1
cmp w22,#22
b.lo snapshot_loop
ldp w8,w9,[x20,#20]
cmp w8,#7
b.lo snapshot_done
cmp w9,#7
b.lo snapshot_done
ldr w8,[x20]
add x9,x20,#32
add x9,x9,w8,uxtw #4
ldr w25,[x9,#12]
cbz w25,snapshot_done
mov x0,x21
mov w1,w8
{call('player_state')}
cbz x0,snapshot_invalid
{call('abilities')}
cbz x0,snapshot_invalid
ldr w8,[x0,#0xd4]
ubfx w9,w8,#4,#1
lsl w9,w9,#8
ubfx w8,w8,#7,#1
orr w9,w9,w8,lsl #9
ldrb w8,[x0,#0x35]
cmp w8,#1
b.hi snapshot_flags
orr w9,w9,w8,lsl #10
orr w9,w9,#0x800
snapshot_flags:
str w9,[x20,#28]
b snapshot_done
snapshot_invalid:
mov w25,#0
snapshot_done:
mov w0,w25
ldr d10,[sp,#80]
ldp d8,d9,[sp,#64]
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#96
ret
''', {'game_info':0x72c3e80,'phase':0x697b60c,'pitch':0x72c3e6c,
      'team_data':0x72c4028,'active':0x6a642f8,'unavailable':0x6a64358,
      'player_info':0x72c408c,'player_state':0x72c40b0,'abilities':0x7301ef8},
      {'min_half_length':32.,'max_half_length':70.,'max_half_width':45.},
      ['72c408c native live PlayerInfo; position +4f4/+4fc',
       '70ed20c..70ed248 checks native active/unavailable before reading positions',
       'snapshot once per decision; no action evaluator, RNG or global cache'])

    # Same 0..100 positional scale for each decoded action. This is a local
    # estimate of attacking position after the action, never native utility.
    b.helper('studio_ai_opportunity_position', '''
ldr s2,[x0,#8]
ldr s3,[x0,#12]
fmul s0,s0,s2
fsub s0,s3,s0
fmul s0,s0,s0
fmadd s0,s1,s1,s0
fsqrt s0,s0
ldr s2,distance_weight
fmul s0,s0,s2
fabs s1,s1
ldr s2,lateral_weight
fmadd s0,s1,s2,s0
ldr s1,hundred
fsub s0,s1,s0
fmov s1,wzr
fmax s0,s0,s1
ret
''', constants={'distance_weight':1.6,'lateral_weight':.8,'hundred':100.})

    # x0 snapshot, s0/s1 start X/Z, s2/s3 end X/Z.
    # Return squared clearance to segment / end / start in s0/s1/s2.
    # A single pass over the captured opponents; all arithmetic is read-only.
    b.helper('studio_ai_opportunity_clearance', '''
fmov s16,s0
fmov s17,s1
fmov s18,s2
fmov s19,s3
fsub s20,s2,s0
fsub s21,s3,s1
fmul s22,s20,s20
fmadd s22,s21,s21,s22
ldr s23,far_distance_sq
fmov s24,s23
fmov s25,s23
ldr w8,[x0,#4]
eor w8,w8,#1
mov w9,#11
mul w8,w8,w9
add x9,x0,#32
add x9,x9,w8,uxtw #4
mov w10,#11
fmov s26,#1.0
fmov s27,wzr
clearance_loop:
ldr w8,[x9,#12]
cbz w8,clearance_next
ldr s0,[x9]
ldr s1,[x9,#8]
fsub s2,s0,s16
fsub s3,s1,s17
fmul s4,s2,s2
fmadd s4,s3,s3,s4
fmin s25,s25,s4
fsub s4,s0,s18
fsub s5,s1,s19
fmul s4,s4,s4
fmadd s4,s5,s5,s4
fmin s24,s24,s4
fcmp s22,s27
b.le clearance_point
fmul s4,s2,s20
fmadd s4,s3,s21,s4
fdiv s4,s4,s22
fmax s4,s4,s27
fmin s4,s4,s26
fmsub s2,s4,s20,s2
fmsub s3,s4,s21,s3
clearance_point:
fmul s4,s2,s2
fmadd s4,s3,s3,s4
fmin s23,s23,s4
clearance_next:
add x9,x9,#16
subs w10,w10,#1
b.ne clearance_loop
fmov s0,s23
fmov s1,s24
fmov s2,s25
ret
''', constants={'far_distance_sq':65536.})

    # A separate private random stream, cached per actor/domain/situation.
    # It never consumes native RNG. Classes, not number of candidates, get
    # equal tickets. No qualification or native pointer is reused as data.
    b.helper('studio_ai_equal_action_draw', '''
ldr w8,[x0]
cmp w8,#22
b.hs draw_empty
cmp w2,#2
b.hi draw_empty
mov w9,#22
madd w9,w2,w9,w8
ldr x10,draw_state
add x10,x10,x9,lsl #5
mov w11,#0x9dc5
movk w11,#0x811c,lsl #16
eor w11,w11,w1
ldr w12,[x0,#28]
eor w11,w11,w12
add x12,x0,#32
mov w13,#22
fmov s4,#0.5
mov w15,#0x193
movk w15,#0x100,lsl #16
draw_hash:
ldr w14,[x12,#12]
eor w11,w11,w14
cbz w14,draw_hash_next
ldr s0,[x12]
ldr s1,[x12,#8]
fmul s0,s0,s4
fmul s1,s1,s4
fcvtzs w14,s0
eor w11,w11,w14
mul w11,w11,w15
fcvtzs w14,s1
eor w11,w11,w14
mul w11,w11,w15
draw_hash_next:
add x12,x12,#16
subs w13,w13,#1
b.ne draw_hash
add x12,x0,#32
add x12,x12,w8,uxtw #4
ldr s0,[x12,#4]
ldr s1,heading_quantum
fmul s0,s0,s1
fcvtzs w14,s0
eor w11,w11,w14
ldp x12,x13,[x10]
cmp x12,x3
b.ne draw_seed
cmp x13,x11
b.ne draw_next
ldr w0,[x10,#20]
mov w12,#1
lsl w12,w12,w0
tst w12,w1
b.ne draw_return
draw_next:
ldr w12,[x10,#16]
b draw_random
draw_seed:
eor w12,w11,w3
eor w12,w12,w9
mov w13,#0x79b9
movk w13,#0x9e37,lsl #16
eor w12,w12,w13
// Avalanche nearby actor/session keys before the independent xorshift.
mov w13,#0xca6b
movk w13,#0x85eb,lsl #16
eor w12,w12,w12,lsr #16
mul w12,w12,w13
mov w13,#0xae35
movk w13,#0xc2b2,lsl #16
eor w12,w12,w12,lsr #13
mul w12,w12,w13
eor w12,w12,w12,lsr #16
draw_random:
cbnz w12,draw_nonzero
mov w12,#1
draw_nonzero:
eor w12,w12,w12,lsl #13
eor w12,w12,w12,lsr #17
eor w12,w12,w12,lsl #5
mov w13,#0
mov w14,w1
draw_count:
and w15,w14,#1
add w13,w13,w15
lsr w14,w14,#1
cbnz w14,draw_count
cbz w13,draw_empty
umull x14,w12,w13
lsr x14,x14,#32
mov w0,#1
draw_pick:
mov w13,#1
lsl w13,w13,w0
tst w1,w13
b.eq draw_pick_next
cbz w14,draw_save
sub w14,w14,#1
draw_pick_next:
add w0,w0,#1
cmp w0,#4
b.lo draw_pick
b draw_empty
draw_save:
stp x3,x11,[x10]
str w12,[x10,#16]
str w0,[x10,#20]
draw_return:
ret
draw_empty:
mov w0,#0
ret
''',constants={'heading_quantum':1./20.},writable={'draw_state':66*32},
      evidence=['actor/domain-separated xorshift stream, multiply-high bounded class draw',
                'stable when quantized situation and candidate classes are unchanged; no native RNG'])

    # Estimate a controllable open-body stance, using the audited native yaw
    # convention and strong-foot side. Never overwrite a body transform or
    # claim this predicts the final native ball-contact animation exactly.
    b.helper('studio_ai_blitz_posture', f'''
stp x19,x20,[sp,#-112]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
stp d10,d11,[sp,#48]
mov x19,x0
mov w21,#0
fmov s8,s0
fmov s9,s1
fmov s10,s2
ldr w8,[x19,#28]
tbz w8,#11,posture_done
fcmp s10,s10
b.vs posture_done
fabs s0,s10
ldr s1,full_turn
fcmp s0,s1
b.gt posture_done
ldr s0,[x19,#8]
ldr s1,[x19,#12]
fmul s0,s0,s1
fsub s0,s0,s8
str s0,[sp,#64]
str wzr,[sp,#68]
fneg s0,s9
str s0,[sp,#72]
add x0,sp,#64
{call('yaw')}
fmov s11,s0
ldr w8,[x19,#28]
fmov s1,#25.0
tbnz w8,#10,posture_left
fsub s0,s0,s1
b posture_ideal
posture_left:
fadd s0,s0,s1
posture_ideal:
fcmp s0,#0.0
b.ge posture_upper
ldr s1,full_turn
fadd s0,s0,s1
posture_upper:
ldr s1,full_turn
fcmp s0,s1
b.lt posture_angle
fsub s0,s0,s1
posture_angle:
str s10,[sp,#80]
str s0,[sp,#84]
add x0,sp,#80
add x1,sp,#84
{call('difference')}
fmov s10,s0
str s8,[sp,#64]
str wzr,[sp,#68]
str s9,[sp,#72]
ldr w8,[x19,#28]
ldr s1,right_turn
tbz w8,#10,posture_foot
fneg s1,s1
posture_foot:
fadd s0,s11,s1
add x0,sp,#64
ldr s1,foot_offset
{call('advance')}
fmov s1,s2
fmov s2,s0
fmov s3,s1
mov x0,x19
bl shared_studio_ai_opportunity_clearance
fmov s1,s0
mov w21,#1
posture_done:
fmov s0,s10
mov w0,w21
ldp d10,d11,[sp,#48]
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#112
ret
''',{'yaw':0x6910428,'difference':0x6ad3e50,'advance':0x6d3a784},
      {'full_turn':360.,'right_turn':90.,'foot_offset':.8},
      ['body heading PlayerInfo +4ec; native yaw and absolute angle difference',
       'compact foot parameter 43 -> 6a745e0 -> native ability byte 53',
       '25-degree open-body target and strong-foot clearance are workshop estimates'])

    # Result {float score; uint flags; float posture_error; float foot_space_sq};
    # flags valid=1, protected pass=2, preferred route/shot=4, inward=8, ready=16.
    # preferred inward/shot=4. Every candidate is evaluated at most once.
    b.helper('studio_ai_opportunity_evaluate', f'''
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
cmp w22,#2
b.eq evaluate_pass
cmp w22,#3
b.eq evaluate_dribble
cmp w22,#1
b.eq evaluate_shot
b evaluate_done
evaluate_pass:
ldr w8,[x20,#0x1c]
cmp w8,#22
b.hs evaluate_done
ldr w9,[x19]
cmp w8,w9
b.eq evaluate_done
cmp w8,#11
cset w9,hs
ldr w10,[x19,#4]
cmp w9,w10
b.ne evaluate_done
// Through/lob/special pass endpoints are not fully represented here.
// Preserve native choices instead of pretending their current position is
// the native predicted reception point.
ldr w9,[x20,#0x20]
cbnz w9,evaluate_done
ldrb w9,[x20,#0x26]
ldrb w10,[x20,#0x27]
orr w9,w9,w10
ldrb w10,[x20,#0x28]
orr w9,w9,w10
ldrb w10,[x20,#0x29]
orr w9,w9,w10
ldrb w10,[x20,#0x2a]
orr w9,w9,w10
ldrb w10,[x20,#0x2b]
orr w9,w9,w10
cbnz w9,evaluate_done
add x9,x19,#32
add x9,x9,w8,uxtw #4
ldr w8,[x9,#12]
cbz w8,evaluate_done
ldr s10,[x9]
ldr s11,[x9,#8]
fsub s0,s10,s8
fsub s1,s11,s9
fmul s0,s0,s0
fmadd s0,s1,s1,s0
fmov s1,#4.0
fcmp s0,s1
b.lt evaluate_done
ldr s1,max_ground_pass_sq
fcmp s0,s1
b.gt evaluate_done
fsqrt s13,s0
b evaluate_metrics
evaluate_dribble:
ldr w8,[x20,#0x2c]
sub w8,w8,#2
cmp w8,#1
b.hi evaluate_done
ldr s0,[x20,#0x30]
fcmp s0,s0
b.vs evaluate_done
fabs s1,s0
ldr s2,heading_bound
fcmp s1,s2
b.gt evaluate_done
ldr w8,[x19]
add x0,x19,#32
add x0,x0,w8,uxtw #4
fmov s1,#4.0
{call('advance')}
fmov s10,s0
fmov s11,s2
fmov s13,#4.0
// Every native moving dribble can be a baseline; only a forward inward
// route receives a preference flag.
fabs s0,s9
fmov s1,#14.0
fcmp s0,s1
b.lt evaluate_metrics
fabs s0,s11
fabs s1,s9
fmov s2,#0.5
fsub s1,s1,s2
fcmp s0,s1
b.gt evaluate_metrics
fsub s0,s10,s8
ldr s1,[x19,#8]
fmul s0,s0,s1
fcmp s0,s2
b.lt evaluate_metrics
orr w23,w23,#8
ldr w8,[x19,#28]
tbz w8,#8,evaluate_metrics
orr w23,w23,#4
b evaluate_metrics
evaluate_shot:
ldr w8,[x20,#8]
cmp w8,#1
b.hi evaluate_done
ldr s0,[x20,#0xc]
ldr s1,[x19,#8]
ldr s2,[x19,#12]
fmul s1,s1,s2
fsub s0,s0,s1
fabs s0,s0
fmov s1,#3.0
fcmp s0,s1
b.vs evaluate_done
b.gt evaluate_done
ldr s0,[x20,#0x10]
fcmp s0,#0.0
b.vs evaluate_done
b.lt evaluate_done
fmov s1,#3.5
fcmp s0,s1
b.gt evaluate_done
ldr s0,[x20,#0x14]
fabs s0,s0
fmov s1,#4.0
fcmp s0,s1
b.vs evaluate_done
b.gt evaluate_done
// Decode the precomputed target, but only compare long shots from a
// sensible angle. Other original shots retain their native request type.
ldr s0,[x19,#8]
ldr s1,[x19,#12]
fmul s0,s8,s0
fsub s0,s1,s0
fabs s1,s9
ldr s2,shot_angle_ratio
ldr w8,[x19,#28]
and w9,w8,#0xff
cmp w9,#3
b.eq shot_wide_angle
tbnz w8,#9,shot_wide_angle
b shot_angle_test
shot_wide_angle:
fmov s2,#1.0
shot_angle_test:
fmul s2,s0,s2
fcmp s1,s2
b.gt evaluate_done
fmul s0,s0,s0
fmadd s0,s9,s9,s0
ldr s1,shot_min_sq
cmp w9,#3
b.eq shot_wide_min
tbnz w8,#9,shot_wide_min
b shot_min_test
shot_wide_min:
ldr s1,blitz_min_sq
shot_min_test:
fcmp s0,s1
b.lt evaluate_done
ldr s1,shot_max_sq
cmp w9,#3
b.eq shot_wide_max
tbnz w8,#9,shot_wide_max
b shot_max_test
shot_wide_max:
ldr s1,blitz_max_sq
shot_max_test:
fcmp s0,s1
b.gt evaluate_done
fsqrt s13,s0
ldr s10,[x20,#0xc]
ldr s11,[x20,#0x14]
fsub s0,s10,s8
fsub s1,s11,s9
fmul s2,s0,s0
fmadd s2,s1,s1,s2
fsqrt s2,s2
fmov s3,#10.0
fdiv s3,s3,s2
fmadd s10,s0,s3,s8
fmadd s11,s1,s3,s9
orr w23,w23,#4
evaluate_metrics:
cmp w22,#3
b.ne metrics_bounds
ldr w8,[x19,#28]
tbz w8,#9,metrics_bounds
// Lone Wolf may progress without Incisive Run. Retain the inward marker
// separately so the combination can favour inward shooting setups.
fsub s0,s10,s8
ldr s1,[x19,#8]
fmul s0,s0,s1
fmov s2,#0.5
fcmp s0,s2
b.lt metrics_bounds
ldr s2,[x19,#12]
fmul s0,s10,s1
fsub s0,s2,s0
fmul s0,s0,s0
fmadd s0,s11,s11,s0
fmul s1,s8,s1
fsub s1,s2,s1
fmul s1,s1,s1
fmadd s1,s9,s9,s1
fcmp s0,s1
b.ge metrics_bounds
orr w23,w23,#4
metrics_bounds:
// Snapshot validated the source positions; also validate native predicted
// dribble endpoints, including NaNs and pitch bounds.
fabs s0,s10
ldr s1,[x19,#12]
fcmp s0,s1
b.vs evaluate_done
b.gt evaluate_done
fabs s0,s11
ldr s1,[x19,#16]
fcmp s0,s1
b.vs evaluate_done
b.gt evaluate_done
mov x0,x19
fmov s0,s8
fmov s1,s9
fmov s2,s10
fmov s3,s11
bl shared_studio_ai_opportunity_clearance
fsqrt s14,s0
fsqrt s15,s1
fsqrt s12,s2
cmp w22,#1
b.eq metrics_shot
cmp w22,#2
b.eq metrics_pass
fmov s0,#1.75
fcmp s14,s0
b.lt evaluate_done
fmov s0,#2.5
fcmp s15,s0
b.lt evaluate_done
fmov s0,#1.5
fcmp s12,s0
b.lt evaluate_done
b metrics_position
metrics_pass:
fmov s0,#1.5
fcmp s14,s0
b.lt evaluate_done
fmov s0,#2.5
fcmp s15,s0
b.lt evaluate_done
// Clear, free reception inside the box is never sacrificed to a skill
// preference. Through/lob passes already fail closed above.
ldr s0,[x19,#8]
ldr s1,[x19,#12]
fmul s0,s10,s0
fsub s0,s1,s0
ldr s1,penalty_depth
fcmp s0,s1
b.gt pass_penetration
fabs s0,s11
ldr s1,penalty_half_width
fcmp s0,s1
b.gt pass_penetration
fmov s0,#3.0
fcmp s15,s0
b.lt pass_penetration
fmov s0,#1.75
fcmp s14,s0
b.lt pass_penetration
orr w23,w23,#2
pass_penetration:
// Protect a clear forward receiver beyond the second-last opponent.
// This is a conservative protection, not an offside/through-ball solver.
fsub s0,s10,s8
ldr s1,[x19,#8]
fmul s0,s0,s1
fmov s2,#4.0
fcmp s0,s2
b.lt metrics_position
ldr w8,[x19,#4]
eor w8,w8,#1
mov w9,#11
mul w8,w8,w9
add x9,x19,#32
add x9,x9,w8,uxtw #4
mov w10,#11
mov w11,#0
fmul s2,s10,s1
penetration_loop:
ldr w8,[x9,#12]
cbz w8,penetration_next
ldr s0,[x9]
fmul s0,s0,s1
fcmp s0,s2
b.gt penetration_behind
b penetration_next
penetration_behind:
add w11,w11,#1
penetration_next:
add x9,x9,#16
subs w10,w10,#1
b.ne penetration_loop
cmp w11,#1
b.hi metrics_position
orr w23,w23,#2
b metrics_position
metrics_shot:
fmov s0,#2.75
fcmp s12,s0
b.lt evaluate_done
fmov s0,#1.5
fcmp s14,s0
b.lt evaluate_done
metrics_position:
mov x0,x19
cmp w22,#1
b.eq position_shot
fmov s0,s10
fmov s1,s11
b position_call
position_shot:
fmov s0,s8
fmov s1,s9
position_call:
bl shared_studio_ai_opportunity_position
fmov s12,s0
fmov s0,#4.0
fsub s12,s12,s0
cmp w22,#2
b.ne position_risk
ldr s0,pass_distance_cost
fmsub s0,s13,s0,s12
fmov s12,s0
position_risk:
// Remaining pressure and corridor uncertainty use the same bounded cost
// scale for each action, after the hard safety gates above.
fmov s0,#3.0
fsub s1,s0,s14
fmov s2,wzr
fmax s1,s1,s2
fmov s3,#4.0
fmul s1,s1,s3
fsub s0,s0,s15
fmax s0,s0,s2
fmadd s0,s0,s3,s1
fsub s12,s12,s0
fmax s12,s12,s2
// Posture is stored separately; it does not secretly bias ordinary action
// opportunity estimates. Only Lone Wolf uses it to rank repositioning.
ldr w8,[x19,#28]
and w8,w8,#0xff
cmp w8,#3
b.ne posture_not_blitz
cmp w22,#1
b.eq posture_current
cmp w22,#3
b.ne posture_not_blitz
fmov s0,s10
fmov s1,s11
ldr s2,[x20,#0x30]
b posture_compute
posture_current:
fmov s0,s8
fmov s1,s9
ldr w8,[x19]
add x9,x19,#32
add x9,x9,w8,uxtw #4
ldr s2,[x9,#4]
posture_compute:
mov x0,x19
bl shared_studio_ai_blitz_posture
cbz w0,posture_unknown
str s0,[x21,#8]
str s1,[x21,#12]
ldr s2,posture_ready_angle
fcmp s0,s2
b.gt posture_store
ldr s2,foot_space_sq
fcmp s1,s2
b.lt posture_store
orr w23,w23,#16
b posture_store
posture_not_blitz:
orr w23,w23,#16
b posture_store
posture_unknown:
ldr s0,unknown_posture
str s0,[x21,#8]
posture_store:
str s12,[x21]
str w23,[x21,#4]
evaluate_done:
ldp d14,d15,[sp,#96]
ldp d12,d13,[sp,#80]
ldp d10,d11,[sp,#64]
ldp d8,d9,[sp,#48]
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#160
ret
''', {'advance':0x6d3a784},
      {'max_ground_pass_sq':900.,'heading_bound':360.,'shot_angle_ratio':.85,
       'shot_min_sq':324.,'shot_max_sq':1024.,'blitz_min_sq':144.,'blitz_max_sq':1225.,'penalty_depth':16.5,
       'penalty_half_width':20.16,'pass_distance_cost':.15,'posture_ready_angle':35.,
       'foot_space_sq':3.0625,'unknown_posture':180.},
      ['70e5354 passes native result +1c to 70e74d0; recipient +0, mode +4',
       '70e7ae8 uses native heading at result +30; original advance is pure geometry',
       'workshop-only opportunity scale; static geometry plus conservative buffers',
       'unknown predictions or modes stay native; never calls original action evaluators'])
