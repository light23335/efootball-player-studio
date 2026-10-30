import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/src/main/python'))
from android_backend import ui_options

class PowerOptionsTests(unittest.TestCase):
 def test_default_on_and_survives_a_new_host_without_changing_other_data(self):
  with tempfile.TemporaryDirectory()as folder:
   store=SimpleNamespace(root=Path(folder));sentinel=store.root/'project.json';sentinel.write_bytes(b'keep')
   self.assertEqual(ui_options(store,{}),{'reduce_power':True})
   self.assertFalse((store.root/'android-ui-options.json').exists())
   self.assertEqual(ui_options(store,{'reduce_power':True}),{'reduce_power':True})
   self.assertEqual(ui_options(SimpleNamespace(root=Path(folder)),{}),{'reduce_power':True})
   self.assertEqual(ui_options(store,{'reduce_power':False}),{'reduce_power':False})
   self.assertEqual(ui_options(SimpleNamespace(root=Path(folder)),{}),{'reduce_power':False})
   self.assertEqual(sentinel.read_bytes(),b'keep')
 def test_only_explicit_boolean_is_accepted(self):
  with tempfile.TemporaryDirectory()as folder:
   for body in ({'reduce_power':1},{'reduce_power':'true'},{'other':True},[],None):
    if body is None:continue
    with self.assertRaises(ValueError):ui_options(SimpleNamespace(root=Path(folder)),body)

if __name__=='__main__':unittest.main()
