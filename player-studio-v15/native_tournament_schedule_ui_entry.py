"""Version-checked build adapter for the actual CHALLENGE schedule button.

Only emits a hook descriptor. It never patches a running game or builds an APK.
"""
import copy
import hashlib
import json
import struct
from studio_resources import bundled_resources
from native_tournament_schedule_ui import CHANNEL_SCHEMA, REVISION

SCHEMA=CHANNEL_SCHEMA


def hooks(engine, event_ids, resources=None, menu_sha256=None):
    event_ids=sorted(set(event_ids))
    if not event_ids:return []
    if len(event_ids)>32 or any(type(v)is not int or not 190000000<=v<240000000 for v in event_ids):
        raise ValueError('赛程按钮只允许已编译的自定义赛事编号')
    folder=bundled_resources() if resources is None else resources
    data=json.loads((folder/'tournament_schedule_ui/native-entry.json').read_text('utf8'))
    if data.get('revision')!=REVISION or data.get('tournament_schedule_channel')!=SCHEMA:
        raise ValueError('赛程按钮适配协议改变')
    if not data.get('execution_proof',{}).get('independent_instruction_probe'):
        raise ValueError('赛程按钮原生指令尚未通过独立核验')
    if not data.get('execution_proof',{}).get('native_guard_counters'):
        raise ValueError('赛程按钮缺少原生门禁诊断')
    if not data.get('execution_proof',{}).get('decoded_callback_control_flow') or data.get('click_state')!={'required':3,'name':'SelectMenu','preserved':True,'timeout_alert_state':6,'timeout_alert_name':'WaitConfirmAlert'}:
        raise ValueError('赛程按钮正常分支与超时分支未区分')
    callback=(folder/'tournament_schedule_ui/native-entry-click-flow.json').read_bytes()
    if hashlib.sha256(callback).hexdigest()!=data.get('callback_flow_sha256') or json.loads(callback).get('blueprint_sha256')!=data.get('menu_source_sha256'):
        raise ValueError('赛程按钮分支证据与当前蓝图不一致')
    if menu_sha256!=data.get('menu_source_sha256'):
        raise ValueError('当前游戏源的赛程按钮Blueprint未核对或不同')
    for entry in [data,*data.get('native_probes',[])]:
        engine.seek(entry['file_offset']);expected=bytes.fromhex(entry['expected_hex'])
        if engine.read(len(expected))!=expected:
            raise ValueError('游戏版本的赛程按钮指令或反射布局不同：'+entry.get('name','entry'))
    body=bytearray.fromhex(data['body_hex']);at=data['event_ids_offset'];capacity=data['event_ids_capacity']
    if hashlib.sha256(body).hexdigest()!=data.get('body_sha256'):
        raise ValueError('赛程按钮指令模板未绑定独立核验结果')
    if capacity!=32 or at%4 or not 8<=at<=len(body)-capacity*4:
        raise ValueError('赛程事件表超出已核验范围')
    if body[at-8:at]!=struct.pack('<Q',0x5354434849445331) or any(body[at:at+capacity*4]):
        raise ValueError('赛程原生模板事件表不完整')
    for i,event in enumerate(event_ids):struct.pack_into('<I',body,at+i*4,event)
    result=copy.deepcopy(data);result['body_hex']=body.hex();result['event_ids']=event_ids
    for key in ('assembly','code','functions','constants','writable','deferred_shared_refs','native_probes'):
        result.pop(key,None)
    return [result]


def attach_descriptor(payload, hook, body_offset, writable_locations):
    """Call from compose() after its existing writable allocation loop."""
    from native_tournament_schedule_ui import attach_descriptor as attach
    return attach(payload,hook,body_offset,writable_locations)
