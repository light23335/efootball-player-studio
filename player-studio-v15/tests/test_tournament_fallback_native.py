"""Production AArch64 fallback gates in isolated Unicorn; no running game.

Reuse the verified queue/plan VM. The native metadata aptitude getter result
is an explicit fixture; production scope, command validation, role/grids,
queue checks and mutations execute their real compiled instructions.
"""
import hashlib
import json
import os
from pathlib import Path
import unittest
import zipfile

import test_tournament_difficulty_native as native
import test_native_coach_takeover as takeover


SOURCE = Path(__file__).resolve().parents[1]
ENGINE = SOURCE.parent / '.work/xi-v17-gameplay-compare/v17-engine.so'
ADAPTER = Path(os.environ.get('STUDIO_TEST_ADAPTER', str(SOURCE / 'resources/native-ai-match-adapter.json')))
MAGIC = 0x54584631


@unittest.skipUnless(ENGINE.is_file() or native.APK.is_file(), 'requires verified original V17 engine fixture')
class TournamentFallbackNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ENGINE.is_file():
            native.raw = ENGINE.read_bytes()
        else:
            with zipfile.ZipFile(native.APK) as archive:
                native.raw = archive.read('lib/arm64-v8a/libUE4.so')
        if hashlib.sha256(native.raw).hexdigest() != 'efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8':
            raise AssertionError('Original engine fixture changed')
        native.bundle = json.loads(ADAPTER.read_text('utf8'))
        native.layout = native.bundle['channel_schema']
        if 'tournament_relaxed_aptitude' not in native.layout:
            raise AssertionError('Compile the tournament fallback adapter before these instruction tests')
        takeover.PLAN_RAW = native.raw

    def plan_vm(self, aptitude=0, *, magic=0, rules=0):
        vm = takeover.PlanVM()
        vm.aptitude_reads = []
        def ability():
            vm.aptitude_reads.append((vm.reg(0), vm.reg(1)))
            return aptitude
        vm.stubs[0x72b3658] = ability
        vm.u32(native.BUS + native.layout['rules_enabled'], rules)
        vm.u32(native.BUS + native.layout['tournament_relaxed_aptitude'], magic)
        proposal = vm.formation()
        vm.send(proposal)
        return vm

    def original_plan(self, vm):
        return bytes(vm.uc.mem_read(native.TEAM + 0x8078, 0xe6c))

    def test_strict_default_still_rejects_true_zero_and_partial_aptitude(self):
        for aptitude in (0, 1):
            with self.subTest(aptitude=aptitude):
                vm = self.plan_vm(aptitude)
                before = self.original_plan(vm)
                self.assertEqual(vm.apply(), 0)
                self.assertEqual(vm.ack(), (1, 3, 10))
                self.assertTrue(vm.aptitude_reads)
                self.assertEqual(self.original_plan(vm), before)
                self.assertEqual(vm.queued, [])

    def test_scoped_tournament_accepts_real_zero_or_partial_without_rewriting_roster(self):
        for aptitude in (0, 1):
            with self.subTest(aptitude=aptitude):
                vm = self.plan_vm(aptitude, magic=MAGIC, rules=1)
                before = self.original_plan(vm)
                roster = bytes(vm.uc.mem_read(native.PLAYERS, 0x406c))
                self.assertEqual(vm.apply(), 1)
                self.assertEqual(vm.ack(), (1, 2, 0))
                self.assertGreaterEqual(len(vm.aptitude_reads), 22)
                self.assertNotEqual(self.original_plan(vm), before)
                self.assertEqual(bytes(vm.uc.mem_read(native.PLAYERS, 0x406c)), roster)
                self.assertEqual(vm.stubs[0x72b3658](), aptitude)
                self.assertEqual(vm.queued, [])

    def test_wrong_magic_or_missing_exact_tournament_rule_opt_in_stays_strict(self):
        for magic, rules in ((0, 1), (MAGIC ^ 1, 1), (MAGIC, 0), (MAGIC, 2)):
            with self.subTest(magic=magic, rules=rules):
                vm = self.plan_vm(0, magic=magic, rules=rules)
                before = self.original_plan(vm)
                self.assertEqual(vm.apply(), 0)
                self.assertEqual(vm.ack(), (1, 3, 10))
                self.assertEqual(self.original_plan(vm), before)
                self.assertEqual(vm.queued, [])

    def test_unknown_native_aptitude_values_remain_rejected_even_in_tournament_scope(self):
        for aptitude in (3, 255, 0xffffffff):
            with self.subTest(aptitude=aptitude):
                vm = self.plan_vm(aptitude, magic=MAGIC, rules=1)
                before = self.original_plan(vm)
                self.assertEqual(vm.apply(), 0)
                self.assertEqual(vm.ack(), (1, 3, 10))
                self.assertEqual(self.original_plan(vm), before)
                self.assertEqual(vm.queued, [])

    def test_fallback_flag_never_bypasses_identity_or_human_control_scope(self):
        for invalid in ('identity', 'human'):
            with self.subTest(invalid=invalid):
                vm = self.plan_vm(0, magic=MAGIC, rules=1)
                if invalid == 'identity':
                    vm.u64(native.PLAYERS + 0xa8 + 0x38, 999999)
                else:
                    vm.human = True
                before = self.original_plan(vm)
                self.assertEqual(vm.apply(), 0xffffffff)
                self.assertEqual(vm.ack()[0], 0)
                self.assertEqual(self.original_plan(vm), before)
                self.assertEqual(vm.queued, [])

    def test_substitution_current_role_intermediate_uses_the_same_scoped_exception(self):
        for aptitude in (0, 1):
            for relaxed in (False, True):
                with self.subTest(aptitude=aptitude, relaxed=relaxed):
                    vm = takeover.QueueVM()
                    vm.u32(native.BUS + native.layout['rules_enabled'], int(relaxed))
                    vm.u32(native.BUS + native.layout['tournament_relaxed_aptitude'], MAGIC if relaxed else 0)
                    # The target roles are all CB, while the CURRENT outgoing
                    # role is CMF. This reaches the separate native
                    # substitution intermediate-role check (reason13).
                    vm.spec['profiles'][0]['attack'] = [0] + [1] * 10
                    vm.spec['profiles'][0]['defence'] = [0] + [1] * 10
                    vm.stubs[0x72b3658] = lambda: aptitude if vm.reg(1) == 5 else 2
                    vm.send(vm.proposal(batch=1))
                    self.assertEqual(vm.tick(), int(relaxed))
                    self.assertEqual(vm.ack(), (1, 1, 0) if relaxed else (1, 3, 13))
                    self.assertEqual(vm.queues[native.SELF + 0x20], [[3, 7, 12]] if relaxed else [])


if __name__ == '__main__':unittest.main()
