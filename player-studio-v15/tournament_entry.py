"""Native Events tile artwork and verified localized labels for tournaments."""
import hashlib,io,json,re
from studio_resources import bundled_resources

REQUEST='/banner/event/990000/3dad1fe746df39d8cd5b999a6a0995d512d719b3ec42553e66eea098648475b7'
RELATIVE='custom-resources/personal-player-studio/tournament-entry.jpg'
COVER_PREFIX='custom-resources/personal-player-studio/tournament-covers/'
COVER_REQUEST='/player-studio/pack-covers/'


def entry_pixels(image,size):
    """Keep the supplied portrait artwork whole in wider native banners."""
    from PIL import Image,ImageOps
    if size[0]>size[1]:
        return ImageOps.pad(image,size,method=Image.Resampling.LANCZOS,color=(7,20,43),centering=(.5,0))
    return ImageOps.fit(image,size,method=Image.Resampling.LANCZOS,centering=(.5,0))


def merge_image_routes(previous,updated):
    """Replaced files cannot retain an old route's incompatible checksum."""
    paths={r['path']for r in updated.values()}
    return {**{k:v for k,v in previous.items()if v.get('path')not in paths},**updated}


def cover_image(path,cover):
    """The UI uses the same object-fit crop, zoom and object-position."""
    from PIL import Image,ImageOps
    with Image.open(path)as source:
        if source.width*source.height>64*1024*1024:raise ValueError('锦标赛封面图片像素过大，请先缩小图片')
        source=ImageOps.exif_transpose(source).convert('RGBA');w,h=source.size
        scale=max(1024/w,576/h)*cover['zoom'];cw,ch=1024/scale,576/scale
        left=(w-cw)*(cover['x']+100)/200;top=(h-ch)*(cover['y']+100)/200
        crop=source.transform((1024,576),Image.Transform.EXTENT,(left,top,left+cw,top+ch),Image.Resampling.BICUBIC)
        canvas=Image.new('RGBA',crop.size,(16,26,44,255));canvas.alpha_composite(crop)
        out=io.BytesIO();canvas.convert('RGB').save(out,'JPEG',quality=95,optimize=True)
        return out.getvalue()


def compile_covers(definitions,store):
    """Bind per-event banners; retain source-APK images without local originals."""
    from export_errors import export_context
    from tournament_rules import normalize_cover
    files={};routes={}
    for definition in definitions:
        with export_context('锦标赛',definition,'读取和编译锦标赛封面'):
            cover=normalize_cover(definition.get('cover'))
            if not cover:
                definition.pop('cover_artwork',None);continue
            revision=hashlib.sha256(json.dumps(cover,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            cached=definition.get('cover_artwork')or{}
            if cached.get('design_sha256')==revision:
                digest=cached.get('sha256','')
                if (isinstance(digest,str)and re.fullmatch(r'[a-f0-9]{64}',digest)
                    and cached.get('path')==COVER_PREFIX+digest+'.jpg'
                    and cached.get('request')==COVER_REQUEST+digest
                    and type(cached.get('bytes'))is int and 0<cached['bytes']<=8*1024*1024
                    and cached.get('mime')=='image/jpeg'):
                    routes[cached['request']]={k:cached[k]for k in('path','sha256','bytes','mime')}
                    continue
            path=store.root/'assets'/cover['asset_id']
            if not path.is_file():raise ValueError('锦标赛封面文件缺失，请重新选择图片')
            raw=cover_image(path,cover);digest=hashlib.sha256(raw).hexdigest()
            relative=COVER_PREFIX+digest+'.jpg';request=COVER_REQUEST+digest
            route={'path':relative,'sha256':digest,'bytes':len(raw),'mime':'image/jpeg'}
            files[relative]=raw;routes[request]=route
            definition['cover_artwork']={**route,'request':request,'design_sha256':revision}
    return files,routes


def image_files(definitions=(),store=None):
    from PIL import Image,ImageOps
    image=Image.open(bundled_resources()/'tournament-entry-v2.png').convert('RGB')
    files={};routes={}
    for shape,size in (('portrait',(512,768)),('landscape',(1024,576))):
        pixels=entry_pixels(image,size)
        out=io.BytesIO();pixels.save(out,'JPEG',quality=94);raw=out.getvalue()
        relative=RELATIVE.replace('.jpg','-'+shape+'.jpg');digest=hashlib.sha256(raw).hexdigest()
        files[relative]=raw;routes['/banner/event/990000/'+digest]={'path':relative,'sha256':digest,'bytes':len(raw),'mime':'image/jpeg'}
    custom_files,custom_routes=compile_covers(definitions,store)
    files.update(custom_files);routes.update(custom_routes)
    return files,routes


def artwork(library):
    """Replace the native Events fallback only, including the patch mount."""
    from native_art import texture
    from PIL import Image,ImageOps
    assets=library.face_assets();result=[]
    for mount in('PesMobile',):
        path='../../../'+mount+'/Content/Assets/ui/Data/Widget/Mode/eFworld/ModeMainMenuMatch/Tex720/ModeMainMenuMatchChoiceMainImgEvent.uasset'
        # Mount paths are case sensitive in the directory index.
        key=next((p for p in assets.files if p.casefold()==path.casefold()),None)
        if key is None:continue
        raw,meta=assets.get(key)
        from native_texture import cooked_mip
        mip=cooked_mip(raw,lambda suffix:assets.get(key.removesuffix('.uasset')+suffix)[0])
        with Image.open(bundled_resources()/'tournament-entry-v2.png')as source:
            image=entry_pixels(source.convert('RGB'),(mip['width'],mip['height']))
        logical='/Game/'+key.split('/Content/',1)[1].removesuffix('.uasset') if mount=='PesMobile'else '/'+mount+'/'+key.split('/Content/',1)[1].removesuffix('.uasset')
        result.append((logical,texture(raw,logical,image)[0],meta))
    if not result:raise ValueError('锦标赛主页活动入口纹理缺失')
    return result


def text_groups(locale):
    title='锦标赛模式'if locale=='zha'else'錦標賽模式'if locale=='chi'else'Tournament Mode'
    # These three native Events labels were read from stock language CPKs.
    labels=('使用1次机会','晋级获得机会')if locale=='zha'else('使用1次機會','晉級獲得機會')if locale=='chi'else('Use 1 chance','Earn chances by advancing')
    return [{'name':'Any1W','id':1137,'items':{178:title}},
            {'name':'Any3W','id':1142,'items':{564:title,573:title,63000:labels[0],63001:labels[1]}}]
