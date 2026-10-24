"""Explicit management of generated files and one-time game settings."""
from pathlib import Path
import json,os,subprocess,uuid

DEFAULTS={'enabled':False,'division':10,'points':0,'matches':0,'wins':0,'draws':0,'losses':0}

def export_folder(store):
    folder=store.root/'exports'
    if folder.is_symlink() or folder.is_junction() or folder.resolve().parent!=store.root.resolve():raise ValueError('导出目录是外部链接，未执行文件操作')
    return folder.resolve()

def game_options(store,body=None):
    path=store.root/'game-options.json'
    if body is None:return json.loads(path.read_text(encoding='utf8')) if path.is_file() else dict(DEFAULTS)
    value={**DEFAULTS,**body}
    if type(value['enabled']) is not bool:raise ValueError('进度修改开关无效')
    for k,low,high in [('division',1,10),('points',0,99999),('matches',0,9999),('wins',0,9999),('draws',0,9999),('losses',0,9999)]:
        if type(value[k]) is not int or not low<=value[k]<=high:raise ValueError(k+' 的数值超出范围')
    if value['wins']+value['draws']+value['losses']!=value['matches']:raise ValueError('胜、平、负之和须等于已赛场次')
    if value['division']>=4 and (value['matches']>2 or value['points']>6):raise ValueError('组别 10–4 当前轮最多已赛 2 场、积分 0–6；第 3 场由游戏结算升降级')
    if value['division']>=4 and value['points']!=3*value['wins']+value['draws']:raise ValueError('组别 10–4 积分须为 胜场×3＋平场')
    value['revision']=str(uuid.uuid4())
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)
    return value

def export_file(store,name):
    folder=export_folder(store);candidate=folder/str(name)
    if Path(str(name)).name!=str(name) or candidate.is_symlink() or candidate.is_junction():raise ValueError('导出文件路径无效')
    path=candidate.resolve()
    if path.parent!=folder or not path.is_file():raise ValueError('导出文件已清除或不存在')
    return path

def export_list(store):
    folder=export_folder(store);rows=[]
    for p in sorted(folder.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
        if p.is_file() and not p.is_symlink() and not p.is_junction():rows.append({'name':p.name,'bytes':p.stat().st_size,'apk':p.suffix.lower()=='.apk','url':'/exports/'+__import__('urllib.parse',fromlist=['quote']).quote(p.name)})
    return {'rows':rows,'count':len(rows),'bytes':sum(r['bytes'] for r in rows)}

def clear_exports(server):
    if server.native_package.status()['phase']=='working' or server.game_import.status()['phase']=='working':raise ValueError('请等待当前导出或导入任务完成')
    with server.store.lock:
        rows=export_list(server.store)['rows']
        for row in rows:export_file(server.store,row['name']).unlink()
    return {'deleted':len(rows),'bytes':sum(r['bytes'] for r in rows)}

def open_export(store,name):
    path=export_file(store,name)
    if os.name!='nt':raise ValueError('当前平台请使用保存或直接安装')
    subprocess.Popen(['explorer.exe','/select,'+str(path)])
    return {'opened':True}
