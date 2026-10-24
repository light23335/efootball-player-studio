package com.playerstudio.editor;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Grants the system installer read access to one generated APK only. */
public final class ExportProvider extends ContentProvider {
    public boolean onCreate(){return true;}
    private File resolve(Uri uri) throws FileNotFoundException {
        try {
            if(uri.getPathSegments().size()!=2||!"export".equals(uri.getPathSegments().get(0)))throw new IOException("Invalid export URI");
            File folder=new File(getContext().getFilesDir(),"studio/data/exports").getCanonicalFile();
            File file=new File(folder,uri.getLastPathSegment()).getCanonicalFile();
            if(!file.getParentFile().equals(folder)||!file.isFile()||!file.getName().endsWith(".apk"))throw new IOException("Generated APK is missing");
            return file;
        }catch(IOException e){throw new FileNotFoundException(e.getMessage());}
    }
    public String getType(Uri uri){return "application/vnd.android.package-archive";}
    public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!"r".equals(mode))throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(resolve(uri),ParcelFileDescriptor.MODE_READ_ONLY);
    }
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String order){
        try {
            File file=resolve(uri);String[] fields=projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection;
            MatrixCursor result=new MatrixCursor(fields,1);Object[] values=new Object[fields.length];
            for(int i=0;i<fields.length;i++)values[i]=OpenableColumns.DISPLAY_NAME.equals(fields[i])?file.getName():OpenableColumns.SIZE.equals(fields[i])?file.length():null;
            result.addRow(values);return result;
        }catch(FileNotFoundException e){return null;}
    }
    public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}
    public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
}
