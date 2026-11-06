"""Execute the original UE FMatchEnv -> native environment bridge.

The decoded JSON-to-FMatchEnv step is a fixture. Both native conversion
functions and 7a5b7c4 execute from the original ELF without replacement.
This verifies the environment consumer, not a complete played match.
"""
import io,struct,unittest,zipfile
import test_skill_effects_v2 as native

@unittest.skipUnless(native.APK.is_file(),'requires original V17 APK')
class NativeTournamentEnvironmentBridgeTests(unittest.TestCase):
    machine=native.NativeSkillV2Tests.machine
    @classmethod
    def setUpClass(cls):
        import unicorn
        from unicorn import arm64_const
        from elftools.elf.elffile import ELFFile
        cls.u,cls.r=unicorn,arm64_const
        with zipfile.ZipFile(native.APK)as z:cls.engine=z.read('lib/arm64-v8a/libUE4.so')
        elf=ELFFile(io.BytesIO(cls.engine))
        cls.segments=[(s['p_vaddr'],s['p_offset'],s['p_filesz'],s['p_memsz'])for s in elf.iter_segments()if s['p_type']=='PT_LOAD']
    def bridge(self,extra,pk,minutes=0):
        vm=self.machine({});r=self.r;destination=0x41001000;source=0x41002000;stop=0x2003f000
        data=bytearray(0x24);data[1:4]=bytes([2,3,4]);data[0x10:0x12]=bytes([bool(extra),bool(pk)])
        struct.pack_into('<I',data,4,minutes)
        vm.mem_write(source,bytes(data));vm.mem_write(destination,b'\xa5'*0x40)
        for n in range(19,30):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),0x12345000+n)
        saved=[vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(n)))for n in range(19,30)]
        sp=vm.reg_read(r.UC_ARM64_REG_SP)
        vm.reg_write(r.UC_ARM64_REG_X0,destination);vm.reg_write(r.UC_ARM64_REG_X1,source);vm.reg_write(r.UC_ARM64_REG_X30,stop)
        vm.emu_start(0x33a0340,stop,count=10000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop);self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),sp)
        self.assertEqual(saved,[vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(n)))for n in range(19,30)])
        self.assertEqual(bytes(vm.mem_read(source,len(data))),bytes(data))
        return bytes(vm.mem_read(destination,0x40))
    def test_all_extra_time_and_penalty_flags_reach_native_environment(self):
        base=self.bridge(False,False)
        for extra,pk in ((False,False),(False,True),(True,False),(True,True)):
            with self.subTest(extra=extra,pk=pk):
                result=self.bridge(extra,pk)
                self.assertEqual(tuple(result[0x20:0x22]),(int(extra),int(pk)))
                self.assertEqual(result[:0x20],base[:0x20]);self.assertEqual(result[0x22:],base[0x22:])
    def test_original_reset_clears_both_environment_flags(self):
        vm=self.machine({});r=self.r;target=0x41001000;root=0x41003000;state=0x41010000;stop=0x2003f000
        # The reset reads only stadium-dependent defaults from the singleton.
        def singleton(uc):uc.reg_write(r.UC_ARM64_REG_X0,root)
        vm.hook_add(self.u.UC_HOOK_CODE,lambda uc,at,size,_:(singleton(uc),uc.reg_write(r.UC_ARM64_REG_PC,uc.reg_read(r.UC_ARM64_REG_X30)))if at==0x82468d4 else None)
        vm.mem_write(root+0x48,struct.pack('<Q',state))
        # Its default source is far beyond the small fixture; use an explicit
        # mapped store while retaining the original reset instructions.
        vm.mem_map(0x41100000,0x100000)
        vm.mem_write(root+0x48,struct.pack('<Q',0x41100000))
        vm.mem_write(target,b'\x01'*0x40);vm.reg_write(r.UC_ARM64_REG_X0,target);vm.reg_write(r.UC_ARM64_REG_X30,stop)
        vm.emu_start(0x7a5b81c,stop,count=10000)
        self.assertEqual(bytes(vm.mem_read(target+0x20,2)),b'\0\0')

    def test_every_configurable_duration_reaches_native_minutes_without_changing_rules(self):
        # FMatchEnv +4 is a minute count, not a menu index. The original
        # bridge and native constructor copy it to destination +0x18.
        baseline=self.bridge(True,True,0)
        for minutes in range(3,31):
            with self.subTest(minutes=minutes):
                result=self.bridge(True,True,minutes)
                self.assertEqual(struct.unpack_from('<I',result,0x18)[0],minutes)
                self.assertEqual(result[:0x18],baseline[:0x18])
                self.assertEqual(result[0x1c:],baseline[0x1c:])
                self.assertEqual(tuple(result[0x20:0x22]),(1,1))

if __name__=='__main__':unittest.main()
