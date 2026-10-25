"""Generate the verified controller snapshot adapter, never the event tree."""
from pathlib import Path
import sys,json,struct,argparse
from keystone import Ks,KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN
p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--resources',required=True);a=p.parse_args()
raw=Path(a.engine).read_bytes();ks=Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
address=0x6772d0c
lines=['sub sp,sp,#448']
for n in range(0,18,2):lines.append(f'stp x{n},x{n+1},[sp,#{n*8}]')
lines+=['stp x18,x30,[sp,#144]','mrs x17,nzcv','str x17,[sp,#160]']
for n in range(0,8,2):lines.append(f'stp q{n},q{n+1},[sp,#{176+n*16}]')
# Read the game's cached control mode for THIS physical port. No game calls,
# no locks, no allocation and no writes to the match or user objects here.
# Native classification: 6fad3e4 (0x5e) = kick/attack modes; 6fad400
# (0x1a0) = defence modes. Other states retain stock menu controls.
lines += ['mov w18,wzr','ldr x10,world_root','ldr x10,[x10]','cbz x10,context_done',
          'ldr x11,[x10,#0x340]','cbz x11,context_done','ldr w12,[x10,#0x54]',
          'cmp w12,#2','b.hi context_done','mov w13,#0x50','umaddl x12,w12,w13,x10',
          'ldr x12,[x12,#0x70]','cbz x12,context_done','ldr x14,[x12,#0x180]',
          'cbz x14,context_done','add x14,x14,#0x2b,lsl #12','add x14,x14,#0x4ec',
          'ldr w15,[sp,#64]','cmp w15,#3','b.hi context_done','mov w16,wzr',
          'context_loop:','ldr w12,[x11,#8]','cmp w12,w15','b.ne context_next',
          'ldr w12,[x11,#4]','tbz w12,#4,context_next','ldr w17,[x14]',
          'cmp w17,#8','b.hi context_done','mov w12,#0x5e','lsr w12,w12,w17',
          'tbnz w12,#0,context_attack','mov w12,#0x1a0','lsr w12,w12,w17',
          'tbz w12,#0,context_done','mov w18,#2','b context_done',
          'context_attack:','mov w18,#1','b context_done','context_next:',
          'add x11,x11,#0xd0','add x14,x14,#0x2c','add w16,w16,#1',
          'cmp w16,#24','b.lo context_loop','context_done:','str w18,[sp,#304]',
          'mov w9,wzr']
offsets=[0x20,0x21,0x22,0x23,0x24,0x27,0x25,0x28,0x26,0x29,0x2f,0x2e,0x2a,0x2b,0x2c,0x2d]
for bit,off in enumerate(offsets):lines += [f'ldrb w10,[x28,#{off}]','cmp w10,#0','cset w10,ne',f'orr w9,w9,w10,lsl #{bit}']
for bit,off in [(6,0x4c),(7,0x50)]:
    lines += [f'ldr s0,[x28,#{off}]','ldr s1,threshold','fcmp s0,s1','cset w10,ge',f'orr w9,w9,w10,lsl #{bit}']
for bit,off,neg in [(12,0x58,True),(13,0x58,False),(14,0x54,True),(15,0x54,False)]:
    lines += [f'ldr s0,[x28,#{off}]']+(['fneg s0,s0'] if neg else [])+['ldr s1,threshold','fcmp s0,s1','cset w10,ge',f'orr w9,w9,w10,lsl #{bit}']
lines += ['ldr w18,[sp,#304]','adr x10,axis_sources','add x10,x10,x18,lsl #3','ldp w16,w17,[x10]',
          'adr x10,table_menu','mov w15,#768','madd x10,x18,x15,x10',
          'mov w11,wzr','mov w12,wzr','loop:','ldp w13,w14,[x10],#16','cbz w13,mapped','and w15,w9,w13','cmp w15,w13','b.ne loop','tst w12,w13','b.ne loop','orr w11,w11,w14','orr w12,w12,w13','ldur w15,[x10,#-8]','tst w14,#64','csel w16,w15,w16,ne','ldur w15,[x10,#-4]','tst w14,#128','csel w17,w15,w17,ne','b loop','mapped:']
for bit,source in ((6,16),(7,17)):
    lines += [f'tbnz w11,#{bit},keep_axis_{bit}',f'cbz w{source},keep_axis_{bit}',f'cmp w{source},#1','mov w15,#64','mov w18,#128','csel w15,w15,w18,eq','tst w12,w15',f'csel w{source},wzr,w{source},ne',f'keep_axis_{bit}:']
for bit,off in enumerate(offsets):lines += [f'ubfx w10,w11,#{bit},#1',f'strb w10,[x28,#{off}]']
lines += ['ldr s2,[x28,#0x4c]','ldr s3,[x28,#0x50]']
for bit,off,source in [(6,0x4c,16),(7,0x50,17)]:
    lines += [f'ubfx w10,w11,#{bit},#1','ucvtf s0,w10',f'cmp w{source},#1',f'b.ne trigger_right_{bit}','fmov s1,s2',f'b trigger_pressure_{bit}',f'trigger_right_{bit}:',f'cmp w{source},#2',f'b.ne trigger_store_{bit}','fmov s1,s3',f'trigger_pressure_{bit}:','fcmp s1,#0.0','fcsel s0,s1,s0,gt',f'trigger_store_{bit}:',f'str s0,[x28,#{off}]']
for low,high,off in [(14,15,0x54),(12,13,0x58)]:
    lines += [f'ubfx w10,w11,#{high},#1',f'ubfx w13,w11,#{low},#1','sub w10,w10,w13','scvtf s0,w10',f'str s0,[x28,#{off}]']
lines+=['ldr w18,[sp,#304]','cbz w18,restore','adr x10,options','ldr w11,[x10]','cbz w11,no_swap','ldr d0,[x28,#0x3c]','ldr d1,[x28,#0x44]','str d1,[x28,#0x3c]','str d0,[x28,#0x44]','no_swap:','ldr w11,[x10,#4]','cbz w11,restore','ldr s0,[x28,#0x48]','fneg s0,s0','str s0,[x28,#0x48]','restore:']
for n in range(0,8,2):lines.append(f'ldp q{n},q{n+1},[sp,#{176+n*16}]')
lines+=['ldr x17,[sp,#160]','msr nzcv,x17']
for n in range(0,18,2):lines.append(f'ldp x{n},x{n+1},[sp,#{n*8}]')
lines+=['ldp x18,x30,[sp,#144]','add sp,sp,#448','ldrb w9,[x28,#0x38]','nop','umaddl x8,w8,w27,x23','ldr s0,[x28,#0x20]','ldr x16,resume','br x16','.align 3',f'resume: .quad {address+16}',
        'world_root: .quad 0xa58de28','threshold: .word 0x3e99999a','options: .word 0x75a13842,0x6531a65b',
        'axis_sources: .quad 0x13ba68275f0348ca,0,0','.align 3','table_menu: .quad 0x63edc7261a09e0b5']
asm='\n'.join(lines);body=bytearray(ks.asm(asm)[0]);resume=body.index(struct.pack('<Q',address+16));world=body.index(struct.pack('<Q',0xa58de28));options=body.index(struct.pack('<II',0x75a13842,0x6531a65b));axes=body.index(struct.pack('<Q',0x13ba68275f0348ca));table=body.index(struct.pack('<Q',0x63edc7261a09e0b5));body[options:options+8]=bytes(8);body[axes:axes+24]=bytes(24);body[table:]=bytes(768*3)
probes=[]
for name,at,size in [('world_root',0x698f7e0,16),('users',0x698f7f0,8),('user_stride',0x698fc74,24),('user_port',0x698fc6c,8),('match_handler',0x72d8e20,44),('command_state',0x6b01d24,96),('mode_stride',0x6fa5640,48),('attack_modes',0x6fad3e4,28),('defence_modes',0x6fad400,28)]:
    probes.append({'name':name,'address':at,'file_offset':at-16384,'expected_hex':raw[at-16384:at-16384+size].hex()})
data={'format':'native-controller-context-v3','proof':'Only the cloned per-device snapshot is written. Bank selection reads the same per-user cached control modes as 0x6fa5a70: attack mask 0x5e, defence mask 0x1a0; absent/non-match modes use stock menu controls. Port is matched to a valid user, not assumed to be team 0.','digital_offsets':offsets,'trigger_axes':[0x4c,0x50],'hat_axes':[0x54,0x58],
      'table_offsets':{'menu':table,'attack':table+768,'defense':table+1536},'table_capacity':768,'axis_sources_offset':axes,'options_offset':options,'context_probes':probes,
      'hook':{'name':'studio_connected_controller_mapping','address':address,'file_offset':address-16384,'expected_hex':raw[address-16384:address-16384+64].hex(),'body_hex':body.hex(),'absolute_fixups':[[resume,address+16],[world,0xa58de28]],'assembly':asm}}
key_address=0x677277c
key_asm='''sub w8,w21,#19
cmp w8,#3
b.hi stock
add x8,x20,x8
cmp w0,#1
cset w9,ne
strb w9,[x8,#0x2a]
ldr x16,tail
br x16
stock:
sub w9,w21,#96
cmp w9,#13
b.ls valid
ldr x16,tail
br x16
valid:
ldr x10,page
ldr x16,next
br x16
.align 3
tail: .quad 0x677290c
page: .quad 0xc77000
next: .quad 0x677278c
'''
key_body=bytes(ks.asm(key_asm)[0]);fixes=[[key_body.index(struct.pack('<Q',v)),v] for v in (0x677290c,0xc77000,0x677278c)]
data['key_hook']={'name':'studio_controller_dpad_key_events','address':key_address,'file_offset':key_address-16384,'expected_hex':raw[key_address-16384:key_address-16384+64].hex(),'body_hex':key_body.hex(),'absolute_fixups':fixes,'assembly':key_asm}
Path(a.resources,'native-controller.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print('controller snapshot adapter:',len(body),'bytes')
