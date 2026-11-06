"""Startup catalogue recovery must never grant cards or rewrite owned progress."""
from pathlib import Path
import copy,hashlib,io,json,sqlite3,sys,tempfile,types,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import personal_runtime as runtime
from catalogue_trash import patch_seed,source_registrations

class BuiltinCatalogueRecycleTests(unittest.TestCase):
    ids=tuple(range(89136418985301,89136418985318))
    def setUp(self):
        self.module=types.SimpleNamespace(MARKER='e213_new_cards_pack_four_native_v4',AGENT_ID=7030)
        self.calls=0;self.fail=False;self.document={'catalogue_recycle_bin':[]}
        self.cards=[{'payload':{'gameplayer_id':{'id':cid,'serial':0},'name':'card '+str(cid),
            'parameters':[65]*147,'level_info':{'level':1,'level_limit':33}},'card_type':'Epic','subtype':'Big Time'}for cid in self.ids]
        self.source=lambda:{'config':{'draw_card_ids':list(self.ids[:-1])},'cards':copy.deepcopy(self.cards)}
        def original(conn):
            self.calls+=1
            if conn.in_transaction:return {'status':'waiting_for_transaction'}
            for cid in self.ids:
                row=conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()
                if not row or json.loads(row[0])['gameplayer_id']['id']!=cid:raise ValueError('registration incomplete: '+str(cid))
                if cid!=self.ids[-1] and not conn.execute('select 1 from managed_members where agent_id=7030 and card_id=?',(str(cid),)).fetchone():raise ValueError('membership incomplete')
            if self.fail:raise ValueError('unrelated native validation failure')
            if not conn.execute('select 1 from meta where key=?',(self.module.MARKER,)).fetchone():
                with conn:conn.execute('insert into meta values(?,?)',(self.module.MARKER,'original-completed'))
            return {'status':'ready'}
        self.original=original;self.module.install_once=original
    def db(self,path=':memory:'):
        conn=sqlite3.connect(path)
        conn.executescript('create table meta(key text primary key,value);create table managed_cards(card_id text primary key,fingerprint,payload,card_type,subtype,evidence);create table managed_members(agent_id,card_id,weight,primary key(agent_id,card_id));create table gameplayers(id,serial,json);create table careerplan(id,serial,category,points);create table squads(squad_id,json);')
        for card in self.cards:
            cid=card['payload']['gameplayer_id']['id'];raw=runtime.compact(card['payload'])
            conn.execute('insert into managed_cards values(?,?,?,?,?,?)',(str(cid),hashlib.sha256(raw.encode()).hexdigest(),raw,'Epic','Big Time','original'))
            if cid!=self.ids[-1]:conn.execute('insert into managed_members values(7030,?,3)',(str(cid),))
            owned={'gameplayer_id':{'id':cid,'serial':7},'level_info':{'level':25,'exp_total':90000,'customize_point':3},
                'additional_skill_id':[7,18],'games':88,'goal':20,'user_unknown':{'keep':True}}
            conn.execute('insert into gameplayers values(?,?,?)',(cid,7,runtime.compact(owned)))
            conn.execute('insert into careerplan values(?,7,"shoot",20)',(cid,))
        conn.execute('insert into squads values(1,?)',(json.dumps({'progress':'keep','players':list(self.ids)}),))
        conn.execute('insert into meta values(?,?)',(self.module.MARKER,'original-completed'))
        conn.execute('insert into meta values("league-progress","keep-results")');conn.commit()
        self.addCleanup(conn.close);return conn
    def snapshot(self,conn):
        return {t:conn.execute('select * from '+t+' order by rowid').fetchall()for t in('gameplayers','careerplan','squads')}
    def install(self,corrections=()):runtime.install_builtin_catalogue_repair(self.module,lambda:self.document,self.source,corrections)
    def recycle(self,conn,ids,archive=True):
        self.document['catalogue_recycle_bin']=[{'id':str(cid),'name':'recycled'}for cid in ids]
        with conn:
            if archive:runtime.apply_catalogue_recycle(conn,self.document['catalogue_recycle_bin'],remove_owned=False)
            else:
                for cid in ids:
                    conn.execute('delete from managed_cards where card_id=?',(str(cid),))
                    conn.execute('delete from managed_members where card_id=?',(str(cid),))
    def test_each_source_card_can_be_recycled_without_startup_failure_or_owned_changes(self):
        self.install()
        for cid in self.ids:
            with self.subTest(cid=cid):
                conn=self.db();before=self.snapshot(conn);self.recycle(conn,[cid])
                self.assertEqual(self.module.install_once(conn)['status'],'ready')
                self.assertIsNone(conn.execute('select 1 from managed_cards where card_id=?',(str(cid),)).fetchone())
                self.assertIsNone(conn.execute('select 1 from managed_members where card_id=?',(str(cid),)).fetchone())
                self.assertEqual(self.snapshot(conn),before)
                self.assertEqual(conn.execute('select value from meta where key=?',(self.module.MARKER,)).fetchone()[0],'original-completed')
    def test_all_source_cards_can_be_recycled_and_old_unarchived_seed_is_repaired(self):
        conn=self.db();before=self.snapshot(conn);self.recycle(conn,self.ids,archive=False);self.install()
        self.assertEqual(self.module.install_once(conn)['status'],'ready')
        self.assertEqual(conn.execute('select count(*) from managed_cards').fetchone()[0],0)
        self.assertEqual(conn.execute('select count(*) from managed_members').fetchone()[0],0)
        self.assertEqual(self.snapshot(conn),before)
    def test_missing_active_catalogue_is_repaired_without_grant_or_level_reset(self):
        conn=self.db();before=self.snapshot(conn);cid=self.ids[3]
        with conn:conn.execute('delete from managed_cards where card_id=?',(str(cid),));conn.execute('delete from managed_members where card_id=?',(str(cid),))
        self.install();self.module.install_once(conn)
        self.assertEqual(json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0])['gameplayer_id']['id'],cid)
        self.assertEqual(self.snapshot(conn),before)
    def test_invalid_json_wrong_id_and_string_id_are_repaired_and_previous_records_retained(self):
        self.install()
        for raw in ('{broken','null',json.dumps({'gameplayer_id':{'id':1}}),json.dumps({'gameplayer_id':{'id':str(self.ids[0])}})):
            conn=self.db();before=self.snapshot(conn)
            with conn:conn.execute('update managed_cards set payload=? where card_id=?',(raw,str(self.ids[0])))
            self.module.install_once(conn)
            audit=json.loads(conn.execute('select value from meta where key="studio_builtin_catalogue_repairs_v1"').fetchone()[0])
            self.assertEqual(audit[str(self.ids[0])][2],raw);self.assertEqual(self.snapshot(conn),before)
    def test_valid_manual_catalogue_edits_are_never_overwritten(self):
        conn=self.db();cid=self.ids[1];owned=self.snapshot(conn)
        with conn:
            row=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0]);row['manual']='keep'
            conn.execute('update managed_cards set payload=? where card_id=?',(runtime.compact(row),str(cid)))
        before=conn.execute('select * from managed_cards').fetchall();self.install();self.module.install_once(conn)
        self.assertEqual(conn.execute('select * from managed_cards').fetchall(),before);self.assertEqual(self.snapshot(conn),owned)
    def test_archive_restores_actual_definition_and_memberships_without_regrant(self):
        conn=self.db();cid=self.ids[4]
        with conn:
            p=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0]);p['personal_edit']='keep'
            conn.execute('update managed_cards set payload=? where card_id=?',(runtime.compact(p),str(cid)))
        self.recycle(conn,[cid]);self.install();self.module.install_once(conn)
        owned=self.snapshot(conn);self.document['catalogue_recycle_bin']=[];self.module.install_once(conn)
        restored=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0])
        self.assertEqual(restored['personal_edit'],'keep');self.assertEqual(self.snapshot(conn),owned)
        self.assertEqual(conn.execute('select weight from managed_members where agent_id=7030 and card_id=?',(str(cid),)).fetchone()[0],3)
    def test_native_failure_propagates_and_recycled_cards_stay_excluded(self):
        conn=self.db();self.recycle(conn,[self.ids[0]]);owned=self.snapshot(conn);self.install();self.fail=True
        with self.assertRaisesRegex(ValueError,'unrelated native'):self.module.install_once(conn)
        self.assertFalse(conn.in_transaction);self.assertEqual(self.snapshot(conn),owned)
        self.assertIsNone(conn.execute('select 1 from managed_cards where card_id=?',(str(self.ids[0]),)).fetchone())
    def test_pending_transaction_is_never_committed_or_rolled_back(self):
        conn=self.db();self.install();conn.execute('insert into meta values("pending","keep")')
        self.assertEqual(self.module.install_once(conn),{'status':'waiting_for_transaction'});self.assertTrue(conn.in_transaction)
        conn.rollback();self.assertIsNone(conn.execute('select value from meta where key="pending"').fetchone())
    def test_repeated_startup_and_installer_refresh_do_not_wrap_twice(self):
        conn=self.db();self.recycle(conn,[self.ids[0]]);owned=self.snapshot(conn);self.install();wrapped=self.module.install_once
        for _ in range(5):self.install();self.module.install_once(conn)
        self.assertIs(self.module.install_once,wrapped);self.assertEqual(self.calls,5);self.assertEqual(self.snapshot(conn),owned)
    def test_fresh_registration_remains_owned_by_original_migration(self):
        conn=self.db();owned=self.snapshot(conn)
        with conn:conn.execute('delete from meta where key=?',(self.module.MARKER,));conn.execute('delete from managed_cards');conn.execute('delete from managed_members')
        self.install();self.module.install_once(conn)
        self.assertEqual(conn.execute('select value from meta where key=?',(self.module.MARKER,)).fetchone()[0],'original-completed')
        self.assertEqual(self.snapshot(conn),owned)
        self.assertIsNone(conn.execute('select 1 from managed_members where card_id=?',(str(self.ids[-1]),)).fetchone())
    def test_completed_catalogue_corrections_apply_only_to_recovered_source_records(self):
        conn=self.db();cid=self.ids[0]
        with conn:conn.execute('delete from managed_cards where card_id=?',(str(cid),));conn.execute('insert into meta values("correction","done")')
        correction=types.SimpleNamespace(MARKER='correction',correct=lambda p:dict(p,corrected=True))
        self.install((correction,));self.module.install_once(conn)
        for value in self.ids[:2]:
            p=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(value),)).fetchone()[0])
            self.assertEqual(p.get('corrected',False),value==cid)
    def test_full_save_backup_is_made_before_catalogue_repair_and_is_not_overwritten(self):
        with tempfile.TemporaryDirectory()as tmp:
            conn=self.db(Path(tmp)/'club.sqlite3');owned=self.snapshot(conn);self.recycle(conn,[self.ids[0]])
            self.install();self.module.install_once(conn)
            backup=next((Path(tmp)/'studio-builtin-catalogue-backups').glob('*.sqlite3'));raw=backup.read_bytes()
            saved=sqlite3.connect(backup)
            try:
                self.assertEqual(self.snapshot(saved),owned)
                self.assertIsNone(saved.execute('select 1 from managed_cards where card_id=?',(str(self.ids[0]),)).fetchone())
            finally:saved.close()
            self.module.install_once(conn);self.assertEqual(backup.read_bytes(),raw);conn.close()
    def test_backup_failure_prevents_catalogue_writes(self):
        conn=self.db();self.recycle(conn,[self.ids[0]]);before=list(conn.iterdump());self.install()
        with patch.object(runtime,'backup_builtin_catalogue',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.module.install_once(conn)
        self.assertEqual(list(conn.iterdump()),before)
    def test_seed_recycle_archives_definitions_and_startup_repair_does_not_regrant(self):
        conn=self.db();store=types.SimpleNamespace()
        with tempfile.TemporaryDirectory()as tmp:
            store.root=Path(tmp)
            items={str(cid):{'id':str(cid),'name':'card','trashed':True}for cid in self.ids}
            (store.root/'catalogue-trash.json').write_text(json.dumps({'format':'studio-catalogue-trash-v1','items':items}),'utf8')
            raw=io.BytesIO()
            with zipfile.ZipFile(raw,'w')as z:z.writestr('assets/gateway-release/outputs/efootball/local-club.sqlite3',conn.serialize())
            with zipfile.ZipFile(raw)as z:replacements=patch_seed(z,store)
            fixed=sqlite3.connect(':memory:');self.addCleanup(fixed.close);fixed.deserialize(next(iter(replacements.values())))
            self.assertEqual(fixed.execute('select count(*) from gameplayers').fetchone()[0],0)
            archived=json.loads(fixed.execute('select value from meta where key="studio_recycled_catalogue_v1"').fetchone()[0]);self.assertEqual(len(archived),len(self.ids))
            self.document['catalogue_recycle_bin']=[{'id':cid}for cid in items];self.install();self.module.install_once(fixed)
            self.assertEqual(fixed.execute('select count(*) from managed_cards').fetchone()[0],0)
            self.assertEqual(fixed.execute('select count(*) from gameplayers').fetchone()[0],0)

    def test_legacy_restore_with_correct_id_but_unknown_type_is_migrated_without_owned_changes(self):
        conn=self.db();owned=self.snapshot(conn);cid=self.ids[0]
        with conn:
            conn.execute('update managed_cards set card_type="UNKNOWN",subtype=NULL,evidence="studio-recycle-restored" where card_id=?',(str(cid),))
        self.install();self.module.install_once(conn)
        row=conn.execute('select card_type,subtype,evidence from managed_cards where card_id=?',(str(cid),)).fetchone()
        self.assertEqual(row[:2],('Epic','Big Time'));self.assertNotEqual(row[2],'studio-recycle-restored')
        self.assertEqual(self.snapshot(conn),owned)
        audit=json.loads(conn.execute('select value from meta where key="studio_builtin_catalogue_repairs_v1"').fetchone()[0])
        self.assertEqual(audit[str(cid)][3:],["UNKNOWN",None,"studio-recycle-restored"])

    def test_identity_only_display_payload_cannot_pass_startup_contract(self):
        conn=self.db();owned=self.snapshot(conn);cid=self.ids[0]
        with conn:conn.execute('update managed_cards set payload=? where card_id=?',(json.dumps({'gameplayer_id':{'id':cid,'serial':0}}),str(cid)))
        self.install();self.module.install_once(conn)
        raw=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0])
        self.assertIn('parameters',raw);self.assertIn('level_info',raw);self.assertEqual(self.snapshot(conn),owned)

    def test_recycle_restore_export_preserves_registered_definition_and_all_members(self):
        conn=self.db();cid=str(self.ids[0]);owned=self.snapshot(conn)
        with conn:conn.execute('insert into managed_members values(999,?,9)',(cid,))
        before=conn.execute('select * from managed_cards where card_id=?',(cid,)).fetchone()
        members=conn.execute('select * from managed_members where card_id=? order by agent_id',(cid,)).fetchall()
        original=io.BytesIO()
        with zipfile.ZipFile(original,'w')as z:z.writestr('assets/gateway-release/outputs/efootball/local-club.sqlite3',conn.serialize())
        with zipfile.ZipFile(original)as z:registration=source_registrations(z,[cid])[cid]
        self.recycle(conn,[int(cid)])
        seed=io.BytesIO()
        with zipfile.ZipFile(seed,'w')as z:z.writestr('assets/gateway-release/outputs/efootball/local-club.sqlite3',conn.serialize())
        with tempfile.TemporaryDirectory()as tmp:
            store=types.SimpleNamespace(root=Path(tmp))
            item={'id':cid,'name':'restored','trashed':False,'snapshot':{'card_type':'UNKNOWN','payload':'{}'},'registration':registration}
            (store.root/'catalogue-trash.json').write_text(json.dumps({'format':'studio-catalogue-trash-v1','items':{cid:item}}),'utf8')
            with zipfile.ZipFile(seed)as z:replacements=patch_seed(z,store)
        fixed=sqlite3.connect(':memory:');self.addCleanup(fixed.close);fixed.deserialize(next(iter(replacements.values())))
        self.assertEqual(fixed.execute('select * from managed_cards where card_id=?',(cid,)).fetchone(),before)
        self.assertEqual(fixed.execute('select * from managed_members where card_id=? order by agent_id',(cid,)).fetchall(),members)
        self.document['catalogue_recycle_bin']=[];self.install();self.module.install_once(fixed)
        self.assertEqual(self.snapshot(fixed),owned)

    def test_old_bin_without_registration_never_invents_unknown_card_before_first_start(self):
        for registered in (False,True):
            with self.subTest(registered=registered):
                conn=self.db();owned=self.snapshot(conn);cid=str(self.ids[0])
                with conn:
                    conn.execute('delete from managed_cards where card_id=?',(cid,));conn.execute('delete from managed_members where card_id=?',(cid,))
                    if not registered:conn.execute('delete from meta where key=?',(self.module.MARKER,))
                seed=io.BytesIO()
                with zipfile.ZipFile(seed,'w')as z:z.writestr('assets/gateway-release/outputs/efootball/local-club.sqlite3',conn.serialize())
                with tempfile.TemporaryDirectory()as tmp:
                    store=types.SimpleNamespace(root=Path(tmp));item={'id':cid,'name':'restored','trashed':False,
                        'snapshot':{'card_type':'UNKNOWN','payload':json.dumps({'gameplayer_id':{'id':int(cid),'serial':0}})}}
                    (store.root/'catalogue-trash.json').write_text(json.dumps({'format':'studio-catalogue-trash-v1','items':{cid:item}}),'utf8')
                    with zipfile.ZipFile(seed)as z:fixed_bytes=next(iter(patch_seed(z,store).values()))
                fixed=sqlite3.connect(':memory:');self.addCleanup(fixed.close);fixed.deserialize(fixed_bytes)
                self.assertIsNone(fixed.execute('select * from managed_cards where card_id=?',(cid,)).fetchone())
                self.install();self.module.install_once(fixed)
                self.assertEqual(fixed.execute('select card_type,subtype from managed_cards where card_id=?',(cid,)).fetchone(),('Epic','Big Time'))
                self.assertEqual(self.snapshot(fixed),owned)

    def test_pending_six_registrar_sees_exact_definition_before_old_completed_corrections(self):
        conn=self.db();cid=self.ids[0];owned=self.snapshot(conn);canonical=runtime.compact(self.cards[0]['payload'])
        with conn:
            conn.execute('update managed_cards set card_type="UNKNOWN",subtype=NULL,evidence="studio-recycle-restored" where card_id=?',(str(cid),))
            conn.execute('insert into meta values("correction","done")')
        registrar=types.SimpleNamespace(MARKER='six-registry',CARDS=[{'id':cid}])
        correction=types.SimpleNamespace(MARKER='correction',correct=lambda p:dict(p,corrected=True))
        original=self.module.install_once
        def strict(conn):
            self.assertEqual(conn.execute('select fingerprint,payload,card_type,subtype from managed_cards where card_id=?',(str(cid),)).fetchone(),
                (hashlib.sha256(canonical.encode()).hexdigest(),canonical,'Epic','Big Time'))
            result=original(conn)
            with conn:conn.execute('insert or ignore into meta values("six-registry","done")')
            return result
        self.module.install_once=strict
        runtime.install_builtin_catalogue_repair(self.module,lambda:self.document,self.source,(correction,),registrars=(registrar,))
        self.module.install_once(conn)
        payload=json.loads(conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()[0])
        self.assertTrue(payload['corrected']);self.assertEqual(self.snapshot(conn),owned)

if __name__=='__main__':unittest.main()
