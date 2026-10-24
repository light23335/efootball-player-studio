import threading,time,unittest,uuid
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from window_sessions import WindowSessions

class WindowSessionTests(unittest.TestCase):
 def test_large_project_delta_keeps_other_shared_definitions(self):
  from window_sessions import apply_project_delta
  project={'custom_boosters':[{'id':i,'effects':{'34':3}} for i in range(10000)]}
  patched=apply_project_delta(project,[{'op':'set','path':['custom_boosters',9999,'effects','34'],'value':7}])
  self.assertEqual(patched['custom_boosters'][9999]['effects']['34'],7);self.assertEqual(project['custom_boosters'][9999]['effects']['34'],3);self.assertEqual(len(patched['custom_boosters']),10000)
 def test_http_close_persists_latest_edit_and_stops_service(self):
  import app,tempfile,json,http.client,copy
  with tempfile.TemporaryDirectory() as folder:
   store=app.Store(folder);server=app.StudioServer(('127.0.0.1',0),store,'window-test-token')
   server.window_sessions.grace=.02
   thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
   try:
    session=str(uuid.uuid4());client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
    headers={'X-Studio-Token':'window-test-token','Content-Type':'application/json'}
    client.request('POST','/api/window/open',json.dumps({'session':session}),headers);response=client.getresponse();response.read();self.assertEqual(response.status,200)
    project=copy.deepcopy(store.project);project['identity']['name']='关闭前的最新编辑'
    client.request('POST','/api/window/close?token=window-test-token',json.dumps({'session':session,'project':project}),{'Content-Type':'application/json'})
    response=client.getresponse();response.read();self.assertEqual(response.status,200);client.close()
    thread.join(1);self.assertFalse(thread.is_alive());self.assertEqual(json.loads(store.project_path.read_text(encoding='utf8'))['identity']['name'],'关闭前的最新编辑')
   finally:server.shutdown();server.server_close()
 def test_last_close_saves_and_exits(self):
  exited=threading.Event();saved=[];session=str(uuid.uuid4());windows=WindowSessions(exited.set,.02)
  windows.open(session);self.assertTrue(windows.close(session,lambda:saved.append(True))['closed'])
  self.assertTrue(exited.wait(.3));self.assertEqual(saved,[True])
 def test_reload_and_other_open_windows_prevent_shutdown(self):
  exited=threading.Event();windows=WindowSessions(exited.set,.04);first=str(uuid.uuid4());second=str(uuid.uuid4())
  windows.open(first);windows.close(first,lambda:None);windows.open(second)
  self.assertFalse(exited.wait(.1));windows.close(second,lambda:None);self.assertTrue(exited.wait(.3))
 def test_unregistered_close_cannot_save_or_stop(self):
  exited=threading.Event();windows=WindowSessions(exited.set,.01);saved=[]
  self.assertFalse(windows.close(str(uuid.uuid4()),lambda:saved.append(True))['closed'])
  self.assertEqual(saved,[]);self.assertFalse(exited.is_set())
