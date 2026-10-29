"""V17 AI preference over native, already evaluated ball-player candidates.

No synthetic shot/movement is inserted. The native priority list, candidate
validity and continuation veto are retained; only eligible alternatives are
promoted. This module does not modify the player/card skill flags.
"""
import hashlib
import json
import struct
from pathlib import Path
from skill_hook_ir import Hooks, call, jump
from ai_opportunity import add_opportunity_helpers, COMPARISON_WINDOW, PREFERENCE_BONUS
from ai_selection import add_selection_helpers

ENGINE_SHA='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
REVISION='v17-ai-cut-in-opportunity-v4-equal-shot-styles'


def add_ai_cut_in_shots(b):
    add_opportunity_helpers(b)
    # Result: w0 = 0 off / 1 shooting / 2 curler / 3 blitz curler;
    # x1 = live PlayerInfo; x2 = pitch; w3 = attacking side; s0 = goal-X
    # distance; s1 = signed lateral position. Native parameter 66 maps to
    # match AI bit 4, NOT bit 3 (which is Early Crosser).
    b.helper('studio_ai_cut_in_profile', f'''
stp x19,x20,[sp,#-112]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x26,[sp,#48]
str x30,[sp,#64]
stp d8,d9,[sp,#80]
mov x19,x0
mov w24,#0
cbz x19,done
ldr x21,[x19]
ldr x20,[x19,#0x18]
cbz x21,done
cbz x20,done
ldr w22,[x21]
cmp w22,#22
b.hs done
mov x0,x20
{call('game_info')}
cbz x0,done
{call('phase')}
cmp w0,#1
b.ne done
mov x0,x20
mov w1,w22
{call('player_state')}
cbz x0,done
{call('abilities')}
mov x23,x0
cbz x23,done
ldr w8,[x23,#0xd4]
tbnz w8,#7,check_skills
bl shared_studio_ai_preference_enabled
cbz w0,done
check_skills:
mov x0,x23
mov w1,#51
{call('skill')}
tbnz w0,#0,blitz
ldr w8,[x23,#0xd4]
tbnz w8,#7,other_skills
tbz w8,#4,done
other_skills:
mov x0,x23
mov w1,#7
{call('skill')}
tbnz w0,#0,curler
mov x0,x23
mov w1,#42
{call('skill')}
tbnz w0,#0,normal_shooter
ldr w8,[x23,#0xd4]
tbz w8,#7,done
normal_shooter:
mov w24,#1
b position
blitz:
mov w24,#3
b position
curler:
mov w24,#2
position:
mov w0,w22
{call('team')}
mov w1,w0
mov x0,x20
{call('team_data')}
cbz x0,no
ldrsb w23,[x0,#0x28c]
cmp w23,#1
b.eq side_ok
cmn w23,#1
b.ne no
side_ok:
mov x0,x20
{call('pitch')}
mov x26,x0
cbz x26,no
mov x0,x20
mov w1,w22
{call('player_info')}
mov x25,x0
cbz x25,no
ldr s8,[x25,#0x4f4]
ldr s9,[x25,#0x4fc]
ldr s0,[x26]
ldr s1,min_half_length
fcmp s0,s1
b.vs no
b.lt no
ldr s1,max_half_length
fcmp s0,s1
b.gt no
scvtf s1,w23
fmul s8,s8,s1
fsub s8,s0,s8
fcmp s8,#0.0
b.vs no
b.lt no
fabs s0,s9
fcmp s0,s0
b.vs no
fmul s0,s0,s0
fmadd s0,s8,s8,s0
ldr s1,min_distance_sq
fcmp s0,s1
b.lt no
ldr s1,max_distance_sq
fcmp s0,s1
b.gt no
mov x1,x25
mov x2,x26
mov w3,w23
fmov s0,s8
fmov s1,s9
b done
no:
mov w24,#0
done:
mov w0,w24
ldp d8,d9,[sp,#80]
ldr x30,[sp,#64]
ldp x25,x26,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#112
ret
''', {'game_info':0x72c3e80,'phase':0x697b60c,
      'player_state':0x72c40b0,'abilities':0x7301ef8,'skill':0x72b39c4,
      'team':0x697d0f8,'team_data':0x72c4028,'pitch':0x72c3e6c,
      'player_info':0x72c408c},
      {'min_half_length':32.,'max_half_length':70.,'max_forward':36.,'min_distance_sq':64.,'max_distance_sq':1936.},
      ['6a74e74 parameter 66 -> AI bit 4; 6a74e94 sets bit 4',
       'original match table c7fec0: skill 18 -> 51, 17 -> 7, 23 -> 42',
       '72b39c4 effective match flags include innate and learned skills',
       'AI candidate path only; normal match phase 1; current half side follows team +28c'])

    # 70e4bfc..70e4c0c constructs {BP AI, GameInfo**, player context, root}.
    # +8 is used by the original selector for game phase; +16 is passed to
    # its continuation veto. Qualification and position need that same +16.
    add_selection_helpers(b)

    address=0x70e57a0
    word=struct.unpack_from('<I',b.engine,address-0x4000)[0]
    b.add('studio_ai_cut_in_candidate_choice',address,f'''
stp x19,x20,[sp,#-32]!
str x30,[sp,#16]
mov x19,x0
bl original
mov w1,w0
mov x0,x19
bl shared_studio_ai_select_cut_in_candidate
ldr x30,[sp,#16]
ldp x19,x20,[sp],#32
ret
original:
.word {word}
{jump('resume')}
''',{'resume':address+4})
    from ai_shot_styles import add_shot_styles
    add_shot_styles(b)
    address=0x70e7430
    word=struct.unpack_from('<I',b.engine,address-0x4000)[0]
    b.add('studio_ai_cut_in_shot_request',address,f'''
stp x19,x20,[sp,#-32]!
str x30,[sp,#16]
mov x19,x0
mov x20,x1
bl original
mov x0,x19
mov x1,x20
bl shared_studio_ai_prefer_curled_shot
ldr x30,[sp,#16]
ldp x19,x20,[sp],#32
ret
original:
.word {word}
{jump('resume')}
''',{'resume':address+4})


def build(engine,release=False):
    if hashlib.sha256(engine).hexdigest()!=ENGINE_SHA:
        raise ValueError('AI cut-in hooks require the audited original V17 engine')
    b=Hooks(engine);add_ai_cut_in_shots(b)
    bundle=b.bundle('studio_ai_cut_in_shots',b.rows+b.helpers)
    ordinary_at=bytes.fromhex(bundle['body_hex']).find(struct.pack('<I',0x58414931))
    if ordinary_at<0:raise ValueError('Missing ordinary AI switch')
    probes=[]
    for name,address,size in [('match_skill_table',0xc83ec0,0x250),('incisive_style_decoder',0x6a74e6c,52),
                              ('native_blitz_branch',0x6d68648,104),('native_shot_dispatch',0x70e5354,180),
                              ('selector_caller_layout',0x70e4bfc,20)]:
        probes.append({'name':name,'file_offset':address-0x4000,'expected_hex':engine[address-0x4000:address-0x4000+size].hex()})
    return {'revision':REVISION,'production_ready':release,'experimental':True,'probes':probes,
            'ordinary_switch_offset':ordinary_at,'engine_sha256':ENGINE_SHA,'hooks':b.rows,'helpers':b.helpers,'bundles':[bundle],
            'priority':['Blitz Curler','Long-range Curler','Long-range Shooting'],
            'qualification':{'ai_parameter':66,'ai_match_bit':4,'lone_wolf_match_bit':7,
                             'lone_wolf_parameter':151,'blitz_requires_incisive':False,
                             'skills':{'18':51,'17':7,'23':42}},
            'shot_styles':{'stage':'only after native CPU chooses a shot','weights':'one equal ticket per available skill',
                           'styles':{'Blitz Curler':{'match_skill':51,'request_subtype':1,'power_min':.55},
                                     'Low Screamer':{'match_skill':58,'request_subtype':0,'power_max':.49},
                                     'Heavy Shot':{'match_skill':74,'request_subtype':2,'power_min':.65}},
                           'all_shooting_positions':True,'native_motion_checks_preserved':True,
                           'low_and_blitz_coexist':'current CPU actor/root, at most two native ticks'},
            'selector_layout':{'game_context_offset':8,'player_context_offset':16,'native_caller':'0x70e4bfc'},
            'opportunity':{'scale':'workshop positional heuristic, not native utility or xG',
                           'window':COMPARISON_WINDOW,'bonus':0,'ordinary_choice':'equal action classes',
                           'lone_wolf':'safe shot first, otherwise reposition; inward if Incisive Run',
                           'posture':'native heading, strong-foot space, estimated open-body alignment',
                           'snapshot_once':True,
                           'candidate_evaluations':'one per unique ID','unknown':'keep original',
                           'protected':['open box reception','clear defensive-line penetration'],
                           'decoded_pass_modes':['ordinary ground pass'],'gameplay_calibrated':False},
            'limits':{'native_candidates_only':True,'native_shot_checks_retained':True,
                      'gameplay_acceptance':'pending user testing'}}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--output',required=True)
    p.add_argument('--release',action='store_true');a=p.parse_args()
    data=build(Path(a.engine).read_bytes(),a.release)
    Path(a.output).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'hooks':len(data['hooks']),'body_bytes':len(bytes.fromhex(data['bundles'][0]['body_hex']))}))
