"""Candidate skill hooks based on the original V17 instruction audit.

The explicit --output path keeps incomplete candidates away from production
resources. Runtime integration is gated on the remaining action/phase audit.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skill_hook_ir import Hooks, call, jump, save_all, restore_all, FRAME, SIMD
from build_custom_skill_protocol import add_protocol
from build_skill_conditions import add_conditions
from build_skill_windup import add_windup_state
from build_skill_actions import add_actions
from custom_skills import REVISION as CUSTOM_PROTOCOL
from build_skill_trajectory import add_trajectory
from build_skill_shield import add_shield

ENGINE_SHA = 'efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
FLAG = 0x6dcd87c


def retained_native_hooks(builder):
    """Keep the working Low Screamer change and isolate repurposed flags.

    Heavy-shot eligibility now lives in committed action provenance, so the
    old candidate-selection hook and its transient match flag are unnecessary.
    No hook at the old miss-score or tight-possession inputs is retained.
    """
    for name,address in (('unused_amazon',0x6eede10),('unused_mekong',0x70d3b50),
                         ('unused_congo',0x70d3c84)):
        builder.add('studio_'+name,address,'mov w0,#0\nret\n')
    for address in (0x6d6281c,0x6d6878c,0x6d688b4):
        builder.add('studio_unused_indus_'+hex(address),address,
                    'mov w0,#0\n'+jump('resume'),{'resume':address+4})
    builder.add('studio_low_screamer_normal_shot',0x6d627c0,
                'mov w10,#0\n'+jump('resume'),{'resume':0x6d627c4},
                evidence=['same retained Low Screamer hook as the released runtime',
                          'the original skill and strictly below 50% power guards remain native'])


def generator_hooks(builder):
    """Contract selected sampled components without changing the RNG sequence.

Both generators receive a nominal yaw/pitch/speed tuple. The normal generator
has several pitch branches; contracting its complete result once also avoids
double scaling when a pitch modulation follows the first sampled error.
"""
    for address, base_reg, result_reg in ((0x6d51bd8, 2, 3), (0x6d51d80, 3, 4)):
        displaced = struct.unpack_from('<I', builder.engine, address - 16384)[0]
        code = f'''
stp x19,x20,[sp,#-96]!
stp x21,x30,[sp,#16]
stp d8,d9,[sp,#32]
str d10,[sp,#48]
mov x19,x0
mov x20,x{base_reg}
mov x21,x{result_reg}
ldr d16,[x20]
str d16,[sp,#56]
ldr w16,[x20,#8]
str w16,[sp,#64]
bl original
mov x0,x19
bl shared_studio_committed_error_factors
fmov s8,s0
fmov s9,s1
fmov s10,s2
fmov s0,#1.0
fcmp s8,s0
b.eq pitch
ldr s0,[x21]
ldr s1,[sp,#56]
fsub s2,s0,s1
ldr s3,half_turn
ldr s4,full_turn
fcmp s2,s3
b.vs done
b.le lower_check
fsub s2,s2,s4
lower_check:
fneg s3,s3
fcmp s2,s3
b.ge wrapped
fadd s2,s2,s4
wrapped:
fmul s2,s2,s8
fadd s0,s1,s2
fcmp s0,s4
b.lt below_turn
fsub s0,s0,s4
below_turn:
fcmp s0,#0.0
b.ge yaw_done
fadd s0,s0,s4
yaw_done:
str s0,[x21]
pitch:
fmov s0,#1.0
fcmp s9,s0
b.eq speed
ldr s0,[x21,#4]
ldr s1,[sp,#60]
fsub s0,s0,s1
fmul s0,s0,s9
fadd s0,s1,s0
str s0,[x21,#4]
speed:
fmov s0,#1.0
fcmp s10,s0
b.eq done
ldr s0,[x21,#8]
ldr s1,[sp,#64]
fsub s0,s0,s1
fmul s0,s0,s10
fadd s0,s1,s0
str s0,[x21,#8]
done:
ldr d10,[sp,#48]
ldp d8,d9,[sp,#32]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#96
ret
original:
.word {displaced}
{jump('resume')}
'''
        builder.add('studio_sampled_angular_error_' + hex(address), address, code,
                    {'resume': address + 4},
                    {'half_turn': 180., 'full_turn': 360.},
                    ['original generator output yaw/pitch/speed', 'same native RNG sequence',
                     'shortest signed yaw delta', 'speed changes only for qualified composed short pass'])


def acceleration_hooks(builder):
    """Adjust the actual ability-44 solver input for running and dribbling.

The dribbling hook is after the native integer round trip, immediately at the
solver-config store. Thus the added fraction survives instead of truncating
back to zero. Neither path writes ability 26 or measured world velocity.
"""
    for name,address,player_offset,displaced in (
        ('running',0x6f40b90,0x2b8,'add x0,sp,#0x1e8'),
        ('dribbling',0x6f11ef4,0xc8,'str s0,[sp,#0x208]'),
    ):
        code = save_all() + f'''
ldr x19,[sp,#{FRAME + player_offset}]
mov x0,x19
mov w1,#69
{call('flag')}
tbnz w0,#0,explosive
mov x0,x19
mov w1,#70
{call('flag')}
tbnz w0,#0,controlled
mov x0,x19
mov w1,#73
{call('flag')}
tbz w0,#0,done
ldr s0,[x19,#0x344]
ldr s1,speed_threshold
fcmp s0,s1
b.vs done
b.ge strong
b mild
explosive:
ldr s0,[x19,#0x344]
ldr s1,speed_threshold
fcmp s0,s1
b.vs done
b.lt strong
b mild
controlled:
ldr s0,controlled_bonus
b apply
strong:
ldr s0,strong_bonus
b apply
mild:
ldr s0,mild_bonus
apply:
ldr s1,[sp,#{SIMD}]
fcmp s1,#0.0
b.vs done
b.lt done
fadd s1,s1,s0
ldr s2,ceiling
fmin s1,s1,s2
ldr s2,[sp,#{SIMD}]
fmax s1,s1,s2
str s1,[sp,#{SIMD}]
done:
''' + restore_all() + f'''
{displaced}
{jump('resume')}
'''
        builder.add('studio_' + name + '_acceleration_input', address, code,
                    {'flag': FLAG, 'resume': address + 4},
                    {'speed_threshold': 20., 'controlled_bonus': .06,
                     'strong_bonus': .12, 'mild_bonus': .03, 'ceiling': 1.1},
                    ['0x6f4d714 -> ability 44; mode 1 includes dribbling 24',
                     'running solver config +0x38 / dribbling config +0x208',
                     '0x6f11ef4 occurs AFTER fcvtzs/scvtf; fraction survives'])


def postprocessing_hook(builder):
    """Scale only the signed RNG delta immediately before native angle-add.

The surrounding postprocessor also contains deterministic clamps and velocity
conversion. Those are left intact; the intercepted S0 is the signed random
angular increment from 0x6dd5678/0x6dd564c, not a world angle or vector.
"""
    code = save_all() + f'''
mov x0,x20
bl shared_studio_committed_error_factors
ldr s1,[sp,#{SIMD}]
fmul s0,s1,s0
str s0,[sp,#{SIMD}]
ldr x17,return_address
str x17,[sp,#240]
''' + restore_all() + jump('angle_add')
    builder.add('studio_postprocess_random_yaw',0x6d54ac8,code,
                {'return_address':0x6d54acc,'angle_add':0x6b06cfc},
                evidence=['native signed random yaw at 0x6d54ab8..0x6d54ac8',
                          'all deterministic clamps and native RNG calls remain unchanged'])


def build(engine, release=False):
    if hashlib.sha256(engine).hexdigest() != ENGINE_SHA:
        raise ValueError('Candidate hooks require the audited original V17 engine')
    builder = Hooks(engine)
    retained_native_hooks(builder)
    generator_hooks(builder)
    acceleration_hooks(builder)
    postprocessing_hook(builder)
    add_protocol(builder)
    add_conditions(builder)
    add_windup_state(builder)
    add_actions(builder)
    add_trajectory(builder)
    add_shield(builder)
    bundle = builder.bundle('studio_skill_runtime_v2', builder.rows + builder.helpers)
    return {'revision': 'skill-effects-v2-1.9.12' if release else 'skill-effects-v2-candidate-2',
            'production_ready': bool(release),
            'custom_skill_protocol':CUSTOM_PROTOCOL,
            'engine_sha256': ENGINE_SHA, 'hooks': builder.rows, 'helpers': builder.helpers,
            'bundles': [bundle],
            'validation': {'native_behavior_enum': '0xc91308; getter 0x72e2eec',
                           'short_pass_behaviors': [22,23], 'through_pass_behavior': 24,
                           'ground_and_lofted_through_native_kinds': [1,2,3,4],
                           'gameplay_acceptance': 'pending user testing'}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--release', action='store_true', help='Activate an audited release bundle')
    args = parser.parse_args()
    result = build(Path(args.engine).read_bytes(), release=args.release)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'candidate_hooks': len(result['hooks']), 'production_ready': result['production_ready']}))
