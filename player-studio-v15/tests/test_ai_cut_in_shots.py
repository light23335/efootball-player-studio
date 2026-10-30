"""Execute the preference hooks against the original V17 AArch64 routines.

The original caller constructs the selector; original per-slot getters and
geometry execute unchanged. Singleton/veto and external fmodf are explicit
inputs. Focused boundary tests control the draw; distribution tests execute
the private PRNG. Different actors never share ability or position records.
"""
import copy, io, json, math, os, struct, sys, unittest, zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'maintenance'))
import test_skill_effects_v2 as nativefixtures
APK=Path(os.environ.get('STUDIO_TEST_APK',str(SOURCE.parent.parent/'73efootball安装包及资源/73efootball-V17.apk')))


@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class NativeAiCutInTests(unittest.TestCase):
    machine=nativefixtures.NativeSkillV2Tests.machine
    install_all=nativefixtures.NativeSkillV2Tests.install_all
    relocate_state=nativefixtures.NativeSkillV2Tests.relocate_state

    @classmethod
    def setUpClass(cls):
        import unicorn
        from unicorn import arm64_const
        from elftools.elf.elffile import ELFFile
        from build_ai_cut_in_shots import build
        cls.u,cls.r=unicorn,arm64_const
        with zipfile.ZipFile(APK)as z:cls.engine=z.read('lib/arm64-v8a/libUE4.so')
        elf=ELFFile(io.BytesIO(cls.engine))
        cls.segments=[(s['p_vaddr'],s['p_offset'],s['p_filesz'],s['p_memsz'])for s in elf.iter_segments()if s['p_type']=='PT_LOAD']
        cls.candidate=build(cls.engine)

    def setup_context(self,skills=(17,),incisive=True,x=27.,z=18.,side=1,phase=1,index=7,game_word=0,patched=True,lone_wolf=False,heading=None,foot=0,fixed_class='eligible',probability=True):
        self.info=0x42010100;self.root=0x42010200;self.model=0x43000000
        self.states=0x44000000;self.players=0x45000000
        slot=index if 0<=index<22 else 0
        self.ability=self.states+slot*0x2000+0x394;self.player=self.players+slot*0x1000
        self.team=0x42013000;self.pitch=0x42014000;self.game=0x42015000;self.ai=0x42001000
        self.veto=set();self.veto_calls=[]
        r=self.r
        def singleton(vm):vm.reg_write(r.UC_ARM64_REG_X0,self.model)
        def veto(vm):
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X1),self.ctx)
            n=vm.reg_read(r.UC_ARM64_REG_W2);self.veto_calls.append(n);vm.reg_write(r.UC_ARM64_REG_W0,int(n in self.veto))
        def fmodf(vm):
            values=[struct.unpack('<f',struct.pack('<I',vm.reg_read(reg)))[0]for reg in (r.UC_ARM64_REG_S0,r.UC_ARM64_REG_S1)]
            vm.reg_write(r.UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',math.fmod(*values)))[0])
        stubs={0x698f7e0:singleton,0x70e72a0:veto,0x8c211f0:fmodf}
        vm=self.machine(stubs);vm.mem_map(0x42000000,0x20000)
        vm.mem_map(self.model,0x10000);vm.mem_map(self.states,0x30000);vm.mem_map(self.players,0x20000)
        vm.mem_write(self.model+0x4d0,struct.pack('<Q',self.game))
        vm.mem_write(self.model+0x5b60,struct.pack('<Q',self.pitch))
        for team in range(2):vm.mem_write(self.model+0x3030+team*0x50,struct.pack('<Q',self.team))
        for n in range(22):
            vm.mem_write(self.model+0x4e80+n*0x50,struct.pack('<Q',self.states+n*0x2000))
            vm.mem_write(self.model+0x3b20+n*0x50,struct.pack('<Q',self.players+n*0x1000))
            self.set_slot(vm,n,(),False,(-35.+(n%11)*2.)*side,-28.+(n%11)*5.)
            vm.mem_write(self.game+0x4202+n,b'\1')
        vm.mem_write(self.game,struct.pack('<I',game_word))
        vm.mem_write(self.game+0x3314,struct.pack('<I',phase))
        # Execute the actual four-instruction constructor immediately before
        # 70e4c0c calls the selector. Never hand-pack a convenient test layout.
        sp=0x40007000;fp=sp+0x120;self.ctx=sp+0x48
        vm.reg_write(r.UC_ARM64_REG_SP,sp);vm.reg_write(r.UC_ARM64_REG_X29,fp)
        vm.mem_write(self.ctx,struct.pack('<Q',self.info));vm.mem_write(self.ctx+0x18,struct.pack('<Q',self.root))
        vm.mem_write(self.info,struct.pack('<I',index));vm.mem_write(fp-0x68,struct.pack('<Q',self.game))
        vm.mem_write(self.pitch,struct.pack('<3f',52.5,0.,34.));vm.mem_write(self.team+0x28c,struct.pack('<b',side))
        if heading is None:heading=(math.degrees(math.atan2(52.5*side-x,-z))+(-25. if foot==0 else 25.))%360 if math.isfinite(x)and math.isfinite(z)else 0.
        self.set_slot(vm,slot,skills,incisive,x,z,lone_wolf,heading,foot)
        self.receiver=(slot//11)*11+(slot+1)%11
        self.set_slot(vm,self.receiver,(),False,x-1.5*side,z-2.*(1 if z>=0 else -1))
        vm.reg_write(r.UC_ARM64_REG_X19,self.ai);vm.reg_write(r.UC_ARM64_REG_X23,self.ctx)
        vm.reg_write(r.UC_ARM64_REG_X21,self.root)
        vm.emu_start(0x70e4bfc,0x70e4c0c,count=100)
        self.selector=vm.reg_read(r.UC_ARM64_REG_X0)
        self.helpers=self.install_all(vm)if patched else {}
        # Controlled random input for focused eligibility/geometry tests.
        # Distribution/cache tests below set fixed_class=None and execute the
        # actual private PRNG. No selector or opportunity result is stubbed.
        if patched and fixed_class is not None:
            draw=self.helpers['shared_studio_ai_equal_action_draw']
            def controlled_draw(vm,address,size,data):
                if address!=draw:return
                mask=vm.reg_read(r.UC_ARM64_REG_W1);domain=vm.reg_read(r.UC_ARM64_REG_W2)
                choices=[n for n in (1,2,3)if mask&(1<<n)]
                selected=(2 if domain else (1 if 1 in choices else 3 if 3 in choices else 2))if fixed_class=='eligible' else fixed_class
                if domain==2:selected=choices[0]if fixed_class=='eligible'or selected not in choices else selected
                self.assertIn(selected,choices)
                vm.reg_write(r.UC_ARM64_REG_W0,selected);vm.reg_write(r.UC_ARM64_REG_PC,vm.reg_read(r.UC_ARM64_REG_X30))
            vm.hook_add(self.u.UC_HOOK_CODE,controlled_draw)
        if patched and probability is not None and 'shared_studio_ai_probability_gate' in self.helpers:
            gate=self.helpers['shared_studio_ai_probability_gate']
            def controlled_gate(vm,address,size,data):
                if address==gate:
                    vm.reg_write(r.UC_ARM64_REG_W0,int(probability))
                    vm.reg_write(r.UC_ARM64_REG_PC,vm.reg_read(r.UC_ARM64_REG_X30))
            vm.hook_add(self.u.UC_HOOK_CODE,controlled_gate)
        return vm

    def set_slot(self,vm,index,skills=(),incisive=False,x=29.,z=12.,lone_wolf=False,heading=90.,foot=0):
        ability=self.states+index*0x2000+0x394;player=self.players+index*0x1000
        flags={17:7,18:51,23:42,24:58,25:74};bits=sum(1<<flags[k]for k in set(skills))
        vm.mem_write(ability+0xc0,bits.to_bytes(12,'little'))
        vm.mem_write(ability+0xd4,struct.pack('<I',((1<<4)if incisive else 0)|((1<<7)if lone_wolf else 0)))
        vm.mem_write(ability+0x35,bytes([foot]))
        vm.mem_write(player+0x4ec,struct.pack('<f',heading))
        vm.mem_write(player+0x4f4,struct.pack('<3f',x,0.,z))

    def choose(self,vm):
        r=self.r;stop=0x2003f000
        vm.reg_write(r.UC_ARM64_REG_X0,self.selector);vm.reg_write(r.UC_ARM64_REG_X30,stop)
        vm.emu_start(0x70e57a0,stop,count=100000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
        return vm.reg_read(r.UC_ARM64_REG_W0)

    def run_helper(self,vm,name,*args):
        r=self.r
        for n,v in enumerate(args):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),v)
        stop=0x2003f000;vm.reg_write(r.UC_ARM64_REG_X30,stop)
        vm.emu_start(self.helpers['shared_'+name],stop,count=100000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
        return vm.reg_read(r.UC_ARM64_REG_W0)

    def candidates(self,vm,rows,order=None):
        for n,row in rows.items():
            data=bytearray(80);struct.pack_into('<I',data,0,row['kind'])
            if row['kind']==1:
                struct.pack_into('<I3f',data,8,row.get('mode',0),*row.get('target',(52.5,0.,1.)))
            if row['kind']==2:
                struct.pack_into('<II',data,0x1c,row.get('recipient',self.receiver),row.get('mode',0))
                if row.get('special'):data[0x26]=1
            if row['kind']==3:struct.pack_into('<If',data,0x2c,row.get('mode',3),row.get('angle',135.))
            vm.mem_write(self.ai+0x49c8+n*80,bytes(data))
        order=list(rows)if order is None else order
        vm.mem_write(self.ai+0x48a8,struct.pack('<I',len(order))+b''.join(struct.pack('<I',n)for n in order))

    def test_skill_priority_all_combinations(self):
        for values,expected in [((),0),((23,),1),((17,),2),((18,),3),((17,23),2),((18,23),3),((17,18),3),((17,18,23),3)]:
            with self.subTest(skills=values):
                vm=self.setup_context(skills=values)
                self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),expected)

    def test_native_caller_constructs_separate_game_and_player_contexts(self):
        vm=self.setup_context()
        ai,game_ref,ctx,root=struct.unpack('<4Q',vm.mem_read(self.selector,32))
        self.assertEqual((ai,ctx,root),(self.ai,self.ctx,self.root))
        self.assertNotEqual(game_ref,self.ctx)
        self.assertEqual(struct.unpack('<Q',vm.mem_read(game_ref,8))[0],self.game)

    def test_null_player_context_keeps_original_candidate(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        vm.mem_write(self.selector+0x10,bytes(8))
        self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),0)
        self.assertEqual(self.veto_calls,[])

    def test_current_qualified_player_not_lost_to_unqualified_other_slot(self):
        vm=self.setup_context(index=7,x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.choose(vm),1)

    def test_other_qualified_player_cannot_grant_current_player_eligibility(self):
        vm=self.setup_context(index=7,skills=(),incisive=False,x=29.,z=12.)
        self.set_slot(vm,0,(17,),True)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.choose(vm),0)

    def test_all_22_slots_keep_qualification_separate_from_game_word(self):
        for index in range(22):
            decoy=(index+2)%22
            for qualified in [False,True]:
                with self.subTest(slot=index,qualified=qualified,decoy=decoy):
                    vm=self.setup_context(index=index,skills=(17,)if qualified else (),incisive=qualified,
                                          x=29.,z=12.,game_word=decoy)
                    self.set_slot(vm,decoy,()if qualified else (18,),not qualified,-30.,28.)
                    self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
                    self.assertEqual(self.choose(vm),int(qualified))

    def test_position_is_read_from_current_player_even_if_both_have_skills(self):
        for current_x,other_x,expected in [(29.,-29.,1),(-29.,29.,0)]:
            vm=self.setup_context(index=7,x=current_x,z=12.)
            self.set_slot(vm,0,(17,),True,other_x,12.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.choose(vm),expected)

    def test_disabled_original_selector_and_enabled_select_same_world(self):
        for patched,expected in [(False,0),(True,1)]:
            vm=self.setup_context(index=7,x=29.,z=12.,patched=patched)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.choose(vm),expected)

    def test_native_geometry_heading_convention(self):
        vm=self.setup_context(x=27.,z=18.);r=self.r
        for angle,x,z in [(45.,29.828427,20.828427),(135.,29.828427,15.171573),
                          (225.,24.171573,15.171573),(315.,24.171573,20.828427)]:
            vm.reg_write(r.UC_ARM64_REG_X0,self.player+0x4f4)
            vm.reg_write(r.UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',angle))[0])
            vm.reg_write(r.UC_ARM64_REG_S1,struct.unpack('<I',struct.pack('<f',4.))[0])
            stop=0x2003f000;vm.reg_write(r.UC_ARM64_REG_X30,stop)
            vm.emu_start(0x6d3a784,stop,count=100000)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
            for reg,want in [(r.UC_ARM64_REG_S0,x),(r.UC_ARM64_REG_S2,z)]:
                actual=struct.unpack('<f',struct.pack('<I',vm.reg_read(reg)))[0]
                self.assertAlmostEqual(actual,want,places=4)

    def test_forward_inward_native_routes_on_both_wings_and_half_sides(self):
        for side,z,angle in [(1,18.,135.),(1,-18.,45.),(-1,18.,225.),(-1,-18.,315.)]:
            vm=self.setup_context(x=27.*side,z=z,side=side)
            self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':angle}})
            self.assertEqual(self.choose(vm),1)

    def test_shot_output_does_not_inherit_other_player_skills(self):
        for qualified,expected in [(False,0),(True,1)]:
            vm=self.setup_context(index=7,skills=(18,)if qualified else (),incisive=qualified,x=29.,z=12.)
            self.set_slot(vm,0,()if qualified else (18,),not qualified)
            out=0x42009000;request=0x42009100;r=self.r
            vm.mem_write(request,struct.pack('<I3f',0,52.5,0.,1.))
            vm.reg_write(r.UC_ARM64_REG_X0,out);vm.reg_write(r.UC_ARM64_REG_X1,self.ctx)
            vm.reg_write(r.UC_ARM64_REG_X2,request);stop=0x2003f000;vm.reg_write(r.UC_ARM64_REG_X30,stop)
            vm.emu_start(0x70e7430,stop,count=100000)
            self.assertEqual(struct.unpack('<II3f',vm.mem_read(out+4,20)),(25,expected,52.5,1.,0.))

    def test_requires_incisive_flag_four_not_early_crosser_three(self):
        vm=self.setup_context(incisive=False)
        vm.mem_write(self.ability+0xd4,struct.pack('<I',1<<3))
        self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),0)

    def test_normal_play_only_and_slot_bounds(self):
        for phase,index in [(0,0),(2,0),(3,0),(1,22),(1,255)]:
            vm=self.setup_context(phase=phase,index=index)
            self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),0)

    def test_half_switch_and_both_wings(self):
        for side in [-1,1]:
            for z in [-18.,18.]:
                vm=self.setup_context(side=side,x=27*side,z=z,index=11 if side==-1 else 0)
                self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),2)

    def test_outside_attack_zone_and_nonfinite_positions_unchanged(self):
        for x,z in [(-27.,18.),(0.,0.),(27.,40.),(52.,1.),(float('nan'),18.),(27.,float('inf'))]:
            vm=self.setup_context(x=x,z=z)
            self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),0)

    def test_promotes_existing_inward_candidate_over_pass(self):
        vm=self.setup_context()
        self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135.}})
        self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),1)

    def test_outward_backward_stopping_or_vetoed_dribble_not_promoted(self):
        for mode,angle,veto in [(3,45.,False),(3,225.,False),(0,135.,False),(3,135.,True)]:
            vm=self.setup_context();self.veto={1}if veto else set()
            self.candidates(vm,{0:{'kind':2},1:{'kind':3,'mode':mode,'angle':angle}})
            self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),0)

    def test_existing_shot_promoted_inside_sensible_angle_and_distance(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),1)

    def test_shot_veto_target_distance_angle_and_chip_preserved(self):
        for row,x,z,veto in [({'kind':1},29.,12.,True),({'kind':1,'target':(0.,0.,0.)},29.,12.,False),
                              ({'kind':1,'mode':2},29.,12.,False),({'kind':1},20.,12.,False),
                              ({'kind':1},40.,12.,False),({'kind':1},29.,25.,False)]:
            vm=self.setup_context(x=x,z=z);self.veto={1}if veto else set()
            self.candidates(vm,{0:{'kind':2},1:row})
            self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),0)

    def test_only_current_native_priority_list_is_searched(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}},order=[0])
        self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),0)

    def test_no_candidate_creation_or_override_of_native_special_action(self):
        for original,kind in [(30,0),(0,4),(0,1),(0,0)]:
            vm=self.setup_context(x=29.,z=12.)
            self.candidates(vm,{0:{'kind':kind},1:{'kind':1}})
            before=bytes(vm.mem_read(self.ai,0x6000))
            self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,original),original)
            self.assertEqual(bytes(vm.mem_read(self.ai,0x6000)),before)

    def test_controlled_request_priority_without_changing_target(self):
        for skills,mode in [((18,),1),((17,),1),((23,),0),((18,17,23),1)]:
            vm=self.setup_context(skills=skills,x=29.,z=12.)
            output=0x42009000;data=bytearray(200);struct.pack_into('<II3f',data,4,25,0,52.5,1.,0.)
            vm.mem_write(output,bytes(data));self.run_helper(vm,'studio_ai_prefer_curled_shot',output,self.ctx)
            data[8:12]=struct.pack('<I',mode)
            self.assertEqual(bytes(vm.mem_read(output,len(data))),bytes(data))

    def test_nonshot_and_setpiece_behavior_is_unchanged(self):
        for behavior,mode,x,z in [(104,0,29.,12.),(22,0,29.,12.)]:
            vm=self.setup_context(skills=(18,),x=x,z=z)
            output=0x42009000;data=struct.pack('<III3f',9,behavior,mode,52.5,1.,0.)
            vm.mem_write(output,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',output,self.ctx)
            self.assertEqual(bytes(vm.mem_read(output,len(data))),data)

    def test_request_wrapper_runs_real_native_shot_output(self):
        vm=self.setup_context(skills=(18,),x=29.,z=12.)
        out=0x42009000;request=0x42009100;vm.mem_write(request,struct.pack('<I3f',0,52.5,0.,1.))
        r=self.r;vm.reg_write(r.UC_ARM64_REG_X0,out);vm.reg_write(r.UC_ARM64_REG_X1,self.ctx);vm.reg_write(r.UC_ARM64_REG_X2,request)
        stop=0x2003f000;vm.reg_write(r.UC_ARM64_REG_X30,stop)
        vm.emu_start(0x70e7430,stop,count=100000)
        self.assertEqual(struct.unpack('<II3f',vm.mem_read(out+4,20)),(25,1,52.5,1.,0.))

    def test_choice_wrapper_runs_original_selector_and_preserves_abi(self):
        for incisive,expected in [(True,1),(False,0)]:
            vm=self.setup_context(incisive=incisive,x=29.,z=12.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            r=self.r;sp=vm.reg_read(r.UC_ARM64_REG_SP)
            for n in range(19,30):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),0x12340000+n)
            vm.reg_write(r.UC_ARM64_REG_X0,self.selector);stop=0x2003f000
            vm.reg_write(r.UC_ARM64_REG_X30,stop)
            vm.emu_start(0x70e57a0,stop,count=100000)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),stop)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_W0),expected)
            self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),sp)
            for n in range(19,30):self.assertEqual(vm.reg_read(getattr(r,'UC_ARM64_REG_X'+str(n))),0x12340000+n)

    def test_excessive_candidate_count_does_not_walk_outside_native_array(self):
        vm=self.setup_context(x=29.,z=12.);self.candidates(vm,{0:{'kind':2}})
        vm.mem_write(self.ai+0x48a8,struct.pack('<I',31))
        self.assertEqual(self.run_helper(vm,'studio_ai_select_cut_in_candidate',self.selector,0),0)

    def test_original_match_table_and_ai_decoder_agree(self):
        pairs=dict(struct.iter_unpack('<II',self.engine[0xc7fec0:0xc7fec0+0x250]))
        self.assertEqual({k:pairs[k]for k in [51,7,42]},{51:18,7:17,42:23})
        # Parameter 66 and AI bit 4 are not interchangeable with style list order.
        from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
        code=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(self.engine[0x6a74e6c-0x4000:0x6a74ea0-0x4000],0x6a74e6c))
        self.assertIn('w1, #0x42',[i.op_str for i in code if i.mnemonic=='mov'])
        self.assertIn('w1, #4',[i.op_str for i in code if i.mnemonic=='mov'])

    def estimate(self,vm,index):
        snapshot=0x4200a000;result=0x4200a200
        ok=self.run_helper(vm,'studio_ai_opportunity_snapshot',self.ctx,snapshot)
        self.assertEqual(ok,1)
        tier=self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx)
        vm.mem_write(snapshot+28,bytes([tier]))
        self.run_helper(vm,'studio_ai_opportunity_evaluate',snapshot,self.ai+0x49c8+index*80,result)
        return struct.unpack('<fI',vm.mem_read(result,8))

    def test_unknown_pass_recipient_or_inactive_receiver_keeps_original(self):
        for recipient in (255,22,11,7,8):
            vm=self.setup_context(x=29.,z=12.)
            if recipient==8:vm.mem_write(self.game+0x4202+8,b'\0')
            self.candidates(vm,{0:{'kind':2,'recipient':recipient},1:{'kind':1}})
            self.assertEqual(self.choose(vm),0)

    def test_through_lob_and_special_passes_are_not_guessed_from_current_position(self):
        for row in ({'kind':2,'mode':1},{'kind':2,'mode':2},{'kind':2,'mode':3},
                    {'kind':2,'special':True}):
            vm=self.setup_context(x=29.,z=12.)
            self.candidates(vm,{0:row,1:{'kind':1}})
            self.assertEqual(self.estimate(vm,0)[1],0)
            self.assertEqual(self.choose(vm),0)

    def test_clear_open_box_reception_is_protected(self):
        vm=self.setup_context(x=29.,z=12.)
        self.set_slot(vm,self.receiver,(),False,44.,4.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.estimate(vm,0)[1]&3,3)
        self.assertEqual(self.choose(vm),0)

    def test_protected_pass_elsewhere_in_native_list_blocks_preference(self):
        vm=self.setup_context(x=29.,z=12.)
        self.set_slot(vm,6,(),False,44.,4.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':2,'recipient':6}})
        self.assertEqual(self.estimate(vm,2)[1]&3,3)
        self.assertEqual(self.choose(vm),0)

    def test_clear_forward_reception_beyond_defensive_line_is_protected(self):
        vm=self.setup_context(x=29.,z=12.)
        self.set_slot(vm,self.receiver,(),False,35.,12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.estimate(vm,0)[1]&2,2)
        self.assertEqual(self.choose(vm),0)

    def test_large_opportunity_gap_keeps_native_choice_even_when_shot_estimate_is_higher(self):
        vm=self.setup_context(x=29.,z=12.)
        self.set_slot(vm,self.receiver,(),False,1.,10.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        a,af=self.estimate(vm,0);b,bf=self.estimate(vm,1)
        self.assertEqual((af&7,bf&7),(1,5));self.assertGreater(b-a,8.)
        self.assertEqual(self.choose(vm),0)

    def test_same_candidate_ranks_do_not_mean_same_opportunity(self):
        for receiver_x,expected in [(27.5,1),(1.,0)]:
            vm=self.setup_context(x=29.,z=12.)
            self.set_slot(vm,self.receiver,(),False,receiver_x,10.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}},[0,1])
            self.assertEqual(self.choose(vm),expected)

    def test_close_opportunity_can_be_later_in_list_without_rank_as_score(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':4}},[0,2,1])
        self.assertEqual(self.choose(vm),1)

    def test_shot_preparation_pressure_and_nearby_blocker_preserve_pass(self):
        for x,z in [(30.,12.),(34.,10.)]:
            vm=self.setup_context(x=29.,z=12.)
            self.set_slot(vm,11,(),False,x,z)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.estimate(vm,1)[1],0)
            self.assertEqual(self.choose(vm),0)

    def test_inward_dribble_with_blocked_path_is_not_promoted(self):
        vm=self.setup_context()
        self.set_slot(vm,11,(),False,29.8,15.2)
        self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135.}})
        self.assertEqual(self.estimate(vm,1)[1],0)
        self.assertEqual(self.choose(vm),0)

    def test_invalid_opponent_geometry_or_incomplete_team_keeps_native(self):
        for incomplete in [False,True]:
            vm=self.setup_context(x=29.,z=12.)
            if incomplete:
                for index in range(11,16):vm.mem_write(self.game+0x4202+index,b'\0')
            else:self.set_slot(vm,11,(),False,float('nan'),12.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.choose(vm),0)

    def test_inactive_or_unavailable_opponent_does_not_block_route(self):
        for field in [0x4202,0x4218]:
            vm=self.setup_context(x=29.,z=12.)
            self.set_slot(vm,11,(),False,30.,12.)
            vm.mem_write(self.game+field+11,b'\0'if field==0x4202 else b'\1')
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertEqual(self.choose(vm),1)

    def test_snapshot_and_unique_candidates_evaluated_once_without_reentering_native_actions(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}},[0,1,1,0])
        counts={'snapshot':0,'evaluate':0}
        watched={self.helpers['shared_studio_ai_opportunity_'+k]:k for k in counts}
        def observe(vm,address,size,data):
            if address in watched:counts[watched[address]]+=1
            self.assertNotIn(address,[0x70ea37c,0x7108a7c,0x71319ac,0x71328c8,0x68d83cc])
        vm.hook_add(self.u.UC_HOOK_CODE,observe)
        self.assertEqual(self.choose(vm),1)
        self.assertEqual(counts,{'snapshot':1,'evaluate':2})

    def test_estimates_do_not_leak_between_decisions(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.choose(vm),1)
        self.set_slot(vm,11,(),False,34.,10.)
        self.assertEqual(self.choose(vm),0)

    def test_equal_estimates_use_first_native_alternative_not_last(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':1}},[0,1,2])
        self.assertEqual(self.choose(vm),1)

    def test_decision_is_read_only_for_native_match_records(self):
        vm=self.setup_context(x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        regions=[(self.ai,0x6000),(self.game,0x5000),(self.model,0x10000),
                 (self.states,0x30000),(self.players,0x20000)]
        before=[bytes(vm.mem_read(p,n))for p,n in regions]
        self.assertEqual(self.choose(vm),1)
        self.assertEqual([bytes(vm.mem_read(p,n))for p,n in regions],before)

    def test_positional_scale_has_independently_computed_values(self):
        vm=self.setup_context();snapshot=0x4200a000;r=self.r
        self.assertEqual(self.run_helper(vm,'studio_ai_opportunity_snapshot',self.ctx,snapshot),1)
        for x,z,expected in [(40.,0.,80.),(52.5,0.,100.),(-52.5,0.,0.),(29.,12.,48.18152)]:
            for reg,v in [(r.UC_ARM64_REG_S0,x),(r.UC_ARM64_REG_S1,z)]:
                vm.reg_write(reg,struct.unpack('<I',struct.pack('<f',v))[0])
            self.run_helper(vm,'studio_ai_opportunity_position',snapshot)
            actual=struct.unpack('<f',struct.pack('<I',vm.reg_read(r.UC_ARM64_REG_S0)))[0]
            self.assertAlmostEqual(actual,expected,places=4)

    def test_segment_clearance_matches_known_geometry(self):
        vm=self.setup_context();snapshot=0x4200a000;r=self.r
        self.set_slot(vm,11,(),False,2.,3.)
        self.assertEqual(self.run_helper(vm,'studio_ai_opportunity_snapshot',self.ctx,snapshot),1)
        for n,v in enumerate([0.,0.,4.,0.]):
            vm.reg_write(getattr(r,'UC_ARM64_REG_S'+str(n)),struct.unpack('<I',struct.pack('<f',v))[0])
        self.run_helper(vm,'studio_ai_opportunity_clearance',snapshot)
        values=[struct.unpack('<f',struct.pack('<I',vm.reg_read(getattr(r,'UC_ARM64_REG_S'+str(n)))))[0]for n in range(3)]
        self.assertEqual(values,[9.,13.,13.])

    def test_shot_target_height_and_lateral_axes_are_checked_separately(self):
        for target,valid in [((52.5,1.,2.),True),((52.5,4.,1.),False),((52.5,1.,8.),False),
                             ((52.5,float('nan'),1.),False),((52.5,0.,float('inf')),False)]:
            vm=self.setup_context(x=29.,z=12.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1,'target':target}})
            self.assertEqual(bool(self.estimate(vm,1)[1]&1),valid)

    def test_already_chosen_blitz_shot_prefers_controlled_even_under_pressure(self):
        for x,z in [(30.,12.),(34.,10.)]:
            vm=self.setup_context(skills=(18,),x=29.,z=12.)
            self.set_slot(vm,11,(),False,x,z)
            output=0x42009000;data=struct.pack('<III3f',9,25,0,52.5,1.,0.)
            vm.mem_write(output,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',output,self.ctx)
            self.assertEqual(struct.unpack('<I',vm.mem_read(output+8,4))[0],1)
            self.assertEqual(bytes(vm.mem_read(output+12,12)),data[12:])

    def test_protected_reception_and_blocking_are_symmetric_across_halves(self):
        for side in [-1,1]:
            for z in [-12.,12.]:
                vm=self.setup_context(x=29.*side,z=z,side=side)
                self.set_slot(vm,self.receiver,(),False,44.*side,4.)
                self.candidates(vm,{0:{'kind':2},1:{'kind':1,'target':(52.5*side,0.,1.)}})
                self.assertEqual(self.estimate(vm,0)[1]&3,3)
                self.assertEqual(self.choose(vm),0)

    def test_blitz_is_eligible_centrally_without_incisive_run(self):
        for side in [-1,1]:
            vm=self.setup_context(skills=(18,),incisive=False,x=25.*side,z=0.,side=side)
            self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),3)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1,'target':(52.5*side,0.,0.)}})
            self.assertEqual(self.choose(vm),1)

    def test_lone_wolf_can_prefer_normal_long_shot_without_special_shooting_skills(self):
        vm=self.setup_context(skills=(),incisive=False,lone_wolf=True,x=29.,z=12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.run_helper(vm,'studio_ai_cut_in_profile',self.ctx),1)
        self.assertEqual(self.choose(vm),1)

    def test_lone_wolf_prioritises_ready_shot_over_protected_pass(self):
        vm=self.setup_context(skills=(18,),lone_wolf=True,x=29.,z=12.)
        self.set_slot(vm,self.receiver,(),False,44.,4.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
        self.assertEqual(self.estimate(vm,0)[1]&2,2)
        self.assertEqual(self.choose(vm),1)

    def test_lone_wolf_repositions_before_blitz_when_current_body_is_wrong(self):
        vm=self.setup_context(skills=(18,),incisive=False,lone_wolf=True,x=25.,z=0.,heading=240.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':3,'angle':75.}})
        self.assertFalse(self.estimate(vm,1)[1]&16)
        self.assertTrue(self.estimate(vm,2)[1]&16)
        self.assertEqual(self.choose(vm),2)

    def test_original_shot_can_yield_to_better_blitz_setup_for_lone_wolf(self):
        vm=self.setup_context(skills=(18,),incisive=False,lone_wolf=True,x=25.,z=0.,heading=240.)
        self.candidates(vm,{0:{'kind':1},1:{'kind':3,'angle':75.}})
        self.assertEqual(self.choose(vm),1)

    def test_strong_foot_changes_the_preferred_native_setup_route(self):
        for foot,z,inward in [(0,-12.,45.),(1,12.,135.)]:
            vm=self.setup_context(skills=(18,),lone_wolf=True,x=29.,z=z,foot=foot,heading=240.)
            self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':90.},2:{'kind':3,'angle':inward}})
            self.assertFalse(self.estimate(vm,1)[1]&16)
            self.assertTrue(self.estimate(vm,2)[1]&16)
            self.assertEqual(self.choose(vm),2)

    def test_lone_wolf_keeps_native_fallback_when_all_progress_routes_are_blocked(self):
        vm=self.setup_context(skills=(18,),lone_wolf=True,x=29.,z=12.,heading=240.)
        self.set_slot(vm,11,(),False,30.,12.)
        self.candidates(vm,{0:{'kind':2},1:{'kind':1},2:{'kind':3,'angle':90.}})
        self.assertEqual(self.choose(vm),0)

    def test_already_chosen_blitz_shot_prefers_controlled_at_any_heading(self):
        for heading,expected in [(90.,1),(240.,1)]:
            vm=self.setup_context(skills=(18,),lone_wolf=True,x=29.,z=12.,heading=heading)
            out=0x42009000;data=struct.pack('<III3f',9,25,0,52.5,1.,0.)
            vm.mem_write(out,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
            self.assertEqual(struct.unpack('<I',vm.mem_read(out+8,4))[0],expected)
            self.assertEqual(bytes(vm.mem_read(out+12,12)),data[12:24])

    def test_unknown_foot_or_heading_does_not_fake_blitz_readiness(self):
        for foot,heading in [(255,90.),(0,float('nan'))]:
            vm=self.setup_context(skills=(18,),lone_wolf=True,x=29.,z=12.,foot=foot,heading=heading)
            self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
            self.assertFalse(self.estimate(vm,1)[1]&16)
            self.assertEqual(self.choose(vm),0)

    def test_real_equal_draw_is_balanced_over_independent_inputs(self):
        vm=self.setup_context(x=29.,z=12.,fixed_class=None)
        snapshot=0x4200a000;self.assertEqual(self.run_helper(vm,'studio_ai_opportunity_snapshot',self.ctx,snapshot),1)
        counts={1:0,2:0,3:0}
        for key in range(1,1201):
            selected=self.run_helper(vm,'studio_ai_equal_action_draw',snapshot,14,0,0x42010000+key*16)
            counts[selected]+=1
        for count in counts.values():self.assertTrue(300<=count<=500,counts)

    def test_real_draw_holds_same_situation_and_separates_action_and_shot_domains(self):
        vm=self.setup_context(x=29.,z=12.,fixed_class=None)
        snapshot=0x4200a000;self.assertEqual(self.run_helper(vm,'studio_ai_opportunity_snapshot',self.ctx,snapshot),1)
        first=self.run_helper(vm,'studio_ai_equal_action_draw',snapshot,14,0,self.root)
        for _ in range(8):self.assertEqual(self.run_helper(vm,'studio_ai_equal_action_draw',snapshot,14,0,self.root),first)
        mode=self.run_helper(vm,'studio_ai_equal_action_draw',snapshot,6,1,self.root)
        self.assertIn(mode,(1,2))
        self.assertEqual(self.run_helper(vm,'studio_ai_equal_action_draw',snapshot,14,0,self.root),first)

    def test_extra_candidates_do_not_give_their_action_class_extra_tickets(self):
        kinds=[]
        for extra in [0,10]:
            vm=self.setup_context(x=29.,z=12.,fixed_class=None)
            rows={0:{'kind':2},1:{'kind':1},2:{'kind':3,'angle':100.}}
            rows.update({n:{'kind':1}for n in range(3,3+extra)})
            self.candidates(vm,rows)
            chosen=self.choose(vm)
            kinds.append(rows[chosen]['kind'])
        self.assertEqual(kinds[0],kinds[1])

    def test_blitz_only_shooter_always_prefers_controlled_after_shot_is_chosen(self):
        vm=self.setup_context(skills=(18,),x=29.,z=12.,fixed_class=None)
        out=0x42009000;counts={0:0,1:0}
        for key in range(100):
            vm.mem_write(self.ctx+0x18,struct.pack('<Q',self.root+key*16))
            vm.mem_write(out,struct.pack('<III3f',9,25,0,52.5,1.,0.))
            self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
            counts[struct.unpack('<I',vm.mem_read(out+8,4))[0]]+=1
        self.assertEqual(counts,{0:0,1:100})

    def test_skill_shot_styles_have_equal_tickets_and_preserve_native_target(self):
        for skills,allowed in [((18,),{1}),((24,),{0}),((25,),{3}),((18,24),{0,1}),((18,24,25),{0,1,3})]:
            vm=self.setup_context(skills=skills,incisive=False,x=25.,z=3.,fixed_class=None)
            counts={n:0 for n in allowed};out=0x42009000
            for key in range(600):
                vm.mem_write(self.ctx+0x18,struct.pack('<Q',self.root+key*16))
                data=struct.pack('<III3f',9,25,0,52.5,1.,0.);vm.mem_write(out,data)
                self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
                kind=struct.unpack('<I',vm.mem_read(out+8,4))[0];self.assertIn(kind,allowed);counts[kind]+=1
                self.assertEqual(bytes(vm.mem_read(out+12,12)),data[12:])
            expected=600/len(allowed)
            for count in counts.values():self.assertTrue(expected*.75<=count<=expected*1.25,(skills,counts))

    def test_unrelated_player_outside_pitch_does_not_veto_any_owned_shot_style(self):
        for skills,expected in [((18,),1),((24,),0),((25,),3),((18,24,25),1)]:
            vm=self.setup_context(skills=skills,incisive=False,lone_wolf=True)
            vm.mem_write(self.players+2*0x1000+0x4f4,struct.pack('<3f',0.,0.,34.1))
            # This invalidates opportunity comparison, but must not invalidate
            # a style choice for a shot the native CPU has ALREADY chosen.
            out=0x42009000;data=struct.pack('<III3f',9,25,2,52.5,1.,0.);vm.mem_write(out,data)
            self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
            self.assertEqual(struct.unpack('<I',vm.mem_read(out+8,4))[0],expected)
            self.assertEqual(bytes(vm.mem_read(out+12,12)),data[12:])

    def power_fixture(self,subtype=0,skills=(51,58,74),distance=20.,patched=True,phase_value=1):
        """Run the WHOLE native behavior 25; only world/scene inputs stubbed."""
        r=self.r;control,info,model=0x42000000,0x42010000,0x43000000
        phase,pitch,team,player,ball,ai,action,rng=[0x42011000+n*0x1000 for n in range(8)]
        state,actor=0x44000000,0x45000000;self.power_clock=100
        def ret(value):return lambda vm:vm.reg_write(r.UC_ARM64_REG_X0,value)
        def scalar(value):return lambda vm:vm.reg_write(r.UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',value))[0])
        def pair(vm):vm.reg_write(r.UC_ARM64_REG_X0,0);vm.reg_write(r.UC_ARM64_REG_W1,0)
        stubs={0x697d0f8:ret(0),0x72c3e80:ret(phase),0x72c3e6c:ret(pitch),
               0x72c3ddc:ret(model),0x72c3de0:ret(ball),0x72c4028:ret(team),
               0x72c408c:ret(player),0x72c3e44:ret(ai),0x72d7dc8:ret(action),
               0x72e3ad4:ret(0),0x697b60c:ret(phase_value),0x72d847c:ret(ball+0x18),
               0x6ad2f60:scalar(90.),0x72c3fbc:ret(0),0x72c3fe4:ret(ai),
               0x72fae2c:ret(0),0x731c5d0:pair,0x730b294:scalar(1.),
               0x72c3f10:ret(rng),0x734317c:ret(0),0x72c40b0:ret(state),
               0x72c1a14:ret(player),0x72c19f8:ret(actor),0x698f7e0:ret(model),0x6a4bd08:lambda vm:vm.reg_write(r.UC_ARM64_REG_W0,self.power_clock)}
        vm=self.machine(stubs);vm.mem_map(control,0x30000);vm.mem_map(model,0x30000)
        vm.mem_map(state,0x10000);vm.mem_map(actor,0x10000)
        vm.mem_write(info+4,struct.pack('<I',7));vm.mem_write(info+0x30,struct.pack('<Q',model))
        vm.mem_write(team+0x28c,b'\1');vm.mem_write(action+4,struct.pack('<II3f',25,subtype,52.5,0.,1.))
        vm.mem_write(rng,struct.pack('<I',1));vm.mem_write(model+0x228e8,struct.pack('<f',distance))
        vm.mem_write(state+0x394+0xc0,sum(1<<n for n in skills).to_bytes(12,'little'))
        vm.mem_write(actor+0x2a38,b'\7');vm.mem_write(actor+0x4620,struct.pack('<Q',model))
        self.helpers=self.install_all(vm)if patched else {}
        if patched:
            # The power stage consumes the selected request-stage ticket.
            # Different native shot modes cannot grant a different skill's ticket.
            style={0:2,1:1,3:3}.get(subtype,0)
            for n,v in enumerate((model,7,1,style,100)):
                vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),v)
            vm.reg_write(r.UC_ARM64_REG_X30,0x2003f000)
            vm.emu_start(self.helpers['shared_studio_ai_style_ticket'],0x2003f000,count=10000)
        self.power_addresses=dict(control=control,info=info,model=model,phase=phase,state=state,actor=actor,action=action)
        return vm

    def native_power(self,vm):
        r=self.r;a=self.power_addresses
        for reg,value in [(r.UC_ARM64_REG_X0,0),(r.UC_ARM64_REG_X1,a['info']),(r.UC_ARM64_REG_X2,a['control']),
                          (r.UC_ARM64_REG_X30,0x2003f000)]:vm.reg_write(reg,value)
        vm.emu_start(0x71a27f0,0x2003f000,count=50000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),0x2003f000)
        return bytes(vm.mem_read(a['control'],0x1100)),vm.reg_read(r.UC_ARM64_REG_X0),vm.reg_read(r.UC_ARM64_REG_Q0)

    def test_whole_native_power_handler_preserves_every_other_control_field_and_return(self):
        for distance in (10.,20.,30.):
            for subtype in range(6):
                before,return0,q0=self.native_power(self.power_fixture(subtype,distance=distance,patched=False))
                after,return1,q1=self.native_power(self.power_fixture(subtype,distance=distance))
                self.assertEqual(before[:0xe7c],after[:0xe7c]);self.assertEqual(before[0xe80:],after[0xe80:])
                self.assertEqual((return0,q0),(return1,q1))
                base=struct.unpack_from('<f',before,0xe7c)[0];value=struct.unpack_from('<f',after,0xe7c)[0]
                expected=min(base,.49)if subtype==0 else max(base,.55)if subtype==1 else (.65 if base<=.5 else base)if subtype==3 else base
                self.assertAlmostEqual(value,expected,places=6,msg=(distance,subtype))

    def test_original_engine_subtype_dispatch_separates_chip_and_stunning(self):
        # Execute the complete UNPATCHED behavior-25 handler. Its low rodata
        # switch table is at file 0xc8fa46 (NOT text VA minus 0x4000).
        self.assertEqual(list(self.engine[0xc8fa46:0xc8fa4b]),[0,142,46,0,0])
        expected={0:(0,False),1:(2,False),2:(3,False),3:(0,True),4:(1,False)}
        for subtype,want in expected.items():
            control,_,_=self.native_power(self.power_fixture(subtype,patched=False))
            word=struct.unpack_from('<I',control,0xff8)[0]
            self.assertEqual(((word>>16)&255,bool(word&(1<<26))),want)

    def test_heavy_preserves_native_type_inside_box_and_requests_stunning_only_outside(self):
        for x,z,outside in [(45.,3.,False),(36.,20.16,False),(35.9,3.,True),(45.,20.3,True),(-45.,3.,False)]:
            vm=self.setup_context(skills=(25,),incisive=False,x=x,z=z)
            for original in (0,1,2,4):
                out=0x42009000;data=struct.pack('<III3f',9,25,original,52.5,1.,0.)
                vm.mem_write(out,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
                self.assertEqual(struct.unpack('<I',vm.mem_read(out+8,4))[0],3 if outside else original,(x,z,original))
                self.assertEqual(bytes(vm.mem_read(out+12,12)),data[12:])

    def test_heavy_lifts_only_original_power_at_or_below_half_to_65_percent(self):
        for subtype in (0,1,2,3,4):
            for power in (.3,.499,.5,.501,.55,.8):
                vm=self.power_fixture(subtype);a=self.power_addresses
                self.run_helper(vm,'studio_ai_style_ticket',a['model'],7,1,3,100)
                vm.mem_write(a['control']+0xe7c,struct.pack('<f',power))
                vm.mem_write(a['control']+0xff8,struct.pack('<I',0x12345678))
                self.run_helper(vm,'studio_ai_bound_shot_power',a['info'],a['control'])
                value=struct.unpack('<f',vm.mem_read(a['control']+0xe7c,4))[0]
                self.assertAlmostEqual(value,.65 if power<=.5 else power,places=6)
                self.assertEqual(bytes(vm.mem_read(a['control']+0xff8,4)),struct.pack('<I',0x12345678))

    def test_probability_rejection_preserves_request_type_and_does_not_leave_a_style_ticket(self):
        vm=self.setup_context(skills=(18,24,25),probability=False)
        out=0x42009000;data=struct.pack('<III3f',9,25,2,52.5,1.,0.)
        vm.mem_write(out,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
        self.assertEqual(bytes(vm.mem_read(out,len(data))),data)
        self.assertEqual(self.run_helper(vm,'studio_ai_style_ticket',self.model,7,0,0,0),0)
        self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135.}})
        self.assertEqual(self.choose(vm),0)

    def test_actual_probability_is_stable_within_a_decision_and_about_80_percent(self):
        vm=self.setup_context(probability=None);r=self.r;clock=[0]
        def tick(vm,address,size,data):
            if address==0x6a4bd08:
                vm.reg_write(r.UC_ARM64_REG_W0,clock[0]);vm.reg_write(r.UC_ARM64_REG_PC,vm.reg_read(r.UC_ARM64_REG_X30))
        vm.hook_add(self.u.UC_HOOK_CODE,tick)
        counts=[]
        for domain in (0,1):
            passed=0
            for n in range(2000):
                clock[0]=n*30;value=self.run_helper(vm,'studio_ai_probability_gate',self.ctx,domain)
                self.assertEqual(value,self.run_helper(vm,'studio_ai_probability_gate',self.ctx,domain))
                passed+=value
            counts.append(passed);self.assertTrue(1500<passed<1700,passed)
        self.assertNotEqual(counts[0],counts[1])

    def test_incisive_and_lone_wolf_candidate_changes_are_restricted_to_attacking_third(self):
        for side,slot in ((1,7),(-1,18)):
            for wolf in (False,True):
                vm=self.setup_context(x=17.4*side,z=18.,side=side,index=slot,lone_wolf=wolf)
                self.candidates(vm,{0:{'kind':2},1:{'kind':3,'angle':135. if side==1 else 225.}})
                self.assertEqual(self.choose(vm),0)

    def test_legacy_curler_request_also_keeps_native_type_before_attacking_third(self):
        vm=self.setup_context(skills=(17,),lone_wolf=True,x=17.4,z=12.)
        out=0x42009000;data=struct.pack('<III3f',9,25,0,52.5,1.,0.)
        vm.mem_write(out,data);self.run_helper(vm,'studio_ai_prefer_curled_shot',out,self.ctx)
        self.assertEqual(bytes(vm.mem_read(out,len(data))),data)

    def test_power_preference_is_disabled_without_skill_or_during_set_piece(self):
        for skills,phase in [((),1),((51,58,74),0)]:
            for subtype in (0,1,2,3):
                before=self.native_power(self.power_fixture(subtype,skills,distance=10.,patched=False,phase_value=phase))
                after=self.native_power(self.power_fixture(subtype,skills,distance=10.,phase_value=phase))
                self.assertEqual(before,after)

    def test_low_and_blitz_permission_uses_current_actor_and_expires_after_two_ticks(self):
        vm=self.power_fixture();self.native_power(vm);a=self.power_addresses
        self.assertEqual(self.run_helper(vm,'studio_ai_allow_low_with_blitz',a['actor']),1)
        self.power_clock+=2;self.assertEqual(self.run_helper(vm,'studio_ai_allow_low_with_blitz',a['actor']),1)
        self.power_clock+=1;self.assertEqual(self.run_helper(vm,'studio_ai_allow_low_with_blitz',a['actor']),0)
        self.power_clock=100
        vm.mem_write(a['actor']+0x4620,struct.pack('<Q',a['model']+16))
        self.assertEqual(self.run_helper(vm,'studio_ai_allow_low_with_blitz',a['actor']),1)
        vm.mem_write(a['actor']+0x4620,struct.pack('<Q',a['model']))
        vm.mem_write(a['actor']+0x2a38,b'\10')
        self.assertEqual(self.run_helper(vm,'studio_ai_allow_low_with_blitz',a['actor']),0)

    def test_native_blitz_exclusion_is_bypassed_only_for_just_produced_cpu_low_shot(self):
        for subtype,expected in [(0,0x6d62874),(1,0x6d628e0),(2,0x6d628e0)]:
            vm=self.power_fixture(subtype);self.native_power(vm);r=self.r;a=self.power_addresses
            fp=0x40007000;vm.reg_write(r.UC_ARM64_REG_X29,fp);vm.mem_write(fp-0x18,struct.pack('<Q',a['actor']))
            vm.reg_write(r.UC_ARM64_REG_W0,1);vm.reg_write(r.UC_ARM64_REG_X30,0x2003f000)
            visited=[]
            def stop(vm,pc,size,data):
                if pc in (0x6d62874,0x6d628e0):visited.append(pc);vm.emu_stop()
            vm.hook_add(self.u.UC_HOOK_CODE,stop)
            vm.emu_start(0x6d62870,0x2003f000,count=10000)
            self.assertEqual(visited,[expected])

    def test_disabling_ordinary_comparison_does_not_disable_explicit_lone_wolf(self):
        original=self.candidate
        try:
            candidate=copy.deepcopy(original);bundle=candidate['bundles'][0]
            raw=bytearray.fromhex(bundle['body_hex'])
            struct.pack_into('<I',raw,candidate['ordinary_switch_offset'],0)
            bundle['body_hex']=raw.hex();self.candidate=candidate
            for wolf,expected in [(False,0),(True,1)]:
                vm=self.setup_context(skills=(18,),lone_wolf=wolf,x=29.,z=12.)
                self.candidates(vm,{0:{'kind':2},1:{'kind':1}})
                self.assertEqual(self.choose(vm),expected)
        finally:self.candidate=original

    def test_loader_writes_only_the_explicit_ordinary_switch(self):
        from native_ai_cut_in_shots import hooks
        a=bytes.fromhex(hooks(io.BytesIO(self.engine),True)[0]['body_hex'])
        b=bytes.fromhex(hooks(io.BytesIO(self.engine),False)[0]['body_hex'])
        offset=self.candidate['ordinary_switch_offset']
        self.assertEqual(a[:offset],b[:offset]);self.assertEqual(a[offset+4:],b[offset+4:])
        self.assertEqual((struct.unpack_from('<I',a,offset)[0],struct.unpack_from('<I',b,offset)[0]),(1,0))


class AiCutInIntegrationTests(unittest.TestCase):
    def test_old_settings_gain_switch_and_can_disable_it(self):
        from game_settings import normalize
        self.assertTrue(normalize({})['ai_cut_in_shots']['enabled'])
        self.assertFalse(normalize({'ai_cut_in_shots':{'enabled':False}})['ai_cut_in_shots']['enabled'])
        with self.assertRaises(ValueError):normalize({'ai_cut_in_shots':{'enabled':'yes'}})

    def test_bundled_resource_and_engine_guard(self):
        import native_ai_cut_in_shots as module
        resource=SOURCE/'resources/native-ai-cut-in-shots.json'
        if not resource.is_file():self.skipTest('candidate resource not promoted yet')
        data=json.loads(resource.read_text('utf8'));self.assertEqual(data['revision'],module.REVISION)
        self.assertTrue(data['experimental']);self.assertEqual(len(data['hooks']),4)
        with self.assertRaisesRegex(ValueError,'接口不同'):module.hooks(io.BytesIO(b'not an engine'))


if __name__=='__main__':unittest.main()
