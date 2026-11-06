"""Independent animated heads for personal coaches, using the native ID resolver."""
from export_errors import call as _export_data
from export_errors import export_context, exported
from pathlib import Path
import copy,hashlib,json,os,re,threading,uuid
from coach_heads import FOLDER,TARGET,ASSET,target_path,compile_head,original,preview,require_path

PREFIXES=('', 'sp', 'im', 'motm', 'ml')
DEFAULT_TEMPLATE=FOLDER+'SK_437sp00v0039_Face.uasset'
_STORE_LOCK=threading.RLock()


class CoachModelStore:
    """Stock-coach edits, explicitly saved by coach identity. Legacy rows stay inert."""
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'coach-models.json'

    @staticmethod
    def normalize(value):
        from coach_heads import normalize as normalize_head
        if not isinstance(value,dict):raise ValueError('原版教练头模编辑无效')
        ident=str(value.get('coach_id',''))
        if not ident.isascii() or not ident.isdecimal() or not 0<int(ident)<1<<63:raise ValueError('请选择一名原版教练')
        return dict(normalize_head(value),coach_id=str(int(ident)),name=str(value.get('name') or ident)[:80])

    def list(self):
        with _STORE_LOCK:
            if not self.path.exists():return []
            doc=json.loads(self.path.read_text(encoding='utf8'))
            if not isinstance(doc,dict) or doc.get('version')!=1 or not isinstance(doc.get('rows'),list):raise ValueError('逐名教练头模配置版本无效')
            rows=[self.normalize(r) for r in doc['rows']]
            if len({r['coach_id'] for r in rows})!=len(rows):raise ValueError('逐名教练头模配置包含重复教练')
            return rows

    def _write(self,rows):
        if self.path.exists():
            backup=self.root/'backups';backup.mkdir(exist_ok=True)
            (backup/('coach-models-'+uuid.uuid4().hex+'.json')).write_bytes(self.path.read_bytes())
        temporary=self.path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('w',encoding='utf8') as f:
            json.dump({'version':1,'rows':rows},f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        temporary.replace(self.path)

    def save(self,value,overwrite=True):
        row=self.normalize(value)
        with _STORE_LOCK:
            rows=self.list()
            if not overwrite and any(r['coach_id']==row['coach_id'] for r in rows):raise ValueError('这名教练已有独立编辑，未覆盖；请直接编辑当前头模')
            self._write([r for r in rows if r['coach_id']!=row['coach_id']]+[row])
        return row

    def delete(self,ident):
        with _STORE_LOCK:self._write([r for r in self.list() if r['coach_id']!=str(ident)])


def stock_coach(library,coach,catalog):
    if not isinstance(coach,dict) or coach.get('type')=='custom':raise ValueError('请选择一名原版教练编辑头模')
    row=next((r for r in catalog if str(r['id'])==str(coach.get('id'))),None)
    if row is None:raise ValueError('当前资料库没有这名原版教练')
    found=template(library,row['id'])
    if not found['available']:raise ValueError(found['message'])
    return row,found['template_path']


def save_stock(library,coach,head,catalog,migrate=False):
    from coach_heads import CoachHeadStore,normalize as normalize_head
    coach,path=stock_coach(library,coach,catalog);store=CoachModelStore(library.store.root)
    if migrate:
        if any(r['coach_id']==str(coach['id']) or r['target']==path for r in store.list()):raise ValueError('这名教练或共用目标已有独立编辑，未覆盖')
        head=next((r for r in CoachHeadStore(library.store.root).list() if r['target']==path),None)
        if head is None:raise ValueError('此教练没有目标完全匹配的旧方案，请直接导入 GLB')
    head=normalize_head(head)
    if head['target']!=path:raise ValueError('头模目标与当前所选教练不一致，请重新打开这名教练')
    result=preview(library,head)
    result['head']=store.save(dict(head,coach_id=str(coach['id']),name=coach['name']),overwrite=not migrate)
    return result


def delete_stock(library,coach,catalog):
    coach,_=stock_coach(library,coach,catalog)
    CoachModelStore(library.store.root).delete(coach['id'])
    return {'deleted':True}


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
    if 'preserve_expression'in value:
        if type(value['preserve_expression'])is not bool:raise ValueError('保持导入表情必须为开关值')
        row['preserve_expression']=value['preserve_expression']
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
        config={'target':head['template_path'],'mode':'custom','asset_id':head['asset_id']}
        if 'preserve_expression'in head:config['preserve_expression']=head['preserve_expression']
        return preview(library,config)
    from coach_heads import with_expression_preview
    return with_expression_preview(original(library,head['template_path']))


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
    path=found['template_path']
    rows=CoachModelStore(library.store.root).list()
    replacement=next((r for r in rows if r['coach_id']==str(coach['id'])),None)
    stale=bool(replacement and replacement['target']!=path)
    if stale:replacement=None  # Keep the old row; let the selected editor repair it explicitly.
    shared=[r for r in rows if r['target']==path and r['coach_id']!=str(coach['id'])]
    effective=replacement or next(iter(shared),None)
    result=preview(library,effective) if effective else original(library,path)
    # Reading a legacy candidate for an explicit migration never activates it.
    from coach_heads import CoachHeadStore
    try:legacy=next((r for r in CoachHeadStore(library.store.root).list() if r['target']==path),None)
    except (ValueError,OSError):legacy=None
    return dict(result,template_path=path,personal=False,replacement=replacement,effective_replacement=effective,
                shared_with=[r['name'] for r in shared],stale_replacement=stale,legacy_available=bool(legacy and not effective and not stale))


def compile_stock_models(library,rows,catalog):
    art=[];reports=[]
    for value in rows:
        row=CoachModelStore.normalize(value)
        with export_context('教练',dict(row,id=row['coach_id']),'编译所选原版教练的头模编辑'):
            coach,path=stock_coach(library,{'id':row['coach_id']},catalog)
            if row['target']!=path:raise ValueError('已保存目标与当前原版教练资源不一致，请重新打开该教练编辑')
            packages,report,_,_=compile_head(library,row)
            report.update(coach_id=str(coach['id']),name=coach['name'],source='per-coach-editor',packages=[p[0] for p in packages])
            art.extend(packages);reports.append(report)
    return art,reports


def collect_head_resources(personal,personal_reports,stock,stock_reports):
    from native_body import deduplicate_art
    owners=[]
    for art,reports,kind in ((personal,personal_reports,'自建教练'),(stock,stock_reports,'原版教练')):
        for name,_,_ in art:
            matches=[r for r in reports if name in r.get('packages',[])]
            owners.append('、'.join(kind+'「'+r.get('name','未命名')+'」['+str(r.get('id',r.get('coach_id',r.get('uuid','?'))))+']' for r in matches) or kind)
    return deduplicate_art(personal+stock,owners)


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
            if 'preserve_expression'in head:config['preserve_expression']=head['preserve_expression']
            packages,report,_,_=compile_head(library,config,destination=name)
            paths=[p[0] for p in packages]
            if name not in paths:raise ValueError('个人教练模型缺少原生加载目标')
            report.update(uuid=coach['uuid'],id=ident,name=coach['name'],model_key=key,model_path=name,
                          template_path=head['template_path'],independent=True,packages=paths,
                          animation='template skeleton and offsets retained; '+('imported expression protected'if head.get('preserve_expression',False)else'compatible imported facial weights preserved'))
            art.extend(packages);reports.append(report)
    return art,reports
