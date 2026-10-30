"""Independent skill IDs, without reusing active native skills or save fields.

The audited V17 Player.bin leaves bits 683..703 zero. The extended native
decoder carries four of those bits in the compact parameter record's alignment
padding, tagged so uninitialised padding never counts as skill ownership.
The ordinary owned-player parameter list remains exactly 147 items.
"""
import json
from pathlib import Path

REVISION = 'studio-custom-skills-v2-2'
FIRST_ID = 74
FIRST_NATIVE_ID = 75  # Native 74 is the empty additional-skill sentinel.
FIRST_PARAMETER = 147
SOURCE_BIT = 683
COMPACT_OFFSET = 0x34
COMPACT_TAG = 0x53534B10
FIRST_MATCH_FLAG = 75
COUNT = 4
ROWS = (
    {'id': 74, 'name': '冷血终结', 'english': 'Cold-Blooded Finisher',
     'description': '在对方禁区内射门且最近对手距离不超过 2.5 米时，水平和仰角随机瞄准偏差降低 50%。球速不变。'},
    {'id': 75, 'name': '手术刀直塞', 'english': 'Surgical Through Pass',
     'description': '地面与挑传直塞的水平随机方向偏差降低 40%；已控球、接近静止且触球位置就绪时前摇缩短 40%，出球后恢复原速。跑动、接球及不安全衔接保留原生时序。'},
    {'id': 76, 'name': '从容不迫', 'english': 'Composed Distributor',
     'description': '在对手距离不超过 2 米时开始短传，本次短传的方向、仰角和球速随机扰动降低 40%；已控球、接近静止且触球位置就绪时前摇缩短 40%，不安全衔接保留原生时序。'},
    {'id': 77, 'name': '钢铁支点', 'english': 'Iron Target Man',
     'description': '实际背身护球时，同一身后对手距离不超过 1.8 米，护球对抗抗性提高 50%。'},
)


def enabled(resources=None):
    """Only a released matching runtime may expose these IDs in the editor."""
    if resources is None:
        from studio_resources import bundled_resources
        resources=bundled_resources()
    path=Path(resources)/'native-skill-effects.json'
    if not path.is_file():return False
    data=json.loads(path.read_text(encoding='utf8'))
    return data.get('production_ready') is True and data.get('custom_skill_protocol')==REVISION


def extend_catalog(catalog):
    """Keep the 147 native owned parameters separate from virtual skill IDs."""
    names=list(catalog['SKILL_NAMES'])
    parameters={str(k):v for k,v in catalog['PARAMETER_BY_SKILL'].items()}
    labels={str(k):v for k,v in catalog['SKILL_LABELS'].items()}
    descriptions={str(k):v for k,v in catalog.get('SKILL_DESCRIPTIONS',{}).items()}
    aliases={str(k):list(v) for k,v in catalog.get('SKILL_ALIASES',{}).items()}
    codes=('STUDIO_COLD_FINISHER','STUDIO_SURGICAL_THROUGH_PASS',
           'STUDIO_COMPOSED_DISTRIBUTOR','STUDIO_IRON_TARGET_MAN')
    for row,code in zip(ROWS,codes):
        ident=row['id'];key=str(ident)
        if ident>len(names):raise ValueError('技能目录缺少原生编号，未插入扩展技能')
        if ident==len(names):names.append(code)
        elif names[ident]!=code:
            # The editor catalogue has an unmapped STEAMROLLER placeholder at
            # 74. Original V17 0x82a2220 / 0x82bb678 accept only IDs 0..73.
            # It has no editor parameter or selectable label, so no existing
            # player/project ownership is reassigned by filling this slot.
            placeholder=(ident==74 and names[ident]=='STEAMROLLER' and
                         key not in parameters and not labels.get(key))
            if not placeholder:raise ValueError('扩展技能编号已被其他技能使用')
            names[ident]=code
        parameters[key]=parameter(ident)
        labels[key]=row['name'];descriptions[key]=row['description']
        aliases[key]=list(dict.fromkeys([*aliases.get(key,()),row['english']]))
    catalog.update(SKILL_NAMES=names,PARAMETER_BY_SKILL=parameters,SKILL_LABELS=labels,
                   SKILL_DESCRIPTIONS=descriptions,SKILL_ALIASES=aliases,
                   CUSTOM_SKILL_IDS=[row['id'] for row in ROWS],CUSTOM_SKILL_PROTOCOL=REVISION)


def require_catalog(project,catalog):
    values=selected(project)
    if values and catalog.get('CUSTOM_SKILL_PROTOCOL')!=REVISION:
        raise ValueError('此工程包含扩展技能，当前软件的比赛技能适配尚未发布，未写入 APK')
    return values


def parameter(skill):
    if type(skill) is not int or not FIRST_ID <= skill < FIRST_ID + COUNT:
        raise ValueError('未知的工坊扩展技能编号')
    return FIRST_PARAMETER + skill - FIRST_ID


def match_flag(skill):
    return FIRST_MATCH_FLAG + parameter(skill) - FIRST_PARAMETER


def source_fields():
    return {str(row['id']): {'bit': SOURCE_BIT + index,
                             'source': REVISION, 'virtual_parameter': parameter(row['id'])}
            for index, row in enumerate(ROWS)}


def selected(project):
    """Carry innate and additional custom ownership in the native card bits.

The owned list still distinguishes additional skills for UI/category purposes.
Its native compact override contains only the original 147 parameters, so the
custom markers are supplied by the card catalogue for either skill category.
"""
    return {skill for key in ('innate_skills', 'additional_skills')
            for skill in project.get(key, ()) if type(skill) is int and FIRST_ID <= skill < FIRST_ID + COUNT}


def messages():
    # New keys in the existing skill text groups. All original keys and IDs
    # remain unchanged; these keys are checked against the original strings.
    return [{'id': FIRST_NATIVE_ID+index, 'name_msg': (352 << 16) | (60000 + index),
             'description_msg': (353 << 16) | (60000 + index)}
            for index, row in enumerate(ROWS)]


def native_ids(values):
    """Editor/project IDs stay stable; never assign native empty-slot ID 74."""
    return [FIRST_NATIVE_ID+skill-FIRST_ID if FIRST_ID<=skill<FIRST_ID+COUNT else skill for skill in values]


def upgrade_definitions(players):
    """Old DIY APKs used editor IDs in owned additional-skill slots."""
    for player in players:
        if not player.get('studio_custom_skills'):continue
        version=player.get('studio_custom_skill_protocol')
        if version==REVISION:
            player['owned'].setdefault('_studio_custom_skill_protocol',REVISION)
            continue
        if version not in (None,'studio-custom-skills-v2-1'):
            raise ValueError('个人包的扩展技能编号协议未知，未修改技能')
        owned=player['owned'];owned['additional_skill_id']=native_ids(owned.get('additional_skill_id',[]))
        owned['_studio_custom_skill_protocol']=REVISION
        player['studio_custom_skill_protocol']=REVISION


def text_groups(locale='zha'):
    chinese = locale in ('zha', 'chi')
    descriptions = (
        'When shooting inside the opposing penalty area with an opponent within 2.5 m, reduces horizontal and elevation random aiming error by 50%. Ball speed is unchanged.',
        'Reduces ground and lofted through-pass horizontal random aiming error by 40%. With established possession, a nearly stationary actor and a local contact pose, reduces pre-contact wind-up by 40% and restores the original rate after release. Running, receiving and unsafe transitions retain native timing.',
        'When starting a short pass with an opponent within 2 m, reduces direction, elevation and speed random perturbations by 40%. With established possession, a nearly stationary actor and a local contact pose, reduces pre-contact wind-up by 40%; unsafe transitions retain native timing.',
        'During actual back-to-goal shielding with the same opponent behind and within 1.8 m, increases shielding contest resistance by 50%.',
    )
    return [
        {'name': 'E15W', 'id': 352, 'items': {60000 + i: row['name'] if chinese else row['english']
                                              for i, row in enumerate(ROWS)}},
        {'name': 'E18T', 'id': 353, 'items': {60000 + i: row['description'] if chinese else descriptions[i]
                                              for i, row in enumerate(ROWS)}},
    ]
