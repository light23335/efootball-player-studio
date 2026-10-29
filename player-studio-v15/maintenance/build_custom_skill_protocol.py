"""Audited V17 transport for four new independent skill markers.

This is a candidate builder, not an installer. Effect hooks and production
integration have a separate readiness gate.
"""
import struct
from skill_hook_ir import call, jump
from custom_skills import (FIRST_NATIVE_ID, FIRST_PARAMETER, FIRST_MATCH_FLAG, COUNT,
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
ldrb w10,[x20,#85]
and w10,w10,#0x80
orr w8,w8,w10
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
cmp w1,#151
b.ne custom_skill
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
bic w10,w10,#0x80
mov w11,#{COMPACT_TAG & 65535}
movk w11,#{COMPACT_TAG >> 16},lsl #16
cmp w10,w11
ubfx w9,w9,#7,#1
csel w9,w9,wzr,eq
str w9,[x2]
mov w0,#1
ret
custom_skill:
sub w8,w1,#{FIRST_PARAMETER}
cmp w8,#{COUNT-1}
b.hi original
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
bic w10,w10,#0x80
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
cmp w1,#151
b.ne custom_skill
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
bic w10,w10,#0x80
mov w11,#{COMPACT_TAG & 65535}
movk w11,#{COMPACT_TAG >> 16},lsl #16
cmp w10,w11
csel w9,w9,w11,eq
bic w9,w9,#0x80
and w10,w2,#1
orr w9,w9,w10,lsl #7
str w9,[x0,#{COMPACT_OFFSET}]
ret
custom_skill:
sub w8,w1,#{FIRST_PARAMETER}
cmp w8,#{COUNT-1}
b.hi original
ldr w9,[x0,#{COMPACT_OFFSET}]
and w10,w9,#0xfffffff0
bic w10,w10,#0x80
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
sub w8,w0,#{FIRST_NATIVE_ID}
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
cmp w8,#151
b.ne custom_skill
mov w0,#60010
movk w0,#352,lsl #16
ret
custom_skill:
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

    # Independent AI-style flag, outside all seven native style bits and the
    # four custom skills. Tagged compact padding survives owned overrides.
    address=0x6a74f08
    builder.add('studio_lone_wolf_match_flag',address,f'''
ldr w8,[x20,#{COMPACT_OFFSET}]
and w9,w8,#0xfffffff0
bic w9,w9,#0x80
mov w10,#{COMPACT_TAG & 65535}
movk w10,#{COMPACT_TAG >> 16},lsl #16
cmp w9,w10
and w8,w8,#0x80
csel w8,w8,wzr,eq
ldr w9,[x19,#0xd4]
bic w9,w9,#0x80
orr w9,w9,w8
str w9,[x19,#0xd4]
add x0,sp,#8
{jump('resume')}
''',{'resume':address+4},evidence=['Player.bin bit 687 -> tagged compact +34 bit 7 -> match AI flag 7',
    'preserves all seven original AI flags; never uses a skill ID'])
    address=0x82a2208
    builder.add('studio_lone_wolf_ai_parameter',address,f'''
cmp w0,#7
b.ne original
mov w0,#151
ret
original:
.word {original_word(builder,address)}
{jump('resume')}
''',{'resume':address+4})
    instruction(builder,'studio_lone_wolf_owned_ai_list',0x7379c7c,'cmp w21,#8')
    instruction(builder,'studio_lone_wolf_library_ai_list',0x2f3e66c,'cmp w21,#8')

    # Do not enlarge the owned player's 147-parameter override loop. Its source
    # has no extension data; copying virtual zeros would erase the native card's
    # four markers. The native catalogue copy already preserves tagged padding.
    instruction(builder, 'studio_custom_skill_name_bound', 0x82bb678, 'cmp w0,#78')
    instruction(builder, 'studio_custom_skill_list_bound', 0x737a314, 'cmp w22,#79')
    instruction(builder, 'studio_custom_skill_library_list_bound', 0x2f45214, 'cmp w21,#79')
    instruction(builder, 'studio_custom_skill_library_count_bound', 0x2f44f90, 'cmp w22,#79')
    instruction(builder, 'studio_custom_skill_owned_count_bound', 0x737b6a4, 'cmp w20,#79')
    instruction(builder, 'studio_custom_skill_additional_text_bound', 0x7b923bc, 'cmp w0,#78')
    # 74 remains the game's empty additional-skill ID. Skip it while walking
    # the expanded ID interval; no original parameter or empty slot is reused.
    for name,address,register,skip in (
        ('owned_list',0x737a328,'w22',0x737a310),
        ('library_list',0x2f4521c,'w21',0x2f45210)):
        builder.add('studio_custom_skill_skip_empty_'+name,address,f'''
cmp {register},#74
b.ne real
{jump('skip')}
real:
mov w0,{register}
{jump('resume')}
''',{'skip':skip,'resume':address+4})
    builder.add('studio_custom_skill_skip_empty_library_count',0x2f44f5c,f'''
cmp w22,#74
b.ne real
mov w28,w27
mov w8,#0
{jump('skip')}
real:
mov w0,w22
{jump('resume')}
''',{'skip':0x2f44f80,'resume':0x2f44f60})
    builder.add('studio_custom_skill_skip_empty_owned_count',0x737b678,f'''
cmp w20,#74
b.ne real
mov w8,#0
{jump('skip')}
real:
mov w0,w20
{jump('resume')}
''',{'skip':0x737b698,'resume':0x737b67c})

    # Native match flags use three 32-bit words for 75 flags. 79 still occupies
    # exactly those same twelve bytes. Expand the checked count and copy bound.
    instruction(builder, 'studio_custom_skill_match_count', 0x72b3c20, 'mov w0,#79')
    instruction(builder, 'studio_custom_skill_match_copy_bound', 0x6b92bcc, 'cmp w23,#79')

    # Reproduce the original 74 descriptor pairs and append independent flags.
    # The table is PC relative in the new hook; original rodata is untouched.
    original_table = builder.engine[0xc7fec0:0xc7fec0 + 0x250]
    pairs = list(struct.unpack('<' + 'I' * (len(original_table) // 4), original_table))
    for index in range(COUNT):
        pairs += [FIRST_MATCH_FLAG + index, FIRST_NATIVE_ID + index]
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
