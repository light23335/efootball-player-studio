"""Reversible catalogue exclusions; projects and shared art are never deleted."""
from pathlib import Path
import collections,contextlib,copy,hashlib,json,os,re,sqlite3,time,zipfile

REASON='Workshop recycle bin'

def load(store):
    path=store.root/'catalogue-trash.json'
    if not path.is_file():return {}
    document=json.loads(path.read_text('utf8'))
    if document.get('format')!='studio-catalogue-trash-v1' or not isinstance(document.get('items'),dict):raise ValueError('球员回收站记录无效，原文件已保留')
    return document['items']

def active(store):return {cid:r for cid,r in load(store).items()if r.get('trashed')}

def change(library,body):
    ids=body.get('ids');restore=body.get('action')=='restore'
    if body.get('action')not in ('trash','restore') or not isinstance(ids,list)or not 1<=len(ids)<=10000 or any(not re.fullmatch('[0-9]{1,16}',str(cid)) for cid in ids):raise ValueError('请选择 1–10000 名球员移入或恢复')
    ids=list(dict.fromkeys(str(int(cid)) for cid in ids));store=library.store
    with store.lock:
        items=load(store);snapshots={}
        if not restore:
            with contextlib.closing(library.db())as db:
                for cid in ids:
                    row=db.execute('select * from players where id=?',(cid,)).fetchone()
                    if not row:raise ValueError('球员不在当前资源库：'+cid)
                    snapshots[cid]=dict(row)
            from apk_sources import recorded
            source=Path(recorded(library,store).get('apk',''))
            native={cid:{} for cid in ids}
            if source.is_file():
                from native_cpk import Cpk,unwrap
                from content_delta import CPKS,TABLES
                with zipfile.ZipFile(source)as archive:
                    cpk=Cpk(archive.read(CPKS[1]))
                    for name,(size,offset)in TABLES.items():
                        data=unwrap(cpk.read(name))
                        for at in range(0,len(data),size):
                            cid=str(int.from_bytes(data[at+offset:at+offset+8],'little'))
                            if cid in native:native[cid][name]=data[at:at+size].hex()
            for cid in ids:
                items[cid]={**items.get(cid,{}),'id':cid,'name':snapshots[cid]['name'],'snapshot':snapshots[cid],
                            'native_records':native[cid]or items.get(cid,{}).get('native_records',{}),'trashed':True,'changed_at':int(time.time())}
        else:
            for cid in ids:
                if cid not in items:raise ValueError('球员不在回收站记录：'+cid)
                items[cid].update(trashed=False,changed_at=int(time.time()))
        path=store.root/'catalogue-trash.json';temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps({'format':'studio-catalogue-trash-v1','items':items},ensure_ascii=False,indent=2),'utf8');os.replace(temp,path)
    return {'changed':len(ids),'trashed':sum(bool(r.get('trashed'))for r in items.values()),'message':'已恢复；下次生成重新允许此卡'if restore else'已移入回收站；原资料保留，下次生成排除此卡'}

def policy(store):return [{'id':cid,'name':r['name']}for cid,r in active(store).items()]

def patch_tables(raw,store,restore_only=False):
    from content_delta import TABLES
    from native_cpk import Cpk,unwrap,wrap
    items=load(store)
    if not items:return raw
    source=Cpk(raw);replacements={}
    for name,(size,offset)in TABLES.items():
        wrapped=source.read(name);data=unwrap(wrapped)
        rows={str(int.from_bytes(data[at+offset:at+offset+8],'little')):data[at:at+size]for at in range(0,len(data),size)}
        for cid,item in items.items():
            if item['trashed']:
                if not restore_only:rows.pop(cid,None)
            elif cid not in rows and item.get('native_records',{}).get(name):
                row=bytes.fromhex(item['native_records'][name])
                if len(row)!=size or str(int.from_bytes(row[offset:offset+8],'little'))!=cid:raise ValueError('恢复原生资料的编号不符：'+cid)
                rows[cid]=row
        result=b''.join(rows[cid]for cid in sorted(rows,key=int))
        if result!=data:replacements[name]=wrap(result,wrapped)
    return source.replace(replacements)if replacements else raw

def patch_seed(archive,store):
    name='assets/gateway-release/outputs/efootball/local-club.sqlite3';items=load(store)
    if not items:return {}
    db=sqlite3.connect(':memory:')
    try:
        db.deserialize(archive.read(name))
        with db:
            for cid,item in items.items():
                if item['trashed']:
                    db.execute('delete from managed_cards where card_id=?',(cid,))
                    if db.execute("select 1 from sqlite_master where name='managed_members'").fetchone():db.execute('delete from managed_members where card_id=?',(cid,))
                else:
                    row=item['snapshot'];p=json.loads(row['payload']);text=json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                    db.execute('insert or ignore into managed_cards values(?,?,?,?,?,?)',(cid,hashlib.sha256(text.encode()).hexdigest(),text,row['card_type'],None,'studio-recycle-restored'))
            from personal_runtime import remove_recycled_owned
            remove_recycled_owned(db,{cid for cid,r in items.items()if r['trashed']})
        if db.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('回收站处理后的种子库校验失败')
        return {name:db.serialize()}
    finally:db.close()

def restore_catalogue(resources,store):
    """Keep even removed source records available to browse/restore locally."""
    items=load(store)
    if not items:return
    db=sqlite3.connect(Path(resources)/'library.sqlite3')
    try:
        with db:
            for cid,item in items.items():
                row=item['snapshot'];keys=list(row)
                db.execute('insert or ignore into players('+','.join(keys)+') values('+','.join('?'for _ in keys)+')',[row[k]for k in keys])
    finally:db.close()
