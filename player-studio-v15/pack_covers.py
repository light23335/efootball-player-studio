"""Content-addressed custom pack banners, cropped identically to the UI."""
from export_errors import export_context, exported
from pathlib import Path
import hashlib,io,re

IMAGE=re.compile(r'[a-f0-9]{64}\.(?:png|jpg|jpeg|webp)')
PREFIX='custom-resources/personal-player-studio/covers/'

def normalize(value):
    if value is None:return None
    if not isinstance(value,dict) or not IMAGE.fullmatch(str(value.get('asset_id',''))):raise ValueError('卡包封面图片无效')
    result={'asset_id':value['asset_id']}
    for key,lo,hi,default in (('zoom',1,4,1),('x',-100,100,0),('y',-100,100,0)):
        v=value.get(key,default)
        if type(v) not in (int,float) or not lo<=v<=hi:raise ValueError('卡包封面裁切参数超出范围')
        result[key]=v
    return result

def compile_covers(packs,store):
    from PIL import Image,ImageOps
    files={};bindings={};routes={}
    for pack in packs:
        with export_context('卡包',pack,'读取和编译卡包封面'):
            cover=normalize(pack.get('cover'))
            if not cover:continue
            path=store.root/'assets'/cover['asset_id']
            if not path.is_file():raise ValueError(pack['name']+'：卡包封面文件缺失，请重新选择图片')
            with Image.open(path) as source:
                source=ImageOps.exif_transpose(source).convert('RGBA');w,h=source.size
                if w*h>64*1024*1024:raise ValueError('卡包封面图片像素过大，请先缩小图片')
                scale=max(1200/w,480/h)*cover['zoom'];cw,ch=1200/scale,480/scale
                left=(w-cw)*(cover['x']+100)/200;top=(h-ch)*(cover['y']+100)/200
                crop=source.transform((1200,480),Image.Transform.EXTENT,(left,top,left+cw,top+ch),Image.Resampling.BICUBIC)
                canvas=Image.new('RGBA',crop.size,(16,26,44,255));canvas.alpha_composite(crop)
                encoded=io.BytesIO();canvas.convert('RGB').save(encoded,format='JPEG',quality=95,optimize=True);raw=encoded.getvalue()
            digest=hashlib.sha256(raw).hexdigest();relative=PREFIX+digest+'.jpg';request='/player-studio/pack-covers/'+digest
            files[relative]=raw;bindings[pack['uuid']]={'c':request,'d':request}
            routes[request]={'path':relative,'sha256':digest,'bytes':len(raw),'mime':'image/jpeg'}
    return files,bindings,routes
