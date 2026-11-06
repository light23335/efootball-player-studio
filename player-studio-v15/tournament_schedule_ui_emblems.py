"""Build-time extraction of the supplied game's crests, without a running app.

Reads prepared IoStore files; writes only the explicit output directory. The
Android presentation receives PNG data URIs and never needs a PC asset path.
"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath


def _png(raw, bulk, native_folder):
    from PIL import Image
    from native_texture import cooked_mip, desktop_etc2_png
    mip = cooked_mip(raw, bulk)
    if mip['format'] in ('PF_ETC2_RGB', 'PF_ETC2_RGBA'):
        png = desktop_etc2_png(mip, native_folder)
        image = Image.open(io.BytesIO(png)).convert('RGBA')
    elif mip['format'] in ('PF_B8G8R8A8', 'PF_R8G8B8A8'):
        image = Image.frombytes('RGBA', (mip['width'],mip['height']), mip['data'],
                                'raw', 'BGRA' if mip['format']=='PF_B8G8R8A8' else 'RGBA')
    else:
        raise ValueError('队徽实际像素格式未适配：' + mip['format'])
    # Flat placeholders are not presented as the actual team's crest.
    if image.getbbox() is None or not any(hi-lo>4 for lo,hi in image.getextrema()):
        raise ValueError('队徽资源为空白或纯色占位图')
    image.thumbnail((96,96), Image.Resampling.LANCZOS)
    output=io.BytesIO();image.save(output,format='PNG',optimize=True)
    return output.getvalue(), {'format':mip['format'],'original_size':[mip['width'],mip['height']],
                              'size':list(image.size),'storage':mip['storage']}


def extract(containers, team_ids, native_folder, *, nation_ids=None, destination=None):
    """Match game team IDs to patch-priority colour crests and provenance.

    A caller must supply the *selected game source's* prepared containers.
    No club IDs are inferred from display names, and no online logos are used.
    """
    from native_iostore import Container
    from native_symbols import merged_symbols, resolve_club
    containers=Path(containers);native_folder=Path(native_folder)
    key=(containers/'resource-key.bin').read_bytes()
    files={};stores={};sources=[]
    for path in sorted(containers.glob('*.utoc'),key=lambda p:('_P' in p.stem,p.name)):
        if path.stem=='global':continue
        store=Container(path,key)
        selected={name:index for name,index in store.paths.items() if '/ui/Data/Symbol/' in name}
        if not selected:continue
        stores[path.name]=store
        sources.append({'container':path.name,'index_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for name,index in selected.items():files[name]=(store,index)
    symbols=merged_symbols({},files)
    teams={};missing={}
    for team in dict.fromkeys(map(int,team_ids)):
        nation=(nation_ids or {}).get(str(team),(nation_ids or {}).get(team))
        if nation is None:ref=resolve_club(symbols,team)
        else:ref=next((symbols[k] for k in (f'{int(nation):03d}_l',f'{int(nation):03d}') if k in symbols),None)
        if not ref:
            missing[str(team)]='此游戏源中未找到适用队徽';continue
        path='../../../'+ref
        store,index=files[path]
        raw=store.read_chunk(index)
        def bulk(suffix):
            target=str(PurePosixPath(path).with_suffix(suffix))
            if target not in files:raise ValueError('队徽缺少外部像素数据：'+suffix)
            container,chunk=files[target]
            return container.read_chunk(chunk)
        try:png,info=_png(raw,bulk,native_folder)
        except (ValueError,OSError) as exc:
            missing[str(team)]=str(exc);continue
        digest=hashlib.sha256(png).hexdigest()
        teams[str(team)]={'uri':'data:image/png;base64,'+base64.b64encode(png).decode('ascii'),
                         'sha256':digest,'source':ref,'source_sha256':hashlib.sha256(raw).hexdigest(),
                         'container':store.path.name,'kind':'nation' if nation is not None else 'club',**info}
        if destination is not None:
            output=Path(destination);output.mkdir(parents=True,exist_ok=True)
            (output/(str(team)+'.png')).write_bytes(png)
    report={'version':1,'kind':'extracted-game-emblems','sources':sources,'teams':teams,'missing':missing}
    if destination is not None:
        (Path(destination)/'emblems.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return report
