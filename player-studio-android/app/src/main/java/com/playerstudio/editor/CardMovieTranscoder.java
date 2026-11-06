package com.playerstudio.editor;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMetadataRetriever;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.*;
import java.util.*;

/** Decode once, generate both crops locally, then encode bounded VP9 streams.
 * Pixel data never crosses the Java/Python boundary. No PNG intermediate.
 */
public final class CardMovieTranscoder {
    private volatile boolean cancelled;
    private final JSONObject progress=new JSONObject();
    private final JSONObject timings=new JSONObject();
    private long deadline,started;
    private int sampled,decoded;
    private String decoderName="",mode="";
    public CardMovieTranscoder() {}
    public void cancel(){cancelled=true;}
    public synchronized String status(){return progress.toString();}
    private synchronized void update(String stage,String role,int frames,int total) throws Exception {
        progress.put("stage",stage).put("role",role).put("frames",frames).put("frame_total",total)
            .put("decoded_frames",decoded).put("sample_timestamps",sampled).put("decode_mode",mode)
            .put("elapsed_ms",(System.nanoTime()-started)/1000000).put("cancel_requested",cancelled);
    }
    private void check() throws IOException {
        if(cancelled)throw new InterruptedIOException("视频导入已取消");
        if(System.nanoTime()>deadline)throw new IOException("视频转换超时，请缩短原视频或降低源视频分辨率");
    }
    private static int optional(MediaFormat format,String key,int fallback) {
        try{return format.containsKey(key)?format.getInteger(key):fallback;}catch(Exception e){return fallback;}
    }
    private static final class Spec implements Closeable {
        final String role;final int width,height,fps,frames,bytes;final double cx,cy;
        final File ivf,raw;final RandomAccessFile pixels;
        Spec(JSONObject value,File folder) throws Exception {
            role=value.getString("role");width=value.getInt("width");height=value.getInt("height");fps=value.getInt("fps");frames=value.getInt("frames");
            cx=value.optDouble("crop_x",0);cy=value.optDouble("crop_y",0);
            if(!(role.equals("large")&&width==182&&height==256||role.equals("mini")&&width==128&&height==128)||(fps!=24&&fps!=30&&fps!=60)||frames<1||frames>fps*30)
                throw new IOException("卡面转换规格不受支持");
            CardMoviePixels.crop(width,height,width,height,cx,cy);
            bytes=width*height*3/2;ivf=new File(folder,role+".ivf");raw=new File(folder,role+".yuv");
            if(ivf.exists()||raw.exists())throw new IOException("视频工作文件已经存在");
            pixels=new RandomAccessFile(raw,"rw");pixels.setLength((long)bytes*frames);
        }
        void put(int index,byte[] data)throws IOException{if(data.length!=bytes)throw new IOException("像素长度错误");pixels.seek((long)index*bytes);pixels.write(data);}
        void reset()throws IOException{pixels.setLength(0);pixels.setLength((long)bytes*frames);}
        public void close()throws IOException{pixels.close();raw.delete();}
    }
    private static final class Request {
        final Spec spec;final int index;
        Request(Spec spec,int index){this.spec=spec;this.index=index;}
    }
    private static TreeMap<Long,List<Request>> plan(List<Spec> specs,long duration) {
        TreeMap<Long,List<Request>> map=new TreeMap<>();
        for(Spec s:specs)for(int i=0;i<s.frames;i++) {
            long stamp=(i*1000000L/s.fps)%duration;
            map.computeIfAbsent(stamp,k->new ArrayList<>()).add(new Request(s,i));
        }
        return map;
    }
    private static ParcelFileDescriptor source(String path)throws Exception{return NativeFiles.openVideoDescriptor(path);}
    private void publishSamples(TreeMap<Long,List<Request>> requests,long boundary,CardMoviePixels.Frame frame) throws Exception {
        Map<Spec,byte[]> converted=new HashMap<>();
        while(!requests.isEmpty()&&requests.firstKey()<=boundary) {
            check();List<Request> rows=requests.pollFirstEntry().getValue();
            for(Request r:rows) {
                byte[] pixels=converted.get(r.spec);
                if(pixels==null){pixels=CardMoviePixels.fit(frame,r.spec.width,r.spec.height,r.spec.cx,r.spec.cy);converted.put(r.spec,pixels);}
                r.spec.put(r.index,pixels);
            }
            sampled++;update("decode","both",sampled,sampled+requests.size());
        }
    }
    private CardMoviePixels.Frame frame(Image image,MediaFormat format,int rotation) throws IOException {
        if(image.getFormat()!=android.graphics.ImageFormat.YUV_420_888)throw new IOException("解码器图像不是标准 8 位 YUV420");
        Image.Plane[] ps=image.getPlanes();if(ps.length!=3)throw new IOException("解码器不提供三个 YUV 平面");
        CardMoviePixels.Plane[] planes=new CardMoviePixels.Plane[3];
        for(int p=0;p<3;p++)planes[p]=new CardMoviePixels.Plane(ps[p].getBuffer(),p==0?image.getWidth():(image.getWidth()+1)/2,
            p==0?image.getHeight():(image.getHeight()+1)/2,ps[p].getRowStride(),ps[p].getPixelStride());
        Rect crop=image.getCropRect();
        int standard=optional(format,MediaFormat.KEY_COLOR_STANDARD,image.getHeight()>=720?1:4);
        if(standard==6)throw new IOException("BT.2020 视频需要系统 RGB 解码路径");
        return new CardMoviePixels.Frame(planes[0],planes[1],planes[2],crop.left,crop.top,crop.width(),crop.height(),rotation,standard,
            optional(format,MediaFormat.KEY_COLOR_RANGE,MediaFormat.COLOR_RANGE_LIMITED));
    }
    private void sequential(String input,List<Spec> specs) throws Exception {
        MediaExtractor extractor=new MediaExtractor();MediaCodec decoder=null;Image previousImage=null;int previousIndex=-1;
        try(ParcelFileDescriptor fd=source(input)) {
            extractor.setDataSource(fd.getFileDescriptor());MediaFormat fmt=null;int track=-1;
            for(int i=0;i<extractor.getTrackCount();i++)if(extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME).startsWith("video/")){track=i;fmt=extractor.getTrackFormat(i);break;}
            if(fmt==null)throw new IOException("视频中没有可读取的视频轨道");
            extractor.selectTrack(track);long origin=Math.max(0,extractor.getSampleTime());
            long duration=fmt.containsKey(MediaFormat.KEY_DURATION)?fmt.getLong(MediaFormat.KEY_DURATION):0;
            if(duration<1)throw new IOException("无法读取视频时长");
            int rotation=optional(fmt,MediaFormat.KEY_ROTATION,0);fmt.setInteger(MediaFormat.KEY_ROTATION,0);
            fmt.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
            decoder=MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME));decoder.configure(fmt,null,null,0);decoder.start();
            decoderName=decoder.getName();mode="sequential-yuv";
            synchronized(this){progress.put("decoder",decoderName).put("source_width",fmt.getInteger(MediaFormat.KEY_WIDTH))
                .put("source_height",fmt.getInteger(MediaFormat.KEY_HEIGHT)).put("rotation",rotation).put("duration_us",duration);}
            TreeMap<Long,List<Request>> requests=plan(specs,duration);MediaFormat output=fmt;
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();boolean inputDone=false,outputDone=false;long prevPts=0;
            while(!outputDone&&!requests.isEmpty()) {
                check();
                if(!inputDone) {
                    int ix=decoder.dequeueInputBuffer(1000);
                    if(ix>=0) {
                        ByteBuffer buffer=decoder.getInputBuffer(ix);int size=extractor.readSampleData(buffer,0);
                        if(size<0){decoder.queueInputBuffer(ix,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);inputDone=true;}
                        else{decoder.queueInputBuffer(ix,0,size,extractor.getSampleTime(),0);extractor.advance();}
                    }
                }
                int ix=decoder.dequeueOutputBuffer(info,10000);
                if(ix==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){output=decoder.getOutputFormat();continue;}
                if(ix<0)continue;
                boolean retained=false;
                try {
                    if((info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0)outputDone=true;
                    if(info.size>0&&(info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0) {
                        Image current=decoder.getOutputImage(ix);
                        if(current==null)throw new IOException("解码器不提供可读取的 YUV 图像");
                        long pts=Math.max(0,info.presentationTimeUs-origin);
                        if(previousImage!=null) {
                            if(pts<prevPts){current.close();throw new IOException("解码输出时间戳不连续");}
                            publishSamples(requests,prevPts+(pts-prevPts)/2,frame(previousImage,output,rotation));
                            previousImage.close();previousImage=null;decoder.releaseOutputBuffer(previousIndex,false);previousIndex=-1;
                        }
                        previousImage=current;previousIndex=ix;prevPts=pts;retained=true;decoded++;
                    }
                }finally{if(!retained)decoder.releaseOutputBuffer(ix,false);}
            }
            if(!requests.isEmpty()) {
                if(previousImage==null)throw new IOException("视频没有解码出有效画面");
                publishSamples(requests,Long.MAX_VALUE,frame(previousImage,output,rotation));
            }
        }finally {
            if(previousImage!=null)try{previousImage.close();}catch(Exception ignored){}
            if(decoder!=null){try{if(previousIndex>=0)decoder.releaseOutputBuffer(previousIndex,false);}catch(Exception ignored){}
                try{decoder.stop();}catch(Exception ignored){}decoder.release();}
            extractor.release();
        }
    }
    /** Vendor decoder fallback; still one shared sampling pass and no PNG. */
    private void retriever(String input,List<Spec> specs) throws Exception {
        MediaMetadataRetriever reader=new MediaMetadataRetriever();
        try(ParcelFileDescriptor fd=source(input)) {
            reader.setDataSource(fd.getFileDescriptor());
            long duration=Long.parseLong(reader.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION))*1000L;
            if(duration<1)throw new IOException("视频时长无效");
            int sw=Integer.parseInt(reader.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH));
            int sh=Integer.parseInt(reader.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT));
            String r=reader.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION);int rotation=r==null?0:Integer.parseInt(r);
            if(rotation%180!=0){int temp=sw;sw=sh;sh=temp;}
            double factor=0;for(Spec s:specs)factor=Math.max(factor,Math.max((double)s.width/sw,(double)s.height/sh));
            int rw=Math.max(2,(int)Math.ceil(sw*factor)),rh=Math.max(2,(int)Math.ceil(sh*factor));
            mode="shared-scaled-bitmap";sampled=0;decoded=0;
            synchronized(this){progress.put("decode_width",rw).put("decode_height",rh);}
            TreeMap<Long,List<Request>> requests=plan(specs,duration);Paint paint=new Paint(Paint.FILTER_BITMAP_FLAG);
            Map<Spec,Bitmap> canvases=new HashMap<>();Map<Spec,int[]> pixels=new HashMap<>();
            try {
                for(Spec s:specs){s.reset();canvases.put(s,Bitmap.createBitmap(s.width,s.height,Bitmap.Config.ARGB_8888));pixels.put(s,new int[s.width*s.height]);}
                while(!requests.isEmpty()) {
                    check();Map.Entry<Long,List<Request>> item=requests.pollFirstEntry();
                    Bitmap bitmap=Build.VERSION.SDK_INT>=27?reader.getScaledFrameAtTime(item.getKey(),MediaMetadataRetriever.OPTION_CLOSEST,rw,rh):reader.getFrameAtTime(item.getKey(),MediaMetadataRetriever.OPTION_CLOSEST);
                    if(bitmap==null)throw new IOException("系统无法读取视频画面");
                    try {
                        Map<Spec,byte[]> converted=new HashMap<>();
                        for(Request req:item.getValue()) {
                            Spec s=req.spec;byte[] yuv=converted.get(s);
                            if(yuv==null) {
                                double[] c=CardMoviePixels.crop(bitmap.getWidth(),bitmap.getHeight(),s.width,s.height,s.cx,s.cy);
                                Bitmap target=canvases.get(s);Canvas canvas=new Canvas(target);canvas.drawColor(0xff000000);
                                android.graphics.Matrix matrix=new android.graphics.Matrix();
                                matrix.setRectToRect(new RectF((float)c[0],(float)c[1],(float)(c[0]+c[2]),(float)(c[1]+c[3])),new RectF(0,0,s.width,s.height),android.graphics.Matrix.ScaleToFit.FILL);
                                canvas.drawBitmap(bitmap,matrix,paint);int[] rgb=pixels.get(s);target.getPixels(rgb,0,s.width,0,0,s.width,s.height);
                                yuv=CardMoviePixels.argb(rgb,s.width,s.height);converted.put(s,yuv);
                            }
                            s.put(req.index,yuv);
                        }
                    }finally{bitmap.recycle();}
                    sampled++;decoded++;update("decode","both",sampled,sampled+requests.size());
                }
            }finally{for(Bitmap bitmap:canvases.values())bitmap.recycle();}
        }finally{reader.release();}
    }
    private static boolean hardware(MediaCodecInfo info) {
        if(Build.VERSION.SDK_INT>=29)return info.isHardwareAccelerated();
        String n=info.getName().toLowerCase(Locale.ROOT);return !(n.startsWith("omx.google.")||n.startsWith("c2.android.")||n.contains(".sw."));
    }
    private static List<MediaCodecInfo> encoders(Spec spec) {
        List<MediaCodecInfo> result=new ArrayList<>();
        for(MediaCodecInfo info:new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            if(!info.isEncoder())continue;
            for(String mime:info.getSupportedTypes())if(mime.equalsIgnoreCase("video/x-vnd.on2.vp9"))try {
                MediaCodecInfo.CodecCapabilities caps=info.getCapabilitiesForType(mime);boolean yuv=false;
                for(int color:caps.colorFormats)if(color==MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)yuv=true;
                if(yuv&&caps.getVideoCapabilities().isSizeSupported(spec.width,spec.height))result.add(info);
            }catch(Exception ignored){}
        }
        result.sort(Comparator.comparingInt(c->hardware(c)?0:1));return result;
    }
    private JSONObject encode(Spec s) throws Exception {
        List<String> errors=new ArrayList<>();
        for(MediaCodecInfo candidate:encoders(s)) {
            check();MediaCodec codec=null;boolean startedCodec=false;
            try {
                MediaFormat format=MediaFormat.createVideoFormat("video/x-vnd.on2.vp9",s.width,s.height);
                format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
                format.setInteger(MediaFormat.KEY_BIT_RATE,Math.max(800000,s.width*s.height*s.fps));format.setInteger(MediaFormat.KEY_FRAME_RATE,s.fps);
                format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,1);
                format.setInteger(MediaFormat.KEY_COLOR_STANDARD,MediaFormat.COLOR_STANDARD_BT601_NTSC);
                format.setInteger(MediaFormat.KEY_COLOR_RANGE,MediaFormat.COLOR_RANGE_LIMITED);
                format.setInteger(MediaFormat.KEY_COLOR_TRANSFER,MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
                codec=MediaCodec.createByCodecName(candidate.getName());codec.configure(format,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE);codec.start();startedCodec=true;
                synchronized(this){progress.put("encoder",candidate.getName()).put("hardware_accelerated",hardware(candidate));}
                try(FileOutputStream output=new FileOutputStream(s.ivf)) {
                    ByteBuffer header=ByteBuffer.allocate(32).order(ByteOrder.LITTLE_ENDIAN);
                    header.put(new byte[]{'D','K','I','F'}).putShort((short)0).putShort((short)32).put(new byte[]{'V','P','9','0'})
                        .putShort((short)s.width).putShort((short)s.height).putInt(s.fps).putInt(1).putInt(s.frames).putInt(0);output.write(header.array());
                    MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();int queued=0,written=0;boolean eos=false,finished=false;
                    byte[] yuv=new byte[s.bytes];byte[] y=new byte[s.width*s.height],u=new byte[s.width*s.height/4],v=new byte[u.length];
                    s.pixels.seek(0);
                    while(!finished) {
                        check();
                        if(!eos) {
                            int index=codec.dequeueInputBuffer(1000);
                            if(index>=0) {
                                if(queued==s.frames){codec.queueInputBuffer(index,0,0,queued*1000000L/s.fps,MediaCodec.BUFFER_FLAG_END_OF_STREAM);eos=true;}
                                else {
                                    s.pixels.readFully(yuv);System.arraycopy(yuv,0,y,0,y.length);System.arraycopy(yuv,y.length,u,0,u.length);System.arraycopy(yuv,y.length+u.length,v,0,v.length);
                                    Image image=codec.getInputImage(index);if(image==null)throw new IOException("编码器不提供标准 YUV 图像输入");
                                    Image.Plane[] ps=image.getPlanes();if(ps.length!=3)throw new IOException("编码器 YUV 平面数量不正确");
                                    byte[][] channels={y,u,v};
                                    for(int p=0;p<3;p++)CardMoviePixels.putPlane(ps[p].getBuffer(),channels[p],p==0?s.width:s.width/2,p==0?s.height:s.height/2,ps[p].getRowStride(),ps[p].getPixelStride());
                                    codec.queueInputBuffer(index,0,codec.getInputBuffer(index).capacity(),queued*1000000L/s.fps,0);queued++;
                                }
                            }
                        }
                        int index=codec.dequeueOutputBuffer(info,10000);
                        if(index>=0)try {
                            if(info.size>0&&(info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0) {
                                long stamp=Math.round(info.presentationTimeUs*s.fps/1000000.0);
                                if(stamp!=written)throw new IOException("编码器输出帧时间戳不连续");
                                ByteBuffer raw=codec.getOutputBuffer(index);raw.position(info.offset);raw.limit(info.offset+info.size);byte[] packet=new byte[info.size];raw.get(packet);
                                output.write(ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN).putInt(packet.length).putLong(stamp).array());output.write(packet);written++;
                                update("encode",s.role,written,s.frames);
                            }
                            if((info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0)finished=true;
                        }finally{codec.releaseOutputBuffer(index,false);}
                    }
                    if(written!=s.frames)throw new IOException("编码结果帧数不匹配");
                    return new JSONObject().put("encoder",candidate.getName()).put("hardware_accelerated",hardware(candidate)).put("frames",written)
                        .put("width",s.width).put("height",s.height).put("color_standard","BT.601 NTSC").put("color_range","limited").put("color_transfer","SDR")
                        .put("previous_encoder_failures",new JSONArray(errors));
                }
            }catch(Exception e){s.ivf.delete();check();errors.add(candidate.getName()+": "+e.getClass().getSimpleName());}
            finally{if(codec!=null){try{if(startedCodec)codec.stop();}catch(Exception ignored){}codec.release();}}
        }
        throw new IOException("此手机没有能处理目标尺寸和 YUV 输入的 VP9 编码器："+errors);
    }
    public String transcode(String source,String specifications,String directory)throws Exception {
        if(started!=0)throw new IOException("视频转换会话不可重复启动");
        started=System.nanoTime();deadline=started+600000000000L;
        File folder=new File(directory).getCanonicalFile();if(!folder.isDirectory())throw new IOException("视频临时目录不存在");
        List<Spec> specs=new ArrayList<>();JSONObject result=new JSONObject();
        try {
            JSONArray rows=new JSONArray(specifications);if(rows.length()<1||rows.length()>2)throw new IOException("视频转换目标数量无效");
            Set<String> roles=new HashSet<>();for(int i=0;i<rows.length();i++){Spec s=new Spec(rows.getJSONObject(i),folder);if(!roles.add(s.role)){s.close();throw new IOException("转换目标重复");}specs.add(s);}
            update("decode","both",0,0);long at=System.nanoTime();
            try{sequential(source,specs);}
            catch(Exception e){check();synchronized(this){progress.put("decoder_fallback",e.getClass().getSimpleName()+": "+String.valueOf(e.getMessage()));}retriever(source,specs);}
            timings.put("decode_and_crop_ms",(System.nanoTime()-at)/1000000);
            for(Spec s:specs){check();at=System.nanoTime();result.put(s.role,encode(s));timings.put(s.role+"_encode_ms",(System.nanoTime()-at)/1000000);}
            update("encoded","both",specs.stream().mapToInt(s->s.frames).sum(),specs.stream().mapToInt(s->s.frames).sum());
            return new JSONObject().put("roles",result).put("timings",timings).put("decode",new JSONObject(status())).put("png_roundtrips",0).put("shared_source_decode",true).toString();
        }catch(Exception e){for(Spec s:specs)s.ivf.delete();throw e;}
        finally{for(Spec s:specs)try{s.close();}catch(Exception ignored){}}
    }
}
