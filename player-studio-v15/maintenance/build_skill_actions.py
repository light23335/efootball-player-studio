"""Committed kick provenance and pre-contact motion-rate integration.

Qualification is staged only after the original handler selected a motion,
then consumed by that same handler record at the real initialization path.
Prediction calls and failed/fallback requests cannot activate the effects.
"""
from skill_hook_ir import call, jump, save_all, restore_all, FRAME, SIMD


def add_actions(builder):
    builder.helper('studio_kick_slot', '''
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
''', evidence=['separate 64-byte kick provenance per live actor in RW memory'],writable={'rows':1408})

    # x0 actor, x1 original request header, x2 selected motion descriptor,
    # x3 durable compact-record destination, x4 final native request.
    # The compact record starts with an XYZ point, NOT a motion descriptor.
    builder.helper('studio_stage_committed_kick', '''
stp x19,x20,[sp,#-64]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
str x30,[sp,#48]
mov x19,x0
mov x20,x1
mov x21,x2
mov x22,x3
mov x24,x4
bl shared_studio_kick_slot
cbz x0,done
mov x23,x0
str wzr,[x23,#36]
cbz x20,done
cbz x21,done
cbz x22,done
cbz x24,done
mov x0,x20
bl shared_studio_classify_committed_kick_request
cbz w0,done
ldr w8,[x24,#4]
cmp w8,w1
b.ne done
ldr w8,[x24]
ldr w9,[x20]
cmp w8,w9
b.ne done
ldr w8,[x21]
cmp w8,#177
b.hs done
str x19,[x23]
ldr x9,[x19,#0x4620]
str x9,[x23,#8]
str x22,[x23,#16]
str w8,[x23,#24]
str w1,[x23,#28]
str w0,[x23,#32]
ldr w8,[x20]
str w8,[x23,#52]
str wzr,[x23,#40]
ldr x9,[x20,#8]
ldr w9,[x9,#8]
str w9,[x23,#44]
mov w8,#1
str w8,[x23,#36]
done:
ldr x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#64
ret
''', evidence=['0x6d3dea4 returns the final compact record',
        'final request state/kind must equal original request conversion',
               'only the durable state-handler record may consume the stage'])

    # x0 actor, x1 actual compact record, w2 actual native animation ID.
    # Returns the adjusted native base rate, even when there is no skill.
    builder.helper('studio_prepare_committed_windup', f'''
stp x19,x20,[sp,#-80]!
stp x21,x22,[sp,#16]
stp x23,x30,[sp,#32]
stp d8,d9,[sp,#48]
mov x19,x0
mov x20,x1
mov w21,w2
ldr s8,[x20,#0x24]
fmov s9,#1.0
mov w1,#1
bl shared_studio_restore_windup
mov x0,x19
bl shared_studio_kick_slot
cbz x0,done
mov x22,x0
ldr w8,[x22,#36]
str wzr,[x22,#36]
cmp w8,#1
b.ne done
ldr x8,[x22]
cmp x8,x19
b.ne done
ldr x8,[x22,#8]
ldr x9,[x19,#0x4620]
cmp x8,x9
b.ne done
ldr x8,[x22,#16]
cmp x8,x20
b.ne done
ldr w8,[x22,#24]
mov w9,#0x2dce
ldrh w9,[x19,x9]
cmp w8,w9
b.ne done
ldr w8,[x22,#52]
ldrb w9,[x19,#0xad0]
cmp w8,w9
b.ne done
str w21,[x22,#52]
str s8,[x22,#48]
ldr x8,[x22,#56]
add x8,x8,#1
str x8,[x22,#56]
mov w8,#2
str w8,[x22,#36]
str wzr,[x22,#40]
ldr w23,[x22,#32]
cmp w23,#1
b.eq short_pass
cmp w23,#2
b.eq through
cmp w23,#3
b.eq through
cmp w23,#4
b.eq air_pass
cmp w23,#5
b.eq shot
b done
short_pass:
mov x0,x19
mov w1,#77
{call('flag')}
tbz w0,#0,done
mov x0,x19
bl shared_studio_nearest_live_opponent
cbz x0,done
ldr s1,close_distance_squared
fcmp s0,s1
b.vs done
b.gt done
mov w8,#1
str w8,[x22,#40]
ldr s9,fast_factor
b speed
through:
mov x0,x19
mov w1,#76
{call('flag')}
tbz w0,#0,check_air
mov w8,#2
str w8,[x22,#40]
ldr s9,fast_factor
b speed
check_air:
cmp w23,#3
b.ne done
air_pass:
mov x0,x19
mov w1,#72
{call('flag')}
tbz w0,#0,done
ldr s9,air_factor
b speed
shot:
mov x0,x19
mov w1,#74
{call('flag')}
tbz w0,#0,done
ldr s0,[x22,#44]
fmov s1,#0.5
fcmp s0,s1
b.vs done
b.ge heavy
ldr w0,[x22,#24]
{call('category')}
cmp w0,#5
b.eq heavy
cmp w0,#6
b.ne done
heavy:
mov w8,#4
str w8,[x22,#40]
b done
speed:
mov x0,x19
fmov s0,s8
fmov s1,s9
bl shared_studio_begin_windup
fmov s8,s0
mov x0,x19
bl shared_studio_windup_slot
cbz x0,done
ldr w8,[x22,#24]
str w8,[x0,#16]
done:
fmov s0,s8
ldp d8,d9,[sp,#48]
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#80
ret
''', {'flag': 0x6dcd87c, 'category': 0x6d3fb94},
        {'close_distance_squared': 2.25, 'fast_factor': .8, 'air_factor': .88},
        ['0x6d3ef68: original base R is also used by contact-time conversion',
         'short-pass pressure qualification is locked at motion start',
         'through and air-pass bonuses take the strongest duration factor',
         'heavy-shot eligibility belongs to this actual selected action'])

    builder.helper('studio_cancel_committed_kick', '''
stp x19,x30,[sp,#-16]!
mov x19,x0
mov w1,#1
bl shared_studio_restore_windup
mov x0,x19
bl shared_studio_kick_slot
cbz x0,done
str wzr,[x0,#36]
str wzr,[x0,#40]
done:
ldp x19,x30,[sp],#16
ret
''', evidence=['new non-kick motion clears provenance and restores an owned rate first'])

    builder.helper('studio_committed_error_factors', f'''
stp x19,x20,[sp,#-80]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
str d10,[sp,#48]
mov x19,x0
fmov s8,#1.0
fmov s9,#1.0
fmov s10,#1.0
bl shared_studio_kick_slot
cbz x0,done
mov x20,x0
ldr w8,[x20,#36]
cmp w8,#2
b.ne done
ldr x8,[x20]
cmp x8,x19
b.ne done
ldr x8,[x20,#8]
ldr x9,[x19,#0x4620]
cmp x8,x9
b.ne done
ldr w8,[x20,#24]
mov w9,#0x2dce
ldrh w9,[x19,x9]
cmp w8,w9
b.ne done
ldr w8,[x20,#52]
mov w9,#0x2dd0
ldrh w9,[x19,x9]
cmp w8,w9
b.ne done
ldr w8,[x20,#32]
ldr w21,[x20,#40]
ldrb w9,[x19,#0xad0]
cmp w8,#5
b.ne pass_state
cmp w9,#10
b.eq shot
b done
pass_state:
cmp w9,#9
b.ne done
cmp w8,#1
b.eq short_pass
cmp w8,#2
b.eq through
cmp w8,#3
b.ne done
through:
tbz w21,#1,done
ldr s8,pass_factor
b done
short_pass:
tbz w21,#0,done
ldr s8,pass_factor
fmov s9,s8
fmov s10,s8
b done
shot:
tbz w21,#2,cold_check
ldr s8,heavy_factor
fmov s9,s8
cold_check:
mov x0,x19
mov w1,#75
{call('flag')}
tbz w0,#0,done
mov x0,x19
bl shared_studio_in_opposing_penalty_area
cbz w0,done
mov x0,x19
bl shared_studio_nearest_live_opponent
cbz x0,done
ldr s1,shoot_distance_squared
fcmp s0,s1
b.vs done
b.gt done
ldr s0,cold_factor
fmin s8,s8,s0
fmin s9,s9,s0
done:
fmov s0,s8
fmov s1,s9
fmov s2,s10
ldr d10,[sp,#48]
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#80
ret
''', {'flag': 0x6dcd87c},
        {'pass_factor': .8, 'heavy_factor': .8, 'cold_factor': .85,
         'shoot_distance_squared': 4.}, evidence=[
            'committed action identity, never a prediction-time temporary skill flag',
            'short-pass qualification remains locked from its start',
            'cold finisher evaluates opposing box and nearest opponent at release',
            'returns yaw/pitch/speed random-error factors, strongest per component'])

    stage = save_all() + f'''
mov x0,x21
add x1,x20,#0xd8
add x2,sp,#{FRAME + 0x198}
add x3,x19,#0x80
add x4,sp,#{FRAME + 0x58}
bl shared_studio_stage_committed_kick
''' + restore_all() + f'''
ldp q0,q1,[sp]
{jump('resume')}
'''
    builder.add('studio_committed_kick_stage', 0x6d3dea8, stage,
                {'resume': 0x6d3deac})

    prepare = save_all() + f'''
mov x0,x20
mov x1,x19
mov w2,w21
bl shared_studio_prepare_committed_windup
str s0,[sp,#{SIMD + 8 * 16}]
''' + restore_all() + jump('resume')
    builder.add('studio_committed_windup_start', 0x6d3ef68, prepare,
                {'resume': 0x6d3ef6c})

    # The native offset solver otherwise uses the faster R to select an earlier
    # clip offset. For R < 1 this can exactly cancel the intended shorter phase.
    # Keep the original offset calculation at saved R, while the queue and
    # actual event windows continue to use the faster R.
    offset = save_all() + f'''
mov x0,x20
fmov s0,s8
bl shared_studio_windup_original_clip_rate
ldr s1,[sp,#{SIMD}]
fmul s0,s1,s0
str s0,[sp,#{SIMD}]
''' + restore_all() + jump('resume')
    builder.add('studio_windup_preserve_original_clip_offset',0x6d3f100,offset,
                {'resume':0x6d3f104},evidence=[
                    'original 0x6d3f0e4..0x6d3f118 chooses clip start from contact metadata',
                    'preserve original start offset, while queue and event windows use the faster rate'])

    cancel = save_all() + f'''
ldr x8,[sp,#240]
ldr x9,committed_return
cmp x8,x9
b.eq done
bl shared_studio_cancel_committed_kick
done:
''' + restore_all() + f'''
mov w8,#0x1eca
{jump('resume')}
'''
    builder.add('studio_other_motion_cancels_windup', 0x6dccb08, cancel,
                {'committed_return': 0x6d3f148, 'resume': 0x6dccb0c},
                evidence=['native animation queue, before the new rate is installed'])

    for address, displaced in ((0x6d42570, 'ldr x8,[x19,#0x20]'),
                               (0x6d424e0, 'mov w8,#0xd70a')):
        release = save_all() + '''
mov x0,x21
mov w1,#0
bl shared_studio_restore_windup
''' + restore_all() + displaced + '\n' + jump('resume')
        builder.add('studio_real_ball_release_' + hex(address), address, release,
                    {'resume': address + 4}, evidence=[
                        'actual strike output after hit-count guard, or native special-release branch',
                        'restore saved R once; repeated output calls are harmless'])
