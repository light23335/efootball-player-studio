"""Delete a local coach and its embedded project copies with recoverable backups."""
from pathlib import Path
import copy,json,os,uuid


def without_coach(project,coach_id,ident):
    result=copy.deepcopy(project)
    rows=result.get('custom_coaches',[])
    if not isinstance(rows,list):raise ValueError('工程教练资料无效')
    filtered=[c for c in rows if c.get('id')!=coach_id and c.get('uuid')!=ident]
    changed=len(filtered)!=len(rows)
    if changed:result['custom_coaches']=filtered
    if result.get('preview',{}).get('coach_id')==coach_id:
        result['preview']['coach_id']=None;changed=True
    return result,changed


def atomic(path,data):
    temp=path.with_name('.coach-delete-'+uuid.uuid4().hex)
    try:
        with temp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def delete_coach(store,ident,confirmed=False):
    if confirmed is not True:raise ValueError('请先确认删除这名自建教练')
    try:ident=str(uuid.UUID(ident))
    except (ValueError,TypeError,AttributeError):raise ValueError('只能删除自建教练') from None
    coach_id='custom:'+ident
    coach_path=store.coaches.root/(ident+'.json')
    with store.lock,store.coaches.lock:
        if coach_path.is_symlink():raise ValueError('教练文件不能是外部链接')
        local=coach_path.read_bytes() if coach_path.is_file() else None
        current,changed=without_coach(store.project,coach_id,ident)
        changes={};skipped=[];affected=0
        if changed:changes[store.project_path]=json.dumps(current,ensure_ascii=False,indent=2).encode('utf8')
        for path in sorted((store.root/'players').glob('*.json')):
            if path.is_symlink():skipped.append(path.name);continue
            try:
                if path.stat().st_size>8*1024*1024:raise ValueError('工程过大')
                entry=json.loads(path.read_text(encoding='utf8'))
                if entry.get('format')!='73efootball-saved-player' or entry.get('version')!=1:raise ValueError('工程格式无效')
                project=entry['project']
                if project.get('package_id')!=path.stem:raise ValueError('工程身份不一致')
                cleaned,used=without_coach(project,coach_id,ident)
            except (ValueError,KeyError,TypeError,AttributeError,OSError):skipped.append(path.name);continue
            if not used:continue
            # Recompute persisted score summaries after removing the preview coach.
            from overall import calculate
            import app
            entry['project']=cleaned;entry['overall']=calculate(cleaned,app.CATALOG);entry['saved_at']=app.migration.stamp()
            changes[path]=json.dumps(entry,ensure_ascii=False,indent=2).encode('utf8');affected+=1
        if local is None and not changes:raise ValueError('这名自建教练已不存在')
        originals={p:p.read_bytes() for p in changes}
        backup=store.root/'backups'/('deleted-coach-'+ident+'-'+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
        # Finish all backups before changing any live project or coach file.
        for path,data in originals.items():
            relative=path.relative_to(store.root);dest=backup/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        if local is not None:
            (backup/'coaches').mkdir(exist_ok=True);(backup/'coaches'/coach_path.name).write_bytes(local)
        written=[];removed=False
        try:
            for path,data in changes.items():atomic(path,data);written.append(path)
            if local is not None:coach_path.unlink();removed=True
        except Exception:
            for path in written:atomic(path,originals[path])
            if removed:atomic(coach_path,local)
            raise
        if changed:store.project=current
        return {'deleted':True,'uuid':ident,'coach_id':coach_id,'affected_projects':affected,
                'project':copy.deepcopy(store.project),'backup':str(backup),'unreadable_projects':skipped}
