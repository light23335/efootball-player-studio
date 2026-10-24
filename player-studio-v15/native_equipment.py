"""Native boot assignments and packed PlayerAppearance sleeve selection."""
from pathlib import Path
import json,struct
from native_cpk import unwrap,wrap
from native_models import person_keys

BOOTS='common/etc/pesdb/Boots.bin'
ASSIGNMENTS='common/etc/appearance/BootsList.bin'
SLEEVES={'keep':None,'seasonal':0,'short':1,'long':2}
SLEEVE_BIT=134

def validate(value):
    if not isinstance(value,dict):raise ValueError('比赛装备设置格式无效')
    if value.get('sleeves','keep') not in SLEEVES:raise ValueError('袖长请选择跟随模板、随季节、短袖或长袖')
    boots=value.get('boots_id')
    if boots is not None and (type(boots) is not int or not 0<=boots<=65535):raise ValueError('球鞋编号无效')

def catalogue(cpk):
    data=unwrap(cpk.read(BOOTS))
    if len(data)%304:raise ValueError('球鞋型号表结构改变，未写入装备')
    rows=[];seen=set()
    for at in range(0,len(data),304):
        row=data[at:at+304];key=struct.unpack_from('<H',row)[0]
        if key in seen:raise ValueError('球鞋型号编号重复')
        seen.add(key)
        color=row[4:104].split(b'\0')[0].decode('utf8','strict')
        material=row[104:204].split(b'\0')[0].decode('utf8','strict')
        name=row[204:304].split(b'\0')[0].decode('utf8','strict')
        rows.append({'id':key,'name':name or material or '原版球鞋','color':color,'material':material})
    return {'boots':rows,'sleeves':[{'id':k,'name':n} for k,n in zip(SLEEVES,('跟随模板','随季节','短袖','长袖'))]}

def write_catalogue(cpk,resources):
    result=catalogue(cpk)
    (Path(resources)/'native-equipment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return len(result['boots'])

def read_catalogue(resources,fallback=None):
    path=Path(resources)/'native-equipment.json'
    if not path.is_file() and fallback:path=Path(fallback)/'native-equipment.json'
    return json.loads(path.read_text(encoding='utf8')) if path.is_file() else {'boots':[],'sleeves':[]}

def patch_sleeves(row,equipment):
    validate(equipment);choice=SLEEVES[equipment.get('sleeves','keep')]
    if choice is None:return row
    if len(row)!=64:raise ValueError('原版外观记录长度改变')
    value=int.from_bytes(row,'little');value=(value&~(3<<SLEEVE_BIT))|(choice<<SLEEVE_BIT)
    return value.to_bytes(64,'little')

def compile_boots(cpk,projects,definitions,bindings,replace_ids=()):
    source=cpk.read(ASSIGNMENTS);data=unwrap(source)
    if len(data)%16:raise ValueError('球鞋分配表结构改变')
    rows=dict(struct.iter_unpack('<QQ',data))
    if len(rows)*16!=len(data):raise ValueError('球鞋分配表含重复编号')
    original=dict(rows);replace_ids=set(replace_ids)
    rows={k:v for k,v in rows.items() if k not in replace_ids}
    available={r['id'] for r in catalogue(cpk)['boots']};report=[]
    for p,d,b in zip(projects,definitions,bindings):
        settings=p.get('equipment') or {};validate(settings)
        donor=p.get('model',{}).get('appearance_source_id') or p['native_card']['source_id']
        inherited=next((original[int(k)] for k in person_keys(donor) if int(k) in original),None)
        selected=settings.get('boots_id')
        if selected is not None and selected not in available:raise ValueError(p['identity']['name']+'：当前 APK 不含所选球鞋型号，请重新选择')
        boots=selected if selected is not None else inherited
        if boots is None:
            report.append({'package_id':d['identity']['package_id'],'boots_id':None,'mode':'native-default'});continue
        aliases={d['identity']['card_id'],*map(int,person_keys(d['identity']['person_id'])),int(b['asset_key'])}
        for alias in aliases:
            if alias in original and alias not in replace_ids:raise ValueError('个人球鞋编号与原版记录冲突')
            rows[alias]=boots
        report.append({'package_id':d['identity']['package_id'],'boots_id':boots,'mode':'selected' if selected is not None else 'template'})
    result=b''.join(struct.pack('<QQ',pid,rows[pid]) for pid in sorted(rows))
    assert all(rows[k]==v for k,v in original.items() if k not in replace_ids)
    return wrap(result,source),report
