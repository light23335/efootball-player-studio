import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_match_runtime as runtime
import ai_tactical_profiles as profiles
from test_ai_match_manager import fixture

RESOURCE=Path(__file__).resolve().parents[1]/'resources'
LAYOUT=json.loads((RESOURCE/'native-ai-match-adapter.json').read_text('utf8'))['channel_schema']


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.buffer=bytearray(b'G'*16+bytes(32768)+b'G'*16)
        self.spec,self.policy=fixture();self.spec['entry_id']='entry-A';self.policy['entry_id']='entry-A'
        base=self.spec['base_profile'];base['attack_coords']=profiles.coordinates(base,'attack','possession')
        base['defence_coords']=profiles.coordinates(base,'defence','possession');self.spec['profiles']=[base]

    def channel(self,proof=None,decoder=None):
        bridge=runtime.Bridge(self.buffer,16,LAYOUT,lambda:None,proof,decoder)
        bridge.configure(self.spec,self.root);return bridge

    def snapshot(self,bridge,sequence=2,epoch=None,minute=80,ack=None):
        block=bytearray(LAYOUT['snapshot_bytes'])
        def put(name,value,fmt='I'):struct.pack_into('<'+fmt,block,LAYOUT['snapshot.'+name],value)
        for name,value,fmt in (('sequence',sequence,'I'),('configuration_sequence',struct.unpack('<I',bridge.read(0,4))[0],'I'),
                               ('epoch',bridge.epoch if epoch is None else epoch,'Q'),('game_id',self.spec['game_id'],'Q'),
                               ('roster_count',23,'I'),('phase',1,'I'),('period',3,'I'),('team',1,'I'),
                               ('clock_frames',minute*3600.,'f'),('score_for',1,'i'),('score_against',0,'i'),
                               ('substitutions_left',5,'I'),('windows_left',3,'I'),('post_event',1,'I')):put(name,value,fmt)
        for i in range(23):
            role=self.policy['roles'].get(str(i),255)
            struct.pack_into('<IIIiIIIII',block,LAYOUT['snapshot.live']+i*36,i,i,i,95 if i<11 else 63,1,0,1,role,role)
        bridge.write(LAYOUT['snapshot'],block)
        if ack:bridge.write(LAYOUT['ack_id'],struct.pack('<QII',*ack))

    def decoder(self,spec,raw):
        state=copy.deepcopy(self.policy)
        state.update(sequence=raw['sequence'],clock_frames=raw['clock_frames'],minute=raw['clock_frames']/3600,
                     score=raw['score'],period=raw['period'])
        for key in ('ack_id','ack_status'): 
            if key in raw:state[key]=raw[key]
        return state

    def test_production_missing_decoder_or_any_proof_keeps_native_execution_off(self):
        ready=dict.fromkeys(runtime.REQUIRED_PROOFS,True)
        bridge=self.channel(ready,None)
        self.assertFalse(bridge.execute);self.assertEqual(bridge.read(LAYOUT['auto_execute'],4),bytes(4))
        for missing in runtime.REQUIRED_PROOFS:
            proof=dict(ready);proof[missing]=False
            bridge=self.channel(proof,self.decoder)
            self.snapshot(bridge);self.assertIsNotNone(bridge.step())
            self.assertEqual(bridge.read(LAYOUT['command'],440),bytes(440))
        self.assertEqual(self.buffer[:16],b'G'*16);self.assertEqual(self.buffer[-16:],b'G'*16)

    def test_same_entry_retry_after_json_roundtrip_does_not_reset_native_epoch(self):
        self.spec['prepared']={'chase':{'mapping':{2:3,10:4}}}
        bridge=self.channel();epoch=bridge.epoch;configuration=bridge.read(0,4)
        self.assertFalse(bridge.configure(json.loads(json.dumps(self.spec)),self.root))
        self.assertEqual(bridge.epoch,epoch);self.assertEqual(bridge.read(0,4),configuration)
        new=copy.deepcopy(self.spec);new['entry_id']='entry-B'
        self.assertTrue(bridge.configure(new,self.root));self.assertNotEqual(bridge.epoch,epoch)
        self.snapshot(bridge,epoch=epoch);self.assertIsNone(bridge.step())

    def test_observed_cpu_serial_is_canonicalized_without_changing_wire_identity(self):
        original=copy.deepcopy(self.spec['players'])
        self.spec['native_identity']={'layout':'serial32-padding32-card64','cpu_serial':-2,'execution_verified':False}
        bridge=self.channel()
        self.assertEqual(bridge.spec['players'],original)
        pairs=list(struct.iter_unpack('<QQ',bridge.read(LAYOUT['expected'],23*16)))
        self.assertEqual(pairs,[(p['id'],0xfffffffe)for p in original])
        self.assertFalse(bridge.execute)
        proof=dict.fromkeys(runtime.REQUIRED_PROOFS,True)
        bridge=runtime.Bridge(self.buffer,16,LAYOUT,lambda:None,proof,self.decoder)
        with self.assertRaisesRegex(ValueError,'observation-only'):bridge.configure(self.spec,self.root)

    def test_external_diagnostic_mirror_requires_opt_in_and_own_android_package(self):
        bridge=self.channel()
        self.assertIsNone(bridge.external_log)
        spec=copy.deepcopy(self.spec);spec['debug_external_status']=True
        with patch.object(bridge,'log'):
            bridge.configure(spec,'/data/user/0/com.efootball.revival.local/files/gateway')
        self.assertEqual(bridge.external_log.as_posix(),'/storage/emulated/0/Android/data/com.efootball.revival.local/files/personal-ai-coaching')
        for root in ('/data/user/0/../files','/tmp/com.efootball.revival.local/files',str(self.root)):
            spec['entry_id']+='x'
            with patch.object(bridge,'log'):bridge.configure(spec,root)
            self.assertIsNone(bridge.external_log)
        spec['entry_id']+='x';spec['debug_external_status']=False
        with patch.object(bridge,'log'):
            bridge.configure(spec,'/data/data/com.efootball.revival.local/files')
        self.assertIsNone(bridge.external_log)

    def test_diagnostic_mirror_contains_same_record_and_bounds_file_size(self):
        bridge=self.channel();mirror=self.root/'external';bridge.external_log=mirror
        bridge.log('test_record',{'raw':1})
        path=next(mirror.glob('*.jsonl'))
        internal=self.root/'outputs/efootball/ai-coaching'/path.name
        self.assertEqual(path.read_text('utf8').splitlines()[-1],internal.read_text('utf8').splitlines()[-1])
        # A long replay/pause session cannot grow one diagnostic file forever.
        path.write_bytes(b' '* (8*1024*1024+1))
        bridge.log('after_rotation',{})
        self.assertLess(path.stat().st_size,1024)
        self.assertTrue(path.with_suffix('.jsonl.1').is_file())

    def test_scope_diagnostics_explain_rejection_without_issuing_commands(self):
        self.spec['debug_external_status']=True
        bridge=self.channel();bridge.step()
        raw=bytearray(392)
        struct.pack_into('<6I',raw,0,2,1,1,23,7,0)
        for i,p in enumerate(self.spec['players']):
            struct.pack_into('<QQ',raw,24+i*16,p['id'],1 if i==0 else p['serial'])
        bridge.write(LAYOUT['diagnostic'],raw);bridge.step();bridge.step()
        record=next((self.root/'outputs/efootball/ai-coaching').glob('*.jsonl'))
        rows=[json.loads(line)for line in record.read_text('utf8').splitlines()]
        scopes=[r for r in rows if r['event']=='scope_diagnostic']
        self.assertEqual([r['reason']for r in scopes],['scope_not_observed','card_or_serial_mismatch'])
        self.assertEqual(scopes[-1]['actual_players'][0]['serial'],1)
        self.assertEqual(len(scopes[-1]['actual_players']),23)
        self.assertEqual(bridge.read(LAYOUT['command'],440),bytes(440))
        struct.pack_into('<I',raw,0,3)
        bridge.write(LAYOUT['diagnostic'],raw);bridge.step()
        self.assertEqual(record.read_text('utf8').splitlines(),[json.dumps(r,ensure_ascii=False,separators=(',',':'))for r in rows])

    def test_observer_keeps_raw_flags_and_native_entry_energy_without_submitting(self):
        bridge=self.channel();self.snapshot(bridge)
        snap=bridge.step();self.assertEqual(snap['live'][12]['stamina'],63)
        self.assertEqual(snap['live'][12]['stamina_source'],'native_entry_ratio')
        self.assertEqual(bridge.read(LAYOUT['command'],440),bytes(440))
        self.assertIsNone(bridge.step())
        logs=list((self.root/'outputs/efootball/ai-coaching').glob('*.jsonl'))
        records=[json.loads(line)for line in logs[0].read_text('utf8').splitlines()]
        self.assertEqual([r['event']for r in records],['configured','native_snapshot'])
        self.assertIn('native_flag_4202',records[-1]['live'][0]);self.assertNotIn('red_card',records[-1]['live'][0])
        self.assertNotIn('raw_plan',records[-1]);self.assertIn('attack_grid',records[-1]['live'][1])

    def test_snapshot_logs_use_game_clock_and_do_not_log_each_render_callback(self):
        bridge=self.channel();self.snapshot(bridge);bridge.step()
        self.snapshot(bridge,4,minute=80.1);bridge.step()
        self.snapshot(bridge,6,minute=80.6);bridge.step()
        record=list((self.root/'outputs/efootball/ai-coaching').glob('*.jsonl'))[0]
        self.assertEqual(sum(json.loads(line)['event']=='native_snapshot' for line in record.read_text('utf8').splitlines()),2)

    def test_verified_fixture_submits_once_and_waits_for_native_receipt(self):
        bridge=self.channel(dict.fromkeys(runtime.REQUIRED_PROOFS,True),self.decoder)
        self.snapshot(bridge);bridge.step();first=bridge.read(LAYOUT['command'],440)
        self.assertEqual(struct.unpack_from('<I',first,0)[0],2)
        plan_id=struct.unpack_from('<Q',first,LAYOUT['command.plan_id'])[0]
        self.snapshot(bridge,4,ack=(plan_id,1,0));bridge.step()
        self.assertEqual(bridge.read(LAYOUT['command'],440),first)
        self.assertIsNotNone(bridge.manager.state['pending'])
        self.snapshot(bridge,6,ack=(plan_id,2,0));bridge.step()
        self.assertIsNone(bridge.manager.state['pending']);self.assertEqual(bridge.manager.state['mode'],'protect')

    def test_worker_failure_stops_heartbeat_and_never_retries_bad_decoder(self):
        def broken(*args):raise RuntimeError('verified fixture decoder failed')
        bridge=self.channel(dict.fromkeys(runtime.REQUIRED_PROOFS,True),broken);self.snapshot(bridge)
        with self.assertLogs('ai_match_runtime',level='ERROR'):bridge.run()
        before=bridge.read(LAYOUT['heartbeat'],4)
        self.assertIn('decoder failed',bridge.failed);self.assertIsNone(bridge.step())
        self.assertEqual(bridge.read(LAYOUT['heartbeat'],4),before)
        self.assertEqual(bridge.read(LAYOUT['command'],440),bytes(440))

    def test_entry_exit_disables_channel_but_keeps_logs_and_spec_preferences(self):
        bridge=self.channel();before=copy.deepcopy(self.spec)
        bridge.deactivate('native accepted menu exit')
        self.assertEqual(bridge.read(LAYOUT['enabled'],4),bytes(4))
        self.assertIsNone(bridge.spec);self.assertIsNone(bridge.step());self.assertEqual(self.spec,before)

    def test_prepare_before_native_binding_and_duplicate_registration_are_safe(self):
        with patch.object(runtime,'_CHANNELS',[]),patch.object(runtime,'_ACTIVE',None):
            state=runtime.activate(self.spec,self.root);self.assertEqual(state['channels'],0)
            channel=runtime.register_channel(self.buffer,16,LAYOUT,lambda:None,start=False)
            self.assertIsNotNone(channel.spec)
            self.assertIs(runtime.register_channel(self.buffer,16,LAYOUT,lambda:None,start=False),channel)
            runtime.deactivate('exit');self.assertIsNone(channel.spec)

    def test_entry_id_is_hashed_for_paths_and_invalid_identity_sets_are_refused(self):
        self.spec['entry_id']='../../untrusted-entry';bridge=self.channel()
        self.assertEqual(len(list((self.root/'outputs/efootball/ai-coaching').glob('*.jsonl'))),1)
        duplicate=copy.deepcopy(self.spec);duplicate['players'][1]=copy.deepcopy(duplicate['players'][0])
        with self.assertRaises(ValueError):bridge.configure(duplicate,self.root)
        self.assertEqual(bridge.spec['entry_id'],'../../untrusted-entry')

    def test_same_entry_recovery_reconciles_without_replaying_pending_command(self):
        ready=dict.fromkeys(runtime.REQUIRED_PROOFS,True)
        first=self.channel(ready,self.decoder);self.snapshot(first);first.step()
        pending=copy.deepcopy(first.manager.state['pending'])
        self.assertIsNotNone(pending)
        recovered=runtime.Bridge(bytearray(32768),0,LAYOUT,lambda:None,ready,self.decoder)
        recovered.configure(self.spec,self.root)
        self.assertTrue(recovered.recovering)
        self.assertIsNone(recovered.manager.state['pending'])
        self.assertEqual(recovered.manager.state['next_id'],pending['id']+1)
        self.snapshot(recovered,sequence=4,minute=80.2);recovered.step()
        self.assertFalse(recovered.recovering)
        self.assertEqual(recovered.read(LAYOUT['command'],440),bytes(440))
        self.assertEqual(recovered.manager.state['journal'][-1]['event'],'restore_reconciled')

    def test_exit_and_different_spec_never_restore_old_policy(self):
        ready=dict.fromkeys(runtime.REQUIRED_PROOFS,True)
        first=self.channel(ready,self.decoder);self.snapshot(first);first.step()
        first.deactivate('explicit exit')
        closed=self.channel(ready,self.decoder)
        self.assertFalse(closed.recovering);self.assertEqual(closed.manager.state['next_id'],1)
        self.snapshot(closed);closed.step()
        self.spec['style']='long_ball'
        changed=self.channel(ready,self.decoder)
        self.assertFalse(changed.recovering);self.assertEqual(changed.manager.state['next_id'],1)

    def test_corrupt_or_invalid_checkpoint_keeps_fresh_policy(self):
        ready=dict.fromkeys(runtime.REQUIRED_PROOFS,True)
        first=self.channel(ready,self.decoder);self.snapshot(first);first.step()
        path=first.checkpoint_path();row=json.loads(path.read_text('utf8'))
        for value in ('{',json.dumps({**row,'state':{**row['state'],'next_id':-1}}),
                      json.dumps({**row,'state':{**row['state'],'elapsed_minute':float('nan')}})):
            path.write_text(value,encoding='utf8')
            fresh=self.channel(ready,self.decoder)
            self.assertFalse(fresh.recovering);self.assertEqual(fresh.manager.state['next_id'],1)

    def test_checkpoint_failure_prevents_publishing_unrecoverable_command(self):
        bridge=self.channel(dict.fromkeys(runtime.REQUIRED_PROOFS,True),self.decoder)
        self.snapshot(bridge)
        with patch.object(bridge,'save_policy',side_effect=OSError('storage full')):
            with self.assertLogs('ai_match_runtime',level='ERROR'):bridge.run()
        self.assertIn('storage full',bridge.failed)
        self.assertEqual(bridge.read(LAYOUT['command'],440),bytes(440))


if __name__=='__main__':unittest.main()
