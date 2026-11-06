"""Actual SQLite result commit/rollback behind both installed mode bridges."""
import copy
import sys
import unittest
from unittest.mock import patch

import tournament_runtime as runtime
from ai_division_sessions import game_id
import test_match_mode_routing as gateway_fixture


class ResultTransactionTests(unittest.TestCase):
    def setUp(self):
        self.g=gateway_fixture.ModeRoutingTests();self.g.setUp();self.addCleanup(self.g.doCleanups)
        self.conn=self.g.db;self.service=self.g.service
        self.conn.execute('create table settlement_effects(game_id text primary key,coins integer)')
        self.conn.commit();self.serializer_calls=[]
        serializer=sys.modules['cup16_service'].Cup16Service
        self.original_reply=serializer._result_reply
        def reply(logic,request,team,home,away,outcome):
            self.assertTrue(self.conn.in_transaction,'native effects require the receipt transaction')
            gid=str(game_id(request))
            self.serializer_calls.append(gid)
            self.conn.execute('insert into settlement_effects values(?,?)',(gid,100))
            return self.original_reply(logic,request,team,home,away,outcome)
        patch.object(serializer,'_result_reply',side_effect=reply).start()

    def start(self):
        self.assertEqual(self.g.enter_tournament()['result'],'NOERR')
        active=self.g.stored_tournament()['active'];gid=active['game_id']
        self.assertEqual(self.g.logic.handle('CMD_START_GAME',{'game_id':gid})['result'],'NOERR')
        self.conn.commit()
        return gid

    def saved_rows(self):return list(self.conn.execute('select key,value from meta order by key'))

    def test_cpu_computation_precedes_write_transaction_and_result_is_atomically_saved(self):
        gid=self.start();old=self.g.stored_tournament();simulated=[]
        original=self.service.simulate_fixture
        def simulate(conn,current,fixture):
            self.assertFalse(conn.in_transaction,'CPU build/rating must precede BEGIN')
            simulated.append(fixture['id']);result=original(conn,current,fixture)
            self.assertFalse(conn.in_transaction,'CPU build/rating must not open a write transaction')
            return result
        with patch.object(self.service,'simulate_fixture',side_effect=simulate):
            out=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.assertEqual(out['result'],'NOERR');self.assertTrue(simulated)
        self.assertEqual(self.serializer_calls,[str(gid)])
        saved=self.g.stored_tournament()
        self.assertIn(str(gid),saved['receipts']);self.assertNotIn('active',saved)
        played=next(f for f in saved['fixtures']if f['id']==old['active']['fixture_id'])
        self.assertEqual(played['score'],[2,0]);self.assertTrue(played['played'])
        self.assertEqual(self.conn.execute('select coins from settlement_effects').fetchall(),[(100,)])
        self.assertFalse(self.conn.in_transaction)

    def test_persistence_failure_rolls_back_native_effects_and_retry_keeps_same_cpu_contracts(self):
        gid=self.start();before=self.saved_rows();computed=[];settle=self.service.settle_result;put=runtime.put
        def compute(logic,t,current,request):
            out=settle(logic,t,current,request)
            computed.append(copy.deepcopy(current['fixtures']));return out
        def fail_final(conn,key,current):
            if key==runtime.PREFIX+self.g.f.definition['uuid']and str(gid)in current.get('receipts',{}):
                raise ValueError('injected final result persistence failure')
            return put(conn,key,current)
        with patch.object(self.service,'settle_result',side_effect=compute),patch.object(runtime,'put',side_effect=fail_final):
            failed=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.assertEqual(failed['result'],'ERR_INVALID_PARAM')
        self.assertEqual(self.saved_rows(),before)
        self.assertEqual(self.conn.execute('select * from settlement_effects').fetchall(),[])
        self.assertTrue(self.g.stored_tournament()['active']['started'])
        with patch.object(self.service,'settle_result',side_effect=compute):
            out=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.assertEqual(out['result'],'NOERR');self.assertEqual(computed[0],computed[1])
        self.assertEqual(self.conn.execute('select count(*)from settlement_effects').fetchone()[0],1)

    def test_compute_failure_never_calls_native_serializer_or_changes_saved_match(self):
        gid=self.start();before=self.saved_rows();original=self.service.simulate_fixture;calls=[]
        def broken(conn,current,fixture):
            self.assertFalse(conn.in_transaction);calls.append(fixture['id'])
            original(conn,current,fixture)
            raise ValueError('injected CPU computation failure')
        with patch.object(self.service,'simulate_fixture',side_effect=broken):
            self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'ERR_INVALID_PARAM')
        self.assertTrue(calls);self.assertEqual(self.serializer_calls,[])
        self.assertEqual(self.saved_rows(),before);self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'NOERR')

    def test_native_serializer_failure_rolls_back_its_effects_and_keeps_active(self):
        gid=self.start();before=self.saved_rows();reply=self.service.result_reply
        def broken(*args):
            reply(*args)
            raise ValueError('injected serializer failure after native effect')
        with patch.object(self.service,'result_reply',side_effect=broken),\
             patch.object(self.service,'close_result')as close:
            self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'ERR_INVALID_PARAM')
            close.assert_not_called()
        self.assertEqual(self.saved_rows(),before)
        self.assertEqual(self.conn.execute('select * from settlement_effects').fetchall(),[])
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'NOERR')
        self.assertEqual(self.conn.execute('select count(*)from settlement_effects').fetchone()[0],1)

    def test_postcommit_home_failure_replays_durable_receipt_without_awarding_twice(self):
        gid=self.start()
        with patch.object(runtime,'publish_saved_home',side_effect=ValueError('injected postcommit home failure')):
            self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'ERR_INVALID_PARAM')
        saved=self.g.stored_tournament();self.assertIn(str(gid),saved['receipts'])
        self.assertNotIn('active',saved)
        again=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.assertEqual(again['result'],'NOERR');self.assertEqual(self.serializer_calls,[str(gid)])
        self.assertEqual(self.g.stored_tournament(),saved)
        self.assertEqual(self.conn.execute('select count(*)from settlement_effects').fetchone()[0],1)

    def test_result_and_native_check_replay_receipt_without_state_writes_or_rewards(self):
        gid=self.start();first=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        before=self.saved_rows();statements=[];self.conn.set_trace_callback(statements.append)
        self.addCleanup(lambda:self.conn.set_trace_callback(None))
        with patch.object(self.service,'settle_result',side_effect=AssertionError('receipt recomputed')),\
             patch.object(self.service,'result_reply',side_effect=AssertionError('reward replayed')),\
             patch.object(runtime,'state',side_effect=AssertionError('receipt normalized again')),\
             patch.object(runtime,'put',side_effect=AssertionError('receipt rewritten')),\
             patch.object(runtime,'publish_saved_home',side_effect=AssertionError('receipt republished')):
            for command in('CMD_GET_VSCOM_GAME_RESULT','CMD_CHECK_GAME_RESULT'):
                out=self.g.logic.handle(command,dict(self.g.result(gid),rqid=77))
                expected=dict(first,msgid=command,rqid=77)
                self.assertEqual(out,expected)
        self.assertEqual(self.saved_rows(),before);self.assertEqual(self.serializer_calls,[str(gid)])
        self.assertFalse(any(s.lstrip().upper().startswith(('BEGIN','INSERT','UPDATE','DELETE'))for s in statements))

    def test_native_check_receipt_still_rejects_cross_event_and_cross_mode_identity(self):
        gid=self.start();self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.g.seed_division(game=12345)
        before=self.saved_rows()
        for request in({'game_id':gid,'match_category':'LEAGUE_COM_CUSTOM'},
                        {'game_id':gid,'event_id':1120005},
                        {'game_id':12345,'event_id':self.g.f.definition['event_id']},
                        {'game_id':gid,'match_result':{'game_id':12345}}):
            with self.subTest(request=request):
                self.assertEqual(self.g.logic.handle('CMD_CHECK_GAME_RESULT',request)['result'],'ERR_INVALID_PARAM')
                self.assertEqual(self.saved_rows(),before)
        self.assertEqual(self.serializer_calls,[str(gid)])

    def test_inherited_transaction_is_reused_without_nested_begin(self):
        gid=self.start();self.conn.execute('insert into meta values(?,?)',('wrapped-write','1'))
        self.assertTrue(self.conn.in_transaction)
        out=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))
        self.assertEqual(out['result'],'NOERR');self.assertFalse(self.conn.in_transaction)
        self.assertEqual(runtime.get(self.conn,'wrapped-write'),1)
        self.assertEqual(self.conn.execute('select count(*)from settlement_effects').fetchone()[0],1)

    def test_inherited_transaction_compute_failure_retains_original_rollback_boundary(self):
        gid=self.start();before=self.saved_rows()
        self.conn.execute('insert into meta values(?,?)',('wrapped-write','1'))
        with patch.object(self.service,'simulate_fixture',side_effect=ValueError('injected inherited compute failure')):
            self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.g.result(gid))['result'],'ERR_INVALID_PARAM')
        self.assertEqual(self.saved_rows(),before);self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.serializer_calls,[])

    def test_eliminated_player_still_settles_remaining_tournament_before_publishing_rewards(self):
        definition=runtime.configuration([dict(self.g.f.definition,stages=[dict(type='knockout')])])[0]
        self.g.f.definition=definition;self.g.f.document['tournaments']=[definition]
        gid=self.start();active=self.g.stored_tournament()['active'];side=active['player_side']
        request=self.g.result(gid)
        goals=[0,1]if side=='HOME'else[1,0]
        request['score']=[dict(score_1st=n,score_2nd=0)for n in goals]
        original=self.service.simulate_fixture;simulated=[]
        def simulate(conn,current,fixture):
            self.assertFalse(conn.in_transaction);simulated.append(fixture['id'])
            result=original(conn,current,fixture)
            self.assertFalse(conn.in_transaction);return result
        with patch.object(self.service,'simulate_fixture',side_effect=simulate):
            out=self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)
        self.assertEqual(out['result'],'NOERR')
        saved=self.g.stored_tournament()
        self.assertTrue(saved['completed']);self.assertEqual(len(saved['fixtures']),3)
        self.assertTrue(all(f['played']for f in saved['fixtures']));self.assertEqual(len(simulated),2)
        self.assertNotEqual(saved['champion'],definition['player_team_id'])
        self.assertIn(str(gid),saved['receipts'])
        self.assertTrue(saved.get('progression_presentation'))


if __name__=='__main__':unittest.main()
