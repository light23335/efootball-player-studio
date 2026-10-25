"""Check each independent game/resource installation without mixing editions."""
import zipfile
from apk_installation import GAME,RESOURCES,COEXIST_GAME,COEXIST_RESOURCES,identity

def inspect(apk):
    with zipfile.ZipFile(apk) as z:
        kind='game' if 'assets/gateway-release/release-manifest.json' in z.namelist() else 'resource' if 'assets/resource-bootstrap/resources.zip' in z.namelist() else None
    if not kind:raise ValueError('APK 不是支持的游戏或配套资源包')
    return dict(identity(apk),kind=kind,path=str(apk))

def expected_resources(game,resources):
    known={GAME:RESOURCES,COEXIST_GAME:COEXIST_RESOURCES}
    if game['package'] in known:return known[game['package']]
    with zipfile.ZipFile(game['path']) as z:dex=[z.read(n) for n in z.namelist() if n.endswith('.dex')]
    matches=[r['package'] for r in resources if any(a.encode() in raw for a in r.get('authorities',[]) for raw in dex)]
    if len(set(matches))!=1:raise ValueError('无法确认这份 DIY 游戏依赖的资源包，请使用配套安装包')
    return matches[0]

def check(rows,errors=(),target=None):
    resources=[r for r in rows if r['kind']=='resource'];results=[]
    games=[r for r in rows if r['kind']=='game' and (not target or r['package']==target)]
    for game in games:
        try:
            expected=expected_resources(game,resources);resource=next((r for r in resources if r['package']==expected),None)
            passed=bool(resource and set(resource.get('signers',[]))&set(game.get('signers',[])))
            message='游戏和资源包名依赖、签名配套' if passed else '缺少配套资源 '+expected if not resource else '游戏与资源签名不同，不配套'
            if resource and resource.get('dex_identity_valid') is False:
                passed=False;message='共存资源 DEX 索引损坏，请使用新版工坊重新生成并同签名覆盖安装资源 APK'
            elif game.get('dex_identity_valid') is False:
                passed=False;message='共存游戏 DEX 索引损坏，请使用新版工坊重新生成游戏 APK'
        except ValueError as exc:expected=None;passed=False;message=str(exc)
        results.append({'game':game['package'],'resource':expected,'passed':passed,'message':message})
    if not games:results.append({'game':target or '', 'resource':None,'passed':False,'message':'未发现可检查的游戏 APK'})
    return {'passed':all(r['passed'] for r in results) and not errors,'pairs':results,'errors':list(errors),'coexist_allowed':True}

def validate_install(incoming,installed):
    row=inspect(incoming);rows=[r for r in installed if r['package']!=row['package']]+[row]
    if row.get('dex_identity_valid') is False:raise ValueError('共存 APK 的 DEX 索引损坏，请使用新版工坊重新生成后安装')
    if row['kind']=='game':
        result=check(rows,target=row['package'])
        if not result['passed']:raise ValueError('安装配套检查未通过：'+result['pairs'][0]['message']+'。请先安装对应资源 APK。')
        return result
    for game in [r for r in installed if r['kind']=='game']:
        try:dependent=expected_resources(game,[row])==row['package']
        except ValueError:continue
        if dependent and not set(game['signers'])&set(row['signers']):raise ValueError('资源与已安装的对应游戏签名不同，不配套')
    return {'passed':True,'resource_first':True}
