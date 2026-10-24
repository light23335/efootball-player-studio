import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).absolute().parents[1]))
from apk_delta import ApkDelta, apk_info, signer_fingerprints
from app import Store

ROOT=Path(__file__).absolute().parents[1]


class DeltaTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT.parent/'.work/delta-unit';parent.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=Store(self.root/'data')
        self.worker=ApkDelta(ROOT,self.store)
        payload=random.Random(14).randbytes(2*1024*1024)
        self.source=self.root/'original.apk';self.target=self.root/'updated.apk'
        for path,value in [(self.source,payload),(self.target,payload[:40000]+b'new-player'+payload[40010:])]:
            with zipfile.ZipFile(path,'x') as z:
                z.writestr(zipfile.ZipInfo('AndroidManifest.xml'),b'fixture-not-installable')
                z.writestr(zipfile.ZipInfo('assets/game.bin'),value)

    def run_job(self,**body):
        self.worker.start(body)
        deadline=time.monotonic()+30
        while self.worker.status()['phase']=='working' and time.monotonic()<deadline:time.sleep(.02)
        state=self.worker.status();self.assertNotEqual(state['phase'],'working');return state

    def test_roundtrip_hash_exact_original_untouched(self):
        original=self.source.read_bytes()
        result=self.run_job(operation='create',source=str(self.source),target=str(self.target))
        self.assertEqual(result['phase'],'done',result)
        packet=result['result']['path'];self.assertLess(Path(packet).stat().st_size,20000)
        with zipfile.ZipFile(packet) as z:self.assertEqual(set(z.namelist()),{'manifest.json','payload.vcdiff'})
        result=self.run_job(operation='apply',source=str(self.source),patch=packet)
        self.assertEqual(result['phase'],'done',result)
        self.assertEqual(Path(result['result']['path']).read_bytes(),self.target.read_bytes())
        self.assertEqual(self.source.read_bytes(),original)
        self.assertFalse(result['result']['manifest']['same_signer'])

    def test_wrong_source_and_corrupt_payload_rejected(self):
        result=self.run_job(operation='create',source=str(self.source),target=str(self.target))
        packet=Path(result['result']['path']);count=len(list((self.store.root/'exports').glob('*.apk')))
        rejected=self.run_job(operation='apply',source=str(self.target),patch=str(packet))
        self.assertEqual(rejected['phase'],'error');self.assertIn('不匹配',rejected['message'])
        bad=self.root/'bad.efupdate'
        with zipfile.ZipFile(packet) as src,zipfile.ZipFile(bad,'x') as dst:
            dst.writestr('manifest.json',src.read('manifest.json'))
            b=bytearray(src.read('payload.vcdiff'));b[-1]^=1;dst.writestr('payload.vcdiff',b)
        rejected=self.run_job(operation='apply',source=str(self.source),patch=str(bad))
        self.assertEqual(rejected['phase'],'error');self.assertIn('损坏',rejected['message'])
        self.assertEqual(count,len(list((self.store.root/'exports').glob('*.apk'))))

    def test_missing_and_identical_target_rejected(self):
        state=self.run_job(operation='create',source=str(self.source),target=str(self.source))
        self.assertEqual(state['phase'],'error');self.assertIn('完全相同',state['message'])


if __name__=='__main__':unittest.main()
