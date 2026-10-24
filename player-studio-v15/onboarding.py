"""Read-only source discovery and the beginner workspace preferences."""
from pathlib import Path
import json,threading,time,zipfile
from apk_installation import identity,local_certificate,plan,resources_needed

def inspect_source(path):
 p=Path(path)
 if not p.is_file() or p.suffix.lower()!='.apk':return None
 try:
  with zipfile.ZipFile(p) as z:
   if 'assets/gateway-release/release-manifest.json' in z.namelist():
    manifest=json.loads(z.read('assets/gateway-release/release-manifest.json'));kind='game';release=manifest.get('release_id','')
   elif 'assets/resource-bootstrap/resources.zip' in z.namelist():kind='resource';release='离线资源'
   else:return None
  info=identity(p)
  return dict(info,path=str(p),name=p.name,kind=kind,release_id=release,bytes=p.stat().st_size)
 except (OSError,ValueError,KeyError,zipfile.BadZipFile):return None

def preferences(store,body=None):
 path=store.root/'workspace-preferences.json';value={'navigation':'simple'}
 if path.is_file():value.update(json.loads(path.read_text(encoding='utf8')))
 if body is not None:
  if body.get('navigation') not in ('simple','full'):raise ValueError('导航模式无效')
  value['navigation']=body['navigation'];temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temp.replace(path)
 return value

class Setup:
 def __init__(self,server):self.server=server;self.cache=None;self.at=0;self.lock=threading.Lock()
 def status(self,refresh=False):
  provider=getattr(self.server,'installed_sources',None)
  with self.lock:
   if refresh or self.cache is None or time.monotonic()-self.at>30:
    rows=[];errors=[]
    if provider:
     try:result=provider()
     except Exception:result={'rows':[],'errors':['无法自动读取已安装游戏，请使用手动选择 APK。']}
     errors=result.get('errors',[])
     for row in result.get('rows',[]):
      item=inspect_source(row['path'])
      if item:rows.append(dict(item,installed=True,label=row.get('label') or item['name']))
    else:
     home=self.server.home;paths=[]
     active=self.server.store.root/'active-game.json'
     if active.is_file():
      data=json.loads(active.read_text(encoding='utf8'));paths.extend(data.get(k) for k in ('apk','companion') if data.get(k))
     folders=[home,home/'原始APK',home.parent,home.parent/'原始APK']
     folders.extend(p/'原始APK' for p in home.parent.glob('球员工坊*') if p.is_dir())
     for folder in folders:
      if folder.is_dir():paths.extend(sorted(folder.glob('*.apk'))[:30])
     seen=set()
     for path in paths[:100]:
      p=str(Path(path).absolute())
      if p in seen:continue
      seen.add(p);item=inspect_source(p)
      if item:rows.append(dict(item,installed=False,label=item['name']))
    self.cache={'rows':rows,'errors':errors,'installed_discovery':bool(provider)};self.at=time.monotonic()
  cert=local_certificate(self.server.store)
  active=self.server.store.root/'active-game.json';selected=json.loads(active.read_text(encoding='utf8')) if active.is_file() else {}
  games=[r for r in self.cache['rows'] if r['kind']=='game'];resources=[r for r in self.cache['rows'] if r['kind']=='resource']
  matching=next((r for r in games if cert in r['signers']),None) if cert else None
  game=next((r for r in games if r['path']==selected.get('apk')),None) or matching or next(iter(games),None)
  resource=next((r for r in resources if r['path']==selected.get('companion')),None) or next((r for r in resources if cert and cert in r['signers']),None) or next(iter(resources),None)
  return {**self.cache,'preferences':preferences(self.server.store),'library':self.server.library.summary(),'resources_needed':resources_needed(self.server.store,self.cache['rows'],game['package'] if game else None),'selected':{'apk':game['path'] if game else selected.get('apk',''),'companion':resource['path'] if resource else selected.get('companion','')},'recommended_mode':'update' if (matching and game and matching['package']==game['package']) or (not provider and cert) else 'coexist',
          'save_notice':'自动读取安装包和资源，不读取其他应用的私有存档。共存版使用独立存档；同包名、同签名覆盖安装才可保留原游戏存档。'}
 def install_plan(self,body):return plan(body['apk'],body.get('installation_mode','update'),local_certificate(self.server.store))
