package com.playerstudio.editor;

import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.webkit.*;
import android.graphics.Color;
import android.view.*;
import android.widget.*;
import java.lang.ref.WeakReference;

public class BaseActivity extends Activity {
    static WeakReference<BaseActivity> current = new WeakReference<>(null);
    private WebView web;
    private TextView status;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String loaded = "";
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        current = new WeakReference<>(this);
        getWindow().setStatusBarColor(Color.rgb(12,18,28));
        getWindow().setNavigationBarColor(Color.rgb(12,18,28));
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setFitsSystemWindows(true); root.setBackgroundColor(Color.rgb(12,18,28));
        status = new TextView(this); status.setTextColor(Color.WHITE); status.setPadding(24,24,24,24);
        status.setText("正在启动球员工坊，本机首次准备资料可能需要一些时间…");
        root.addView(status);
        web = new WebView(this); root.addView(web,new LinearLayout.LayoutParams(-1,0,1)); setContentView(root);
        WebView.setWebContentsDebuggingEnabled((getApplicationInfo().flags&android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(false);
        web.setBackgroundColor(Color.rgb(12,18,28));
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl();
                if ("127.0.0.1".equals(uri.getHost()) && uri.getPort()==StudioService.port) return false;
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri=request.getUrl(); String scheme=uri.getScheme();
                if (("http".equals(scheme)||"https".equals(scheme)) &&
                    !("127.0.0.1".equals(uri.getHost()) && uri.getPort()==StudioService.port)) {
                    return new WebResourceResponse("text/plain","UTF-8",new java.io.ByteArrayInputStream(new byte[0]));
                }
                return super.shouldInterceptRequest(view,request);
            }
        });
        web.setDownloadListener((url,agent,disposition,mime,size)->{
            try { NativeFiles.exportDownload(Uri.parse(url)); }
            catch(Exception e) { showMessage(e.getMessage()); }
        });
        if (Build.VERSION.SDK_INT>=33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},88);
        startForegroundService(new Intent(this,StudioService.class));
        handler.post(new Runnable(){ public void run(){
            if (isDestroyed()) return;
            if (StudioService.error!=null) status.setText("启动失败："+StudioService.error);
            if (StudioService.url!=null && !StudioService.url.equals(loaded)) {
                loaded=StudioService.url; web.loadUrl(loaded); status.setVisibility(View.GONE);
            }
            handler.postDelayed(this,500);
        }});
    }
    static BaseActivity activity() {
        BaseActivity activity=current.get();
        if (activity==null || activity.isDestroyed()) throw new IllegalStateException("请回到球员工坊后选择文件");
        return activity;
    }
    void showMessage(String message) { runOnUiThread(()->Toast.makeText(this,message,Toast.LENGTH_LONG).show()); }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data); NativeFiles.onResult(request,result,data);
    }
    @Override public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else moveTaskToBack(true);
    }
    @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);super.onDestroy();}
}
