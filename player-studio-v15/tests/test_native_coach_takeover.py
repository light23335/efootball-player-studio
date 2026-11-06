"""Compiled lease/state machine + original V17 native queue entry instructions.

Only root services, metadata aptitude and queue VECTOR primitives are fixtures.
Actual can_queue, queue_sub, roster identity, budget checks and field reads run.
"""
import copy,json,struct,unittest
from pathlib import Path
from ai_match_channel import read_snapshot,encode_command,publish
import test_tournament_difficulty_native as native
import unicorn.arm64_const as REG


class QueueVM(native.VM):
    def __init__(self):
        super().__init__()
        self.queues={native.SELF+0x20:[],native.TEAM+0xa8:[]};self.erased=[]
        self.stubs.update({0x68fbf34:lambda:len(self.queues.get(self.reg(0),[])),
            0x72eb25c:self.add,0x72eb08c:self.row,0x72eb3b4:self.remove,
            0x68fbea0:lambda:native.DATA+0x160000,0x72b3658:lambda:2,
            0x72eb1d8:self.contains,0x72eb0ec:lambda:0,
            0x72eb390:self.begin,0x72eb398:self.end,0x72eb3ac:self.erase_pointer})
        self.u32(native.BUS+native.layout['auto_execute'],1)
        self.u32(native.BUS+native.layout['heartbeat'],1)
        self.observe()
        self.spec={'game_id':789,'entry_id':'round-A','profiles':[{'id':'probe','attack':[0]+[5]*10,
            'defence':[0]+[5]*10,'attack_coords':[[24,0]]+[[10+i*2,50]for i in range(10)],
            'defence_coords':[[24,0]]+[[10+i*2,40]for i in range(10)]}]}
    def add(self):
        self.queues[self.reg(0)].append([self.reg(1),self.reg(3),self.reg(2)])
        self.queued.append([self.reg(i)for i in range(4)]);return 1
    def contains(self):
        return int(any(self.reg(1)in r[1:]for r in self.queues.get(self.reg(0),[])))
    def row(self):
        rows=self.queues.get(self.reg(0),[]);i=self.reg(1)
        if i>=len(rows):return 0
        at=native.DATA+0x180000+(0 if self.reg(0)==native.SELF+0x20 else 128)+i*12
        self.uc.mem_write(at,struct.pack('<III',*rows[i]));return at
    def remove(self):
        queue,index=self.reg(0),self.reg(1);self.erased.append([queue,index])
        self.queues[queue]=[r for r in self.queues[queue]if index not in r[1:]]
        return 0
    def begin(self):
        queue=self.reg(0);base=native.DATA+0x180000+(0 if queue==native.SELF+0x20 else 128)
        for i,row in enumerate(self.queues.get(queue,[])):self.uc.mem_write(base+i*12,struct.pack('<III',*row))
        return base
    def end(self):
        queue=self.reg(0)
        return native.DATA+0x180000+(0 if queue==native.SELF+0x20 else 128)+12*len(self.queues.get(queue,[]))
    def erase_pointer(self):
        queue,pointer=self.reg(0),self.reg(1)
        base=native.DATA+0x180000+(0 if queue==native.SELF+0x20 else 128)
        i=(pointer-base)//12;self.erased.append([queue,'exact_index',i])
        self.queues[queue].pop(i)
        return base+i*12
    def observe(self):return self.call(native.EXT+native.bundle['helper_entries']['studio_observe'],native.SELF,native.EVENT,1)
    def tick(self):return self.call(native.EXT+native.bundle['helper_entries']['studio_queue_tick'],native.SELF)
    def reconcile(self):return self.call(native.EXT+native.bundle['helper_entries']['studio_queue_reconcile'],native.SELF)
    def managed(self):return self.call(native.EXT+native.bundle['helper_entries']['studio_managed'],native.SELF)
    def fence(self):self.call(native.EXT+native.bundle['helper_entries']['studio_fence'])
    def snapshot(self):
        s=read_snapshot(lambda a,n:bytes(self.uc.mem_read(native.BUS+a,n)),native.layout,self.fence)
        s['entry_id']='round-A';return s
    def proposal(self,batch=2):
        incoming=[12,13][:batch];outgoing=[7,8][:batch]
        mapping={i:i for i in range(11)}
        for a,b in zip(incoming,outgoing):mapping[b]=a
        return dict(id=1,game_id=789,entry_id='round-A',kind='substitution',active_count=11,
            score=[2,1],attack_level=2,profile_id='probe',mapping=mapping,incoming=incoming,
            outgoing=outgoing,pairs=list(zip(incoming,outgoing)))
    def send(self,p=None,seq=2,epoch=456):
        raw=encode_command(native.layout,self.spec,self.snapshot(),p or self.proposal(),seq,epoch)
        publish(lambda a,b:self.uc.mem_write(native.BUS+a,b),native.layout['command'],raw,self.fence)
    def ack(self):
        return (struct.unpack('<Q',self.uc.mem_read(native.BUS+native.layout['ack_id'],8))[0],
                self.read32(native.BUS+native.layout['ack_status']),
                self.read32(native.BUS+native.layout['rejection_reason']))
    def set_clock(self,minute,heartbeat=True):
        self.u32(native.INFO+0x3320,struct.unpack('<I',struct.pack('<f',minute*3600.))[0]^native.KEY)
        if heartbeat:
            at=native.BUS+native.layout['heartbeat'];self.u32(at,self.read32(at)+1)
        self.observe()
    def phase(self,value):self.u32(native.INFO+0x3314,value);self.observe()
    def swap(self,a,b):
        self.u32(native.PLAYERS+4+a*4,b);self.u32(native.PLAYERS+4+b*4,a)


class NativeTakeoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[2]
        native.raw=(root/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
        native.bundle=json.loads((root/'player-studio-v15/resources/native-ai-match-adapter.json').read_text('utf8'))
        native.layout=native.bundle['channel_schema']
        global PLAN_RAW
        PLAN_RAW=native.raw

    def test_normal_selector_is_owned_without_any_pending_substitution(self):
        v=QueueVM();self.assertEqual(v.managed(),1)
        self.assertEqual(v.read32(native.BUS+native.layout['ownership_state']),1)
        self.assertEqual(v.queued,[])
        v.queues[native.SELF+0x20]=[[3,6,17]]
        self.assertEqual(v.managed(),1)
        self.assertEqual(v.read32(native.BUS+native.layout['ownership_state']),2)
        self.assertEqual(v.queues[native.SELF+0x20],[[3,6,17]])

    def test_batch_waits_more_than_three_minutes_and_queues_only_in_pre_event_window(self):
        v=QueueVM();v.phase(1);v.send();self.assertEqual(v.tick(),0)
        self.assertEqual(v.ack(),(1,7,0));self.assertEqual(v.queued,[])
        for minute in (64,68,75):
            v.set_clock(minute);self.assertEqual(v.tick(),0);self.assertEqual(v.ack(),(1,7,0))
            self.assertEqual(v.managed(),1)
        v.phase(2);v.reconcile();self.assertEqual(v.queued,[])
        self.assertEqual(v.tick(),1)
        self.assertEqual(v.queues[native.SELF+0x20],[[3,7,12],[3,8,13]])
        self.assertEqual(v.read32(native.BUS+native.layout['ownership_state']),4)
        self.assertEqual(v.snapshot()['windows_left'],3)
        v.swap(7,12);v.swap(8,13);v.observe();v.reconcile()
        self.assertEqual(v.ack(),(1,2,0));self.assertEqual(v.managed(),1)

    def test_disabled_identity_loss_or_dead_worker_cleans_only_owned_normal_pairs(self):
        for failure in ('disabled','bad_identity','worker_dead','bad_state'):
            with self.subTest(failure=failure):
                v=QueueVM();v.send();self.assertEqual(v.tick(),1)
                v.queues[native.TEAM+0xa8]=[[3,7,12],[3,8,13],[2,6,18]]
                # Original emergency supersedes one of our pairs.
                v.queues[native.SELF+0x20][0]=[2,7,12]
                if failure=='disabled':v.u32(native.BUS+native.layout['auto_execute'],0)
                elif failure=='bad_state':v.u32(native.BUS+native.layout['state_healthy'],0)
                elif failure=='bad_identity':v.u32(native.PLAYERS+0xa8+0x30,17)
                else:v.wall_seconds+=3;v.set_clock(61,heartbeat=False)
                self.assertEqual(v.managed(),0);v.tick()
                self.assertEqual(v.queues[native.SELF+0x20],[[2,7,12]])
                self.assertEqual(v.queues[native.TEAM+0xa8],[[2,6,18]])

    def test_period_transition_cancels_unexecuted_batch_without_rolling_back_completed_member(self):
        v=QueueVM();v.send();self.assertEqual(v.tick(),1)
        v.swap(7,12);v.u32(native.INFO+0x3310,2);v.set_clock(0)
        v.reconcile()
        self.assertEqual(v.queues[native.SELF+0x20],[])
        self.assertEqual(v.read32(native.PLAYERS+4+7*4),12)
        self.assertEqual(v.ack()[1:],(4,40))

    def test_waiting_batch_context_change_never_mutates_queue(self):
        v=QueueVM();v.phase(1);v.send();v.tick()
        v.u32(native.INFO+0x3310,2);v.set_clock(0);v.tick()
        self.assertEqual(v.ack()[1:],(4,40));self.assertEqual(v.queued,[])

    def test_period_clock_reset_before_next_worker_heartbeat_is_not_classified_as_dead_worker(self):
        v=QueueVM();v.phase(1);v.send();v.tick()
        v.u32(native.INFO+0x3310,2);v.set_clock(0,heartbeat=False);v.tick()
        self.assertEqual(v.ack()[1:],(4,40))
        self.assertEqual(v.read32(native.BUS+native.layout['ownership_reason']),40)
        self.assertEqual(v.queued,[])

    def test_transition_keeps_waiting_and_queued_batches_without_new_mutations(self):
        for queued in (False,True):
            v=QueueVM();v.phase(2 if queued else 1);v.send();v.tick()
            before=copy.deepcopy(v.queues);ack=v.ack()
            for turn in range(6):
                v.wall_seconds+=1;v.set_clock(60+turn,heartbeat=True);v.phase(3)
                self.assertEqual(v.managed(),1);v.tick();v.reconcile()
                self.assertEqual(v.queues,before);self.assertEqual(v.ack(),ack)
            v.phase(2);v.tick()
            self.assertEqual(v.ack(),(1,1,0))
            v.swap(7,12);v.observe();v.reconcile()
            v.swap(8,13);v.observe();v.reconcile()
            self.assertEqual(v.ack(),(1,2,0))

    def test_real_worker_death_during_frozen_transition_clock_releases_owned_rows(self):
        v=QueueVM();v.send();v.tick();v.phase(3);self.assertEqual(v.managed(),1)
        v.wall_seconds+=3
        self.assertEqual(v.managed(),0);self.assertEqual(v.queues[native.SELF+0x20],[])
        self.assertEqual(v.read32(native.BUS+native.layout['ownership_reason']),3)

    def test_missing_native_info_or_unknown_phase_releases_without_accessing_null(self):
        for missing in (True,False):
            v=QueueVM();v.send();v.tick()
            if missing:v.stubs[0x72c3e80]=lambda:0
            else:v.phase(99)
            self.assertEqual(v.managed(),0)
            self.assertEqual(v.queues[native.SELF+0x20],[])
            self.assertEqual(v.read32(native.BUS+native.layout['ownership_reason']),2 if missing else 43)

    def test_committed_native_shape_stays_owned_through_transition_then_resumes(self):
        v=PlanVM();shape=v.formation();v.send(shape);self.assertEqual(v.apply(),1)
        actual=bytes(v.uc.mem_read(native.TEAM+0x8078,0xe6c))
        for second in range(1,7):
            v.wall_seconds=1+second
            v.u32(native.BUS+native.layout['heartbeat'],1+second);v.phase(3)
            self.assertEqual(v.managed(),1);self.assertEqual(v.apply(),0)
            self.assertEqual(bytes(v.uc.mem_read(native.TEAM+0x8078,0xe6c)),actual)
        v.phase(1);self.assertEqual(v.apply(),0);self.assertEqual(v.managed(),1)
        self.assertEqual(bytes(v.uc.mem_read(native.TEAM+0x8078,0xe6c)),actual)

    def test_python_shape_readback_matches_original_native_roles_grids_and_identity_mapping(self):
        from ai_match_state import decode_match
        from ai_match_manager import Manager
        v=PlanVM();shape=v.formation();v.send(shape);self.assertEqual(v.apply(),1);v.observe()
        spec=dict(v.spec,players=[{}for _ in range(23)],base_profile=v.spec['profiles'][0])
        raw=v.snapshot();state=decode_match(spec,raw)
        self.assertIsNotNone(state)
        expected=Manager(spec).expected_shape(spec['base_profile'],shape['mapping'])
        self.assertEqual(state['actual_shape'],expected)

    def test_original_emergency_actor_transitions_release_and_restore_ordinary_ownership(self):
        for kind in ('injury','red','goalkeeper'):
            with self.subTest(kind=kind):
                v=QueueVM();v.send();v.tick()
                slot=0 if kind=='goalkeeper'else 4
                entry=native.PLAYERS+0xa8+slot*0x198
                if kind=='red':v.uc.mem_write(entry,bytes((0,1)))
                else:v.u32(entry+0x18,1)
                self.assertEqual(v.managed(),0)
                self.assertEqual(v.queues[native.SELF+0x20],[])
                v.uc.mem_write(entry,bytes(2));v.u32(entry+0x18,0)
                v.u32(native.BUS+native.layout['heartbeat'],2);v.observe()
                self.assertEqual(v.managed(),1)

    def test_same_actor_emergency_is_preserved_by_exact_row_erase(self):
        v=QueueVM();v.send();v.tick()
        v.queues[native.SELF+0x20].append([2,7,12])
        v.queues[native.TEAM+0xa8]=[[3,7,12],[2,6,13],[3,8,13]]
        v.u32(native.BUS+native.layout['state_healthy'],0);v.tick()
        self.assertEqual(v.queues[native.SELF+0x20],[[2,7,12]])
        self.assertEqual(v.queues[native.TEAM+0xa8],[[2,6,13]])
        self.assertIn(0x72eb3ac,v.calls)

    def test_existing_native_queue_drains_before_our_batch_and_changed_roster_requires_replan(self):
        v=QueueVM();v.queues[native.SELF+0x20]=[[3,6,17]]
        v.send();v.tick()
        self.assertEqual(v.ack(),(1,7,18));self.assertEqual(v.queued,[])
        self.assertEqual(v.managed(),1);self.assertEqual(v.erased,[])
        v.swap(6,17);v.queues[native.SELF+0x20]=[];v.observe();v.tick()
        self.assertEqual(v.ack()[1:],(4,4));self.assertEqual(v.queued,[])
        self.assertEqual(v.managed(),0)
        # A fresh worker read of the ACTUAL native entrant re-establishes the lease.
        v.u32(native.BUS+native.layout['state_field_mask'],((1<<11)-1)&~(1<<6)|(1<<17))
        self.assertEqual(v.managed(),1)

    def test_two_completed_members_use_two_substitutions_but_one_original_window_counter(self):
        # Completed member notifications are fixtures, as are live roster
        # swaps elsewhere in this suite. BOTH budget decrement functions and
        # the original end-of-batch window decision execute native V17 code.
        import unicorn.arm64_const as R
        for batch in (1,2):
            for period,charged in ((1,True),(2,False),(3,True),(4,False),(5,True),(6,False),(7,True)):
                with self.subTest(batch=batch,period=period):
                    v=QueueVM();v.send(v.proposal(batch));self.assertEqual(v.tick(),1)
                    v.stubs[0x72c3f48]=lambda:0  # No unlimited-substitution exhibition override.
                    for _ in range(batch):v.call(0x6ce2ce4,native.SELF)
                    self.assertEqual(v.uc.mem_read(native.TEAM+0xa5,1),bytes((5-batch,)))
                    v.u32(native.INFO+0x3310,period)
                    v.uc.reg_write(R.UC_ARM64_REG_X19,native.SELF)
                    v.uc.reg_write(R.UC_ARM64_REG_X21,1)  # At least one completed member in THIS batch.
                    v.uc.emu_start(0x6ce3d48,0x6ce3da8,count=1000)
                    self.assertEqual(v.uc.mem_read(native.TEAM+0xa6,1),bytes((2 if charged else 3,)))

    def test_actual_wrapper_enqueues_both_members_before_original_event_dispatch(self):
        import unicorn
        v=QueueVM();v.send();seen=[]
        def stop_at_original(u,address,size,_):
            if address==native.bundle['address']+4:
                seen.extend(copy.deepcopy(v.queues[native.SELF+0x20]));u.emu_stop()
        v.uc.hook_add(unicorn.UC_HOOK_CODE,stop_at_original)
        v.call(native.EXT+native.bundle['entry_offset'],native.SELF,native.EVENT)
        self.assertEqual(seen,[[3,7,12],[3,8,13]])

    def test_new_match_reusing_objects_never_erases_foreign_queue_or_receives_old_ack(self):
        v=QueueVM();v.send();v.tick()
        v.queues[native.SELF+0x20]=[[3,7,12],[2,6,18]]
        v.u64(native.BUS+native.layout['game_id'],790);v.u64(native.BUS+native.layout['epoch'],457)
        v.u64(native.BUS+native.layout['ack_id'],0)
        v.u32(native.BUS+native.layout['state_healthy'],0);v.observe();v.tick()
        self.assertEqual(v.queues[native.SELF+0x20],[[3,7,12],[2,6,18]])
        self.assertEqual(v.ack()[0],0);self.assertEqual(v.erased,[])

    def test_formation_then_waiting_substitution_never_opens_native_normal_selector_gap(self):
        v=PlanVM();shape=v.formation();v.send(shape)
        self.assertEqual(v.managed(),1)
        self.assertEqual(v.apply(),1);self.assertEqual(v.ack(),(1,2,0))
        self.assertEqual(v.managed(),1)
        v.phase(1);sub=v.proposal();sub.update(id=2);v.send(sub,seq=4);v.tick()
        self.assertEqual(v.ack(),(2,7,0));self.assertEqual(v.managed(),1)
        for minute in (64,70):
            v.set_clock(minute);v.tick();self.assertEqual(v.managed(),1)
        v.phase(2);v.tick();self.assertEqual(v.ack(),(2,1,0))
        v.swap(7,12);v.swap(8,13);v.observe();v.reconcile()
        self.assertEqual(v.ack(),(2,2,0));self.assertEqual(v.managed(),1)
        self.assertEqual(v.apply(),0)  # Current shape stays workshop-owned during cleanup.

    def test_confirmed_reduced_lineup_recovers_actual_native_shape_without_restoring_red_player(self):
        for count in (7,8,9,10):
            v=PlanVM();gone=list(range(count,11))
            for i in gone:
                entry=native.PLAYERS+0xa8+i*0x198
                v.uc.mem_write(entry+1,b'\1')
                v.uc.mem_write(native.INFO+0x4202+11+i,b'\0')
            v.observe();p=v.formation();p.update(active_count=count)
            v.u32(native.BUS+native.layout['state_field_mask'],(1<<count)-1)
            p['mapping']={s:i for s,i in p['mapping'].items()if i not in gone}
            p['duties']={'captain':0,'set_piece_taker':[0]*6,'df_overlap_setplay':[0]*3}
            v.send(p);self.assertEqual(v.apply(),1);self.assertEqual(v.ack(),(1,2,0))
            self.assertEqual(v.managed(),1)

    def test_healthy_deliberate_hold_owns_original_formation_and_attack_callbacks(self):
        v=PlanVM();before=bytes(v.uc.mem_read(native.TEAM+0x8078,0xe6c))
        self.assertEqual(v.apply(),0)
        self.assertEqual(v.call(native.EXT+native.bundle['helper_entries']['studio_attack_tick'],v.CONTEXT)&0xffffffff,0)
        self.assertEqual(bytes(v.uc.mem_read(native.TEAM+0x8078,0xe6c)),before)
        v.u32(native.BUS+native.layout['state_healthy'],0)
        self.assertEqual(v.apply(),0xffffffff)
        self.assertEqual(v.call(native.EXT+native.bundle['helper_entries']['studio_attack_tick'],v.CONTEXT)&0xffffffff,0xffffffff)

    def test_both_real_tournament_foreign_serials_own_batches_and_wrong_serial_still_releases(self):
        for side,serial in ((0,0xfffffffd),(1,0xfffffffe)):
            with self.subTest(cpu_side=side):
                v=QueueVM();v.u32(native.SELF+8,side)
                for i in range(23):
                    v.u32(native.PLAYERS+0xa8+i*0x198+0x30,serial)
                    v.u64(native.BUS+native.layout['expected']+i*16+8,serial)
                v.observe();self.assertEqual(v.managed(),1)
                p=v.proposal();p['score']=v.snapshot()['score'];v.send(p)
                self.assertEqual(v.tick(),1)
                self.assertEqual(v.queues[native.SELF+0x20],[[3,7,12],[3,8,13]])
                for i in range(23):v.u32(native.PLAYERS+0xa8+i*0x198+0x30,0xfffffffe if side==0 else 0xfffffffd)
                self.assertEqual(v.managed(),0);self.assertEqual(v.queues[native.SELF+0x20],[])


class PlanVM(QueueVM):
    """Actual native roles/grids/world setters; only memcpy and object roots are fixtures."""
    CONTEXT=native.DATA+0x190000
    PITCH=native.DATA+0x1a0000
    def __init__(self):
        super().__init__()
        self.u64(self.CONTEXT+0x6380,native.ROOT);self.u64(self.CONTEXT+0x6388,native.TEAM);self.u32(self.CONTEXT+8,1)
        self.uc.mem_write(self.PITCH,struct.pack('<ff',52.5,34.))
        self.stubs[0x72c3e6c]=lambda:self.PITCH
        self.stubs[0x8c1bc70]=self.memcpy
        for at in (0x73b000,0xc34000,0x74b000,0xc36000):
            self.uc.mem_map(at,4096);self.uc.mem_write(at,PLAN_RAW[at:at+4096])
        for plan in (0,1):
            for axis in range(3):
                for base in (0x214,0x68c):
                    self.uc.mem_write(native.TEAM+0x8078+base+plan*0x18c+axis*12,struct.pack('<fff',-50.,0.,0.))
        self.u32(native.TEAM+0xb45c,2)
        self.uc.mem_write(native.TEAM+0x8078+0xd24,struct.pack('<10I',*range(1,11)))
        self.observe()
    def memcpy(self):
        dest,source,n=(self.reg(i)for i in range(3))
        self.uc.mem_write(dest,bytes(self.uc.mem_read(source,n)));return dest
    def formation(self):
        p=self.proposal();p.update(kind='formation',incoming=[],outgoing=[],pairs=[],attack_level=3)
        p['mapping']={i:i for i in range(11)}
        p['mapping'][3],p['mapping'][6]=6,3
        self.spec['profiles'][0]['attack']=[0,1,1,2,3,4,5,8,9,10,12]
        self.spec['profiles'][0]['defence']=[0,1,1,2,3,4,5,5,6,7,12]
        return p
    def apply(self):
        return self.call(native.EXT+native.bundle['helper_entries']['studio_plan_tick'],self.CONTEXT)&0xffffffff


if __name__=='__main__':unittest.main()
