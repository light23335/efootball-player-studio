from pathlib import Path
import copy,json,sys,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_v193_binding as binding_fixture
from native_worker_sim import run
from personal_binding import prepare,compose


class WorkerInstallationTests(unittest.TestCase):
 def test_sized_allocator_failure_and_full_install_for_119_routes(self):
  binding_fixture.V193BindingTests.setUpClass();source=binding_fixture.V193BindingTests()
  routes=[dict(source.route,cardId=90000000000+n,portraitKey=str(8000000+n),modelFaceKey=str(8000000+n),thumbnail_names=[str(8000000+n)+'_b','0501_278_f02','',str(8000000+n)+'_m','','0501_m06']) for n in range(119)]
  binding=dict(copy.deepcopy(source.binding),routes=routes);payload=compose(source.payload,routes,binding['profile']);calls=[]
  def allocate(libc,rows,base,size,*args):calls.append(size);return base+0x6000000,'simulated_original'
  with zipfile.ZipFile(source.apk) as z:engine=z.read('lib/arm64-v8a/libUE4.so')
  actual,_=source.actual_loader(allocate);raw=actual.__globals__['_start_legend_portrait_binding'];original=raw.__globals__['allocate_portrait_pages']
  raw.__globals__['allocate_portrait_pages']=actual.__globals__['allocate_portrait_pages']
  broken,_=prepare(actual,binding);before=run(broken,payload,engine)
  self.assertEqual(before['status'],'not_applied');self.assertIn('DIY allocation size changed',before['error']);self.assertEqual(before['patched_hooks'],0)
  raw.__globals__['allocate_portrait_pages']=original;fixed,_=prepare(actual,binding);after=run(fixed,payload,engine)
  self.assertEqual(after['status'],'binding_installed');self.assertEqual(after['patched_hooks'],after['total_hooks']);self.assertEqual(after['total_hooks'],len(payload['hooks']));self.assertGreaterEqual(after['total_hooks'],11);self.assertEqual(calls,[4096])


if __name__=='__main__':unittest.main()
