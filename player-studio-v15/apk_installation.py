"""Independent coexist identities and honest update/signing information."""
from pathlib import Path
import hashlib,json,struct,zipfile,zlib
from android_manifest import Manifest
from apk_delta import signer_fingerprints

GAME='com.efootball.revival.local'
RESOURCES='com.efootball.revival.resources'
COEXIST_GAME='com.efootball.revival.diyer'
COEXIST_RESOURCES='com.efootball.revival.diyassets'
ALIASES={GAME:COEXIST_GAME,RESOURCES:COEXIST_RESOURCES}

def identity(apk):
 with zipfile.ZipFile(apk) as z:
  info=Manifest(z.read('AndroidManifest.xml')).info()
  if info['package'] in (COEXIST_GAME,COEXIST_RESOURCES):
   from dex_identity import inspect
   try:
    for name in z.namelist():
     if name.endswith('.dex'):inspect(z.read(name))
    info['dex_identity_valid']=True
   except ValueError as exc:info.update(dex_identity_valid=False,dex_identity_error=str(exc))
 return dict(info,signers=signer_fingerprints(apk))

def local_certificate(store):
 path=store.root/'signing/personal-apk-signing-cert.der'
 return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def remember_resource(store,mode,package,certificate):
 path=store.root/'resource-installations.json';value=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
 value[mode]={'package':package,'signer':certificate,'dex_identity_revision':1};temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temp.replace(path)

def resources_needed(store,rows,game_package=None):
 cert=local_certificate(store);path=store.root/'resource-installations.json';known=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {};result={}
 for mode,package in [('update',COEXIST_RESOURCES if game_package==COEXIST_GAME else RESOURCES),('coexist',COEXIST_RESOURCES)]:
  exists=cert and (any(r.get('signer')==cert and r.get('package')==package and (package!=COEXIST_RESOURCES or r.get('dex_identity_revision')==1) for r in known.values()) or any(r['package']==package and cert in r['signers'] and (package!=COEXIST_RESOURCES or r.get('dex_identity_valid') is True) for r in rows))
  if package==COEXIST_RESOURCES and any(r['package']==package and cert in r['signers'] and r.get('dex_identity_valid') is False for r in rows):exists=False
  result[mode]=not bool(exists)
 return result

def plan(apk,mode,certificate=None):
 if mode not in ('update','coexist'):raise ValueError('请选择共存安装或更新已有工坊包')
 info=identity(apk);same=bool(certificate and certificate in info['signers']);kind='resource' if info['package'] in (RESOURCES,COEXIST_RESOURCES) else 'game'
 if mode=='coexist' and info['package'] not in (*ALIASES,*ALIASES.values()):raise ValueError('此包名尚未支持共存，请使用已支持的 73efootball 原版或工坊包')
 target=(COEXIST_RESOURCES if kind=='resource' else COEXIST_GAME) if mode=='coexist' else info['package']
 return {'mode':mode,'source_package':info['package'],'package':target,'source_signer_matches':same,'existing_save_shared':False if mode=='coexist' else None,
         'message':'独立安装工坊版，原游戏及存档保持独立；首次使用需同时生成共存资源包。' if mode=='coexist' else '覆盖保留存档需要包名、签名与已安装游戏匹配。此前本机工坊生成的同包名游戏通常可更新；任意原版或他人 DIY 包不能保证覆盖。'}

def patch_dex(raw):
 from dex_identity import rewrite
 return rewrite(raw,ALIASES)

def coexist_entries(source,mode):
 if mode=='update':
  metadata={'mode':'update','package':identity(source.filename)['package'],'rewritten_dex_strings':0}
  if metadata['package']==COEXIST_GAME:verify_private_root(source.filename);metadata['private_root_check_verified']=True
  repaired={}
  if metadata['package'] in (COEXIST_GAME,COEXIST_RESOURCES):
   from dex_identity import rewrite
   for name in source.namelist():
    if name.endswith('.dex'):
     original=source.read(name);raw,_=rewrite(original,{})
     if raw!=original:repaired[name]=raw
  return repaired,dict(metadata,repaired_dex_files=len(repaired))
 metadata=plan(source.filename,'coexist');document=Manifest(source.read('AndroidManifest.xml'))
 if metadata['package']==COEXIST_GAME:
  verify_private_root(source.filename)
  metadata['private_root_check_verified']=True
 document.clone(metadata['package'],'73efootball 工坊版' if metadata['package']==COEXIST_GAME else '73efootball 工坊资源',ALIASES)
 replacements={'AndroidManifest.xml':document.bytes()};count=0
 for name in source.namelist():
  if name.endswith('.dex'):
   original=source.read(name);raw,changed=patch_dex(original);count+=changed
   if raw!=original:replacements[name]=raw
 return replacements,dict(metadata,rewritten_dex_strings=count)

def verify_private_root(apk):
 import types
 from apk_literals import module_reader
 from personal_binding import code_fingerprint
 code=next(c for c in module_reader(apk)('legend_cr7_grants').co_consts if isinstance(c,types.CodeType) and c.co_name=='_device_root')
 if code_fingerprint(code)!='c72dbd0080b6556425a7d207f69c64437f4a5064bad6b4c506f33ce6d178458c':raise ValueError('原版私有目录检查接口已改变，未生成共存包')
