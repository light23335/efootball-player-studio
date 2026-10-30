"""Durable partial editor drafts, independent from valid exportable records."""
import copy
import json
import os
import time
import uuid

CATEGORIES={'coach','pack','settings','progress'}


def listing(store):
    path=store.root/'editor-drafts.json'
    with store.lock:
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}


def update(store,category,value,commit=True):
    if category not in CATEGORIES:raise ValueError('未知编辑草稿')
    if value is not None and not isinstance(value,dict):raise ValueError('编辑草稿须为对象')
    key=str(uuid.UUID(value['uuid'])) if category in ('coach','pack') and value else category
    if len(json.dumps(value).encode())>2*1024*1024:raise ValueError('编辑草稿过大')
    with store.lock:
        rows=listing(store);rows[category+':'+key]={'category':category,'value':copy.deepcopy(value),'saved_at':time.time_ns()}
        path=store.root/'editor-drafts.json';temp=path.with_name('.draft-'+uuid.uuid4().hex)
        try:
            with temp.open('w',encoding='utf8') as f:
                json.dump(rows,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            if temp.exists():temp.unlink()
    result={'saved':True,'committed':False,'draft_key':category+':'+key}
    if not commit or value is None:return result
    try:
        if category=='coach':
            # The caller supplies the current prepared head model. The normal
            # store validates models/portraits without reloading the editor.
            result.update(store.coaches.save(value))
        elif category=='pack':
            import packs
            result.update(packs.save(store,value))
        elif category=='settings':
            from game_settings import settings
            result['value']=settings(store,value)
        elif category=='progress':
            from workspace_tools import game_options
            result['value']=game_options(store,value)
        result['committed']=True
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result['message']=str(exc)
    return result


def remove(store,category,identity):
    key=category+':'+str(uuid.UUID(identity))
    with store.lock:
        rows=listing(store)
        if key not in rows:return
        del rows[key]
        path=store.root/'editor-drafts.json';temp=path.with_name('.draft-'+uuid.uuid4().hex)
        try:
            temp.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf8');os.replace(temp,path)
        finally:
            if temp.exists():temp.unlink()
