package com.playerstudio.editor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.system.Os;
import com.chaquo.python.android.AndroidPlatform;
import java.io.*;
import java.util.*;
import org.json.*;

public final class QaBridge {
    private static final Map<String,ParcelFileDescriptor> files=new HashMap<>();
    private static android.content.Context context(){return NativeFiles.applicationContext();}
    public static String originals(String home) throws Exception {
        JSONObject cfg=QaDocumentsProvider.config(context());JSONObject result=new JSONObject();
        File folder=new File(home,"qa-inputs");folder.mkdirs();
        for(String id:new String[]{"main","companion"}) {
            JSONObject item=cfg.getJSONObject("sources").getJSONObject(id);File target=new File(folder,item.getString("name"));
            bind(id,target);result.put(id,target.getAbsolutePath());
        }
        return result.toString();
    }
    private static void bind(String id,File target) throws Exception {
        Uri uri=DocumentsContract.buildDocumentUri(QaDocumentsProvider.AUTHORITY,id);
        ParcelFileDescriptor fd=context().getContentResolver().openFileDescriptor(uri,"r");
        NativeFiles.registerDescriptor(target,fd);files.put(id,fd);
    }
    public static String cacheManifest() throws Exception {
        return QaDocumentsProvider.config(context()).getJSONObject("sources").toString();
    }
    public static void useEquivalentReadOnlyCache(String folder) throws Exception {
        File root=new File(context().getFilesDir(),"studio/library/versions").getCanonicalFile();File cache=new File(folder).getCanonicalFile();
        if(!cache.getPath().startsWith(root.getPath()+File.separator) || !cache.getName().equals("containers"))throw new IOException("Invalid QA cache location");
        JSONObject sources=QaDocumentsProvider.config(context()).getJSONObject("sources");Iterator<String> keys=sources.keys();
        while(keys.hasNext()){String id=keys.next();if(!id.startsWith("cache-"))continue;String name=sources.getJSONObject(id).getString("name");if(name.contains("/")||name.contains("\\"))throw new IOException("Invalid cache name");bind(id,new File(cache,name));}
    }
}
