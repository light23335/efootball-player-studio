"""Real match bridge lifecycle behind the original mode dispatch fixture.

Only asset services/START serialization use the documented routing fixture.
The global coaching API, Bridge configuration, shared buffer and deactivation
execute unchanged, with no worker thread and only temporary output files.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import ai_match_runtime as coaching
import ai_tactical_profiles as profiles
from test_ai_match_manager import fixture
import test_match_mode_routing as routing_fixture

LAYOUT=json.loads((Path(__file__).resolve().parents[1]/'resources/native-ai-match-adapter.json').read_text('utf8'))['channel_schema']


class ModeCoachingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.gateway=routing_fixture.ModeRoutingTests();self.gateway.setUp()
        self.addCleanup(self.gateway.doCleanups)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        patch.dict(sys.modules,{'ai_match_runtime':coaching}).start()
        patch.object(coaching,'_CHANNELS',[]).start()
        patch.object(coaching,'_ACTIVE',None).start()
        self.buffer=bytearray(32768)
        self.channel=coaching.register_channel(self.buffer,0,LAYOUT,lambda:None,
            proof=dict.fromkeys(coaching.REQUIRED_PROOFS,True),start=False)

    def activate(self,gid):
        spec,_=fixture();spec.update(game_id=gid,entry_id='match-'+str(gid))
        base=spec['base_profile'];base['attack_coords']=profiles.coordinates(base,'attack','possession')
        base['defence_coords']=profiles.coordinates(base,'defence','possession');spec['profiles']=[base]
        coaching.activate(spec,self.root)
        self.assertEqual(self.channel.read(LAYOUT['enabled'],4),b'\x01\0\0\0')
        self.assertEqual(self.channel.read(LAYOUT['auto_execute'],4),b'\x01\0\0\0')
        return (copy.deepcopy(coaching._ACTIVE),copy.deepcopy(self.channel.spec),bytes(self.buffer),self.channel.epoch)

    def assert_channel(self,expected):
        self.assertEqual((coaching._ACTIVE,self.channel.spec,bytes(self.buffer),self.channel.epoch),expected)

    def start_tournament(self):
        g=self.gateway
        self.assertEqual(g.enter_tournament()['result'],'NOERR')
        gid=g.stored_tournament()['active']['game_id']
        self.assertEqual(g.logic.handle('CMD_START_GAME',{'game_id':gid})['result'],'NOERR')
        return gid

    def test_late_first_tournament_result_and_receipt_keep_new_division_bridge_enabled(self):
        g=self.gateway;gid=self.start_tournament();g.seed_division(started=True,game=12345)
        g.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})
        expected=self.activate(12345)
        first=g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(gid))
        self.assertEqual(first['owner'],'tournament')
        self.assert_channel(expected)
        self.assertEqual(g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(gid)),first)
        self.assert_channel(expected)

    def test_matching_tournament_result_closes_bridge_but_receipt_preserves_replacement(self):
        g=self.gateway;gid=self.start_tournament();self.activate(gid)
        first=g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(gid))
        self.assertEqual(first['owner'],'tournament')
        self.assertIsNone(coaching._ACTIVE);self.assertIsNone(self.channel.spec)
        self.assertEqual(self.channel.read(LAYOUT['enabled'],4),bytes(4))
        self.assertEqual(self.channel.read(LAYOUT['auto_execute'],4),bytes(4))
        expected=self.activate(12345)
        self.assertEqual(g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(gid)),first)
        self.assert_channel(expected)

    def test_division_receipt_does_not_close_current_tournament_bridge(self):
        g=self.gateway;g.seed_division(started=True,game=12345)
        receipt=g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(12345))
        self.assertEqual(receipt['owner'],'division')
        expected=self.activate(self.start_tournament())
        self.assertEqual(g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',g.result(12345)),receipt)
        self.assert_channel(expected)

    def test_identity_is_checked_after_acquiring_the_activation_lock(self):
        self.activate(12345)
        attempted=threading.Event();finished=threading.Event();result=[];errors=[]
        original_lock=coaching._LOCK
        class ObservedLock:
            def __enter__(self):
                if threading.current_thread()is worker:attempted.set()
                original_lock.acquire();return self
            def __exit__(self,*args):original_lock.release()
        def close_old():
            try:result.append(coaching.deactivate_for_match(12345,'old result'))
            except BaseException as exc:errors.append(exc)
            finally:finished.set()
        worker=threading.Thread(target=close_old)
        with patch.object(coaching,'_LOCK',ObservedLock()):
            with original_lock:
                worker.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.is_set())
                expected=self.activate(12346)
            worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(result,[False]);self.assert_channel(expected)
        self.assertTrue(coaching.deactivate_for_match('12346','matching result'))
        self.assertIsNone(coaching._ACTIVE)


if __name__=='__main__':unittest.main()
