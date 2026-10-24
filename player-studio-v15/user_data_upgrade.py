"""Import the latest V13 studio state once, retaining content-addressed assets.

The V13 installation and its signed APKs stay usable. Temporary build files,
running sessions and browser profiles do not belong in the new installation.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import uuid

def refresh_v13_designs(source,destination):
    """Copy later V13 designs, preserving any independently edited V14 file.

    Only design assets, saved players/coaches, packs and progress snapshots are
    eligible. Native caches, live state and signing material remain version local.
    """
    source,destination=Path(source).resolve(),Path(destination).resolve()
    marker=destination/'imported-from-v13.json'
    if source==destination or not marker.is_file():raise ValueError('请先完成首次 V13 数据导入')
    baseline=json.loads(marker.read_text(encoding='utf8'));previous=baseline.get('files',{})
    report={'copied':[],'unchanged':[],'preserved_v14_edits':[],'source':str(source),'verified':False}
    plan=[]
    for p in source.rglob('*'):
        if not p.is_file() or p.is_symlink():continue
        rel=p.relative_to(source);key=rel.as_posix()
        allowed=(rel.parts[0] in ('assets','players','coaches') or key in ('current-project.json','packs.json')
                 or (rel.parts[0]=='exports' and p.suffix in ('.efplayer','.efproject','.efsave')))
        if not allowed or p.suffix=='.tmp':continue
        content=p.read_bytes();digest=hashlib.sha256(content).hexdigest();target=destination/rel
        if target.is_file():
            current=hashlib.sha256(target.read_bytes()).hexdigest()
            if current==digest:
                previous[key]={'sha256':digest,'bytes':len(content)}
                report['unchanged'].append(key);continue
            if current!=previous.get(key,{}).get('sha256'):
                if rel.parts[0]=='assets':raise ValueError('新旧版本同名资源不同，未同步：'+key)
                report['preserved_v14_edits'].append(key);continue
        # Snapshot once, then verify the source stayed unchanged during planning.
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('V13 正在修改文件，请稍后重新同步：'+key)
        plan.append((key,target,content,digest))
    backup=destination/'backups'/('同步V13前-'+uuid.uuid4().hex)
    for key,target,content,digest in plan:
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            old=backup/key;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,old)
        temp=target.with_name(target.name+'.sync-'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_bytes(content)
            if hashlib.sha256(temp.read_bytes()).hexdigest()!=digest:raise ValueError('同步资源校验失败：'+key)
            os.replace(temp,target)
        finally:temp.unlink(missing_ok=True)
        previous[key]={'sha256':digest,'bytes':len(content)};report['copied'].append(key)
    report['verified']=True
    temp=marker.with_suffix('.tmp');temp.write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,marker)
    (destination/'last-v13-design-sync.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return report


def import_v13_data(source,destination):
    source,destination=Path(source),Path(destination)
    marker=destination/'imported-from-v13.json'
    if marker.is_file() or (destination/'current-project.json').is_file():return None
    if not (source/'current-project.json').is_file():return None
    if source.resolve()==destination.resolve():raise ValueError('新旧版本的数据目录必须分开')
    staging=destination.with_name(destination.name+'-import-'+uuid.uuid4().hex)
    staging.mkdir(parents=True)
    report={'format':'player-studio-v13-to-v14-v1','files':{},'source':str(source.resolve())}
    try:
        for p in source.rglob('*'):
            rel=p.relative_to(source)
            if any(part in ('tmp','browser','__pycache__') for part in rel.parts):continue
            if not p.is_file() or p.name in ('runtime.json','studio.log') or p.suffix=='.tmp':continue
            if 'exports' in rel.parts and p.suffix=='.apk':continue
            target=staging/rel;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,target)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                raise ValueError('V13 数据导入校验失败：'+str(rel))
            report['files'][rel.as_posix()]={'sha256':digest,'bytes':target.stat().st_size}
        report['verified']=True
        (staging/'imported-from-v13.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if destination.exists():
            if any(destination.iterdir()):raise ValueError('V14 数据目录已有内容，未覆盖现有数据')
            destination.rmdir()
        os.replace(staging,destination)
        return report
    finally:
        if staging.exists():
            resolved=staging.resolve();parent=destination.parent.resolve()
            if resolved.parent!=parent or not resolved.name.startswith(destination.name+'-import-') or staging.is_symlink():
                raise ValueError('导入临时目录不在预期位置，未清理：'+str(staging))
            shutil.rmtree(resolved)
