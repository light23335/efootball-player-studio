"""The large card's background layers, flattened for the native small card."""
from pathlib import Path
import io,re,subprocess
from PIL import Image,ImageChops

REVISION='linked-card-thumbnail-v1'
ASSET=re.compile(r'[a-f0-9]{64}\.(?:png|jpg|jpeg|webp|webm|mp4)')

def poster_time(layer):
    duration=layer.get('duration')
    return min(.8,duration/3) if type(duration) in (int,float) and duration>0 else .8

def desktop_frame(library,path,seconds):
    tool=Path(library.ffmpeg)
    if not tool.is_file():raise ValueError('缺少卡面视频工具，无法生成联动小头像')
    for moment in (seconds,0):
        result=subprocess.run([str(tool),'-hide_banner','-loglevel','error','-ss',str(moment),'-i',str(path),
            '-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode==0 and result.stdout:
            with Image.open(io.BytesIO(result.stdout)) as im:return im.convert('RGBA')
    raise ValueError('无法读取卡面背景动画的静态帧，请重新载入卡面')

def layer_image(library,layer):
    asset=layer.get('asset_id','')
    if not ASSET.fullmatch(asset):raise ValueError('卡面背景资源编号无效')
    path=library.store.root/'assets'/asset
    if not path.is_file():raise ValueError('卡面背景资源缺失，请重新载入卡面')
    seconds=poster_time(layer);key=(asset,layer.get('kind'),seconds)
    with library.thumbnail_lock:
        cache=library.thumbnail_frames
        if key in cache:cache.move_to_end(key);return cache[key].copy()
        if layer.get('kind')=='video':image=library.thumbnail_video_frame(path,seconds)
        else:
            with Image.open(path) as im:image=im.convert('RGBA')
        cache[key]=image.copy()
        while len(cache)>8:cache.popitem(last=False)
        return image

def background(project,library,size=512):
    appearance=project['appearance'];card=project.get('native_card') or {}
    # Match the large-card renderer's layers below its replacement portrait.
    order=({'f01':0,'f02':1,'f04':2,'f03':3,'f05':4,'f07':5,'portrait':6}
           if card.get('preset_id') else {'f01':0,'f02':1,'portrait':2})
    layers=[l for l in card.get('layers',[]) if l.get('slot') in order and order[l['slot']]<order['portrait']]
    if not layers:
        asset=appearance.get('background_image') or (project.get('native_art',{}).get('background') or {}).get('asset_id')
        if asset:layers=[{'asset_id':asset,'kind':'image','slot':'f01'}]
    result=Image.new('RGBA',(size,size),appearance.get('background','#101a2c'))
    for layer in sorted(layers,key=lambda l:order.get(l.get('slot'),0)):
        image=layer_image(library,layer).resize(result.size,Image.Resampling.LANCZOS)
        mode='source-over' if layer.get('slot')=='f01' else layer.get('blend','source-over')
        if mode in ('screen','multiply'):
            rgb=getattr(ImageChops,mode)(result.convert('RGB'),image.convert('RGB')).convert('RGBA')
            rgb.putalpha(image.getchannel('A'));image=rgb
        elif mode!='source-over':raise ValueError('小头像背景不支持此图层混合方式：'+mode)
        result.alpha_composite(image)
    return result
