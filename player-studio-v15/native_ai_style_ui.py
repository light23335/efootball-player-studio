"""Verified V17 display-count repair for the independent Lone Wolf AI style."""
import copy

BUNDLES=[{'name': 'studio_lone_wolf_ai_display_counts',
  'body_hex': 'a016951ae83f40b90b6d1c126b7918120c6289526c6aaa727f010c6b081d075308019f1a0000080b9002005800021fd6a016951a683640b90b6d1c126b7918120c6289526c6aaa727f010c6b081d075308019f1a0000080b5001005800021fd6324d4f494455545300000000000000003000000000000000d4b837070000000030e0f30200000000',
  'absolute_fixups': [[120, 121092308], [128, 49537072]],
  'writable_fixups': [],
  'address': 121092304,
  'file_offset': 121075920,
  'expected_hex': 'a016951a3f010aebc1000054ff830791f44f42a9fc5741a9fd7bc3a8c0035fd6c4806294ff0301d1fd7b02a9f44f03a9fd83009154d03bd500c00091881640f9',
  'entry_offset': 0,
  'extra_entries': [{'name': 'studio_lone_wolf_library_ai_count',
                     'address': 49537068,
                     'file_offset': 49520684,
                     'expected_hex': 'a016951a3f010aebc1000054f44f43a9fd7b41a9f51340f9ff030191c0035fd6ed767395ff8306d1fd7b15a9fc6716a9f85f17a9f65718a9f44f19a9fd430591',
                     'entry_offset': 48}]}]

def hooks(engine):
    for bundle in BUNDLES:
        for entry in [bundle]+bundle.get('extra_entries',[]):
            engine.seek(entry['file_offset'])
            if engine.read(64).hex()!=entry['expected_hex']:
                raise ValueError('此版本的 AI 比赛风格显示接口改变，未写入独狼显示修复')
    return copy.deepcopy(BUNDLES)
