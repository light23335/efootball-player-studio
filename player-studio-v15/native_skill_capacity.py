"""Version-checked V17 100 innate / 100 additional native display support."""
import copy
import json
from studio_resources import bundled_resources
REVISION='v17-owned-skills-100-100-v3-widgets'


def hooks(engine):
    data=json.loads((bundled_resources()/'native-skill-capacity.json').read_text(encoding='utf8'))
    if not data.get('production_ready') or data.get('revision')!=REVISION:
        raise ValueError('100 项天生 / 100 项追加技能接口尚未完成验证')
    result=copy.deepcopy(data['bundles'])
    for bundle in result:
        for entry in [bundle]+bundle.get('extra_entries',[]):
            engine.seek(entry['file_offset'])
            if engine.read(64).hex()!=entry['expected_hex']:
                raise ValueError('此版本的追加技能读取或显示接口发生变化，未写入扩展')
        for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs','writable','evidence'):
            bundle.pop(key,None)
    return result
