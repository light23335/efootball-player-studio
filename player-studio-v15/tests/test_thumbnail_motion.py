from pathlib import Path
from types import SimpleNamespace
import json,sqlite3,struct,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from thumbnail_motion import plan,names
from personal_binding import _thumbnail_hook


class MotionTests(unittest.TestCase):
    def library(self):
        return SimpleNamespace(card_media={'movies':['PesMobile/Content/Movies/PlayerCard/0501_278_f02_v.usm',
            'PesMobile/Content/Movies/PlayerCard/0501_m06_v.usm']},db=lambda:sqlite3.connect(':memory:'),_alias=lambda db,name:name)
    def project(self):
        p=app.default_project();p['native_card']={'native_style':'0501','native_agent':278,'layers':[
            {'slot':'f02','kind':'video','path':'PesMobile/Content/Movies/PlayerCard/0501_278_f02_v.usm'}]};return p
    def test_linked_native_movies_and_foreground_have_distinct_slots(self):
        m=plan(self.project(),self.library());self.assertTrue(m['animated'])
        self.assertEqual(names('8737832',m),['8737832_b','0501_278_f02','','8737832_m','','0501_m06'])
        self.assertEqual(m['layers'][0]['source'],'linked-large')
    def test_native_mini_background_is_used_when_available(self):
        lib=self.library();lib.card_media['movies'].append('PesMobile/Content/Movies/PlayerCard/0501_278_m02_v.usm')
        m=plan(self.project(),lib);self.assertEqual(names('8737832',m)[1],'0501_278_m02')
        self.assertEqual(m['layers'][0]['source'],'native-mini')
    def test_missing_mini_family_uses_only_the_selected_available_large_background(self):
        p=self.project();p['native_card']['native_style']='0500';p['native_card']['native_agent']=301
        p['native_card']['layers'][0]['path']='PesMobile/Content/Movies/PlayerCard/0500_281_f02_v.usm'
        lib=self.library();lib.card_media['movies'].append(p['native_card']['layers'][0]['path'])
        m=plan(p,lib);self.assertEqual(names('8737832',m)[1],'0500_281_f02')
        p['native_card']['layers'][0]['path']='unregistered.usm';self.assertFalse(plan(p,lib)['animated'])
    def test_disabled_animation_keeps_static_background_and_transparent_portrait(self):
        p=self.project();p['appearance']['thumbnail_animation']=False;m=plan(p,self.library())
        self.assertFalse(m['animated']);self.assertEqual(names('8737832',m),['8737832_b','','','8737832_m','',''])
    def test_a_movie_from_another_library_cannot_be_bound(self):
        p=self.project();p['native_card']['layers'][0]['path']='../foreign.usm';p['native_card']['native_style']=''
        self.assertFalse(plan(p,self.library())['animated'])
    def test_switch_is_boolean_and_migrates_old_projects(self):
        p=app.default_project();p['appearance'].pop('thumbnail_animation');self.assertTrue(app.normalize_project(p)['appearance']['thumbnail_animation'])
        p['appearance']['thumbnail_animation']='false'
        with self.assertRaisesRegex(ValueError,'开关'):app.normalize_project(p)


class NativeMiniHookTests(unittest.TestCase):
    def test_native_assignments_preserve_abi_and_leave_foreign_players_untouched(self):
        try:
            from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
            from unicorn import arm64_const as r
        except ImportError:self.skipTest('optional ARM64 emulator')
        hook={'address':0x120000,'original_call':0x130000,'assign':0x140000,'mini_offset':440,'expected_hex':'00'*64}
        native_names=['8737832_b','0501_278_f02','','8737832_m','','0501_m06']
        payload={'hooks':[]};blob=bytearray();_thumbnail_hook(payload,blob,[{'cardId':11,'thumbnail_names':['a']*6},{'cardId':29,'thumbnail_names':native_names}],hook)
        for at,value in payload['absolute_fixups']:struct.pack_into('<Q',blob,at,value)
        for cid in (29,37):
            with self.subTest(card=cid):
                uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);uc.mem_map(0x100000,0x10000);uc.mem_write(0x100000,bytes(blob))
                for address in (0x120000,0x130000,0x140000,0x300000,0x400000):uc.mem_map(address,0x10000)
                registers=[getattr(r,'UC_ARM64_REG_X'+str(i)) for i in range(29)]+[r.UC_ARM64_REG_X29,r.UC_ARM64_REG_X30]
                expected={reg:0x8000+i for i,reg in enumerate(registers)}
                expected[r.UC_ARM64_REG_X19]=0x300000;expected[r.UC_ARM64_REG_X23]=cid
                for reg,val in expected.items():uc.reg_write(reg,val)
                for i in range(8):uc.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(i)),0x123400+i)
                uc.reg_write(r.UC_ARM64_REG_SP,0x408000);uc.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000);calls=[];returned=[]
                def intercept(vm,address,size,user):
                    if address==hook['assign']:
                        dest,src,n=[vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
                        calls.append((dest,bytes(vm.mem_read(src,n)).decode()));back=vm.reg_read(r.UC_ARM64_REG_X30)
                        for reg in registers[:19]:vm.reg_write(reg,0)
                        for i in range(8):vm.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(i)),0)
                        vm.reg_write(r.UC_ARM64_REG_NZCV,0);vm.reg_write(r.UC_ARM64_REG_PC,back)
                    elif address==hook['original_call']:
                        for reg,val in expected.items():
                            if reg not in (r.UC_ARM64_REG_X16,r.UC_ARM64_REG_X30):self.assertEqual(vm.reg_read(reg),val)
                        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X30),hook['address']+4)
                        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x408000);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV),0xa0000000)
                        for i in range(8):self.assertEqual(vm.reg_read(getattr(r,'UC_ARM64_REG_Q'+str(i))),0x123400+i)
                        returned.append(True);vm.emu_stop()
                uc.hook_add(UC_HOOK_CODE,intercept);uc.emu_start(0x100000,0x150000,count=2000)
                self.assertTrue(returned)
                self.assertEqual(calls,[(0x300000+440+i*24,n) for i,n in enumerate(native_names)] if cid==29 else [])

    def test_old_routes_do_not_gain_an_unconfigured_hook(self):
        payload={};blob=bytearray();_thumbnail_hook(payload,blob,[{'cardId':1}],{})
        self.assertEqual(blob,b'');self.assertEqual(payload,{})


if __name__=='__main__':unittest.main()
