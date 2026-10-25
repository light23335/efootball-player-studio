package com.playerstudio.editor;

import android.os.Bundle;
import android.view.*;
import android.webkit.WebView;

/** Controller-aware entry point; the established editor lifecycle is inherited. */
public class MainActivity extends BaseActivity {
    private final ControllerBridge controllerBridge=new ControllerBridge();
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        attachController(findViewById(android.R.id.content));
    }
    private void attachController(View view) {
        if(view instanceof WebView)((WebView)view).addJavascriptInterface(controllerBridge,"StudioController");
        if(view instanceof ViewGroup){
            ViewGroup group=(ViewGroup)view;
            for(int i=0;i<group.getChildCount();i++)attachController(group.getChildAt(i));
        }
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event){return controllerBridge.key(event)||super.dispatchKeyEvent(event);}
    @Override public boolean dispatchGenericMotionEvent(MotionEvent event){return controllerBridge.move(event)||super.dispatchGenericMotionEvent(event);}
    @Override protected void onPause(){controllerBridge.reset();super.onPause();}
}
