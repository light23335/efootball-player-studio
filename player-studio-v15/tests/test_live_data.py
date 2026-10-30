from pathlib import Path
import json,sys,tempfile,types,unittest,io,zipfile,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_live import compile_template,verify_template,reserve_version,verify_apk
from personal_runtime import patch_resource_checks

class LiveDataTests(unittest.TestCase):
    def template(self):return {'version_file':json.dumps({'version':2026101904,'dt870Hash':'old','dt870FileSize':4,'dt880':[{'name':'keep'}]}),'livedata_list':[{'name':'dt870_mobile_and.cpk','size':4,'url':'https://example.invalid/dt870_mobile_and.cpk'},{'name':'other.utoc','size':3,'url':'keep'}]}

    def test_changed_cpk_rejects_old_manifest_and_publishes_consistent_contract(self):
        template=self.template();cpk=b'changed-personal-cpk'
        with self.assertRaises(ValueError):verify_template(template,cpk)
        new=compile_template(template,cpk,2026101905);report=verify_template(new,cpk)
        self.assertTrue(report['verified']);self.assertEqual(report['bytes'],len(cpk))
        self.assertEqual(json.loads(new['version_file'])['dt880'],[{'name':'keep'}])
        self.assertEqual(new['livedata_list'][1],template['livedata_list'][1])
        self.assertEqual(json.loads(template['version_file'])['dt870Hash'],'old')

    def test_new_content_advances_version_and_repeat_reuses_it(self):
        root=Path(__file__).resolve().parents[2]/'.work/studio-unit';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as d:
            path=Path(d)/'versions.json';v,registry=reserve_version(path,'V13',self.template(),'hash-a')
            path.write_text(json.dumps(registry))
            repeated,_=reserve_version(path,'V13',self.template(),'hash-a');self.assertEqual(v,repeated)
            changed,registry=reserve_version(path,'V13',self.template(),'hash-b');self.assertGreater(changed,v)
            path.write_text(json.dumps(registry))
            rollback,_=reserve_version(path,'V13',self.template(),'hash-a');self.assertGreater(rollback,changed)

    def test_literal_and_table_resource_checks_still_reject_corrupt_data(self):
        module=types.ModuleType('fixture_legend');old='a'*64;new='b'*64
        exec("_R9_RESOURCE_CHECKS=[{'bytes':54509300,'sha256':'"+old+"'}]\ndef check(size,digest):\n return size==54509300 and digest=='"+old+"'\n",vars(module))
        doc={'original_resource_files':{'cpk':{'bytes':54509300,'sha256':old}},'resource_files':{'cpk':{'bytes':61384704,'sha256':new}}}
        patch_resource_checks(module,doc)
        self.assertTrue(module.check(61384704,new));self.assertFalse(module.check(54509300,old));self.assertFalse(module.check(61384704,'bad'))
        self.assertEqual(module._R9_RESOURCE_CHECKS,[{'bytes':61384704,'sha256':new}])

    def apk(self,download=b'actual-cpk',old_template=False,old_document=False,old_manifest=False):
        cpk=b'actual-cpk';t=compile_template(self.template(),b'old'if old_template else cpk,2026101905)
        report=verify_template(compile_template(self.template(),b'old'if old_document else cpk,2026101905),b'old'if old_document else cpk)
        meta={'bytes':len(cpk),'sha256':hashlib.sha256(cpk).hexdigest()}
        doc={'live_data':report,'resource_files':{'dt870_mobile_and.cpk':meta}}
        values={'custom-resources/legends-v10/dt870_mobile_and.cpk':cpk,'livedata/dt870_mobile_and.cpk':download,
                'work/templates/CMD_LOGIN_LIVEDATA.json':json.dumps(t).encode(),'custom-resources/personal-player-studio/players.json':json.dumps(doc).encode()}
        manifest={'files':[{'path':k,'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()}for k,v in values.items()]}
        if old_manifest:manifest['files'][0]['sha256']='old'
        values['release-manifest.json']=json.dumps(manifest).encode();result=io.BytesIO()
        with zipfile.ZipFile(result,'w')as z:
            for k,v in values.items():z.writestr('assets/gateway-release/'+k,v)
        result.seek(0);return result

    def test_final_apk_checks_both_actual_copies_document_and_release_manifest(self):
        self.assertTrue(verify_apk(self.apk())['active_download_copies_match'])
        for change in ({'download':b'old'},{'old_template':True},{'old_document':True},{'old_manifest':True}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'实时更新校验失败'):verify_apk(self.apk(**change))

if __name__=='__main__':unittest.main()
