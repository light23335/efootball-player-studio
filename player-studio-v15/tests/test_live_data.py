from pathlib import Path
import json,sys,tempfile,types,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_live import compile_template,verify_template,reserve_version
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

if __name__=='__main__':unittest.main()
