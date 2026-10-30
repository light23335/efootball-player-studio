"""Exercise Android's real signing adapter and resource export call site."""
import hashlib,io,json,struct,sys,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app/src/main/python'),
              str(Path(__file__).resolve().parents[2]/'player-studio-v15')]
import apk_format as apk
from android_package import AndroidPackage,sign_v2_in_place
from apk_installation import RESOURCES,COEXIST_RESOURCES,identity


def manifest(package):
    strings=['manifest','package',package];data=bytearray();offsets=[]
    for value in strings:
        offsets.append(len(data));data.extend(struct.pack('<H',len(value))+value.encode('utf-16le')+b'\0\0')
    data.extend(bytes((-len(data))%4));start=28+len(strings)*4
    pool=struct.pack('<HHI5I',1,28,start+len(data),len(strings),0,0,start,0)
    pool+=struct.pack('<3I',*offsets)+data
    node=struct.pack('<HHIII',0x102,16,56,0,0xffffffff)
    node+=struct.pack('<IIHHHHHH',0xffffffff,0,20,20,1,0,0,0)
    node+=struct.pack('<IIIHBBI',0xffffffff,1,2,8,0,3,2)
    end=struct.pack('<HHIIIII',0x103,16,24,0,0xffffffff,0xffffffff,0)
    body=pool+node+end
    return struct.pack('<HHI',3,8,8+len(body))+body


class AndroidSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.key,self.cert=apk.local_signer(self.root/'signing')
        self.source=self.root/'game.apk'
        with zipfile.ZipFile(self.source,'w')as z:
            z.writestr('AndroidManifest.xml',manifest('com.efootball.revival.local'))
            z.writestr('assets/players.cpk',b'original game data')

    def test_prepared_game_payload_reuses_digest_and_matches_pc_signature(self):
        for size in(0,1024*1024+1):
            with self.subTest(size=size):
                unsigned=self.root/f'unsigned-{size}.apk';signed=self.root/f'android-{size}.apk'
                prepared=apk.replace_entries(self.source,unsigned,{'assets/players.cpk':b'x'*size},prepare_signing=True)
                baseline=self.root/f'pc-{size}.apk';apk.sign_v2(unsigned,baseline,self.key,self.cert)
                with patch('apk_format.content_digest',side_effect=AssertionError('Repeated digest')) as digest_check, \
                     patch('apk_format.copy_bytes',side_effect=AssertionError('Payload recopy')):
                    report=sign_v2_in_place(unsigned,signed,self.key,self.cert,prepared=prepared,consume=True)
                self.assertFalse(unsigned.exists());self.assertTrue(report['digest_reused'])
                self.assertTrue(report['payload_recopy_avoided']);self.assertEqual(signed.read_bytes(),baseline.read_bytes())
                self.assertTrue(apk.verify_v2(signed)['verified_v2'])

    def test_legacy_call_consumes_input_but_explicit_copy_preserves_it(self):
        preserved=self.root/'preserved.apk'
        report=sign_v2_in_place(self.source,preserved,self.key,self.cert,consume=False)
        self.assertTrue(self.source.exists());self.assertFalse(report['payload_recopy_avoided'])
        consumed=self.root/'consumed.apk';sign_v2_in_place(self.source,consumed,self.key,self.cert)
        self.assertFalse(self.source.exists());self.assertEqual(consumed.read_bytes(),preserved.read_bytes())
        self.assertTrue(apk.verify_v2(consumed)['verified_v2'])

    def test_changed_unsigned_file_recomputes_digest(self):
        unsigned=self.root/'changed.apk';prepared=apk.replace_entries(self.source,unsigned,{},prepare_signing=True)
        with zipfile.ZipFile(unsigned)as z:offset=z.getinfo('assets/players.cpk').header_offset
        with unsigned.open('r+b')as f:
            f.seek(offset+26);n,e=struct.unpack('<HH',f.read(4));f.seek(offset+30+n+e)
            value=f.read(1);f.seek(-1,1);f.write(bytes([value[0]^1]))
        output=self.root/'changed-signed.apk'
        report=sign_v2_in_place(unsigned,output,self.key,self.cert,prepared=prepared,consume=True)
        self.assertFalse(report['digest_reused']);self.assertTrue(apk.verify_v2(output)['verified_v2'])

    def test_existing_output_never_overwritten(self):
        output=self.root/'existing.apk';output.write_bytes(b'keep');before=self.source.read_bytes()
        with self.assertRaises(ValueError):sign_v2_in_place(self.source,output,self.key,self.cert,prepared={},consume=True)
        self.assertEqual(output.read_bytes(),b'keep');self.assertEqual(self.source.read_bytes(),before)

    def test_companion_worker_exports_update_and_coexist_with_android_and_pc_signers(self):
        source=self.root/'resource.apk';payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w')as z:z.writestr('native/resource',b'keep resource bytes')
        with zipfile.ZipFile(source,'w')as z:
            z.writestr('AndroidManifest.xml',manifest(RESOURCES))
            z.writestr('assets/resource-bootstrap/resources.zip',payload.getvalue())
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        for label,signer in(('android',sign_v2_in_place),('pc',apk.sign_v2)):
            for mode,package in(('update',RESOURCES),('coexist',COEXIST_RESOURCES)):
                with self.subTest(platform=label,mode=mode):
                    folder=self.root/(label+'-'+mode);(folder/'tmp').mkdir(parents=True);(folder/'exports').mkdir()
                    store=SimpleNamespace(root=folder);compiler=AndroidPackage(SimpleNamespace(store=store),folder,'')
                    with patch('native_package.sign_v2',wraps=signer)as actual:
                        compiler._companion(source,mode)
                    state=compiler.status();self.assertEqual(state['phase'],'done',state)
                    self.assertTrue(actual.call_args.kwargs['consume'])
                    self.assertIn('content_digest',actual.call_args.kwargs['prepared'])
                    output=Path(state['result']['path']);self.assertTrue(apk.verify_v2(output)['verified_v2'])
                    self.assertEqual(identity(output)['package'],package)
                    with zipfile.ZipFile(output)as z:self.assertEqual(z.read('assets/resource-bootstrap/resources.zip'),payload.getvalue())
                    self.assertEqual(json.loads((folder/'resource-installations.json').read_text())[mode]['package'],package)
                    self.assertFalse(list((folder/'tmp').iterdir()))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
