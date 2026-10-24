"""Read literal option tables from the APK; never import or execute its modules."""
import dis,importlib.util,io,marshal,types,zipfile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def module_reader(apk):
    with zipfile.ZipFile(apk) as z:
        with zipfile.ZipFile(io.BytesIO(z.read('assets/chaquopy/app.imy'))) as archive:
            raw=archive.read('_protected_runtime.pyc')
    if raw[:4]!=importlib.util.MAGIC_NUMBER:raise ValueError('APK 的资料字节码版本改变，需要资料适配')
    code=marshal.loads(raw[16:]);instructions=list(dis.get_instructions(code));literals={};payloads={}
    for a,b in zip(instructions,instructions[1:]):
        if a.opname=='LOAD_CONST' and b.opname in ('STORE_NAME','STORE_GLOBAL') and b.argval in ('_AAD','_MAGIC','_PARTS'):literals[b.argval]=a.argval
        if a.opname==b.opname=='LOAD_CONST' and isinstance(a.argval,str) and isinstance(b.argval,bytes):payloads[a.argval]=b.argval
    cipher=AESGCM(bytes(a^b for a,b in zip(*literals['_PARTS'])))
    def read(name):
        raw=payloads[name];data=cipher.decrypt(raw[:12],raw[12:],literals['_AAD']+name.encode()+literals['_MAGIC'])
        if data[:4]!=importlib.util.MAGIC_NUMBER:raise ValueError('APK 资料模块的版本不兼容')
        value=marshal.loads(data[16:])
        if not isinstance(value,types.CodeType):raise ValueError('APK 资料模块格式无效')
        return value
    return read

def literal_assignments(code,wanted):
    instructions=list(dis.get_instructions(code));start=0;result={}
    for at,instruction in enumerate(instructions):
        if instruction.opname not in ('STORE_NAME','STORE_FAST','STORE_DEREF','STORE_GLOBAL'):continue
        if instruction.argval in wanted:
            stack=[]
            for op in instructions[start:at]:
                if op.opname=='LOAD_CONST':stack.append(op.argval)
                elif op.opname in ('BUILD_LIST','BUILD_TUPLE'):
                    values=stack[-op.arg:] if op.arg else []
                    if op.arg:del stack[-op.arg:]
                    stack.append(tuple(values) if op.opname=='BUILD_TUPLE' else values)
                elif op.opname=='BUILD_MAP':
                    values=stack[-op.arg*2:] if op.arg else []
                    if op.arg:del stack[-op.arg*2:]
                    stack.append(dict(zip(values[::2],values[1::2])))
                elif op.opname=='MAP_ADD':value,key=stack.pop(),stack.pop();stack[-op.arg][key]=value
                elif op.opname=='BUILD_CONST_KEY_MAP':
                    keys=stack.pop();values=stack[-op.arg:] if op.arg else []
                    if op.arg:del stack[-op.arg:]
                    stack.append(dict(zip(keys,values)))
                elif op.opname=='DICT_UPDATE':values=stack.pop();stack[-op.arg].update(values)
                elif op.opname=='LIST_EXTEND':values=stack.pop();stack[-op.arg].extend(values)
                elif op.opname=='POP_TOP' and not stack:pass
                elif op.opname in ('EXTENDED_ARG','RESUME','NOP'):pass
                else:raise ValueError('新版选项资料不再是支持的常量格式：'+str(instruction.argval))
            if len(stack)!=1:raise ValueError('APK 常量资料不完整')
            result[instruction.argval]=stack[0]
        start=at+1
    if set(result)!=set(wanted):raise ValueError('APK 缺少必要选项资料')
    return result

def update_options(apk,catalog):
    reader=module_reader(apk)
    options=literal_assignments(reader('player_editor'),{'ABILITIES','PLAY_STYLES','SKILL_LABELS','POSITIONS','APTITUDES'})
    skill=literal_assignments(reader('player_skills'),{'SKILL_NAMES','PARAMETER_BY_SKILL'})
    if list(options['POSITIONS'])!=catalog['POSITIONS'] or list(options['APTITUDES'])!=catalog['APTITUDES'] or {str(k) for k in options['ABILITIES']}!=set(catalog['ABILITIES']):raise ValueError('新版位置或基础能力协议改变，未启用数据库')
    for key,value in catalog['PARAMETER_BY_SKILL'].items():
        if key in {str(k) for k in skill['PARAMETER_BY_SKILL']} and int(skill['PARAMETER_BY_SKILL'].get(int(key),skill['PARAMETER_BY_SKILL'].get(key)))!=int(value):raise ValueError('新版技能参数位置改变')
    if any(type(v) is not int or not 0<=v<147 for v in skill['PARAMETER_BY_SKILL'].values()):raise ValueError('新版技能参数超出 147 项布局')
    data=literal_assignments(reader('editor_boosters'),{'ROWS','EFFECTS','CATEGORY_NAMES','NAMED_NAMES'})
    stat_to_parameter=[14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,34,35,36,37,38,39,40]
    old={b['id']:b for b in catalog['boosters']};boosters=[]
    for ident,kind,category,amount in data['ROWS']:
        if type(ident) is not int or not 1<=ident<=1023:raise ValueError('新版增能编号超出当前原生字段')
        effects={}
        for stat,value in data['EFFECTS'].get(ident,()):
            if type(stat) is not int or not 0<=stat<len(stat_to_parameter):raise ValueError('新版增能能力字段未知')
            effects[str(stat_to_parameter[stat])]=value
        label=(data['NAMED_NAMES'].get(ident) or data['CATEGORY_NAMES'].get(category) or '原版增能 '+str(ident))+((' +'+str(amount)) if amount else '')
        if ident in old and old[ident]['effects']==effects:label=old[ident]['label']
        boosters.append({'id':ident,'category':kind,'label':label,'conditional':kind!=0,'effects':effects})
    catalog.update(options);catalog.update(skill);catalog['boosters']=boosters
    costs=literal_assignments(reader('pes_tables'),{'EXPERIENCE_LIST'})['EXPERIENCE_LIST']
    if isinstance(costs,(list,tuple)) and costs and all(isinstance(row,(list,tuple)) and len(row)==2 for row in costs):
        pairs=dict(costs)
        if sorted(pairs)!=list(range(2,max(pairs)+1)):raise ValueError('新版等级经验表不连续')
        costs=[0,0]+[pairs[level] for level in range(2,max(pairs)+1)]
    if not isinstance(costs,(list,tuple)) or len(costs)<36 or any(type(v) is not int or v<0 for v in costs):raise ValueError('新版等级经验资料格式改变')
    return {'costs':list(costs),'boosters':len(boosters),'skills':len(skill['SKILL_NAMES'])}
