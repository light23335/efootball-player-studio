"""Audited V17 transport for four new independent skill markers.

This is a candidate builder, not an installer. Effect hooks and production
integration have a separate readiness gate.
"""
import struct
from skill_hook_ir import call, jump
from custom_skills import (FIRST_ID, FIRST_PARAMETER, FIRST_MATCH_FLAG, COUNT,
                           SOURCE_BIT, COMPACT_OFFSET, COMPACT_TAG, messages)


def original_word(builder, address):
    return struct.unpack_from('<I', builder.engine, address - 16384)[0]


def instruction(builder, name, address, replacement):
    builder.add(name, address, replacement + '\n' + jump('resume'), {'resume': address + 4})


def add_protocol(builder):
    # The source decoder is the only place which reads the four new disk bits.
    # Native mode 1 uses another record layout; never interpret it as Player.bin.
    address = 0x82aa124
    builder.add('studio_custom_skill_decode', address, f'''
stp x19,x20,[sp,#-32]!
stp x21,x30,[sp,#16]
mov x19,x0
mov x20,x1
mov w21,w2
bl original
mov w8,#0
cbnz w21,tag
ldrb w8,[x20,#{SOURCE_BIT // 8}]
ubfx w8,w8,#{SOURCE_BIT % 8},#{COUNT}
tag:
mov w9,#{COMPACT_TAG & 65535}
movk w9,#{COMPACT_TAG >> 16},lsl #16
orr w8,w8,w9
str w8,[x19,#{COMPACT_OFFSET}]
ldp x21,x30,[sp,#16]
ldp x19,x20,[sp],#32
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''', {'resume': address + 4}, evidence=['Player.bin bits 683..686', 'compact tagged padding +0x34'])

    address = 0x82a84d4
    builder.add('studio_custom_skill_get_parameter', address, f'''
sub w8,w1,#{FIRST_PARAMETER}
cmp w8,#{COUNT-1}
b.hi original
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
mov w11,#{COMPACT_TAG & 65535}
movk w11,#{COMPACT_TAG >> 16},lsl #16
cmp w10,w11
lsr w9,w9,w8
and w9,w9,#1
csel w9,w9,wzr,eq
str w9,[x2]
mov w0,#1
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''', {'resume': address + 4})

    address = 0x82a907c
    builder.add('studio_custom_skill_set_parameter', address, f'''
sub w8,w1,#{FIRST_PARAMETER}
cmp w8,#{COUNT-1}
b.hi original
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
mov w11,#{COMPACT_TAG & 65535}
movk w11,#{COMPACT_TAG >> 16},lsl #16
cmp w10,w11
csel w9,w9,w11,eq
mov w10,#1
lsl w10,w10,w8
bic w9,w9,w10
and w10,w2,#1
lsl w10,w10,w8
orr w9,w9,w10
str w9,[x0,#{COMPACT_OFFSET}]
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''', {'resume': address + 4})

    address = 0x82a2220
    builder.add('studio_custom_skill_parameter_id', address, f'''
sub w8,w0,#{FIRST_ID}
cmp w8,#{COUNT-1}
b.hi original
add w0,w8,#{FIRST_PARAMETER}
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''', {'resume': address + 4})

    address = 0x82bb60c
    values = ','.join(str(row['name_msg']) for row in messages())
    builder.add('studio_custom_skill_name_message', address, f'''
ldr w8,[x0]
sub w9,w8,#{FIRST_PARAMETER}
cmp w9,#{COUNT-1}
b.hi original
adr x10,names
ldr w0,[x10,w9,uxtw #2]
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
.align 2
names: .word {values}
''', {'resume': address + 4})

    # Do not enlarge the owned player's 147-parameter override loop. Its source
    # has no extension data; copying virtual zeros would erase the native card's
    # four markers. The native catalogue copy already preserves tagged padding.
    instruction(builder, 'studio_custom_skill_name_bound', 0x82bb678, 'cmp w0,#77')
    instruction(builder, 'studio_custom_skill_list_bound', 0x737a314, 'cmp w22,#78')

    # Native match flags use three 32-bit words for 75 flags. 79 still occupies
    # exactly those same twelve bytes. Expand the checked count and copy bound.
    instruction(builder, 'studio_custom_skill_match_count', 0x72b3c20, 'mov w0,#79')
    instruction(builder, 'studio_custom_skill_match_copy_bound', 0x6b92bcc, 'cmp w23,#79')

    # Reproduce the original 74 descriptor pairs and append independent flags.
    # The table is PC relative in the new hook; original rodata is untouched.
    original_table = builder.engine[0xc7fec0:0xc7fec0 + 0x250]
    pairs = list(struct.unpack('<' + 'I' * (len(original_table) // 4), original_table))
    for index in range(COUNT):
        pairs += [FIRST_MATCH_FLAG + index, FIRST_ID + index]
    builder.add('studio_custom_skill_match_table', 0x6a74c0c, f'''
adr x23,table
{jump('resume')}
.align 3
table: .word {','.join(map(str,pairs))}
''', {'resume': 0x6a74c14})
    instruction(builder, 'studio_custom_skill_match_table_bound', 0x6a74c38, 'cmp x22,#624')

    # The detail screen had a thirty-byte flag array immediately after a live
    # 464-byte player record. Increasing its loop bound in place would corrupt
    # the record or stack canary. An outer stack frame owns the new array.
    address = 0x30e8964
    builder.add('studio_custom_skill_detail_frame', address, f'''
sub sp,sp,#112
str x30,[sp]
stp xzr,xzr,[sp,#32]
stp xzr,xzr,[sp,#48]
str wzr,[sp,#64]
bl original
ldr x30,[sp]
add sp,sp,#112
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''', {'resume': address + 4})
    instruction(builder, 'studio_custom_skill_detail_flags_write', 0x30e89b0, 'add x23,x29,#0x80')
    instruction(builder, 'studio_custom_skill_detail_flags_read', 0x30e8a7c, 'add x8,x29,#0x80')
    instruction(builder, 'studio_custom_skill_detail_scan_bound', 0x30e89e0, 'cmp x24,#34')
    instruction(builder, 'studio_custom_skill_detail_text_bound', 0x30e8a74, 'cmp x22,#34')
    data = builder.engine[0xc3b070:0xc3b4a8]
    for row in messages():
        data += struct.pack('<9I', row['id'], row['name_msg'], row['description_msg'], 0, 0, 0, 0, 0, 0)
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    builder.add('studio_custom_skill_detail_descriptors', 0x30e89b4, f'''
adr x21,table
{jump('resume')}
.align 3
table: .word {','.join(map(str,words))}
''', {'resume': 0x30e89bc})
