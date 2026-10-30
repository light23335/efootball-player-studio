"""Execute actual ARM64 routes to verify exact-card isolation and layer order."""
import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from personal_binding import _thumbnail_hook


class PrivateCardTests(unittest.TestCase):
    def test_compact_front_changes_only_portrait_and_suppressed_layers(self):
        from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
        from unicorn import arm64_const as r
        from card_front import front_overrides
        for preset in (False,True):
            profile={'address':0x120000,'original_call':0x130000,'assign':0x140000,'mini_offset':440,'front_date_offset':200,'expected_hex':'00'*64}
            front=front_overrides({'preset_id':'x'} if preset else {},'8000002');payload={'hooks':[]};blob=bytearray()
            _thumbnail_hook(payload,blob,[{'cardId':7,'thumbnail_names':['mini']*6,'front_names':front}],profile)
            for at,address in payload['absolute_fixups']:struct.pack_into('<Q',blob,at,address)
            uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
            for base in (0x100000,0x120000,0x130000,0x140000,0x300000,0x400000):uc.mem_map(base,0x10000)
            uc.mem_write(0x100000,bytes(blob));uc.reg_write(r.UC_ARM64_REG_X19,0x300000);uc.reg_write(r.UC_ARM64_REG_X23,7);uc.reg_write(r.UC_ARM64_REG_SP,0x408000)
            calls=[]
            def intercept(vm,address,size,user):
                if address==profile['assign']:
                    dest,src,n=[vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
                    calls.append((dest-0x300000,bytes(vm.mem_read(src,n)).decode()))
                    ret=vm.reg_read(r.UC_ARM64_REG_X30)
                    for i in range(19):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),0)
                    vm.reg_write(r.UC_ARM64_REG_PC,ret)
                elif address==profile['original_call']:vm.emu_stop()
            uc.hook_add(UC_HOOK_CODE,intercept);uc.emu_start(0x100000,0x150000,count=3000)
            expected=[(440+i*24,'mini') for i in range(6)]+[(200,''),(152,'8000002f'),(128,'')]+([(80,'')] if preset else [])
            self.assertEqual(calls,expected)

    def test_ten_thousand_compact_routes_fit_existing_capacity(self):
        import json
        from personal_binding import compose
        from card_front import front_overrides
        root=Path(__file__).resolve().parents[1]/'resources'
        original=json.loads((root/'native-binding-profile.json').read_text())
        profile=json.loads((root/'native-route-templates.json').read_text());profile['external_routes']=True
        profile['thumbnail_hook']=json.loads((root/'native-thumbnail-hook.json').read_text())
        rows=[{'cardId':90000000+i,'suiteDonorId':89135161919067,'portraitKey':'8000002','modelFaceKey':'8000002',
               'thumbnail_names':['mini']*6,'front_names':front_overrides({'preset_id':'x'},'8000002')} for i in range(10000)]
        result=compose(original,rows,profile)
        self.assertTrue(result['blob_hex']);self.assertTrue(result.get('extension_blob_hex'))

    def test_exact_id_front_and_mini_assignments(self):
        from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
        from unicorn import arm64_const as r
        profile={'address':0x120000,'original_call':0x130000,'assign':0x140000,
                 'mini_offset':440,'front_date_offset':200,'expected_hex':'00'*64}
        card=90159685089463
        front=['','c01234567890','','','','','8000001f','','','']
        mini=['8000001_b','cabcdefghijk','','8000001_m','','']
        partial=[None,None,None,'',None,'','8000002f',None,'',None]
        blob=bytearray();payload={'hooks':[]}
        _thumbnail_hook(payload,blob,[{'cardId':3,'thumbnail_names':['old']*6},
                                    {'cardId':card,'thumbnail_names':mini,'front_names':front},
                                    {'cardId':card+1,'thumbnail_names':['other']*6},
                                    {'cardId':card+2,'thumbnail_names':['mini']*6,'front_names':partial}],profile)
        for offset,address in payload['absolute_fixups']:struct.pack_into('<Q',blob,offset,address)
        for cid in (card,card+1,card+2,card-1,89129161334103):
            uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
            for base in (0x100000,0x120000,0x130000,0x140000,0x300000,0x400000):uc.mem_map(base,0x10000)
            uc.mem_write(0x100000,bytes(blob));uc.reg_write(r.UC_ARM64_REG_X19,0x300000)
            uc.reg_write(r.UC_ARM64_REG_X23,cid);uc.reg_write(r.UC_ARM64_REG_SP,0x408000)
            calls=[];returned=[]
            def intercept(vm,address,size,user):
                if address==profile['assign']:
                    dest,src,n=[vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
                    calls.append((dest-0x300000,bytes(vm.mem_read(src,n)).decode()))
                    ret=vm.reg_read(r.UC_ARM64_REG_X30)
                    for i in range(19):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),0)
                    vm.reg_write(r.UC_ARM64_REG_PC,ret)
                elif address==profile['original_call']:
                    returned.append(True);vm.emu_stop()
            uc.hook_add(UC_HOOK_CODE,intercept);uc.emu_start(0x100000,0x150000,count=3000)
            self.assertTrue(returned)
            expected=([(440+i*24,value) for i,value in enumerate(mini)]+[(200,'')]+
                      [(8+i*24,value) for i,value in enumerate(front)] if cid==card else
                      [(440+i*24,'other') for i in range(6)]+[(200,'')] if cid==card+1 else
                      [(440+i*24,'mini') for i in range(6)]+[(200,'')]+[(8+i*24,v) for i,v in enumerate(partial) if v is not None] if cid==card+2 else [])
            self.assertEqual(calls,expected)

    def test_every_catalogue_design_routes_full_portrait_separately(self):
        import json
        from card_front import front_overrides
        rows=json.loads((Path(__file__).resolve().parents[1]/'resources/native-card-presets.json').read_text('utf8'))['rows']
        self.assertTrue(any(r['native_style']=='0501' and r['native_agent']==6 for r in rows))
        for row in rows:
            front=front_overrides(dict(row,preset_id=row['id']),'8000002')
            self.assertEqual(front[6],'8000002f');self.assertEqual(front[3],'')
            self.assertIsNone(front[0]);self.assertIsNone(front[1]);self.assertEqual(len(front),10)


if __name__=='__main__':unittest.main()
