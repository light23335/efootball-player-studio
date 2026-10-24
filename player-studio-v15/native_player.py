"""Compile editor designs into the inspected V14 147-parameter player layout.

No coach preview bonus is baked into a player's abilities. Editor training is
used only for a first grant; the Android importer preserves an existing owned
instance and its ledger when the same permanent package is imported again.
"""
import copy
import hashlib
import json
import uuid
from overall import calculate,maximum_development
from native_models import person_keys
from native_celebration import project_value
from ai_playing_styles import project_value as ai_styles,write_parameters as write_ai_styles
from player_identity_binding import normalize as original_binding,BOUND_AGENT_MIN


def training_cost(upgrades):
    return sum(1+i//4 for i in range(upgrades))


def experience_curve(costs, cap):
    values=list(costs)
    while len(values)<=cap:
        values.append(values[-1]+max(1,(values[-1]-values[-2])*105//100))
    return values[:cap+1]


def reserve_identity(project, occupied, registry):
    key=str(uuid.UUID(project['package_id']))
    bound=original_binding(project.get('identity') or {},project.get('source_player'))
    if key in registry:
        person=registry[key].get('independent_person_id',registry[key]['person_id'])
    else:
        # Dedicated person namespace; all original cards and their low-28-bit
        # person keys must be checked before reserving a number.
        start=90000000+int(hashlib.sha256(key.encode()).hexdigest()[:12],16)%9000000
        person=start
        reserved={int(k) for r in registry.values() for pid in {r['person_id'],r.get('independent_person_id',r['person_id'])} for k in person_keys(pid)}
        while set(map(int,person_keys(person)))&(occupied|reserved):
            person=90000000+(person-90000000+1)%9000000
            if person==start:raise ValueError('个人球员编号空间已用完')
        registry[key]={'person_id':person,'card_ids':[]}
    row=registry[key];row.setdefault('independent_person_id',person)
    if bound is not None:
        if bound not in occupied and not any(int(k) in occupied for k in person_keys(bound)):
            raise ValueError('绑定的原游戏球员 ID 不在当前 APK 数据库中')
        base=bound&0xfffffff
        if not base:raise ValueError('原游戏球员身份编号无效')
        person=base
        row.setdefault('bound_person_ids',[])
        if person not in row['bound_person_ids']:row['bound_person_ids'].append(person)
    row['person_id']=person
    row['bound_original_player_id']=bound
    card=project.get('native_card') or {}
    style=card.get('native_style')
    if not isinstance(style,str) or len(style)!=4 or not style.isdigit():
        raise ValueError('请先选择原版卡面预设或载入有原版卡面的球员')
    style_byte=int(style[:2])*16+int(style[2:])
    agent=int(card.get('native_agent',0))
    if not 0<=agent<=4095:raise ValueError('原版卡面系列编号超出 V14 范围')
    limited=bool((card.get('preset') or {}).get('limited'))
    if 'limited' not in (card.get('preset') or {}):
        limited=bool(int(card.get('source_id') or 0)&(1<<48))
    cid=(style_byte<<40)|(agent<<28)|person|((1<<48) if limited else 0)
    unavailable=occupied
    if bound is not None:
        unavailable=occupied|{int(cid) for uid,entry in registry.items() if uid!=key for cid in entry.get('card_ids',[])}
        previous=row.get('card_id')
        if previous is not None and previous not in unavailable and previous&0xfffffff==person and (previous>>40)&255==style_byte and bool(previous&(1<<48))==limited and (previous>>28)&4095>=BOUND_AGENT_MIN:
            cid=previous
        else:
            cid=next(((style_byte<<40)|(a<<28)|person|((1<<48) if limited else 0)
                      for a in range(4095,BOUND_AGENT_MIN-1,-1) if ((style_byte<<40)|(a<<28)|person|((1<<48) if limited else 0)) not in unavailable),None)
            if cid is None:raise ValueError('该原版球员当前卡种的独立绑定卡号已用完')
    if cid in unavailable:
        if bound is None:raise ValueError('个人球员卡号与原库冲突，未写入')
        # Keep the original person's low 24 bits while reserving a distinct
        # card variant. Native art is independently routed by the custom ID.
        cid=next(((style_byte<<40)|(a<<28)|person|((1<<48) if limited else 0)
                  for a in range(4095,-1,-1) if ((style_byte<<40)|(a<<28)|person|((1<<48) if limited else 0)) not in unavailable),None)
        if cid is None:raise ValueError('该原版球员的独立卡号已用完')
    if cid not in row['card_ids']:row['card_ids'].append(cid)
    row['card_id']=cid
    return {'package_id':key,'person_id':person,'card_id':cid,'previous_card_ids':list(row['card_ids']),
            'independent_person_id':row['independent_person_id'],'bound_original_player_id':bound,
            'bound_person_ids':list(row.get('bound_person_ids',[]))}


def compile_player(project,catalog,costs,identity,template,nation_id,team_id,source_record=None):
    p=copy.deepcopy(template)
    base=list(p.get('parameters') or [])
    if len(base)!=147:raise ValueError('实装模板不是已核对的 147 项参数布局')
    for index in catalog['ABILITIES']:
        value=project['base_abilities'][index]
        if type(value) is not int or not 40<=value<=103:
            raise ValueError(f"{catalog['ABILITIES'][index]}：V14 客户端基础能力可写范围为 40–103，请调整后导出")
        base[int(index)]=value
    profile=project['identity']
    base[0]=catalog['POSITIONS'].index(profile['position'])
    for index,position in enumerate(catalog['APTITUDES'],1):
        base[index]=int(project.get('position_aptitudes',{}).get(position,0))
    traits=project.get('traits',{})
    base[33]=['低','普通','高','极高'].index(traits.get('weak_foot_accuracy','普通'))
    base[41]=['不稳定','普通','稳定'].index(traits.get('form','普通'))
    base[42]=['低','普通','高'].index(traits.get('injury','普通'))
    base[43]=int(profile['preferred_foot']=='左脚')
    base[45]=['低','普通','高','极高'].index(traits.get('weak_foot_usage','普通'))
    base[46:49]=[profile['age'],profile['height_cm'],profile['weight_kg']]
    base[59]=project_value(project,template,source_record)
    selected_ai_styles=ai_styles(project,template,source_record)
    write_ai_styles(base,selected_ai_styles)
    for index in catalog['PARAMETER_BY_SKILL'].values():base[int(index)]=0
    from native_skill_effects import compiled_skills
    for skill in compiled_skills(project.get('innate_skills',[]),profile['height_cm']):base[int(catalog['PARAMETER_BY_SKILL'][str(skill)])]=1
    style=project.get('play_style') or {}
    base[61:63]=[int(style.get('attack',0)),int(style.get('defense',0))]
    base[144:147]=list(project['booster_ids'])+[0]
    trained=list(base)
    ledger={}
    for group in catalog['training_groups']:
        upgrades=int(project['training'].get(group['id'],0))
        if upgrades:
            ledger[group['id']]=training_cost(upgrades)
            for index in group['indices']:trained[index]=min(105,trained[index]+upgrades)
    level,cap=project['initial_level'],project['max_level']
    budget=2*(level-1) if project['card_type']!='Trending' else 0
    if sum(ledger.values())>budget:raise ValueError('当前培养方案超出此等级的可用点数，未写入')
    curve=experience_curve(costs,cap)
    cid=identity['card_id']
    p.update(gameplayer_id={'id':cid,'serial':1},parameters=trained,
             _careerplan_base_parameters=base,_personal_player_uuid=identity['package_id'],
             _personal_design_revision=hashlib.sha256((json.dumps(project,sort_keys=True,ensure_ascii=False,separators=(',',':'))+':v16-compiler-1.9.2').encode()).hexdigest(),
             name=profile['name'],name_en=profile['name'],player_name=project.get('display_name') or profile['name'],
             _nation_id=nation_id,initial_base_team_id=team_id,initial_base_national_team_id=0,
             uniform_number=profile['number'],play_style=base[61:63],
             ai_playing_styles=selected_ai_styles,
             initial_booster_id_list=base[144:147],additional_skill_id=compiled_skills(project.get('additional_skills',[]),profile['height_cm']),
             additional_position=[],games=0,goal=0,assist=0,is_lock='YES',type='NORMAL',
             default_rarity=int(project.get('appearance',{}).get('card_rarity',5))-1,
             level_info={'level':level,'level_limit':cap,'exp_total':sum(curve[:level+1]),
                         'exp_current_level':0,'exp_to_next_level':curve[level+1] if level<cap else 0,
                         'customize_point':budget-sum(ledger.values())})
    for key in list(p):
        if key.startswith(('_e16','_studio','_training_auto','_level_training','_editor_ability_caps')):p.pop(key,None)
    # Never inherit the template player's rating. The original preview module
    # otherwise treats Messi's rating as this custom player's native baseline.
    p['_overall']=calculate(project,catalog)['base']
    p.pop('overall',None);p.pop('default_overall',None)
    maximum=maximum_development(project,catalog)
    display_parameters=list(base)
    for i,n in maximum.pop('parameters').items():display_parameters[int(i)]=n
    maximum['parameters']=display_parameters
    return {'identity':identity,'owned':p,'base_parameters':base,'allocation':ledger,
            'card_art_source':{k:(project.get('native_card') or {}).get(k) for k in ('source_id','native_style','native_agent')},
            'weekly_condition':project.get('weekly_condition','auto'),
            'maximum_development':maximum,'card_type':project['card_type'],'card_series':project.get('card_series',project['card_type'])}
