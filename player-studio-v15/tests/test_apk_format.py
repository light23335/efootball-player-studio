from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import io
import struct
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).absolute().parents[1]))
from apk_format import local_signer,sign_v2,verify_v2,replace_entries,layout,content_digest


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

    def test_update_preserves_payloads_alignment_and_signing_identity(self):
        original=self.root/'original.apk';sign_v2(self.raw,original,self.key,self.cert)
        updated=self.root/'updated-unsigned.apk';replace_entries(original,updated,{'assets/players.cpk':b'new player data','assets/personal.json':b'{}'})
        with zipfile.ZipFile(original) as before,zipfile.ZipFile(updated) as after:
            for n in ['AndroidManifest.xml','lib/arm64-v8a/libUE4.so']:
                self.assertEqual(before.read(n),after.read(n))
            with updated.open('rb') as stream:
                for item in after.infolist():
                    stream.seek(item.header_offset+26);n,e=struct.unpack('<HH',stream.read(4))
                    self.assertEqual((item.header_offset+30+n+e)%(16384 if item.filename.endswith('.so') else 4),0)
            self.assertEqual(after.read('assets/players.cpk'),b'new player data')
            self.assertEqual(len(after.namelist()),len(set(after.namelist())))
        final=self.root/'updated-signed.apk';sign_v2(updated,final,*local_signer(self.root/'signing'))
        self.assertEqual(verify_v2(original)['signer_sha256'],verify_v2(final)['signer_sha256'])

    def test_repeated_signed_exports_reclaim_old_replacement_bytes(self):
        source=self.raw;sizes=[]
        for index in range(4):
            unsigned=self.root/f'u{index}.apk';output=self.root/f's{index}.apk'
            replace_entries(source,unsigned,{'assets/players.cpk':bytes(1024*1024)})
            sign_v2(unsigned,output,self.key,self.cert);verify_v2(output)
            sizes.append(output.stat().st_size);source=output
        self.assertEqual(len(set(sizes)),1)

    def test_deflate_descriptor_and_metadata_survive_without_recompression(self):
        class Pipe(io.BytesIO):
            def seekable(self):return False
            def seek(self,*args):raise io.UnsupportedOperation()
        stream=Pipe()
        item=zipfile.ZipInfo('assets/中文.txt');item.compress_type=zipfile.ZIP_DEFLATED
        item.comment=b'entry comment';item.extra=struct.pack('<HH4s',0xcafe,4,b'meta')
        with zipfile.ZipFile(stream,'w') as z:
            z.comment=b'apk comment';z.writestr(item,b'abc'*10000)
        source=self.root/'descriptor.apk';source.write_bytes(stream.getvalue())
        output=self.root/'descriptor-fixed.apk';replace_entries(source,output,{})
        def compressed(path,item):
            with path.open('rb') as f:
                f.seek(item.header_offset+26);n,e=struct.unpack('<HH',f.read(4));f.seek(item.header_offset+30+n+e)
                return f.read(item.compress_size)
        with zipfile.ZipFile(source) as before,zipfile.ZipFile(output) as after:
            a,b=before.infolist()[0],after.infolist()[0]
            self.assertTrue(a.flag_bits&8);self.assertFalse(b.flag_bits&8)
            self.assertEqual(compressed(source,a),compressed(output,b))
            self.assertEqual(after.read(b),before.read(a));self.assertEqual(a.extra,b.extra)
            self.assertEqual(a.comment,b.comment);self.assertEqual(after.comment,before.comment)

    def test_hidden_old_local_payloads_are_removed(self):
        # Legacy writers left superseded local records before the live ones.
        source=self.root/'bloated.apk';source.write_bytes(b'old-deleted-resource'*100000)
        with zipfile.ZipFile(source,'a') as z:z.writestr('assets/live',b'live')
        output=self.root/'compact.apk';replace_entries(source,output,{})
        with zipfile.ZipFile(output) as z:self.assertEqual(z.read('assets/live'),b'live')
        self.assertLess(output.stat().st_size,500)

    def test_capacity_preflight_fails_before_creating_output(self):
        output=self.root/'too-big.apk'
        with patch('apk_format.UINT32_LIMIT',32768),patch('apk_format.SIGNING_RESERVE',4096):
            with self.assertRaisesRegex(ValueError,'最大文件.*players.cpk'):
                replace_entries(self.raw,output,{'assets/players.cpk':bytes(100000)})
        self.assertFalse(output.exists())

    def test_replaced_ucas_can_be_stored_with_identical_payload_and_alignment(self):
        source=self.root/'compressed.apk'
        with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED)as z:
            z.writestr('assets/test.ucas',b'old');z.writestr('assets/keep.txt',b'unchanged')
        payload=bytes(range(256))*1000;output=self.root/'stored.apk'
        report=replace_entries(source,output,{'assets/test.ucas':payload},store_ucas=True,prepare_signing=True)
        with zipfile.ZipFile(output)as z,output.open('rb')as f:
            item=z.getinfo('assets/test.ucas');self.assertEqual(item.compress_type,zipfile.ZIP_STORED)
            self.assertEqual(z.read(item),payload);self.assertEqual(z.read('assets/keep.txt'),b'unchanged')
            self.assertEqual(z.getinfo('assets/keep.txt').compress_type,zipfile.ZIP_DEFLATED)
            f.seek(item.header_offset+26);n,e=struct.unpack('<HH',f.read(4))
            self.assertEqual((item.header_offset+30+n+e)%4,0)
        self.assertEqual(report['content_digest'],content_digest(output).hex())

    def test_streamed_digest_and_consuming_signer_match_the_independent_signer(self):
        for size in(0,1,1024*1024-1,1024*1024+1):
            output=self.root/f'stream-{size}.apk'
            prepared=replace_entries(self.raw,output,{'assets/players.cpk':b'x'*size},prepare_signing=True)
            baseline=self.root/f'baseline-{size}.apk';sign_v2(output,baseline,self.key,self.cert)
            signed=self.root/f'fast-{size}.apk'
            with patch('apk_format.content_digest',side_effect=AssertionError('Repeated hash')),patch('apk_format.copy_bytes',side_effect=AssertionError('Payload recopy')):
                report=sign_v2(output,signed,self.key,self.cert,prepared=prepared,consume=True)
            self.assertFalse(output.exists());self.assertTrue(report['digest_reused']);self.assertTrue(report['payload_recopy_avoided'])
            self.assertEqual(signed.read_bytes(),baseline.read_bytes());self.assertTrue(verify_v2(signed)['verified_v2'])

    def test_changed_unsigned_file_invalidates_prepared_digest(self):
        output=self.root/'changed.apk';prepared=replace_entries(self.raw,output,{},prepare_signing=True)
        with output.open('r+b')as f:f.seek(80);value=f.read(1);f.seek(80);f.write(bytes([value[0]^1]))
        signed=self.root/'changed-signed.apk'
        report=sign_v2(output,signed,self.key,self.cert,prepared=prepared,consume=True)
        self.assertFalse(report['digest_reused']);self.assertTrue(verify_v2(signed)['verified_v2'])

    def test_consuming_signer_keeps_existing_destination_and_input_intact(self):
        destination=self.root/'existing.apk';destination.write_bytes(b'keep')
        before=self.raw.read_bytes()
        with self.assertRaisesRegex(ValueError,'new file'):sign_v2(self.raw,destination,self.key,self.cert,consume=True)
        self.assertEqual(destination.read_bytes(),b'keep');self.assertEqual(self.raw.read_bytes(),before)


if __name__=='__main__':unittest.main()
