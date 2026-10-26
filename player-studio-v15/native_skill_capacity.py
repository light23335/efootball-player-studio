"""Version-checked V17 20 innate / 10 additional native display support."""
import copy
import json
from studio_resources import bundled_resources
REVISION='v17-owned-skills-20-10-v2-widgets'


def hooks(engine):
    data=json.loads((bundled_resources()/'native-skill-capacity.json').read_text(encoding='utf8'))
    if not data.get('production_ready') or data.get('revision')!=REVISION:
        raise ValueError('20 项天生 / 10 项追加技能接口尚未完成验证')
    result=copy.deepcopy(data['bundles'])
    for bundle in result:
        for entry in [bundle]+bundle.get('extra_entries',[]):
            engine.seek(entry['file_offset'])
            if engine.read(64).hex()!=entry['expected_hex']:
                raise ValueError('此版本的追加技能读取或显示接口发生变化，未写入扩展')
        for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs','writable','evidence'):
            bundle.pop(key,None)
    return result
