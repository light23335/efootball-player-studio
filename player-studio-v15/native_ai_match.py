"""V17 match observer/command channel with explicit execution capability gates."""
import copy
import json
from studio_resources import bundled_resources

REVISION='v17-situational-coach-channel-v1'


def hooks(engine,resources=None):
    folder=bundled_resources() if resources is None else resources
    data=json.loads((folder/'native-ai-match-adapter.json').read_text(encoding='utf8'))
    if data.get('revision')!=REVISION or data.get('observer_ready') is not True:
        raise ValueError('AI 临场观察接口尚未通过核查')
    # The manifest contains reviewed observation capabilities, separately from
    # automatic execution. False proof fields intentionally remain false until
    # the actual native state/entry/window adapter and game tests are complete.
    if not isinstance(data.get('execution_proof'),dict):raise ValueError('AI 临场能力记录缺失')
    for entry in [data,*data.get('extra_entries',[]),*data.get('native_import_probes',[])]:
        engine.seek(entry['file_offset']);expected=bytes.fromhex(entry['expected_hex'])
        if engine.read(len(expected))!=expected:
            raise ValueError('此版本的 AI 临场接口不同，请关闭“AI 组别随机组队与临场战术”后再生成')
    result=copy.deepcopy(data)
    for name in ('native_import_probes','evidence'):result.pop(name,None)
    return [result]
