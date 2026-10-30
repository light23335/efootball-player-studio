from pathlib import Path
import copy,hashlib,json,sqlite3,sys,tempfile,threading,types,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalogue_trash import change,active,load,restore_catalogue
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

if __name__=='__main__':unittest.main()
