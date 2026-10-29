"""Candidate validation against real V17 instructions, not fake effect outputs.

Candidates remain outside production until action/phase coverage is complete.
RNG/context dependencies below are explicit; the native error generator and its
trigonometry, wrapping and speed arithmetic execute unchanged.
"""
from pathlib import Path
import io
import copy
import json
import math
import os
import struct
import sys
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'maintenance'))
APK = Path(os.environ.get('STUDIO_TEST_APK',str(SOURCE.parent.parent/'73efootball安装包及资源/73efootball-V17.apk')))


@unittest.skipUnless(APK.is_file(), 'requires original V17 APK')
class NativeSkillV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import unicorn
            from unicorn import arm64_const
            from elftools.elf.elffile import ELFFile
            from build_skill_effects_v2 import build
        except ImportError as error:
            raise unittest.SkipTest(str(error))
        cls.u, cls.r = unicorn, arm64_const
        with zipfile.ZipFile(APK) as archive:
            cls.engine = archive.read('lib/arm64-v8a/libUE4.so')
        elf = ELFFile(io.BytesIO(cls.engine))
        cls.segments = [(s['p_vaddr'], s['p_offset'], s['p_filesz'], s['p_memsz'])
                        for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        cls.candidate = build(cls.engine)
        cls.hooks = {row['name']: row for row in cls.candidate['hooks']}
        cls.helpers = {row['name']: row for row in cls.candidate['helpers']}

    @staticmethod
    def bits(value):
        return struct.unpack('<I', struct.pack('<f', value))[0]

    def float(self, machine, register):
        return struct.unpack('<f', struct.pack('<I', machine.reg_read(register)))[0]

    def machine(self, stubs):
        u, r = self.u, self.r
        machine = u.Uc(u.UC_ARCH_ARM64, u.UC_MODE_ARM)
        for address, size in ((0x20000000, 0x40000), (0x40000000, 0x10000),
                              (0x41000000, 0x20000)):
            machine.mem_map(address, size)
        machine.reg_write(r.UC_ARM64_REG_SP, 0x40008000)
        machine.reg_write(r.UC_ARM64_REG_TPIDR_EL0, 0x4101f000)

        def missing(vm, access, address, size, value, user):
            page = address & ~4095
            for va, offset, filesz, memsz in self.segments:
                if va <= address < va + memsz:
                    vm.mem_map(page, 4096)
                    lower, upper = max(page, va), min(page + 4096, va + filesz)
                    if upper > lower:
                        vm.mem_write(lower, self.engine[offset + lower - va:offset + upper - va])
                    return True
            raise AssertionError(('unmapped native dependency', hex(address),
                                  hex(vm.reg_read(r.UC_ARM64_REG_PC))))

        def calls(vm, pc, size, user):
            if pc in stubs:
                stubs[pc](vm)
                vm.reg_write(r.UC_ARM64_REG_PC, vm.reg_read(r.UC_ARM64_REG_X30))
        machine.hook_add(u.UC_HOOK_MEM_UNMAPPED, missing)
        machine.hook_add(u.UC_HOOK_CODE, calls)
        machine.mem_map(0x49000000,0x10000)
        machine._studio_state_cursor=0x49000000
        return machine

    def install(self, machine, row):
        machine.mem_write(0x20000000, self.relocate_state(machine,row))

    def relocate_state(self,machine,row):
        body=bytearray.fromhex(row['body_hex'])
        for offset,size in row.get('writable_fixups',[]):
            at=machine._studio_state_cursor;machine._studio_state_cursor+=(size+15)//16*16
            struct.pack_into('<Q',body,offset,at)
        return bytes(body)

    def install_all(self, machine):
        targets = {}
        helpers = {}
        cursor = 0x20000000
        for row in self.candidate.get('bundles', self.candidate['hooks']):
            target = cursor
            body = self.relocate_state(machine,row)
            self.assertLess(target + len(body), 0x2003f000)
            machine.mem_write(target, body)
            cursor += (len(body) + 4095) & ~4095
            for entry in [row] + row.get('extra_entries', []):
                targets[entry['address']] = target + entry.get('entry_offset', 0)
            helpers.update({name:target+offset for name,offset in row.get('helper_entries',{}).items()})
        # Match the real Android loader: code RX, actor state RW, never RWX.
        machine.mem_protect(0x20000000,0x3f000,self.u.UC_PROT_READ|self.u.UC_PROT_EXEC)
        def redirect(vm, pc, size, user):
            if pc in targets:
                vm.reg_write(self.r.UC_ARM64_REG_PC, targets[pc])
        machine.hook_add(self.u.UC_HOOK_CODE, redirect)
        return helpers

    def execute(self, machine, address, stop=0x2003f000):
        machine.reg_write(self.r.UC_ARM64_REG_X30, stop)
        machine.emu_start(address, stop, count=50000)
        self.assertEqual(machine.reg_read(self.r.UC_ARM64_REG_PC), stop)

    def severe(self, patched, flags, yaw, sign, qualified=True):
        r = self.r
        observed = []
        def integer(value):
            return lambda vm: vm.reg_write(r.UC_ARM64_REG_W0, value)
        def draw(label, value):
            def sample(vm):
                observed.append(label)
                vm.reg_write(r.UC_ARM64_REG_W0, value)
            return sample
        stubs = {
            0x6dd5678: draw('sample', 500), 0x6dd564c: draw('sign', sign),
            0x6ddb3a0: lambda vm: vm.reg_write(r.UC_ARM64_REG_X0, 0x41001000),
            0x73628ac: draw('profile-sample', 75),
            0x8c211f0: lambda vm: vm.reg_write(r.UC_ARM64_REG_S0, self.bits(
                math.fmod(self.float(vm, r.UC_ARM64_REG_S0), self.float(vm, r.UC_ARM64_REG_S1)))),
            0x6dcd87c: lambda vm: vm.reg_write(r.UC_ARM64_REG_W0,
                                            int(vm.reg_read(r.UC_ARM64_REG_W1) in flags)),
        }
        vm = self.machine(stubs)
        player, profile, base, output = 0x41000000, 0x41002000, 0x41003000, 0x41004000
        if patched:
            self.populate_world(vm)
            helpers=self.install_all(vm)
            player=0x44000000
            if qualified:
                record=self.stage_kick(vm,helpers,player,state=10)
                self.prepare_kick(vm,helpers,player,record)
        for offset, value in {0: 10, 4: .5, 0x10: 4, 0x14: .5, 0x18: 1,
                              0x20: .1, 0x24: .5, 0x28: 1, 0x38: .2}.items():
            vm.mem_write(profile + offset, struct.pack('<f', value))
        nominal = (yaw, 10., 100.)
        vm.mem_write(base, struct.pack('<3f', *nominal))
        for index, value in enumerate((player, profile, base, output)):
            vm.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), value)
        canaries = {register: 0x12345678 + index for index, register in enumerate(
            [getattr(r, 'UC_ARM64_REG_X' + str(i)) for i in range(19, 29)])}
        for register, value in canaries.items():
            vm.reg_write(register, value)
        vm.reg_write(r.UC_ARM64_REG_D8, 0x123456789abcdef)
        self.execute(vm, 0x6d51bd8)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP), 0x40008000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_D8), 0x123456789abcdef)
        for register, value in canaries.items():
            self.assertEqual(vm.reg_read(register), value)
        return struct.unpack('<3f', vm.mem_read(output, 12)), observed

    def test_sampled_error_scales_signed_angles_and_preserves_rng_and_speed(self):
        for yaw in (0., 1., 180., 359.):
            for sign in (0, 1):
                original, original_rng = self.severe(False, (), yaw, sign)
                actual, actual_rng = self.severe(True, (74,), yaw, sign)
                delta = (original[0] - yaw + 180) % 360 - 180
                adjusted = (actual[0] - yaw + 180) % 360 - 180
                self.assertAlmostEqual(adjusted, delta * .5, delta=.00005)
                self.assertAlmostEqual(actual[1] - 10., (original[1] - 10.) * .5, places=5)
                self.assertEqual(struct.pack('<f', actual[2]), struct.pack('<f', original[2]))
                self.assertEqual(actual_rng, original_rng)

    def test_original_native_request_mapping_and_attribute_selection_prove_shot_kinds(self):
        r = self.r
        vm = self.machine({0x72c3e6c: lambda m: m.reg_write(r.UC_ARM64_REG_X0, 0x41008000)})
        self.execute(vm, 0x6d3c0c0)
        # Execute the original action-to-request conversion, with its actual
        # packed mode byte. The three shot modes are 9, 10 and 11.
        for mode, expected in ((0, 9), (2, 10), (3, 11)):
            vm.mem_write(0x41000186, bytes([mode]))
            vm.reg_write(r.UC_ARM64_REG_X0, 0x41000000)
            vm.reg_write(r.UC_ARM64_REG_W1, 10)
            vm.reg_write(r.UC_ARM64_REG_W2, 0)
            self.execute(vm, 0x6d45fc4)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0), expected)
        # This original selector uses ability 27 (finishing) for state 10;
        # states 8/9 instead select the native ground/lofted pass fields.
        vm.mem_write(0x41001000, struct.pack('<4I', 164, 0, 0, 0))
        for state, kind, expected in ((10, 9, 27), (10, 10, 27), (10, 11, 27),
                                       (8, 8, 29), (9, 1, 28), (9, 4, 29)):
            vm.mem_write(0x41000ad0, bytes([state]))
            vm.mem_write(0x41002a3c, bytes([kind]))
            for index, value in enumerate((0x41000000, 0x41001000, 0, 0x71, 0x14)):
                vm.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), value)
            self.execute(vm, 0x6d4dd70, 0x6dcd844)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W1), expected)

    def test_low_screamer_keeps_native_skill_and_power_guards_for_both_shot_buttons(self):
        r=self.r
        for skill,power,stunning,wanted in ((True,.49,False,True),(True,.49,True,True),
                                           (True,.5,False,False),(False,.2,False,False)):
            vm=self.machine({})
            self.install_all(vm)
            vm.mem_write(0x4100000c,struct.pack('<f',power))
            vm.mem_write(0x41000061,bytes([int(stunning)]))
            vm.reg_write(r.UC_ARM64_REG_X19,0x41000000)
            vm.reg_write(r.UC_ARM64_REG_W0,int(skill))
            self.execute(vm,0x6d627a4,0x6d627cc)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W25)==0,wanted)
        addresses={row['address'] for row in self.candidate['hooks']}
        self.assertFalse(addresses & {0x6d5f640,0x6d58f94,0x6d5a034,0x6f2ca9c})

    def test_error_wrapper_requires_both_ownership_and_action_qualification(self):
        for flags,qualified in (((),True),((71,),True),((74,),False)):
            original, _ = self.severe(False, (), 359., 1)
            actual, _ = self.severe(True, flags, 359., 1,qualified)
            self.assertEqual(actual, original)

    def test_real_running_input_preserves_context_and_never_writes_measured_speed(self):
        r = self.r
        for flag, speed, bonus in ((69, 10., .20), (69, 20., .13),(69,28.,.06),
                                    (70, 10., .12), (70, 25., .12),
                                    (73, 10., .06), (73,20.,.13),(73,28.,.20),(0, 10., 0.)):
            flags = {flag}
            def query(vm):
                vm.reg_write(r.UC_ARM64_REG_W0, int(vm.reg_read(r.UC_ARM64_REG_W1) in flags))
                for index in range(1, 19):
                    vm.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), 0xbad000 + index)
                for index in tuple(range(8)) + tuple(range(16, 32)):
                    vm.reg_write(getattr(r, 'UC_ARM64_REG_Q' + str(index)), 0xbad000 + index)
                vm.reg_write(r.UC_ARM64_REG_NZCV, 0)
            vm = self.machine({0x6dcd87c: query})
            self.install(vm, self.hooks['studio_running_acceleration_input'])
            for index in range(31):
                vm.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), 0x123000 + index)
            for index in range(32):
                vm.reg_write(getattr(r, 'UC_ARM64_REG_Q' + str(index)), 0x456000 + index)
            vm.reg_write(r.UC_ARM64_REG_S0, self.bits(.5))
            vm.reg_write(r.UC_ARM64_REG_NZCV, 0xa0000000)
            vm.mem_write(0x400082b8, struct.pack('<Q', 0x41000000))
            vm.mem_write(0x41000344, struct.pack('<f', speed))
            self.execute(vm, 0x20000000, 0x6f40b94)
            self.assertAlmostEqual(self.float(vm, r.UC_ARM64_REG_S0), .5 + bonus, places=6)
            self.assertEqual(vm.mem_read(0x41000344, 4), struct.pack('<f', speed))
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0), 0x400081e8)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_NZCV), 0xa0000000)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP), 0x40008000)
            for index in tuple(range(1, 16)) + tuple(range(17, 30)):
                self.assertEqual(vm.reg_read(getattr(r, 'UC_ARM64_REG_X' + str(index))), 0x123000 + index)
            for index in range(1, 32):
                self.assertEqual(vm.reg_read(getattr(r, 'UC_ARM64_REG_Q' + str(index))), 0x456000 + index)

    def test_candidate_cannot_be_accidentally_claimed_as_production_ready(self):
        self.assertFalse(self.candidate['production_ready'])
        self.assertEqual(self.candidate['validation']['gameplay_acceptance'],'pending user testing')

    def test_dribbling_acceleration_survives_original_integer_round_trip(self):
        r=self.r
        for flag,speed,bonus in ((69,5.,.20),(69,20.,.13),(70,5.,.12),(73,20.,.13),(73,30.,.20)):
            vm=self.machine({0x6dcd87c:lambda m:m.reg_write(r.UC_ARM64_REG_W0,
                int(m.reg_read(r.UC_ARM64_REG_W1)==flag))})
            self.install_all(vm)
            vm.mem_write(0x400080c8,struct.pack('<Q',0x41000000))
            vm.mem_write(0x41000344,struct.pack('<f',speed))
            vm.reg_write(r.UC_ARM64_REG_S0,self.bits(.75))
            # Execute original fcvtzs/scvtf and then the real config store.
            self.execute(vm,0x6f11ed8,0x6f11ef8)
            actual=struct.unpack('<f',vm.mem_read(0x40008208,4))[0]
            self.assertAlmostEqual(actual,bonus,places=6)
            self.assertEqual(vm.mem_read(0x41000344,4),struct.pack('<f',speed))
        # A high native coefficient is not reduced by the optional ceiling.
        vm.reg_write(r.UC_ARM64_REG_S0,self.bits(1.5))
        self.execute(vm,0x6f11ef4,0x6f11ef8)
        self.assertEqual(struct.unpack('<f',vm.mem_read(0x40008208,4))[0],1.5)

    def test_shared_bundle_is_installed_once_and_all_native_entries_use_its_offsets(self):
        sys.path.insert(0, str(SOURCE))
        from personal_binding import compose
        bundle = self.candidate['bundles'][0]
        payload = {'blob_hex': bytes(8).hex(), 'hooks': [], 'back_fixup': 0}
        result = compose(payload, [], {'sites': {}, 'templates': {}, 'native_hooks': [bundle]})
        body = bytes.fromhex(bundle['body_hex'])
        actual = bytes.fromhex(result['blob_hex'])
        self.assertEqual(actual.count(body), 1)
        self.assertEqual(len(result['hooks']), len(self.candidate['hooks']))
        start = actual.index(body)
        entries = {row['address']: row for row in [bundle] + bundle['extra_entries']}
        for hook in result['hooks']:
            self.assertEqual(hook['offset'], start + entries[hook['address']]['entry_offset'])
            self.assertEqual(hook['expected_hex'], entries[hook['address']]['expected_hex'])

    def test_shared_bundle_installs_through_the_real_native_bridge_loader(self):
        from test_v193_binding import V17BindingTests
        from personal_binding import capture, prepare
        from native_worker_sim import run
        V17BindingTests.original_apk=APK
        V17BindingTests.setUpClass()
        case = V17BindingTests()
        binding = copy.deepcopy(case.binding)
        binding['profile']['native_hooks'] = self.candidate['bundles']
        actual, _ = case.actual_loader(lambda *args: (0x7000000000 + 0x6000000, 'isolated'))
        prepared, _ = prepare(actual, binding)
        report = run(prepared, capture(prepared), self.engine)
        self.assertEqual(report['status'], 'binding_installed', report)
        self.assertEqual(report['patched_hooks'], report['total_hooks'])

    def get_parameter(self, machine, record, index):
        r = self.r
        machine.reg_write(r.UC_ARM64_REG_X0, record)
        machine.reg_write(r.UC_ARM64_REG_W1, index)
        machine.reg_write(r.UC_ARM64_REG_X2, 0x4101e000)
        self.execute(machine, 0x82a84d4)
        return struct.unpack('<I', machine.mem_read(0x4101e000, 4))[0]

    def set_parameter(self, machine, record, index, value):
        r = self.r
        machine.reg_write(r.UC_ARM64_REG_X0, record)
        machine.reg_write(r.UC_ARM64_REG_W1, index)
        machine.reg_write(r.UC_ARM64_REG_W2, value)
        self.execute(machine, 0x82a907c)

    def test_four_independent_disk_markers_preserve_all_147_original_parameters(self):
        r = self.r
        original = self.machine({})
        original.mem_write(0x41000000, bytes(400))
        for index, value in enumerate((0x41001000, 0x41000000, 0)):
            original.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), value)
        self.execute(original, 0x82aa124)
        expected = [self.get_parameter(original, 0x41001000, i) for i in range(147)]
        vm = self.machine({})
        self.install_all(vm)
        for mask in range(16):
            vm.mem_write(0x41000000, (mask << 683).to_bytes(400, 'little'))
            vm.mem_write(0x41001000, bytes([0xa5]) * 512)
            for index, value in enumerate((0x41001000, 0x41000000, 0)):
                vm.reg_write(getattr(r, 'UC_ARM64_REG_X' + str(index)), value)
            self.execute(vm, 0x82aa124)
            actual = [self.get_parameter(vm, 0x41001000, i) for i in range(147)]
            self.assertEqual(actual, expected)
            for index in range(4):
                self.assertEqual(self.get_parameter(vm, 0x41001000, 147 + index), mask >> index & 1)
            self.assertEqual(bytes(vm.mem_read(0x41001038, 32)), bytes([0xa5]) * 32)

    def test_new_disk_bits_and_string_keys_are_unoccupied_in_the_actual_original_apk(self):
        sys.path.insert(0, str(SOURCE))
        from apk_database import read_tables, PREFIX
        from native_tables import PLAYER
        from native_cpk import Cpk
        from native_strings import read, unwrap
        from custom_skills import SOURCE_BIT, COUNT, text_groups
        with zipfile.ZipFile(APK) as archive:
            rows = read_tables(archive)[PLAYER]
            cpk = Cpk(archive.read(PREFIX + 'livedata/dt870_mobile_and.cpk'))
        mask = ((1 << COUNT) - 1) << SOURCE_BIT
        self.assertGreater(len(rows), 46000)
        self.assertFalse(any(int.from_bytes(row, 'little') & mask for row in rows.values()))
        checked = 0
        for name in cpk.files:
            if not name.endswith(('/string/all.str', '/string/all_diff.str')):
                continue
            groups = {g['id']: g for g in read(unwrap(cpk.read(name)))}
            for update in text_groups(name.split('/')[0]):
                if update['id'] not in groups:
                    self.assertNotIn(update['name'], {g['name'] for g in groups.values()})
                    continue
                self.assertEqual(groups[update['id']]['name'], update['name'])
                self.assertFalse(groups[update['id']]['items'].keys() & update['items'].keys())
            checked += 1
        self.assertGreaterEqual(checked, 2)

    def test_new_parameter_setters_keep_other_markers_and_native_parameters(self):
        r = self.r
        vm = self.machine({})
        self.install_all(vm)
        vm.mem_write(0x41001000, bytes([0xa5]) * 56)
        for index in range(4):
            self.assertEqual(self.get_parameter(vm, 0x41001000, 147 + index), 0)
        self.set_parameter(vm, 0x41001000, 147, 1)
        self.set_parameter(vm, 0x41001000, 150, 1)
        before = bytes(vm.mem_read(0x41001000, 52))
        self.set_parameter(vm, 0x41001000, 149, 1)
        self.set_parameter(vm, 0x41001000, 147, 0)
        self.assertEqual(bytes(vm.mem_read(0x41001000, 52)), before)
        self.assertEqual([self.get_parameter(vm, 0x41001000, i) for i in range(147, 151)], [0, 0, 1, 1])
        self.set_parameter(vm, 0x41001000, 18, 80)
        self.assertEqual(self.get_parameter(vm, 0x41001000, 18), 80)
        self.assertEqual([self.get_parameter(vm, 0x41001000, i) for i in range(147, 151)], [0, 0, 1, 1])

    def test_real_147_parameter_owned_override_does_not_erase_native_custom_skills(self):
        r = self.r
        from custom_skills import COMPACT_TAG
        vm = self.machine({})
        self.install_all(vm)
        vm.mem_write(0x41000080, bytes(52) + bytes([0xa5]) * 4)
        vm.mem_write(0x41001000, bytes(52) + struct.pack('<I', COMPACT_TAG | 15))
        vm.reg_write(r.UC_ARM64_REG_X19, 0x41001000)
        vm.reg_write(r.UC_ARM64_REG_X20, 0x41000000)
        self.execute(vm, 0x7a87ff8, 0x7a88030)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W22), 147)
        self.assertEqual([self.get_parameter(vm, 0x41001000, i) for i in range(147, 151)], [1, 1, 1, 1])

    def test_actual_match_table_constructor_transports_four_new_flags_without_overflow(self):
        r = self.r
        vm = self.machine({})
        self.install_all(vm)
        for mask in range(16):
            vm.mem_write(0x41001000, bytes(56))
            for index in range(4):
                self.set_parameter(vm, 0x41001000, 147 + index, mask >> index & 1)
            vm.mem_write(0x41002000, bytes(0xcc))
            vm.mem_write(0x410020cc, bytes([0xa5]) * 32)
            vm.reg_write(r.UC_ARM64_REG_X0, 0)
            vm.reg_write(r.UC_ARM64_REG_X1, 0x41002000)
            vm.reg_write(r.UC_ARM64_REG_X2, 0x41001000)
            self.execute(vm, 0x6a74bec)
            for index in range(79):
                vm.reg_write(r.UC_ARM64_REG_X0, 0x41002000)
                vm.reg_write(r.UC_ARM64_REG_W1, index)
                self.execute(vm, 0x72b39c4)
                self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0), mask >> (index - 75) & 1 if index >= 75 else 0)
            self.assertEqual(bytes(vm.mem_read(0x410020cc, 32)), bytes([0xa5]) * 32)

    def test_native_skill_name_lookup_handles_new_ids_and_keeps_old_ids(self):
        r = self.r
        vm = self.machine({})
        self.install_all(vm)
        from custom_skills import messages
        for row in messages():
            vm.mem_write(0x41000000, struct.pack('<I', row['id']))
            vm.reg_write(r.UC_ARM64_REG_X0, 0x41000000)
            self.execute(vm, 0x82bb658)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0), row['name_msg'])
        original = self.machine({})
        for skill in range(74):
            for machine in (original, vm):
                machine.mem_write(0x41000000, struct.pack('<I', skill))
                machine.reg_write(r.UC_ARM64_REG_X0, 0x41000000)
                self.execute(machine, 0x82bb658)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0), original.reg_read(r.UC_ARM64_REG_W0))

    def test_native_innate_list_excludes_the_same_skills_in_additional_slots(self):
        r=self.r
        from custom_skills import COMPACT_TAG
        def copy_record(m):
            out=m.reg_read(r.UC_ARM64_REG_X8)
            m.mem_write(out,bytes(52)+struct.pack('<I',COMPACT_TAG|15))
        for additional,wanted in (((),[75,76,77,78]),((75,77),[76,78]),
                                  ((75,76,77,78),[])):
            vm=self.machine({0x7a87f44:copy_record})
            self.install_all(vm)
            vm.mem_write(0x41000094,struct.pack('<5I',*(list(additional)+[74]*(5-len(additional)))))
            vm.mem_write(0x41000120,struct.pack('<I',1))
            found=[]
            def strings(m,pc,size,user):
                if pc==0x737a380:
                    found.append(m.reg_read(r.UC_ARM64_REG_W22))
                    m.reg_write(r.UC_ARM64_REG_PC,0x737a310)
            vm.hook_add(self.u.UC_HOOK_CODE,strings)
            for i,value in enumerate((0x41000000,0x41002000,0x41003000)):
                vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
            self.execute(vm,0x737a2b0,0x737a628)
            self.assertEqual(found,wanted)

    def test_native_detail_scan_uses_separate_34_byte_array_without_canary_or_record_damage(self):
        r = self.r
        from custom_skills import COMPACT_TAG
        def record_copy(vm):
            out = vm.reg_read(r.UC_ARM64_REG_X8)
            record = bytearray([0xa5] * 464)
            record[:52] = bytes(52)
            struct.pack_into('<I', record, 52, COMPACT_TAG | 15)
            vm.mem_write(out, bytes(record))
        vm = self.machine({0x7a87f44: record_copy})
        self.install_all(vm)
        vm.mem_write(0x4101f028, struct.pack('<Q', 0x1234abcd5678ef90))
        vm.mem_write(0x410000c0, struct.pack('<QQ', 0x41001000, 0x410010f8))
        vm.reg_write(r.UC_ARM64_REG_X0, 0x41002000)
        vm.reg_write(r.UC_ARM64_REG_X1, 0x41000000)
        self.execute(vm, 0x30e8964, 0x30e8a28)
        frame = vm.reg_read(r.UC_ARM64_REG_X29)
        stack = vm.reg_read(r.UC_ARM64_REG_SP)
        self.assertEqual(bytes(vm.mem_read(frame + 0x80, 34)), bytes(30) + bytes([1] * 4))
        self.assertEqual(struct.unpack('<Q', vm.mem_read(frame - 16, 8))[0], 0x1234abcd5678ef90)
        self.assertEqual(bytes(vm.mem_read(stack + 0x60 + 56, 408)), bytes([0xa5]) * 408)

    def test_library_and_owned_counts_show_all_four_skills_without_empty_id_74(self):
        r=self.r
        from custom_skills import COMPACT_TAG
        for mask in range(16):
            expected=[75+i for i in range(4) if mask>>i&1]
            vm=self.machine({});self.install_all(vm)
            vm.mem_write(0x41001000,bytes(52)+struct.pack('<I',COMPACT_TAG|mask))
            vm.reg_write(r.UC_ARM64_REG_X25,0x41001000);vm.reg_write(r.UC_ARM64_REG_W21,0)
            found=[]
            def capture(m,pc,size,user):
                if pc==0x2f45244:
                    found.append(m.reg_read(r.UC_ARM64_REG_W21));m.reg_write(r.UC_ARM64_REG_PC,0x2f45210)
            vm.hook_add(self.u.UC_HOOK_CODE,capture)
            self.execute(vm,0x2f4521c,0x2f454f4)
            self.assertEqual(found,expected)
            vm.reg_write(r.UC_ARM64_REG_X21,0x41001000)
            vm.reg_write(r.UC_ARM64_REG_W22,0);vm.reg_write(r.UC_ARM64_REG_W27,0)
            self.execute(vm,0x2f44f5c,0x2f44f98)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W27),len(expected))

    def test_relocated_state_lives_outside_rx_code_and_cancellation_can_write_it(self):
        r=self.r
        from personal_binding import compose,relocate_code
        bundle=self.candidate['bundles'][0]
        payload=compose({'blob_hex':bytes(8).hex(),'hooks':[],'offsets':{},'back_fixup':0},[],
                        {'sites':{},'templates':{},'native_hooks':[bundle]})
        raw=bytearray.fromhex(payload['blob_hex']);struct.pack_into('<Q',raw,0,payload['hooks'][0]['address']+4)
        self.assertEqual(payload['writable_data_bytes'],2816)
        # Pure relocation refuses an absent state allocation.
        with self.assertRaisesRegex(ValueError,'尚未分配'):
            relocate_code(payload,bytes(raw),0,0,0)
        code,_=relocate_code(payload,bytes(raw),0x20000000,0,0,0x49000000)
        for at,offset in payload['writable_pointer_fixups']:
            self.assertEqual(struct.unpack_from('<Q',code,at)[0],0x49000000+offset)
        vm=self.machine({});self.populate_world(vm);helpers=self.install_all(vm)
        player=0x44000000;vm.mem_write(player+0x2a38,bytes([9]))
        vm.reg_write(r.UC_ARM64_REG_X0,player);self.execute(vm,helpers['shared_studio_kick_slot'])
        slot=vm.reg_read(r.UC_ARM64_REG_X0);self.assertTrue(0x49000000<=slot<0x49001000)
        vm.mem_write(slot+36,struct.pack('<2I',2,7))
        vm.reg_write(r.UC_ARM64_REG_X0,player);self.execute(vm,helpers['shared_studio_cancel_committed_kick'])
        self.assertEqual(bytes(vm.mem_read(slot+36,8)),bytes(8))

    def world(self, helper, stubs=None):
        """Synthetic live records; all native lookup routines execute for real."""
        vm = self.machine(stubs or {})
        self.populate_world(vm)
        self.install(vm, self.helpers[helper])
        return vm

    def populate_world(self, vm):
        for at, size in ((0x42000000, 0x10000), (0x43000000, 0x10000),
                         (0x44000000, 0x100000), (0x45000000, 0x10000),
                         (0x47000000,0x20000),(0x48000000,0x20000),(0xa58d000, 4096)):
            vm.mem_map(at, size)
        vm.mem_write(0xa58de28, struct.pack('<Q', 0x42000000))
        vm.mem_write(0x420004d0, struct.pack('<Q', 0x43000000))
        vm.mem_write(0x42005b60, struct.pack('<Q', 0x45004000))
        for team in range(2):
            vm.mem_write(0x42003030 + team * 0x50, struct.pack('<Q', 0x45000000 + team * 0x1000))
            vm.mem_write(0x4500028c + team * 0x1000, struct.pack('<b', 1 if team == 0 else -1))
        for pid in range(22):
            actor = 0x44000000 + pid * 0x5000
            # Native live-state and PlayerInfo pointers have distinct layouts.
            vm.mem_write(0x42003170 + pid * 0x50, struct.pack('<Q', 0x48000000+pid*0x1000))
            vm.mem_write(0x42003b20 + pid * 0x50, struct.pack('<Q', 0x47000000+pid*0x1000))
            vm.mem_write(actor + 0x2a38, bytes([pid]))
            self.set_position(vm,pid,1000+pid,0,1000+pid)
            vm.mem_write(0x43004202 + pid, bytes([1]))
        vm.mem_write(0x45004000, struct.pack('<2f', 52.5, 34.))
        vm.mem_write(0x45004018, struct.pack('<2f', 36., 20.15))

    @staticmethod
    def set_position(vm,pid,x,y,z):
        packed=struct.pack('<3f',x,y,z)
        vm.mem_write(0x44000000+pid*0x5000+8,packed)
        vm.mem_write(0x47000000+pid*0x1000+0x4f4,packed)

    def test_nearest_opponent_uses_live_teams_active_mask_and_ground_distance(self):
        r = self.r
        vm = self.world('studio_nearest_live_opponent')
        self_actor = 0x44000000
        teammate, keeper, opponent = (0x44000000 + pid * 0x5000 for pid in (1, 11, 12))
        self.set_position(vm,0,0,300,0)
        self.set_position(vm,1,.01,0,0)
        self.set_position(vm,12,.2,0,0)
        vm.mem_write(0x43004202 + 12, bytes([0]))
        for distance in (1.5, 2., 2.0001):
            self.set_position(vm,11,distance,-300,0)
            vm.reg_write(r.UC_ARM64_REG_X0, self_actor)
            self.execute(vm, 0x20000000)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0), 0x4700b000)
            self.assertAlmostEqual(self.float(vm, r.UC_ARM64_REG_S0), distance * distance, places=5)
        self.set_position(vm,11,float('nan'),0,0)
        for pid in range(13, 22):
            vm.mem_write(0x43004202 + pid, bytes([0]))
        vm.reg_write(r.UC_ARM64_REG_X0, self_actor)
        self.execute(vm, 0x20000000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0), 0)
        self.assertEqual(self.float(vm, r.UC_ARM64_REG_S0), float('inf'))

    def test_opposing_box_uses_current_side_longitudinal_x_and_inclusive_lines(self):
        r = self.r
        vm = self.world('studio_in_opposing_penalty_area')
        for pid in (0, 11):
            actor = 0x44000000 + pid * 0x5000
            team = int(pid >= 11)
            for side in (-1, 1):
                vm.mem_write(0x4500028c + team * 0x1000, struct.pack('<b', side))
                for x, z, expected in ((36., 0., 1), (35.999, 0., 0),
                                       (52.5, 20.15, 1), (52.501, 0., 0),
                                       (40., 20.151, 0), (-40., 0., 0), (0., 40., 0)):
                    vm.mem_write(actor + 8, struct.pack('<3f', x * side, 5., z))
                    vm.reg_write(r.UC_ARM64_REG_X0, actor)
                    self.execute(vm, 0x20000000)
                    self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0), expected, (pid, side, x, z))

    def test_committed_request_classifier_uses_original_subtype_and_air_mode(self):
        r = self.r
        vm = self.machine({})
        self.install(vm, self.helpers['studio_classify_committed_kick_request'])
        for state, subtype, mode, manual, expected, native_kind in (
            (9, 22, 0, 0, 1, 1), (9, 23, 0, 1, 1, 2),
            (9, 0, 0, 0, 0, 1), (9, 18, 0, 1, 0, 2),
            (9, 25, 0, 0, 0, 1), (9, 999, 0, 1, 0, 2),
            (9, 24, 0, 0, 2, 3), (9, 24, 0, 1, 2, 2),
            (9, 24, 3, 0, 3, 4), (9, 22, 3, 0, 4, 4),
            (9, 0, 3, 0, 0, 4),
            (8, 18, 1, 0, 4, 5), (8, 19, 3, 0, 4, 6),
            (8, 21, 3, 0, 0, 8), (8, 18, 0, 0, 0, 7),
            (10, 25, 0, 0, 5, 9), (10, 25, 2, 0, 5, 10),
            (10, 25, 3, 0, 5, 11), (7, 0, 0, 0, 0, 20),
        ):
            vm.mem_write(0x41000000, bytes(64))
            vm.mem_write(0x41000000, struct.pack('<I', state))
            vm.mem_write(0x41000008, struct.pack('<Q', 0x41001000))
            vm.mem_write(0x4100001c, struct.pack('<I', subtype))
            vm.mem_write(0x41001184, struct.pack('<I', (mode << 8) | (manual << 28)))
            vm.mem_write(0x41001186, bytes([mode]))
            vm.reg_write(r.UC_ARM64_REG_X0, 0x41000000)
            self.execute(vm, 0x20000000)
            self.assertEqual((vm.reg_read(r.UC_ARM64_REG_W0), vm.reg_read(r.UC_ARM64_REG_W1)),
                             (expected, native_kind), (state, subtype, mode, manual))

    def test_native_pass_dispatch_and_relative_names_confirm_short_and_through_ids(self):
        r = self.r
        vm = self.machine({})
        output, request = 0x41002000, 0x41003000
        names = {0: (22, 'SHORT_PASS'), 1: (18, 'LONG_PASS'),
                 2: (19, 'CENTERING'), 3: (24, 'THROUGH_PASS')}
        # Execute the original type dispatch, not a reconstructed Python map.
        # Earlier context/flag copying is unrelated to this selected type.
        for primitive, (behavior, name) in names.items():
            for loft in (0, 1):
                vm.mem_write(output, bytes(64))
                vm.mem_write(request, struct.pack('<2I', 7, primitive) + bytes(6) + bytes([loft]))
                vm.reg_write(r.UC_ARM64_REG_X19, output)
                vm.reg_write(r.UC_ARM64_REG_X20, request)
                self.execute(vm, 0x70e7758, 0x70e77cc if primitive == 3 else 0x70e779c)
                self.assertEqual(struct.unpack('<I', vm.mem_read(output + 4, 4))[0], behavior)
                self.assertEqual(struct.unpack('<I', vm.mem_read(output + 0x1c, 4))[0], 7)
                if primitive == 3:
                    self.assertEqual(bytes(vm.mem_read(output + 0x22, 1)), bytes([loft]))
                vm.reg_write(r.UC_ARM64_REG_W0, behavior)
                self.execute(vm, 0x72e2eec)
                pointer = vm.reg_read(r.UC_ARM64_REG_X0)
                for va, offset, filesz, _ in self.segments:
                    if va <= pointer < va + filesz:
                        start = offset + pointer - va
                        self.assertEqual(self.engine[start:].split(b'\0', 1)[0].decode(), name)
                        break
                else:
                    self.fail('native name pointer outside ELF segments')

    def rate_world(self, vm=None, player=0x41000000):
        r = self.r
        if vm is None:
            vm = self.machine({0x67a11f4: lambda m:m.reg_write(r.UC_ARM64_REG_X0,0),
                               0x6894fa8: lambda m:m.reg_write(r.UC_ARM64_REG_X0,0)})
        helpers = self.install_all(vm)
        comp, ctx, tree, node, group, tracks = (
            0x41008000,0x4100a000,0x4100b000,0x4100c000,0x4100d000,0x4100f000)
        for at,value in ((player+0xa88,comp),(comp+0x80,ctx),(ctx+0x10,tree),
                         (tree+0xf8,node),(comp+0x100,group),(group+0x120,tracks),
                         (player+0x4620,0x12345678)):
            vm.mem_write(at,struct.pack('<Q',value))
        vm.mem_write(node+0x48,struct.pack('<I',0))
        vm.mem_write(node+0xc,struct.pack('<I',2))
        vm.mem_write(group+0x114,struct.pack('<I',2))
        vm.mem_write(comp+0x3d0,bytes([2]))
        vm.mem_write(player+0x2a38,bytes([0]))
        vm.mem_write(player+0x2dce,struct.pack('<H',11))
        for index in range(2):
            vm.mem_write(tracks+64*index,bytes([0x30+index])*64)
        return vm,helpers,player,tracks

    def native_rate(self,vm,player,value):
        r = self.r
        vm.reg_write(r.UC_ARM64_REG_X0,player)
        vm.reg_write(r.UC_ARM64_REG_S0,self.bits(value))
        self.execute(vm,0x6ddbf6c)

    def begin_rate(self,vm,helpers,player,base,factor):
        r = self.r
        vm.reg_write(r.UC_ARM64_REG_X0,player)
        vm.reg_write(r.UC_ARM64_REG_S0,self.bits(base))
        vm.reg_write(r.UC_ARM64_REG_S1,self.bits(factor))
        self.execute(vm,helpers['shared_studio_begin_windup'])
        return self.float(vm,r.UC_ARM64_REG_S0)

    def restore_rate(self,vm,helpers,player,reason=0):
        r = self.r
        vm.reg_write(r.UC_ARM64_REG_X0,player)
        vm.reg_write(r.UC_ARM64_REG_W1,reason)
        self.execute(vm,helpers['shared_studio_restore_windup'])
        return vm.reg_read(r.UC_ARM64_REG_W0)

    def test_windup_state_restores_actual_native_tracks_to_original_rate_once(self):
        for base,factor in ((.8,.8),(1.,.8),(1.3,.8),(.97,.88)):
            vm,helpers,player,tracks = self.rate_world()
            self.native_rate(vm,player,base)
            original=bytes(vm.mem_read(tracks,128))
            fast=self.begin_rate(vm,helpers,player,base,factor)
            self.assertAlmostEqual(fast,base/factor,places=6)
            self.native_rate(vm,player,fast)
            self.assertEqual(self.restore_rate(vm,helpers,player),1)
            self.assertEqual(bytes(vm.mem_read(tracks,128)),original)
            self.assertEqual(struct.unpack('<f',vm.mem_read(player+0x4244,4))[0],
                             struct.unpack('<f',struct.pack('<f',base))[0])
            self.assertEqual(self.restore_rate(vm,helpers,player),0)
            self.assertEqual(bytes(vm.mem_read(tracks,128)),original)

    def test_windup_cancellation_and_stale_release_never_overwrite_a_new_native_rate(self):
        vm,helpers,player,tracks=self.rate_world()
        fast=self.begin_rate(vm,helpers,player,1.3,.8)
        self.native_rate(vm,player,fast)
        vm.mem_write(player+0x2dce,struct.pack('<H',12))
        self.assertEqual(self.restore_rate(vm,helpers,player,reason=1),1)
        self.assertAlmostEqual(struct.unpack('<f',vm.mem_read(player+0x4244,4))[0],1.3,places=6)
        fast=self.begin_rate(vm,helpers,player,1.3,.8)
        self.native_rate(vm,player,fast)
        self.native_rate(vm,player,1.7)
        current=bytes(vm.mem_read(tracks,128))
        self.assertEqual(self.restore_rate(vm,helpers,player),0)
        self.assertEqual(bytes(vm.mem_read(tracks,128)),current)

    def test_repeated_windup_start_uses_unmodified_base_rate_and_separate_generation(self):
        r=self.r
        vm,helpers,player,tracks=self.rate_world()
        self.assertEqual(self.begin_rate(vm,helpers,player,1.,.8),1.25)
        self.native_rate(vm,player,1.25)
        self.assertEqual(self.begin_rate(vm,helpers,player,1.,.8),1.25)
        vm.reg_write(r.UC_ARM64_REG_X0,player)
        self.execute(vm,helpers['shared_studio_windup_slot'])
        row=vm.reg_read(r.UC_ARM64_REG_X0)
        self.assertEqual(struct.unpack('<Q',vm.mem_read(row+40,8))[0],2)

    def action_world(self, flags):
        r = self.r
        vm = self.machine({
            0x67a11f4: lambda m:m.reg_write(r.UC_ARM64_REG_X0,0),
            0x6894fa8: lambda m:m.reg_write(r.UC_ARM64_REG_X0,0),
            0x6dcd87c: lambda m:m.reg_write(r.UC_ARM64_REG_W0,
                int(m.reg_read(r.UC_ARM64_REG_W1) in flags)),
        })
        self.populate_world(vm)
        vm, helpers, player, tracks = self.rate_world(vm, player=0x44000000)
        vm.mem_write(player + 8, struct.pack('<3f', 0, 0, 0))
        self.native_rate(vm, player, 1.3)
        return vm, helpers, player, tracks

    def stage_kick(self, vm, helpers, player, state=9, subtype=None, mode=0,
                   final_kind=None, raw_motion=11, power=.6):
        r = self.r
        if subtype is None:
            subtype = {8: 18, 9: 22, 10: 25}.get(state, 0)
        header, packed, spec, record, final = (0x41002000,0x41003000,
                                              0x41004000,0x41005000,0x41006000)
        vm.mem_write(header, bytes(64))
        vm.mem_write(packed, bytes(512))
        vm.mem_write(header, struct.pack('<I', state))
        vm.mem_write(header+8, struct.pack('<Q', packed))
        vm.mem_write(header+0x1c, struct.pack('<I', subtype))
        vm.mem_write(packed+8, struct.pack('<f', power))
        vm.mem_write(packed+0x184, struct.pack('<I', mode << 8))
        vm.mem_write(packed+0x186, bytes([mode]))
        vm.reg_write(r.UC_ARM64_REG_X0, header)
        self.execute(vm, helpers['shared_studio_classify_committed_kick_request'])
        native_kind = vm.reg_read(r.UC_ARM64_REG_W1)
        vm.mem_write(spec, struct.pack('<3I', raw_motion, 0, 0))
        vm.mem_write(final, struct.pack('<2I', state,
            native_kind if final_kind is None else final_kind))
        # XYZ point at the start proves it must not be mistaken for IDs.
        vm.mem_write(record, struct.pack('<3f', 39.25, 0, -12.5))
        vm.mem_write(record+0x24, struct.pack('<f',1.3))
        for i, value in enumerate((player,header,spec,record,final)):
            vm.reg_write(getattr(r, 'UC_ARM64_REG_X'+str(i)),value)
        self.execute(vm, helpers['shared_studio_stage_committed_kick'])
        vm.mem_write(player+0xad0, bytes([state]))
        vm.mem_write(player+0x2dce,struct.pack('<H',raw_motion))
        return record

    def prepare_kick(self, vm, helpers, player, record, anime=2884):
        r = self.r
        # The original selected-motion setup writes this before initialization.
        vm.mem_write(player+0x2dd0, struct.pack('<H', anime))
        vm.reg_write(r.UC_ARM64_REG_X0, player)
        vm.reg_write(r.UC_ARM64_REG_X1, record)
        vm.reg_write(r.UC_ARM64_REG_W2, anime)
        self.execute(vm, helpers['shared_studio_prepare_committed_windup'])
        return self.float(vm, r.UC_ARM64_REG_S0)

    def kick_row(self, vm, helpers, player):
        vm.reg_write(self.r.UC_ARM64_REG_X0,player)
        self.execute(vm,helpers['shared_studio_kick_slot'])
        return vm.reg_read(self.r.UC_ARM64_REG_X0)

    def test_committed_windup_uses_final_request_and_real_short_pass_distance_snapshot(self):
        for distance, expected in ((1.5,1.3/.6),(2.,1.3/.6),(2.0001,1.3)):
            vm,helpers,player,tracks=self.action_world({77})
            self.set_position(vm,11,distance,90,0)
            record=self.stage_kick(vm,helpers,player)
            original=bytes(vm.mem_read(record,48))
            fast=self.prepare_kick(vm,helpers,player,record)
            self.assertAlmostEqual(fast,expected,places=6)
            self.assertEqual(bytes(vm.mem_read(record,48)),original)
            row=self.kick_row(vm,helpers,player)
            qualification=struct.unpack('<I',vm.mem_read(row+40,4))[0]
            self.assertEqual(qualification,int(distance<=2.))
            # Qualification is immutable if the defender subsequently leaves.
            self.set_position(vm,11,5,0,0)
            self.assertEqual(struct.unpack('<I',vm.mem_read(row+40,4))[0],qualification)

    def test_committed_heavy_qualification_uses_native_shot_modes_and_selected_volley_metadata(self):
        r=self.r
        for state,mode,motion,power,wanted in ((10,0,71,.5,True),(10,2,71,.49,False),
                (10,3,71,.9,True),(10,0,73,.2,True),(10,0,74,.2,True),
                (8,0,73,.9,False),(9,0,74,.9,False),(10,0,71,float('nan'),False)):
            vm,helpers,player,tracks=self.action_world({74})
            def metadata(m,pc,size,user):
                if pc==0x72c3e6c:
                    m.reg_write(r.UC_ARM64_REG_X0,0x41008000)
                    m.reg_write(r.UC_ARM64_REG_PC,m.reg_read(r.UC_ARM64_REG_X30))
            handle=vm.hook_add(self.u.UC_HOOK_CODE,metadata)
            self.execute(vm,0x6d3c0c0)
            vm.hook_del(handle)
            record=self.stage_kick(vm,helpers,player,state=state,mode=mode,raw_motion=motion,power=power)
            self.prepare_kick(vm,helpers,player,record)
            yaw,pitch,speed=self.error_factors(vm,helpers,player)
            self.assertAlmostEqual(yaw,.5 if wanted else 1.,places=6)
            self.assertAlmostEqual(pitch,.5 if wanted else 1.,places=6)
            self.assertEqual(speed,1.)

    def native_queued_start(self,rate,flags,subtype=24):
        """Run real start-offset/window arithmetic and the native queue writer.

        Clip metadata is fixed: 60 Hz, contact at .5 s, requested contact after
        30 ticks. Rendering/debug dependencies are outside this isolated test.
        """
        r=self.r
        vm,helpers,player,tracks=self.action_world(flags)
        record=self.stage_kick(vm,helpers,player,state=9,subtype=subtype)
        vm.mem_write(record+0x24,struct.pack('<f',rate))
        vm.mem_write(record+0x18,struct.pack('<h',30))
        vm.mem_write(record+0x2c,struct.pack('<f',0.))
        before=bytes(vm.mem_read(record,48))
        stubs={0x68d83d4:('s',60.),0x6d78934:('w',60),0x6d78a3c:('w',90),
               0x6d3fa00:('w',0),0x6dbe174:('s',.5),
               0x6dbe004:('x',0x41009000),0x6b37be0:('w',0)}
        def calls(m,pc,size,user):
            if pc in stubs:
                kind,value=stubs[pc]
                m.reg_write({'s':r.UC_ARM64_REG_S0,'w':r.UC_ARM64_REG_W0,'x':r.UC_ARM64_REG_X0}[kind],
                            self.bits(value) if kind=='s' else value)
            elif pc in (0x6ddaa4c,0x6bbefe8):pass # unrelated blend duration / logging
            else:return
            m.reg_write(r.UC_ARM64_REG_PC,m.reg_read(r.UC_ARM64_REG_X30))
        vm.hook_add(self.u.UC_HOOK_CODE,calls)
        vm.mem_map(0x99ed000,4096)
        vm.mem_write(0x99ed4e0,struct.pack('<Q',0x41010000))
        for reg,value in ((r.UC_ARM64_REG_X19,record),(r.UC_ARM64_REG_X20,player),
            (r.UC_ARM64_REG_W21,2884),(r.UC_ARM64_REG_X27,0x41009000),
            (r.UC_ARM64_REG_W26,0),(r.UC_ARM64_REG_X29,0x400080c0)):
            vm.reg_write(reg,value)
        self.execute(vm,0x6d3ef68,0x6d3f148)
        offset=struct.unpack('<f',vm.mem_read(player+0x4200,4))[0]
        queued=struct.unpack('<f',vm.mem_read(player+0x4244,4))[0]
        self.assertEqual(bytes(vm.mem_read(record,48)),before)
        # Execute the original consumer loading queued R and updating the two
        # existing native tracks. Track allocation/rendering is not simulated.
        vm.reg_write(r.UC_ARM64_REG_X19,player)
        vm.reg_write(r.UC_ARM64_REG_X20,player+0x41fc)
        self.execute(vm,0x6dc4718,0x6dc4734)
        for track in (tracks,tracks+64):
            self.assertAlmostEqual(struct.unpack('<f',vm.mem_read(track+20,4))[0],queued,places=6)
        return vm,helpers,player,record,tracks,offset,queued

    def test_native_start_offset_queue_consumer_and_release_preserve_the_original_post_contact_rate(self):
        r=self.r
        for rate in (.8,.97,1.,1.3):
            base=self.native_queued_start(rate,set())
            fast=self.native_queued_start(rate,{76})
            vm,helpers,player,record,tracks,offset,queued=fast
            self.assertEqual(struct.pack('<f',offset),struct.pack('<f',base[-2]))
            self.assertAlmostEqual(queued,rate/.6,places=6)
            self.assertAlmostEqual((.5-offset)/queued,((.5-base[-2])/base[-1])*.6,places=6)
            vm.reg_write(r.UC_ARM64_REG_X19,record)
            vm.reg_write(r.UC_ARM64_REG_X21,player)
            self.execute(vm,0x6d42570,0x6d42574)
            for track in (tracks,tracks+64):
                self.assertAlmostEqual(struct.unpack('<f',vm.mem_read(track+20,4))[0],rate,places=6)
                self.assertAlmostEqual(struct.unpack('<f',vm.mem_read(track+24,4))[0],1/rate,places=6)
            self.assertAlmostEqual(struct.unpack('<f',vm.mem_read(player+0x4244,4))[0],rate,places=6)
        # Owning the through-pass skill cannot alter an ordinary short pass.
        actual=self.native_queued_start(.8,{76},subtype=22)
        self.assertAlmostEqual(actual[-1],.8,places=6)
        self.assertAlmostEqual((.5-actual[-2])/actual[-1],.5,places=6)

    def test_through_and_air_windup_take_the_strongest_bonus_and_restore_on_native_release(self):
        for state,subtype,mode,flags,factor in (
            (9,24,0,{76,72},.6),(9,24,3,{76,72},.6),
            (9,24,3,{72},.6),(8,18,1,{72},.6),
            (9,22,0,{76,72},1.),(8,21,3,{76,72},1.),
        ):
            vm,helpers,player,tracks=self.action_world(flags)
            original=bytes(vm.mem_read(tracks,128))
            record=self.stage_kick(vm,helpers,player,state,subtype,mode)
            fast=self.prepare_kick(vm,helpers,player,record)
            self.assertAlmostEqual(fast,1.3/factor,places=6)
            self.native_rate(vm,player,fast)
            vm.reg_write(self.r.UC_ARM64_REG_X21,player)
            vm.reg_write(self.r.UC_ARM64_REG_X19,0x41001000)
            self.execute(vm,0x6d42570,0x6d42574)
            self.assertEqual(bytes(vm.mem_read(tracks,128)),original)

    def test_fallback_stale_motion_or_different_handler_record_never_get_windup_bonus(self):
        for invalid in ('fallback','different_pointer','changed_motion','changed_state','changed_context'):
            vm,helpers,player,tracks=self.action_world({76})
            record=self.stage_kick(vm,helpers,player,subtype=24,
                final_kind=1 if invalid=='fallback' else None)
            if invalid=='different_pointer':
                vm.mem_write(record+64,bytes(vm.mem_read(record,48)))
                record+=64
            if invalid=='changed_motion':vm.mem_write(player+0x2dce,struct.pack('<H',13))
            if invalid=='changed_state':vm.mem_write(player+0xad0,bytes([10]))
            if invalid=='changed_context':vm.mem_write(player+0x4620,struct.pack('<Q',0x87654321))
            self.assertAlmostEqual(self.prepare_kick(vm,helpers,player,record),1.3,places=6)
            row=self.kick_row(vm,helpers,player)
            self.assertEqual(struct.unpack('<I',vm.mem_read(row+36,4))[0],0,invalid)

    def test_actual_new_motion_queue_cancels_owned_windup_before_replacing_the_rate(self):
        vm,helpers,player,tracks=self.action_world({76})
        original=bytes(vm.mem_read(tracks,128))
        record=self.stage_kick(vm,helpers,player,subtype=24)
        fast=self.prepare_kick(vm,helpers,player,record)
        self.native_rate(vm,player,fast)
        vm.reg_write(self.r.UC_ARM64_REG_X0,player)
        self.execute(vm,0x6dccb08,0x6dccb0c)
        self.assertEqual(bytes(vm.mem_read(tracks,128)),original)
        row=self.kick_row(vm,helpers,player)
        self.assertEqual(struct.unpack('<I',vm.mem_read(row+36,4))[0],0)

    def error_factors(self,vm,helpers,player):
        r=self.r
        vm.reg_write(r.UC_ARM64_REG_X0,player)
        self.execute(vm,helpers['shared_studio_committed_error_factors'])
        return tuple(self.float(vm,getattr(r,'UC_ARM64_REG_S'+str(i))) for i in range(3))

    def test_error_policy_separates_components_locks_short_pass_and_rejects_stale_actions(self):
        for state,subtype,mode,flags,distance,expected in (
            (9,24,0,{76},8.,(.6,1.,1.)),
            (9,24,3,{76},8.,(.6,1.,1.)),
            (9,24,3,{72},8.,(.6,.6,.6)),
            (9,24,3,{72,76},8.,(.6,.6,.6)),
            (9,24,0,{72},8.,(1.,1.,1.)),
            (9,22,0,{77},2.,(.6,.6,.6)),
            (9,23,0,{77},2.,(.6,.6,.6)),
            (9,22,0,{77},2.001,(1.,1.,1.)),
            (9,0,0,{77},1.,(1.,1.,1.)),
            (8,18,1,{72},1.,(.6,.6,.6)),
            (8,18,1,set(),1.,(1.,1.,1.)),
            (10,25,0,{74},1.,(.5,.5,1.)),
        ):
            vm,helpers,player,tracks=self.action_world(flags)
            self.set_position(vm,11,distance,0,0)
            record=self.stage_kick(vm,helpers,player,state,subtype,mode)
            self.prepare_kick(vm,helpers,player,record)
            # Short-pass start qualification persists until its release.
            self.set_position(vm,11,10,0,0)
            for actual,wanted in zip(self.error_factors(vm,helpers,player),expected):
                self.assertAlmostEqual(actual,wanted,places=6)
            vm.mem_write(player+0xad0,bytes([7]))
            self.assertEqual(self.error_factors(vm,helpers,player),(1.,1.,1.))
            vm.mem_write(player+0xad0,bytes([state]))
            vm.mem_write(player+0x2dce,struct.pack('<H',14))
            self.assertEqual(self.error_factors(vm,helpers,player),(1.,1.,1.))

    def test_error_bonus_expires_when_animation_identity_changes_even_with_the_same_raw_motion(self):
        for flags, state, subtype in (({76},9,24), ({77},9,22), ({74},10,25)):
            vm,helpers,player,_=self.action_world(flags)
            self.set_position(vm,11,1,0,0)
            record=self.stage_kick(vm,helpers,player,state=state,subtype=subtype)
            self.prepare_kick(vm,helpers,player,record,anime=2884)
            self.assertLess(self.error_factors(vm,helpers,player)[0],1.)
            vm.mem_write(player+0x2dd0,struct.pack('<H',2885))
            self.assertEqual(self.error_factors(vm,helpers,player),(1.,1.,1.))

    def test_cold_finisher_checks_box_and_distance_at_release_and_never_compounds_heavy(self):
        for flags,x,distance,expected in (
            ({75},36.,2.5,.5),({75},35.999,2.5,1.),
            ({75},40.,2.5001,1.),({74,75},40.,2.5,.5),
            ({75},-40.,1.,1.),
        ):
            vm,helpers,player,tracks=self.action_world(flags)
            record=self.stage_kick(vm,helpers,player,state=10)
            self.prepare_kick(vm,helpers,player,record)
            vm.mem_write(player+8,struct.pack('<3f',x,0,0))
            self.set_position(vm,11,x+distance,0,0)
            actual=self.error_factors(vm,helpers,player)
            self.assertAlmostEqual(actual[0],expected,places=6)
            self.assertAlmostEqual(actual[1],expected,places=6)
            self.assertEqual(actual[2],1.)

    def test_native_postprocessor_only_scales_random_increment_and_wraps_the_original_angle(self):
        r=self.r
        for yaw,delta in ((359.,4.),(1.,-4.),(180.,0.)):
            vm,helpers,player,tracks=self.action_world({76})
            record=self.stage_kick(vm,helpers,player,subtype=24)
            self.prepare_kick(vm,helpers,player,record)
            # Native angle-add calls fmod only for the 0/360 wrap.
            def fmod(m):
                m.reg_write(r.UC_ARM64_REG_S0,self.bits(math.fmod(
                    self.float(m,r.UC_ARM64_REG_S0),self.float(m,r.UC_ARM64_REG_S1))))
                m.reg_write(r.UC_ARM64_REG_PC,m.reg_read(r.UC_ARM64_REG_X30))
            vm.hook_add(self.u.UC_HOOK_CODE,lambda m,pc,size,user:
                fmod(m) if pc==0x8c211f0 else None)
            angle=0x41001000
            vm.mem_write(angle,struct.pack('<f',yaw))
            vm.reg_write(r.UC_ARM64_REG_X0,angle)
            vm.reg_write(r.UC_ARM64_REG_X20,player)
            vm.reg_write(r.UC_ARM64_REG_S0,self.bits(delta))
            self.execute(vm,0x6d54ac8,0x6d54acc)
            actual=struct.unpack('<f',vm.mem_read(angle,4))[0]
            self.assertAlmostEqual(actual,(yaw+delta*.6)%360,places=4)

    def normal_error(self,patched,state,subtype,flags,sign,mode=0):
        r=self.r
        draws=[]
        def sample(label,value):
            def action(m):
                draws.append(label)
                m.reg_write(r.UC_ARM64_REG_W0,value)
            return action
        stubs={
            0x6dd5678:sample('integer',500),0x6dd564c:sample('sign',sign),
            0x73628ac:sample('profile',75),
            0x6ddb3a0:lambda m:m.reg_write(r.UC_ARM64_REG_X0,0x41001000),
            0x72c3de0:lambda m:m.reg_write(r.UC_ARM64_REG_X0,0x41001000),
            0x6d3f888:lambda m:m.reg_write(r.UC_ARM64_REG_X0,0x41009000),
            0x6d3d9e4:lambda m:m.reg_write(r.UC_ARM64_REG_X0,0x4100b000),
            0x72d847c:lambda m:m.reg_write(r.UC_ARM64_REG_X0,0x4100c000),
            0x6d43378:lambda m:m.reg_write(r.UC_ARM64_REG_W0,1),
            0x6dcd87c:lambda m:m.reg_write(r.UC_ARM64_REG_W0,
                int(m.reg_read(r.UC_ARM64_REG_W1) in flags)),
            0x8c211f0:lambda m:m.reg_write(r.UC_ARM64_REG_S0,self.bits(math.fmod(
                self.float(m,r.UC_ARM64_REG_S0),self.float(m,r.UC_ARM64_REG_S1)))),
        }
        vm=self.machine(stubs)
        self.populate_world(vm)
        player=0x44000000
        self.set_position(vm,0,40,0,0)
        self.set_position(vm,11,41,0,0)
        if patched:
            helpers=self.install_all(vm)
            record=self.stage_kick(vm,helpers,player,state=state,subtype=subtype,mode=mode)
            self.prepare_kick(vm,helpers,player,record)
        else:vm.mem_write(player+0xad0,bytes([state]))
        vm.mem_write(0x4100c004,struct.pack('<f',1.))
        profile,base,output,spec=0x41002000,0x41003000,0x41004000,0x41007000
        vm.mem_write(profile,bytes(128))
        for offset,value in {0x10:10.,0x14:.5,0x18:1.,0x20:4.,0x24:.5,
                             0x28:1.,0x30:.1,0x34:.5,0x38:1.,0x48:.5}.items():
            vm.mem_write(profile+offset,struct.pack('<f',value))
        vm.mem_write(base,struct.pack('<3f',359.,10.,100.))
        vm.mem_write(spec,struct.pack('<4I',11,0,0,0))
        for i,value in enumerate((player,spec,profile,base,output)):
            vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
        self.execute(vm,0x6d51d80)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x40008000)
        return struct.unpack('<3f',vm.mem_read(output,12)),draws

    def test_normal_native_error_generator_uses_each_skills_components_without_extra_rng(self):
        for state,subtype,flags,factors in (
            (10,0,{74},(.5,.5,1.)),(10,0,{75},(.5,.5,1.)),
            (10,0,{74,75},(.5,.5,1.)),(9,24,{76},(.6,1.,1.)),
            (9,22,{77},(.6,.6,.6)),
        ):
            for sign in (0,1):
                original,rng=self.normal_error(False,state,subtype,flags,sign)
                actual,actual_rng=self.normal_error(True,state,subtype,flags,sign)
                yaw_delta=(original[0]-359.+180.)%360.-180.
                expected=((359.+yaw_delta*factors[0])%360.,
                    10.+(original[1]-10.)*factors[1],100.+(original[2]-100.)*factors[2])
                for value,wanted in zip(actual,expected):self.assertAlmostEqual(value,wanted,places=4)
                self.assertEqual(actual_rng,rng)

    @staticmethod
    def polar_host(vector):
        x,y,z=vector
        return math.degrees(math.atan2(x,z))%360.,math.degrees(math.atan2(y,math.hypot(x,z))),math.sqrt(x*x+y*y+z*z)

    def trajectory(self,patched,velocity,reference,offset,yaw,pitch,ratio,
                   state=10,subtype=0,flags=(74,),caller=0x6d535bc,category=0,mode=0):
        r=self.r
        def fmod(m):
            m.reg_write(r.UC_ARM64_REG_S0,self.bits(math.fmod(
                self.float(m,r.UC_ARM64_REG_S0),self.float(m,r.UC_ARM64_REG_S1))))
            m.reg_write(r.UC_ARM64_REG_PC,m.reg_read(r.UC_ARM64_REG_X30))
        if patched:
            vm,helpers,player,_=self.action_world(set(flags))
            self.set_position(vm,0,40,0,0);self.set_position(vm,11,41,0,0)
            record=self.stage_kick(vm,helpers,player,state=state,subtype=subtype,mode=mode)
            self.prepare_kick(vm,helpers,player,record)
            vm.reg_write(r.UC_ARM64_REG_X19,player)
        else:vm=self.machine({})
        calls=[]
        def trace(m,pc,size,user):
            if pc==0x8c211f0:fmod(m)
            if pc==0x6d4e94c:calls.append(pc)
            if pc in (0x6dd5678,0x6dd564c,0x73628ac):
                raise AssertionError('deterministic trajectory solve replayed RNG')
        vm.hook_add(self.u.UC_HOOK_CODE,trace)
        inputs=(velocity,reference,offset)
        vm.mem_write(0x40008134,struct.pack('<I',category))
        for i,value in enumerate(inputs):vm.mem_write(0x41011000+i*0x100,struct.pack('<3f',*value))
        for i in range(5):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),0x41011000+i*0x100)
        for i,value in enumerate((yaw,pitch,ratio)):
            vm.reg_write(getattr(r,'UC_ARM64_REG_S'+str(i)),self.bits(value))
        self.execute(vm,0x6d4e948,caller)
        for i,value in enumerate(inputs):self.assertEqual(vm.mem_read(0x41011000+i*0x100,12),struct.pack('<3f',*value))
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),0x40008000)
        return bytes(vm.mem_read(0x41011300,12)),bytes(vm.mem_read(0x41011400,12)),len(calls)

    def test_trajectory_errors_are_contracted_against_the_native_zero_error_solve_without_rng_or_spin_changes(self):
        for caller in (0x6d535bc,0x6d53694):
            for sign in (-1,1):
                for state,subtype,flags,factors in (
                    (10,0,{74},(.5,.5,1.)),(10,0,{75},(.5,.5,1.)),
                    (10,0,{74,75},(.5,.5,1.)),(9,24,{76},(.6,1.,1.)),
                    (9,22,{77},(.6,.6,.6)),
                ):
                    velocity,reference=(.1,2.,30.),(.1,0.,30.)
                    error=(.1*sign,.05*sign,0.)
                    before,spin,count=self.trajectory(False,velocity,reference,error,2*sign,sign,1.+.1*sign,caller=caller)
                    baseline,_,_=self.trajectory(False,velocity,reference,(0.,0.,0.),0.,0.,1.,caller=caller)
                    after,actual_spin,count=self.trajectory(True,velocity,reference,error,2*sign,sign,1.+.1*sign,
                        state,subtype,flags,caller)
                    actual=self.polar_host(struct.unpack('<3f',after))
                    native=self.polar_host(struct.unpack('<3f',before))
                    ideal=self.polar_host(struct.unpack('<3f',baseline))
                    delta=(native[0]-ideal[0]+180.)%360.-180.
                    expected=((ideal[0]+delta*factors[0])%360.,
                              ideal[1]+(native[1]-ideal[1])*factors[1],
                              ideal[2]+(native[2]-ideal[2])*factors[2])
                    self.assertAlmostEqual((actual[0]-expected[0]+180.)%360.-180.,0.,delta=.0003)
                    self.assertAlmostEqual(actual[1],expected[1],delta=.0003)
                    self.assertAlmostEqual(actual[2],expected[2],delta=.0001)
                    self.assertEqual(actual_spin,spin)
                    self.assertEqual(count,2)

    def test_trajectory_zero_error_and_unqualified_callers_preserve_original_output_exactly(self):
        v,r=(0.,2.,30.),(0.,0.,30.)
        original,spin,_=self.trajectory(False,v,r,(0.,0.,0.),0.,0.,1.)
        actual,actual_spin,count=self.trajectory(True,v,r,(0.,0.,0.),0.,0.,1.)
        self.assertEqual((actual,actual_spin),(original,spin));self.assertEqual(count,2)
        original,spin,_=self.trajectory(False,v,r,(.1,.05,0.),2.,1.,.9)
        for flags,caller in ((set(),0x6d535bc),({74},0x2003f000)):
            actual,actual_spin,count=self.trajectory(True,v,r,(.1,.05,0.),2.,1.,.9,flags=flags,caller=caller)
            self.assertEqual((actual,actual_spin),(original,spin));self.assertEqual(count,1)
        for category in (3,4):
            actual,actual_spin,count=self.trajectory(True,v,r,(.1,.05,0.),2.,1.,.9,category=category)
            self.assertEqual((actual,actual_spin),(original,spin));self.assertEqual(count,1)

    def shield_world(self,owned=True,holder=0,opponent=11):
        r=self.r
        def data(m):
            pid=m.reg_read(r.UC_ARM64_REG_W1)
            m.reg_write(r.UC_ARM64_REG_X0,0x41008000+pid*64)
        def flags(m):
            pid=(m.reg_read(r.UC_ARM64_REG_X0)-0x41008000)//64
            key=m.reg_read(r.UC_ARM64_REG_W1)
            m.reg_write(r.UC_ARM64_REG_W0,int(owned and pid==holder and key==78))
        def physical(m):
            pid=m.reg_read(r.UC_ARM64_REG_W1)
            self.assertEqual(m.reg_read(r.UC_ARM64_REG_W2),41)
            m.reg_write(r.UC_ARM64_REG_W0,80 if pid==holder else 60)
        vm=self.machine({
            0x72c40b0:data,0x7301ef8:lambda m:None,0x72b39c4:flags,
            0x733cbbc:physical,
            0x68d83cc:lambda m:m.reg_write(r.UC_ARM64_REG_W0,60),
            0x733d574:lambda m:m.reg_write(r.UC_ARM64_REG_W0,holder),
            0x72d551c:lambda m:m.reg_write(r.UC_ARM64_REG_W0,0),
        })
        self.populate_world(vm)
        self.set_position(vm,holder,0,0,0)
        self.set_position(vm,opponent,0,100,-1.5)
        state=0x48000000+holder*0x1000
        info=0x47000000+holder*0x1000
        vm.mem_write(state,bytes([84]))
        vm.mem_write(state+0x38,bytes([11]))
        vm.mem_write(info+0x4ec,struct.pack('<f',0.))
        vm.mem_write(info+0x5ac,struct.pack('<I',opponent))
        vm.mem_write(info+0x601,bytes([1]))
        return vm

    def contact_ratio(self,vm,patched=True,first=0,second=11,caller=0x6ddaca0):
        r=self.r
        if patched:self.install_all(vm)
        vm.reg_write(r.UC_ARM64_REG_X0,0x42000000)
        vm.reg_write(r.UC_ARM64_REG_W1,first)
        vm.reg_write(r.UC_ARM64_REG_W2,second)
        # Execute the original BL from actual settlement or prediction. All
        # local physical values, bonuses and the resulting ratio run native.
        self.execute(vm,caller,caller+4)
        return self.float(vm,r.UC_ARM64_REG_S0)

    def test_shield_resistance_changes_only_the_holders_local_input_in_real_contact_settlement(self):
        for holder,opponent in ((0,11),(11,0)):
            for first,second in ((holder,opponent),(opponent,holder)):
                for variant in (11,12,14,15):
                    def setup():
                        m=self.shield_world(holder=holder,opponent=opponent)
                        m.mem_write(0x48000038+holder*0x1000,bytes([variant]))
                        return m
                    original=self.contact_ratio(setup(),False,first,second)
                    vm=setup()
                    before=bytes(vm.mem_read(0x48000000,0x16000))
                    info=bytes(vm.mem_read(0x47000000,0x16000))
                    actual=self.contact_ratio(vm,True,first,second)
                    self.assertAlmostEqual(original,.4 if first==holder else .6,places=6)
                    self.assertAlmostEqual(actual,60/195 if first==holder else 135/195,places=6)
                    self.assertEqual(bytes(vm.mem_read(0x48000000,0x16000)),before)
                    self.assertEqual(bytes(vm.mem_read(0x47000000,0x16000)),info)

    def test_original_contact_relation_uses_body_heading_and_the_actual_counterpart(self):
        r=self.r
        for x,z,heading,wanted in ((0,1,0,0),(1,0,0,1),(0,-1,0,2),
                                    (0,1,180,2),(0,-1,180,0)):
            def pointer(value):return lambda m:m.reg_write(r.UC_ARM64_REG_X0,value)
            vm=self.machine({0x72c3ddc:pointer(0x41001000),0x6ad3af8:pointer(0x41002000),
                0x6a78b48:pointer(0x41003000),0x72c3e80:pointer(0x41004000),
                0x697b60c:lambda m:m.reg_write(r.UC_ARM64_REG_W0,1),
                0x8c211f0:lambda m:m.reg_write(r.UC_ARM64_REG_S0,self.bits(math.fmod(
                    self.float(m,r.UC_ARM64_REG_S0),self.float(m,r.UC_ARM64_REG_S1))))})
            self.populate_world(vm)
            vm.mem_write(0x41003000,struct.pack('<I',11))
            vm.mem_write(0x470004ec,struct.pack('<f',heading))
            self.set_position(vm,0,0,0,0)
            self.set_position(vm,11,x,0,z)
            vm.reg_write(r.UC_ARM64_REG_X0,0x42000000)
            vm.reg_write(r.UC_ARM64_REG_W1,0)
            self.execute(vm,0x6ed9cd8)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0),wanted)

    def test_shield_ignores_predictions_front_side_far_inactive_and_uncommitted_contacts(self):
        for case in ('no-skill','front','side','far','inactive','wrong-opponent',
                     'no-contact','ordinary-dribble','unconfirmed-variant','not-holder','teammate'):
            def setup():
                vm=self.shield_world(owned=case!='no-skill')
                if case=='front':self.set_position(vm,11,0,0,1)
                if case=='side':self.set_position(vm,11,1,0,0)
                if case=='far':self.set_position(vm,11,0,0,-1.8001)
                if case=='inactive':vm.mem_write(0x4300420d,bytes([0]))
                if case=='wrong-opponent':vm.mem_write(0x470005ac,struct.pack('<I',12))
                if case=='no-contact':vm.mem_write(0x47000601,bytes([0]))
                if case=='ordinary-dribble':vm.mem_write(0x48000000,bytes([5]))
                if case=='unconfirmed-variant':vm.mem_write(0x48000038,bytes([13]))
                return vm
            first,second=(1,11) if case=='not-holder' else (0,1) if case=='teammate' else (0,11)
            original=self.contact_ratio(setup(),False,first,second)
            actual=self.contact_ratio(setup(),True,first,second)
            self.assertEqual(struct.pack('<f',actual),struct.pack('<f',original),case)
        for caller in (0x700c724,0x700e724):
            original=self.contact_ratio(self.shield_world(),False,caller=caller)
            actual=self.contact_ratio(self.shield_world(),True,caller=caller)
            self.assertEqual(struct.pack('<f',actual),struct.pack('<f',original))


    def test_stronger_acceleration_profiles_are_continuous_monotonic_and_bounded(self):
        r=self.r;speeds=(0.,11.999,12.,12.001,16.,19.999,20.,20.001,24.,27.999,28.,28.001,40.)
        curves={}
        for flag in (69,70,73):
            vm=self.machine({0x6dcd87c:lambda m:m.reg_write(r.UC_ARM64_REG_W0,int(m.reg_read(r.UC_ARM64_REG_W1)==flag))})
            self.install(vm,self.hooks['studio_running_acceleration_input'])
            vm.mem_write(0x400082b8,struct.pack('<Q',0x41000000));samples=[]
            for speed in speeds:
                vm.mem_write(0x41000344,struct.pack('<f',speed));vm.reg_write(r.UC_ARM64_REG_S0,self.bits(.5))
                self.execute(vm,0x20000000,0x6f40b94)
                samples.append(self.float(vm,r.UC_ARM64_REG_S0)-.5)
            self.assertTrue(all(.05999<=value<=.20001 for value in samples))
            if flag==69:self.assertTrue(all(a>=b-1e-6 for a,b in zip(samples,samples[1:])))
            if flag==73:self.assertTrue(all(a<=b+1e-6 for a,b in zip(samples,samples[1:])))
            if flag==70:self.assertTrue(all(abs(value-.12)<1e-6 for value in samples))
            self.assertLess(abs(samples[5]-samples[7]),.0001)
            self.assertAlmostEqual(samples[0],.20 if flag==69 else .12 if flag==70 else .06,places=6)
            self.assertAlmostEqual(samples[-1],.06 if flag==69 else .12 if flag==70 else .20,places=6)
            vm.reg_write(r.UC_ARM64_REG_S0,self.bits(1.15));self.execute(vm,0x20000000,0x6f40b94)
            self.assertAlmostEqual(self.float(vm,r.UC_ARM64_REG_S0),1.2,places=6)
            curves[flag]=samples
        self.assertGreater(curves[69][0],curves[73][0]);self.assertLess(curves[69][-1],curves[73][-1])

    def test_long_pass_precision_covers_air_modes_and_lofted_through_without_double_scaling(self):
        for state,subtype,mode,flags in ((8,18,1,{72}),(8,18,2,{72}),
                                       (9,24,3,{72}),(9,24,3,{72,76})):
            for sign in (0,1):
                with self.subTest(state=state,subtype=subtype,mode=mode,flags=flags,sign=sign):
                    original,rng=self.normal_error(False,state,subtype,flags,sign,mode)
                    actual,draws=self.normal_error(True,state,subtype,flags,sign,mode)
                    expected=((359.+((original[0]-359.+180.)%360.-180.)*.6)%360.,
                              10.+(original[1]-10.)*.6,100.+(original[2]-100.)*.6)
                    for value,wanted in zip(actual,expected):self.assertAlmostEqual(value,wanted,places=4)
                    self.assertEqual(draws,rng)

    def test_long_pass_trajectory_contracts_all_random_components_and_preserves_spin(self):
        for state,subtype,mode,flags in ((8,18,1,{72}),(9,24,3,{72}),(9,24,3,{72,76})):
            for caller in (0x6d535bc,0x6d53694):
                velocity,reference=(.1,2.,30.),(.1,0.,30.);error=(.1,.05,0.)
                before,spin,_=self.trajectory(False,velocity,reference,error,2.,1.,1.1,caller=caller)
                baseline,_,_=self.trajectory(False,velocity,reference,(0.,0.,0.),0.,0.,1.,caller=caller)
                after,actual_spin,_=self.trajectory(True,velocity,reference,error,2.,1.,1.1,
                    state=state,subtype=subtype,flags=flags,caller=caller,mode=mode)
                native=self.polar_host(struct.unpack('<3f',before));ideal=self.polar_host(struct.unpack('<3f',baseline))
                actual=self.polar_host(struct.unpack('<3f',after));delta=(native[0]-ideal[0]+180.)%360.-180.
                expected=((ideal[0]+delta*.6)%360.,ideal[1]+(native[1]-ideal[1])*.6,ideal[2]+(native[2]-ideal[2])*.6)
                self.assertAlmostEqual((actual[0]-expected[0]+180.)%360.-180.,0.,delta=.0003)
                self.assertAlmostEqual(actual[1],expected[1],delta=.0003)
                self.assertAlmostEqual(actual[2],expected[2],delta=.0001)
                self.assertEqual(actual_spin,spin)

    def test_shield_new_distance_boundary_is_inclusive_and_keeps_facing_requirement(self):
        for distance,enabled in ((1.5,True),(1.8,True),(1.8001,False)):
            vm=self.shield_world();self.set_position(vm,11,0,0,-distance)
            actual=self.contact_ratio(vm,True)
            self.assertAlmostEqual(actual,60/195 if enabled else .4,places=6)


if __name__ == '__main__':
    unittest.main()
