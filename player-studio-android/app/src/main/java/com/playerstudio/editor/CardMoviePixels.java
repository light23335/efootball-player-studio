package com.playerstudio.editor;

import java.nio.ByteBuffer;

/** Small, Android-independent pixel kernel. Never writes padding or UV gaps. */
public final class CardMoviePixels {
    private CardMoviePixels() {}
    public static int clamp(int n){return Math.max(0,Math.min(255,n));}
    public static void putPlane(ByteBuffer target,byte[] source,int width,int height,int rowStride,int pixelStride) {
        if(width<1||height<1||pixelStride<1||rowStride<(width-1)*pixelStride+1||source.length!=width*height)
            throw new IllegalArgumentException("视频平面布局无效");
        int base=target.position();long end=(long)base+(height-1L)*rowStride+(width-1L)*pixelStride+1;
        if(end>target.limit())throw new IllegalArgumentException("视频平面超出有效缓冲区");
        ByteBuffer view=target.duplicate();
        for(int y=0;y<height;y++) {
            int at=base+y*rowStride;
            if(pixelStride==1){view.position(at);view.put(source,y*width,width);}
            else for(int x=0;x<width;x++)view.put(at+x*pixelStride,source[y*width+x]);
        }
    }
    public static final class Plane {
        final ByteBuffer data;final int width,height,row,pixel,base;
        public Plane(ByteBuffer data,int width,int height,int row,int pixel) {
            this.data=data.duplicate();this.width=width;this.height=height;this.row=row;this.pixel=pixel;this.base=data.position();
            if(width<1||height<1||pixel<1||row<(width-1)*pixel+1||base+(height-1L)*row+(width-1L)*pixel>=data.limit())
                throw new IllegalArgumentException("解码器图像平面不完整");
        }
        double sample(double x,double y) {
            x=Math.max(0,Math.min(width-1,x));y=Math.max(0,Math.min(height-1,y));
            int ix=(int)x,iy=(int)y,jx=Math.min(width-1,ix+1),jy=Math.min(height-1,iy+1);
            double dx=x-ix,dy=y-iy;
            int a=data.get(base+iy*row+ix*pixel)&255,b=data.get(base+iy*row+jx*pixel)&255;
            int c=data.get(base+jy*row+ix*pixel)&255,d=data.get(base+jy*row+jx*pixel)&255;
            return (a+(b-a)*dx)*(1-dy)+(c+(d-c)*dx)*dy;
        }
    }
    public static final class Frame {
        final Plane y,u,v;final int left,top,width,height,rotation,standard,range;
        public Frame(Plane y,Plane u,Plane v,int left,int top,int width,int height,int rotation,int standard,int range) {
            this.y=y;this.u=u;this.v=v;this.left=left;this.top=top;this.width=width;this.height=height;
            this.rotation=((rotation%360)+360)%360;this.standard=standard;this.range=range;
            if(width<1||height<1||left<0||top<0||left+width>y.width||top+height>y.height||this.rotation%90!=0)
                throw new IllegalArgumentException("解码器裁切或旋转信息无效");
        }
    }
    public static double[] crop(int sourceWidth,int sourceHeight,int width,int height,double cx,double cy) {
        if(width<2||height<2||(width&1)!=0||(height&1)!=0||!Double.isFinite(cx)||!Double.isFinite(cy)||Math.abs(cx)>100||Math.abs(cy)>100)
            throw new IllegalArgumentException("视频裁切信息无效");
        double w=sourceWidth,h=sourceHeight;
        if(w/h>(double)width/height)w=h*width/height;else h=w*height/width;
        return new double[]{(sourceWidth-w)*(cx+100)/200,(sourceHeight-h)*(cy+100)/200,w,h};
    }
    /** Decoder YUV -> sampled BT.601 limited I420; rotations are applied once. */
    public static byte[] fit(Frame f,int width,int height,double cx,double cy) {
        int dw=f.rotation%180==0?f.width:f.height,dh=f.rotation%180==0?f.height:f.width;
        double[] crop=crop(dw,dh,width,height,cx,cy);
        int area=width*height,quarter=area/4;
        byte[] out=new byte[area+2*quarter];double[] us=new double[quarter],vs=new double[quarter];
        for(int y=0;y<height;y++)for(int x=0;x<width;x++) {
            double dx=crop[0]+(x+.5)*crop[2]/width-.5,dy=crop[1]+(y+.5)*crop[3]/height-.5;
            double sx=dx,sy=dy;
            if(f.rotation==90){sx=dy;sy=f.height-1-dx;}
            else if(f.rotation==180){sx=f.width-1-dx;sy=f.height-1-dy;}
            else if(f.rotation==270){sx=f.width-1-dy;sy=dx;}
            sx+=f.left;sy+=f.top;
            double yy=f.y.sample(sx,sy),uu=f.u.sample(sx/2,sy/2),vv=f.v.sample(sx/2,sy/2);
            double luma=(yy-(f.range==1?0:16))/(f.range==1?255:219);
            double cb=(uu-128)/(f.range==1?255:224),cr=(vv-128)/(f.range==1?255:224);
            // Android values: BT709=1, BT601_PAL=2, BT601_NTSC=4.
            double r,g,b;
            if(f.standard==1){r=luma+1.5748*cr;g=luma-.187324*cb-.468124*cr;b=luma+1.8556*cb;}
            else{r=luma+1.402*cr;g=luma-.344136*cb-.714136*cr;b=luma+1.772*cb;}
            r=Math.max(0,Math.min(1,r));g=Math.max(0,Math.min(1,g));b=Math.max(0,Math.min(1,b));
            out[y*width+x]=(byte)clamp((int)Math.round(16+65.481*r+128.553*g+24.966*b));
            int ci=(y/2)*(width/2)+x/2;
            us[ci]+=128-37.797*r-74.203*g+112*b;vs[ci]+=128+112*r-93.786*g-18.214*b;
        }
        for(int i=0;i<quarter;i++){out[area+i]=(byte)clamp((int)Math.round(us[i]/4));out[area+quarter+i]=(byte)clamp((int)Math.round(vs[i]/4));}
        return out;
    }
    public static byte[] argb(int[] pixels,int width,int height) {
        int area=width*height;if(pixels.length!=area||(width&1)!=0||(height&1)!=0)throw new IllegalArgumentException("RGB 图像尺寸无效");
        byte[] out=new byte[area*3/2];
        for(int y=0;y<height;y+=2)for(int x=0;x<width;x+=2) {
            double us=0,vs=0;
            for(int dy=0;dy<2;dy++)for(int dx=0;dx<2;dx++) {
                int at=(y+dy)*width+x+dx,p=pixels[at];double r=(p>>>16)&255,g=(p>>>8)&255,b=p&255;
                out[at]=(byte)clamp((int)Math.round(16+(65.481*r+128.553*g+24.966*b)/255));
                us+=128+(-37.797*r-74.203*g+112*b)/255;vs+=128+(112*r-93.786*g-18.214*b)/255;
            }
            int at=(y/2)*(width/2)+x/2;out[area+at]=(byte)clamp((int)Math.round(us/4));out[area+area/4+at]=(byte)clamp((int)Math.round(vs/4));
        }
        return out;
    }
}
