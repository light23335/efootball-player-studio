from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_tournament_schedule_ui as native
import native_tournament_schedule_ui_entry as entry
import tournament_rules as rules
from test_tournament_schedule_ui import definition,db


class Engine:
    def __init__(self,profile,broken=False):
        self.data={r['file_offset']:bytes.fromhex(r['expected_hex']) for r in [profile,*profile['native_probes']]}
        if broken:
            at=profile['file_offset'];self.data[at]=bytes(len(self.data[at]))
    def seek(self,at):self.at=at
    def read(self,n):return self.data.get(self.at,b'')[:n]


class EntryTests(unittest.TestCase):
    def test_ready_gates_and_native_counters_are_persisted_without_db_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);memory=bytearray(native.CHANNEL_SCHEMA['bytes'])
            channel=native.ClickChannel(memory,0,native.CHANNEL_SCHEMA,lambda:None)
            data={'definitions':[],'url':None}
            service=types.SimpleNamespace(root=root,definitions=lambda:data['definitions'],overview_url=lambda:data['url'])
            with patch.multiple(native,_SERVICE=service,_CHANNEL=channel,_WORKER=None,_HOST=None,
                                _STATUS={'ready_reason':'initial'},_STATUS_EVENTS=native.deque(maxlen=32),_LAST_FLUSH=0):
                native._worker_tick(channel,service)
                path=root/'outputs/efootball/tournament-schedule-ui-status.json'
                status=json.loads(path.read_text('utf8'))
                self.assertEqual(status['worker']['ready_reason'],'no tournament definitions')
                self.assertEqual(status['channel']['ready'],0)
                data['definitions']=[{'event_id':205060988}]
                native._worker_tick(channel,service)
                self.assertEqual(json.loads(path.read_text('utf8'))['worker']['ready_reason'],'content service unavailable')
                data['url']='http://127.0.0.1:9/player-studio/tournaments'
                native._worker_tick(channel,service)
                self.assertEqual(json.loads(path.read_text('utf8'))['channel']['ready'],1)
                diag=native.CHANNEL_SCHEMA['diagnostics'];gate=1+native.DIAGNOSTIC_GATES.index('menu_state')
                struct.pack_into('<4I',memory,64,1,gate,gate,6)
                struct.pack_into('<Q',memory,24,0x123456789abc)
                struct.pack_into('<I',memory,diag['reached_offset'],1)
                struct.pack_into('<I',memory,diag['rejected_offset']+(gate-1)*4,1)
                native._worker_tick(channel,service)
                status=json.loads(path.read_text('utf8'))
                self.assertEqual(status['channel']['last_reject'],'menu_state')
                self.assertEqual(status['channel']['rejected']['menu_state'],1)
                self.assertEqual(status['channel']['observed']['state'],6)
                self.assertTrue(status['channel']['actor_present'])
                self.assertNotIn('20015998343868',path.read_text('utf8'))
                self.assertFalse(status['game_ui_success_asserted'])
                self.assertFalse((path.parent/'local-club.sqlite3').exists())
                self.assertEqual(list(path.parent.glob('.tournament-schedule-*.tmp')),[])

    def test_activity_unavailable_is_persisted_as_host_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=types.SimpleNamespace(root=Path(tmp))
            java=types.ModuleType('java');java.dynamic_proxy=lambda *args:object
            java.jclass=lambda name:types.SimpleNamespace(Get=lambda:None)
            with patch.multiple(native,_SERVICE=service,_CHANNEL=None,_WORKER=None,_HOST=None,
                                _STATUS={'ready_reason':'initial'},_STATUS_EVENTS=native.deque(maxlen=32),_LAST_FLUSH=0),patch.dict(sys.modules,{'java':java}):
                uid=definition()['uuid']
                with self.assertRaisesRegex(RuntimeError,'Activity'):
                    native.open_in_game('http://127.0.0.1:9/player-studio/tournaments/'+uid,uid)
                path=Path(tmp)/'outputs/efootball/tournament-schedule-ui-status.json'
                status=json.loads(path.read_text('utf8'))
                self.assertEqual(status['events'][-1]['event'],'host_create_failed')
                self.assertIn('Activity',status['events'][-1]['error'])
                self.assertFalse(status['game_ui_success_asserted'])

    def test_external_app_copy_survives_unwritable_primary_without_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);blocked=root/'blocked';blocked.write_text('regular file','utf8')
            external=root/'external/player-studio-tournament-schedule-ui-status.json'
            service=types.SimpleNamespace(root=blocked)
            with patch.multiple(native,_SERVICE=service,_CHANNEL=None,_WORKER=None,_HOST=None,
                                _STATUS={'ready_reason':'channel not registered'},_STATUS_EVENTS=native.deque(maxlen=32),
                                _EXTERNAL_STATUS_PATH=external,_EXTERNAL_STATUS_ERROR=None,_LAST_FLUSH=0):
                with self.assertLogs(native.LOG,level='WARNING'):
                    self.assertTrue(native.write_status(True))
                self.assertEqual(json.loads(external.read_text('utf8'))['worker']['ready_reason'],'channel not registered')
                native._SERVICE=None
                self.assertTrue(native.write_status(True))
                self.assertFalse(json.loads(external.read_text('utf8'))['configured'])
                self.assertEqual(blocked.read_text('utf8'),'regular file')

    def test_original_callback_normal_path_preserves_select_menu(self):
        resources=Path(__file__).resolve().parents[1]/'resources/tournament_schedule_ui'
        profile=json.loads((resources/'native-entry.json').read_text('utf8'))
        raw=(resources/'native-entry-click-flow.json').read_bytes()
        evidence=json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),profile['callback_flow_sha256'])
        self.assertEqual(evidence['blueprint_sha256'],profile['menu_source_sha256'])
        # Follow the decoded original branch, rather than assuming the state
        # immediately before the fade. The timeout branch is a different path.
        script=evidence['ScriptBytecode'];by_index={s['StatementIndex']:i for i,s in enumerate(script)}
        def trace(timeout):
            state=3;at=0;writes=[];calls=[]
            for _ in range(20):
                node=script[at];token=node['Token'];at+=1
                if token=='EX_Return':return state,writes,calls
                if token=='EX_JumpIfNot':
                    self.assertIn('IsChMissionTimeoutEvent',node['BooleanExpression']['Variable']['Property']['Name'])
                    if not timeout:at=by_index[node['CodeOffset']]
                elif token=='EX_Jump':at=by_index[node['CodeOffset']]
                elif token=='EX_Let':
                    self.assertEqual(node['Variable']['Variable']['Property']['Name'],'MainMenuState')
                    state=node['Expression']['Value'];writes.append(state)
                elif token=='EX_LocalVirtualFunction':calls.append(node['Function'])
                elif token=='EX_Context':
                    fade=node['ContextExpression'];calls.append(fade['Function'])
                    self.assertEqual(fade['Function'],'StartFadeOutFunc')
                    self.assertEqual([n.get('Value') for n in fade['Parameters'][1:]],['record','forward'])
            self.fail('Original callback did not return')
        state,writes,calls=trace(False)
        self.assertEqual((state,writes,calls),(3,[],['StartFadeOutFunc']))
        self.assertEqual(profile['click_state']['required'],state)
        state,writes,calls=trace(True)
        self.assertEqual((state,writes,calls),(6,[6],['CreateCommonAlert']))
        self.assertNotEqual(profile['click_state']['required'],state)

    def test_template_engine_menu_and_independent_proof_are_checked(self):
        resources=Path(__file__).resolve().parents[1]/'resources'
        p=json.loads((resources/'tournament_schedule_ui/native-entry.json').read_text('utf8'))
        result=entry.hooks(Engine(p),[205060988],resources,menu_sha256=p['menu_source_sha256'])[0]
        raw=bytes.fromhex(result['body_hex'])
        self.assertEqual(struct.unpack_from('<I',raw,p['event_ids_offset'])[0],205060988)
        self.assertTrue(result['execution_proof']['independent_instruction_probe'])
        self.assertFalse(result['device_validated']);self.assertFalse(result['production_ready'])
        self.assertEqual(result['address'],0x3c9408c)
        self.assertEqual(len(raw),len(bytes.fromhex(p['body_hex'])))
        with self.assertRaises(ValueError):entry.hooks(Engine(p,broken=True),[205060988],resources,menu_sha256=p['menu_source_sha256'])
        with self.assertRaises(ValueError):entry.hooks(Engine(p),[205060988],resources)
        with self.assertRaises(ValueError):entry.hooks(Engine(p),[1120005],resources,menu_sha256=p['menu_source_sha256'])
        out={};entry.attach_descriptor(out,result,800,[(64,native.CHANNEL_SCHEMA['bytes'])])
        d=out['tournament_schedule_channel'];self.assertEqual(d['data_offset'],64)
        self.assertEqual(d['schema'],native.CHANNEL_SCHEMA)
        self.assertEqual(d['fence_offset'],800+p['helper_entries']['studio_schedule_fence'])
        with self.assertRaises(ValueError):entry.attach_descriptor(out,result,800,[(64,native.CHANNEL_SCHEMA['bytes'])])

    def test_native_click_channel_is_one_shot_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=rules.start(definition(),2);path=db(root,s);before=path.read_bytes()
            memory=bytearray(native.CHANNEL_SCHEMA['bytes']+32);fences=[];channel=native.ClickChannel(memory,16,native.CHANNEL_SCHEMA,lambda:fences.append(1))
            calls=[];event=205060988
            service=types.SimpleNamespace(root=root,definitions=lambda:[dict(uuid=s['uuid'],event_id=event)],
                                          overview_url=lambda:'http://127.0.0.1:9/player-studio/tournaments')
            channel.set_ready(True)
            self.assertEqual(struct.unpack_from('<I',memory,16)[0],1)
            self.assertIsNone(channel.poll(service,lambda *args:calls.append(args)))
            struct.pack_into('<IQI',memory,16+4,1,1,event)
            result=channel.poll(service,lambda *args:calls.append(args)or True)
            self.assertTrue(result['queued']);self.assertEqual(len(calls),1)
            self.assertEqual(struct.unpack_from('<Q',memory,16+32)[0],1)
            self.assertEqual(struct.unpack_from('<I',memory,16+4)[0],0)
            self.assertIsNone(channel.poll(service,lambda *args:calls.append(args)))
            self.assertEqual(path.read_bytes(),before);self.assertGreater(len(fences),4)

    def test_channel_never_creates_a_missing_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory=bytearray(native.CHANNEL_SCHEMA['bytes']);channel=native.ClickChannel(memory,0,native.CHANNEL_SCHEMA,lambda:None)
            s=definition();service=types.SimpleNamespace(root=Path(tmp),definitions=lambda:[dict(uuid=s['uuid'],event_id=205060988)],
                   overview_url=lambda:'http://127.0.0.1:9/player-studio/tournaments')
            struct.pack_into('<IQI',memory,4,1,1,205060988)
            self.assertIsNone(channel.poll(service,lambda *args:self.fail('Missing save must not open UI')))
            self.assertFalse((Path(tmp)/'outputs').exists())

    def test_manifest_read_error_is_recorded_and_pending_click_acknowledged(self):
        memory=bytearray(native.CHANNEL_SCHEMA['bytes'])
        channel=native.ClickChannel(memory,0,native.CHANNEL_SCHEMA,lambda:None)
        def failed_definitions():raise OSError('manifest unavailable')
        service=types.SimpleNamespace(definitions=failed_definitions)
        struct.pack_into('<IQI',memory,4,1,7,205060988)
        with self.assertRaisesRegex(OSError,'manifest unavailable'):
            channel.poll(service)
        self.assertEqual(struct.unpack_from('<Q',memory,32)[0],7)
        self.assertEqual(struct.unpack_from('<I',memory,4)[0],0)
        self.assertIn('manifest unavailable',channel.last_result['error'])


if __name__=='__main__':unittest.main()
