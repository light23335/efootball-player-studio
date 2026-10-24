package com.playerstudio.editor;

import android.app.*;
import android.content.*;
import android.os.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.*;
import java.util.zip.*;

public class StudioService extends Service {
    static volatile String url,error;
    static volatile int port;
    private volatile boolean started;
    private volatile boolean destroyed;
    private volatile boolean taskRemoved;
    private PowerManager.WakeLock taskLock;
    private Notification.Builder notification;
    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("studio-work","球员工坊本机任务",NotificationManager.IMPORTANCE_LOW));
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        notification=new Notification.Builder(this,"studio-work").setSmallIcon(android.R.drawable.ic_menu_edit)
            .setContentTitle("球员工坊").setContentText("本机编辑和打包服务运行中").setOngoing(true).setContentIntent(open);
        taskLock=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"PlayerStudio:LocalBuild");taskLock.setReferenceCounted(false);
        startForeground(184,notification.build());
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        taskRemoved=false;
        if(!started) {started=true;new Thread(()->{
            try {
                File home=new File(getFilesDir(),"studio");home.mkdirs();prepareBundle(this,home);NativeFiles.initialize(this,home);
                if(!Python.isStarted())Python.start(new AndroidPlatform(this));
                JSONObject result=new JSONObject(Python.getInstance().getModule("android_backend").callAttr("start",home.getAbsolutePath(),getApplicationInfo().nativeLibraryDir).toString());
                port=result.getInt("port");url=result.getString("url");
                new Thread(()->{
                    String last="";
                    while(!destroyed){
                        try{
                            JSONObject work=new JSONObject(Python.getInstance().getModule("android_backend").callAttr("work_status").toString());
                            if(work.getBoolean("busy")){if(!taskLock.isHeld())taskLock.acquire(15*60*1000L);}else {
                                if(taskLock.isHeld())taskLock.release();if(taskRemoved){stopSelf();break;}
                            }
                            String message=work.getString("message");if(!message.equals(last)){last=message;getSystemService(NotificationManager.class).notify(184,notification.setContentText(message).build());}
                            Thread.sleep(1500);
                        }catch(Exception ignored){break;}
                    }
                },"StudioJobStatus").start();
            }catch(Exception e){error=e.toString();android.util.Log.e("PlayerStudio","Startup failed",e);}
        },"StudioStartup").start();}
        return START_NOT_STICKY;
    }
    static void prepareBundle(Context context,File home) throws IOException {
        File folder=new File(home,"bundle");File marker=new File(folder,".android-bundle.sha256");
        String revision;
        try(InputStream input=context.getAssets().open("studio-bundle.sha256")) {
            byte[] raw=new byte[128];int count=input.read(raw);revision=new String(raw,0,count,"US-ASCII").trim();
        }
        if(!revision.matches("[a-f0-9]{64}"))throw new IOException("软件资源版本标识无效");
        if(marker.isFile() && revision.equals(new String(java.nio.file.Files.readAllBytes(marker.toPath()),"US-ASCII").trim()))return;
        folder.mkdirs();
        try(ZipInputStream archive=new ZipInputStream(context.getAssets().open("studio-bundle.zip"))) {
            ZipEntry item;byte[] buffer=new byte[1024*1024];String prefix=folder.getCanonicalPath()+File.separator;
            while((item=archive.getNextEntry())!=null) {
                File target=new File(folder,item.getName());
                if(!target.getCanonicalPath().startsWith(prefix))throw new IOException("软件资源路径无效");
                if(item.isDirectory()){target.mkdirs();continue;}target.getParentFile().mkdirs();
                try(OutputStream output=new FileOutputStream(target)){int n;while((n=archive.read(buffer))!=-1)output.write(buffer,0,n);}
            }
        }
        File temporary=new File(folder,".android-bundle.sha256.tmp");
        try(OutputStream output=new FileOutputStream(temporary)){output.write(revision.getBytes("US-ASCII"));}
        java.nio.file.Files.move(temporary.toPath(),marker.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
    @Override public void onTaskRemoved(Intent intent) {
        taskRemoved=true;
        try {if(Python.isStarted() && Python.getInstance().getModule("android_backend").callAttr("busy").toBoolean())return;}catch(Exception ignored){}
        stopSelf();
    }
    @Override public void onDestroy() {
        destroyed=true;if(taskLock!=null&&taskLock.isHeld())taskLock.release();
        try {if(Python.isStarted())Python.getInstance().getModule("android_backend").callAttr("stop");}catch(Exception ignored){}
        url=null;super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent){return null;}
    @Override public void onTimeout(int startId,int foregroundServiceType){stopSelf();}
}
