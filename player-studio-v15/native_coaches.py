"""Personal coach records and ownership, preserving the original coach rows."""
import copy,hashlib,json,struct
from native_cpk import unwrap,wrap

COACH='common/etc/pesdb/Coach.bin'
BOOSTER='common/etc/pesdb/CoachBooster.bin'
TACTICS={'possession':206,'short_counter':224,'long_counter':238,'side_attack':213,'long_ball':199}
# Native disk getters 0x8236464 / 0x823648c / 0x82364b4 / 0x82364dc.
ABILITY_BITS=(160,148,128,138)
SLOT_LAYOUT='native-coach-four-10bit-v2'

def ability_ids(row):
    value=int.from_bytes(row,'little')
    return [(value>>bit)&1023 for bit in ABILITY_BITS]
# CoachBooster enum -> native ability enum -> 147-parameter index. Verified
# against 0x8236528 / 0x8236530 and 0x82a1ee4, then the runtime ability getter.
# The reference coach_boost_map.json in the original APK uses a different
# ordering and must not be used to compile or preview these native records.
ATTRIBUTES={'14':1,'15':11,'16':21,'17':4,'18':2,'19':3,'20':7,'21':5,
            '22':6,'23':10,'24':12,'25':13,'26':26,'27':8,'28':9,'29':23,
            '30':24,'31':25,'32':22,'34':15,'35':17,'36':18,'37':14,'38':16,
            '39':19,'40':20}

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
    template=next((c for c in catalogue if int(c['id']) in records and c.get('raw_payload_verified',True)),None)
    if template is None:template=next((c for c in catalogue if int(c['id']) in records),None)
    if template is None:raise ValueError('当前数据库没有可用的原生教练记录，请重新读取主 APK')
    owned=[];used=registry.setdefault('coaches',{});boost_registry=registry.setdefault('boosters',{})
    for c in coaches:
        from coach_identity import normalize as identity_fields,NATION_BIT,NATION_WIDTH
        identity=identity_fields(c)
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
        if len(effects)>2:raise ValueError(c['name']+'：原生教练只有 2 项能力增能；另外两个编号用于心有灵犀，请减少到 2 项后实装')
        if effects.keys()-ATTRIBUTES.keys():raise ValueError(c['name']+'：部分教练增能属性尚未核对原生编号，未用其他效果替代')
        if any(type(v) is not int or not 0<=v<=20 for v in effects.values()):raise ValueError(c['name']+'：教练实装增能支持 +1 至 +20，不能写入负数')
        abilities=[]
        for index,amount in effects.items():
            key=uid+':'+index
            # Reuse immutable stock entries when possible; never reserve them
            # as mutable personal identities, or a later edit could change an
            # original coach's effects as well.
            shared=next((bid for bid,row in bonus.items()
                         if bid<256 and (int.from_bytes(row,'little')>>10)&1023
                         ==amount|(ATTRIBUTES[index]<<5)),None)
            if key not in boost_registry and shared is not None:
                abilities.append(shared);continue
            if key not in boost_registry:
                free=next((i for i in range(256,512) if i not in bonus and i not in boost_registry.values()),None)
                if free is None:raise ValueError('个人教练增能编号已用完')
                boost_registry[key]=free
            bid=boost_registry[key]
            if bid in bonus and bid not in replace_boosters:raise ValueError('个人教练增能编号与原版冲突')
            # Native constructor iterates at most 200 rows (not 512 IDs).
            if bid not in bonus and len(bonus)>=200:
                raise ValueError('本次 APK 教练增能表已达原生 200 条上限，请复用已有加成或减少不同的教练增能')
            bonus[bid]=struct.pack('<I',bid|(amount<<10)|(ATTRIBUTES[index]<<15));abilities.append(bid)
        abilities+= [0]*(2-len(abilities))
        abilities+=list(c.get('_compiled_link_ids') or [0,0])
        origin=next((r for r in catalogue if str(r['id'])==identity['native_source_id'] and int(r['id']) in records),template)
        value=int.from_bytes(records[int(origin['id'])],'little');value=bitfield(value,0,64,cid)
        value=bitfield(value,NATION_BIT,NATION_WIDTH,identity['nation_id'])
        for key,bit in TACTICS.items():value=bitfield(value,bit,7,c['tactics'][key])
        age=int(c.get('age') or origin['age']);value=bitfield(value,231,6,age-15)
        for bit,bid in zip(ABILITY_BITS,abilities):value=bitfield(value,bit,10,bid)
        row=bytearray(value.to_bytes(176,'little'))
        # Native getters return row+0x20 (Japanese) and row+0x4e
        # (other locales); each name is 0x2e bytes including its terminator.
        for at,text in ((32,c['name']),(78,c.get('name_en') or c['name']),(124,c['name'])):
            encoded=text.encode('utf8')
            if len(encoded)>45:raise ValueError(c['name']+'：教练名称最多 45 个 UTF-8 字节，请缩短后实装')
            row[at:at+46]=encoded+bytes(46-len(encoded))
        records[cid]=bytes(row)
        payload=copy.deepcopy(origin['raw_payload'])
        payload.update(coach_id={'id':cid,'serial':0},name=c['name'],name_en=c.get('name_en') or c['name'],age=age,
                       ability_id=abilities,initial_base_team_id=identity['team_id'],**c['tactics'],_personal_coach_uuid=uid)
        payload['is_coach_texture_use']='YES' if c.get('portrait') else origin['raw_payload'].get('is_coach_texture_use','NO')
        payload['_personal_coach_revision']=hashlib.sha256(json.dumps(c,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        owned.append({'uuid':uid,'id':cid,'payload':payload,**identity})
    return {COACH:wrap(b''.join(records[k] for k in sorted(records)),original),
            BOOSTER:wrap(b''.join(bonus[k] for k in sorted(bonus)),booster_wrapper)},owned
