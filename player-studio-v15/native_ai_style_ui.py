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


def preflight(definitions,bundles):
    """Fail at export rather than silently emit a missing AI-style UI chain."""
    from ai_playing_styles import definition_value
    players=[p for p in definitions if 'lone_wolf' in definition_value(p)]
    if not players:return {'lone_wolf_players':0}
    entries={r.get('name') for b in bundles for r in [b]+b.get('extra_entries',[])}
    expected={'studio_custom_skill_decode','studio_custom_skill_get_parameter',
              'studio_custom_skill_name_message','studio_lone_wolf_ai_parameter',
              'studio_lone_wolf_owned_ai_list','studio_lone_wolf_library_ai_list',
              'studio_lone_wolf_ai_display_counts','studio_lone_wolf_library_ai_count'}
    missing=expected-entries
    if missing:raise ValueError('独狼 AI 风格显示适配缺少入口：'+', '.join(sorted(missing)))
    return {'lone_wolf_players':len(players),'source_bit':687,'virtual_parameter':151,
            'native_styles_preserved':7,'owned_and_library_lists':True,'display_counts':True,
            'name_message':(352<<16)|60010,'revision':'lone-wolf-display-v2'}
