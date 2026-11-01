"""V17 AI-style display counts, independent of the match decision policy."""
import hashlib
from skill_hook_ir import Hooks,jump
from custom_skills import COMPACT_TAG,COMPACT_OFFSET

ENGINE_SHA='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'

def build(engine):
    if hashlib.sha256(engine).hexdigest()!=ENGINE_SHA:raise ValueError('AI style display requires the audited V17 engine')
    builder=Hooks(engine)
    for name,address,operand in [('owned',0x737b8d0,f'[sp,#{8+COMPACT_OFFSET}]'),
                                 ('library',0x2f3e02c,f'[x19,#{COMPACT_OFFSET}]')]:
        builder.add('studio_lone_wolf_'+name+'_ai_count',address,f'''
// The unrolled native counter has just counted styles 0..6. Preserve it.
cinc w0,w21,eq
ldr w8,{operand}
and w11,w8,#0xfffffff0
bic w11,w11,#0x80
mov w12,#{COMPACT_TAG & 65535}
movk w12,#{COMPACT_TAG >> 16},lsl #16
cmp w11,w12
ubfx w8,w8,#7,#1
csel w8,w8,wzr,eq
add w0,w0,w8
// x9/x10 already hold the native stack canary: never clobber either one.
{jump('resume')}
''',{'resume':address+4},evidence=['Native style counts are unrolled for seven styles, independently of the name-list loop',
    'Adds only the validated tagged Lone Wolf marker; preserves native styles and stack canaries'])
    bundle=builder.bundle('studio_lone_wolf_ai_display_counts',builder.rows)
    for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs','writable','evidence'):bundle.pop(key,None)
    return [bundle]
