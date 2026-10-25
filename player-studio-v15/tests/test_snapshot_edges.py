from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest,uuid
from contextlib import closing
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import player_package as pp

class SnapshotEdgeTests(unittest.TestCase):
    def test_unknown_unselected_stock_progress_is_preserved_and_zero_alias_keeps_target_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.sqlite3';target=root/'target.sqlite3';uid=str(uuid.uuid4());cid=99;serial=8
            player={'gameplayer_id':{'id':cid,'serial':serial},'_personal_player_uuid':uid,'parameters':[40]*147,
                    'level_info':{'level':2,'level_limit':35,'exp_total':200,'customize_point':1},'additional_skill_id':[1,2]}
            stock={'gameplayer_id':{'id':12,'serial':2},'parameters':[0]*147,'level_info':{'level':1,'level_limit':None}}
            with closing(sqlite3.connect(source)) as c, c:
                c.executescript('''create table meta(key text primary key,value text);
                create table gameplayers(id integer,serial integer,json text,source text,acquired_at text,primary key(id,serial));
                create table careerplan(id integer,serial integer,category text,points integer,at text);
                create table squads(squad_id integer,json text);create table warehouse(id integer,serial integer);
                create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
                create table managed_serials(card_id text primary key,next_serial integer);
                create table owned_identity_aliases(id integer,old_serial integer,new_serial integer,primary key(id,old_serial));''')
                c.execute('insert into meta values(?,?)',(pp.REGISTRY_KEY,json.dumps({uid:{'card_id':cid,'serial':7,'released':True}})))
                c.execute('insert into meta values("coins","12345")')
                for ident,number,p in ((cid,serial,player),(12,2,stock)):c.execute('insert into gameplayers values(?,?,?,?,?)',(ident,number,json.dumps(p),'test','now'))
                c.execute('insert into careerplan values(?,?,?,?,?)',(cid,serial,'shooting',1,'now'))
                c.execute('insert into managed_cards values(?,?,?,?,?,?)',(str(cid),'hash',json.dumps(player),'BigTime','','personal-player-studio:'+uid))
                c.execute('insert into owned_identity_aliases values(?,?,?)',(cid,0,serial))
            import shutil;shutil.copy2(source,target)
            with closing(sqlite3.connect(target)) as c, c:c.execute('delete from gameplayers where id=?',(cid,));c.execute('delete from careerplan where id=?',(cid,));c.execute('update owned_identity_aliases set new_serial=7 where id=?',(cid,))
            package=root/'player.efplayer';output=root/'restored.sqlite3'
            with patch('player_package.native_fingerprint',return_value={'native_engine_sha256':'same','release_id':'test'}):
                pp.export_player(source,'source.apk',cid,serial,package);report=pp.migration(target,package,'target.apk',output,'package')
                with closing(sqlite3.connect(output)) as c, c:
                    self.assertEqual(json.loads(c.execute('select json from gameplayers where id=?',(cid,)).fetchone()[0]),player)
                    self.assertEqual(json.loads(c.execute('select json from gameplayers where id=12').fetchone()[0]),stock)
                    self.assertEqual(c.execute('select new_serial from owned_identity_aliases where id=? and old_serial=0',(cid,)).fetchone()[0],7)
                    self.assertEqual(c.execute('select value from meta where key="coins"').fetchone()[0],'12345')
                self.assertEqual(len(report['preserved_target_zero_serial_aliases']),1)
                with self.assertRaises(pp.PackageError):pp.export_player(source,'source.apk',12,2,root/'unknown.efplayer')
    def test_partial_personal_progress_is_still_rejected(self):
        p={'gameplayer_id':{'id':99,'serial':8},'_personal_player_uuid':str(uuid.uuid4()),'parameters':[40]*147,'level_info':{'level':1,'level_limit':None}}
        with self.assertRaises(pp.PackageError):pp.check_player(p,99,8,True)

if __name__=='__main__':unittest.main()
