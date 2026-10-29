"""Add personal V13 database rows without changing original player records."""
import csv
import io
import json
import struct

from native_cpk import Cpk,unwrap,wrap
from native_appearance import patch as patch_appearance,donor as appearance_donor
from native_strings import booster_rows,merge as merge_strings
from native_models import person_keys
from player_identity_binding import owned_person_aliases
from native_equipment import patch_sleeves,compile_boots,ASSIGNMENTS as BOOT_ASSIGNMENTS
from custom_boosters import BOOSTER_BITS,validate_projects,canonical,context,text_key
from native_celebration import FIELD as CELEBRATION_FIELD,validate as validate_celebration
from ai_playing_styles import FIELDS as AI_FIELDS

PLAYER='common/etc/pesdb/Player.bin'
APPEARANCE='common/etc/appearance/PlayerAppearance.bin'
VARIATION='common/etc/pesdb/PlayerVariationDetail.bin'
ALIASES='common/etc/playercard/filenameConvTable.csv'
BOOSTERS='common/etc/pesdb/PlayerBooster.bin'
WEEKLY='common/etc/pesdb/PlayerWeekly.bin'


def set_bits(value,bit,width,new):
    if type(new) is not int or not 0<=new<(1<<width):raise ValueError('Native database field is outside its bit range')
    mask=((1<<width)-1)<<bit
    return (value&~mask)|(new<<bit)


def rows(data,size,key_offset=0,require_sorted=True):
    if len(data)%size:raise ValueError('Native database table stride changed')
    result={}
    for i in range(0,len(data),size):
        row=data[i:i+size];key=int.from_bytes(row[key_offset:key_offset+8],'little')
        if key in result:raise ValueError('Duplicate native database player identity')
        result[key]=row
    if require_sorted and list(result)!=sorted(result):raise ValueError('Original native player table is not sorted')
    return result


def player_record(template,project,definition,fields,ability_bits,skill_bits):
    identity=project['identity'];base=definition['base_parameters'];value=int.from_bytes(template,'little')
    updates={'external_pid':definition['identity']['card_id'],'club':definition['owned']['initial_base_team_id'],
             'nationality':definition['owned']['_nation_id'],'position':base[0],
             'height_cm':identity['height_cm']-100,'weight_kg':identity['weight_kg']-30,'age':identity['age']-10,
             'foot':base[43],'weak_foot_accuracy':base[33],'weak_foot_usage':base[45],
             'form':base[41],'injury_resistance':base[42],
             'style.in_possession':base[61],'style.out_of_possession':base[62],
             'celebration':validate_celebration(base[59])}
    for pos,aptitude in project['position_aptitudes'].items():updates['aptitude.'+pos]=int(aptitude)
    for key,new in updates.items():
        field=fields.get(key,CELEBRATION_FIELD) if key=='celebration' else fields[key]
        value=set_bits(value,**field,new=int(new))
    for index,field in ability_bits.items():value=set_bits(value,field['bit'],6,base[int(index)]-40)
    for field in AI_FIELDS.values():value=set_bits(value,field['bit'],1,base[field['parameter']])
    from ai_playing_styles import CUSTOM_SOURCE_BIT
    value=set_bits(value,CUSTOM_SOURCE_BIT,1,int('lone_wolf' in definition.get('ai_playing_styles',definition['owned'].get('ai_playing_styles',[]))))
    from native_skill_effects import compiled_skills
    selected=set(compiled_skills(project['innate_skills'],identity['height_cm']))
    # Extended match markers carry custom ownership from either editor list.
    # The owned JSON still keeps the user's innate/additional choice separate.
    from custom_skills import selected as selected_custom
    selected.update(selected_custom(project))
    # Native skills keep the 147-parameter protocol. Extended skills use their
    # separately verified client markers; unknown table bits remain untouched.
    for skill,field in skill_bits.items():value=set_bits(value,field['bit'],1,int(int(skill) in selected))
    result=bytearray(value.to_bytes(400,'little'))
    # The historical card club is a separate native header from the current
    # club/national-team field at bit 128. Contract artwork reads this header.
    struct.pack_into('<Q',result,0,definition['owned']['initial_base_team_id'])
    shirt=identity.get('shirt_name') or identity['name']
    for index,name in enumerate([identity['name'],shirt,identity['name'],shirt,project.get('display_name') or identity['name']]):
        encoded=name.encode('utf8')
        if len(encoded)>60:raise ValueError('原版姓名字段最多 60 个 UTF-8 字节，请缩短姓名后导出')
        result[88+61*index:149+61*index]=encoded+b'\0'*(61-len(encoded))
    from native_motion import patch_record
    return patch_record(bytes(result),project)


def booster_table(data,projects,replace_ids=()):
    if len(data)%40:raise ValueError('Native booster record layout changed')
    validate_projects(projects)
    result={int.from_bytes(data[i+14:i+16],'little')&1023:data[i:i+40] for i in range(0,len(data),40)}
    custom={}
    for project in projects:
        selected=set(project['booster_ids'])
        for booster in project.get('custom_boosters',[]):
            if booster['id'] not in selected:continue
            key=booster['id']
            if key in result and key not in custom and key not in replace_ids:raise ValueError(context(project,booster)+'：编号与 APK 内已有增能冲突，请使用配套工程和原编号注册表')
            effects={str(k):v for k,v in booster['effects'].items() if v}
            if key in custom and canonical(custom[key])!=canonical(booster):
                raise ValueError(context(project,booster)+'：不同增能占用同一编号，请新建独立增能')
            custom[key]=booster
            # Keep an existing native description reference until a personal
            # language-string row is compiled; ability effects are independent.
            value=int.from_bytes(result[76],'little')
            value=set_bits(value,112,10,key)
            for bit in BOOSTER_BITS.values():value=set_bits(value,bit,5,0)
            for ability,amount in effects.items():value=set_bits(value,BOOSTER_BITS[ability],5,amount)
            # In all 418 original nonempty records this field equals the
            # largest individual effect. The detail panel reads it directly.
            value=set_bits(value,212,5,max(effects.values(),default=0))
            result[key]=value.to_bytes(40,'little')
    return b''.join(result[k] for k in sorted(result))


def weekly_table(data,projects,definitions,bindings=None,replace_ids=()):
    if len(data)%16:raise ValueError('原生实时更新状态表长度改变')
    original=list(struct.iter_unpack('<QII',data))
    original=[r for r in original if r[0] not in replace_ids];data=b''.join(struct.pack('<QII',*r) for r in original)
    seen={r[0] for r in original}
    sequence=max((r[1] for r in original),default=0);extra=[]
    # All 1,398 supplied Legendary/Epic/Big Time weekly records use grade 3
    # (B). Keep every original byte, including duplicate original identities.
    for project,definition,binding in zip(projects,definitions,bindings or [{} for _ in definitions]):
        selected=project.get('weekly_condition','auto')
        if selected=='auto' and project['card_type'] not in ('BigTime','Epic','Legendary'):continue
        grades={'A':4,'B':3,'C':2,'D':1,'E':0}
        if selected!='auto' and selected not in grades:raise ValueError('实时更新状态无效')
        grade=3 if selected=='auto' else grades[selected]
        identity=definition['identity']
        basic=set() if identity.get('bound_original_player_id') else {identity['person_id']}
        if binding.get('asset_key'):basic.add(int(binding['asset_key']))
        for pid in sorted({identity['card_id'],*basic,*identity.get('previous_card_ids',[])}):
            if pid in seen:raise ValueError('个人周状态编号与原版冲突')
            if selected=='auto' and pid not in basic and ((pid>>40)&255) not in (0x10,0x50,0x51,0x70):continue
            sequence+=1;extra.append(struct.pack('<QII',pid,sequence,grade));seen.add(pid)
    return data+b''.join(extra),len(extra)


def compile_tables(original,projects,definitions,resources,bindings,extra=None,replace_ids=(),replace_boosters=()):
    cpk=Cpk(original)
    wrapped={n:cpk.read(n) for n in (PLAYER,APPEARANCE,VARIATION,ALIASES,BOOSTERS)}
    raw={n:unwrap(value) for n,value in wrapped.items()}
    players=rows(raw[PLAYER],400,8);appearances=rows(raw[APPEARANCE],64);variants=rows(raw[VARIATION],168,require_sorted=False)
    original_players=dict(players);original_appearances=dict(appearances);original_variants=dict(variants)
    replace_ids=set(replace_ids)
    players={k:v for k,v in players.items() if k not in replace_ids}
    appearances={k:v for k,v in appearances.items() if k not in replace_ids}
    variants={k:v for k,v in variants.items() if k not in replace_ids}
    fields=json.loads((resources/'native-player-fields.json').read_text(encoding='utf8'))
    ability_bits=json.loads((resources/'native-ability-bits.json').read_text(encoding='utf8'))
    from native_skill_effects import skill_bits as verified_skill_bits
    skill_bits=verified_skill_bits(resources)
    lines=raw[ALIASES].decode('utf8').splitlines();alias_rows=list(csv.reader(lines))
    aliases={row[0]:row[1] for row in alias_rows[1:] if len(row)==2}
    for project,definition,binding in zip(projects,definitions,bindings):
        cid=definition['identity']['card_id'];person=definition['identity']['person_id']
        anchor=int(project['native_card']['source_id'])
        if cid in players or person in players and not definition['identity'].get('bound_original_player_id'):raise ValueError('个人编号与原版球员冲突，未写入')
        template=original_players[anchor]
        record=player_record(template,project,definition,fields,ability_bits,skill_bits)
        players[cid]=record
        # Different native readers normalise the same permanent identity to
        # low-24, low-23 or low-22 person keys. Each needs the same body data.
        basic=set(owned_person_aliases(definition['identity']))
        if binding.get('asset_key'):basic.add(int(binding['asset_key']))
        for target in basic:
            if target in players:raise ValueError('个人基础资料别名与原版球员冲突')
            base_record=bytearray(record);struct.pack_into('<Q',base_record,8,target);players[target]=bytes(base_record)
        donor=appearance_donor(project,original_appearances,binding['appearance_id'])
        if donor not in original_appearances:raise ValueError('所选体型没有已核对的原版外观记录')
        for target in {cid,*basic}:
            appearance=bytearray(patch_sleeves(patch_appearance(original_appearances[donor],project.get('model',{})),project.get('equipment',{})));struct.pack_into('<Q',appearance,0,target);appearances[target]=bytes(appearance)
        variant=bytearray(original_variants.get(anchor,bytes(168)))
        struct.pack_into('<Q',variant,0,cid)
        date=project.get('appearance',{}).get('card_date') or ''
        if project['card_type']=='BigTime' and date:
            import datetime
            day=datetime.date.fromisoformat(date)
            label=f"Big Time {day.day} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][day.month-1]} '{day.year%100:02d}".encode()
        else:label=(project['card_type']+' Personal').encode()
        variant[12:140]=label[:127]+b'\0'*(128-min(127,len(label)))
        variants[cid]=bytes(variant)
        for target in {cid,*basic}:
            for suffix in ('_','_l'):aliases[str(target)+suffix]=binding['portrait_name']
            aliases[str(target)+'f']=binding['asset_key']+'f'
        for before,after in binding.get('card_aliases',{}).items():aliases[before]=after
    for key,value in original_players.items():
        if key in replace_ids:continue
        if players[key]!=value:raise ValueError('An original player record changed')
    for key,value in original_appearances.items():
        if key in replace_ids:continue
        if appearances[key]!=value:raise ValueError('An original appearance record changed')
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\r\n');writer.writerow(['before','after']);writer.writerows(sorted(aliases.items()))
    updated={PLAYER:b''.join(players[k] for k in sorted(players)),APPEARANCE:b''.join(appearances[k] for k in sorted(appearances)),
             VARIATION:b''.join(variants.values()),ALIASES:stream.getvalue().encode(),
             BOOSTERS:booster_table(raw[BOOSTERS],projects,replace_boosters)}
    replacements={name:wrap(value,wrapped[name]) for name,value in updated.items()}
    abilities=json.loads((resources/'catalog.json').read_text(encoding='utf8'))['ABILITIES']
    texts,text_routes=booster_rows(projects,abilities)
    from native_skill_effects import text_groups
    from native_strings import merge_groups
    for name in cpk.files:
        if name.endswith('/string/all_diff.str'):
            content=cpk.read(name)
            if texts:content=merge_strings(content,texts,{text_key(bid)+j for bid in replace_boosters for j in (0,1)})
            replacements[name]=merge_groups(content,text_groups(resources,name.split('/')[0]))
    weekly,weekly_added=weekly_table(unwrap(cpk.read(WEEKLY)),projects,definitions,bindings,replace_ids)
    replacements[WEEKLY]=wrap(weekly,cpk.read(WEEKLY))
    replacements[BOOT_ASSIGNMENTS],equipment_report=compile_boots(cpk,projects,definitions,bindings,replace_ids)
    replacements.update(extra or {})
    result=cpk.replace(replacements)
    server_only=sorted({skill for project in projects for skill in project['innate_skills'] if str(skill) not in skill_bits})
    return result,{'players_added':len(players)-len(original_players),'original_player_records_preserved':len(original_players),
                   'original_appearance_records_preserved':len(original_appearances),'personal_cards':len(projects),
                   'native_person_aliases':{d['identity']['package_id']:owned_person_aliases(d['identity']) for d in definitions},
                   'equipment':equipment_report,'personal_booster_text_routes':text_routes,
                   'fixed_B_weekly_records_added':weekly_added,
                   'personal_weekly_states':{d['identity']['package_id']:p.get('weekly_condition','auto') for p,d in zip(projects,definitions)},
                   'innate_skills_written_via_owned_protocol_only':server_only}
