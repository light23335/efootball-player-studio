"""Independent, deterministic thumbnail crop shared by APK exports."""
import base64,hashlib,io,json,threading
from PIL import Image,ImageOps,ImageChops


def card_portrait(project,assets,include_underlay=True):
    """Keep the existing large-card portrait composition byte-for-byte."""
    card=project.get('native_card') or {};a=project['appearance'];canvas=Image.new('RGBA',(1200,1720))
    under=next((r for r in card.get('layers',[]) if r['slot']=='f04' and r['kind']=='image'),None)
    if include_underlay and under and card.get('preset_id') and not card.get('custom_motion'):
        with Image.open(assets/under['asset_id']) as im:canvas.alpha_composite(im.convert('RGBA').resize(canvas.size,Image.Resampling.LANCZOS))
    if not a.get('portrait'):raise ValueError('请先选择球员人物图')
    with Image.open(assets/a['portrait']) as im:image=im.convert('RGBA')
    contain=a.get('portrait_fit')=='contain' or card.get('preset_id') and (project.get('native_art',{}).get('portrait') or {}).get('kind')!='portrait'
    scale=min(1200/image.width,1720/image.height) if contain else None;zoom=a.get('photo_zoom',1)
    w=round((image.width*scale if contain else 1200)*zoom);h=round((image.height*scale if contain else 1720)*zoom)
    if max(w,h)>16384:raise ValueError('卡图缩放超过原生导出的处理范围')
    x=round((1200-w)/2+a.get('photo_x',0)*2);y=round(1720-h+a.get('photo_y',0)*2)
    canvas.alpha_composite(image.resize((w,h),Image.Resampling.LANCZOS),(x,y));return canvas

def render(project,assets,fallback,size=512,background=None):
    a=project['appearance'];mode=a.get('thumbnail_mode','card')
    out=background.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS) if background is not None else Image.new('RGBA',(size,size))
    if mode=='card':out.alpha_composite(fallback.resize((size,size),Image.Resampling.LANCZOS));return out
    source=a.get('thumbnail_image') if mode=='image' else a.get('portrait')
    if not source:raise ValueError('请先选择小头像图片，或选择从大图裁切')
    with Image.open(assets/source) as source_image:image=ImageOps.exif_transpose(source_image).convert('RGBA')
    scale=max(size/image.width,size/image.height)*a.get('thumbnail_zoom',1)
    w,h=max(1,round(image.width*scale)),max(1,round(image.height*scale))
    if max(w,h)>32768:raise ValueError('小头像缩放过大，请减小缩放')
    x=round((size-w)/2+a.get('thumbnail_x',0)*size/100)
    y=round((size-h)/2+a.get('thumbnail_y',0)*size/100)
    out.alpha_composite(image.resize((w,h),Image.Resampling.LANCZOS),(x,y))
    return out


class ThumbnailPreview:
    def __init__(self,library):self.library=library;self.lock=threading.Lock();self.cache={}
    def prepare(self,project):
        from thumbnail_background import background,REVISION
        from thumbnail_motion import plan,REVISION as MOTION_REVISION
        from thumbnail_mask import preview_masks,REVISION as MASK_REVISION
        fields={k:v for k,v in project['appearance'].items() if k.startswith(('thumbnail_','photo_')) or k in ('portrait','portrait_fit','background_image','background')}
        key=hashlib.sha256(json.dumps([REVISION,MOTION_REVISION,MASK_REVISION,fields,project.get('native_card'),project.get('native_art')],sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key in self.cache:return self.cache[key]
            assets=self.library.store.root/'assets';fallback=card_portrait(project,assets,include_underlay=False) if fields.get('thumbnail_mode','card')=='card' else None
            backdrop=background(project,self.library);foreground=render(project,assets,fallback)
            mask=None
            if getattr(self.library,'profile',{}).get('game_version')=='V17':
                inner,outer=preview_masks();inner=inner.resize(foreground.size,Image.Resampling.LANCZOS)
                foreground.putalpha(ImageChops.multiply(foreground.getchannel('A'),inner))
                mask=outer.resize(foreground.size,Image.Resampling.LANCZOS)
            image=backdrop.convert('RGBA').resize(foreground.size,Image.Resampling.LANCZOS)
            image.alpha_composite(foreground)
            if mask is not None:image.putalpha(ImageChops.multiply(image.getchannel('A'),mask))
            motion=plan(project,self.library)
            layers=[layer if layer.get('source')=='custom' else {**layer,**self.library.thumbnail_movie(layer['path'])} for layer in motion['layers']]
            def png(im):
                stream=io.BytesIO();im.save(stream,format='PNG');return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')
            value={'revision':motion['revision'],'image':png(image),'background':png(backdrop),'foreground':png(foreground),
                   'animation':{**motion,'layers':layers},'background_linked':True,
                   'note':('小头像背景联动大卡面动画，人物独立叠加。' if any(l['role']=='background' for l in motion['layers']) else
                           '当前预设只提供动态光效，背景使用大卡面静态帧。' if motion['animated'] else
                           '背景跟随大卡面；当前使用静态背景，人像裁切独立保存。')}
            if mask is not None:
                silhouette=Image.new('RGBA',mask.size,'white');silhouette.putalpha(mask)
                value['outer_mask']=png(silhouette)
                value['note']+=' 自建头像已取消左侧人物遮挡，保留原生圆角；游戏文字和卡框颜色在游戏内叠加。'
            if len(self.cache)>=8:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=value;return value
