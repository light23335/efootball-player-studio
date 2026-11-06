"""Scoped chance-button strings, using the native localized text setter."""
from pathlib import Path
import hashlib,json,sys
from maintenance.skill_hook_ir import Hooks,save_all,restore_all

SITE=0x3585b48
ENGINE_SHA='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'

def build(engine_path,output):
    raw=Path(engine_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ENGINE_SHA:raise ValueError('Wrong native engine')
    code='''
    cbz x0,fallback
    cbz x2,fallback
    cbz x3,fallback
    cmp w1,#5
    b.hi fallback
    ldr x9,[x0,#0x1380]
    ldr x10,first_agent
    cmp x9,x10
    b.lo fallback
    ldr x10,last_agent
    cmp x9,x10
    b.hs fallback
    stp x29,x30,[sp,#-32]!
    stp x19,x20,[sp,#16]
    mov x19,x3
    mov x0,x2
    mov w1,#63000
    movk w1,#1142,lsl #16
    ldr x16,set_text
    blr x16
    mov x0,x19
    mov w1,#63001
    movk w1,#1142,lsl #16
    ldr x16,set_text
    blr x16
    ldp x19,x20,[sp,#16]
    ldp x29,x30,[sp],#32
    ret
fallback:
    stp x29,x30,[sp,#-0x60]!
    str x28,[sp,#0x10]
    stp x26,x25,[sp,#0x20]
    stp x24,x23,[sp,#0x30]
    ldr x16,resume
    br x16
.align 3
first_agent: .quad 1500000000
last_agent: .quad 1600000000
'''
    builder=Hooks(raw)
    builder.add('tournament_chance_labels',SITE,code,
        {'set_text':0x81efe78,'resume':SITE+16})
    # An empty price vector is intentional: earned chances are the only
    # payment. Stock details skip chance-option initialization when count==0.
    # Keep the real count and enter the original single chance-deal builder,
    # which fills the native button/switcher instead of leaving BP defaults.
    entry=0x358161c
    builder.add('tournament_empty_chance_option',entry,save_all()+'''
    cbnz w10,chance_option
    cbz x21,no_option
    ldr x9,[x21,#0x1380]
    ldr x11,first_agent
    cmp x9,x11
    b.lo no_option
    ldr x11,last_agent
    cmp x9,x11
    b.hs no_option
chance_option:
'''+restore_all()+'''
    ldr x16,with_option
    br x16
no_option:
'''+restore_all()+'''
    ldr x16,without_option
    br x16
.align 3
first_agent: .quad 1500000000
last_agent: .quad 1600000000
''',{'with_option':entry+4,'without_option':0x358163c})
    hook=builder.bundle('tournament_chance_button',builder.rows)
    hook.update(revision='tournament-chance-ui-v2-zero-count-initialization',source_engine_sha256=ENGINE_SHA,
        body_sha256=hashlib.sha256(bytes.fromhex(hook['body_hex'])).hexdigest(),
        native_probes=[{'file_offset':at-0x4000,'expected_hex':raw[at-0x4000:at-0x4000+n].hex()}
            for at,n in ((0x81efe78,64),(0x3585bb8,8),(0x3585cbc,24),(0x3586934,64),(0x3586a40,32),
                         (0x35815bc,0x734),(0x3589424,0x438))],
        execution_proof={'independent_instruction_probe':False,'gameplay_validated':False},
        scope='Reserved tournament chance IDs; initialize the original chance option at count0 without changing count, currency or prices')
    hook['native_probes'].append({'address':0xc32e58,'file_offset':0xc32e58,
                                  'expected_hex':raw[0xc32e58:0xc32e60].hex()})
    Path(output).write_text(json.dumps(hook,ensure_ascii=False,indent=2),'utf8')

if __name__=='__main__':build(*sys.argv[1:])
