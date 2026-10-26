"""Portable, per-export game display and physical-controller preferences."""
import copy,json,struct
from pathlib import Path
from studio_resources import bundled_resources

BUTTONS=['A','B','X','Y','LB','RB','LT','RT','LS','RS','SELECT','START','UP','DOWN','LEFT','RIGHT']
LABELS={'A':'A / ×','B':'B / ○','X':'X / □','Y':'Y / △','LB':'LB / L1','RB':'RB / R1','LT':'LT / L2','RT':'RT / R2','LS':'左摇杆按下','RS':'右摇杆按下','SELECT':'返回 / Share','START':'菜单 / Options','UP':'方向上','DOWN':'方向下','LEFT':'方向左','RIGHT':'方向右'}
ACTION_LABELS={'A':'短传 / 施压','B':'长传 / 传中','X':'射门','Y':'直塞','LB':'切换球员 / 辅助跑位','RB':'辅助施压 / 控制射门','LT':'紧密盘带 / 防守对位','RT':'冲刺 / 紫色射门','LS':'左摇杆按下','RS':'右摇杆按下','SELECT':'返回','START':'暂停','UP':'战术：上','DOWN':'战术：下','LEFT':'战术：左','RIGHT':'战术：右'}

def legacy_preset(name='default'):
    if name not in ('default','fc'):raise ValueError('未知手柄预设')
    inputs={k:[k] for k in BUTTONS}
    if name=='fc':inputs.update(X=['B'],B=['X'],LT=['RB'],RB=['LT'])
    result=[{'id':k,'label':ACTION_LABELS[k],'input':inputs[k],'output':[k]} for k in BUTTONS]
    result.extend([{'id':'finesse','label':'搓射 / 控制射门','input':['RB','B'] if name=='fc' else ['RB','X'],'output':['RB','X']},
                   {'id':'cancel','label':'超级取消','input':['LT','RT'] if name=='fc' else ['RB','RT'],'output':['RB','RT']},
                   {'id':'chip','label':'挑射','input':['LB','B'] if name=='fc' else ['LB','X'],'output':['LB','X']}])
    return result

SCOPES={'attack':'进攻','defense':'防守','common':'通用'}
COMMON=BUTTONS[8:]
ATTACK_LABELS={'A':'短传','B':'长传 / 传中','X':'射门','Y':'直塞','LB':'辅助跑位修饰键','RB':'控制射门 / 传球前插修饰键','LT':'紧密盘带','RT':'冲刺 / 急停 / 趟球'}
DEFENSE_LABELS={'A':'施压','B':'铲球','X':'身体对抗 / 解围','Y':'门将出击','LB':'切换球员','RB':'辅助施压','LT':'防守对位','RT':'防守冲刺'}
COMBOS=[('finesse','控制射门 / 搓射',['RB','X']),('chip','挑射',['LB','X']),
        ('loft_through','过顶直塞',['LB','Y']),('one_two','二过一',['LB','A']),
        ('run_pass','短传后前插',['RB','A']),('run_through','直塞后前插',['RB','Y']),
        ('stunning_shot','大力射门（紫射）',['RT','X']),('stunning_pass','大力地面传球',['RT','A']),
        ('stunning_loft','大力长传 / 门将大脚开球',['RT','B']),('stunning_through','大力直塞',['RT','Y'])]

def preset(name='default'):
    if name not in ('default','fc'):raise ValueError('未知手柄预设')
    result=[]
    for scope,labels in (('attack',ATTACK_LABELS),('defense',DEFENSE_LABELS)):
        for key,label in labels.items():
            source=key
            if name=='fc' and scope=='attack':source={'X':'B','B':'X','LT':'RB','RB':'LT'}.get(key,key)
            result.append({'id':scope+'.'+key,'scope':scope,'label':label,'input':[source],'output':[key]})
        if scope=='attack':
            for key,label,output in COMBOS:
                # FC uses RB for controlled shots and pass-and-run, independently
                # of its LT native modifier mapping.
                source=[{'X':'B','B':'X'}.get(k,k) for k in output] if name=='fc' else list(output)
                result.append({'id':scope+'.'+key,'scope':scope,'label':label,'input':source,'output':list(output)})
        if scope=='attack':
            result.append({'id':'attack.cancel','scope':scope,'label':'超级取消','input':['LT','RT'] if name=='fc' else ['RB','RT'],'output':['RB','RT']})
    for key in COMMON:
        result.append({'id':'common.'+key,'scope':'common','label':ACTION_LABELS[key],'input':[key],'output':[key]})
    return result

def migrate_controller(c):
    """Keep previously saved custom inputs; split their contexts without loss."""
    if c.get('mapping_revision',0)>=3:return
    old=c.get('bindings')
    if c.get('preset') in ('default','fc'):
        c['bindings']=preset(c['preset']);return
    if not isinstance(old,list):return
    old={r.get('id'):r for r in old if isinstance(r,dict)}
    rows=preset()
    for row in rows:
        short=row['id'].split('.',1)[1]
        if short in old:row['input']=copy.deepcopy(old[short].get('input',[]))
        else:
            keys=[]
            for k in row['output']:
                for source in old.get(k,{}).get('input',[]):
                    if source not in keys:keys.append(source)
            row['input']=keys if len(keys)<=3 else []
    # Added shortcut rows cannot displace a previously configured command.
    for scope in ('attack','defense'):
        used=set()
        candidates=[r for r in rows if r['scope'] in (scope,'common')]
        candidates.sort(key=lambda r:r['id'].split('.',1)[1] not in old)
        for row in candidates:
            key=frozenset(row['input'])
            if key and key in used and row['id'].split('.',1)[1] not in old:row['input']=[]
            if row['input']:used.add(key)
    c['bindings']=rows

DEFAULTS={'frame_rate':{'enabled':False,'target':160},'display':{'enabled':False,'height':1080},'card_motion':{'enabled':True},
          'controller':{'enabled':False,'preset':'default','mapping_revision':3,'bindings':preset(),'swap_sticks':False,'invert_right_y':False}}

def normalize(body):
    if not isinstance(body,dict):raise ValueError('游戏设置格式无效')
    out=copy.deepcopy(DEFAULTS)
    for key in out:
        value=body.get(key,{})
        if not isinstance(value,dict):raise ValueError('游戏设置格式无效：'+key)
        out[key].update(value)
        if type(out[key]['enabled']) is not bool:raise ValueError('游戏设置开关无效')
    fps=out['frame_rate']['target'];height=out['display']['height']
    if type(fps) is not int or not 15<=fps<=999:raise ValueError('帧率上限须为 15–999 的整数')
    if type(height) is not int or not 480<=height<=2160:raise ValueError('分辨率短边须为 480–2160，最高 4K')
    c=out['controller']
    if 'controller' in body and body['controller'].get('mapping_revision',0)<3:
        c['mapping_revision']=body['controller'].get('mapping_revision',0);migrate_controller(c)
    c['mapping_revision']=3
    if c['preset'] not in ('default','fc','custom'):raise ValueError('手柄预设无效')
    for key in ('swap_sticks','invert_right_y'):
        if type(c[key]) is not bool:raise ValueError('摇杆设置无效')
    rows=c['bindings']
    if isinstance(rows,list):
        # Older scoped settings included a synthetic defensive cancel combo.
        # Drop that obsolete row only; retain every actual action's custom keys.
        obsolete=[r for r in rows if isinstance(r,dict) and r.get('id')=='defense.cancel']
        if len(obsolete)>1:raise ValueError('手柄动作重复或无效')
        rows=[r for r in rows if not isinstance(r,dict) or r.get('id')!='defense.cancel']
    if not isinstance(rows,list) or len(rows)!=len(preset()):raise ValueError('手柄绑定数量无效')
    expected={r['id']:r for r in preset()};seen=set();normalized=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('id') not in expected or row['id'] in seen:raise ValueError('手柄动作重复或无效')
        seen.add(row['id']);source=row.get('input')
        if not isinstance(source,list) or len(source)>3 or len(set(source))!=len(source) or any(k not in BUTTONS for k in source):raise ValueError('每个动作可绑定 0–3 个不同手柄按键')
        normalized.append({**expected[row['id']],'input':list(source)})
    # A physical input is reusable in different match contexts, but never for
    # unrelated commands in the same context (including common commands).
    for scope in ('attack','defense'):
        used={}
        for row in normalized:
            if row['scope'] not in (scope,'common'):continue
            source=tuple(sorted(row['input'],key=BUTTONS.index))
            if source and source in used:raise ValueError(SCOPES[scope]+'按键冲突：'+used[source]+' 与 '+row['label'])
            if source:used[source]=row['label']
    c['bindings']=normalized
    return out

def settings(store,body=None):
    path=store.root/'game-settings.json'
    if body is None:return normalize(json.loads(path.read_text(encoding='utf8'))) if path.is_file() else copy.deepcopy(DEFAULTS)
    value=normalize(body);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path);return value

def schema():return {'buttons':[{'id':k,'label':LABELS[k]} for k in BUTTONS],'scopes':[{'id':k,'label':v} for k,v in SCOPES.items()],'presets':{k:preset(k) for k in ('default','fc')}}

def controller_table(controller,scope='attack'):
    rows=[r for r in controller['bindings'] if r['input'] and r['scope'] in (scope,'common') and r['id']!='defense.cancel']
    if scope=='menu':rows=[{'input':[k],'output':[k]} for k in BUTTONS]
    rows.sort(key=lambda r:-len(r['input']))
    def mask(keys):return sum(1<<BUTTONS.index(k) for k in keys)
    result=bytearray()
    for row in rows:
        source=(1 if row['input']==['LT'] else 2 if row['input']==['RT'] else 0)
        left=(1 if 'LT' in row['input'] else source) if 'LT' in row['output'] else 0
        right=(2 if 'RT' in row['input'] else source) if 'RT' in row['output'] else 0
        result.extend(struct.pack('<IIII',mask(row['input']),mask(row['output']),left,right))
    return bytes(result)+bytes(16)

def controller_hooks(controller,engine,resources=None):
    if not controller['enabled']:return []
    path=(Path(resources) if resources else bundled_resources())/'native-controller.json'
    data=json.loads(path.read_text(encoding='utf8'));hook=copy.deepcopy(data['hook']);engine.seek(hook['file_offset'])
    if engine.read(64).hex()!=hook['expected_hex']:raise ValueError('此版本的实体手柄输入接口发生变化，未写入键位')
    body=bytearray.fromhex(hook['body_hex'])
    def axis_source(scope,target):
        row=next(r for r in controller['bindings'] if r['id']==scope+'.'+target)
        return 1 if row['input']==['LT'] else 2 if row['input']==['RT'] else 0
    for scope,at in data['table_offsets'].items():
        table=controller_table(controller,scope)
        if len(table)>data['table_capacity']:raise ValueError('手柄绑定表超出已验证容量')
        body[at:at+len(table)]=table
    for i,scope in enumerate(('menu','attack','defense')):
        struct.pack_into('<II',body,data['axis_sources_offset']+8*i,1 if scope=='menu' else axis_source(scope,'LT'),2 if scope=='menu' else axis_source(scope,'RT'))
    for probe in data['context_probes']:
        engine.seek(probe['file_offset'])
        if engine.read(len(bytes.fromhex(probe['expected_hex']))).hex()!=probe['expected_hex']:raise ValueError('此版本的比赛控制模式接口发生变化，未写入键位')
    struct.pack_into('<II',body,data['options_offset'],int(controller['swap_sticks']),int(controller['invert_right_y']))
    hook['body_hex']=body.hex();hook.pop('assembly',None)
    key=copy.deepcopy(data['key_hook']);engine.seek(key['file_offset'])
    if engine.read(64).hex()!=key['expected_hex']:raise ValueError('此版本的实体手柄方向键接口发生变化，未写入键位')
    key.pop('assembly',None);return [hook,key]
