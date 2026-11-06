"""Atomic compressed audits, legacy reads and an actual 32,512-fixture shape."""
import copy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

import tournament_runtime as rt
import test_tournament_background_remainder as fixtures

SCALE_MEASUREMENT=None


class ContractStorageTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.BackgroundRemainderTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.conn=self.f.conn

    def blob_rows(self):return list(self.conn.execute('select key,value from meta where key like ? order by key',(rt.BLOB_PREFIX+'%',)))

    def test_native_and_cpu_settled_contracts_roundtrip_with_restart_and_readonly_audit(self):
        active=self.f.start();_,saved=self.f.lose(active)
        own=next(f for f in saved['fixtures']if f['id']==active['fixture_id'])
        self.assertIn('blob_v1',own['simulation_v1']);self.assertNotIn('teams',own['simulation_v1'])
        full=rt.hydrate_contract(self.conn,saved,own)
        self.assertEqual(len(full['teams']['home']['player_list']),23)
        self.assertEqual(len(full['teams']['away']['player_list']),23)
        self.assertTrue(full['ratings']['home']['audit']['players'])
        self.assertEqual(full['source'],'native');self.assertEqual(full['result']['final_score'],own['score'])
        self.f.finish_worker(saved);complete=self.f.g.stored_tournament()
        self.assertEqual(len(self.blob_rows()),3)
        restart=sqlite3.connect('file:'+self.f.path+'?mode=ro',uri=True);self.addCleanup(restart.close)
        before=list(self.conn.execute('select key,value from meta order by key'))
        hydrated=rt.hydrate_state(restart,complete)
        self.assertTrue(all(f['simulation_v1']['teams']for f in hydrated['fixtures']))
        self.assertEqual(list(self.conn.execute('select key,value from meta order by key')),before)
        self.assertTrue(all(not key.startswith(rt.PREFIX)for key,_ in self.blob_rows()))

    def test_result_final_put_failure_rolls_back_blobs_state_receipt_and_native_effects(self):
        active=self.f.start();before=list(self.conn.execute('select key,value from meta order by key'));put=rt.put
        def fail(conn,key,current):
            if key==rt.PREFIX+self.f.g.f.definition['uuid']and str(active['game_id'])in current.get('receipts',{}):
                self.assertTrue(self.blob_rows(),'snapshot inserts must precede final state in the same transaction')
                raise ValueError('injected final put after blob insertion')
            return put(conn,key,current)
        request=self.f.g.result(active['game_id'])
        with patch.object(rt,'put',side_effect=fail):self.assertEqual(self.f.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)['result'],'ERR_INVALID_PARAM')
        self.assertEqual(list(self.conn.execute('select key,value from meta order by key')),before)
        self.assertEqual(self.blob_rows(),[]);self.assertTrue(self.f.g.stored_tournament()['active']['started'])
        self.assertEqual(self.f.g.logic.handle('CMD_GET_VSCOM_GAME_RESULT',request)['result'],'NOERR')
        self.assertTrue(self.blob_rows())

    def test_corruption_missing_blob_binding_and_summary_disagreement_fail_without_redraw(self):
        active=self.f.start();_,saved=self.f.lose(active)
        row=next(f for f in saved['fixtures']if f['id']==active['fixture_id']);reference=row['simulation_v1']['blob_v1']
        key=reference['key'];payload=self.conn.execute('select value from meta where key=?',(key,)).fetchone()[0]
        with self.conn:self.conn.execute('update meta set value=? where key=?',(payload[:-1]+bytes([payload[-1]^1]),key))
        with self.assertRaises(ValueError):rt.hydrate_contract(self.conn,saved,row)
        with self.conn:self.conn.execute('update meta set value=? where key=?',(payload,key))
        changed=copy.deepcopy(row);changed['simulation_v1']['seeds']['lineup']+=1
        with self.assertRaisesRegex(ValueError,'摘要'):rt.hydrate_contract(self.conn,saved,changed)
        changed=copy.deepcopy(row);changed['id']+=1
        with self.assertRaisesRegex(ValueError,'不属于'):rt.hydrate_contract(self.conn,saved,changed)
        with self.conn:self.conn.execute('delete from meta where key=?',(key,))
        with self.assertRaisesRegex(ValueError,'缺失'):rt.hydrate_contract(self.conn,saved,row)
        self.assertEqual(self.f.g.stored_tournament(),saved)

    def test_legacy_full_contract_is_readable_and_unsettled_start_is_never_compacted(self):
        active=self.f.start();current=self.f.g.stored_tournament();row=next(f for f in current['fixtures']if f['id']==active['fixture_id'])
        old=copy.deepcopy(row['simulation_v1']);self.assertEqual(rt.hydrate_contract(self.conn,current,row),old)
        with self.conn:
            self.conn.execute('begin immediate');rt.compact_contracts(self.conn,current,[row['id']])
        self.assertEqual(row['simulation_v1'],old);self.assertEqual(self.blob_rows(),[])
        self.assertEqual(self.f.g.stored_tournament()['active'],current['active'])

    def test_oversized_reference_is_rejected_before_blob_fetch_and_stored_length_is_guarded(self):
        active=self.f.start();_,saved=self.f.lose(active)
        row=next(f for f in saved['fixtures']if f['id']==active['fixture_id']);changed=copy.deepcopy(row)
        changed['simulation_v1']['blob_v1']['compressed_bytes']=rt.MAX_CONTRACT_BYTES*2
        class NoFetch:
            def execute(self,*args):raise AssertionError('oversized reference reached SQLite')
        with self.assertRaisesRegex(ValueError,'压缩长度'):rt.hydrate_contract(NoFetch(),saved,changed)
        reference=row['simulation_v1']['blob_v1']
        with self.conn:self.conn.execute('update meta set value=zeroblob(?) where key=?',(2*1024*1024,reference['key']))
        statements=[];self.conn.set_trace_callback(statements.append)
        try:
            with self.assertRaisesRegex(ValueError,'长度'):rt.hydrate_contract(self.conn,saved,row)
        finally:self.conn.set_trace_callback(None)
        self.assertTrue(any("typeof(value)='blob'"in sql and'length(value)='in sql for sql in statements))

    def test_32512_complete_fixture_main_state_stays_small_without_dropping_compressed_audit(self):
        global SCALE_MEASUREMENT
        # Legal maximum four-cycle 128-team round-robin match count. Storage
        # stress uses repeated deterministic wire-shaped vectors, not 32k model
        # draws. Other tests above use real clubs and full native/model audits.
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('create table meta(key primary key,value)')
        parameters=[80]*147;players=[{'gameplayer_id':{'id':1000+i,'serial':0},'parameters':parameters}for i in range(23)]
        contract={'model_version':'storage-test','strength_version':'storage-test','seeds':{'lineup':1,'regulation':2,'extra_time':3,'penalties':4},
            'frozen':True,'settled':True,'source':'cpu','xg':[1.3,1.3],
            'ratings':{side:dict(attack=80,creation=80,defence=80,goalkeeping=80,depth=80,audit={'players':players})for side in('home','away')},
            'teams':{side:{'player_list':players,'coach_data':{'coach_id':1},'formation':[[1,2]]*11}for side in('home','away')},
            'result':{'final_score':[1,0],'raw_score':[1,0],'corrected_score':[1,0],'extra_time_score':[0,0],'penalties':None}}
        current={'definition':{'uuid':'storage-scale'},'run_id':'storage-run',
            'fixtures':[dict(id=i+1,home=1,away=2,played=True,score=[1,0],simulation_v1=contract)for i in range(32512)]}
        raw_size=len(json.dumps(contract).encode());self.assertGreater(raw_size*32512,1_000_000_000)
        with conn:
            conn.execute('begin immediate');rt.compact_contracts(conn,current,range(1,32513));rt.put(conn,'scale-state',current)
        size=len(conn.execute('select value from meta where key=?',('scale-state',)).fetchone()[0].encode())
        self.assertLess(size,45*1024*1024)
        self.assertEqual(conn.execute('select count(*)from meta where key like ?',(rt.BLOB_PREFIX+'%',)).fetchone()[0],32512)
        for index in(0,16256,32511):
            full=rt.hydrate_contract(conn,current,current['fixtures'][index])
            self.assertEqual(full,contract)
        self.assertTrue(all('teams'not in f['simulation_v1']for f in current['fixtures']))
        SCALE_MEASUREMENT=dict(fixtures=32512,expanded_contract_bytes=raw_size*32512,main_state_bytes=size,
            compressed_blob_bytes=conn.execute('select sum(length(value))from meta where key like ?',(rt.BLOB_PREFIX+'%',)).fetchone()[0],
            sample_hydration_exact=True,all_blob_rows_written=True,
            scope='Storage stress with repeated deterministic 23-player 147-parameter wire-shaped vectors and complete audits; no claim of 32k model draws.')


if __name__=='__main__':unittest.main()
