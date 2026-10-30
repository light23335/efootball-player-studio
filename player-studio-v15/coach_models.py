"""Independent animated heads for personal coaches, using the native ID resolver."""
from export_errors import call as _export_data
from export_errors import export_context, exported
from pathlib import Path
import copy,hashlib,json,re
from coach_heads import FOLDER,TARGET,ASSET,target_path,compile_head,original,preview,require_path

PREFIXES=('', 'sp', 'im', 'motm', 'ml')
DEFAULT_TEMPLATE=FOLDER+'SK_437sp00v0039_Face.uasset'


def native_key(ident):
    """V17 manager branch at 0x3a84b08: low 22-bit person + type/subtype/version."""
    ident=int(ident)
    if not 0<ident<1<<63 or ident&(1<<23):raise ValueError('教练编号不能生成三维模型路径')
    person=ident&0xffff0000003fffff;kind=ident>>44&15
    if kind in (0,15):return str(person)
    if kind>=len(PREFIXES):raise ValueError('此教练类型的三维命名尚未核对')
    return f'{person}{PREFIXES[kind]}{ident>>40&15:02d}v{ident>>28&4095:04d}'


def normalize(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('教练三维头模设置无效')
    row={'template_path':target_path(value.get('template_path'))}
    asset=value.get('asset_id')
    if asset is not None:
        if not isinstance(asset,str) or not ASSET.fullmatch(asset):raise ValueError('教练头模需要内嵌贴图的 GLB')
        row['asset_id']=asset
    return row


def template(library,source_id,allow_default=False):
    if library.state['phase']!='ready':return {'ready':False,'available':False,'message':'请先准备游戏资源，才能读取教练原版头模。'}
    if allow_default:
        exact=template(library,source_id) if source_id else {'available':False}
        if exact['available']:return exact
        paths={p.removeprefix('../../../') for p in library.face_assets().files}
        found=next((p for p in (DEFAULT_TEMPLATE,*sorted(paths)) if TARGET.fullmatch(p) and p in paths),None)
        if found:return {'ready':True,'available':True,'template_path':found,'default':True,'message':'使用默认教练头模，可直接导入自己的 GLB 替换。'}
        return {'ready':True,'available':False,'message':'当前资源中没有可用的教练头模，请先导入完整游戏资源。'}
    if not source_id:return {'ready':True,'available':False,'message':'请从有三维头模的原版教练复制。'}
    try:key=native_key(source_id)
    except (ValueError,TypeError):return {'ready':True,'available':False,'message':'此原版教练类型尚无可读取的三维头模。'}
    path=FOLDER+'SK_'+key+'_Face.uasset'
    # Native resolver checks the exact model first, then the plain person key.
    fallback=FOLDER+'SK_'+str(int(source_id)&0xffff0000003fffff)+'_Face.uasset'
    files=library.face_assets().files
    found=next((p for p in (path,fallback) if '../../../'+p in files),None)
    if not found:return {'ready':True,'available':False,'message':'此原版教练没有可读取的独立三维头模，请选择“只看有三维头模”的原版教练。'}
    return {'ready':True,'available':True,'template_path':found,'source_id':str(source_id)}


def prepare(coach,library):
    result=copy.deepcopy(coach);head=normalize(result.get('head_model'))
    if head is None:
        found=template(library,result.get('native_source_id'),allow_default=True)
        if found['available']:head={'template_path':found['template_path']}
    if head:require_path(library,head['template_path'])
    result['head_model']=head
    return result


def preview_coach(library,value):
    head=normalize(value)
    if not head:raise ValueError('尚未选择原版教练头模模板')
    if head.get('asset_id'):
        return preview(library,{'target':head['template_path'],'mode':'custom','asset_id':head['asset_id']})
    return original(library,head['template_path'])


def current(library,coach):
    """Resolve the same saved configuration used by export, before decoding it."""
    if not isinstance(coach,dict):raise ValueError('请选择一名教练')
    if coach.get('type')=='custom' or str(coach.get('id','')).startswith('custom:'):
        head=prepare(coach,library).get('head_model')
        if not head:raise ValueError('请先准备完整游戏资源，再查看默认教练头模')
        result=preview_coach(library,head)
        return dict(result,template_path=head['template_path'],head_model=head,personal=True)
    found=template(library,coach.get('id'))
    if not found['available']:raise ValueError(found['message'])
    from coach_heads import CoachHeadStore
    path=found['template_path']
    replacement=next((r for r in CoachHeadStore(library.store.root).list() if r['target']==path),None)
    result=preview(library,replacement) if replacement else original(library,path)
    return dict(result,template_path=path,personal=False,replacement=replacement)


def verify_loader(engine,resources=None):
    from studio_resources import bundled_resources
    path=Path(resources or bundled_resources())/'native-coach-model-loader.json'
    info=_export_data("资料文件",path,"读取并解析 JSON",lambda: json.loads(path.read_text(encoding='utf8')))
    for region in info['regions']:
        engine.seek(region['file_offset']);raw=engine.read(region['bytes'])
        if hashlib.sha256(raw).hexdigest()!=region['sha256']:raise ValueError('此版本的教练模型加载接口已变化，未写入独立头模')
    return {'resolver_address':info['resolver_address'],'native_id_to_path_verified':True,'engine_patched':False}


def compile_models(library,coaches,definitions,replace_ids=()):
    if len(coaches)!=len(definitions):raise ValueError('个人教练与原生编号定义数量不一致')
    art=[];reports=[];seen=set()
    for coach,definition in zip(coaches,definitions):
        with export_context('教练',coach,'编译独立三维头模'):
            coach=prepare(coach,library);head=coach.get('head_model')
            if not head:continue
            ident=definition['id']
            if type(ident) is not int or not 600000<=ident<1000000:raise ValueError('个人教练编号不在已核对的独立模型范围内')
            key=native_key(ident);name='/Game/Assets/character/DemoFace/Manager/SK_'+key+'_Face'
            file='../../../PesMobile/Content/'+name[6:]+'.uasset'
            if file in library.face_assets().files and ident not in replace_ids:raise ValueError('个人教练模型路径与现有资源冲突')
            if name in seen:raise ValueError('个人教练模型目标重复')
            seen.add(name)
            config={'target':head['template_path'],'mode':'custom','asset_id':head['asset_id']} if head.get('asset_id') else {'target':head['template_path'],'mode':'native','source':head['template_path']}
            packages,report,_,_=compile_head(library,config,destination=name)
            paths=[p[0] for p in packages]
            if name not in paths:raise ValueError('个人教练模型缺少原生加载目标')
            report.update(uuid=coach['uuid'],id=ident,name=coach['name'],model_key=key,model_path=name,
                          template_path=head['template_path'],independent=True,packages=paths,
                          animation='template skeleton and offsets retained; compatible imported facial weights preserved')
            art.extend(packages);reports.append(report)
    return art,reports
