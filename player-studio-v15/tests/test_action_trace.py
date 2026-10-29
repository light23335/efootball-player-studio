import io,json,struct,sys,tempfile,unittest,ctypes,copy
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'maintenance')]
import action_trace as trace


def event(seq=1,slot=7,kind=1):
    data=bytearray(trace.EVENT_BYTES)
    struct.pack_into('<QQQ7I',data,0,seq,0x43000000,0x42000000,100,1,slot,10,25,1,1)
    struct.pack_into('<3f',data,52,20.,0.,15.)
    struct.pack_into('<3f',data,64,52.5,0.,1.)
    struct.pack_into('<2f4I',data,76,float('nan'),.55,kind,160,1,0)
    return data


class JournalTests(unittest.TestCase):
    def test_decoded_events_retain_native_ids_and_never_output_nan(self):
        value=trace.decode_event(event(kind=4))
        self.assertEqual(value['motion']['family_id'],160);self.assertTrue(value['motion']['selection_succeeded'])
        self.assertEqual(value['action']['name'],'控制射门');self.assertIsNone(value['power_before'])
        self.assertEqual(value['skills'],['弧线落叶射门']);json.dumps(value,allow_nan=False)
        raw=event();struct.pack_into('<I',raw,36,222)
        self.assertEqual(trace.decode_event(raw)['action']['name'],'原生动作 222')

    def test_bad_rows_are_refused(self):
        with self.assertRaises(ValueError):trace.decode_event(b'')
        with self.assertRaises(ValueError):trace.decode_event(event(slot=22))
        with self.assertRaises(ValueError):trace.decode_event(event(kind=99))

    def ring(self,count):
        data=bytearray(trace.BUFFER_BYTES);struct.pack_into('<II',data,0,trace.MAGIC,1)
        for n in range(max(1,count-trace.CAPACITY+1),count+1):
            at=trace.HEADER_BYTES+n%trace.CAPACITY*trace.EVENT_BYTES;data[at:at+trace.EVENT_BYTES]=event(n)
        struct.pack_into('<Q',data,16,count)
        return data,trace.RingReader(lambda at,size:bytes(data[at:at+size]))

    def test_ring_overflow_is_explicit_and_each_retained_row_is_ordered(self):
        data,reader=self.ring(trace.CAPACITY+3);rows=reader.drain()
        self.assertEqual(rows[0],{'event':'trace_overrun','lost_events':3})
        self.assertEqual([v['sequence']for v in rows[1:]],list(range(4,trace.CAPACITY+4)))
        self.assertEqual(reader.drain(),[])

    def test_torn_or_overwritten_slots_are_not_reported_as_another_actor(self):
        data,reader=self.ring(1)
        at=trace.HEADER_BYTES+trace.EVENT_BYTES;struct.pack_into('<Q',data,at,2)
        self.assertEqual(reader.drain(),[{'event':'trace_overrun','lost_events':1}])

    def test_journal_rotates_without_erasing_previous_events(self):
        with tempfile.TemporaryDirectory()as folder:
            journal=trace.Journal(folder,max_bytes=1);journal.append([trace.decode_event(event())]);journal.close()
            files=sorted(journal.folder.glob('*.jsonl'));self.assertEqual(len(files),2)
            data=[json.loads(line)for p in files for line in p.read_text('utf8').splitlines()]
            self.assertEqual(sum(v['event']=='action_change'for v in data),1)


class ObserverBindingTests(unittest.TestCase):
    def payload(self,split):
        from native_action_trace import hooks
        from personal_binding import compose
        resources=ROOT/'resources';data=json.loads((resources/'native-action-trace.json').read_text('utf8'))
        class Engine:
            def seek(self,at):self.at=at
            def read(self,n):return next((bytes.fromhex(row['expected_hex'])[:n]for row in [data['bundles'][0],*data['bundles'][0]['extra_entries']]if row['file_offset']==self.at),bytes(n))
        original=json.loads((resources/'native-binding-profile.json').read_text('utf8'))
        profile=json.loads((resources/'native-route-templates.json').read_text('utf8'))
        profile['external_routes']=split;profile['native_hooks']=hooks(Engine())
        return original,compose(original,[],profile)

    def test_ring_and_fence_follow_split_code_relocation(self):
        from personal_binding import relocate_code
        original,payload=self.payload(True);d=payload['action_trace_channel']
        self.assertEqual(d['code_region'],'extension');self.assertEqual(d['schema'],trace.SCHEMA)
        code=bytearray.fromhex(payload['blob_hex']);struct.pack_into('<Q',code,payload['back_fixup'],0x7000000000+payload['hooks'][0]['address']+4)
        prefix,extension=relocate_code(payload,bytes(code),0x7100000000,0x7300000538,0x7500000000,0x7600000000)
        self.assertEqual(extension[d['fence_offset']:d['fence_offset']+8],bytes.fromhex('bf3b03d5c0035fd6'))
        self.assertIn(0x7600000000+d['data_offset'],[struct.unpack_from('<Q',extension,at)[0]for at,_ in payload['extension_writable_pointer_fixups']])
        self.assertLessEqual(len(prefix),4096)

    def test_registration_uses_only_private_rw_view_and_verified_fence(self):
        from personal_binding import _BindingCtypes
        _,payload=self.payload(True);d=payload['action_trace_channel'];binding=_BindingCtypes(ctypes,payload)
        with patch('action_trace.register_channel',return_value='registered')as register:binding._register_action_channel(0x7100000000,0x7300000538)
        self.assertEqual(binding.action_channel,'registered');self.assertIs(register.call_args.args[0],binding.writable)
        self.assertEqual(register.call_args.args[1],d['data_offset'])
        self.assertEqual(ctypes.cast(register.call_args.args[3],ctypes.c_void_p).value,0x7300000538+d['fence_offset'])

    def test_reexport_without_observer_drops_old_channel(self):
        from personal_binding import compose
        original,payload=self.payload(False);self.assertEqual(payload['action_trace_channel']['code_region'],'root')
        original['action_trace_channel']=payload['action_trace_channel']
        profile=json.loads((ROOT/'resources/native-route-templates.json').read_text('utf8'))
        self.assertNotIn('action_trace_channel',compose(original,[],profile))


ENGINE=ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so'
@unittest.skipUnless(ENGINE.is_file(),'requires audited native V17 engine')
class NativeObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import unicorn
        from unicorn import arm64_const
        from elftools.elf.elffile import ELFFile
        from build_action_observer import build
        import test_skill_effects_v2 as fixtures
        cls.u,cls.r=unicorn,arm64_const;cls.engine=ENGINE.read_bytes()
        elf=ELFFile(io.BytesIO(cls.engine));cls.segments=[(s['p_vaddr'],s['p_offset'],s['p_filesz'],s['p_memsz'])for s in elf.iter_segments()if s['p_type']=='PT_LOAD']
        cls.candidate=build(cls.engine)
        cls.machine=fixtures.NativeSkillV2Tests.machine;cls.install_all=fixtures.NativeSkillV2Tests.install_all
        cls.relocate_state=fixtures.NativeSkillV2Tests.relocate_state

    def scene(self,slot=7,enabled=True,patched=True,with_identity=False):
        r=self.r;self.actor=0x42000000;self.root=0x43000000;self.info=0x44000000
        self.state=0x45000000;self.ai=0x46000000;self.request=0x47000000;self.output=0x48000000
        self.frame=100;self.current_root=self.root;self.calls=0
        self.card_id=90159685099299;self.roster_calls=[]
        def ret(value):return lambda vm:vm.reg_write(r.UC_ARM64_REG_X0,value)
        def current(vm):self.calls+=1;vm.reg_write(r.UC_ARM64_REG_X0,self.current_root)
        stubs={0x698f7e0:current,0x72c408c:lambda vm:vm.reg_write(r.UC_ARM64_REG_X0,self.actor if self.current_root==self.root else self.actor+16),0x72c3e80:ret(self.info),0x697b60c:ret(1),
               0x6a4bd08:lambda vm:vm.reg_write(r.UC_ARM64_REG_W0,self.frame),
               0x72d7dc8:ret(self.ai),0x72c40b0:ret(self.state),
               0x72c404c:ret(0),
               0x6d3fe78:ret(0),0x6d64b78:ret(0)}
        if with_identity:
            def players(vm):self.roster_calls.append(('team',vm.reg_read(r.UC_ARM64_REG_W1)));vm.reg_write(r.UC_ARM64_REG_X0,self.info+0x4000)
            def entry(vm):self.roster_calls.append(('slot',vm.reg_read(r.UC_ARM64_REG_W1)));vm.reg_write(r.UC_ARM64_REG_X0,self.info+0x5000)
            def identity(vm):vm.reg_write(r.UC_ARM64_REG_X0,0xfeed1234fffffffe);vm.reg_write(r.UC_ARM64_REG_X1,self.card_id)
            stubs.update({0x72c404c:players,0x68fb5fc:ret(23),0x72f2d04:entry,0x72f29e0:identity})
        vm=self.machine(stubs);vm.mem_map(0x49010000,0x80000)
        for address in (self.actor,self.root,self.info,self.state,self.ai,self.request,self.output):vm.mem_map(address,0x10000)
        vm.mem_write(self.actor+0x4620,struct.pack('<Q',self.root));vm.mem_write(self.actor+0x2a38,bytes([slot]))
        vm.mem_write(self.actor+0xad0,b'\x0a');vm.mem_write(self.actor+0x4f4,struct.pack('<3f',20.,0.,15.))
        vm.mem_write(self.ai+4,struct.pack('<II3f',25,1,52.5,0.,1.))
        vm.mem_write(self.state+0x394+0xc0,(1<<51).to_bytes(12,'little'))
        vm.mem_write(self.request+0x138,struct.pack('<Q',self.actor));vm.mem_write(self.request+0xc,struct.pack('<f',.55))
        vm.mem_write(self.request+0x60,b'\1')
        self.helpers=self.install_all(vm)if patched else {}
        self.ring=0x49000000;vm.mem_write(self.ring,struct.pack('<II',trace.MAGIC,int(enabled)))
        self.reader=trace.RingReader(lambda at,size:bytes(vm.mem_read(self.ring+at,size)))
        return vm

    def invoke(self,vm,address,*args):
        r=self.r
        for n,value in enumerate(args):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(n)),value)
        vm.reg_write(r.UC_ARM64_REG_X30,0x2003f000);vm.emu_start(address,0x2003f000,count=50000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_PC),0x2003f000)
        return vm.reg_read(r.UC_ARM64_REG_X0)

    def test_state_getter_returns_original_result_and_logs_actual_player(self):
        vm=self.scene();self.assertEqual(self.invoke(vm,0x6d3d9dc,self.actor),10)
        rows=self.reader.drain();self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['slot'],rows[0]['action']['id'],rows[0]['request']['subtype']),(7,10,1))
        self.assertEqual(rows[0]['skills'],['弧线落叶射门'])

    def test_state_changes_and_request_changes_are_logged_but_duplicate_getters_are_not(self):
        vm=self.scene()
        for _ in range(20):self.invoke(vm,0x6d3d9dc,self.actor)
        self.assertEqual(len(self.reader.drain()),1)
        self.frame+=1;self.invoke(vm,0x6d3d9dc,self.actor);self.assertEqual(self.reader.drain(),[])
        vm.mem_write(self.ai+8,struct.pack('<I',2));self.invoke(vm,0x6d3d9dc,self.actor)
        self.assertEqual(self.reader.drain()[0]['request']['subtype'],2)
        vm.mem_write(self.actor+0xad0,b'\x0b');self.invoke(vm,0x6d3d9dc,self.actor)
        self.assertEqual(self.reader.drain()[0]['action']['id'],11)

    def test_disabled_invalid_slot_or_old_root_never_touch_engine_state(self):
        for slot,enabled,old in [(7,False,False),(255,True,False),(7,True,True)]:
            vm=self.scene(slot,enabled)
            if old:self.current_root+=16
            before=bytes(vm.mem_read(self.actor,0x5000))
            self.assertEqual(self.invoke(vm,0x6d3d9dc,self.actor),10)
            self.assertEqual(self.reader.drain(),[]);self.assertEqual(bytes(vm.mem_read(self.actor,0x5000)),before)

    def test_both_teams_are_observed_and_expired_cache_pointers_are_only_compared(self):
        vm=self.scene(slot=17)
        cache=self.ring+64+17*128;vm.mem_write(cache,struct.pack('<QQ',0xdead0000,0xdead1000))
        self.invoke(vm,0x6d3d9dc,self.actor)
        self.assertEqual(self.reader.drain()[0]['team'],1)

    def test_card_and_serial_identity_follow_current_roster_after_substitution(self):
        vm=self.scene(slot=17,with_identity=True);self.invoke(vm,0x6d3d9dc,self.actor)
        row=self.reader.drain()[0]
        self.assertEqual(row['player_id'],self.card_id);self.assertEqual(row['player_serial'],0xfffffffe)
        self.assertEqual(self.roster_calls,[('team',1),('slot',6)])
        self.card_id+=1;self.invoke(vm,0x6d3d9dc,self.actor)
        self.assertEqual(self.reader.drain()[0]['player_id'],self.card_id)

    def test_full_native_motion_selector_return_and_output_are_preserved(self):
        results=[]
        for patched in (False,True):
            vm=self.scene(patched=patched)
            result=self.invoke(vm,0x6d5f2f0,160,0,self.request,self.output,0,0)
            results.append((result,bytes(vm.mem_read(self.output,0x100))))
            if patched:
                rows=self.reader.drain();self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['event'],'motion_selection')
                self.assertEqual(rows[0]['motion'],{'family_id':160,'name':'弧线落叶射门动作','selection_succeeded':False})
                self.assertAlmostEqual(rows[0]['power_after'],.55,places=5)
        self.assertEqual(results[0],results[1])


if __name__=='__main__':unittest.main()
