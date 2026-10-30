"""The current library's imported APKs are authoritative export inputs."""
from pathlib import Path
import hashlib,json,os,struct,uuid,zipfile

MARKERS={'apk':'assets/gateway-release/release-manifest.json','companion':'assets/resource-bootstrap/resources.zip'}
WORKSHOP_DOCUMENT='assets/gateway-release/custom-resources/personal-player-studio/players.json'


def _read(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def recorded(library,store):
    active=_read(store.root/'active-game.json')
    if active.get('apk') or active.get('companion'):return active
    release=getattr(library,'profile',{}).get('release_id')
    for folder,name in ((getattr(library,'resources',None),'import-report.json'),(getattr(library,'root',None),'ready.json')):
        if folder is None:continue
        row=_read(Path(folder)/name)
        if (row.get('apk') or row.get('companion')) and (not release or row.get('release_id')==release):return row
    return {}


def kind_matches(path,key):
    try:
        with zipfile.ZipFile(path) as archive:return MARKERS[key] in archive.namelist()
    except (OSError,ValueError,zipfile.BadZipFile):return False


def _mode_source(path):
    p=Path(path).absolute();stat=p.stat()
    return {'path':str(p),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}


def remember_mode(store,path,mode):
    """Remember a successful export's mode for this exact source and signer."""
    from apk_installation import local_certificate
    if mode not in ('coexist','update'):raise ValueError('安装方式无效')
    source=_mode_source(path);key=hashlib.sha256(os.path.normcase(source['path']).encode()).hexdigest()
    target=store.root/'installation-modes.json';value=_read(target)
    certificate=local_certificate(store);previous=value.get(key)
    if isinstance(previous,dict)and previous.get('source')==source and previous.get('signer')==certificate and previous.get('mode')in('coexist','update'):return
    value[key]={'source':source,'mode':mode,'signer':certificate}
    temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temp.replace(target)
    finally:temp.unlink(missing_ok=True)


def installation_guidance(path,store):
    """Inspect the selected library's APK, never an unrelated installed game."""
    from apk_installation import identity,local_certificate,GAME,COEXIST_GAME
    result={'recommended_mode':'coexist','reason':'尚未读取到可识别的主 APK；请先导入游戏库。',
            'source_path':str(path or ''),'package':None,'workshop':False,'signer_matches':False,'basis':'unavailable'}
    certificate=local_certificate(store);source=None;prior=None
    try:
        if not path:return result
        source=_mode_source(path)
        with zipfile.ZipFile(path)as archive:
            if MARKERS['apk']not in archive.namelist():return result
            workshop=WORKSHOP_DOCUMENT in archive.namelist()
        info=identity(path);matches=bool(certificate and certificate in info['signers'])
        key=hashlib.sha256(os.path.normcase(source['path']).encode()).hexdigest()
        prior=_read(store.root/'installation-modes.json').get(key)
        result.update(package=info['package'],workshop=workshop,signer_matches=matches)
        if info['package']==COEXIST_GAME:
            result.update(reason='当前库来自“工坊版”共存包，后续更新请继续使用共存模式。',basis='coexist_package')
            if not matches:result['reason']+='此包与本机签名不同，重新生成后不能直接覆盖原设备签名的安装。'
        elif info['package']!=GAME:
            result.update(reason='当前包名无法确认安装方式，建议先核对导入来源，再使用共存模式。',basis='unknown_package')
        elif workshop and not matches:
            result.update(reason='当前库来自其他签名的工坊包，可能由另一台设备或另一端工坊生成，推荐共存模式。',basis='foreign_signer')
        elif isinstance(prior,dict)and prior.get('source')==source and prior.get('signer')==certificate and certificate and prior.get('mode')in('coexist','update'):
            result.update(recommended_mode=prior['mode'],reason='此来源已成功生成过安装包，继续沿用首次选择的'+('共存模式。'if prior['mode']=='coexist'else'工坊更新模式。'),basis='successful_export')
        elif workshop and matches:
            result.update(recommended_mode='update',reason='当前库来自本机同签名、非共存的工坊包，推荐工坊更新模式。',basis='local_workshop')
        else:
            result.update(reason='当前库来自原版包。若要保留原版游戏，推荐共存模式；未安装原游戏但已有原版资源包，也可手动选择工坊更新模式。',basis='original')
    except (OSError,ValueError,KeyError,IndexError,struct.error,zipfile.BadZipFile):
        result.update(reason='无法完整读取当前来源的包名或签名，未认定可覆盖更新；请核对文件或重新导入。',basis='unreadable')
    finally:
        result['key']=hashlib.sha256(json.dumps([source,certificate,prior,result['recommended_mode']],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    return result


def resolve(library,store):
    row=recorded(library,store);home=Path(getattr(library,'home',store.root.parent));selected={};errors=[]
    names={'apk':'73efootball-'+getattr(library,'profile',{}).get('game_version','V17')+'.apk',
           'companion':'73efootball-离线资源包-V9+.apk'}
    for key in MARKERS:
        if row:
            # Keep a missing imported path visible. Never silently substitute
            # an unrelated installed base.apk after URI permission is lost.
            path=str(row.get(key) or '')
        else:
            candidates=[home/'原始APK'/names[key],home/names[key],home.parent/names[key]]
            path=next((str(p) for p in candidates if p.is_file() and kind_matches(p,key)),'')
        selected[key]=path
        if row and (not path or not Path(path).is_file()):
            errors.append(('主程序' if key=='apk' else '离线资源')+' APK 已移动或读取授权失效，请重新选择导入时使用的文件。')
        elif path and not kind_matches(path,key):
            errors.append(('主程序' if key=='apk' else '离线资源')+' APK 内容与导入记录不符，请重新选择对应文件。')
    key=hashlib.sha256(json.dumps([row.get('database'),*selected.values()],ensure_ascii=False).encode()).hexdigest()[:24]
    return dict(selected,source_key=key,recorded=bool(row),errors=errors,
                installation=installation_guidance(selected['apk'],store))
