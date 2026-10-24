from pathlib import Path
import json,marshal,sys,unittest,struct
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_binding_source import read_installer,verify_installer
from personal_binding import fingerprint,compose,relocate_code

class V15BindingSourceTests(unittest.TestCase):
    def test_literal_inspection_does_not_execute_wrapped_apk_module(self):
        module=compile("def _start_legend_portrait_binding(root):\n    PAYLOAD={'blob_hex':'00','hooks':[], 'offsets':{},'back_fixup':0}\n    raise RuntimeError('must not execute')\nraise RuntimeError('must not execute')\n",'fixture.py','exec')
        wrapped=compile('import marshal\nexec(marshal.loads('+repr(marshal.dumps(module))+'),globals())','wrapper.py','exec')
        with patch('native_binding_source.module_reader',return_value=lambda name:wrapped):
            payload,code=read_installer('unused.apk')
        self.assertEqual(payload['blob_hex'],'00');self.assertEqual(code.co_name,'_start_legend_portrait_binding')

    def test_real_v15_installer_preflight_keeps_fingerprint_and_page_contract(self):
        root=Path(__file__).resolve().parents[2];apk=root/'球员工坊-V15/原始APK/73efootball-V15.apk'
        if not apk.is_file():self.skipTest('requires the original V15 APK')
        resources=Path(__file__).resolve().parents[1]/'resources';payload,code=read_installer(apk)
        self.assertEqual(payload,json.loads((resources/'native-binding-profile.json').read_text()))
        profile=json.loads((resources/'native-route-templates.json').read_text());profile.update(external_routes=True,club_emblems=True)
        for field,file in (('position_hook','native-position-hook.json'),('acquisition_hook','native-acquisition-hook.json'),('overall_hook','native-overall-hook.json'),('thumbnail_hook','native-thumbnail-hook.json')):profile[field]=json.loads((resources/file).read_text())
        route={'cardId':990001,'suiteDonorId':990001,'portraitKey':'8900001','modelFaceKey':'8900001','club_id':108,'position':1,'maximum_overall':99,'presentation_rarity':10}
        route['thumbnail_names']=['8900001_b','0501_278_f02','','8900001_m','','0501_m06']
        binding={'original_fingerprint':fingerprint(payload),'routes':[route],'profile':profile};report=verify_installer(code,binding)
        self.assertEqual(report['page_bytes'],4096);self.assertLessEqual(report['code_bytes'],report['page_bytes'])
        result=compose(payload,[route],profile);original=bytes.fromhex(payload['blob_hex']);root_bytes=bytearray.fromhex(result['blob_hex']);cut=result['root_prefix_bytes']
        self.assertEqual(cut,2400);self.assertEqual(root_bytes[:cut],original[:cut])
        struct.pack_into('<Q',root_bytes,result['back_fixup'],0x7000000000+result['hooks'][0]['address']+4)
        struct.pack_into('<Q',root_bytes,result['thumbnail_back_fixup'],0x7001234567)
        root_addr,ext_addr=0x7100000000,0x7300000000
        relocated,extension=relocate_code(result,bytes(root_bytes),root_addr,ext_addr,0x7500000000)
        changed=set()
        for ref in result['native_appendix_relocations']:
            at=ref['offset']-cut;word=struct.unpack_from('<I',extension,at)[0];changed.update(range(at,at+4))
            if ref['kind']=='branch':
                bits=26 if word&0x7c000000==0x14000000 else (14 if word&0x7e000000==0x36000000 else 19)
                value=(word>>(0 if bits==26 else 5))&((1<<bits)-1)
                if value&(1<<(bits-1)):value-=1<<bits
                slot=at+value*4
                self.assertEqual(extension[slot:slot+8],struct.pack('<II',0x58000050,0xd61f0200))
                self.assertEqual(struct.unpack_from('<Q',extension,slot+8)[0],root_addr+ref['target'])
            else:
                value=(word>>5)&0x7ffff
                if value&(1<<18):value-=1<<19
                slot=at+value*4
                self.assertEqual(extension[slot:slot+8],root_bytes[ref['target']:ref['target']+8])
        appendix=original[cut:]
        self.assertTrue(all(extension[i]==byte for i,byte in enumerate(appendix) if i not in changed))
        binding['original_fingerprint']='0'*64
        with self.assertRaisesRegex(ValueError,'指纹'):verify_installer(code,binding)

if __name__=='__main__':unittest.main()
