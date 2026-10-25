"""The current library's imported APKs are authoritative export inputs."""
from pathlib import Path
import hashlib,json,zipfile

MARKERS={'apk':'assets/gateway-release/release-manifest.json','companion':'assets/resource-bootstrap/resources.zip'}


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
    return dict(selected,source_key=key,recorded=bool(row),errors=errors)
