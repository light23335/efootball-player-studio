package com.playerstudio.editor;
import android.database.*;
import android.os.*;
import android.os.storage.StorageManager;
import android.provider.DocumentsContract;
import android.provider.DocumentsProvider;
import java.io.*;
import java.net.*;
import java.util.*;
import org.json.*;

/** Debug-only read-only documents, so QA can use host originals without duplicates. */
public class QaDocumentsProvider extends DocumentsProvider {
    static final String AUTHORITY="com.playerstudio.editor.qa";
    private static final String[] DOCS={"document_id","_display_name","mime_type","flags","_size"};
    static JSONObject config(android.content.Context context) throws Exception {
        File file=new File(context.getFilesDir(),"qa-source-settings.json");
        return new JSONObject(new String(java.nio.file.Files.readAllBytes(file.toPath()),"UTF-8"));
    }
    @Override public boolean onCreate(){return true;}
    @Override public Cursor queryRoots(String[] projection) {
        MatrixCursor cursor=new MatrixCursor(new String[]{"root_id","document_id","title","flags","mime_types"});
        try{config(getContext());cursor.addRow(new Object[]{"qa","root","本地验收源（只读）",0,"*/*"});}catch(Exception ignored){}
        return cursor;
    }
    @Override public Cursor queryDocument(String id,String[] projection) throws FileNotFoundException {
        MatrixCursor cursor=new MatrixCursor(DOCS);add(cursor,id);return cursor;
    }
    private void add(MatrixCursor cursor,String id) throws FileNotFoundException {
        if(id.equals("root")){cursor.addRow(new Object[]{id,"原版 APK",DocumentsContract.Document.MIME_TYPE_DIR,0,0});return;}
        try{JSONObject item=config(getContext()).getJSONObject("sources").getJSONObject(id);
            cursor.addRow(new Object[]{id,item.getString("name"),"application/octet-stream",0,item.getLong("size")});
        }catch(Exception e){throw new FileNotFoundException(e.toString());}
    }
    @Override public Cursor queryChildDocuments(String parent,String[] projection,String sort) throws FileNotFoundException {
        MatrixCursor cursor=new MatrixCursor(DOCS);add(cursor,"main");add(cursor,"companion");return cursor;
    }
    @Override public ParcelFileDescriptor openDocument(String id,String mode,CancellationSignal signal) throws FileNotFoundException {
        if(!mode.equals("r"))throw new FileNotFoundException("Read-only QA source");
        try{
            JSONObject cfg=config(getContext()),item=cfg.getJSONObject("sources").getJSONObject(id);
            long size=item.getLong("size");String url="http://127.0.0.1:"+cfg.getInt("port")+"/file/"+id,token=cfg.getString("token");
            HandlerThread thread=new HandlerThread("QaReadOnlySource");thread.start();
            ProxyFileDescriptorCallback callback=new ProxyFileDescriptorCallback(){
                final int block=4*1024*1024;
                final LinkedHashMap<Long,byte[]> cache=new LinkedHashMap<>(4,.75f,true);
                @Override public long onGetSize(){return size;}
                private byte[] block(long at) throws Exception {
                    byte[] old=cache.get(at);if(old!=null)return old;
                    HttpURLConnection conn=(HttpURLConnection)new URL(url).openConnection();conn.setConnectTimeout(15000);conn.setReadTimeout(60000);
                    conn.setRequestProperty("X-Studio-QA",token);conn.setRequestProperty("Range","bytes="+at+"-"+Math.min(size-1,at+block-1));
                    if(conn.getResponseCode()!=206)throw new IOException("QA range source failed: "+conn.getResponseCode());
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream in=conn.getInputStream()){byte[] buffer=new byte[65536];int n;while((n=in.read(buffer))!=-1)bytes.write(buffer,0,n);}finally{conn.disconnect();}
                    byte[] result=bytes.toByteArray();cache.put(at,result);if(cache.size()>3)cache.remove(cache.keySet().iterator().next());return result;
                }
                @Override public int onRead(long offset,int count,byte[] target) throws android.system.ErrnoException {
                    try{int copied=0;while(copied<count && offset<size){long at=offset/block*block;byte[] value=block(at);int start=(int)(offset-at),length=Math.min(count-copied,value.length-start);if(length<=0)throw new IOException("Incomplete QA source block");System.arraycopy(value,start,target,copied,length);copied+=length;offset+=length;}return copied;}
                    catch(Exception e){android.util.Log.e("QaSource","Read failed",e);throw new android.system.ErrnoException("qa_read",android.system.OsConstants.EIO,e);}
                }
                @Override public void onRelease(){cache.clear();thread.quitSafely();}
            };
            return getContext().getSystemService(StorageManager.class).openProxyFileDescriptor(ParcelFileDescriptor.MODE_READ_ONLY,callback,new Handler(thread.getLooper()));
        }catch(Exception e){throw new FileNotFoundException(e.toString());}
    }
}
