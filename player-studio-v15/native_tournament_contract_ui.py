"""Reject changed native interfaces before packaging chance-button labels."""
import copy,hashlib,json
from studio_resources import bundled_resources

def hooks(engine,resources=None):
    folder=bundled_resources() if resources is None else resources
    data=json.loads((folder/'tournament_schedule_ui/native-contract.json').read_text('utf8'))
    if data['revision']!='tournament-chance-ui-v2-zero-count-initialization':raise ValueError('锦标赛抽取界面版本不同')
    if not data['execution_proof']['independent_instruction_probe']:raise ValueError('锦标赛抽取按钮指令尚未核验')
    if hashlib.sha256(bytes.fromhex(data['body_hex'])).hexdigest()!=data['body_sha256']:
        raise ValueError('锦标赛抽取按钮模板摘要不同')
    for p in [data,*data.get('extra_entries',[]),*data['native_probes']]:
        engine.seek(p['file_offset']);expected=bytes.fromhex(p['expected_hex'])
        if engine.read(len(expected))!=expected:raise ValueError('锦标赛抽取按钮原生接口不同')
    out=copy.deepcopy(data)
    for key in ('assembly','code','functions','constants','writable','deferred_shared_refs','native_probes'):out.pop(key,None)
    return [out]
