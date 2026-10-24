"""Custom coach portraits use the game's coach-ID texture lookup."""
import hashlib,io
import json
from pathlib import Path
from pack_covers import normalize as normalize_crop

FOLDER='/Game/Assets/ui/Data/Symbol/Coach/'

def original_portraits(library,coaches,ids):
    if not isinstance(ids,list):raise ValueError('教练编号必须为列表')
    ids=list(dict.fromkeys(ids or []))
    if not ids or len(ids)>24:raise ValueError('每次读取 1–24 名教练头像')
    known={str(c['id']) for c in coaches if c.get('type')!='custom'}
    if any(str(cid) not in known or not str(cid).isdigit() for cid in ids):raise ValueError('教练编号不在当前游戏数据库中')
    if library.state['phase']!='ready':return {'portraits':{},'ready':False,'message':'请先准备游戏资源，才能显示原版头像'}
    result={};pending={}
    with library.convert_lock:
        available=library.face_assets().files
        for cid in map(str,ids):
            hit=library.cache.get('coach:'+cid)
            if hit and (library.store.root/'assets'/hit['asset_id']).is_file():result[cid]=hit;continue
            prefix='../../../PesMobile/Content/Assets/ui/Data/Symbol/Coach/'
            path=next((prefix+variation+'coach_'+cid+'_.uasset' for variation in ('Variation/','') if prefix+variation+'coach_'+cid+'_.uasset' in available),None)
            if path is None:result[cid]={'missing':True,'message':'游戏资源内没有此教练的独立头像'};continue
            pending[cid]=path.removeprefix('../../../')
        paths=[p for p in pending.values() if not (library.converted/Path(p).with_suffix('.png')).is_file()]
        error=''
        if paths:
            try:library.run(paths)
            except (ValueError,OSError) as exc:error=str(exc)
        for cid,path in pending.items():
            file=library.converted/Path(path).with_suffix('.png')
            if not file.is_file():result[cid]={'unavailable':True,'message':error or '此原版头像尚未能读取'};continue
            asset=library.store.import_asset(file,'image')
            result[cid]={'asset_id':asset['id'],'zoom':1,'x':0,'y':0,'native_path':path}
            library.cache['coach:'+cid]=result[cid]
        library.cache_path.write_text(json.dumps(library.cache,ensure_ascii=False,indent=2),encoding='utf8')
    return {'portraits':result,'ready':True}


def normalize(value):
    try:return normalize_crop(value)
    except ValueError as exc:raise ValueError(str(exc).replace('卡包封面','教练头像')) from exc


def pixels(value,store,size=(128,128)):
    from PIL import Image,ImageOps
    crop=normalize(value)
    path=store.root/'assets'/crop['asset_id']
    if not path.is_file():raise ValueError('教练头像文件缺失，请重新上传图片')
    with Image.open(path) as source:
        source=ImageOps.exif_transpose(source).convert('RGBA');w,h=source.size
        if w*h>64*1024*1024:raise ValueError('教练头像图片像素过大，请先缩小图片')
        scale=max(size[0]/w,size[1]/h)*crop['zoom'];cw,ch=size[0]/scale,size[1]/scale
        left=(w-cw)*(crop['x']+100)/200;top=(h-ch)*(crop['y']+100)/200
        return source.transform(size,Image.Transform.EXTENT,(left,top,left+cw,top+ch),Image.Resampling.BICUBIC)


def compile_portraits(coaches,definitions,library):
    from native_art import Assets,texture
    from native_iostore import package_names
    selected=[(c,d) for c,d in zip(coaches,definitions) if c.get('portrait')]
    if not selected:return [],[]
    assets=Assets(library.containers);raw,_=assets.get(FOLDER+'coach_8_')
    packages=[];report=[]
    for coach,definition in selected:
        name=FOLDER+'coach_'+str(definition['id'])+'_'
        image=pixels(coach['portrait'],library.store)
        data,meta=texture(raw,name,image)
        if name not in package_names(data):raise ValueError('教练头像原生资源名称校验失败')
        packages.append((name,data,meta))
        report.append({'uuid':coach['uuid'],'id':definition['id'],'path':name,'size':list(image.size),'sha256':hashlib.sha256(data).hexdigest()})
    return packages,report


def owned_paths(container,ids):
    names={f'coach_{int(cid)}_.uasset' for cid in ids}
    return {i for p,i in container.paths.items() if '/ui/Data/Symbol/Coach/' in p and p.rsplit('/',1)[-1] in names}
