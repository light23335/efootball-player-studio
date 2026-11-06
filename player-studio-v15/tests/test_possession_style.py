"""Native holder writes -> one70% ticket -> forced style choice and diagnostics."""
import struct,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_ai_cut_in_shots as fixture

class PossessionStyleTests(unittest.TestCase):
    machine=fixture.NativeAiCutInTests.machine
    install_all=fixture.NativeAiCutInTests.install_all
    relocate_state=fixture.NativeAiCutInTests.relocate_state
    setup_context=fixture.NativeAiCutInTests.setup_context
    set_slot=fixture.NativeAiCutInTests.set_slot
    run_helper=fixture.NativeAiCutInTests.run_helper
    candidates=fixture.NativeAiCutInTests.candidates
    choose=fixture.NativeAiCutInTests.choose
    selection_result=fixture.NativeAiCutInTests.selection_result
    estimate=fixture.NativeAiCutInTests.estimate
    simulation_clock=fixture.NativeAiCutInTests.simulation_clock
    @classmethod
    def setUpClass(cls):fixture.NativeAiCutInTests.setUpClass.__func__(cls)
    def owner(self,vm,index):
        r=self.r;source=0x4101e800;stop=0x2003f000
        vm.mem_write(source,struct.pack('<I',index&0xffffffff))
        vm.reg_write(r.UC_ARM64_REG_X0,self.ball_manager)
        vm.reg_write(r.UC_ARM64_REG_X1,source)
        vm.reg_write(r.UC_ARM64_REG_X30,stop)
        sp=vm.reg_read(r.UC_ARM64_REG_SP)
        vm.emu_start(0x6acd550,stop,count=100000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),sp)
        self.assertEqual(struct.unpack('<I',vm.mem_read(self.ball_manager+0x28780,4))[0],index&0xffffffff)
    def inward(self,vm):
        self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135.}})
    def test_incisive_forces_inward_without_shooting_skill_or_attack_half(self):
        for x in(-29.,0.,29.):
            vm=self.setup_context(skills=(),x=x,z=18.);self.inward(vm)
            chosen,why=self.selection_result(vm)
            self.assertEqual((chosen,why['reason']),(1,'forced_incisive_route'))
            self.assertTrue(why['possession']['active'])
            self.assertEqual(why['possession']['probability'],.7)
    def test_one_roll_stays_locked_across_repeated_decisions_and_geometry(self):
        vm=self.setup_context(skills=());self.inward(vm)
        first=None
        for i in range(40):
            self.set_slot(vm,7,(),True,20.+i*.1,18.)
            chosen,why=self.selection_result(vm)
            self.assertEqual(chosen,1)
            ticket=why['possession']
            if first is None:first=ticket
            self.assertEqual(ticket,first)
        self.assertEqual(len(self.possession_draws),1)
    def test_holder_uses_ai_game_context_not_global_game_model(self):
        vm=self.setup_context(skills=(),lone_wolf=True);self.inward(vm)
        self.assertEqual(bytes(vm.mem_read(self.model+0x10,8)),bytes(8))
        self.assertEqual(self.selection_result(vm)[0],1)
        other=0x47040000;vm.mem_map(other,0x30000)
        vm.mem_write(other+0x28780,struct.pack('<I',18))
        vm.mem_write(self.model+0x10,struct.pack('<Q',other))
        self.assertEqual(self.selection_result(vm)[0],1)
        self.owner(vm,8)
        why=self.selection_result(vm)[1]
        self.assertEqual(why['reason'],'not_current_ball_holder')
        self.assertEqual(why['native_owner_slot'],8)
    def test_missing_game_context_manager_is_not_mislabeled_as_another_holder(self):
        vm=self.setup_context(skills=());self.inward(vm)
        vm.mem_write(self.root+0x10,bytes(8))
        self.assertEqual(self.selection_result(vm)[1]['reason'],'possession_context_missing')
    def test_missed_roll_keeps_native_for_entire_possession(self):
        vm=self.setup_context(skills=(),style_roll=9);self.inward(vm)
        for _ in range(30):
            chosen,why=self.selection_result(vm)
            self.assertEqual((chosen,why['reason']),(0,'possession_roll_rejected'))
            self.assertFalse(why['possession']['active'])
            self.assertFalse(why['incisive_branch'])
        self.assertEqual(len(self.possession_draws),1)
    def test_all_seven_accepting_tickets_and_three_rejecting_tickets(self):
        for roll in range(10):
            vm=self.setup_context(skills=(),style_roll=roll);self.inward(vm)
            chosen,why=self.selection_result(vm)
            self.assertEqual(chosen,int(roll<7))
            self.assertEqual(why['possession']['roll'],roll)
    def test_teammate_handoff_and_return_reset_even_without_teammate_decisions(self):
        vm=self.setup_context(skills=());self.inward(vm)
        first=self.selection_result(vm)[1]['possession']['epoch']
        self.owner(vm,8);self.owner(vm,7)
        second=self.selection_result(vm)[1]['possession']['epoch']
        self.assertGreater(second,first)
        self.assertEqual(sum(owner==7 for _,owner in self.possession_draws),2)
    def test_opponent_or_no_owner_ends_the_ticket(self):
        for other in(18,0xffffffff):
            vm=self.setup_context(skills=());self.inward(vm)
            first=self.selection_result(vm)[1]['possession']['epoch']
            self.owner(vm,other)
            self.assertEqual(self.selection_result(vm)[1]['reason'],'not_current_ball_holder')
            self.owner(vm,7)
            self.assertGreater(self.selection_result(vm)[1]['possession']['epoch'],first)
    def test_same_owner_setter_does_not_reroll(self):
        vm=self.setup_context(skills=());self.inward(vm)
        first=self.selection_result(vm)[1]['possession']
        for _ in range(20):self.owner(vm,7)
        self.assertEqual(self.selection_result(vm)[1]['possession'],first)
        self.assertEqual(len(self.possession_draws),1)
    def test_off_ball_queries_do_not_claim_someone_elses_ticket(self):
        vm=self.setup_context(skills=());self.inward(vm)
        self.owner(vm,8)
        chosen,why=self.selection_result(vm)
        self.assertEqual((chosen,why['reason']),(0,'not_current_ball_holder'))
        self.assertFalse(any(owner==7 for _,owner in self.possession_draws))
        self.owner(vm,7)
        self.assertEqual(self.selection_result(vm)[0],1)
        self.assertEqual(sum(owner==7 for _,owner in self.possession_draws),1)
    def test_pause_without_owner_change_keeps_the_ticket(self):
        vm=self.setup_context(skills=());self.inward(vm)
        before=self.selection_result(vm)[1]['possession']
        vm.mem_write(self.game+0x3314,struct.pack('<I',14))
        self.assertEqual(self.selection_result(vm)[0],0)
        vm.mem_write(self.game+0x3314,struct.pack('<I',1))
        self.assertEqual(self.selection_result(vm)[1]['possession'],before)
        self.assertEqual(len(self.possession_draws),1)
    def test_prediction_manager_does_not_replace_the_real_possessions_ticket(self):
        vm=self.setup_context(skills=());self.inward(vm)
        before=self.selection_result(vm)[1]['possession']
        clone=0x48000000;vm.mem_map(clone,0x30000)
        vm.mem_write(clone+0x28780,struct.pack('<I',7))
        vm.mem_write(self.root+0x10,struct.pack('<Q',clone))
        other=self.selection_result(vm)[1]['possession']
        self.assertNotEqual(other['epoch'],before['epoch'])
        vm.mem_write(self.root+0x10,struct.pack('<Q',self.ball_manager))
        self.assertEqual(self.selection_result(vm)[1]['possession'],before)
        self.assertEqual(len(self.possession_draws),2)
    def test_clock_rewind_and_actor_replacement_do_not_reuse_an_old_ticket(self):
        vm=self.setup_context(skills=());self.inward(vm);clock=[100]
        self.simulation_clock(vm,clock)
        before=self.selection_result(vm)[1]['possession']['epoch']
        clock[0]=2
        after=self.selection_result(vm)[1]['possession']['epoch']
        self.assertGreater(after,before)
        old=self.states+7*0x2000;new=self.states+0x2c000
        vm.mem_write(new,bytes(vm.mem_read(old,0x2000)))
        vm.mem_write(self.model+0x4e80+7*0x50,struct.pack('<Q',new))
        self.assertGreater(self.selection_result(vm)[1]['possession']['epoch'],after)
    def test_contention_is_bounded_and_does_not_cache_a_failed_roll(self):
        vm=self.setup_context(skills=());self.inward(vm)
        cursor=0x49000000
        for _,size in self.candidate['bundles'][0]['writable_fixups']:
            if size==64+256*64:break
            cursor+=(size+15)//16*16
        else:self.fail('Missing possession state')
        vm.mem_write(cursor,struct.pack('<I',1))
        self.assertEqual(self.selection_result(vm)[1]['reason'],'possession_state_busy')
        self.assertEqual(self.possession_draws,[])
        vm.mem_write(cursor,bytes(4))
        self.assertEqual(self.selection_result(vm)[0],1)
        self.assertEqual(len(self.possession_draws),1)
    def test_holder_hook_keeps_original_registers_flags_and_native_store(self):
        results=[]
        for patched in(False,True):
            vm=self.setup_context(skills=(),patched=patched)
            if patched:self.run_helper(vm,'studio_ai_possession_profile',self.ctx)
            source=0x4101e800;stop=0x2003f000;r=self.r
            vm.mem_write(source,struct.pack('<I',8))
            for n in range(31):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),0x12340000+n)
            for n in range(32):vm.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(n)),(1<<100)+n)
            vm.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000)
            vm.reg_write(r.UC_ARM64_REG_X0,self.ball_manager)
            vm.reg_write(r.UC_ARM64_REG_X1,source);vm.reg_write(r.UC_ARM64_REG_X30,stop)
            sp=vm.reg_read(r.UC_ARM64_REG_SP)
            vm.emu_start(0x6acd550,stop,count=100000)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
            results.append(([vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(n)))for n in range(31)],
                            [vm.reg_read(getattr(r,'UC_ARM64_REG_Q'+str(n)))for n in range(32)],
                            vm.reg_read(r.UC_ARM64_REG_SP),vm.reg_read(r.UC_ARM64_REG_NZCV),
                            bytes(vm.mem_read(self.ball_manager,0x30000))))
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),sp)
        self.assertEqual(results[0],results[1])
    def test_shared_ticket_drives_the_combined_style_without_a_second_roll(self):
        vm=self.setup_context(skills=(),lone_wolf=True,x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':3,'angle':135.}})
        chosen,why=self.selection_result(vm)
        self.assertEqual((chosen,why['reason']),(1,'lone_wolf_shot'))
        self.assertTrue(why['incisive_branch']);self.assertTrue(why['lone_wolf_branch'])
        self.veto={1}
        chosen,why=self.selection_result(vm)
        self.assertEqual((chosen,why['reason']),(2,'lone_wolf_route'))
        self.assertEqual(len(self.possession_draws),1)
    def test_lone_wolf_without_incisive_or_shooting_skills_still_uses_ticket(self):
        vm=self.setup_context(skills=(),incisive=False,lone_wolf=True)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.selection_result(vm)[0],1)
    def test_native_veto_remains_authoritative_and_no_actions_are_synthesized(self):
        vm=self.setup_context(skills=());self.inward(vm);self.veto={1}
        chosen,why=self.selection_result(vm)
        self.assertEqual(chosen,0);self.assertEqual(why['native_vetoed_ids'],[1])
        self.candidates(vm,{0:{'kind':2},1:{'kind':10}})
        self.assertEqual(self.selection_result(vm)[0],0)
    def test_protected_pass_does_not_suppress_an_active_inward_route(self):
        vm=self.setup_context(x=29.,z=12.);self.set_slot(vm,self.receiver,(),False,44.,4.)
        self.inward(vm)
        self.assertTrue(self.estimate(vm,0)[1]&2)
        self.assertEqual(self.selection_result(vm)[0],1)
    def test_original_opportunity_gap_does_not_suppress_active_wolf(self):
        vm=self.setup_context(lone_wolf=True,x=29.,z=12.)
        self.set_slot(vm,self.receiver,(),False,1.,10.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        first=self.estimate(vm,0)[0];second=self.estimate(vm,1)[0]
        self.assertGreater(second-first,8.)
        self.assertEqual(self.selection_result(vm)[0],1)
    def test_old_workshop_clearance_gate_does_not_replace_native_veto(self):
        vm=self.setup_context();self.set_slot(vm,11,(),False,29.8,15.2);self.inward(vm)
        self.assertEqual(self.estimate(vm,1)[1],0)
        self.assertEqual(self.selection_result(vm)[0],1)
        self.veto={1};self.assertEqual(self.selection_result(vm)[0],0)
        self.assertEqual(len(self.possession_draws),1)
    def test_incisive_does_not_pretend_an_unavailable_route_was_created(self):
        vm=self.setup_context(skills=())
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.selection_result(vm)[1]['reason'],'no_executable_incisive_route')
    def test_wolf_uses_native_shots_without_old_distance_or_angle_gate(self):
        for x,z in((0.,25.),(40.,12.),(-20.,18.)):
            vm=self.setup_context(skills=(),incisive=False,lone_wolf=True,x=x,z=z)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.selection_result(vm)[0],1)
    def test_invalid_shot_target_or_mode_is_not_invented_into_a_style_action(self):
        for row in({'kind':1,'target':(0.,0.,0.)},{'kind':1,'mode':2}):
            vm=self.setup_context(skills=(),incisive=False,lone_wolf=True)
            self.candidates(vm,{0:{'kind':2},1:row})
            self.assertEqual(self.selection_result(vm)[0],0)
    def test_bad_snapshot_is_reported_without_spending_another_possession_roll(self):
        vm=self.setup_context(skills=());self.inward(vm)
        self.set_slot(vm,21,(),False,float('nan'),12.)
        self.assertEqual(self.selection_result(vm)[1]['reason'],'snapshot_rejected')
        self.set_slot(vm,21,(),False,-15.,22.)
        self.assertEqual(self.selection_result(vm)[0],1)
        self.assertEqual(len(self.possession_draws),1)
    def test_original_class_and_original_score_no_longer_block_incisive(self):
        for kind in(1,2,10,13):
            vm=self.setup_context(skills=());self.candidates(vm,{0:{'kind':kind},1:{'kind':3,'angle':135.}})
            self.assertEqual(self.selection_result(vm)[0],1)
    def test_original_no_candidate_can_use_a_native_executable_style_route(self):
        vm=self.setup_context(skills=());self.inward(vm)
        self.assertEqual(self.selection_result(vm,30)[0],1)
    def test_handoff_during_candidate_check_rejects_the_stale_decision(self):
        vm=self.setup_context(skills=());self.inward(vm)
        self.on_veto=lambda uc,n:uc.mem_write(self.ball_manager+0x28780,struct.pack('<I',8))
        chosen,why=self.selection_result(vm)
        self.assertEqual((chosen,why['reason']),(0,'possession_changed_during_decision'))
        self.assertTrue(why['possession']['expired_during_decision'])
    def test_private_hash_gate_is_approximately_seventy_percent_over_possessions(self):
        vm=self.setup_context(skills=(),style_roll=None)
        state=self.states+7*0x2000
        active=0;count=2000
        self.run_helper(vm,'studio_ai_possession_state',self.ball_manager,7,1,7,state,0,self.model)
        for _ in range(count):
            self.owner(vm,8);self.owner(vm,7)
            active+=self.run_helper(vm,'studio_ai_possession_state',self.ball_manager,7,1,7,state,0,self.model)
        self.assertLess(abs(active/count-.7),.035,(active,count))
        self.assertEqual(sum(owner==7 for _,owner in self.possession_draws),count+1)
        type(self).distribution_proof={'accepted':active,'possessions':count,'native_rng_called':False}
