"""Remove superseded imported libraries only after the new pointer is committed."""
from pathlib import Path
import json,re,shutil

def cleanup_old_libraries(store,home,current):
    root=store.root/'game-databases';current=Path(current).resolve();home=Path(home)
    result={'databases':0,'cache_versions':0,'warnings':[]};names=set()
    if not root.is_dir():return result
    active=json.loads((store.root/'active-game.json').read_text(encoding='utf8'))
    if (root/active['database']).resolve()!=current:raise ValueError('新数据库尚未切换，未清理旧库')
    keep=json.loads((current/'native-resource-profile.json').read_text(encoding='utf8')).get('cache_namespace')
    for old in list(root.iterdir()):
        if old.resolve()==current or not re.fullmatch('[a-f0-9]{24}',old.name):continue
        if old.is_symlink() or old.is_junction() or old.resolve().parent!=root.resolve():continue
        if not (old/'import-report.json').is_file():continue
        try:
            if json.loads((old/'import-report.json').read_text(encoding='utf8')).get('format')!='player-studio-apk-database-v1':continue
            namespace=json.loads((old/'native-resource-profile.json').read_text(encoding='utf8')).get('cache_namespace')
            shutil.rmtree(old);result['databases']+=1
            if namespace and namespace!=keep and re.fullmatch('[A-Za-z0-9_-]+',namespace):names.add(namespace)
        except (OSError,ValueError) as exc:result['warnings'].append(old.name+'：'+str(exc))
    versions=home/'library/versions'
    for namespace in names:
        cache=versions/namespace
        try:
            if cache.exists() and not cache.is_symlink() and not cache.is_junction() and cache.resolve().parent==versions.resolve():
                shutil.rmtree(cache);result['cache_versions']+=1
            index=store.root/('native-cache-'+namespace+'.json')
            if index.is_file() and not index.is_symlink():index.unlink()
        except OSError as exc:result['warnings'].append(namespace+'：'+str(exc))
    return result
