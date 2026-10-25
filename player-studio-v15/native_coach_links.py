"""Coach Link-up conditions. IDs in coach slots 2/3 are not boosters."""
import copy
import json
from pathlib import Path
from studio_resources import bundled_resources
from native_cpk import unwrap,wrap

TABLE='common/etc/pesdb/CoachLink.bin'
RESOURCE=bundled_resources()


def schema(resources=None):
    return json.loads(((Path(resources) if resources else RESOURCE)/'native-coach-links.json').read_text(encoding='utf8'))


def rows(raw):
    if len(raw)%8:raise ValueError('心有灵犀条件表长度改变')
    values={int.from_bytes(raw[i:i+8],'little')&1023:raw[i:i+8] for i in range(0,len(raw),8)}
    if len(values)!=len(raw)//8 or 0 in values:raise ValueError('心有灵犀条件编号无效或重复')
    return values


def decode(row,info):
    value=int.from_bytes(row,'little');result={'template_id':value&1023}
    for role in ('source','target'):
        result[role+'_positions']=[int(pos) for pos,bit in info['position_bits'][role].items() if value>>bit&1]
        result[role+'_style']=(value>>(10 if role=='source' else 16))&63
    return result


def normalize(value,info=None):
    info=info or schema()
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('心有灵犀设置格式无效')
    ident=value.get('template_id')
    if type(ident) is not int or str(ident) not in info['effect_by_template']:
        raise ValueError('心有灵犀只能选择当前游戏已有的类型')
    result={'template_id':ident}
    for role in ('source','target'):
        positions=value.get(role+'_positions')
        if not isinstance(positions,list) or not positions or any(type(p) is not int or not 0<=p<=12 for p in positions):
            raise ValueError('核心球员和关键球员必须分别选择至少一个有效位置')
        style=value.get(role+'_style')
        if type(style) is not int or not 0<=style<=35:raise ValueError('心有灵犀比赛风格编号无效')
        result[role+'_positions']=sorted(set(positions));result[role+'_style']=style
    return result


def normalize_slots(value,info=None):
    if value is None:return [None,None]
    if not isinstance(value,list) or len(value)>2:raise ValueError('原生教练最多有两项心有灵犀')
    return [normalize(v,info) for v in value]+[None]*(2-len(value))


def encode(template,config,ident,info):
    config=normalize(config,info);value=int.from_bytes(template,'little')
    value=(value&~1023)|ident
    for role,shift in (('source',10),('target',16)):
        value=(value&~(63<<shift))|(config[role+'_style']<<shift)
        for position,bit in info['position_bits'][role].items():
            value=(value&~(1<<bit))|(int(int(position) in config[role+'_positions'])<<bit)
    return value.to_bytes(8,'little')


def compile_links(cpk,coaches,registry,info=None):
    if not coaches:return {},{},[]
    info=info or schema();wrapped=cpk.read(TABLE);records=rows(unwrap(wrapped))
    assigned=registry.setdefault('links',{});by_coach={};routes=[]
    for coach in coaches:
        selected=[]
        for slot,config in enumerate(normalize_slots(coach.get('linkups'),info)):
            if config is None:selected.append(0);continue
            template=config['template_id']
            if template not in records:raise ValueError('原 APK 缺少所选心有灵犀类型')
            if decode(records[template],info)==config:selected.append(template);continue
            key=coach['uuid']+':'+str(slot)
            ident=assigned.get(key)
            if ident is None:
                ident=next((v for v in range(256,512) if v not in records and v not in assigned.values()),None)
                if ident is None:raise ValueError('本次 APK 的独立心有灵犀条件编号已用完')
                assigned[key]=ident
            if type(ident) is not int or not 256<=ident<512:raise ValueError('独立心有灵犀编号无效')
            records[ident]=encode(records[template],config,ident,info)
            routes.append({'id':ident,'template_id':template});selected.append(ident)
        by_coach[coach['uuid']]=selected
    return {TABLE:wrap(b''.join(records[k] for k in sorted(records)),wrapped)},by_coach,routes


def read_catalogue(cpk,coaches,resources,routes=()):
    info=schema(resources);records=rows(unwrap(cpk.read(TABLE)))
    templates={r['id']:r['template_id'] for r in routes if str(r.get('template_id')) in info['effect_by_template']}
    for coach in coaches:
        ids=coach.get('ability_ids',[])[2:4]
        coach['linkups']=[dict(decode(records[ident],info),template_id=templates.get(ident,ident)) if ident in records else None for ident in ids]
        coach['linkups']+=(2-len(coach['linkups']))*[None]
    labels=info.get('template_labels',{})
    return [{**decode(row,info),'label':labels.get(str(ident),'原生组合 '+str(ident)),
             'effect':info['effect_by_template'][str(ident)],
             'coaches':[c['name'] for c in coaches if ident in c.get('ability_ids',[])[2:4]]}
            for ident,row in sorted(records.items()) if str(ident) in info['effect_by_template']]


def repair_legacy(document,info=None,resources=None):
    """Repair previously imported read-only coach options without touching saves."""
    info=info or schema();known=info.get('booster_records',{});templates=info.get('templates',[])
    from native_coaches import SLOT_LAYOUT,COACH,ability_ids
    if resources and document.get('coach_slot_layout')!=SLOT_LAYOUT:
        import zipfile
        from native_cpk import Cpk
        report=Path(resources)/'import-report.json'
        try:
            apk=json.loads(report.read_text(encoding='utf8'))['apk'];native={}
            with zipfile.ZipFile(apk) as archive:
                for source in ('livedata','custom-resources/legends-v10'):
                    cpk=Cpk(archive.read('assets/gateway-release/'+source+'/dt870_mobile_and.cpk'))
                    if COACH not in cpk.files:continue
                    raw=unwrap(cpk.read(COACH))
                    if len(raw)%176:raise ValueError('教练表长度改变')
                    for at in range(0,len(raw),176):native[str(int.from_bytes(raw[at:at+8],'little'))]=ability_ids(raw[at:at+176])
            for coach in document['coaches']:
                if str(coach['id']) in native:
                    coach['ability_ids']=native[str(coach['id'])]
                    coach.setdefault('raw_payload',{})['ability_id']=coach['ability_ids']
            document.pop('coach_options_revision',None);document['coach_slot_layout']=SLOT_LAYOUT
        except (OSError,KeyError,ValueError,zipfile.BadZipFile):pass
    if document.get('coach_options_revision')=='native-boosters-2-and-links-2-v1':
        for row in document.get('linkup_types',[]):row['label']=info.get('template_labels',{}).get(str(row['template_id']),row.get('label',''))
        return document
    indexed={t['template_id']:t for t in templates}
    for coach in document.get('coaches',[]):
        ids=coach.get('ability_ids') or coach.get('raw_payload',{}).get('ability_id',[])
        if not ids:continue
        effects={};unmapped=[]
        for ident in ids[:2]:
            if not ident:continue
            effect=known.get(str(ident))
            if effect:
                key=effect['parameter'];effects[key]=effects.get(key,0)+effect['amount']
            else:unmapped.append(ident)
        coach.update(effects=effects,unmapped_abilities=unmapped,
                     linkups=[copy.deepcopy(indexed.get(ident)) for ident in (ids+[0]*4)[2:4]])
    document['linkup_types']=[{**copy.deepcopy(t),'label':info.get('template_labels',{}).get(str(t['template_id']),'原生组合 '+str(t['template_id'])),
                              'effect':info['effect_by_template'][str(t['template_id'])],
                              'coaches':[c['name'] for c in document['coaches'] if t['template_id'] in (c.get('ability_ids') or c.get('raw_payload',{}).get('ability_id',[]))[2:4]]}
                             for t in templates]
    document['coach_options_revision']='native-boosters-2-and-links-2-v1'
    return document
