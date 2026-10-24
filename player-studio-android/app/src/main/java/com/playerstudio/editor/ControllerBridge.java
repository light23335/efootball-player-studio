package com.playerstudio.editor;

import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.webkit.JavascriptInterface;
import java.util.HashMap;
import org.json.JSONArray;
import org.json.JSONObject;

/** Read-only controller monitor for the local editor; game bindings live in the exported APK. */
public final class ControllerBridge {
    private static final int[] KEYS={96,97,99,100,102,103,104,105,109,108,106,107,19,20,21,22};
    private final HashMap<Integer,boolean[]> keys=new HashMap<>();
    private final HashMap<Integer,float[]> motion=new HashMap<>();
    private volatile boolean capture=false;
    static boolean controller(InputDevice d) {
        return d!=null && ((d.getSources()&InputDevice.SOURCE_GAMEPAD)==InputDevice.SOURCE_GAMEPAD ||
                (d.getSources()&InputDevice.SOURCE_JOYSTICK)==InputDevice.SOURCE_JOYSTICK);
    }
    synchronized boolean key(KeyEvent event) {
        if (!controller(event.getDevice())) return false;
        boolean[] state=keys.get(event.getDeviceId());
        if(state==null){state=new boolean[16];keys.put(event.getDeviceId(),state);}
        for(int i=0;i<KEYS.length;i++) if(KEYS[i]==event.getKeyCode()) state[i]=event.getAction()!=KeyEvent.ACTION_UP;
        return capture;
    }
    synchronized boolean move(MotionEvent event) {
        if(!controller(event.getDevice()))return false;
        float[] values={event.getAxisValue(MotionEvent.AXIS_X),event.getAxisValue(MotionEvent.AXIS_Y),
                event.getAxisValue(MotionEvent.AXIS_Z),event.getAxisValue(MotionEvent.AXIS_RZ),
                Math.max(event.getAxisValue(MotionEvent.AXIS_LTRIGGER),event.getAxisValue(MotionEvent.AXIS_BRAKE)),
                Math.max(event.getAxisValue(MotionEvent.AXIS_RTRIGGER),event.getAxisValue(MotionEvent.AXIS_GAS)),
                event.getAxisValue(MotionEvent.AXIS_HAT_X),event.getAxisValue(MotionEvent.AXIS_HAT_Y)};
        motion.put(event.getDeviceId(),values);return capture;
    }
    @JavascriptInterface public void setCapture(boolean value){capture=value;}
    @JavascriptInterface public synchronized String getState(){
        JSONArray result=new JSONArray();
        try{for(int id:InputDevice.getDeviceIds()){
            InputDevice d=InputDevice.getDevice(id);if(!controller(d))continue;
            boolean[] state=keys.get(id);if(state==null)state=new boolean[16];
            float[] values=motion.get(id);if(values==null)values=new float[8];
            JSONArray buttons=new JSONArray(),axes=new JSONArray();
            for(int i=0;i<16;i++){
                float value=state[i]?1:0;
                if(i==6)value=Math.max(value,values[4]);if(i==7)value=Math.max(value,values[5]);
                if(i==12)value=Math.max(value,-values[7]);if(i==13)value=Math.max(value,values[7]);
                if(i==14)value=Math.max(value,-values[6]);if(i==15)value=Math.max(value,values[6]);
                buttons.put(new JSONObject().put("value",value).put("pressed",value>=0.3));
            }
            for(int i=0;i<4;i++)axes.put(values[i]);
            result.put(new JSONObject().put("index",id).put("id",d.getName()).put("mapping","standard")
                    .put("connected",true).put("buttons",buttons).put("axes",axes));
        }}catch(Exception ignored){}return result.toString();
    }
    synchronized void reset(){keys.clear();motion.clear();capture=false;}
}
