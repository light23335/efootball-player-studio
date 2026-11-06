"""Execute both native UI counters, including their original seven-style reads."""
import copy,io,struct,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'maintenance'))
from ai_playing_styles import FIELDS
from native_ai_style_ui import BUNDLES,hooks
from build_ai_style_ui import build
import test_skill_effects_v2 as fixtures

@unittest.skipUnless(fixtures.APK.is_file(),'requires original V17 APK')
class AIStyleDisplayTests(unittest.TestCase):
    machine=fixtures.NativeSkillV2Tests.machine
    install_all=fixtures.NativeSkillV2Tests.install_all
    relocate_state=fixtures.NativeSkillV2Tests.relocate_state
    execute=fixtures.NativeSkillV2Tests.execute
    @classmethod
    def setUpClass(cls):
        fixtures.NativeSkillV2Tests.setUpClass.__func__(cls)
        cls.old_candidate=copy.deepcopy(cls.candidate)
        cls.candidate['bundles']+=hooks(io.BytesIO(cls.engine))
    def vm_for_counter(self,extended=True):
        def db(vm):vm.reg_write(self.r.UC_ARM64_REG_X0,0x41004000)
        def common(vm):vm.reg_write(self.r.UC_ARM64_REG_X0,0x41001000)
        def copy_common(vm):
            out=vm.reg_read(self.r.UC_ARM64_REG_X8)
            vm.mem_write(out,bytes(vm.mem_read(0x41001000,0x1d0)))
        vm=self.machine({0x82468d4:db,0x823c8d4:common,0x7a87f44:copy_common})
        if extended:self.install_all(vm)
        else:
            current=self.candidate
            try:self.candidate=self.old_candidate;self.install_all(vm)
            finally:self.candidate=current
        return vm
    def decode(self,vm,mask,wolf):
        value=(wolf<<687)
        for index,field in enumerate(FIELDS.values()):value|=((mask>>index)&1)<<field['bit']
        vm.mem_write(0x41000000,value.to_bytes(400,'little'));vm.mem_write(0x41001000,bytes(512))
        for n,v in enumerate((0x41001000,0x41000000,0)):vm.reg_write(getattr(self.r,'UC_ARM64_REG_X'+str(n)),v)
        self.execute(vm,0x82aa124)
    def count(self,vm,address):
        vm.reg_write(self.r.UC_ARM64_REG_X0,0x41003000);self.execute(vm,address)
        return vm.reg_read(self.r.UC_ARM64_REG_W0)
    def test_count_bundle_matches_the_audited_original_and_maintenance_builder(self):
        self.assertEqual(BUNDLES,build(self.engine))
        engine=bytearray(self.engine);engine[BUNDLES[0]['file_offset']]^=1
        with self.assertRaisesRegex(ValueError,'显示接口'):hooks(io.BytesIO(engine))
    def test_previous_ui_counter_reproduces_salah_four_visible_styles_instead_of_five(self):
        for extended,expected in [(False,4),(True,5)]:
            vm=self.vm_for_counter(extended);self.decode(vm,0b0001111,1)
            self.assertEqual(self.count(vm,0x2f3ded4),expected)
            self.assertEqual(self.count(vm,0x737b73c),expected)
    def test_all_native_style_combinations_plus_lone_wolf_have_matching_display_counts(self):
        vm=self.vm_for_counter()
        for mask in range(128):
            for wolf in (0,1):
                self.decode(vm,mask,wolf)
                for address in (0x2f3ded4,0x737b73c):
                    self.assertEqual(self.count(vm,address),mask.bit_count()+wolf,(mask,wolf,hex(address)))
    def test_untagged_padding_never_adds_a_style(self):
        vm=self.vm_for_counter();self.decode(vm,0,0)
        for garbage in (0xffffffff,0x80,0x53534a90):
            vm.mem_write(0x41001034,struct.pack('<I',garbage))
            for address in (0x2f3ded4,0x737b73c):self.assertEqual(self.count(vm,address),0)

    def list_machine(self):
        """Run the real vector construction, index conversion and name getter.

        Only external DB storage, text lookup and libc memcpy/strlen are stubs.
        Both native list loops and native getter/compact copies execute.
        """
        r=self.r
        def db(vm):vm.reg_write(r.UC_ARM64_REG_X0,0x41004000)
        def common(vm):vm.reg_write(r.UC_ARM64_REG_X0,0x41001000)
        def memcpy(vm):
            dst=vm.reg_read(r.UC_ARM64_REG_X0);src=vm.reg_read(r.UC_ARM64_REG_X1)
            size=vm.reg_read(r.UC_ARM64_REG_X2)
            vm.mem_write(dst,bytes(vm.mem_read(src,size)))
        def strlen(vm):
            src=vm.reg_read(r.UC_ARM64_REG_X0)
            vm.reg_write(r.UC_ARM64_REG_X0,bytes(vm.mem_read(src,100)).index(0))
        def text(vm):
            message=vm.reg_read(r.UC_ARM64_REG_W1)
            self.messages.append(message)
            label=('Lone Wolf' if message==(352<<16)|60010 else f'native {message}').encode()
            self.assertLess(len(label),23)
            dst=vm.reg_read(r.UC_ARM64_REG_X0)
            vm.mem_write(dst,bytes([len(label)*2])+label+b'\0'+bytes(22-len(label)))
        vm=self.machine({0x82468d4:db,0x823c8d4:common,0x8c1bc70:memcpy,
                         0x8c1bc60:memcpy,0x8c1bca0:strlen,0x2f47358:text})
        self.install_all(vm)
        return vm

    def list_styles(self,vm,owned):
        self.messages=[]
        for vector,base,width in ((0x41006000,0x41007000,24),(0x41006020,0x41008000,4)):
            vm.mem_write(vector,struct.pack('<3Q',base,base,base+8*width))
        # The real owned common-copy function can run with no owned overrides.
        vm.mem_write(0x41003030,struct.pack('<2Q',0,7511))
        vm.mem_write(0x410030b0,bytes(56))
        for reg,value in ((self.r.UC_ARM64_REG_X0,0x41003000 if owned else 7511),
                          (self.r.UC_ARM64_REG_X1,0x41006000),
                          (self.r.UC_ARM64_REG_X2,0x41006020)):
            vm.reg_write(reg,value)
        self.execute(vm,0x7379c20 if owned else 0x2f3e600)
        begin,end=struct.unpack('<2Q',vm.mem_read(0x41006000,16))
        labels=[]
        for at in range(begin,end,24):
            raw=bytes(vm.mem_read(at,24));self.assertFalse(raw[0]&1)
            labels.append(raw[1:1+(raw[0]>>1)].decode())
        return labels,list(self.messages)

    def test_full_native_library_and_owned_lists_include_lone_wolf(self):
        vm=self.list_machine()
        for mask in (0,15,127):
            for wolf in (0,1):
                self.decode(vm,mask,wolf)
                for owned in (False,True):
                    labels,messages=self.list_styles(vm,owned)
                    self.assertEqual(len(labels),mask.bit_count()+wolf,(mask,wolf,owned))
                    self.assertEqual(labels.count('Lone Wolf'),wolf,(mask,wolf,owned))
                    self.assertEqual(messages.count((352<<16)|60010),wolf)

if __name__=='__main__':unittest.main()
