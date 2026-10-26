"""V17 owned skill lists: retain the five-slot ABI and snapshot a 10-slot sidecar.

The JSON vector is dynamic, but the decoded common-player object is not. No
inline field or original record size is enlarged. The UI keeps its existing
std::vector name/ID appenders, with a private stack snapshot of all ten IDs.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile
from skill_hook_ir import Hooks, jump, save_all, restore_all, FRAME

REVISION = 'v17-owned-skills-20-10-v2-widgets'
CAPACITY = 65536
STATE_BYTES = 64 + CAPACITY * 64


def build(engine):
    b = Hooks(engine)
    # Original transport IDs 0..73 are the native IDs, in the same order.
    expected = tuple(v for i in range(74) for v in (i, i))
    if struct.unpack_from('<148I', engine, 0xc9df1c) != expected:
        raise ValueError('追加技能原生编号映射改变')
    b.helper('skill_capacity_cache', f'''
// x0 common player, x1 40-byte IDs, w2 count, w3 0 read / 1 write.
// A short native lock protects publication and the entire snapshot copy.
ldr x6,state
acquire:
ldaxr w7,[x6]
cbnz w7,acquire
mov w7,#1
stxr w8,w7,[x6]
cbnz w8,acquire
ldp x4,x5,[x0,#8]
eor x9,x4,x4,lsr #32
eor x9,x9,x5
eor x9,x9,x5,lsr #32
and w9,w9,#65535
mov w10,#65536
probe:
add x11,x6,#64
add x11,x11,x9,lsl #6
ldp x12,x13,[x11]
cbz x12,empty
cmp x12,x4
ccmp x13,x5,#0,eq
b.eq found
next:
add w9,w9,#1
and w9,w9,#65535
subs w10,w10,#1
b.ne probe
b.miss
empty:
cbz w3,miss
cmp w2,#5
b.le miss
stp x4,x5,[x11]
found:
cbz w3,read
str w2,[x11,#16]
ldp q0,q1,[x1]
ldr x12,[x1,#32]
stur q0,[x11,#20]
stur q1,[x11,#36]
str x12,[x11,#52]
mov w0,w2
b.release
read:
ldr w0,[x11,#16]
ldur q0,[x11,#20]
ldur q1,[x11,#36]
ldr x12,[x11,#52]
stp q0,q1,[x1]
str x12,[x1,#32]
b.release
miss:
mov w0,#-1
release:
stlr wzr,[x6]
ret
'''.replace('b.miss','b miss').replace('b.release','b release'), writable={'state': STATE_BYTES})

    # Process the dynamic input list once, copy only the original five inline
    # IDs, and retain all ten in the cache before the input vector is destroyed.
    # Native 74 remains EMPTY; new independent skills are 75..78.
    b.add('skill_capacity_transport', 0x765613c, save_all() + f'''
sub sp,sp,#64
mov w8,#74
mov w9,#0
fill:
str w8,[sp,w9,uxtw #2]
add w9,w9,#1
cmp w9,#10
b.ne fill
ldp x10,x11,[x19,#0xd8]
sub x11,x11,x10
lsr x11,x11,#2
cmp x11,#10
mov x12,#10
csel x11,x11,x12,lo
mov w9,#0
cbz x11,copy_inline
copy_input:
ldr w8,[x10,x9,lsl #2]
cmp w8,#78
mov w12,#74
csel w8,w8,w12,ls
str w8,[sp,x9,lsl #2]
add x9,x9,#1
cmp x9,x11
b.lo copy_input
copy_inline:
ldp x8,x9,[sp]
ldr w10,[sp,#16]
stur x8,[x20,#0x64]
stur x9,[x20,#0x6c]
str w10,[x20,#0x74]
mov x0,x20
mov x1,sp
mov w2,w11
mov w3,#1
bl shared_skill_capacity_cache
add sp,sp,#64
''' + restore_all() + jump('resume'), {'resume': 0x765638c},
          evidence=['fixed DTO additional IDs +0x64..0x74 only', 'dynamic JSON input vector +0xd8',
                    'native sentinel 74; new skill IDs 75..78', 'all callee state restored'])

    # Reserve a private 64-byte outer stack frame for this UI call. The old
    # frame and all frame-relative string lifetimes stay at their old offsets.
    b.add('skill_capacity_list_frame', 0x737a66c,
          'sub sp,sp,#64\nsub sp,sp,#0xd0\n' + jump('resume'), {'resume': 0x737a670})
    b.add('skill_capacity_list_return', 0x737ac94,
          'add sp,sp,#0x110\n' + jump('resume'), {'resume': 0x737ac98})
    b.add('skill_capacity_list_snapshot', 0x737a6ac, save_all() + f'''
add x0,x21,#0x30
add x1,sp,#{FRAME + 0xd0}
mov w3,#0
bl shared_skill_capacity_cache
str w0,[sp,#{FRAME + 0xd0 + 48}]
cmp w0,#5
b.le original
add x8,sp,#{FRAME + 0xd0}
add x9,x8,w0,uxtw #2
stp x8,x9,[sp,#216]
b done
original:
add x8,x21,#0x94
add x9,x21,#0xa8
stp x8,x9,[sp,#216]
done:
''' + restore_all() + jump('resume'), {'resume': 0x737a6b4})
    b.add('skill_capacity_list_padding', 0x737a984, '''
ldr w10,[sp,#0x100]
cmp w10,#5
mov w10,#5
b.le done
mov w10,#10
done:
''' + jump('resume'), {'resume': 0x737a988})

    # The original name vector excludes five additional flags from innate
    # skills. Extend that filter to all ten without moving any object fields.
    b.add('skill_capacity_innate_filter', 0x737a350,
          'sub sp,sp,#64\n' + save_all() + f'''
add x0,x21,#0x30
add x1,sp,#{FRAME}
mov w3,#0
bl shared_skill_capacity_cache
cmp w0,#5
b.le original
mov w9,#0
scan:
add x8,sp,#{FRAME}
ldr w8,[x8,w9,uxtw #2]
cmp w8,w22
b.eq excluded
add w9,w9,#1
cmp w9,w0
b.lo scan
''' + restore_all() + 'add sp,sp,#64\n' + jump('included') + '''
excluded:
''' + restore_all() + 'add sp,sp,#64\n' + jump('excluded_resume') + '''
original:
''' + restore_all() + 'add sp,sp,#64\nldr w8,[x21,#0x120]\n' + jump('resume'),
          {'included': 0x737a380, 'excluded_resume': 0x737a310, 'resume': 0x737a354})
    b.add('skill_capacity_innate_count', 0x737b6ac,
          'sub sp,sp,#64\n' + save_all() + f'''
add x0,x19,#0x30
add x1,sp,#{FRAME}
mov w3,#0
bl shared_skill_capacity_cache
cmp w0,#5
b.le original
neg w8,w0
str x8,[sp,#64]
''' + restore_all() + 'add sp,sp,#64\n' + jump('count_resume') + '''
original:
''' + restore_all() + 'add sp,sp,#64\nldr w8,[x19,#0x120]\n' + jump('resume'),
          {'count_resume': 0x737b70c, 'resume': 0x737b6b0})
    from build_skill_widgets import add_widgets
    add_widgets(b)
    bundle = b.bundle('studio_skill_capacity', b.rows + b.helpers)
    return {'revision': REVISION, 'production_ready': False,
            'engine_sha256': hashlib.sha256(engine).hexdigest(),
            'innate_limit': 20, 'additional_limit': 10, 'cache_capacity': CAPACITY,
            'hooks': b.rows, 'helpers': b.helpers, 'bundles': [bundle]}


if __name__ == '__main__':
    with zipfile.ZipFile(sys.argv[1]) as archive:
        result = build(archive.read('lib/arm64-v8a/libUE4.so'))
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'revision': result['revision'], 'hooks': len(result['hooks']),
                      'state_bytes': STATE_BYTES, 'ready': result['production_ready']}))
