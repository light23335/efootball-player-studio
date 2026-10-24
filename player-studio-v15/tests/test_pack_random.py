from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import packs

class RandomPackTests(unittest.TestCase):
    def test_quotas_exclude_existing_and_placeholders_and_keep_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=sqlite3.connect(root/'library.sqlite3')
            db.execute('create table players(id text,name text,card_type text,payload text)')
            for pid,kind,height in [('1','BigTime',180),('2','BigTime',181),('3','BigTime',182),('4','Epic',183),('5','BigTime',0)]:
                parameters=[0]*147;parameters[47]=height
                db.execute('insert into players values(?,?,?,?)',(pid,'Player '+pid,kind,json.dumps({'parameters':parameters})))
            db.commit();db.close();before=(root/'library.sqlite3').read_bytes()
            existing=[{'kind':'original','id':'1','name':'existing','weight':7}]
            request={'members':existing,'quotas':[{'card_type':'BigTime','count':2},{'card_type':'Epic','count':1}]}
            saved=copy.deepcopy(request);result=packs.random_members(root,request)
            self.assertEqual({r['id'] for r in result['rows']},{'2','3','4'})
            self.assertEqual(result['count'],3);self.assertEqual(request,saved)
            self.assertTrue(all(r['weight']==1 for r in result['rows']))
            self.assertEqual(packs.random_options(root),[{'card_type':'BigTime','available':3},{'card_type':'Epic','available':1}])
            self.assertEqual((root/'library.sqlite3').read_bytes(),before)
            request['quotas'][0]['count']=3
            with self.assertRaisesRegex(ValueError,'可添加 2'):packs.random_members(root,request)
            for invalid in (True,-1,1.5,2001):
                request['quotas'][0]['count']=invalid
                with self.assertRaises(ValueError):packs.random_members(root,request)
            for quotas in ([{'card_type':'missing','count':1}], [{'card_type':'Epic','count':0}], [{'card_type':'Epic','count':1}]*2):
                request['quotas']=quotas
                with self.assertRaises(ValueError):packs.random_members(root,request)
            request={'members':existing*2000,'quotas':[{'card_type':'Epic','count':1}]}
            with self.assertRaisesRegex(ValueError,'最多 2000'):packs.random_members(root,request)

if __name__=='__main__':unittest.main()
