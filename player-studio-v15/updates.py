"""Optional, non-blocking public GitHub Release checks. Never installs updates."""
from pathlib import Path
import copy,json,logging,re,threading,time,urllib.request,urllib.error
from urllib.parse import urlsplit
NATIVE_TRANSPORT=None

def native_fetch(url,agent):
 if NATIVE_TRANSPORT:return NATIVE_TRANSPORT(url,agent)
 from native_https import fetch
 return fetch(url,agent)

def repository(value):
 value=str(value or '').strip().removeprefix('https://github.com/').removesuffix('/').removesuffix('.git')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',value):raise ValueError('请输入 GitHub 用户名/仓库名，或完整仓库地址')
 return value

def version(value):
 match=re.fullmatch(r'(?:V16-)?v?(\d+\.\d+\.\d+(?:\.\d+)?)',str(value))
 if not match:return None
 parts=tuple(map(int,match[1].split('.')));return parts+(0,)*(4-len(parts))

def release_result(data,current,repo,platform):
 if data.get('draft') or data.get('prerelease'):return {'phase':'current','message':'当前没有新的正式版本'}
 tag=data.get('tag_name','');number=version(tag)
 if number is None or number<=version(current):return {'phase':'current','message':'当前已是最新正式版本'}
 prefix='https://github.com/'+repo+'/releases/'
 page=data.get('html_url','')
 if not page.startswith(prefix+'tag/'):raise ValueError('Release 地址与配置仓库不一致')
 assets=[]
 for asset in data.get('assets',[]):
  name=str(asset.get('name',''));url=str(asset.get('browser_download_url',''))
  if not url.startswith(prefix+'download/') or 'V15' in name.upper():continue
  if platform=='android' and name.lower().endswith('.apk'):assets.append((name,url))
  elif platform=='pc' and name.lower().endswith('.zip') and ('免安装' in name or 'portable' in name.lower()):assets.append((name,url))
 return {'phase':'available','version':tag,'message':'发现可选更新 '+tag,'notes':str(data.get('body') or '')[:8000],'release_url':page,'download_url':assets[0][1] if assets else page,'asset':assets[0][0] if assets else None,'mandatory':False}

class UpdateChecker:
 def __init__(self,store,resources,current,platform='pc'):
  self.store=store;self.resources=Path(resources);self.current=current;self.platform=platform;self.lock=threading.Lock();self.state={'phase':'idle'};self.dismissed=set()
 def settings(self,body=None):
  path=self.store.root/'update-preferences.json';defaults=self.resources/'github-updates.json'
  value=json.loads(defaults.read_text(encoding='utf8')) if defaults.is_file() else {'repository':'','enabled':False}
  if path.is_file():value.update(json.loads(path.read_text(encoding='utf8')))
  if body is not None:
   if type(body.get('enabled')) is not bool:raise ValueError('自动更新提醒开关无效')
   value={'repository':repository(body['repository']),'enabled':body['enabled']};temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temp.replace(path)
  return value
 def status(self):
  with self.lock:result=copy.deepcopy(self.state)
  return dict(result,settings=self.settings(),current=self.current,prompt=bool(result.get('phase')=='available' and result.get('version') not in self.dismissed))
 def dismiss(self):
  with self.lock:self.dismissed.add(self.state.get('version'))
  return self.status()
 def start(self,manual=False):
  settings=self.settings()
  if not manual and (not settings.get('enabled') or not settings.get('repository')):return self.status()
  repo=repository(settings['repository'])
  with self.lock:
   if self.state['phase']=='checking':return dict(self.state)
   self.state={'phase':'checking','message':'正在检查 GitHub 正式版本…'}
  threading.Thread(target=self._check,args=(repo,),daemon=True,name='studio-update-check').start();return self.status()
 def _check(self,repo):
  try:
   request=urllib.request.Request('https://api.github.com/repos/'+repo+'/releases/latest',headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'PlayerStudio/'+self.current})
   transport='python-https'
   try:
    with urllib.request.urlopen(request,timeout=8) as response:raw=response.read(256*1024+1)
   except urllib.error.HTTPError:raise
   except OSError as exc:
    logging.warning('Python HTTPS failed; using system HTTPS: %s: %s',type(exc).__name__,str(exc))
    raw=native_fetch(request.full_url,'PlayerStudio/'+self.current);transport='system-https'
   if len(raw)>256*1024:raise ValueError('更新说明超过大小限制')
   result=release_result(json.loads(raw),self.current,repo,self.platform)
   result['transport']=transport
  except urllib.error.HTTPError as exc:
   logging.warning('GitHub update HTTP failure: %s %s',exc.code,exc.reason)
   result={'phase':'current','message':'仓库还没有正式 Release；当前版本可以继续使用'} if exc.code==404 else {'phase':'offline','message':'暂时无法检查更新；不影响继续编辑'}
  except Exception as exc:
   logging.exception('GitHub update request failure: %s: %s',type(exc).__name__,str(exc))
   result={'phase':'offline','message':'暂时无法检查更新；不影响继续编辑','detail':type(exc).__name__+': '+str(exc)[:300]}
  with self.lock:self.state=result
 def link(self):
  with self.lock:target=self.state.get('download_url') or self.state.get('release_url')
  if not target or not target.startswith('https://github.com/'+repository(self.settings()['repository'])+'/releases/'):raise ValueError('请先检查更新')
  return target
