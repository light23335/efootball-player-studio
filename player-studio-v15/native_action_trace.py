"""Version-checked observation-only native V17 player action hooks."""
import copy,json
from studio_resources import bundled_resources
from action_trace import SCHEMA

REVISION='v17-player-actions-v4-dribbling-and-shot-modes'

def hooks(engine,ai_enabled=False):
    data=json.loads((bundled_resources()/'native-action-trace.json').read_text('utf8'))
    if data.get('revision')!=REVISION or data.get('production_ready')is not True or data.get('schema')!=SCHEMA:
        raise ValueError('比赛动作观察接口尚未通过检查')
    result=copy.deepcopy(data['ai_bundles']if ai_enabled else data['bundles'])
    for row in result:
        for entry in [row,*row.get('extra_entries',[])]:
            engine.seek(entry['file_offset']);expected=bytes.fromhex(entry['expected_hex'])
            if engine.read(len(expected))!=expected:raise ValueError('此游戏的动作观察入口不同，请关闭动作日志后导出')
        for key in ('assembly','code','functions','constants','deferred_shared_refs','writable','evidence'):row.pop(key,None)
    return result
