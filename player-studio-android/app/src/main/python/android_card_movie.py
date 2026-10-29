"""Phone-local VP9 IVF encoder; no desktop executable or remote service."""
from pathlib import Path
import io,struct,time


def plane_bytes(raw,width,height,row_stride,pixel_stride):
    if row_stride<(width-1)*pixel_stride+1:raise ValueError('手机编码器图像行跨度无效')
    out=bytearray((height-1)*row_stride+(width-1)*pixel_stride+1)
    for y in range(height):
        out[y*row_stride:y*row_stride+width*pixel_stride:pixel_stride]=raw[y*width:(y+1)*width]
    return bytes(out)


def encode(source,destination,ffmpeg,width,height,fps,seconds,crop_x=0,crop_y=0):
    from java import jclass,jarray,jbyte
    from PIL import Image,ImageOps
    from native_movie import ivf_packets
    if (width,height)not in ((182,256),(128,128)) or fps not in (24,30,60) or not 0<seconds<=30:raise ValueError('手机动态卡面尺寸或时长无效')
    if any(type(v)not in (int,float)or not -100<=v<=100 for v in (crop_x,crop_y)):raise ValueError('视频裁切位置应在 -100 至 100 之间')
    target=Path(destination)
    if target.exists():raise ValueError('视频输出已存在')
    Codec=jclass('android.media.MediaCodec');Format=jclass('android.media.MediaFormat')
    Retriever=jclass('android.media.MediaMetadataRetriever');ByteArray=jarray(jbyte)
    reader=Retriever();codec=None;started=False;finished=False;eos_sent=False;frames=0;queued=0;deadline=time.monotonic()+300
    count=round(fps*seconds);packets=[]
    try:
        reader.setDataSource(str(source))
        duration=max(1,int(str(reader.extractMetadata(Retriever.METADATA_KEY_DURATION))))*1000
        fmt=Format.createVideoFormat('video/x-vnd.on2.vp9',width,height)
        fmt.setInteger(Format.KEY_COLOR_FORMAT,2135033992) # COLOR_FormatYUV420Flexible
        fmt.setInteger(Format.KEY_BIT_RATE,max(800000,width*height*fps))
        fmt.setInteger(Format.KEY_FRAME_RATE,fps);fmt.setInteger(Format.KEY_I_FRAME_INTERVAL,1)
        try:codec=Codec.createEncoderByType('video/x-vnd.on2.vp9');codec.configure(fmt,None,None,Codec.CONFIGURE_FLAG_ENCODE);codec.start();started=True
        except Exception as exc:raise ValueError('此手机没有可用的 VP9 编码器；可导入别人已转换好的动态卡面工程')from exc
        info=jclass('android.media.MediaCodec$BufferInfo')()
        def drain(wait=False):
            nonlocal finished,frames
            while True:
                index=codec.dequeueOutputBuffer(info,20000 if wait else 0)
                if index<0:return
                try:
                    if info.size>0 and not info.flags&Codec.BUFFER_FLAG_CODEC_CONFIG:
                        buf=codec.getOutputBuffer(index);buf.position(info.offset);buf.limit(info.offset+info.size)
                        raw=ByteArray(info.size);buf.get(raw)
                        packets.append((round(info.presentationTimeUs*fps/1000000),bytes(raw)));frames+=1
                    if info.flags&Codec.BUFFER_FLAG_END_OF_STREAM:finished=True
                finally:codec.releaseOutputBuffer(index,False)
        with target.open('xb')as output:
            while not finished:
                if time.monotonic()>deadline:raise ValueError('手机视频转换超时，请缩短原视频或降低分辨率')
                index=-1 if eos_sent else codec.dequeueInputBuffer(20000)
                if index>=0:
                    if queued>=count:
                        codec.queueInputBuffer(index,0,0,queued*1000000//fps,Codec.BUFFER_FLAG_END_OF_STREAM);eos_sent=True
                    else:
                        bitmap=None
                        try:
                            stamp=(queued*1000000//fps)%duration
                            if jclass('android.os.Build$VERSION').SDK_INT>=27:
                                bitmap=reader.getScaledFrameAtTime(stamp,Retriever.OPTION_CLOSEST,1024,1024)
                            else:bitmap=reader.getFrameAtTime(stamp,Retriever.OPTION_CLOSEST)
                            if bitmap is None:raise ValueError('手机无法解码这个视频的画面')
                            stream=jclass('java.io.ByteArrayOutputStream')()
                            bitmap.compress(jclass('android.graphics.Bitmap$CompressFormat').PNG,100,stream)
                            with Image.open(io.BytesIO(bytes(stream.toByteArray())))as im:
                                rgb=ImageOps.fit(im.convert('RGB'),(width,height),method=Image.Resampling.LANCZOS,centering=((crop_x+100)/200,(crop_y+100)/200))
                                y,cb,cr=rgb.convert('YCbCr').split()
                                # Android's YUV encoder expects studio-range BT.601.
                                y=y.point(lambda v:round(16+v*219/255))
                                cb=cb.resize((width//2,height//2),Image.Resampling.BOX).point(lambda v:round(128+(v-128)*224/255))
                                cr=cr.resize((width//2,height//2),Image.Resampling.BOX).point(lambda v:round(128+(v-128)*224/255))
                            image=codec.getInputImage(index)
                            if image is None:raise ValueError('手机 VP9 编码器不支持标准 YUV 图像输入')
                            for n,(plane,pixels)in enumerate(zip(image.getPlanes(),(y,cb,cr))):
                                data=plane_bytes(pixels.tobytes(),pixels.width,pixels.height,plane.getRowStride(),plane.getPixelStride())
                                plane.getBuffer().put(ByteArray(data))
                            size=codec.getInputBuffer(index).capacity();codec.queueInputBuffer(index,0,size,queued*1000000//fps,0);queued+=1
                        finally:
                            if bitmap is not None:bitmap.recycle()
                drain(queued>=count)
            if frames!=count or [t for t,_ in packets]!=list(range(count)):raise ValueError('手机编码结果帧数或时间戳不连续')
            output.write(struct.pack('<4sHH4sHHIIII',b'DKIF',0,32,b'VP90',width,height,fps,1,frames,0))
            for stamp,raw in packets:output.write(struct.pack('<IQ',len(raw),stamp)+raw)
        result=ivf_packets(target.read_bytes())
        if len(result['packets'])!=count:raise ValueError('手机视频回读验证失败')
        return result
    except Exception:
        target.unlink(missing_ok=True);raise
    finally:
        if codec is not None:
            try:
                if started:codec.stop()
            finally:codec.release()
        reader.release()


def install():
    import card_movie_import,custom_motion_import
    card_movie_import.encode=encode;custom_motion_import.encode=encode
