"""Verified match-time effects; no permanent ability inflation."""
import copy,json
from pathlib import Path
from studio_resources import bundled_resources

VISIBLE={9:'施丹式转身',25:'重炮攻门',43:'长传好手',52:'健步如飞'}
DESCRIPTIONS={9:'带球时使用施丹式转身；动作由游戏原生操作触发。',
              25:'凌空抽射或蓄力达到 50% 的射门，水平和仰角随机瞄准偏差降低 50%。',
              24:'普通射门与紫色射门均可触发；保留原生低于 50% 蓄力及其他动作条件。',
              43:'长传、传中及挑传直塞的动作前摇缩短 40%，方向、仰角和球速随机扰动降低 40%；出球后恢复原速，理想球速保持原值。',
              52:'按身高采用更强的平滑加速曲线：爆发型（≤175 cm）偏低速起步，掌控型（176–185 cm）均衡，漫长型（≥186 cm）偏中高速追赶。'}
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
    return any('lone_wolf' in p.get('ai_playing_styles',[]) or p.get('studio_custom_skills') or any(p['base_parameters'][index] for index in indices) or set(p['owned'].get('additional_skill_id',[]))&set(skills) for p in definitions)

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
        for key in ('assembly','code','functions','constants','helper_entries','deferred_shared_refs','writable'):
            hook.pop(key,None)
    return result

def text_groups(resources=None,locale='zha'):
    # The native detail-screen table has separate name and description IDs.
    # Reserved slots must populate both, including each height variant.
    path=(Path(resources) if resources else RESOURCE)/'native-skill-ui.json'
    if not path.is_file():path=RESOURCE/'native-skill-ui.json'
    data=json.loads(path.read_text(encoding='utf8'))
    # Imported databases predate the Spring Cut text audit. Do not require a
    # database reimport just to repair this already verified native message.
    if not any(row['id']==9 for row in data['rows']):
        verified=json.loads((RESOURCE/'native-skill-ui.json').read_text(encoding='utf8'))
        data['rows'].extend(row for row in verified['rows'] if row['id']==9)
    chinese=locale in ('zha','chi')
    names={9:'Zidane Turn',25:'Power Strike',43:'Lofted Pass Specialist',52:'Quick Stride'}
    descriptions={9:'Performs a Zidane turn while dribbling using the native game controls.',
                  25:'Reduces horizontal and elevation random aiming error by 50% for volleys or shots with at least 50% power.',
                  24:'Increases the speed of eligible low-power shots below 50% power. Applies to normal and Stunning Shots; other native motion conditions still apply.',
                  43:'Reduces pre-contact wind-up and direction, elevation and speed random perturbations by 40% for lofted passes, crosses and lofted through passes. Restores the original playback rate after release; nominal ball speed is unchanged.',
                  52:'Uses stronger smooth acceleration curves: explosive low-speed starts up to 175 cm, balanced controlled acceleration from 176 to 185 cm, and lengthy mid/high-speed acceleration from 186 cm.'}
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
        result.setdefault(352,{'name':'E15W','id':352,'items':{}})['items'][60010]='独狼' if chinese else 'Lone Wolf'
        result.setdefault(353,{'name':'E18T','id':353,'items':{}})['items'][60010]=('优先寻找安全远射；与内切突破组合时优先内切寻找射位。' if chinese else 'Prioritises safe long shots and dribbles towards a shooting position. Combines with Incisive Run to prefer inward routes.')
    return list(result.values())

def skill_bits(resources):
    result=json.loads((Path(resources)/'native-skill-bits.json').read_text(encoding='utf8'))
    verified=json.loads((RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
    for skill in (9,14,25,31,43,51,52,63,68,70):
        if str(skill) not in result:result[str(skill)]=verified[str(skill)]
    # Older imported V17 databases contain two correlation-derived aliases.
    # The instruction audit resolves these to independent source flags.
    for skill in (9,31):result[str(skill)]=verified[str(skill)]
    from custom_skills import enabled,source_fields
    if enabled():result.update(source_fields())
    return result
