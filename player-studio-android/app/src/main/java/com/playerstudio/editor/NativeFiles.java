package com.playerstudio.editor;

import android.app.Activity;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.system.Os;
import android.system.OsConstants;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

public final class NativeFiles {
    private static Context context;
    private static File home;
    private static CompletableFuture<String> pending;
    private static String category;
    private static File exportSource;
    private static File pendingInstall;
    private static final Map<String,ParcelFileDescriptor> descriptors=new ConcurrentHashMap<>();
    private static final ExecutorService io=Executors.newSingleThreadExecutor();
    private static final long VIDEO_LIMIT=512L*1024*1024;
    static Context applicationContext(){return context;}
    public static String descriptorSnapshot() throws Exception {
        JSONObject result=new JSONObject();for(Map.Entry<String,ParcelFileDescriptor> entry:descriptors.entrySet())result.put(entry.getKey(),entry.getValue().getFd());return result.toString();
    }
    static void registerDescriptor(File target,ParcelFileDescriptor descriptor) throws Exception {
        java.nio.file.Files.deleteIfExists(target.toPath());target.createNewFile();
        String path=target.getAbsolutePath();ParcelFileDescriptor old=descriptors.put(path,descriptor);
        if(com.chaquo.python.Python.isStarted())com.chaquo.python.Python.getInstance().getModule("android_files").callAttr("register",path,descriptor.getFd());
        if(old!=null)old.close();
    }
    static void initialize(Context c,File h) {
        context=c;home=h;
        Map<String,?> stored=c.getSharedPreferences("sourceDocuments",0).getAll();
        for (Map.Entry<String,?> entry:stored.entrySet()) try { link(Uri.parse(entry.getValue().toString()),entry.getKey()); }
        catch(Exception ignored) {aliasFile(safeName(entry.getKey())).delete();}
    }
    public static synchronized String pick(String kind,String selectedCategory,String initial) throws Exception {
        if (pending!=null) throw new IllegalStateException("已有文件选择窗口");
        if (!"open".equals(kind)) throw new IllegalArgumentException("请使用导出按钮保存文件");
        CompletableFuture<String> future=new CompletableFuture<>();pending=future;category=selectedCategory;
        BaseActivity activity=BaseActivity.activity();
        activity.runOnUiThread(()->{
            Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("image".equals(selectedCategory)?"image/*":"motion-video".equals(selectedCategory)?"video/*":"*/*");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            activity.startActivityForResult(intent,100);
        });
        try { return future.get(30,TimeUnit.MINUTES); }
        finally { pending=null; }
    }
    private static String safeName(String value) { return value.replaceAll("[\\\\/\\x00-\\x1f]","_"); }
    private static String documentName(Uri uri) {
        String name="selected-file";
        try(Cursor cursor=context.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)) {
            if(cursor!=null && cursor.moveToFirst()) name=cursor.getString(0);
        } catch(Exception ignored) {}
        return safeName(name);
    }
    private static String stableName(Uri uri,String name) throws Exception {
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(uri.toString().getBytes("UTF-8"));
        StringBuilder prefix=new StringBuilder();for(int i=0;i<8;i++)prefix.append(String.format("%02x",digest[i]));
        return prefix+"-"+name;
    }
    private static File aliasFile(String filename) {
        File folder=new File(home,"input-links");
        if(filename.matches("[a-f0-9]{16}-.+")){
            folder=new File(folder,filename.substring(0,16));folder.mkdirs();return new File(folder,filename.substring(17));
        }
        folder.mkdirs();return new File(folder,filename);
    }
    private static String link(Uri uri,String filename) throws Exception {
        if(!filename.equals(safeName(filename))||filename.equals(".")||filename.equals(".."))throw new IOException("输入文件名无效");
        ParcelFileDescriptor descriptor=context.getContentResolver().openFileDescriptor(uri,"r");
        if(descriptor==null)throw new IOException("无法读取所选文件");
        try { Os.lseek(descriptor.getFileDescriptor(),0,OsConstants.SEEK_CUR); }
        catch(Exception e){descriptor.close();throw new IOException("此文件提供方不支持随机读取，请先把 APK 下载到手机本地存储");}
        File path=aliasFile(filename);
        registerDescriptor(path,descriptor);
        return path.getAbsolutePath();
    }
    private static String importDocument(Uri uri,int flags,String selectedCategory) throws Exception {
        String name=documentName(uri);
        if("apk".equals(selectedCategory)) {
            if(!name.toLowerCase(Locale.ROOT).endsWith(".apk"))throw new IOException("请选择 APK 文件");
            try { context.getContentResolver().takePersistableUriPermission(uri,flags&Intent.FLAG_GRANT_READ_URI_PERMISSION); }
            catch(SecurityException e){throw new IOException("无法保留此 APK 的读取权限，请从系统文件选择器选择本地文件",e);}
            String filename=stableName(uri,name);String path=link(uri,filename);
            context.getSharedPreferences("sourceDocuments",0).edit().putString(filename,uri.toString()).apply();
            return path;
        }
        if("motion-video".equals(selectedCategory)) {
            if(!name.toLowerCase(Locale.ROOT).matches(".*\\.(mp4|mov|webm)$"))throw new IOException("请选择 MP4、MOV 或 WebM 视频");
            long declaredSize=-1;
            try(Cursor cursor=context.getContentResolver().query(uri,new String[]{OpenableColumns.SIZE},null,null,null)) {
                if(cursor!=null&&cursor.moveToFirst()&&!cursor.isNull(0))declaredSize=cursor.getLong(0);
            }catch(Exception ignored){} // Some providers omit SIZE; fstat/bounded copy still enforce the limit.
            if(declaredSize>VIDEO_LIMIT)throw new IOException("视频不能超过 512 MB");
            // Seekable local SAF documents can be read without a cache copy.
            ParcelFileDescriptor descriptor=null;
            try {
                descriptor=context.getContentResolver().openFileDescriptor(uri,"r");
                if(descriptor==null)throw new IOException("视频无法打开");
                Os.lseek(descriptor.getFileDescriptor(),0,OsConstants.SEEK_CUR);
                long size=descriptor.getStatSize();
                if(size>VIDEO_LIMIT)throw new IOException("视频不能超过 512 MB");
                if(size<1)throw new IOException("此文件提供方需要复制读取");
                context.getContentResolver().takePersistableUriPermission(uri,flags&Intent.FLAG_GRANT_READ_URI_PERMISSION);
                String filename=stableName(uri,name);File alias=aliasFile(filename);
                registerDescriptor(alias,descriptor);descriptor=null;
                context.getSharedPreferences("sourceDocuments",0).edit().putString(filename,uri.toString()).apply();
                return alias.getAbsolutePath();
            }catch(Exception e) {
                if(e instanceof IOException&&"视频不能超过 512 MB".equals(e.getMessage()))throw e;
                // Non-seekable providers and transient grants use a bounded copy.
            }finally{if(descriptor!=null)descriptor.close();}
        }
        File folder=new File(context.getCacheDir(),"selected-inputs");folder.mkdirs();
        File dest=new File(folder,UUID.randomUUID()+"-"+name);
        boolean complete=false;
        try(InputStream input=context.getContentResolver().openInputStream(uri);OutputStream output=new FileOutputStream(dest)) {
            if(input==null)throw new IOException("文件无法打开");
            if("motion-video".equals(selectedCategory))copyLimited(input,output,VIDEO_LIMIT);else copy(input,output);
            complete=true;
        }finally{if(!complete)dest.delete();}
        return dest.getAbsolutePath();
    }
    private static void copyLimited(InputStream in,OutputStream out,long limit)throws IOException {
        byte[] buffer=new byte[1024*1024];long total=0;int count;
        while((count=in.read(buffer))!=-1){total+=count;if(total>limit)throw new IOException("视频不能超过 512 MB");out.write(buffer,0,count);}
    }
    public static ParcelFileDescriptor openVideoDescriptor(String path)throws Exception {
        File file=new File(path);ParcelFileDescriptor original=descriptors.get(file.getAbsolutePath());
        if(original==null)for(Map.Entry<String,ParcelFileDescriptor> entry:descriptors.entrySet())
            if(new File(entry.getKey()).getCanonicalPath().equals(file.getCanonicalPath())){original=entry.getValue();break;}
        ParcelFileDescriptor result=original==null?ParcelFileDescriptor.open(file,ParcelFileDescriptor.MODE_READ_ONLY):ParcelFileDescriptor.dup(original.getFileDescriptor());
        long size=result.getStatSize();
        if(size<1||size>VIDEO_LIMIT){result.close();throw new IOException(size>VIDEO_LIMIT?"视频不能超过 512 MB":"视频文件为空或无法读取大小");}
        return result;
    }
    private static void copy(InputStream in,OutputStream out) throws IOException {
        byte[] buffer=new byte[1024*1024];int count;while((count=in.read(buffer))!=-1)out.write(buffer,0,count);
    }
    static void exportDownload(Uri uri) throws Exception {
        if(!"127.0.0.1".equals(uri.getHost()) || uri.getPort()!=StudioService.port)throw new IOException("导出地址无效");
        String path=uri.getPath();if(path==null || !path.startsWith("/exports/"))throw new IOException("只可导出本机生成的文件");
        File folder=new File(home,"data/exports").getCanonicalFile();File source=new File(folder,path.substring(9)).getCanonicalFile();
        if(!source.getParentFile().equals(folder) || !source.isFile())throw new IOException("导出文件不存在");
        exportSource=source;
        Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(source.getName().endsWith(".apk")?"application/vnd.android.package-archive":"application/octet-stream");
        intent.putExtra(Intent.EXTRA_TITLE,source.getName());BaseActivity.activity().startActivityForResult(intent,101);
    }
    static void onResult(int request,int result,Intent data) {
        if(request==103) {
            File file=pendingInstall;pendingInstall=null;
            if(file!=null&&context.getPackageManager().canRequestPackageInstalls())launchInstaller(file);
            else BaseActivity.activity().showMessage("未允许安装，请授权后再次点击直接安装");
        } else if(request==100) {
            CompletableFuture<String> future=pending;if(future==null)return;
            if(result!=Activity.RESULT_OK || data==null || data.getData()==null){future.complete("");return;}
            Uri uri=data.getData();int flags=data.getFlags();String selectedCategory=category;
            io.execute(()->{try{future.complete(importDocument(uri,flags,selectedCategory));}catch(Exception e){future.completeExceptionally(e);}});
        } else if(request==101 && result==Activity.RESULT_OK && data!=null && data.getData()!=null) {
            Uri uri=data.getData();File source=exportSource;
            io.execute(()->{try(InputStream input=new FileInputStream(source);OutputStream output=context.getContentResolver().openOutputStream(uri,"w")) {
                if(output==null)throw new IOException("无法写入目标位置");copy(input,output);BaseActivity.activity().showMessage("已导出 "+source.getName());
            }catch(Exception e){BaseActivity.activity().showMessage("导出失败："+e.getMessage());}});
        }
    }
    public static String install(String path) throws Exception {
        File folder=new File(home,"data/exports").getCanonicalFile();File file=new File(path).getCanonicalFile();
        if(!file.getParentFile().equals(folder)||!file.isFile()||!file.getName().endsWith(".apk"))throw new IOException("请选择本软件生成且尚未清除的 APK");
        if(!context.getPackageManager().canRequestPackageInstalls()) {
            pendingInstall=file;BaseActivity activity=BaseActivity.activity();
            activity.runOnUiThread(()->activity.startActivityForResult(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+context.getPackageName())),103));
            return "permission";
        }
        launchInstaller(file);return "installer";
    }
    private static void launchInstaller(File file) {
        BaseActivity activity=BaseActivity.activity();activity.runOnUiThread(()->{
            try {
                Uri uri=new Uri.Builder().scheme("content").authority(context.getPackageName()+".exports").appendPath("export").appendPath(file.getName()).build();
                Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                intent.setClipData(ClipData.newRawUri("Generated APK",uri));activity.startActivity(intent);
            }catch(Exception e){activity.showMessage("无法打开安装器："+e.getMessage());}
        });
    }
}
