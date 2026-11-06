"""Compose the reviewed promotion helper with the existing homepage channel."""
from pathlib import Path
import hashlib,json,struct
from maintenance.skill_hook_ir import save_all,restore_all


def append(builder):
    root=Path(__file__).resolve().parents[1]
    helper=json.loads((root/'resources/tournament_schedule_ui/native-promotion-helper.json').read_text('utf8'))
    from tournament_home import SCHEMA
    assert SCHEMA['promotion_offset']==131136 and SCHEMA['promotion_bytes']>=920
    raw=bytes.fromhex(helper['body_hex'])
    assert helper['entry_offset']==0 and hashlib.sha256(raw).hexdigest()==helper['body_sha256']
    assert hashlib.sha256((root/'maintenance/tournament_promotion_native.c').read_bytes()).hexdigest()==helper['source_sha256']
    code='\n'.join('.byte '+','.join(str(n)for n in raw[i:i+64])for i in range(0,len(raw),64))
    builder.helper('promotion_native',code)
    builder.helper('promotion_observe','''
    stp x29,x30,[sp,#-16]!
    mov x2,x0
    mov w3,w1
    bl shared_home_control
    add x1,x0,#0x20,lsl #12
    add x1,x1,#64
    mov w0,#1
    mov x4,xzr
    bl shared_promotion_native
    ldp x29,x30,[sp],#16
    ret
''')
    for name,address,action,replay in (
        ('tournament_promotion_menu_frame',0x3bf7d88,2,'sub sp,sp,#0x70'),
        ('tournament_promotion_confirm_button',0x3336440,3,'sub sp,sp,#0x50'),
        ('tournament_promotion_delete',0x3336518,4,'stp x29,x30,[sp,#-0x20]!'),
        ('tournament_promotion_destruct',0x33364bc,4,'stp x29,x30,[sp,#-0x20]!'),
        ('tournament_promotion_fadeout_finished',0x302e978,5,'stp x29,x30,[sp,#-0x20]!'),
        ('tournament_promotion_numbered_badges',0x333ffac,6,'sub sp,sp,#0x50')):
        arguments=('ldr x3,[sp,#8]\nldr x4,[sp,#16]\n'if action==6 else 'mov w3,wzr\nldr x4,[sp,#240]\n')
        code=save_all()+f'''
    bl shared_home_control
    add x1,x0,#0x20,lsl #12
    add x1,x1,#64
    mov w0,#{action}
    ldr x2,[sp]
'''+arguments+'bl shared_promotion_native\n'+restore_all()+replay+'\nldr x16,resume\nbr x16\n'
        assert bytes(builder.assembler.asm(replay)[0])==builder.engine[address-16384:address-16384+4]
        builder.add(name,address,code,{'resume':address+4})
    # The one original caller restores actor/default/new in x19/x20/x21.
    # Apply the mask again AFTER SetData, before returning to FadeIn setup.
    # No generic close or unrelated caller can enter the scoped adjustment.
    post=save_all()+'''
    ldr x9,[sp,#240]
    ldr x10,original_caller
    cmp x9,x10
    b.ne finished
    bl shared_home_control
    add x1,x0,#0x20,lsl #12
    add x1,x1,#64
    mov w0,#6
    ldr x2,[sp,#152]
    ldr x3,[sp,#160]
    ldr x4,[sp,#168]
    bl shared_promotion_native
finished:
'''+restore_all()+'ret\n'
    assert builder.engine[0x33401cc-16384:0x33401cc-16384+4]==bytes.fromhex('c0035fd6')
    builder.add('tournament_promotion_numbered_badges_post',0x33401cc,post,{'original_caller':0x333fd10})
    return helper


def finalize(hook,helper):
    start=hook['helper_entries']['shared_promotion_native'];body=bytes.fromhex(hook['body_hex'])
    raw=bytes.fromhex(helper['body_hex'])
    assert body[start:start+len(raw)]==raw
    for delta in range(0,helper['imports_bytes'],8):
        at=start+helper['imports_offset']+delta
        hook['absolute_fixups'].append([at,struct.unpack_from('<Q',body,at)[0]])
    hook['promotion_native']={'revision':'tournament-native-promotion-v1','helper_entry':start,
        'helper_bytes':len(raw),'source_sha256':helper['source_sha256'],'helper_body_sha256':helper['body_sha256'],
        'original_factory':0x333b1f0,'original_setup':0x33401d4,'button_caller':0x3bba220,
        'generic_menu_frame':0x3bf7d88,'state3_interactive_only':True,'changes_league_data':False,
        'numbered_badges_suppressed_before_binding':True,
        'numbered_badges_suppressed_after_binding':True,
        'device_validated':False}
