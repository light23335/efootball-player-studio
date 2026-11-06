"""Build-time validation of the native tournament homepage adapter."""
import copy,hashlib,json
from studio_resources import bundled_resources
from tournament_home import REVISION,SCHEMA


def hooks(engine,resources=None,menu_sha256=None):
    folder=bundled_resources()if resources is None else resources
    data=json.loads((folder/'tournament_schedule_ui/native-home.json').read_text('utf8'))
    if data['revision']!=REVISION or data['tournament_home_channel']!=SCHEMA:raise ValueError('锦标赛主页协议不同')
    if data.get('special_plan_team_identity',{}).get('rental_field_encoding')!='native-team-id-shift-left-14':
        raise ValueError('锦标赛租借球队身份未按原生编码核验')
    membership=data.get('special_plan_roster_membership',{})
    if membership.get('policy_offset')!=SCHEMA['membership_offset']or not membership.get('requires_event_special_team_match'):
        raise ValueError('锦标赛原生球员候选归属未核验')
    if not data['execution_proof']['independent_instruction_probe']:raise ValueError('锦标赛主页原生指令尚未核验')
    if menu_sha256!=data['menu_source_sha256']:raise ValueError('锦标赛主页蓝图不同，未应用控件修改')
    raw=bytes.fromhex(data['body_hex'])
    if hashlib.sha256(raw).hexdigest()!=data['body_sha256']:raise ValueError('锦标赛主页模板摘要不同')
    for probe in [data,*data.get('extra_entries',[]),*data['native_probes']]:
        engine.seek(probe['file_offset']);expected=bytes.fromhex(probe['expected_hex'])
        if engine.read(len(expected))!=expected:raise ValueError('锦标赛主页原生接口不同：'+probe.get('name','entry'))
    out=copy.deepcopy(data)
    for k in ('assembly','code','functions','constants','writable','deferred_shared_refs','native_probes'):out.pop(k,None)
    return [out]
