"""Personal coach records and ownership, preserving the original coach rows."""
import copy,hashlib,json,struct
from native_cpk import unwrap,wrap

COACH='common/etc/pesdb/Coach.bin'
BOOSTER='common/etc/pesdb/CoachBooster.bin'
TACTICS={'possession':206,'short_counter':224,'long_counter':238,'side_attack':213,'long_ball':199}
# Independently matched against every supplied coach with this ability. Other
# attribute enums must be verified before they can be compiled.
ATTRIBUTES={'38':1,'25':3,'35':4,'18':5,'21':7,'22':8,'27':10,'15':11,
            '37':13,'40':14,'39':15,'24':16,'36':17,'23':18,'14':20}

def bitfield(value,bit,width,new):
    if type(new) is not int or not 0<=new<1<<width:raise ValueError('教练原生字段超出可写范围')
    return (value&~(((1<<width)-1)<<bit))|(new<<bit)

def compile_coaches(cpk,coaches,catalogue,registry,replace_ids=(),replace_boosters=()):
    if not coaches:return {},[]
    original=cpk.read(COACH);raw=unwrap(original)
    if len(raw)%176:raise ValueError('原生教练表长度改变')
    records={int.from_bytes(raw[i:i+8],'little'):raw[i:i+176] for i in range(0,len(raw),176)}
    booster_wrapper=cpk.read(BOOSTER);boosters=unwrap(booster_wrapper)
    if len(boosters)%4:raise ValueError('教练增能表长度改变')
    bonus={int.from_bytes(boosters[i:i+4],'little')&1023:boosters[i:i+4] for i in range(0,len(boosters),4)}
    template=next(c for c in catalogue if int(c['id']) in records and c.get('raw_payload_verified',True))
    owned=[];used=registry.setdefault('coaches',{});boost_registry=registry.setdefault('boosters',{})
    for c in coaches:
        uid=c['uuid']
        if uid not in used:
            start=600000+int(hashlib.sha256(uid.encode()).hexdigest()[:12],16)%400000
            cid=start
            while cid in records or cid in used.values():
                cid=600000+(cid-600000+1)%400000
                if cid==start:raise ValueError('个人教练编号空间已用完')
            used[uid]=cid
        cid=used[uid]
        if cid in records and cid not in replace_ids:raise ValueError('个人教练编号与原版冲突')
        effects={str(k):v for k,v in c['effects'].items() if v}
        if len(effects)>4:raise ValueError(c['name']+'：V13 教练最多支持 4 项独立能力增能')
        if effects.keys()-ATTRIBUTES.keys():raise ValueError(c['name']+'：部分教练增能属性尚未核对原生编号，未用其他效果替代')
        if any(type(v) is not int or not 0<=v<=15 for v in effects.values()):raise ValueError(c['name']+'：教练实装增能目前支持 +1 至 +15')
        abilities=[]
        for index,amount in effects.items():
            key=uid+':'+index
            if key not in boost_registry:
                free=next((i for i in range(256,512) if i not in bonus and i not in boost_registry.values()),None)
                if free is None:raise ValueError('个人教练增能编号已用完')
                boost_registry[key]=free
            bid=boost_registry[key]
            if bid in bonus and bid not in replace_boosters:raise ValueError('个人教练增能编号与原版冲突')
            bonus[bid]=struct.pack('<I',bid|(amount<<10)|(ATTRIBUTES[index]<<15));abilities.append(bid)
        abilities+= [0]*(4-len(abilities))
        value=int.from_bytes(records[int(template['id'])],'little');value=bitfield(value,0,64,cid)
        for key,bit in TACTICS.items():value=bitfield(value,bit,7,c['tactics'][key])
        age=int(c.get('age') or template['age']);value=bitfield(value,231,6,age-15)
        for bit,bid in zip((160,148,128,137),abilities):value=bitfield(value,bit,9,bid)
        row=bytearray(value.to_bytes(176,'little'))
        # Native getters return row+0x20 (Japanese) and row+0x4e
        # (other locales); each name is 0x2e bytes including its terminator.
        for at,text in ((32,c['name']),(78,c.get('name_en') or c['name']),(124,c['name'])):
            encoded=text.encode('utf8')
            if len(encoded)>45:raise ValueError(c['name']+'：教练名称最多 45 个 UTF-8 字节，请缩短后实装')
            row[at:at+46]=encoded+bytes(46-len(encoded))
        records[cid]=bytes(row)
        payload=copy.deepcopy(template['raw_payload'])
        payload.update(coach_id={'id':cid,'serial':0},name=c['name'],name_en=c.get('name_en') or c['name'],age=age,
                       ability_id=abilities,**c['tactics'],_personal_coach_uuid=uid)
        payload['is_coach_texture_use']='YES' if c.get('portrait') else template['raw_payload'].get('is_coach_texture_use','NO')
        payload['_personal_coach_revision']=hashlib.sha256(json.dumps(c,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        owned.append({'uuid':uid,'id':cid,'payload':payload})
    return {COACH:wrap(b''.join(records[k] for k in sorted(records)),original),
            BOOSTER:wrap(b''.join(bonus[k] for k in sorted(bonus)),booster_wrapper)},owned
