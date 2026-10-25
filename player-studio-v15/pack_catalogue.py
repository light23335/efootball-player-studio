"""Version-local exclusions declared by the game; never override its guards."""
from pathlib import Path
from functools import lru_cache
import json,zipfile
from studio_resources import bundled_resources

REFERENCE='assets/gateway-release/outputs/reference/excluded_card_catalog.json'

def blocked_only(rows):
    # The user allows China-edition cards; all other stock exclusions stay.
    return {cid:row for cid,row in rows.items() if row.get('reason')!='China edition'}

def catalogue_from_archive(archive):
    if REFERENCE not in archive.namelist():return {}
    rows=json.loads(archive.read(REFERENCE))
    if not isinstance(rows,dict):raise ValueError('APK 的禁用卡目录格式改变')
    return {str(cid):{'name':str(row.get('name') or cid),'reason':str(row.get('type') or row.get('version_label') or '当前版本禁用')}
            for cid,row in rows.items()}

def from_archive(archive):return blocked_only(catalogue_from_archive(archive))

@lru_cache(maxsize=8)
def _apk(path,mtime,size):
    with zipfile.ZipFile(path) as archive:return from_archive(archive)

def exclusions(resources):
    resources=Path(resources);path=resources/'pack-exclusions.json'
    if path.is_file():return blocked_only(json.loads(path.read_text(encoding='utf8')))
    # Existing imported catalogues predate this file. Read their exact APK,
    # without migrating or rewriting the user's saved catalogue.
    pointer=resources.parent.parent/'active-game.json'
    if pointer.is_file():
        source=Path(json.loads(pointer.read_text(encoding='utf8')).get('apk',''))
        if source.is_file():
            s=source.stat();return _apk(str(source),s.st_mtime_ns,s.st_size)
    bundled=bundled_resources()
    if resources!=bundled and (bundled/'pack-exclusions.json').is_file():
        try:
            old=json.loads((resources/'native-resource-profile.json').read_text(encoding='utf8'))
            new=json.loads((bundled/'native-resource-profile.json').read_text(encoding='utf8'))
            if old['native_engine_sha256']==new['native_engine_sha256']:
                return blocked_only(json.loads((bundled/'pack-exclusions.json').read_text(encoding='utf8')))
        except (OSError,KeyError):pass
    return {}
