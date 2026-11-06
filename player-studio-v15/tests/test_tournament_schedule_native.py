"""Host lifecycle contract with a fake Java UI; explicitly not device proof."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_tournament_schedule_ui as native


class JavaUi:
    def __init__(self):
        self.visible=[];self.ui_calls=0;self.webs=[];owner=self
        class Window:
            def getDecorView(self):return self
            def getSystemUiVisibility(self):return 5894
            def setSystemUiVisibility(self,value):self.flags=value
            def setLayout(self,*value):self.layout=value
            def setSoftInputMode(self,value):self.soft=value
        class Activity:
            def __init__(self):self.window=Window()
            def runOnUiThread(self,task):owner.ui_calls+=1;task.run()
            def isFinishing(self):return False
            def getWindow(self):return self.window
        owner.activity=Activity()
        class GameActivity:
            @staticmethod
            def Get():return owner.activity
        class NativeCalls:
            @staticmethod
            def WebViewVisible(v):owner.visible.append(v)
        class Handler:
            def __init__(self,*args):self.tasks=[]
            def postDelayed(self,task,delay):self.tasks.append((task,delay))
            def removeCallbacks(self,task):self.tasks=[t for t in self.tasks if t[0] is not task]
        class Looper:
            @staticmethod
            def getMainLooper():return object()
        class Web:
            def __init__(self,*args):self.destroyed=False;self.title='赛程';self.calls=[];owner.webs.append(self)
            def getSettings(self):return self
            def getTitle(self):return self.title
            def loadUrl(self,url):self.url=url;self.calls.append(('loadUrl',url))
            def stopLoading(self):self.calls.append(('stopLoading',))
            def destroy(self):self.destroyed=True
            def __getattr__(self,name):return lambda *args:self.calls.append((name,*args))
        class Dialog:
            def __init__(self,*args):self.showing=False;self.window=Window()
            def setContentView(self,v):self.web=v
            def setCancelable(self,v):self.cancelable=v
            def setCanceledOnTouchOutside(self,v):self.outside=v
            def setOnDismissListener(self,l):self.listener=l
            def getWindow(self):return self.window
            def show(self):self.showing=True
            def isShowing(self):return self.showing
            def dismiss(self):
                if self.showing:self.showing=False;self.listener.onDismiss(self)
        classes={'com.epicgames.ue4.GameActivity':GameActivity,'com.epicgames.ue4.NativeCalls':NativeCalls,
                 'android.os.Handler':Handler,'android.os.Looper':Looper,'android.app.Dialog':Dialog,
                 'android.webkit.WebView':Web,'android.webkit.WebViewClient':type('WebViewClient',(),{})}
        self.module=types.ModuleType('java')
        self.module.jclass=lambda name:classes.get(name,object)
        self.module.dynamic_proxy=lambda interface:object


class NativeHostTests(unittest.TestCase):
    def test_dialog_open_reload_return_title_and_cleanup(self):
        java=JavaUi()
        with patch.dict(sys.modules,{'java':java.module}):
            host=native.AndroidScheduleHost()
            self.assertTrue(host.open('http://127.0.0.1:9/player-studio/tournaments/x?host=android'))
            first=host.web
            self.assertEqual(java.visible,[True]);self.assertEqual(java.ui_calls,1)
            self.assertEqual(host.dialog.getWindow().layout,(-1,-1))
            self.assertTrue(host.dialog.cancelable);self.assertFalse(host.dialog.outside)
            self.assertIn(('setAllowFileAccess',False),first.calls)
            self.assertIn(('setJavaScriptCanOpenWindowsAutomatically',False),first.calls)
            host.open('http://127.0.0.1:9/second')
            self.assertIs(first,host.web);self.assertEqual(len(java.webs),1)
            first.title='player-studio-schedule:close';host.poller.run()
            self.assertIsNone(host.dialog);self.assertIsNone(host.web)
            self.assertTrue(first.destroyed);self.assertEqual(host.handler.tasks,[])
            self.assertEqual(java.visible,[True,False])

    def test_explicit_close_restores_native_visibility_and_can_reopen(self):
        java=JavaUi()
        with patch.dict(sys.modules,{'java':java.module}):
            host=native.AndroidScheduleHost();host.open('http://127.0.0.1:9/x')
            host.close();host.close()
            self.assertEqual(java.visible,[True,False])
            host.open('http://127.0.0.1:9/x');self.assertEqual(java.visible,[True,False,True])
            host.close()


if __name__=='__main__':unittest.main()
