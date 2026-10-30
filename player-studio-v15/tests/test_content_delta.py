from pathlib import Path
import copy,hashlib,json,sqlite3,sys,tempfile,types,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_delta import Delta,merge_table,project_levels,CONTENT
from personal_runtime import apply_content_catalogue


class FakeDelta:
    def blob(self,value):return value

class ContentDeltaTests(unittest.TestCase):
    def make_zip(self,root,entries=None,extra=None,manifest_change=None):
        entries=entries or {'data/test.json':b'{"id":1}'}
        manifest={'format':'efootball-workshop-content-delta','schema_version':1,'base_version':'V17','package_id':'test-v1',
          'import_policy':{'delete_originals':False,'modify_gameplay':False,'ownership_grants':False},
          'entries':[{'path':k,'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()}for k,v in entries.items()]}
        if manifest_change:manifest_change(manifest)
        p=root/'pack.zip'
        with zipfile.ZipFile(p,'w')as z:
            z.writestr('manifest.json',json.dumps(manifest))
            for k,v in entries.items():z.writestr(k,v)
            for k,v in (extra or {}).items():z.writestr(k,v)
        return p
    def test_verifies_all_hashes_without_executing_pack_scripts(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);p=self.make_zip(root,{'validate_delta.py':b'raise RuntimeError("must not execute")'})
            with Delta(p)as d:self.assertEqual(d.summary()['verified_files'],1)
    def test_unlisted_and_traversal_files_rejected(self):
        for extra in ({'unlisted':b'x'},{'../outside':b'x'},{'C:/outside':b'x'},{'nested\\outside':b'x'}):
            with self.subTest(extra=extra),tempfile.TemporaryDirectory()as tmp:
                with self.assertRaises((ValueError,KeyError)):Delta(self.make_zip(Path(tmp),extra=extra))
    def test_tampered_hash_and_gameplay_policy_rejected(self):
        for change in (lambda m:m['entries'][0].update(sha256='0'*64),lambda m:m['import_policy'].update(ownership_grants=True),lambda m:m.update(schema_version=True)):
            with tempfile.TemporaryDirectory()as tmp:
                with self.assertRaises(ValueError):Delta(self.make_zip(Path(tmp),manifest_change=change))
    def test_case_insensitive_duplicate_rejected(self):
        with tempfile.TemporaryDirectory()as tmp:
            with self.assertRaises(ValueError):Delta(self.make_zip(Path(tmp),{'data/test':b'a','DATA/test':b'b'}))
    def record(self,key,fill):return b'\0'*8+key.to_bytes(8,'little')+bytes([fill])*384
    def table(self,base,record):return {'path':'common/etc/pesdb/Player.bin','stride':400,'key_offset':8,'key_bytes':8,
            'base_sha256':hashlib.sha256(base).hexdigest(),'added':[{'key':'2','record':record}]}
    def test_exact_idempotent_addition_keeps_original_and_diy_bytes(self):
        base=self.record(1,7);new=self.record(2,8);personal=self.record(3,9);table=self.table(base,new)
        result=merge_table(base+personal,table,FakeDelta(),{3})
        self.assertEqual(result,base+new+personal)
        self.assertEqual(merge_table(result,table,FakeDelta(),{3}),result)
    def test_same_id_different_record_is_conflict(self):
        base=self.record(1,7);new=self.record(2,8)
        with self.assertRaisesRegex(ValueError,'冲突'):merge_table(base+self.record(2,99),self.table(base,new),FakeDelta())
    def test_unknown_base_changes_are_rejected(self):
        base=self.record(1,7);new=self.record(2,8)
        with self.assertRaisesRegex(ValueError,'基底'):merge_table(self.record(1,6),self.table(base,new),FakeDelta())
    def test_removal_and_binary_identity_mismatch_rejected(self):
        base=self.record(1,7);new=self.record(2,8);t=self.table(base,new)
        t['removed']=['1']
        with self.assertRaises(ValueError):merge_table(base,t,FakeDelta())
        t.pop('removed');t['added'][0]['key']='5'
        with self.assertRaises(ValueError):merge_table(base,t,FakeDelta())
    def test_levels_project_the_actual_curve_not_stale_one_level_exp(self):
        cards={'1':{'definition':{'level_info':{'level':1,'level_limit':1,'exp_to_next_level':0}}}}
        project_levels(cards,[{'card_id':'1','level_limit':32}],[0,0]+list(range(100,200)))
        self.assertEqual(cards['1']['definition']['level_info'],{'level':1,'level_limit':32,'exp_total':0,'exp_current_level':0,'exp_to_next_level':100,'customize_point':0})
    def test_runtime_only_registers_catalogue_and_does_not_touch_owned_players(self):
        conn=sqlite3.connect(':memory:');conn.executescript('create table managed_cards(card_id primary key,fingerprint,payload,card_type,subtype,evidence);create table meta(key primary key,value);create table gameplayers(id,serial,json);insert into gameplayers values(1,7,\'owned progress\');')
        doc={'format':'studio-content-catalogue-v1','packages':[{'package_id':'test'}],'players':[{'card_id':'2','origin':{'card_type':'BigTime'},'definition':{'gameplayer_id':{'id':2,'serial':0}}}]}
        apply_content_catalogue(conn,doc);apply_content_catalogue(conn,doc)
        self.assertEqual(conn.execute('select count(*) from managed_cards').fetchone()[0],1)
        self.assertEqual(conn.execute('select * from gameplayers').fetchall(),[(1,7,'owned progress')])
    def test_failed_catalogue_import_removes_only_uncommitted_source(self):
        from apk_database import GameImport
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);base=root/'base';base.mkdir();data=root/'data';data.mkdir();(data/'current-project.json').write_bytes(b'my draft')
            p=self.make_zip(root);apk=root/'game.apk'
            with zipfile.ZipFile(apk,'w')as z:z.writestr('manifest','placeholder')
            library=types.SimpleNamespace(resources=base,profile={});server=types.SimpleNamespace(store=types.SimpleNamespace(root=data),library=library)
            def build(delta,apk,output,work,profile,progress):output.write_bytes(b'new source');return {'package_id':'test'}
            job=GameImport(server,base)
            with patch('content_delta.build_source',side_effect=build),patch.object(job,'_work',side_effect=ValueError('index failed')):job._delta_work(apk,apk,p)
            self.assertEqual(job.status()['phase'],'error');self.assertIn('index failed',job.status()['message'])
            self.assertEqual((data/'current-project.json').read_bytes(),b'my draft');self.assertFalse((data/'active-game.json').exists())
            self.assertFalse(list((data/'content-sources').glob('*.apk')))
            self.assertFalse(list((data/'tmp').iterdir()))

if __name__=='__main__':unittest.main()
