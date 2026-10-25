"""Verified match-time effects; no permanent ability inflation."""
import copy,json
from pathlib import Path
from studio_resources import bundled_resources

VISIBLE={25:'重炮攻门',43:'长传好手',52:'健步如飞'}
DESCRIPTIONS={25:'凌空抽射或蓄力达到 50% 的射门，射门偏差降低 20%。',
              24:'普通射门与紫色射门均可触发；保留原生低于 50% 蓄力及其他动作条件。',
              43:'空中传球的动作前摇缩短 12%，地面传球不变。',
              52:'按身高采用爆发加速（≤175 cm）、掌控加速（176–185 cm）或漫长加速（≥186 cm）。'}
RESOURCE=bundled_resources()

def compiled_skills(values,height):
    variant=51 if height<=175 else 52 if height<=185 else 68
    return [variant if skill==52 else skill for skill in values]

def visible_skills(values):
    return list(dict.fromkeys(52 if skill in (51,68) else skill for skill in values))


def decode_skills(value,parameters,catalog,fields):
    """Read client ownership without extending the native 147-item array."""
    selected=[]
    for ident,field in fields.items():
        if (value>>field['bit'])&1:
            selected.append(int(ident))
            index=int(catalog['PARAMETER_BY_SKILL'][str(ident)])
            if index<147:parameters[index]=1
    return selected

def required(definitions,catalog):
    skills=(24,25,43,51,52,68)
    indices=[int(catalog['PARAMETER_BY_SKILL'][str(skill)]) for skill in skills]
    return any(p.get('studio_custom_skills') or any(p['base_parameters'][index] for index in indices) or set(p['owned'].get('additional_skill_id',[]))&set(skills) for p in definitions)

def hooks(engine,resources=None):
    data=json.loads(((Path(resources) if resources else RESOURCE)/'native-skill-effects.json').read_text(encoding='utf8'))
    if data.get('production_ready') is False:
        raise ValueError('此技能适配仍在验证中，尚不能写入游戏 APK')
    result=copy.deepcopy(data.get('bundles') or data['hooks'])
    for hook in result:
        for entry in [hook]+list(hook.get('extra_entries',[])):
            engine.seek(entry['file_offset'])
            if engine.read(64).hex()!=entry['expected_hex']:
                raise ValueError('此版本的比赛技能接口发生变化，未写入新增技能效果')
        for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs'):
            hook.pop(key,None)
    return result

def text_groups(resources=None,locale='zha'):
    # The native detail-screen table has separate name and description IDs.
    # Reserved slots must populate both, including each height variant.
    path=(Path(resources) if resources else RESOURCE)/'native-skill-ui.json'
    if not path.is_file():path=RESOURCE/'native-skill-ui.json'
    data=json.loads(path.read_text(encoding='utf8'))
    chinese=locale in ('zha','chi')
    names={25:'Power Strike',43:'Lofted Pass Specialist',52:'Quick Stride'}
    descriptions={25:'Reduces shot error by 20% for volleys or shots with at least 50% power.',
                  24:'Increases the speed of eligible low-power shots below 50% power. Applies to normal and Stunning Shots; other native motion conditions still apply.',
                  43:'Reduces the wind-up for lofted passes by 12%. Ground passes are unchanged.',
                  52:'Uses explosive acceleration up to 175 cm, controlled acceleration from 176 to 185 cm, and lengthy acceleration from 186 cm.'}
    result={}
    for row in data['rows']:
        skill=52 if row['id'] in (51,68) else row['id']
        for kind in ('name','description'):
            if kind=='name' and skill==24:continue
            message=row[kind+'_msg'];gid=message>>16;key=message&65535
            group=result.setdefault(gid,{'name':row[kind+'_group'],'id':gid,'items':{}})
            group['items'][key]=(VISIBLE[skill] if chinese else names[skill]) if kind=='name' else (DESCRIPTIONS[skill] if chinese else descriptions[skill])
    from custom_skills import enabled,text_groups as custom_text_groups
    if enabled():
        for row in custom_text_groups(locale):
            result.setdefault(row['id'],{'name':row['name'],'id':row['id'],'items':{}})['items'].update(row['items'])
    return list(result.values())

def skill_bits(resources):
    result=json.loads((Path(resources)/'native-skill-bits.json').read_text(encoding='utf8'))
    verified=json.loads((RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
    for skill in (14,25,43,51,52,63,68,70):
        if str(skill) not in result:result[str(skill)]=verified[str(skill)]
    from custom_skills import enabled,source_fields
    if enabled():result.update(source_fields())
    return result
