"""Current due CPU matches are private read-only preparations, never results."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

import tournament_runtime as rt
import tournament_rules as rules
import test_tournament_background_remainder as background_fixture


class RoundPrewarmTests(unittest.TestCase):
    def setUp(self):
        self.f=background_fixture.BackgroundRemainderTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.configure([dict(type='league',advance_per_group=2),dict(type='knockout')])
        self.active=self.f.start();self.service=self.f.service;self.conn=self.f.conn
        self.current=self.f.g.stored_tournament()

    def warm(self,current=None):
        current=rules.State(copy.deepcopy(current or self.current));player=current['definition']['player_team_id']
        self.service._round_source_token=self.service.source_context(self.conn)
        rows=[(f['id'],self.service.round_cache_key(current,f))for f in rules.due(current)if player not in(f['home'],f['away'])]
        self.service.run_prewarm(self.f.path,current,rows,('manual',current['run_id']))
        return rows

    def test_real_readonly_connection_and_independent_generator_never_publish_result_or_progress(self):
        before=list(self.conn.execute('select key,value from meta order by key'));players=list(self.conn.execute('select * from managed_cards'))
        original=rt.Service.simulate_fixture;calls=[]
        def inspect(worker,conn,current,row):
            self.assertIsNot(conn,self.conn);self.assertIsNot(worker.generator,self.service.generator)
            self.assertFalse(conn.in_transaction)
            with self.assertRaises(sqlite3.OperationalError):conn.execute("insert into meta values('forbidden','1')")
            calls.append(row['id']);return original(worker,conn,current,row)
        with patch.object(rt.Service,'simulate_fixture',new=inspect):rows=self.warm()
        self.assertEqual(calls,[r[0]for r in rows]);self.assertEqual(len(rows),1)
        self.assertEqual(list(self.conn.execute('select key,value from meta order by key')),before)
        self.assertEqual(list(self.conn.execute('select * from managed_cards')),players)
        self.assertFalse(any(f['played']for f in self.f.g.stored_tournament()['fixtures']))
        self.assertEqual(self.f.g.stored_tournament()['active'],self.current['active'])
        self.assertTrue(self.f.prewarm_mock.called,'successful ENTRY/START must schedule optional work')

    def test_finish_consumes_only_verified_ready_contract_with_exact_same_scores_and_ratings(self):
        oracle=rules.State(copy.deepcopy(self.current));memory=sqlite3.connect(':memory:');self.addCleanup(memory.close)
        self.conn.backup(memory)
        control=rt.Service(lambda:self.f.g.f.document,'.',self.service.worker_generator(self.f.g.f.document))
        score=[2,0]if self.active['player_side']=='HOME'else[0,2]
        rules.record(oracle,self.active['fixture_id'],*score);oracle.pop('active')
        control.next_fixture(memory,oracle)
        rows=self.warm();request=self.f.g.result(self.active['game_id'])
        request['score']=[dict(score_1st=n,score_2nd=0)for n in score]
        with patch.object(rt,'_team_ratings',side_effect=AssertionError('ready CPU was rescored')):
            response=self.f.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)
        self.assertEqual(response['result'],'NOERR');saved=self.f.g.stored_tournament()
        for fid,_ in rows:
            actual=next(f for f in rt.hydrate_state(self.conn,saved)['fixtures']if f['id']==fid)
            expected=next(f for f in oracle['fixtures']if f['id']==fid)
            self.assertEqual(actual,json.loads(json.dumps(expected)))
        self.assertEqual(saved['active']if'active'in saved else None,None)
        self.assertFalse(saved['completed'])

    def test_cache_signature_ignores_disjoint_current_player_score_but_rejects_run_rules_history_and_document_changes(self):
        rows=self.warm();fid,key=rows[0]
        fixture=next(f for f in self.current['fixtures']if f['id']==fid)
        played=rules.State(copy.deepcopy(self.current));rules.record(played,self.active['fixture_id'],2,0)
        target=next(f for f in played['fixtures']if f['id']==fid)
        self.assertEqual(self.service.round_cache_key(played,target),key)
        for mutate in(lambda s:s.update(run_id='another-run'),
                       lambda s:s['definition'].update(include_diy=False),
                       lambda s:s['definition']['stages'][0].update(win_points=4),
                       lambda s:s['fixtures'].append(dict(id=999,home=fixture['home'],away=999,played=True,score=[9,0]))):
            changed=rules.State(copy.deepcopy(self.current));mutate(changed)
            changed_fixture=next(f for f in changed['fixtures']if f['id']==fid)
            self.assertNotEqual(self.service.round_cache_key(changed,changed_fixture),key)
        self.f.g.f.document['revision']='source-changed'
        self.assertNotEqual(self.service.round_cache_key(self.current,fixture),key)

    def test_two_leg_prewarm_obeys_due_leg_boundary_and_failure_is_readonly_fallback(self):
        self.f.configure([dict(type='knockout',legs=2)])
        with self.conn:self.conn.execute('delete from meta where key=?',(rt.PREFIX+self.f.g.f.definition['uuid'],))
        self.active=self.f.start();current=self.f.g.stored_tournament();before=copy.deepcopy(current)
        rows=self.warm(current)
        self.assertEqual(len(rows),1)
        self.assertTrue(all(self.service._round_cache[key]['leg']==1 for _,key in rows))
        self.assertTrue(all(f['leg']==1 for f in rules.due(current)))
        self.assertTrue(any(f['leg']==2 for f in current['fixtures']))
        self.assertEqual(self.f.g.stored_tournament(),before)
        self.service._round_cache.clear()
        with patch.object(rt.Service,'simulate_fixture',side_effect=ValueError('optional precompute failure')):self.warm(current)
        self.assertEqual(self.service._round_cache,{})
        self.assertEqual(self.f.g.stored_tournament(),before)
        # Instant finish or a failed prewarm still uses the original algorithm.
        request=self.f.g.result(self.active['game_id'])
        self.assertEqual(self.f.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)['result'],'NOERR')

    def test_exact_source_content_invalidates_ready_cache_without_revision_or_unrelated_meta_changes(self):
        rows=self.warm();fid,key=rows[0];source=self.service._round_source_token
        with self.conn:rt.put(self.conn,'unrelated-progress',{'counter':7})
        self.assertEqual(self.service.source_context(self.conn),source)
        cid,raw=self.conn.execute('select card_id,payload from managed_cards order by card_id limit 1').fetchone()
        card=json.loads(raw);card['parameters'][20]+=1
        with self.conn:self.conn.execute('update managed_cards set payload=? where card_id=?',(json.dumps(card),cid))
        changed=self.service.source_context(self.conn);self.assertNotEqual(changed,source)
        target=next(f for f in self.current['fixtures']if f['id']==fid)
        self.assertNotEqual(self.service.round_cache_key(self.current,target,changed),key)
        for field in('coaches','tournament_fallback_standard_cards','catalogue_recycle_bin'):
            self.f.g.f.document[field]=[{'changed':field}]
            self.assertNotEqual(self.service.source_context(self.conn),changed,field)
            self.f.g.f.document.pop(field)



if __name__=='__main__':unittest.main()
