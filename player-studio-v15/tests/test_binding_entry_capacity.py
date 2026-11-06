"""Keep full current hooks in the fixed 4 KiB native-bridge entry page."""
import copy,json,struct,unittest
from pathlib import Path
from personal_binding import compose,relocate_code,_split_code
from native_binding_source import read_installer

R=Path(__file__).resolve().parents[2];C=R/'player-studio-v15'
SOURCE=R/'.work/integrated-2.5-promotion-coach-recycle-20261105/source-game.apk'

class BindingEntryCapacityTests(unittest.TestCase):
    def test_full_export_profile_fits_without_moving_or_editing_original_prefix(self):
        import zipfile
        with zipfile.ZipFile(SOURCE)as z:d=json.loads(z.read('assets/gateway-release/custom-resources/personal-player-studio/players.json'))
        original,_=read_installer(SOURCE);profile=copy.deepcopy(d['native_binding']['profile'])
        home=json.loads((C/'resources/tournament_schedule_ui/native-home.json').read_text('utf8'))
        for i,h in enumerate(profile['native_hooks']):
            if h['name']==home['name']:profile['native_hooks'][i]=home
        result=compose(original,d['native_binding']['routes'],profile)
        prefix=result['root_prefix_bytes'];root=bytes.fromhex(result['blob_hex'])
        self.assertEqual(prefix,2400);self.assertLessEqual(len(root),4096)
        self.assertEqual(root[:prefix],bytes.fromhex(original['blob_hex'])[:prefix])
        self.assertEqual(len(result['inlined_leaf_hooks']),3)
        self.assertEqual(len({h['offset']for h in result['inlined_leaf_hooks']}),1)
        targets={h['name']for h in result['hooks']}
        self.assertIn('tournament_own_team_identity',targets)
        # Relocate to a deliberately far extension, the native-bridge case.
        prefix_address,extension_address=0x10000000,0x7000000000
        root_copy,ext=relocate_code(result,root,prefix_address,extension_address,0x7100000000,0x7200000000)
        from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
        import unicorn.arm64_const as K
        for row in result['inlined_leaf_hooks']:
            u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(prefix_address,4096)
            u.mem_write(prefix_address,root_copy);u.mem_map(0x20000000,4096)
            u.reg_write(K.UC_ARM64_REG_X0,12345);u.reg_write(K.UC_ARM64_REG_X16,67890)
            u.reg_write(K.UC_ARM64_REG_X30,0x20000000);u.reg_write(K.UC_ARM64_REG_NZCV,0xa0000000)
            u.emu_start(prefix_address+row['offset'],0x20000000,count=10)
            self.assertEqual(u.reg_read(K.UC_ARM64_REG_X0),0)
            self.assertEqual(u.reg_read(K.UC_ARM64_REG_X16),67890)
            self.assertEqual(u.reg_read(K.UC_ARM64_REG_NZCV),0xa0000000)
        self.assertGreater(len(ext),4096)
        self.assertTrue(result['compact_dispatch_hooks'])
        # Execute every actual compact entry against near and deliberately
        # far code allocations. Check the full register/stack/flags ABI at
        # handoff, rather than merely counting emitted bytes.
        for base in(0x20000000,0x7000000000):
            root_copy,extension=relocate_code(result,root,prefix_address,base,0x7100000000,0x7200000000)
            vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM);vm.mem_map(prefix_address,4096);vm.mem_write(prefix_address,root_copy)
            vm.mem_map(base,(len(extension)+4095)//4096*4096);vm.mem_write(base,extension)
            vm.mem_map(0x30000000,8192)
            registers=[getattr(K,'UC_ARM64_REG_X'+str(i))for i in range(31)]
            for entry in result['compact_dispatch_hooks']:
                expected={reg:0x123400000000+i*0x10001 for i,reg in enumerate(registers)}
                for reg,value in expected.items():vm.reg_write(reg,value)
                vm.reg_write(K.UC_ARM64_REG_SP,0x30001000);vm.reg_write(K.UC_ARM64_REG_NZCV,0xa0000000)
                vm.mem_write(0x30000fe0,b'guard0123456789abcdef0123456789XY')
                target=base+entry['extension_offset']
                vm.emu_start(prefix_address+entry['offset'],target,count=20)
                self.assertEqual(vm.reg_read(K.UC_ARM64_REG_PC),target,entry['name'])
                for reg,value in expected.items():
                    self.assertEqual(vm.reg_read(reg),target if reg==K.UC_ARM64_REG_X16 else value,entry['name'])
                self.assertEqual(vm.reg_read(K.UC_ARM64_REG_SP),0x30001000)
                self.assertEqual(vm.reg_read(K.UC_ARM64_REG_NZCV),0xa0000000)
                self.assertEqual(bytes(vm.mem_read(0x30000fe0,16)),b'guard0123456789abcdef0123456789XY'[:16])

    def test_shared_constant_returns_keep_distinct_true_and_false_results(self):
        zero=bytes.fromhex('00008052c0035fd6');one=bytes.fromhex('20008052c0035fd6')
        prefix=bytes(range(16))
        payload={'blob_hex':(prefix+zero+zero+one+bytes(8)).hex(),
                 'hooks':[{'name':'false_a','offset':16},{'name':'false_b','offset':24},{'name':'true','offset':32}],
                 'route_pointer_fixup':40}
        _split_code(payload,16,[],[])
        root=bytes.fromhex(payload['blob_hex']);rows=payload['inlined_leaf_hooks']
        self.assertEqual(root[:16],prefix);self.assertEqual(len(root),32)
        self.assertEqual(rows[0]['offset'],rows[1]['offset']);self.assertNotEqual(rows[0]['offset'],rows[2]['offset'])
        from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
        import unicorn.arm64_const as K
        for row,expected in zip(rows,(0,0,1)):
            vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM);vm.mem_map(0x10000000,4096);vm.mem_write(0x10000000,root)
            vm.mem_map(0x20000000,4096);vm.reg_write(K.UC_ARM64_REG_X30,0x20000000)
            vm.reg_write(K.UC_ARM64_REG_X0,999);vm.reg_write(K.UC_ARM64_REG_X16,67890)
            vm.reg_write(K.UC_ARM64_REG_NZCV,0xa0000000)
            vm.emu_start(0x10000000+row['offset'],0x20000000,count=10)
            self.assertEqual(vm.reg_read(K.UC_ARM64_REG_X0),expected)
            self.assertEqual(vm.reg_read(K.UC_ARM64_REG_X16),67890)
            self.assertEqual(vm.reg_read(K.UC_ARM64_REG_NZCV),0xa0000000)

if __name__=='__main__':unittest.main()
