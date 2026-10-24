"""Portable, per-export game display and physical-controller preferences."""
import copy,json,struct
from pathlib import Path

BUTTONS=['A','B','X','Y','LB','RB','LT','RT','LS','RS','SELECT','START','UP','DOWN','LEFT','RIGHT']
LABELS={'A':'A / ×','B':'B / ○','X':'X / □','Y':'Y / △','LB':'LB / L1','RB':'RB / R1','LT':'LT / L2','RT':'RT / R2','LS':'左摇杆按下','RS':'右摇杆按下','SELECT':'返回 / Share','START':'菜单 / Options','UP':'方向上','DOWN':'方向下','LEFT':'方向左','RIGHT':'方向右'}
ACTION_LABELS={'A':'短传 / 施压','B':'长传 / 传中','X':'射门','Y':'直塞','LB':'切换球员 / 辅助跑位','RB':'辅助施压 / 控制射门','LT':'紧密盘带 / 防守对位','RT':'冲刺 / 紫色射门','LS':'左摇杆按下','RS':'右摇杆按下','SELECT':'返回','START':'暂停','UP':'战术：上','DOWN':'战术：下','LEFT':'战术：左','RIGHT':'战术：右'}

def preset(name='default'):
    if name not in ('default','fc'):raise ValueError('未知手柄预设')
    inputs={k:[k] for k in BUTTONS}
    if name=='fc':inputs.update(X=['B'],B=['X'],LT=['RB'],RB=['LT'])
    result=[{'id':k,'label':ACTION_LABELS[k],'input':inputs[k],'output':[k]} for k in BUTTONS]
    result.extend([{'id':'finesse','label':'搓射 / 控制射门','input':['RB','B'] if name=='fc' else ['RB','X'],'output':['RB','X']},
                   {'id':'cancel','label':'超级取消','input':['LT','RT'] if name=='fc' else ['RB','RT'],'output':['RB','RT']},
                   {'id':'chip','label':'挑射','input':['LB','B'] if name=='fc' else ['LB','X'],'output':['LB','X']}])
    return result

DEFAULTS={'frame_rate':{'enabled':False,'target':160},'display':{'enabled':False,'height':1080},'card_motion':{'enabled':True},
          'controller':{'enabled':False,'preset':'default','mapping_revision':2,'bindings':preset(),'swap_sticks':False,'invert_right_y':False}}

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
    if body.get('controller',{}).get('preset')=='fc' and body['controller'].get('mapping_revision',0)<2:c['bindings']=preset('fc')
    c['mapping_revision']=2
    if c['preset'] not in ('default','fc','custom'):raise ValueError('手柄预设无效')
    for key in ('swap_sticks','invert_right_y'):
        if type(c[key]) is not bool:raise ValueError('摇杆设置无效')
    rows=c['bindings']
    if not isinstance(rows,list) or len(rows)!=len(preset()):raise ValueError('手柄绑定数量无效')
    expected={r['id']:r for r in preset()};seen=set();normalized=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('id') not in expected or row['id'] in seen:raise ValueError('手柄动作重复或无效')
        seen.add(row['id']);source=row.get('input')
        if not isinstance(source,list) or len(source)>3 or len(set(source))!=len(source) or any(k not in BUTTONS for k in source):raise ValueError('每个动作可绑定 0–3 个不同手柄按键')
        normalized.append({**expected[row['id']],'input':list(source)})
    # Identical input combinations would trigger unrelated actions together.
    used={}
    for row in normalized:
        source=tuple(sorted(row['input'],key=BUTTONS.index))
        if source and source in used:raise ValueError('按键冲突：'+used[source]+' 与 '+row['label'])
        if source:used[source]=row['label']
    c['bindings']=normalized
    return out

def settings(store,body=None):
    path=store.root/'game-settings.json'
    if body is None:return normalize(json.loads(path.read_text(encoding='utf8'))) if path.is_file() else copy.deepcopy(DEFAULTS)
    value=normalize(body);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path);return value

def schema():return {'buttons':[{'id':k,'label':LABELS[k]} for k in BUTTONS],'presets':{k:preset(k) for k in ('default','fc')}}

def controller_table(controller):
    rows=[r for r in controller['bindings'] if r['input']]
    rows.sort(key=lambda r:-len(r['input']))
    def mask(keys):return sum(1<<BUTTONS.index(k) for k in keys)
    result=bytearray()
    for row in rows:
        source=(1 if row['input']==['LT'] else 2 if row['input']==['RT'] else 0)
        result.extend(struct.pack('<IIII',mask(row['input']),mask(row['output']),source if row['output']==['LT'] else 0,source if row['output']==['RT'] else 0))
    return bytes(result)+bytes(16)

def controller_hooks(controller,engine,resources=None):
    if not controller['enabled']:return []
    path=(Path(resources) if resources else Path(__file__).parent/'resources')/'native-controller.json'
    data=json.loads(path.read_text(encoding='utf8'));hook=copy.deepcopy(data['hook']);engine.seek(hook['file_offset'])
    if engine.read(64).hex()!=hook['expected_hex']:raise ValueError('此版本的实体手柄输入接口发生变化，未写入键位')
    body=bytearray.fromhex(hook['body_hex']);table=controller_table(controller)
    body[data['table_offset']:data['table_offset']+len(table)]=table
    def axis_source(target):
        row=next(r for r in controller['bindings'] if r['id']==target)
        return 1 if row['input']==['LT'] else 2 if row['input']==['RT'] else 0
    struct.pack_into('<IIII',body,data['options_offset'],int(controller['swap_sticks']),int(controller['invert_right_y']),axis_source('LT'),axis_source('RT'))
    hook['body_hex']=body.hex();hook.pop('assembly',None)
    key=copy.deepcopy(data['key_hook']);engine.seek(key['file_offset'])
    if engine.read(64).hex()!=key['expected_hex']:raise ValueError('此版本的实体手柄方向键接口发生变化，未写入键位')
    key.pop('assembly',None);return [hook,key]
