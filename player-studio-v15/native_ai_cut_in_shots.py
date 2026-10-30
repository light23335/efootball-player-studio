"""Local experimental V17 AI cut-in/curled-shot preference bundle."""
import copy
import json
import struct
from studio_resources import bundled_resources

REVISION='v17-ai-cut-in-opportunity-v7-203-selection-fixed-shot-modes'


def hooks(engine,ordinary_enabled=True):
    data=json.loads((bundled_resources()/'native-ai-cut-in-shots.json').read_text(encoding='utf8'))
    if data.get('revision')!=REVISION or not data.get('production_ready'):
        raise ValueError('AI 内切远射试验接口尚未通过检查')
    result=copy.deepcopy(data['bundles'])
    body=bytearray.fromhex(result[0]['body_hex']);offset=data['ordinary_switch_offset']
    if struct.unpack_from('<I',body,offset)[0]!=0x58414931:raise ValueError('AI 机会比较配置接口无效')
    struct.pack_into('<I',body,offset,int(bool(ordinary_enabled)))
    result[0]['body_hex']=body.hex()
    entries=[entry for bundle in result for entry in [bundle]+bundle.get('extra_entries',[])]+data['probes']
    for entry in entries:
        engine.seek(entry['file_offset']);expected=bytes.fromhex(entry['expected_hex'])
        if engine.read(len(expected))!=expected:
            raise ValueError('此版本的 AI 内切或弧线射门接口不同，请关闭 AI 内切远射试验后再生成')
    for bundle in result:
        for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs','writable','evidence'):
            bundle.pop(key,None)
    return result
