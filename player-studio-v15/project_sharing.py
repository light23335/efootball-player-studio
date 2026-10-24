"""Portable multi-player projects with verified assets and collision-safe import."""
from pathlib import Path
import json,uuid

def export_selected(store,selected,current):
    import app
    if not isinstance(selected,list) or not 1<=len(selected)<=100 or len(set(selected))!=len(selected):raise ValueError('请选择 1–100 名球员')
    projects=[app.normalize_project(current) if uid==current['package_id'] else store.saved_player(uid)['project'] for uid in selected]
    files={'projects.json':json.dumps(projects,ensure_ascii=False,indent=2).encode()}
    for project in projects:
        for name in app.referenced_assets(project):
            path=store.root/'assets'/name
            if not path.is_file():raise ValueError(project['identity']['name']+'：工程引用的资源缺失')
            files['assets/'+name]=path.read_bytes()
    if sum(map(len,files.values()))>512*1024*1024:raise ValueError('工程包总大小超过 512 MB，请分批导出')
    manifest={'format':'73efootball-studio-project','version':2,'players':len(projects),'sha256':{k:app.migration.digest(v) for k,v in files.items()}}
    files['manifest.json']=app.migration.compact(manifest).encode()
    name='球员合集-'+str(len(projects))+'人-'+uuid.uuid4().hex[:8]+'.efproject';target=store.root/'exports'/name;target.write_bytes(app.migration.archive_bytes(files))
    return {'url':'/exports/'+name,'filename':name,'path':str(target),'players':len(projects)}

def import_selected(store,archive,manifest):
    import app
    expected=set(manifest['sha256'])|{'manifest.json'}
    if set(archive.namelist())!=expected or 'projects.json' not in expected:raise ValueError('工程合集清单不完整')
    files={}
    for name,digest in manifest['sha256'].items():
        raw=archive.read(name)
        if app.migration.digest(raw)!=digest:raise ValueError('工程合集校验失败：'+name)
        if name!='projects.json' and (not name.startswith('assets/') or not app.ASSET_ID.fullmatch(name[7:]) or len(raw)>app.MAX_ASSET or name[7:71]!=digest):raise ValueError('工程合集资源无效')
        files[name]=raw
    rows=app.migration.read_json(files['projects.json'])
    if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('工程合集人数无效')
    projects=[app.normalize_project(p) for p in rows]
    if len({p['package_id'] for p in projects})!=len(projects):raise ValueError('工程合集包含重复身份')
    for p in projects:
        if not p['identity']['name'].strip():raise ValueError('工程合集包含未命名球员')
        if any('assets/'+n not in files for n in app.referenced_assets(p)):raise ValueError('工程合集缺少球员资源')
        target=store._player_path(p['package_id'])
        if target.exists():
            old=store.saved_player(p['package_id'])['project']
            if old!=p:p['package_id']=str(uuid.uuid4());p['card_id']=None;p['serial']=0
    # Validation finishes before any local project or asset is changed.
    for name,raw in files.items():
        if name.startswith('assets/') and not (store.root/name).exists():(store.root/name).write_bytes(raw)
    if store.project['identity']['name'].strip():store.save_player(store.project)
    for p in projects:store.save_player(p)
    store.save(projects[0],manual=True)
    return projects[0]
