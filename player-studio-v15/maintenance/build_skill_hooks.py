from pathlib import Path
import sys,struct,json
from keystone import Ks,KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN
import argparse
p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--resources',default=str(Path(__file__).resolve().parents[1]/'resources'));a=p.parse_args()
root=Path(a.resources);engine=Path(a.engine).read_bytes();ks=Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
FLAG=0x6dcd87c;CTX=0x6d3d9cc;STATE=0x72c40b0;PARAMS=0x7301ef8;SET_FLAG=0x72b3a38

def save_all():
 lines=['sub sp,sp,#688']
 for i in range(0,18,2):lines.append(f'stp x{i},x{i+1},[sp,#{i*8}]')
 lines.append('stp x18,x30,[sp,#144]')
 for i in range(0,32,2):lines.append(f'stp q{i},q{i+1},[sp,#{160+i*16}]')
 return '\n'.join(lines+['mrs x17,nzcv','str x17,[sp,#672]'])
def restore_all():
 lines=['ldr x17,[sp,#672]','msr nzcv,x17']
 for i in range(0,32,2):lines.append(f'ldp q{i},q{i+1},[sp,#{160+i*16}]')
 for i in range(0,18,2):lines.append(f'ldp x{i},x{i+1},[sp,#{i*8}]')
 return '\n'.join(lines+['ldp x18,x30,[sp,#144]','add sp,sp,#688'])
def call(name):return f'ldr x16,{name}\nblr x16'
def jump(name):return f'ldr x16,{name}\nbr x16'
hooks=[]
def add(name,address,code,functions=None,constants=None):
 functions=dict(functions or {});constants=dict(constants or {})
 pool='\n.align 3\n'+'\n'.join(f'{key}: .quad {value}' for key,value in functions.items())+'\n'+'\n'.join(f'{key}: .word {value}' for key,value in constants.items())
 asm=code+pool;body=bytes(ks.asm(asm)[0]);fixes=[]
 for key,value in functions.items():
  needle=struct.pack('<Q',value);offset=body.find(needle);assert offset>=0 and body.find(needle,offset+1)<0 and offset%8==0,(name,key)
  fixes.append([offset,value])
 h={'name':name,'address':address,'file_offset':address-16384,'expected_hex':engine[address-16384:address-16384+64].hex(),'body_hex':body.hex(),'absolute_fixups':fixes,'assembly':asm}
 hooks.append(h)
# Cache Heavy Shot eligibility on the selected player's match skill flags.
# All original source records have AMAZON/INDUS/MEKONG/THAMES/NILE/CONGO unset.
# Match flag 71 is a transient marker, never an innate skill in owned records.
code=save_all()+f'''
mov x0,x27
mov w1,#74
{call('flag')}
tbz w0,#0,lofted
mov w17,#0
ldr w8,[x20,#4]
cmp w8,#8
b.ne set_marker
ldr s0,[x20,#12]
fmov s1,#0.5
fcmp s0,s1
b.vs set_marker
b.ge eligible
cmp w26,#5
b.eq eligible
cmp w26,#6
b.ne set_marker
eligible:
mov w17,#1
set_marker:
str w17,[sp,#680]
mov x0,x27
{call('context')}
mov w8,#0x2a38
ldrb w1,[x27,x8]
{call('state')}
{call('parameters')}
cbz x0,lofted
mov w1,#71
ldr w2,[sp,#680]
{call('set_flag')}
lofted:
ldr w8,[x20,#4]
sub w8,w8,#4
cmp w8,#2
b.hi done
mov x0,x27
mov w1,#72
{call('flag')}
tbz w0,#0,done
ldr s1,lofted_factor
fmul s8,s8,s1
str s8,[sp,#288]
done:
{restore_all()}
mov w8,#0x1ecb
{jump('resume')}
'''
add('studio_shot_marker_and_lofted_windup',0x6d5f640,code,{'flag':FLAG,'context':CTX,'state':STATE,'parameters':PARAMS,'set_flag':SET_FLAG,'resume':0x6d5f644},{'lofted_factor':struct.unpack('<I',struct.pack('<f',1/0.88))[0]})
# Acceleration profile is chosen at compile time from the player's actual height.
code=save_all()+f'''
mov x0,x21
mov w1,#69
{call('flag')}
tbnz w0,#0,explosive
mov x0,x21
mov w1,#70
{call('flag')}
tbnz w0,#0,controlled
mov x0,x21
mov w1,#73
{call('flag')}
tbz w0,#0,done
ldr s0,[x21,#836]
fmov s1,#20.0
fcmp s0,s1
b.vs done
b.ge strong
b mild
explosive:
ldr s0,[x21,#836]
fmov s1,#20.0
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
fadd s9,s9,s0
ldr s1,ceiling
fmin s9,s9,s1
str s9,[sp,#304]
done:
{restore_all()}
mov w8,#0x5c29
{jump('resume')}
'''
floatbits=lambda value:struct.unpack('<I',struct.pack('<f',value))[0]
add('studio_height_acceleration',0x6f2ca9c,code,{'flag':FLAG,'resume':0x6f2caa0},{'controlled_bonus':floatbits(.06),'strong_bonus':floatbits(.12),'mild_bonus':floatbits(.03),'ceiling':floatbits(1.1)})
for address in (0x6d58f94,0x6d5a034):
 displaced=struct.unpack_from('<I',engine,address-16384)[0]
 code=f'''
stp x19,x30,[sp,#-32]!
str d8,[sp,#16]
mov x19,x0
bl original
fmov s8,s0
mov x0,x19
mov w1,#74
{call('flag')}
tbz w0,#0,done
mov x0,x19
mov w1,#71
{call('flag')}
tbz w0,#0,done
ldr s1,accuracy_factor
fmul s8,s8,s1
done:
fmov s0,s8
ldr d8,[sp,#16]
ldp x19,x30,[sp],#32
ret
original:
.word {displaced}
{jump('resume')}
'''
 add('studio_heavy_shot_error_'+hex(address),address,code,{'flag':FLAG,'resume':address+4},{'accuracy_factor':floatbits(.8)})
# Disable the previously unreleased consumers of our transient/repurposed flags.
for name,address in [('unused_amazon',0x6eede10),('unused_mekong',0x70d3b50)]:add('studio_'+name,address,'mov w0,#0\nret\n')
for address in (0x6d6281c,0x6d6878c,0x6d688b4):add('studio_unused_indus_'+hex(address),address,'mov w0,#0\n'+jump('resume'),{'resume':address+4})
# Ignore the stunning-only condition for Low Screamer; retain its <50% gate.
add('studio_low_screamer_normal_shot',0x6d627c0,'mov w10,#0\n'+jump('resume'),{'resume':0x6d627c4})
info={'version':1,'source':'V17/V16.1 ARM64 checked match interfaces; fixed studio skill effects','hooks':hooks,'visible_skills':{'25':'重炮攻门','43':'长传好手','52':'健步如飞'},'acceleration_variants':{'explosive':51,'controlled':52,'lengthy':68},'defaults':{'shot_error_factor':.8,'power_threshold':.5,'lofted_windup_factor':.88,'explosive_max_height':175,'controlled_max_height':185,'native_speed_threshold':20}}
(root/'native-skill-effects.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
print('hooks',len(hooks),'bytes',sum(len(bytes.fromhex(h['body_hex'])) for h in hooks))
