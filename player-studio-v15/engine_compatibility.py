"""Recognize compatible small updates by the interfaces we actually consume."""
import hashlib,json,re,zipfile
from pathlib import Path


def game_version(apk,release,default):
    # A source-contract-v1 tag is a protocol version, not the game's release.
    match=re.search(r'(?:^|[^A-Za-z0-9])V([0-9]{1,3})(?![0-9])',Path(apk).stem,re.I)
    if match:return 'V'+match[1]
    matches=[m for m in re.finditer(r'(?:^|[-_])V([0-9]{1,3})(?:[-_]|$)',release,re.I) if int(m[1])>=13]
    return 'V'+matches[0][1] if matches else default


def detect(apk,resources,release,known=None):
    resources=Path(resources)
    try:
        profile=json.loads((resources/'native-resource-profile.json').read_text(encoding='utf8'))
        profile.update({k:v for k,v in (known or {}).items() if k in ('resource_key_offset','resource_key_sha256')})
        contract=json.loads((resources/'native-compatibility.json').read_text(encoding='utf8'))
        with zipfile.ZipFile(apk) as archive,archive.open('lib/arm64-v8a/libUE4.so') as engine:
            head=engine.read(64)
            if head[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(head[18:20],'little')!=183:raise ValueError('需要 ARM64 原生引擎')
            engine.seek(profile['resource_key_offset']);key=engine.read(32)
            if hashlib.sha256(key).hexdigest()!=profile['resource_key_sha256']:raise ValueError('资源解码接口发生变化')
            for region in contract['regions']:
                engine.seek(region['offset']);raw=engine.read(region['bytes'])
                if hashlib.sha256(raw).hexdigest()!=region['sha256']:raise ValueError('关键接口发生变化：'+region['name'])
        # Inspect bytecode and construct our hook extension without running APK code.
        from native_binding_source import read_installer,verify_installer
        from personal_binding import fingerprint
        payload,code=read_installer(apk)
        # The inspected V17 composition protocol identifies the interface
        # family even when a user renames/re-signs a derived APK.
        verified_v17=getattr(code,'proof',{}).get('interface_family')=='V17'
        route_profile=json.loads((resources/'native-route-templates.json').read_text(encoding='utf8'))
        route_profile.update(club_emblems=True,external_routes=True)
        for name in ('position','acquisition','overall','thumbnail'):
            route_profile[name+'_hook']=json.loads((resources/('native-'+name+'-hook.json')).read_text(encoding='utf8'))
        route={'cardId':90000000,'suiteDonorId':90000000,'portraitKey':'8000000','modelFaceKey':'8000000','club_id':100,'position':0,'maximum_overall':100,'presentation_rarity':10}
        verify_installer(code,{'original_fingerprint':fingerprint(payload),'routes':[route],'profile':route_profile})
        return {**(known or {}),'family':profile.get('family','V14'),'game_version':'V17'if verified_v17 else game_version(apk,release,(known or profile).get('game_version','V16')),
                'validation':'Automatic interface verification; full-engine digest is recorded for integrity only.',
                'compatibility':{'mode':'interfaces','regions':len(contract['regions']),'installer':'verified'}}
    except (OSError,KeyError,ValueError) as exc:
        raise ValueError('此引擎的关键接口暂不兼容，当前数据库和工程已保留：'+str(exc)) from exc
