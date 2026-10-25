"""V13's 64-byte appearance records. Unedited fields remain byte-identical."""
import struct

FIELDS=(('neck_length','颈长'),('neck_size','颈围'),('shoulder_height','肩高'),
        ('shoulder_width','肩宽'),('chest','胸围'),('waist','腰围'),
        ('arm_size','上臂围'),('arm_length','臂长'),('thigh_size','大腿围'),
        ('calf_size','小腿围'),('leg_length','腿长'),('head_height','头部长度'),
        ('head_width','头部宽度'),('head_depth','头部厚度'))

def decode(row):
    value=int.from_bytes(row,'little')
    return {'physique':{key:(value>>(64+4*i))&15 for i,(key,_) in enumerate(FIELDS)},
            'skin_tone':(value>>292)&7}

def compact_table(records):
    """Encode native 64-byte rows into the preview's indexed 16-byte format."""
    result=[]
    for ident,row in sorted(records.items()):
        if len(row)!=64 or struct.unpack_from('<Q',row)[0]!=ident:
            raise ValueError('原生外观记录的身份或长度不一致')
        values=decode(row)
        physique=sum(values['physique'][key]<<(4*i) for i,(key,_) in enumerate(FIELDS))
        result.append(struct.pack('<Q',ident)+physique.to_bytes(7,'little')+bytes([values['skin_tone']]))
    return b''.join(result)

def validate(model):
    if 'skin_tone_edited' in model and type(model['skin_tone_edited']) is not bool:
        raise ValueError('肤色编辑标记必须为开关值')
    values=model.get('physique') or {}
    if not isinstance(values,dict) or values.keys()-{key for key,_ in FIELDS}:
        raise ValueError('未知的原生体型参数')
    if any(type(v) is not int or not 0<=v<=14 for v in values.values()):
        raise ValueError('原生体型参数范围为整数 0–14')
    tone=model.get('skin_tone')
    if tone is not None and (type(tone) is not int or not 1<=tone<=6):
        raise ValueError('原生肤色档位范围为 1–6')

def patch(row,model):
    validate(model);value=int.from_bytes(row,'little')
    for i,(key,_) in enumerate(FIELDS):
        if key in (model.get('physique') or {}):
            bit=64+i*4;value=(value&~(15<<bit))|(model['physique'][key]<<bit)
    if model.get('skin_tone') is not None:
        # Older editors displayed native default 0 as 1. Merely copying that
        # displayed value must not turn a native default into an override.
        native_default=(value>>292)&7==0 and model['skin_tone']==1 and not model.get('skin_tone_edited')
        if not native_default:value=(value&~(7<<292))|(model['skin_tone']<<292)
    return value.to_bytes(64,'little')

def face_skin(raw,tone):
    if tone is None:return raw
    validate({'skin_tone':tone})
    from native_iostore import package_names
    names=package_names(raw)
    if 'SkinColor' not in names or 'IntProperty' not in names:
        raise ValueError('此脸模没有已适配的 SkinColor 属性，未写入肤色')
    tag=struct.pack('<IIIIII',names.index('SkinColor'),0,names.index('IntProperty'),0,4,0)
    found=[];start=0
    while (at:=raw.find(tag,start))>=0:
        if at+29<=len(raw) and raw[at+24]==0 and 0<=struct.unpack_from('<i',raw,at+25)[0]<=6:found.append(at+25)
        start=at+1
    if len(found)!=1:raise ValueError('脸模肤色属性位置不唯一，未写入')
    out=bytearray(raw);struct.pack_into('<i',out,found[0],tone);return bytes(out)

def original_face_skin(raw,model,resources,source_id=None):
    """Keep an unedited original face intact, including optional properties."""
    validate(model)
    tone=model.get('skin_tone')
    source_id=model.get('appearance_source_id') or source_id
    baseline=profile(resources,source_id) if source_id is not None else None
    # The editor displays native default (0) as tone 1 when loading a player.
    original_tone=(baseline['skin_tone'] or 1) if baseline else None
    if tone is None or original_tone is not None and tone==original_tone:
        return raw,{'mode':'preserved-original','requested':tone,'original':original_tone}
    try:
        result=face_skin(raw,tone)
    except ValueError as exc:
        hint=(f'请将肤色恢复为原版档位 {original_tone}，即可保留原脸模生成 APK'
              if original_tone is not None else '无法确认原版肤色，请重新从原版资源库载入此球员')
        raise ValueError(f'此原版脸模不支持当前肤色修改（{exc}）；{hint}') from exc
    return result,{'mode':'modified','requested':tone,'original':original_tone}


def donor(project,records,fallback):
    """Card decoration changes must not replace the copied player's body."""
    explicit=(project.get('model') or {}).get('appearance_source_id')
    if explicit is not None:
        ident=int(explicit)
        if ident not in records:raise ValueError('所选体型没有对应的原版外观记录')
        return ident
    source=(project.get('source_player') or {}).get('id')
    if source is not None:
        from native_models import person_keys
        for ident in map(int,person_keys(source)):
            if ident in records:return ident
    ident=int(fallback)
    if ident not in records:raise ValueError('所选体型没有已核对的原版外观记录')
    return ident


def profile(resources,pid):
    # Compact, original values: ID(8), fourteen 4-bit fields(7), skin(1).
    data=(resources/'native-appearance.bin').read_bytes();pid=int(pid)
    low,high=0,len(data)//16
    while low<high:
        mid=(low+high)//2;key=struct.unpack_from('<Q',data,mid*16)[0]
        if key<pid:low=mid+1
        else:high=mid
    if low>=len(data)//16 or struct.unpack_from('<Q',data,low*16)[0]!=pid:return None
    values=int.from_bytes(data[low*16+8:low*16+15],'little')
    return {'source_id':str(pid),'physique':{key:(values>>(4*i))&15 for i,(key,_) in enumerate(FIELDS)},
            'skin_tone':data[low*16+15]}
