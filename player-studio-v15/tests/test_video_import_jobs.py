from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sys,tempfile,threading,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from card_motion_jobs import VideoImports,Cancelled
import custom_motion_import as motion


class VideoJobsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  for name in('tmp','assets'):(self.root/name).mkdir()
  self.source=self.root/'source.mp4';self.source.write_bytes(b'local video fixture')
  self.store=SimpleNamespace(root=self.root)
 def tearDown(self):self.tmp.cleanup()
 def finish(self,worker):
  deadline=time.monotonic()+3
  while worker.status()['phase']=='working'and time.monotonic()<deadline:time.sleep(.01)
  self.assertNotEqual(worker.status()['phase'],'working');return worker.status()
 def test_cancel_is_observable_does_not_commit_and_keeps_other_job_identity(self):
  entered=threading.Event()
  def convert(*args,context=None,**kwargs):
   entered.set()
   while True:context.check_cancel();time.sleep(.005)
  worker=VideoImports(self.store,'ffmpeg',convert)
  first=worker.start({'path':str(self.source)});self.assertTrue(entered.wait(1))
  with self.assertRaisesRegex(ValueError,'已有视频'):worker.start({'path':str(self.source)})
  with self.assertRaisesRegex(ValueError,'未取消其它'):worker.cancel('old-id')
  worker.cancel(first['job_id']);state=self.finish(worker)
  self.assertEqual(state['phase'],'cancelled');self.assertNotIn('result',state)
  self.assertTrue((self.root/'video-import-reports'/ (first['job_id']+'.json')).is_file())
 def test_completed_job_can_be_followed_by_an_independent_job(self):
  worker=VideoImports(self.store,'ffmpeg',lambda *a,**kw:{'mini':{'asset_id':'fixture'}})
  a=worker.start({'path':str(self.source),'role':'mini'});one=self.finish(worker)
  self.assertEqual(one['phase'],'done');self.assertEqual(one['result']['mini']['asset_id'],'fixture')
  b=worker.start({'path':str(self.source),'role':'mini'});self.assertNotEqual(a['job_id'],b['job_id']);self.finish(worker)
  with self.assertRaisesRegex(ValueError,'已更新'):worker.status(a['job_id'])
 def test_cache_is_role_specific_and_corrupt_assets_are_not_reused(self):
  calls=[]
  def encode(source,destination,ffmpeg,w,h,fps,seconds,x,y,**kw):
   calls.append((w,h,x,y));Path(destination).write_bytes(f'{w}x{h}:{x}:{y}'.encode())
  def mux(source,destination):
   Path(destination).write_bytes(b'USM'+Path(source).read_bytes());Path(destination).with_suffix('.webm').write_bytes(b'WEBM'+Path(source).read_bytes());return{'duration':10 if'large'in str(source)else 5}
  with patch.object(motion,'encode',encode),patch.object(motion,'mux_ivf',mux),patch.object(motion,'BATCH_ENCODER',None):
   first=motion.convert(self.store,'ffmpeg',self.source,['large','mini']);self.assertEqual(len(calls),2)
   self.assertEqual(motion.convert(self.store,'ffmpeg',self.source,['large','mini']),first);self.assertEqual(len(calls),2)
   changed=motion.convert(self.store,'ffmpeg',self.source,['large','mini'],50,-25)
   self.assertEqual(len(calls),3);self.assertEqual(changed['large'],first['large']);self.assertNotEqual(changed['mini'],first['mini'])
   (self.root/'assets'/first['mini']['asset_id']).write_bytes(b'corrupt')
   # A corrupt content-addressed user asset must be reported, never accepted.
   with self.assertRaisesRegex(ValueError,'已有动画素材校验失败'):motion.convert(self.store,'ffmpeg',self.source,['mini'])
   self.assertEqual(len(calls),4)
 def test_batch_backend_only_receives_missing_roles_and_cancel_cleans_work(self):
  received=[]
  def batch(source,folder,specs,context=None):
   received.append([s['role']for s in specs])
   for s in specs:(folder/(s['role']+'.ivf')).write_bytes(s['role'].encode())
   return{'png_roundtrips':0}
  def mux(source,target):
   Path(target).write_bytes(Path(source).read_bytes());Path(target).with_suffix('.webm').write_bytes(b'preview'+Path(source).read_bytes());return{'duration':5}
  with patch.object(motion,'BATCH_ENCODER',batch),patch.object(motion,'mux_ivf',mux):
   motion.convert(self.store,'ffmpeg',self.source,['large','mini'])
   motion.convert(self.store,'ffmpeg',self.source,['large','mini'],20,0)
   self.assertEqual(received,[['large','mini'],['mini']]);self.assertEqual(list((self.root/'tmp').iterdir()),[])
   self.source.write_bytes(b'another source')
   def cancelled(*a,**kw):raise Cancelled('cancel')
   with patch.object(motion,'BATCH_ENCODER',cancelled),self.assertRaises(Cancelled):motion.convert(self.store,'ffmpeg',self.source,['mini'])
   self.assertEqual(list((self.root/'tmp').iterdir()),[])

if __name__=='__main__':unittest.main()
