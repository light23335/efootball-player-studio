from pathlib import Path
import copy,hashlib,io,json,sqlite3,sys,tempfile,threading,types,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalogue_trash import change,active,load,restore_catalogue,patch_seed
from personal_runtime import apply_catalogue_recycle,backup_recycled_owned

class RecycleTests(unittest.TestCase):
    def make_db(self,conn):
        conn.executescript('create table meta(key primary key,value);create table managed_cards(card_id primary key,fingerprint,payload,card_type,subtype,evidence);create table managed_members(agent_id,card_id,weight,primary key(agent_id,card_id));create table gameplayers(id,serial,json);create table careerplan(id,serial,category,points,at);create table player_pool(id,serial,rarity,json,source);create table owned_identity_aliases(id,old_serial,new_serial);create table squads(squad_id primary key,json);')
        conn.executemany('insert into managed_cards values(?,?,?,?,?,?)',[(str(i),'fp','{"name":"same name"}','BigTime',None,'stock')for i in (10,20)])
        conn.executemany('insert into managed_members values(?,?,?)',[(1,str(i),1)for i in (10,20)])
        conn.executemany('insert into gameplayers values(?,?,?)',[(i,1,'owned '+str(i))for i in (10,20)])
        conn.execute('insert into careerplan values(10,1,"shoot",5,"now")');conn.execute('insert into owned_identity_aliases values(10,0,1)')
        data={'squad_data':{'player_list':[{'gameplayer_id':{'id':10,'serial':1}},{'gameplayer_id':{'id':20,'serial':1}}],
          'squad_gameplan':{'formation':[{'coach_link_data':[{'key_member_Id':0,'link_member_Id':1,'is_link_on':'YES'}]}],
          'match_plan_settings':{'order':[0,1,255],'captain':1,'set_piece_taker':[0,1],'df_overlap_setplay':[255,1]}}}}
        conn.execute('insert into squads values(1,?)',(json.dumps(data),));conn.commit()
    def test_owned_removal_is_exact_card_and_squad_indices_are_repaired(self):
        conn=sqlite3.connect(':memory:');self.make_db(conn)
        apply_catalogue_recycle(conn,[{'id':'10','name':'same name'}])
        self.assertEqual(conn.execute('select id from gameplayers').fetchall(),[(20,)])
        self.assertEqual(conn.execute('select count(*)from careerplan').fetchone()[0],0)
        self.assertEqual(conn.execute('select count(*)from owned_identity_aliases').fetchone()[0],0)
        squad=json.loads(conn.execute('select json from squads').fetchone()[0])['squad_data']
        self.assertEqual(squad['player_list'],[{'gameplayer_id':{'id':20,'serial':1}}])
        self.assertEqual(squad['squad_gameplan']['match_plan_settings']['order'],[255,0,255])
        self.assertEqual(squad['squad_gameplan']['match_plan_settings']['captain'],0)
        self.assertEqual(squad['squad_gameplan']['formation'][0]['coach_link_data'][0]['is_link_on'],'NO')
        self.assertEqual(conn.execute('select card_id from managed_cards').fetchall(),[('20',)])
    def test_restore_restores_catalogue_and_members_but_does_not_regrant_owned_card(self):
        conn=sqlite3.connect(':memory:');self.make_db(conn)
        apply_catalogue_recycle(conn,[{'id':'10'}]);apply_catalogue_recycle(conn,[{'id':'10'}]);apply_catalogue_recycle(conn,[])
        self.assertEqual(conn.execute('select card_id from managed_cards order by card_id').fetchall(),[('10',),('20',)])
        self.assertEqual(conn.execute('select card_id from managed_members order by card_id').fetchall(),[('10',),('20',)])
        self.assertEqual(conn.execute('select id from gameplayers').fetchall(),[(20,)])
        self.assertFalse(conn.execute('select * from excluded_catalog_ids').fetchall())
    def test_backup_captures_owned_save_before_removal_and_is_not_overwritten(self):
        with tempfile.TemporaryDirectory()as tmp:
            conn=sqlite3.connect(Path(tmp)/'club.sqlite3');self.make_db(conn)
            backup_recycled_owned(conn,[{'id':'10'}]);backup=next((Path(tmp)/'studio-recycle-backups').glob('*.sqlite3'));before=backup.read_bytes()
            apply_catalogue_recycle(conn,[{'id':'10'}]);conn.commit();backup_recycled_owned(conn,[{'id':'10'}])
            saved=sqlite3.connect(backup)
            try:self.assertEqual(saved.execute('select id from gameplayers order by id').fetchall(),[(10,),(20,)])
            finally:saved.close()
            self.assertEqual(backup.read_bytes(),before);conn.close()
    def test_local_soft_delete_keeps_source_database_and_can_restore(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);resources=root/'resources';resources.mkdir();data=root/'data';data.mkdir()
            path=resources/'library.sqlite3';conn=sqlite3.connect(path);conn.execute('create table players(id text primary key,name,payload)');conn.execute('insert into players values("10","same name","{}")');conn.commit();conn.close()
            store=types.SimpleNamespace(root=data,lock=threading.RLock())
            def db():
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
            library=types.SimpleNamespace(store=store,db=db,resources=resources,root=root/'library',profile={})
            before=path.read_bytes();change(library,{'ids':['10'],'action':'trash'})
            self.assertEqual(set(active(store)),{'10'});self.assertEqual(path.read_bytes(),before)
            change(library,{'ids':['10'],'action':'restore'});self.assertFalse(active(store));self.assertIn('snapshot',load(store)['10'])
    def test_invalid_actions_cannot_change_the_bin(self):
        with tempfile.TemporaryDirectory()as tmp:
            store=types.SimpleNamespace(root=Path(tmp),lock=threading.RLock());library=types.SimpleNamespace(store=store)
            for body in ({'ids':['../x'],'action':'trash'},{'ids':[],'action':'restore'},{'ids':['1'],'action':'delete'}):
                with self.assertRaises(ValueError):change(library,body)
            self.assertFalse((store.root/'catalogue-trash.json').exists())

    def test_change_trash_restore_export_keeps_registry_metadata_instead_of_display_row(self):
        import content_delta
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();browse=root/'browse.sqlite3'
            p={'gameplayer_id':{'id':10,'serial':0},'parameters':[65]*147,'level_info':{'level':1,'level_limit':30}}
            raw=json.dumps(p,sort_keys=True,separators=(',',':'))
            db=sqlite3.connect(browse);db.execute('create table players(id text primary key,name,payload,card_type)')
            db.execute('insert into players values("10","same name",?,"UNKNOWN")',(raw,));db.commit();db.close()
            seed=sqlite3.connect(':memory:');self.addCleanup(seed.close);self.make_db(seed)
            record=('10',hashlib.sha256(raw.encode()).hexdigest(),raw,'Epic','Big Time','original-registry')
            with seed:seed.execute('update managed_cards set fingerprint=?,payload=?,card_type=?,subtype=?,evidence=? where card_id=?',(*record[1:],'10'))
            source=root/'source.apk';seed_name='assets/gateway-release/outputs/efootball/local-club.sqlite3'
            with zipfile.ZipFile(source,'w')as z:
                z.writestr(seed_name,seed.serialize());z.writestr(content_delta.CPKS[1],b'fixture; no native tables in this registry test')
            store=types.SimpleNamespace(root=data,lock=threading.RLock())
            def browse_db():
                result=sqlite3.connect(browse);result.row_factory=sqlite3.Row;return result
            library=types.SimpleNamespace(store=store,db=browse_db,resources=root,root=root/'library',profile={})
            with patch('apk_sources.recorded',return_value={'apk':str(source)}),patch('native_cpk.Cpk'),patch.dict(content_delta.TABLES,{},clear=True):
                change(library,{'ids':['10'],'action':'trash'})
            item=load(store)['10'];self.assertEqual(item['snapshot']['card_type'],'UNKNOWN')
            self.assertEqual(item['registration']['card'],list(record));self.assertEqual(item['registration']['members'],[[1,'10',1]])
            with zipfile.ZipFile(source)as z:trashed=patch_seed(z,store)[seed_name]
            change(library,{'ids':['10'],'action':'restore'})
            exported=io.BytesIO()
            with zipfile.ZipFile(exported,'w')as z:z.writestr(seed_name,trashed)
            with zipfile.ZipFile(exported)as z:restored=patch_seed(z,store)[seed_name]
            fixed=sqlite3.connect(':memory:');self.addCleanup(fixed.close);fixed.deserialize(restored)
            self.assertEqual(fixed.execute('select * from managed_cards where card_id="10"').fetchone(),record)
            self.assertEqual(fixed.execute('select * from managed_members where card_id="10"').fetchall(),[(1,'10',1)])
            self.assertEqual(fixed.execute('select id from gameplayers').fetchall(),[(20,)])

if __name__=='__main__':unittest.main()
