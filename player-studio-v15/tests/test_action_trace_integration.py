"""Execute whole native shot boundaries, with and without observation."""
import io,struct,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'maintenance')]
import test_ai_cut_in_shots as ai
import test_skill_effects_v2 as fixture
import action_trace as trace


@unittest.skipUnless(ai.APK.is_file(),'requires original V17 engine')
class ShotObserverIntegrationTests(unittest.TestCase):
    setup_context=ai.NativeAiCutInTests.setup_context
    set_slot=ai.NativeAiCutInTests.set_slot
    candidates=ai.NativeAiCutInTests.candidates
    choose=ai.NativeAiCutInTests.choose
    power_fixture=ai.NativeAiCutInTests.power_fixture
    native_power=ai.NativeAiCutInTests.native_power
    relocate_state=fixture.NativeSkillV2Tests.relocate_state

    @classmethod
    def setUpClass(cls):
        ai.NativeAiCutInTests.setUpClass.__func__(cls)
        cls.policy=cls.candidate
        from build_action_observer import build
        cls.observed=build(cls.engine,ai=True)
        cls.observed_native=build(cls.engine)

    def machine(self,stubs):
        stubs=dict(stubs)
        stubs.setdefault(0x698f7e0,lambda vm:vm.reg_write(self.r.UC_ARM64_REG_X0,
                        self.power_addresses['model']if hasattr(self,'power_addresses')else self.model))
        vm=fixture.NativeSkillV2Tests.machine(self,stubs);vm.mem_map(0x49010000,0x100000)
        return vm

    def install_all(self,vm):
        helpers=fixture.NativeSkillV2Tests.install_all(self,vm)
        bundle=self.candidate['bundles'][0]
        if 'action_trace_schema'in bundle:
            index=bundle['action_trace_writable_index']
            ring=0x49000000+sum((size+15)//16*16 for _,size in bundle['writable_fixups'][:index])
            vm.mem_write(ring,struct.pack('<II',trace.MAGIC,1))
            self.reader=trace.RingReader(lambda at,size:bytes(vm.mem_read(ring+at,size)))
        return helpers

    def request(self,vm):
        r=self.r;out=0x42009000;request=0x42009100
        vm.mem_write(request,struct.pack('<I3f',0,52.5,0.,1.))
        for reg,value in ((r.UC_ARM64_REG_X0,out),(r.UC_ARM64_REG_X1,self.ctx),
                          (r.UC_ARM64_REG_X2,request),(r.UC_ARM64_REG_X30,0x2003f000)):
            vm.reg_write(reg,value)
        vm.emu_start(0x70e7430,0x2003f000,count=100000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),0x2003f000)
        return bytes(vm.mem_read(out,24)),vm.reg_read(r.UC_ARM64_REG_X0)

    def test_observed_request_matches_existing_ai_policy_and_records_native_then_modified_type(self):
        for skills in ((),(18,),(24,),(25,)):
            results=[]
            for candidate in (self.policy,self.observed):
                self.candidate=candidate
                vm=self.setup_context(skills=skills,fixed_class=None)
                vm.mem_write(self.model+0x3b20+7*0x50,struct.pack('<Q',self.player))
                vm.mem_write(self.player+0x2a38,b'\7');vm.mem_write(self.player+0x4620,struct.pack('<Q',self.model))
                results.append(self.request(vm))
                if candidate is self.observed:
                    rows=[r for r in self.reader.drain()if r['event']=='ai_shot_request']
                    self.assertEqual(len(rows),2)
                    self.assertEqual(rows[0]['selected_type'],0)
                    self.assertEqual(rows[1]['selected_type'],struct.unpack_from('<I',results[-1][0],8)[0])
                    self.assertEqual(rows[1]['original_type'],0)
            self.assertEqual(results[0],results[1])

    def test_observed_power_preserves_whole_native_control_state_and_return(self):
        for subtype in (0,1,2,3,4):
            results=[]
            for candidate in (self.policy,self.observed):
                self.candidate=candidate
                vm=self.power_fixture(subtype=subtype);results.append(self.native_power(vm))
                if candidate is self.observed:
                    rows=[r for r in self.reader.drain()if r['event']=='ai_shot_power']
                    self.assertEqual(len(rows),2)
                    self.assertEqual(rows[0]['stage'],'native_power_before_preference')
                    self.assertEqual(rows[1]['stage'],'power_after_preference')
                    self.assertEqual(rows[1]['power_after'],round(struct.unpack_from('<f',results[-1][0],0xe7c)[0],6))
            self.assertEqual(results[0],results[1])

    def test_trace_only_does_not_enable_ai_preferences(self):
        self.candidate=self.observed_native
        vm=self.setup_context(skills=(18,),fixed_class=None)
        result=self.request(vm)
        self.assertEqual(struct.unpack_from('<I',result[0],8)[0],0)

    def test_candidate_hook_records_real_native_pass_and_modified_dribble_without_changing_policy(self):
        results=[]
        for candidate in (self.policy,self.observed):
            self.candidate=candidate
            vm=self.setup_context(x=27.,z=18.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135.}})
            results.append(self.choose(vm))
            if candidate is self.observed:
                rows=[v for v in self.reader.drain()if v['event']=='ai_candidate_choice']
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[0]['candidate']['original_name'],'传球')
                self.assertEqual(rows[1]['candidate']['selected_name'],'盘带候选')
                self.assertEqual(rows[1]['candidate']['selected_id'],results[-1])
                self.assertTrue(rows[1]['candidate']['changed'])
                self.assertFalse(rows[1]['candidate']['motion_execution_confirmed'])
                self.assertIn('内切突破',rows[1]['ai_styles'])
        self.assertEqual(results,[1,1])


if __name__=='__main__':unittest.main()
