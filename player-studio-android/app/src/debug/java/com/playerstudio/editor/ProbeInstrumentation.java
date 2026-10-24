package com.playerstudio.editor;
import android.app.*;
import android.content.*;
import android.os.Bundle;
import java.io.*;
import java.util.zip.*;
import com.chaquo.python.*;
import com.chaquo.python.android.AndroidPlatform;

/** Debug-only checks, excluded from the distributable release APK. */
public class ProbeInstrumentation extends Instrumentation {
    private String mode="smoke";
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);if(arguments!=null)mode=arguments.getString("mode","smoke");start();}
    @Override public void onStart(){
        Bundle result=new Bundle();
        try {
            Context context=getTargetContext();File home=new File(context.getFilesDir(),"studio");home.mkdirs();
            StudioService.prepareBundle(context,home);NativeFiles.initialize(context,home);
            File fixtures=new File(home,"qa-fixtures");fixtures.mkdirs();
            try(ZipInputStream archive=new ZipInputStream(context.getAssets().open("qa-fixtures.zip"))) {
                ZipEntry entry;byte[] buffer=new byte[65536];
                while((entry=archive.getNextEntry())!=null){
                    File target=new File(fixtures,entry.getName());
                    if(!target.getCanonicalPath().startsWith(fixtures.getCanonicalPath()+File.separator))throw new IOException("Invalid fixture path");
                    target.getParentFile().mkdirs();
                    try(OutputStream out=new FileOutputStream(target)){int n;while((n=archive.read(buffer))!=-1)out.write(buffer,0,n);}
                }
            }
            if(!Python.isStarted())Python.start(new AndroidPlatform(context));
            Python python=Python.getInstance();python.getModule("sys").get("path").callAttr("insert",0,fixtures.getAbsolutePath());
            String text;
            if(mode.equals("documents")||mode.equals("companion"))text=python.getModule("android_documents_check").callAttr("run",home.getAbsolutePath(),context.getApplicationInfo().nativeLibraryDir,fixtures.getAbsolutePath(),mode).toString();
            else text=mode.equals("resume")?python.getModule("android_full_check").callAttr("run",home.getAbsolutePath(),context.getApplicationInfo().nativeLibraryDir,fixtures.getAbsolutePath(),true).toString():python.getModule(mode.equals("full")?"android_full_check":"android_smoke").callAttr("run",home.getAbsolutePath(),context.getApplicationInfo().nativeLibraryDir,fixtures.getAbsolutePath()).toString();
            result.putString("result",text);finish(Activity.RESULT_OK,result);
        } catch(Exception error){result.putString("error",error.toString());android.util.Log.e("StudioProbe","Probe failed",error);finish(Activity.RESULT_CANCELED,result);}
    }
}
