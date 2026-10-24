package com.playerstudio.editor;

import android.content.*;
import android.content.pm.*;
import android.os.Build;
import java.io.File;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.ZipFile;
import org.json.*;

/** Only reads compatible installation APKs; never reads another app's data. */
public final class InstalledGames {
    public static boolean openReleasePage(String url){
        android.net.Uri uri=android.net.Uri.parse(url);
        if(!"https".equals(uri.getScheme())||!"github.com".equals(uri.getHost())||!uri.getPath().contains("/releases/"))throw new IllegalArgumentException("更新下载地址无效");
        NativeFiles.applicationContext().startActivity(new Intent(Intent.ACTION_VIEW,uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));return true;
    }
    private static final String[] KNOWN={"com.efootball.revival.local","com.efootball.revival.resources","com.efootball.revival.diyer","com.efootball.revival.diyassets"};
    private static int flags(){return Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;}
    private static Set<String> signatures(PackageInfo info) throws Exception {
        android.content.pm.Signature[] signatures=Build.VERSION.SDK_INT>=28&&info.signingInfo!=null?info.signingInfo.getApkContentsSigners():info.signatures;
        Set<String> result=new TreeSet<>();
        if(signatures!=null)for(android.content.pm.Signature value:signatures){
            byte[] hash=MessageDigest.getInstance("SHA-256").digest(value.toByteArray());StringBuilder s=new StringBuilder();for(byte b:hash)s.append(String.format("%02x",b&255));result.add(s.toString());
        }
        return result;
    }
    public static String scan() throws Exception {
        Context context=NativeFiles.applicationContext();PackageManager pm=context.getPackageManager();Set<String> packages=new LinkedHashSet<>(Arrays.asList(KNOWN));
        Intent launcher=new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        for(ResolveInfo item:pm.queryIntentActivities(launcher,0))if(item.activityInfo!=null)packages.add(item.activityInfo.packageName);
        JSONArray rows=new JSONArray(),errors=new JSONArray();
        for(String name:packages){
            try {
                PackageInfo info=pm.getPackageInfo(name,flags());ApplicationInfo app=info.applicationInfo;
                if(app==null||app.sourceDir==null)continue;
                try(ZipFile zip=new ZipFile(app.sourceDir)){
                    boolean game=zip.getEntry("assets/gateway-release/release-manifest.json")!=null;
                    boolean resource=zip.getEntry("assets/resource-bootstrap/resources.zip")!=null;
                    if(!game&&!resource)continue;
                    if(app.splitSourceDirs!=null&&app.splitSourceDirs.length>0){errors.put(pm.getApplicationLabel(app)+"：分包安装暂不支持，请选择完整 APK。");continue;}
                    rows.put(new JSONObject().put("package",name).put("label",pm.getApplicationLabel(app).toString()).put("path",app.sourceDir).put("kind",game?"game":"resource").put("signers",new JSONArray(signatures(info))).put("installed",true));
                }
            }catch(PackageManager.NameNotFoundException ignored){}
            catch(Exception e){if(Arrays.asList(KNOWN).contains(name))errors.put(name+"：无法读取已安装 APK，请手动选择文件。");}
        }
        return new JSONObject().put("rows",rows).put("errors",errors).toString();
    }
    public static String validateInstall(String path) throws Exception {
        PackageManager pm=NativeFiles.applicationContext().getPackageManager();PackageInfo incoming=pm.getPackageArchiveInfo(path,flags());
        if(incoming==null)throw new IllegalArgumentException("无法读取 APK 安装信息");
        try {
            PackageInfo installed=pm.getPackageInfo(incoming.packageName,flags());Set<String> before=signatures(installed),after=signatures(incoming);
            if(before.isEmpty()||!before.equals(after))throw new IllegalArgumentException("已安装游戏与此 APK 签名不同，不能保留存档覆盖安装。请改选共存安装，或恢复制作旧包时的工坊签名。不要卸载旧游戏。");
            long oldVersion=Build.VERSION.SDK_INT>=28?installed.getLongVersionCode():installed.versionCode;
            long newVersion=Build.VERSION.SDK_INT>=28?incoming.getLongVersionCode():incoming.versionCode;
            if(newVersion<oldVersion)throw new IllegalArgumentException("安装包版本号低于已安装游戏，请先读取当前已安装版本后重新生成。");
            return new JSONObject().put("action","update").put("package",incoming.packageName).put("same_signer",true).toString();
        }catch(PackageManager.NameNotFoundException e){return new JSONObject().put("action","new_install").put("package",incoming.packageName).toString();}
    }
}
