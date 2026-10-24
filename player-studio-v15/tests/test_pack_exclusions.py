from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,packs
from personal_runtime import apply_packs

class PackExclusionsTests(unittest.TestCase):
    def test_random_and_compile_follow_version_exclusions_without_editing_saved_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=sqlite3.connect(root/'library.sqlite3');db.execute('create table players(id text,name text,card_type text,payload text)')
            for cid in ('1','2'):
                params=[0]*147;params[47]=180;db.execute('insert into players values(?,?,?,?)',(cid,'Player '+cid,'Epic',json.dumps({'parameters':params})))
            db.commit();db.close()
            (root/'pack-exclusions.json').write_text(json.dumps({'2':{'name':'Blocked','reason':'dummy'}}))
            (root/'native-pack-template.json').write_bytes((app.RESOURCE/'native-pack-template.json').read_bytes())
            self.assertEqual(packs.random_options(root),[{'card_type':'Epic','available':1}])
            self.assertEqual(packs.random_members(root,{'members':[],'quotas':[{'card_type':'Epic','count':1}]})['rows'][0]['id'],'1')
            p={'uuid':str(uuid.uuid4()),'name':'Example','members':[{'kind':'original','id':cid,'name':'Player '+cid,'weight':1} for cid in ('1','2')]};before=copy.deepcopy(p)
            result=packs.compile_packs([p],[],root)[0]
            self.assertEqual([m['card_id'] for m in result['members']],['1']);self.assertEqual(result['skipped_members'][0]['card_id'],'2');self.assertEqual(p,before)
            p['members']=p['members'][1:]
            with self.assertRaisesRegex(ValueError,'没有可用球员'):packs.compile_packs([p],[],root)

    def test_china_edition_is_allowed_but_other_exclusions_remain(self):
        from pack_catalogue import from_archive,blocked_only
        class Archive:
            def namelist(self):return ['assets/gateway-release/outputs/reference/excluded_card_catalog.json']
            def read(self,path):return json.dumps({'1':{'name':'China card','type':'China edition'},'2':{'name':'Dummy','type':'dummy'}}).encode()
        self.assertEqual(set(from_archive(Archive())),{'2'})
        self.assertEqual(set(blocked_only({'1':{'reason':'China edition'},'2':{'reason':'Not used'}})),{'2'})

    def test_legacy_runtime_skips_blocked_rows_preserves_guards_and_draw_receipts(self):
        c=sqlite3.connect(':memory:');c.executescript('''
        create table meta(key text primary key,value text);
        create table managed_agents(agent_id integer primary key,name text,enabled integer,replacement integer,mode text);
        create table agents(agent_id integer primary key,json text);
        create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
        create table managed_members(agent_id integer,card_id text,weight integer);
        create table excluded_catalog_ids(card_id text primary key,reason text);
        insert into excluded_catalog_ids values('2','dummy');
        create trigger guard before insert on managed_cards when NEW.card_id in(select card_id from excluded_catalog_ids) begin select raise(ignore); end;
        create table receipts(receipt text);insert into receipts values('old draw');
        ''')
        p={'uuid':'pack','name':'Example','agent_id':1,'enabled':True,'replacement':False,'price':{'agent_id':1},'agent':{'agent_id':1},'members':[{'card_id':i,'weight':3,'payload':{},'card_type':'Epic','subtype':''} for i in ('1','2')]}
        for _ in range(2):apply_packs(c,[p])
        self.assertEqual(c.execute('select card_id from managed_members').fetchall(),[('1',)])
        self.assertEqual(c.execute('select * from receipts').fetchall(),[('old draw',)])
        self.assertTrue(c.execute("select 1 from sqlite_master where type='trigger' and name='guard'").fetchone())
        self.assertEqual(json.loads(c.execute("select value from meta where key='personal_pack_skipped_v1'").fetchone()[0])[0]['card_id'],'2')
        p['members']=p['members'][1:];apply_packs(c,[p]);self.assertEqual(c.execute('select enabled from managed_agents').fetchone()[0],0)
        self.assertEqual(c.execute('select * from agents').fetchall(),[])

if __name__=='__main__':unittest.main()
