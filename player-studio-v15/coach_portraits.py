"""Custom coach portraits use the game's coach-ID texture lookup."""
import hashlib,io
from pack_covers import normalize as normalize_crop

FOLDER='/Game/Assets/ui/Data/Symbol/Coach/'


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
