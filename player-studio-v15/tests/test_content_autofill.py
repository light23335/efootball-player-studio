from pathlib import Path
import io,json,sys,tempfile,types,unittest,zipfile,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_autofill import Overlay,missing,retain_materials,cache_path,CPK,STEM
from export_payload import FilePayload

class ImportedContentTests(unittest.TestCase):
 def test_partial_receipt_is_retryable_and_same_id_changed_digest_is_rejected(self):
  wanted={'packages':[{'package_id':'v20','manifest_sha256':'good'}]}
  self.assertEqual(missing({'packages':[]},wanted),['v20'])
  self.assertEqual(missing({'packages':[dict(wanted['packages'][0],pending_entities=['card:1'])]},wanted),['v20'])
  self.assertEqual(missing(wanted,wanted),[])
  with self.assertRaisesRegex(ValueError,'v20'):missing({'packages':[{'package_id':'v20','manifest_sha256':'bad'}]},wanted)
 def test_virtual_source_preserves_real_zip_and_streams_file_payload(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);apk=root/'source.apk';data=root/'large.bin';data.write_bytes(b'cache resource')
   with zipfile.ZipFile(apk,'w')as z:z.writestr('unchanged',b'original');z.writestr('changed',b'old')
   original=apk.read_bytes()
   with zipfile.ZipFile(apk)as z:
    overlay=Overlay(z,{'changed':b'new','added':FilePayload.from_path(data)})
    self.assertEqual(overlay.read('unchanged'),b'original');self.assertEqual(overlay.read('changed'),b'new')
    with overlay.open('added')as stream:self.assertEqual(stream.read(),b'cache resource')
    self.assertEqual(set(overlay.namelist()),{'unchanged','changed','added'})
   self.assertEqual(apk.read_bytes(),original)
 def test_import_keeps_data_and_cache_references_without_a_delta_zip(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);resources=root/'resources';resources.mkdir();containers=root/'containers';containers.mkdir();apk=root/'imported.apk'
   catalogue={'format':'studio-content-catalogue-v1','packages':[{'package_id':'v20','manifest_sha256':'x'}]}
   library=types.SimpleNamespace(resources=resources,containers=containers,profile={'native_engine_sha256':'engine'})
   with zipfile.ZipFile(apk,'w')as z:
    z.writestr('assets/gateway-release/release-manifest.json',json.dumps({'release_id':'v17'}));z.writestr(CPK,b'cached CPK')
    for suffix in('.utoc','.ucas'):
     raw=('cache '+suffix).encode();z.writestr(STEM+suffix,raw);(containers/('pc3700_mobile_and_10_P'+suffix)).write_bytes(raw)
   result=retain_materials(apk,library,catalogue);apk.unlink()
   with zipfile.ZipFile(result)as z:
    material=json.loads(z.read('materials.json'));self.assertEqual(z.read(CPK),b'cached CPK')
    self.assertEqual(material['catalogue'],catalogue);self.assertEqual(material['items'][STEM+'.ucas']['cache'],'pc3700_mobile_and_10_P.ucas')
    self.assertNotIn(STEM+'.ucas',z.namelist());self.assertFalse(any(n.endswith('.apk')for n in z.namelist()))
   self.assertEqual(cache_path(resources,catalogue),result)
if __name__=='__main__':unittest.main()
