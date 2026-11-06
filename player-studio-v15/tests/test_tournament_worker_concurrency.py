"""Slow real worker threads: bounded concurrency, cache publication and retry."""
import copy
import json
import threading
import time
import unittest
from unittest.mock import patch

import tournament_runtime as rt
import test_tournament_background_remainder as fixtures


class WorkerConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.BackgroundRemainderTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.service=self.f.service;self.conn=self.f.conn

    def drain(self,seconds=15):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            threads=list(self.service._remainder_workers.values())+list(self.service._prewarm_workers.values())
            if not threads:return
            for thread in threads:thread.join(.05)
        self.fail('worker threads did not stop')

    def eight_team_league(self):
        originals=[json.loads(raw)for cid,raw in self.conn.execute('select card_id,payload from managed_cards')if int(cid)<1000000]
        for team in range(125,129):
            for source in originals:
                card=copy.deepcopy(source);card['gameplayer_id']['id']+=team*10000;card['initial_base_team_id']=team
                raw=json.dumps(card)
                self.conn.execute('insert into managed_cards values(?,?,?)',(str(card['gameplayer_id']['id']),raw,raw))
        definition=rt.configuration([dict(self.f.g.f.definition,team_ids=list(range(121,129)),
            stages=[dict(type='league',advance_per_group=2),dict(type='knockout')])])[0]
        self.f.g.f.definition=definition;self.f.g.f.document['tournaments']=[definition];self.conn.commit()

    def test_partial_prewarm_then_repeated_real_entry_start_keeps_one_worker(self):
        self.eight_team_league();active=self.f.start();self.f.prewarm.stop()
        original=rt.Service.simulate_fixture;second=threading.Event();release=threading.Event();calls=[]
        def slow(worker,conn,current,row):
            calls.append(row['id'])
            if len(calls)==2:second.set();self.assertTrue(release.wait(10))
            return original(worker,conn,current,row)
        with patch.object(rt.Service,'simulate_fixture',new=slow):
            self.f.g.logic.handle('CMD_START_GAME',{'game_id':active['game_id']})
            try:
                self.assertTrue(second.wait(10));self.assertEqual(len(self.service._round_cache),1)
                worker=self.service._prewarm_workers[self.f.path]
                for _ in range(4):
                    self.assertEqual(self.f.g.logic.handle('CMD_START_GAME',{'game_id':active['game_id']})['result'],'NOERR')
                    self.assertEqual(self.f.g.enter_tournament()['result'],'NOERR')
                    self.assertIs(self.service._prewarm_workers[self.f.path],worker)
                self.assertEqual(len(calls),2)
            finally:release.set();self.drain()
        self.assertEqual(len(calls),3);self.assertEqual(len(self.service._round_cache),3)

    def test_cache_publishes_while_foreground_holds_global_tournament_lock(self):
        self.f.configure([dict(type='league',advance_per_group=2),dict(type='knockout')])
        self.f.start();current=self.f.g.stored_tournament();computed=threading.Event();release=threading.Event();published=threading.Event()
        class Cache(dict):
            def __setitem__(self,key,value):super().__setitem__(key,value);published.set()
        self.service._round_cache=Cache();original=rt.Service.simulate_fixture
        def slow(worker,conn,state,row):
            original(worker,conn,state,row);computed.set();self.assertTrue(release.wait(10))
        with patch.object(rt.Service,'simulate_fixture',new=slow):
            rt.Service.prewarm_round(self.service,self.conn,current)
            try:
                self.assertTrue(computed.wait(10))
                with rt.LOCK:
                    release.set();self.assertTrue(published.wait(2),'cache publication waited on global LOCK')
            finally:release.set();self.drain()

    def test_multiple_eliminated_editions_share_one_remainder_worker_per_database(self):
        self.f.launch.stop();entered=threading.Event();release=threading.Event();original=rt.Service.simulate_fixture
        runs=[];busy=[0];maximum=[0];mutex=threading.Lock()
        def slow(worker,conn,current,row):
            with mutex:busy[0]+=1;maximum[0]=max(maximum[0],busy[0])
            try:entered.set();self.assertTrue(release.wait(10));return original(worker,conn,current,row)
            finally:
                with mutex:busy[0]-=1
        with patch.object(rt.Service,'simulate_fixture',new=slow):
            try:
                for _ in range(3):
                    active=self.f.start();_,saved=self.f.lose(active);runs.append(saved['run_id'])
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(sum(t.is_alive()for t in self.service._remainder_workers.values()),1)
            finally:release.set();self.drain()
        self.assertEqual(maximum,[1]);self.assertEqual(len(set(runs)),3)
        for run in runs:
            _,saved=self.service.remainder_state(self.conn,[self.f.g.f.definition['uuid'],run,rt.progress_signature(self.f.g.f.definition),121])
            self.assertTrue(saved['completed'])

    def test_failed_worker_native_request_storm_obeys_persisted_backoff(self):
        self.f.launch.stop();calls=[]
        def fail(worker,conn,current,row):calls.append(row['id']);raise ValueError('persistent CPU source failure')
        with patch.object(rt.Service,'simulate_fixture',new=fail),patch.object(rt.time,'time',return_value=1000):
            active=self.f.start();self.f.lose(active);self.drain()
            saved=self.f.g.stored_tournament();self.assertEqual(saved['cpu_remainder_v1']['attempts'],1)
            for _ in range(20):self.f.g.logic.handle('CMD_GET_MAINMENU_INFO',{})
            self.drain();self.assertEqual(len(calls),1)
            self.assertEqual(self.f.g.stored_tournament()['cpu_remainder_v1']['retry_after'],1002)
        with patch.object(rt.Service,'simulate_fixture',new=fail),patch.object(rt.time,'time',return_value=1003):
            self.f.g.logic.handle('CMD_GET_MAINMENU_INFO',{});self.drain()
        self.assertEqual(len(calls),2)
        self.assertEqual(self.f.g.stored_tournament()['cpu_remainder_v1']['attempts'],2)
        self.assertEqual(self.f.g.stored_tournament()['cpu_remainder_v1']['retry_after'],1007)


if __name__=='__main__':unittest.main()
