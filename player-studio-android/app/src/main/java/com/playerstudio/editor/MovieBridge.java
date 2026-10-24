package com.playerstudio.editor;

import android.media.*;
import java.io.*;
import java.nio.*;
import java.nio.channels.*;
import org.jcodec.codecs.mpeg12.*;
import org.jcodec.common.model.*;
import org.jcodec.containers.mps.MPEGPacket;
import org.json.JSONObject;

/** Original game video is unchanged; only the editor preview is transcoded. */
public final class MovieBridge {
    private final MediaCodec codec;
    private final MediaMuxer muxer;
    private final int width,height,fps;
    private final MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
    private int track=-1,frames;
    private boolean muxerStarted,finished;
    private MovieBridge(String output,int width,int height,int fps) throws Exception {
        this.width=width;this.height=height;this.fps=fps;
        MediaFormat format=MediaFormat.createVideoFormat("video/x-vnd.on2.vp8",width,height);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        format.setInteger(MediaFormat.KEY_BIT_RATE,Math.max(4000000,width*height*fps*2));
        format.setInteger(MediaFormat.KEY_FRAME_RATE,fps);format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL,1);
        codec=MediaCodec.createEncoderByType("video/x-vnd.on2.vp8");codec.configure(format,null,null,MediaCodec.CONFIGURE_FLAG_ENCODE);codec.start();
        muxer=new MediaMuxer(output,MediaMuxer.OutputFormat.MUXER_OUTPUT_WEBM);
    }
    private void drain(boolean wait) throws Exception {
        int empty=0;
        while(!finished) {
            int index=codec.dequeueOutputBuffer(info,wait?20000:0);
            if(index==MediaCodec.INFO_TRY_AGAIN_LATER){if(!wait)return;if(++empty>1000)throw new IOException("手机视频编码超时");continue;}
            if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){track=muxer.addTrack(codec.getOutputFormat());muxer.start();muxerStarted=true;continue;}
            if(index>=0) {
                ByteBuffer buffer=codec.getOutputBuffer(index);
                if((info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)!=0)info.size=0;
                if(info.size>0){if(!muxerStarted)throw new IOException("视频轨道尚未准备");buffer.position(info.offset);buffer.limit(info.offset+info.size);muxer.writeSampleData(track,buffer,info);}
                finished=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;codec.releaseOutputBuffer(index,false);
            }
        }
    }
    private void put(Picture picture) throws Exception {
        int index;
        while((index=codec.dequeueInputBuffer(20000))<0)drain(false);
        Image image=codec.getInputImage(index);
        if(image==null)throw new IOException("手机 VP8 编码器不提供 YUV 输入");
        Image.Plane[] planes=image.getPlanes();
        for(int plane=0;plane<3;plane++) {
            int w=plane==0?width:width/2,h=plane==0?height:height/2;
            byte[] source=picture.getData()[plane];int sourceStride=picture.getPlaneWidth(plane);
            ByteBuffer dest=planes[plane].getBuffer();int rowStride=planes[plane].getRowStride(),pixelStride=planes[plane].getPixelStride();
            for(int y=0;y<h;y++)for(int x=0;x<w;x++)dest.put(y*rowStride+x*pixelStride,(byte)(source[y*sourceStride+x]+128));
        }
        int size=codec.getInputBuffer(index).capacity();codec.queueInputBuffer(index,0,size,(frames++)*1000000L/fps,0);drain(false);
    }
    private void complete() throws Exception {
        int index;while((index=codec.dequeueInputBuffer(20000))<0)drain(false);
        codec.queueInputBuffer(index,0,0,frames*1000000L/fps,MediaCodec.BUFFER_FLAG_END_OF_STREAM);drain(true);
    }
    private void close(){try{codec.stop();}catch(Exception ignored){}codec.release();try{if(muxerStarted)muxer.stop();}catch(Exception ignored){}muxer.release();}
    public static String transcode(String source,String output) throws Exception {
        byte[] header=new byte[8];try(InputStream in=new FileInputStream(source)){if(in.read(header)!=8)throw new IOException("原版 MPEG-2 序列头不完整");}
        int width=((header[4]&255)<<4)|((header[5]&255)>>4),height=((header[5]&15)<<8)|(header[6]&255);
        int[] rates={0,24,24,25,30,30,50,60,60};int code=header[7]&15;
        if(width<2||height<2||width>4096||height>4096||(width&1)!=0||(height&1)!=0||code<1||code>8)throw new IOException("原版视频尺寸或帧率不受支持");
        MovieBridge encoder=new MovieBridge(output,width,height,rates[code]);MPEGDecoder decoder=new MPEGDecoder();Picture held=null;
        try(FileInputStream file=new FileInputStream(source)) {
            MPEGES stream=new MPEGES(file.getChannel(),65536);MPEGPacket packet;int decoded=0;
            while((packet=stream.getFrame())!=null) {
                if(++decoded>18000)throw new IOException("原版视频帧数超过限制");
                // JCodec's MPEG decoder requires luma-sized backing arrays for
                // every plane, including the subsampled chroma planes.
                int planeSize=((width+15)&~15)*((height+15)&~15);
                Picture picture=decoder.decodeFrame(packet.getData().duplicate(),new byte[3][planeSize]);
                int type=MPEGDecoder.getPictureHeader(packet.getData().duplicate()).picture_coding_type;
                if(type<=2){if(held!=null)encoder.put(held);held=picture;}else encoder.put(picture);
            }
            if(held!=null)encoder.put(held);encoder.complete();
            return new JSONObject().put("codec","VP8").put("width",width).put("height",height).put("frames",encoder.frames).put("preview_transcoded",true).toString();
        }finally{encoder.close();}
    }
}
