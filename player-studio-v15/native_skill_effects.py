"""Verified match-time effects; no permanent ability inflation."""
import copy,json
from pathlib import Path

VISIBLE={25:'重炮攻门',43:'长传好手',52:'健步如飞'}
DESCRIPTIONS={25:'凌空抽射或蓄力达到 50% 的射门，射门偏差降低 20%。',
              24:'普通射门与紫色射门均可触发；保留原生低于 50% 蓄力及其他动作条件。',
              43:'空中传球的动作前摇缩短 12%，地面传球不变。',
              52:'按身高采用爆发加速（≤175 cm）、掌控加速（176–185 cm）或漫长加速（≥186 cm）。'}
RESOURCE=Path(__file__).parent/'resources'

def compiled_skills(values,height):
    variant=51 if height<=175 else 52 if height<=185 else 68
    return [variant if skill==52 else skill for skill in values]

def visible_skills(values):
    return list(dict.fromkeys(52 if skill in (51,68) else skill for skill in values))

def required(definitions,catalog):
    skills=(24,25,43,51,52,68)
    indices=[int(catalog['PARAMETER_BY_SKILL'][str(skill)]) for skill in skills]
    return any(any(p['base_parameters'][index] for index in indices) or set(p['owned'].get('additional_skill_id',[]))&set(skills) for p in definitions)

def hooks(engine,resources=None):
    data=json.loads(((Path(resources) if resources else RESOURCE)/'native-skill-effects.json').read_text(encoding='utf8'))
    result=copy.deepcopy(data['hooks'])
    for hook in result:
        engine.seek(hook['file_offset'])
        if engine.read(64).hex()!=hook['expected_hex']:
            raise ValueError('此版本的比赛技能接口发生变化，未写入新增技能效果')
        hook.pop('assembly',None)
    return result

def text_groups(resources=None):
    path=(Path(resources) if resources else RESOURCE)/'skill-labels-zh.json'
    if not path.is_file():path=RESOURCE/'skill-labels-zh.json'
    data=json.loads(path.read_text(encoding='utf8'))
    result={}
    for row in data['rows']:
        skill=row['id']
        if skill not in (25,43,51,52,68):continue
        group=result.setdefault(row['group'],{'name':row['group_name'],'id':row['group'],'items':{}})
        group['items'][row['key']]=VISIBLE[52 if skill in (51,68) else skill]
    return list(result.values())

def skill_bits(resources):
    result=json.loads((Path(resources)/'native-skill-bits.json').read_text(encoding='utf8'))
    verified=json.loads((RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
    for skill in (14,25,43,51,52,63,68,70):
        if str(skill) not in result:result[str(skill)]=verified[str(skill)]
    return result
