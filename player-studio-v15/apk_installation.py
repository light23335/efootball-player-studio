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
 with zipfile.ZipFile(apk) as z:info=Manifest(z.read('AndroidManifest.xml')).info()
 return dict(info,signers=signer_fingerprints(apk))

def local_certificate(store):
 path=store.root/'signing/personal-apk-signing-cert.der'
 return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def remember_resource(store,mode,package,certificate):
 path=store.root/'resource-installations.json';value=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {}
 value[mode]={'package':package,'signer':certificate};temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');temp.replace(path)

def resources_needed(store,rows):
 cert=local_certificate(store);path=store.root/'resource-installations.json';known=json.loads(path.read_text(encoding='utf8')) if path.is_file() else {};result={}
 for mode,package in [('update',RESOURCES),('coexist',COEXIST_RESOURCES)]:
  exists=cert and (known.get(mode,{}).get('signer')==cert or any(r['package']==package and cert in r['signers'] for r in rows))
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
 if not raw.startswith(b'dex\n') or len(raw)<112:raise ValueError('DEX 格式不支持共存修改')
 out=bytearray(raw);count,offset=struct.unpack_from('<II',out,56);changed=0
 for n in range(count):
  pos=struct.unpack_from('<I',out,offset+4*n)[0];start=pos
  for _ in range(5):
   byte=out[start];start+=1
   if byte<128:break
  else:raise ValueError('DEX 字符串长度无效')
  end=out.index(0,start);old=bytes(out[start:end]);new=old
  for a,b in ALIASES.items():
   assert len(a)==len(b);new=new.replace(a.encode(),b.encode())
  if new!=old:out[start:end]=new;changed+=1
 if changed:
  out[12:32]=hashlib.sha1(out[32:]).digest();struct.pack_into('<I',out,8,zlib.adler32(out[12:])&0xffffffff)
 return bytes(out),changed

def coexist_entries(source,mode):
 if mode=='update':return {},{'mode':'update','rewritten_dex_strings':0}
 metadata=plan(source.filename,'coexist');document=Manifest(source.read('AndroidManifest.xml'))
 document.clone(metadata['package'],'73efootball 工坊版' if metadata['package']==COEXIST_GAME else '73efootball 工坊资源',ALIASES)
 replacements={'AndroidManifest.xml':document.bytes()};count=0
 for name in source.namelist():
  if name.endswith('.dex'):
   raw,changed=patch_dex(source.read(name));count+=changed
   if changed:replacements[name]=raw
 return replacements,dict(metadata,rewritten_dex_strings=count)
