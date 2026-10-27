"""Extend the audited V17 detail widget consumers, not just their input lists."""
from skill_hook_ir import call,jump,save_all,restore_all,FRAME


def add_widgets(b):
    b.helper('skill_widget_assign', '''
// x0 libc++ map begin/header, w1 row index, x2 widget. Return node.
stp x19,x20,[sp,#-64]!
stp x21,x22,[sp,#16]
stp x23,x30,[sp,#32]
mov x19,x0
mov w20,w1
mov x21,x2
add x23,x19,#8
mov x22,x23
ldr x8,[x23]
search:
cbz x8,insert
ldr w9,[x8,#32]
cmp w20,w9
b.eq existing
mov x22,x8
add x23,x8,#8
csel x23,x8,x23,lt
ldr x8,[x23]
b search
existing:
str x21,[x8,#40]
mov x0,x8
b done
insert:
mov w0,#48
''' + call('allocate') + '''
mov x9,x0
stp xzr,xzr,[x9]
str x22,[x9,#16]
str w20,[x9,#32]
str x21,[x9,#40]
str x9,[x23]
ldr x8,[x19]
ldr x8,[x8]
cbz x8,begin_ready
str x8,[x19]
begin_ready:
mov x21,x9
ldr x0,[x19,#8]
mov x1,x9
''' + call('balance') + '''
ldr x8,[x19,#16]
add x8,x8,#1
str x8,[x19,#16]
mov x0,x21
done:
ldp x23,x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#64
ret
''',{'allocate':0x8c1bbd0,'balance':0x2f46e8c})
    b.helper('skill_widget_find', '''
// x0 map begin/header, w1 index. Return widget, or null without mutation.
ldr x8,[x0,#8]
search:
cbz x8,missing
ldr w9,[x8,#32]
cmp w1,w9
b.eq found
add x10,x8,#8
csel x10,x8,x10,lt
ldr x8,[x10]
b search
found:
ldr x0,[x8,#40]
ret
missing:
mov x0,xzr
ret
''')
    b.helper('skill_widget_create_rows', '''
stp x19,x20,[sp,#-48]!
stp x21,x22,[sp,#16]
str x30,[sp,#32]
mov x19,x0
mov x20,x1
mov w22,w2
mov w21,#1
loop:
mov x0,x19
mov x1,x20
''' + call('create') + '''
mov x2,x0
mov w1,w21
mov w8,#0x1358
add x0,x19,x8
bl shared_skill_widget_assign
add w21,w21,#1
cmp w21,w22
b.le loop
ldr x30,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#48
ret
''',{'create':0x3052434})
    b.helper('skill_widget_fill_rows', '''
stp x19,x20,[sp,#-80]!
stp x21,x22,[sp,#16]
stp x23,x24,[sp,#32]
stp x25,x30,[sp,#48]
mov x19,x0
mov x20,x1
mov x21,x2
ldr w22,[x20,#8]
ldr w8,[x21,#8]
cmp w22,w8
csel w22,w22,w8,le
cmp w22,#100
mov w8,#100
csel w22,w22,w8,le
mov w8,#0x1358
add x0,x19,x8
mov w1,#0
bl shared_skill_widget_find
cbz x0,rows
mov x24,x0
mov x0,x19
mov w1,#6
''' + call('heading') + '''
mov w1,w0
mov x0,x24
mov w2,#1
''' + call('set_heading') + '''
rows:
mov w23,#0
cmp w22,#1
b.lt done
loop:
mov w8,#0x1358
add x0,x19,x8
add w1,w23,#1
bl shared_skill_widget_find
cbz x0,next
ldr x8,[x20]
add x1,x8,w23,uxtw #4
ldr x8,[x21]
ldr w8,[x8,w23,uxtw #2]
cmp w8,#74
cset w2,ne
''' + call('set_row') + '''
next:
add w23,w23,#1
cmp w23,w22
b.lt loop
done:
ldp x25,x30,[sp,#48]
ldp x23,x24,[sp,#32]
ldp x21,x22,[sp,#16]
ldp x19,x20,[sp],#80
ret
''',{'heading':0x305b714,'set_heading':0x30468f0,'set_row':0x3047108})
    # These two signed guards are the direct cause of an entirely blank page.
    for name,address in (('owned',0x3051594),('library',0x2f457d0)):
        b.add('skill_widget_'+name+'_innate_bound',address,
              'cmp w8,#100\n'+jump('resume'),{'resume':address+4})
    # The original constructor creates its heading before this first row call.
    # Existing <=5 layouts use the unmodified five-row constructor.
    b.add('skill_widget_additional_creation',0x304bb0c,
          'sub sp,sp,#512\n'+save_all()+f'''
mov x0,x19
''' + call('player') + f'''
cbz x0,original
add x0,x0,#0x30
add x1,sp,#{FRAME}
mov w3,#0
bl shared_skill_capacity_cache
cmp w0,#5
b.le original
mov w2,w0
mov x0,x19
mov x1,x20
bl shared_skill_widget_create_rows
'''+restore_all()+'add sp,sp,#512\n'+jump('done')+'''
original:
'''+restore_all()+'add sp,sp,#512\n'+call('create')+'\n'+jump('resume'),
          {'player':0x302b480,'create':0x3052434,'resume':0x304bb10,'done':0x304be70})
    b.add('skill_widget_additional_display',0x305191c, '''
cmp w8,#5
b.le original
cmp w8,#100
b.gt invalid
'''+save_all()+'''
mov x0,x19
mov x1,x21
mov x2,x20
bl shared_skill_widget_fill_rows
'''+restore_all()+jump('done')+'''
invalid:
'''+jump('done')+'''
original:
cmp w8,#5
'''+jump('resume'),{'done':0x305208c,'resume':0x3051920})
    # The secondary skill-info modal also constructs exactly five rows.
    b.add('skill_widget_additional_modal',0x30fb0dc, '''
ldr w8,[x19,#0x12f0]
cmp w8,#5
b.le original
'''+save_all()+'''
mov x24,#0
ldr w25,[x19,#0x12f0]
cmp w25,#100
mov w8,#100
csel w25,w25,w8,le
loop:
ldr x8,[x19,#0x12e8]
ldr w2,[x8,x24,lsl #2]
mov x0,x19
mov x1,x20
'''+call('add_row')+'''
add x24,x24,#1
cmp x24,x25
b.lt loop
'''+restore_all()+jump('done')+'''
original:
'''+jump('resume'),{'add_row':0x30fb51c,'done':0x30fb1b0,'resume':0x30fb0e0})
