from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).absolute().parents[1]))
from apk_format import local_signer,sign_v2,verify_v2,replace_entries,layout


class ApkFormatTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).absolute().parents[2]/'.work/apk-format-unit';parent.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.raw=self.root/'unsigned.apk'
        with zipfile.ZipFile(self.raw,'x') as z:
            z.writestr('AndroidManifest.xml',b'unit-test-fixture')
            z.writestr('lib/arm64-v8a/libUE4.so',b'native-data-position-preserved'*600)
            z.writestr('assets/players.cpk',b'old player data')
        self.key,self.cert=local_signer(self.root/'signing')

    def test_signature_and_tampering(self):
        signed=self.root/'signed.apk';result=sign_v2(self.raw,signed,self.key,self.cert)
        check=verify_v2(signed);self.assertTrue(check['verified_v2']);self.assertEqual(check['signer_sha256'],result['signer_sha256'])
        with signed.open('r+b') as f:f.seek(80);b=f.read(1);f.seek(80);f.write(bytes([b[0]^1]))
        with self.assertRaises(ValueError):verify_v2(signed)

    def test_update_preserves_original_local_offsets_and_signing_identity(self):
        original=self.root/'original.apk';sign_v2(self.raw,original,self.key,self.cert)
        updated=self.root/'updated-unsigned.apk';replace_entries(original,updated,{'assets/players.cpk':b'new player data','assets/personal.json':b'{}'})
        with zipfile.ZipFile(original) as before,zipfile.ZipFile(updated) as after:
            for n in ['AndroidManifest.xml','lib/arm64-v8a/libUE4.so']:
                self.assertEqual(before.getinfo(n).header_offset,after.getinfo(n).header_offset)
                self.assertEqual(before.read(n),after.read(n))
            self.assertEqual(after.read('assets/players.cpk'),b'new player data')
            self.assertEqual(len(after.namelist()),len(set(after.namelist())))
        final=self.root/'updated-signed.apk';sign_v2(updated,final,*local_signer(self.root/'signing'))
        self.assertEqual(verify_v2(original)['signer_sha256'],verify_v2(final)['signer_sha256'])


if __name__=='__main__':unittest.main()
