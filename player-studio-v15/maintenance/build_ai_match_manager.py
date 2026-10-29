"""Compile the reviewed freestanding match adapter into a relocatable hook.

Maintenance only. End-user PC/Android builds ship the resulting JSON and never
need a C compiler. Every external pointer is listed for the existing binder.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile
from keystone import Ks,KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from skill_hook_ir import save_all,restore_all,FRAME

ROOT=Path(__file__).resolve().parents[1]
SCHEMA_NAMES=(
    'bus_bytes_used','snapshot_bytes','command_bytes','live_player_bytes','placement_bytes',
    'configuration_sequence','enabled','auto_execute','heartbeat','epoch','game_id','expected','snapshot','command',
    'ack_id','ack_status','rejection_reason',
    'snapshot.sequence','snapshot.configuration_sequence','snapshot.epoch','snapshot.game_id',
    'snapshot.team','snapshot.phase','snapshot.period','snapshot.stop_reason','snapshot.clock_frames',
    'snapshot.score_for','snapshot.score_against','snapshot.substitutions_left','snapshot.windows_left',
    'snapshot.native_pending','snapshot.roster_count','snapshot.native_event','snapshot.post_event','snapshot.live','snapshot.raw_plan',
    'command.sequence','command.checksum','command.epoch','command.game_id','command.plan_id','command.kind',
    'command.based_on_snapshot','command.active_count','command.score_for','command.score_against',
    'command.substitutions_left','command.windows_left','command.attack_level','command.placement_count','command.sub_count',
    'command.issued_clock_frames','command.incoming','command.outgoing','command.placement',
    'command.captain','command.set_piece','command.overlap',
    'diagnostic_enabled','diagnostic','diagnostic_bytes',
    'snapshot.yellow_count','snapshot.direct_red','snapshot.injury_state','snapshot.current_attack_level')


def build(compiler,engine,work):
    compiler=compiler.resolve();engine=engine.resolve();work=work.resolve()
    work.mkdir(parents=True,exist_ok=True)
    script=work/'adapter.ld'
    script.write_text('SECTIONS { . = 0; .text : { KEEP(*(.text*)) *(.rodata*) *(.data*) *(.got*) } '
                      '/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) } }',encoding='ascii')
    output=work/'adapter.elf';source=ROOT/'maintenance/ai_match_native.c'
    subprocess.run([str(compiler),'cc','-target','aarch64-freestanding','-O2','-ffreestanding',
                    '-fno-stack-protector','-fno-builtin','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
                    '-fno-jump-tables','-mcmodel=tiny','-fPIC','-nostdlib','-Wl,-T,'+str(script),
                    '-Wl,--entry=studio_observe','-Wl,-Bsymbolic',str(source),'-o',str(output)],check=True)
    elf=ELFFile(io.BytesIO(output.read_bytes()));section=elf.get_section_by_name('.text')
    if section['sh_addr']!=0:raise ValueError('Nonzero adapter image origin')
    symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
    body=bytearray(section.data());fixups=[]
    disassembler=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
    for symbol in symbols.values():
        if symbol['st_info']['type']=='STT_FUNC' and symbol['st_size']:
            at=symbol['st_value'];end=at+symbol['st_size']
            if any(i.mnemonic=='adrp' for i in disassembler.disasm(bytes(body[at:end]),at)):
                raise ValueError('Page-relative code cannot be moved to an unaligned native extension')
    imports=symbols['imports'];start=imports['st_value']
    for offset in range(start,start+imports['st_size'],8):
        address=struct.unpack_from('<Q',body,offset)[0]
        if not 0x6800000<address<0x9000000:raise ValueError('Unexpected native import')
        fixups.append([offset,address])
    bus_at=symbols['bus_pointer']['st_value']
    if struct.unpack_from('<Q',body,bus_at)[0]!=0x5354ee0000000000:raise ValueError('Missing channel pointer')
    layout=symbols['channel_layout'];values=struct.unpack_from('<'+'I'*len(SCHEMA_NAMES),body,layout['st_value'])
    if layout['st_size']!=4*len(SCHEMA_NAMES):raise ValueError('Channel schema mismatch')
    assembler=Ks(KS_ARCH_ARM64,KS_MODE_LITTLE_ENDIAN)
    entry=len(body);entry=(entry+15)&~15;body.extend(b'\0'*(entry-len(body)))
    observe=symbols['studio_observe']['st_value']
    # Keep original self/event and caller LR on an extra aligned frame. Observe
    # before and after the original event. The original first instruction has
    # no PC-relative operand, so its replay remains exact.
    origin=0x6ce3198;continuation=origin+4
    asm='stp x30,x0,[sp,#-32]!\nstr x1,[sp,#16]\n'+save_all()
    asm+='mov w2,#0\nbl '+str(observe)+'\n'+restore_all()
    asm+='adr x30,post_event\nsub sp,sp,#0xa0\nldr x16,original_next\nbr x16\n'
    asm+='post_event:\n'+save_all()+f'ldr x0,[sp,#{FRAME+8}]\nldr x1,[sp,#{FRAME+16}]\nmov w2,#1\nbl '+str(observe)+'\n'
    asm+=f'ldr x0,[sp,#{FRAME+8}]\nbl '+str(symbols['studio_queue_tick']['st_value'])+'\n'
    asm+=restore_all()+'ldp x30,x16,[sp],#32\nret\n.align 3\noriginal_next: .quad '+str(continuation)
    wrapper=bytes(assembler.asm(asm,addr=entry)[0]);at=wrapper.find(struct.pack('<Q',continuation))
    if at<0 or wrapper.find(struct.pack('<Q',continuation),at+1)>=0:raise ValueError('Ambiguous native continuation')
    fixups.append([entry+at,continuation]);body.extend(wrapper)
    raw=engine.read_bytes();extra=[]
    # All three adapters preserve the full incoming state when falling back,
    # replay exactly the verified first instruction and resume the original.
    for name,address,helper,replay in (
        ('studio_cpu_normal_sub_guard',0x6ce4b78,'studio_managed','sub sp,sp,#0x150'),
        ('studio_cpu_plan_commit',0x6c4ce44,'studio_plan_tick','stp x29,x30,[sp,#-0x60]!'),
        ('studio_cpu_attack_level',0x6c49a04,'studio_attack_tick','sub sp,sp,#0x80')):
        start=(len(body)+15)&~15;body.extend(bytes(start-len(body)))
        guard=name.endswith('guard')
        code=save_all()+'bl '+str(symbols[helper]['st_value'])+'\n'
        code+=('cbz w0,fallback\nmov w0,#0\n' if guard else 'tbnz w0,#31,fallback\n')
        code+='str x0,[sp]\n'+restore_all()+'ret\nfallback:\n'+restore_all()+replay+'\nldr x16,original_next\nbr x16\n.align 3\noriginal_next: .quad '+str(address+4)
        fragment=bytes(assembler.asm(code,addr=start)[0]);literal=fragment.find(struct.pack('<Q',address+4))
        if literal<0 or fragment.find(struct.pack('<Q',address+4),literal+1)>=0:raise ValueError('Ambiguous callback continuation')
        expected=bytes(assembler.asm(replay)[0])
        if raw[address-16384:address-16384+4]!=expected:raise ValueError('Native callback prologue differs')
        fixups.append([start+literal,address+4]);body.extend(fragment)
        extra.append({'name':name,'address':address,'file_offset':address-16384,'entry_offset':start,
                      'expected_hex':raw[address-16384:address-16384+64].hex()})
    bundle={'name':'situational_cpu_match_adapter','address':origin,'file_offset':origin-16384,
            'revision':'v17-situational-coach-channel-v1','observer_ready':True,
            'expected_hex':raw[origin-16384:origin-16384+64].hex(),
            'entry_offset':entry,'body_hex':body.hex(),'absolute_fixups':fixups,
            'writable_fixups':[[bus_at,32768]],'extra_entries':extra,
            'helper_entries':{name:symbols[name]['st_value'] for name in ('studio_observe','studio_queue_tick','studio_fence','studio_managed','studio_plan_tick','studio_attack_tick')},
            'channel_schema':dict(zip(SCHEMA_NAMES,values)),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'implementation_phase':'read-only-runtime-bridge-await-state-and-live-validation','automatic_execution_verified':False,
            'execution_proof':dict.fromkeys(('automatic_execution_verified','state_decoder_verified','entry_binding_verified',
                                            'legal_windows_verified','emergency_reconciliation_verified'),False),
            'native_import_probes':[{'address':address,'file_offset':address-16384,
                                      'expected_hex':raw[address-16384:address-16384+64].hex()}
                                    for address in sorted({target for _,target in fixups})],
            'evidence':['V17 complete 23 card/serial scope and CPU-only native test',
                        'Original integer stamina ratio ABI W0 and native frame clock S0',
                        'Original CPU event flow preserved before/after snapshot capture']}
    return bundle


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',required=True,type=Path)
    parser.add_argument('--engine',required=True,type=Path);parser.add_argument('--work',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    result=build(args.compiler,args.engine,args.work)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'bytes':len(bytes.fromhex(result['body_hex'])),'phase':result['implementation_phase'],
                      'channel':result['channel_schema']},ensure_ascii=False))
