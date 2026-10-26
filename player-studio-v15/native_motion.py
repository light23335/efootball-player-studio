"""Per-card posture inheritance from the native 400-byte player record."""
from pathlib import Path
import copy,json,os,threading,uuid

FIELDS={'52':(563,3,4),'53':(347,4,9),'54':(569,3,4),'55':(380,4,9)}

def parameters(value):
    if not isinstance(value,dict) or set(value)!=set(FIELDS):raise ValueError('动作组合不完整，请重新选择来源或预设')
    if any(type(value[k]) is not int or not 0<=value[k]<=limit for k,(_,_,limit) in FIELDS.items()):raise ValueError('动作参数超出当前原生范围')
    return dict(value)

def normalize(value):
    if value is None:return None
    if not isinstance(value,dict) or value.get('mode') not in ('legacy','source','custom'):raise ValueError('动作风格格式无效')
    out={'version':1,'mode':value['mode']}
    if out['mode']=='legacy':return out
    out['parameters']=parameters(value.get('parameters'))
    for key in ('source_id','source_name','label','preset_id','period'):
        text=value.get(key,'')
        if not isinstance(text,str) or len(text)>120:raise ValueError('动作风格文字过长或格式无效')
        out[key]=text
    if out['source_id'] and (not out['source_id'].isascii() or not out['source_id'].isdigit()):raise ValueError('动作来源编号无效')
    if value.get('original_parameters') is not None:out['original_parameters']=parameters(value['original_parameters'])
    return out

def from_player(row):
    try:raw=bytes.fromhex(row.get('payload',{}).get('_studio_client_record',''))
    except (ValueError,TypeError):raise ValueError('来源球员缺少原生记录，请重新导入当前游戏数据库') from None
    if len(raw)!=400:raise ValueError('来源球员缺少当前版本的400字节原生记录')
    bits=int.from_bytes(raw,'little');values={k:(bits>>bit)&((1<<width)-1) for k,(bit,width,_) in FIELDS.items()}
    return normalize({'mode':'source','source_id':str(row['id']),'source_name':row['name'],'label':row['name'],
                      'parameters':values,'original_parameters':values})

def apply_definition(project,definition):
    selected=normalize(project.get('motion_style'))
    if not selected or selected['mode']=='legacy':return definition
    arrays=[definition['base_parameters'],definition['owned']['parameters'],definition['owned']['_careerplan_base_parameters']]
    if isinstance(definition.get('maximum_development',{}).get('parameters'),list):arrays.append(definition['maximum_development']['parameters'])
    for array in arrays:
        if len(array)!=147:raise ValueError('动作参数协议与当前游戏不兼容')
        for key,value in selected['parameters'].items():array[int(key)]=value
    definition['motion_style']=copy.deepcopy(selected)
    return definition

def patch_record(raw,project):
    selected=normalize(project.get('motion_style'))
    if not selected or selected['mode']=='legacy':return raw
    if len(raw)!=400:raise ValueError('动作原生记录布局不兼容')
    bits=int.from_bytes(raw,'little')
    for key,new in selected['parameters'].items():
        bit,width,_=FIELDS[key];mask=((1<<width)-1)<<bit;bits=(bits&~mask)|(new<<bit)
    return bits.to_bytes(400,'little')

class MotionPresets:
    def __init__(self,store):self.path=Path(store.root)/'motion-presets.json';self.lock=threading.RLock()
    def list(self):
        rows=json.loads(self.path.read_text(encoding='utf8')) if self.path.is_file() else []
        if not isinstance(rows,list) or len(rows)>200:raise ValueError('动作预设库格式无效，请保留文件并核对备份')
        return rows
    def save(self,body):
        label=body.get('label');style=normalize(body.get('style'))
        if not isinstance(label,str) or not label.strip() or len(label)>60 or not style or style['mode']=='legacy':raise ValueError('请先选择动作，并填写1至60字的预设名称')
        with self.lock:
            rows=self.list()
            if len(rows)>=200:raise ValueError('已保存200个动作预设')
            row={'id':str(uuid.uuid4()),'label':label.strip(),'style':style};rows.append(row)
            temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temporary,self.path)
            return {'row':row,'rows':rows}
