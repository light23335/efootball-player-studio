import com.playerstudio.editor.CardMoviePixels;
import java.nio.ByteBuffer;
import java.util.Arrays;

public class CardMoviePixelsTest {
 static int checks=0;
 static void check(boolean value,String name){checks++;if(!value)throw new AssertionError(name);}
 static void uv(boolean nv21,boolean direct) {
  int width=4,height=3,row=12;ByteBuffer shared=direct?ByteBuffer.allocateDirect(row*height):ByteBuffer.allocate(row*height);
  for(int i=0;i<shared.capacity();i++)shared.put(i,(byte)0x7d);
  ByteBuffer u=shared.duplicate(),v=shared.duplicate();u.position(nv21?1:0);v.position(nv21?0:1);
  u.limit(row*(height-1)+(width-1)*2+(nv21?2:1));v.limit(row*(height-1)+(width-1)*2+(nv21?1:2));
  byte[] us=new byte[width*height],vs=new byte[width*height];for(int i=0;i<us.length;i++){us[i]=(byte)(90+i);vs[i]=(byte)(140+i);}
  CardMoviePixels.putPlane(u,us,width,height,row,2);CardMoviePixels.putPlane(v,vs,width,height,row,2);
  for(int y=0;y<height;y++)for(int x=0;x<width;x++){
   check(shared.get(y*row+x*2+(nv21?1:0))==us[y*width+x],"U preserved");
   check(shared.get(y*row+x*2+(nv21?0:1))==vs[y*width+x],"V preserved");
  }
  for(int y=0;y<height;y++)for(int x=8;x<row;x++)check(shared.get(y*row+x)==0x7d,"padding preserved");
  check(u.position()==(nv21?1:0)&&v.position()==(nv21?0:1),"caller buffer positions preserved");
 }
 static CardMoviePixels.Frame grey(int[] values,int w,int h,int rotation,int range) {
  byte[] y=new byte[values.length];for(int i=0;i<y.length;i++)y[i]=(byte)values[i];
  byte[] chroma=new byte[w*h/4];Arrays.fill(chroma,(byte)128);
  return new CardMoviePixels.Frame(new CardMoviePixels.Plane(ByteBuffer.wrap(y),w,h,w,1),
   new CardMoviePixels.Plane(ByteBuffer.wrap(chroma),w/2,h/2,w/2,1),new CardMoviePixels.Plane(ByteBuffer.wrap(chroma),w/2,h/2,w/2,1),0,0,w,h,rotation,4,range);
 }
 public static void main(String[] args) {
  uv(false,false);uv(true,false);uv(false,true);uv(true,true);
  int[] rgb={0xffffff,0,0xff0000,0x00ff00,0x0000ff,0xffff00,0x00ffff,0xff00ff};
  int[][] expected={{235,128,128},{16,128,128},{81,90,240},{145,54,34},{41,240,110},{210,16,146},{170,166,16},{106,202,222}};
  for(int i=0;i<rgb.length;i++) {
   int[] solid={rgb[i],rgb[i],rgb[i],rgb[i]};byte[] out=CardMoviePixels.argb(solid,2,2);
   for(int j=0;j<4;j++)check(Math.abs((out[j]&255)-expected[i][0])<=1,"colour bar luma "+i);
   check(Math.abs((out[4]&255)-expected[i][1])<=1,"colour bar U "+i);
   check(Math.abs((out[5]&255)-expected[i][2])<=1,"colour bar V "+i);
  }
  byte[] full=CardMoviePixels.fit(grey(new int[]{0,255,0,255},2,2,0,1),2,2,0,0);
  check((full[0]&255)==16&&(full[1]&255)==235,"full to limited range");
  int[] vals={20,40,60,80,100,120,140,160};byte[] rotated=CardMoviePixels.fit(grey(vals,2,4,90,2),4,2,0,0);
  int[] right={140,100,60,20,160,120,80,40};
  for(int i=0;i<right.length;i++)check(Math.abs((rotated[i]&255)-right[i])<=1,"rotation "+i);
  int[] wide={20,30,40,50,60,70,80,90,20,30,40,50,60,70,80,90};
  byte[] left=CardMoviePixels.fit(grey(wide,8,2,0,2),2,2,-100,0),r=CardMoviePixels.fit(grey(wide,8,2,0,2),2,2,100,0);
  check((left[0]&255)==20&&(r[0]&255)==80,"crop endpoints");
  ByteBuffer shortBuffer=ByteBuffer.allocate(4);boolean bad=false;
  try{CardMoviePixels.putPlane(shortBuffer,new byte[4],2,2,4,2);}catch(IllegalArgumentException e){bad=true;}check(bad,"invalid layout rejected");
  System.out.println("{\"pixel_checks\":"+checks+",\"nv12_nv21\":true,\"colour_bars\":true,\"range_rotation_crop\":true}");
 }
}
