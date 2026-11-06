"""Phone-local VP9 conversion. Pixel work stays in the Android runtime."""
from pathlib import Path
import json

BACKEND='android-shared-yuv-bt601-v3'


def plane_bytes(raw,width,height,row_stride,pixel_stride):
    """Legacy standalone layout helper; never copy its padding to an Image.

    Production writes use CardMoviePixels.putPlane, which preserves UV gaps.
    """
    if row_stride<(width-1)*pixel_stride+1:raise ValueError('手机编码器图像行跨度无效')
    out=bytearray((height-1)*row_stride+(width-1)*pixel_stride+1)
    for y in range(height):out[y*row_stride:y*row_stride+width*pixel_stride:pixel_stride]=raw[y*width:(y+1)*width]
    return bytes(out)


def encode_batch(source,folder,specs,context=None):
    from java import jclass
    from native_movie import ivf_packets
    job=jclass('com.playerstudio.editor.CardMovieTranscoder')()
    if context is not None:context.native_job(job);context.check_cancel()
    try:
        metadata=json.loads(str(job.transcode(str(source),json.dumps(specs,separators=(',',':')),str(folder))))
        for spec in specs:
            path=Path(folder)/(spec['role']+'.ivf');result=ivf_packets(path.read_bytes())
            if(len(result['packets'])!=spec['frames']or(result['width'],result['height'])!=(spec['width'],spec['height'])or
                [t for t,_,_ in result['packets']]!=list(range(spec['frames']))):raise ValueError('手机视频回读的帧数、尺寸或时间戳不匹配')
        if context is not None:context.check_cancel()
        return metadata
    finally:
        if context is not None:context.native_job(None)


def encode(source,destination,ffmpeg,width,height,fps,seconds,crop_x=0,crop_y=0,context=None):
    import math,tempfile
    from native_movie import ivf_packets
    if(width,height)not in((182,256),(128,128))or fps not in(24,30,60)or not 0<seconds<=30:raise ValueError('手机动态卡面尺寸或时长无效')
    if any(type(v)not in(int,float)or not math.isfinite(v)or not -100<=v<=100 for v in(crop_x,crop_y)):raise ValueError('视频裁切位置应在 -100 至 100 之间')
    target=Path(destination)
    if target.exists():raise ValueError('视频输出已存在')
    role='large'if width==182 else'mini'
    with tempfile.TemporaryDirectory(prefix='vp9-',dir=target.parent)as tmp:
        folder=Path(tmp);spec={'role':role,'width':width,'height':height,'fps':fps,'frames':round(fps*seconds),'crop_x':crop_x,'crop_y':crop_y}
        encode_batch(source,folder,[spec],context);(folder/(role+'.ivf')).replace(target)
    return ivf_packets(target.read_bytes())


def install():
    import card_movie_import,custom_motion_import
    card_movie_import.encode=encode;custom_motion_import.encode=encode
    custom_motion_import.BATCH_ENCODER=encode_batch;custom_motion_import.BACKEND=BACKEND
