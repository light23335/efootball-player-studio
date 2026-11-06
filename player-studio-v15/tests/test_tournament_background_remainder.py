"""File SQLite, real clubs/model and both installed routing bridges."""
import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_division_sessions as sessions
import tournament_runtime as rt
import tournament_rules as rules
import test_match_mode_routing as fixture


class BackgroundRemainderTests(unittest.TestCase):
    def setUp(self):
        self.g=fixture.ModeRoutingTests();self.g.setUp();self.addCleanup(self.g.doCleanups)
        temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.test-temp')
        self.addCleanup(temp.cleanup);self.path=str(Path(temp.name)/'isolated.sqlite3')
        conn=sqlite3.connect(self.path);self.g.db.commit();self.g.db.backup(conn)
        self.addCleanup(conn.close)
        self.g.db=self.g.f.db=self.g.logic.conn=conn
        self.conn=conn;self.service=self.g.service;self.launched=[]
        self.launch=patch.object(self.service,'launch_remainder',side_effect=lambda path,binding:self.launched.append((path,tuple(binding))))
        self.launch.start();self.addCleanup(self.launch.stop)
        self.prewarm=patch.object(self.service,'prewarm_round');self.prewarm_mock=self.prewarm.start();self.addCleanup(self.prewarm.stop)
        self.configure([dict(type='knockout')])

    def configure(self,stages):
        definition=rt.configuration([dict(self.g.f.definition,stages=stages)])[0]
        self.g.f.definition=definition;self.g.f.document['tournaments']=[definition]
        return definition

    def start(self):
        self.assertEqual(self.g.enter_tournament()['result'],'NOERR')
        active=self.g.stored_tournament()['active']
        self.assertEqual(self.g.logic.handle('CMD_START_GAME',{'game_id':active['game_id']})['result'],'NOERR')
        return active

    def lose(self,active):
        request=self.g.result(active['game_id']);goals=[0,1]if active['player_side']=='HOME'else[1,0]
        request['score']=[dict(score_1st=n,score_2nd=0)for n in goals]
        self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)['result'],'NOERR')
        return request,self.g.stored_tournament()

    def finish_worker(self,current):
        self.service.run_remainder(self.path,tuple(current['cpu_remainder_v1']['binding']))

    def test_first_round_loss_commits_real_result_receipt_and_one_elimination_before_cpu_work(self):
        active=self.start()
        with patch.object(self.service,'simulate_fixture',side_effect=AssertionError('result drained the remainder')):
            request,saved=self.lose(active)
        self.assertFalse(saved['completed']);self.assertNotIn('active',saved)
        self.assertEqual(sum(f['played']for f in saved['fixtures']),1)
        self.assertEqual(saved['cpu_remainder_v1']['status'],'pending')
        own=next(f for f in saved['fixtures']if f['id']==active['fixture_id'])
        self.assertEqual(own['score'],[r['score_1st']for r in request['score']])
        self.assertIn(str(active['game_id']),saved['receipts']);self.assertTrue(self.launched)
        events=saved['progression_presentation']['events']
        self.assertEqual([e['outcome']for e in events],['eliminated'])
        self.finish_worker(saved);complete=self.g.stored_tournament()
        self.assertTrue(complete['completed']);self.assertEqual(complete['cpu_remainder_v1']['settled_cpu'],2)
        self.assertTrue(all(f['played']for f in complete['fixtures']))
        self.assertEqual(complete['receipts'],saved['receipts'])
        self.assertEqual(complete['progression_presentation']['events'],events)

    def test_list_home_and_opponent_do_not_replay_old_fixture_or_drain_pending_remainder(self):
        active=self.start();_,saved=self.lose(active)
        with patch.object(self.service,'simulate_fixture',side_effect=AssertionError('menu advanced CPU')):
            out=self.g.logic.handle('CMD_GET_EVENT_LIST_AND_LOG',{})
            self.assertEqual(out['result'],'NOERR')
            self.assertIn('已被淘汰',out['event_list'][0]['description_text'])
            for command,request in(('CMD_GET_VSCOM_OPPONENT',{'event_id':saved['definition']['event_id']}),('CMD_START_GAME',{'game_id':active['game_id']})):
                response=self.g.logic.handle(command,request)
                self.assertEqual(response['result'],'ERR_INVALID_PARAM')
                self.assertIn('重新报名',response['studio_error'])
        self.assertEqual(self.g.stored_tournament()['fixtures'],saved['fixtures'])
        self.assertFalse(self.g.stored_tournament()['completed'])

    def test_immediate_new_entry_archives_old_run_and_worker_only_finishes_that_archive(self):
        active=self.start();request,old=self.lose(active)
        self.assertEqual(self.g.enter_tournament()['result'],'NOERR')
        new=copy.deepcopy(self.g.stored_tournament());self.assertNotEqual(new['run_id'],old['run_id'])
        key=rt.PREFIX+old['definition']['uuid']+':history:'+old['run_id']
        self.assertEqual(rt.get(self.conn,key),old)
        session=copy.deepcopy(vars(sessions.routing(self.g.logic)))
        self.finish_worker(old)
        self.assertTrue(rt.get(self.conn,key)['completed'])
        self.assertEqual(self.g.stored_tournament(),new)
        self.assertEqual(vars(sessions.routing(self.g.logic)),session)
        self.g.seed_division(started=True);self.g.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})
        mode=copy.deepcopy(vars(sessions.routing(self.g.logic)));division=sessions.read(self.conn,'ai_division_active_match')
        with patch.object(self.service,'settle_result',side_effect=AssertionError('old receipt recomputed')):
            for command in('CMD_GET_VSCOM_GAME_RESULT','CMD_CHECK_GAME_RESULT'):
                out=self.g.logic.handle(command,dict(request,rqid=88))
                expected=dict(old['receipts'][str(active['game_id'])],msgid=command,rqid=88)
                self.assertEqual(out,expected)
        self.assertEqual(vars(sessions.routing(self.g.logic)),mode)
        self.assertEqual(sessions.read(self.conn,'ai_division_active_match'),division)
        self.assertEqual(self.g.stored_tournament(),new)
        for bad in(dict(request,event_id=1120005),dict(request,match_category='LEAGUE_COM_CUSTOM')):
            self.assertEqual(self.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',bad)['result'],'ERR_INVALID_PARAM')

    def test_completed_table_elimination_defers_only_after_last_required_cpu_table_result(self):
        definition=self.configure([dict(type='league',advance_per_group=2),dict(type='knockout')])
        current=rules.start(definition,71);player=definition['player_team_id']
        last=max(f['round']for f in current['fixtures'])
        while rules.due(current)[0]['round']<last:
            for row in list(rules.due(current)):
                score=[0,1]if row['home']==player else[1,0]
                rules.record(current,row['id'],*score)
        with self.conn:rt.put(self.conn,rt.PREFIX+definition['uuid'],current)
        active=self.start();_,saved=self.lose(active)
        self.assertFalse(saved['completed']);self.assertEqual(saved['stage_index'],1)
        self.assertTrue(saved['stage_history']);self.assertTrue(rt.player_eliminated(saved))
        self.assertEqual(saved['cpu_remainder_v1']['settled_cpu'],0)
        self.finish_worker(saved);self.assertTrue(self.g.stored_tournament()['completed'])

    def test_initial_knockout_elimination_does_not_compute_later_four_cycle_league_in_result(self):
        self.configure([dict(type='knockout',advance=2),dict(type='league',cycles=4,advance_per_group=1)])
        active=self.start()
        with patch.object(self.service,'simulate_fixture',side_effect=AssertionError('future league ran in RESULT')):
            _,saved=self.lose(active)
        self.assertEqual(saved['stage_index'],0);self.assertFalse(saved['completed'])
        self.finish_worker(saved);complete=self.g.stored_tournament()
        self.assertTrue(complete['completed']);self.assertEqual(complete['stage_index'],1)
        self.assertEqual(complete['cpu_remainder_v1']['settled_cpu'],5)

    def test_worker_failure_and_cold_recovery_preserve_all_seeds_rosters_scores_and_receipt(self):
        active=self.start();_,saved=self.lose(active)
        oracle=rules.State(rt.hydrate_state(self.conn,saved));memory=sqlite3.connect(':memory:')
        self.addCleanup(memory.close);self.conn.backup(memory)
        self.service.next_fixture(memory,oracle)
        original=rt.Service.simulate_fixture;failed=[]
        def fail(worker,conn,current,row):
            self.assertIsNot(conn,self.conn);self.assertFalse(conn.in_transaction)
            self.assertIsNot(worker.generator,self.service.generator)
            original(worker,conn,current,row);failed.append(copy.deepcopy(row))
            raise ValueError('injected private CPU failure')
        with patch.object(rt.Service,'simulate_fixture',new=fail):self.finish_worker(saved)
        retry=self.g.stored_tournament()
        self.assertEqual(retry['fixtures'],saved['fixtures']);self.assertEqual(retry['receipts'],saved['receipts'])
        self.assertEqual(retry['cpu_remainder_v1']['status'],'failed')
        cold=rt.Service(lambda:self.g.f.document,'.',self.g.f.generator)
        launched=[]
        with patch.object(cold,'launch_remainder',side_effect=lambda p,b:launched.append((p,b))),patch.object(rt.time,'time',return_value=retry['cpu_remainder_v1']['retry_after']+1):cold.resume_remainders(self.conn)
        self.assertEqual(len(launched),1);cold.run_remainder(*launched[0])
        complete=self.g.stored_tournament()
        self.assertTrue(complete['completed']);self.assertEqual(rt.hydrate_state(self.conn,complete)['fixtures'],json.loads(json.dumps(oracle['fixtures'])))
        self.assertEqual(complete['champion'],oracle['champion'])
        self.assertEqual(next(f for f in rt.hydrate_state(self.conn,complete)['fixtures']if f['id']==failed[0]['id']),json.loads(json.dumps(failed[0])))

    def test_definition_change_during_cpu_work_cannot_merge_stale_result(self):
        active=self.start();_,saved=self.lose(active);original=rt.Service.simulate_fixture
        before=copy.deepcopy(saved['fixtures'])
        def edit(worker,conn,current,row):
            original(worker,conn,current,row)
            changed=copy.deepcopy(self.g.f.definition);changed['player_team_id']=122
            self.g.f.document['tournaments']=[changed]
            with self.conn:rt.state(self.conn,changed)
        with patch.object(rt.Service,'simulate_fixture',new=edit):self.finish_worker(saved)
        current=self.g.stored_tournament()
        self.assertEqual(current['fixtures'],before);self.assertNotIn('cpu_remainder_v1',current)
        self.assertEqual(current['definition']['player_team_id'],122)

    def test_worker_commit_failure_keeps_previous_fixture_and_retry_settles_only_the_remaining_one(self):
        active=self.start();_,saved=self.lose(active);put=rt.put
        def fail(conn,key,current):
            job=current.get('cpu_remainder_v1')or{}
            if job.get('status')=='completed':raise ValueError('injected worker final commit failure')
            return put(conn,key,current)
        with patch.object(rt,'put',side_effect=fail):self.finish_worker(saved)
        partial=self.g.stored_tournament()
        self.assertFalse(partial['completed']);self.assertEqual(partial['cpu_remainder_v1']['settled_cpu'],1)
        self.assertEqual(partial['cpu_remainder_v1']['status'],'failed')
        fixed=copy.deepcopy([f for f in partial['fixtures']if f['played']])
        self.finish_worker(partial);complete=self.g.stored_tournament()
        self.assertTrue(complete['completed']);self.assertEqual(complete['cpu_remainder_v1']['settled_cpu'],2)
        self.assertEqual([f for f in complete['fixtures']if f['id']in{r['id']for r in fixed}],fixed)
        self.assertEqual(complete['receipts'],saved['receipts'])

    def test_foreground_delivery_and_metadata_updates_survive_worker_fixture_merge(self):
        active=self.start();_,saved=self.lose(active);simulate=rt.Service.simulate_fixture;edited=[]
        def update(worker,conn,current,row):
            simulate(worker,conn,current,row)
            if edited:return
            latest=self.g.stored_tournament();latest['foreground_delivery_note']={'foreground':'retained'}
            latest['progression_presentation']['events'][0]['status']='confirmed'
            with self.conn:rt.put(self.conn,rt.PREFIX+latest['definition']['uuid'],latest)
            edited.append(True)
        with patch.object(rt.Service,'simulate_fixture',new=update):self.finish_worker(saved)
        complete=self.g.stored_tournament();self.assertTrue(complete['completed'],complete.get('cpu_remainder_v1'))
        self.assertEqual(complete['foreground_delivery_note'],{'foreground':'retained'})
        self.assertEqual(complete['progression_presentation']['events'][0]['status'],'confirmed')
        self.assertEqual(complete['receipts'],saved['receipts'])

    def test_cold_recovery_finds_pending_archived_run_without_selecting_it(self):
        active=self.start();_,old=self.lose(active);self.g.enter_tournament()
        new=copy.deepcopy(self.g.stored_tournament());cold=rt.Service(lambda:self.g.f.document,'.',self.g.f.generator)
        rows=[]
        with patch.object(cold,'launch_remainder',side_effect=lambda p,b:rows.append((p,b))):cold.resume_remainders(self.conn)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0][1][1],old['run_id'])
        cold.run_remainder(*rows[0])
        self.assertEqual(self.g.stored_tournament(),new)
        archive=rt.get(self.conn,rt.PREFIX+old['definition']['uuid']+':history:'+old['run_id'])
        self.assertTrue(archive['completed']);self.assertEqual(archive['receipts'],old['receipts'])

    def test_archived_definition_change_marks_job_superseded_without_relaunch_loop(self):
        active=self.start();_,old=self.lose(active);self.g.enter_tournament()
        new=copy.deepcopy(self.g.stored_tournament());changed=copy.deepcopy(self.g.f.definition)
        changed['player_team_id']=122;self.g.f.document['tournaments']=[changed]
        self.finish_worker(old)
        archive=rt.get(self.conn,rt.PREFIX+old['definition']['uuid']+':history:'+old['run_id'])
        self.assertEqual(archive['cpu_remainder_v1']['status'],'superseded')
        self.assertEqual(archive['fixtures'],old['fixtures']);self.assertEqual(self.g.stored_tournament(),new)
        cold=rt.Service(lambda:self.g.f.document,'.',self.g.f.generator)
        with patch.object(cold,'launch_remainder')as launch:
            for _ in range(10):cold.resume_remainders(self.conn)
            launch.assert_not_called()

    def test_include_diy_change_during_compute_discards_unpublished_old_context(self):
        active=self.start();_,saved=self.lose(active);simulate=rt.Service.simulate_fixture;calls=[]
        def change(worker,conn,current,row):
            calls.append((row['id'],current['definition']['include_diy']))
            simulate(worker,conn,current,row)
            if len(calls)==1:
                latest=self.g.stored_tournament();latest['definition']['include_diy']=False
                with self.conn:rt.put(self.conn,rt.PREFIX+latest['definition']['uuid'],latest)
        with patch.object(rt.Service,'simulate_fixture',new=change):self.finish_worker(saved)
        complete=self.g.stored_tournament();self.assertTrue(complete['completed'])
        self.assertEqual(calls[0][0],calls[1][0]);self.assertEqual([v for _,v in calls[:2]],[True,False])
        self.assertEqual(complete['cpu_remainder_v1']['settled_cpu'],2)
        self.assertEqual(complete['receipts'],saved['receipts'])

    def test_source_change_between_commits_rebuilds_worker_before_next_compute(self):
        active=self.start();_,saved=self.lose(active);put=rt.put;edited=[]
        def change(conn,key,current):
            put(conn,key,current)
            if(current.get('cpu_remainder_v1')or{}).get('settled_cpu')==1 and not edited:
                self.g.f.document['preview_boosters']['7']['effects']['20']=6;edited.append(True)
        factory=self.service.worker_generator
        with patch.object(rt,'put',side_effect=change),patch.object(self.service,'worker_generator',wraps=factory)as clone:
            self.finish_worker(saved)
        self.assertTrue(self.g.stored_tournament()['completed']);self.assertEqual(clone.call_count,2)
        self.assertEqual(clone.call_args_list[-1].args[0]['preview_boosters']['7']['effects']['20'],6)

    def test_actual_worker_computes_without_gateway_lock_or_write_transaction(self):
        active=self.start();_,saved=self.lose(active)
        entered=threading.Event();release=threading.Event();original=rt.Service.simulate_fixture
        def pause(worker,conn,current,row):
            self.assertIsNot(conn,self.conn);self.assertFalse(conn.in_transaction)
            entered.set();self.assertTrue(release.wait(10));return original(worker,conn,current,row)
        with patch.object(rt.Service,'simulate_fixture',new=pause):
            thread=threading.Thread(target=self.service.run_remainder,args=(self.path,tuple(saved['cpu_remainder_v1']['binding'])))
            thread.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertTrue(rt.LOCK.acquire(timeout=1));rt.LOCK.release()
                self.g.seed_division(started=True)
                self.assertEqual(self.g.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})['result'],'NOERR')
            finally:release.set();thread.join(15)
            self.assertFalse(thread.is_alive())
        self.assertTrue(self.g.stored_tournament()['completed'])


if __name__=='__main__':unittest.main()
