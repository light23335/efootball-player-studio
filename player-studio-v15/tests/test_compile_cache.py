import copy,hashlib,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compile_cache import CompileCache,clear,code_fingerprint,MODULES,REVISION,_CODE
from native_art import compile_art

class CompileCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.assets=self.root/'assets';self.assets.mkdir();self.cache=CompileCache(self.root/'cache',{'base':'one'})
        self.photo='1'*64+'.png';self.model='2'*64+'.glb'
        (self.assets/self.photo).write_bytes(b'photo');(self.assets/self.model).write_bytes(b'model')
        self.library=SimpleNamespace(store=SimpleNamespace(root=self.root))
        self.project={'package_id':'one','appearance':{'portrait':self.photo},'native_card':{'source_id':'7'},
                      'model':{'asset':self.model},'base_abilities':{'speed':80},'identity':{'name':'QA'}}
        self.identity={'person_id':90000001,'card_id':91000001};self.calls={'card':0,'face':0}
    def card(self,*args):
        self.calls['card']+=1;return[('/Game/card',b'pixels',{'imports':[]})],{'asset_key':'90000001'},{'card':True}
    def face(self,*args):
        self.calls['face']+=1;return[('/Game/face',b'mesh',{'imports':[]})],{'model':'fixture'}
    def build(self):
        with patch('native_art._compile_card_art',side_effect=self.card),patch('native_art._compile_face_art',side_effect=self.face):
            return compile_art(self.project,self.identity,self.library,cache=self.cache)
    def test_ability_changes_reuse_both_artifacts_and_card_crop_does_not_rebuild_face(self):
        before=self.build();self.project['base_abilities']['speed']=90;after=self.build()
        self.assertEqual(before[:2],after[:2]);self.assertEqual(self.calls,{'card':1,'face':1})
        self.project['appearance']['photo_x']=10;self.build();self.assertEqual(self.calls,{'card':2,'face':1})
        self.project['model']['head_vertical_cm']=1;self.build();self.assertEqual(self.calls,{'card':2,'face':2})
    def test_file_bytes_identity_and_source_adapter_changes_invalidate_relevant_artifacts(self):
        self.build();(self.assets/self.photo).write_bytes(b'changed in place');self.build()
        self.assertEqual(self.calls,{'card':2,'face':1})
        (self.assets/self.model).write_bytes(b'changed geometry');self.build();self.assertEqual(self.calls,{'card':2,'face':2})
        self.cache=CompileCache(self.root/'cache',{'base':'new-adapter'});self.build()
        self.assertEqual(self.calls,{'card':3,'face':3})
        self.identity['card_id']+=1;self.build();self.assertEqual(self.calls,{'card':4,'face':3})
    def test_damaged_cache_recompiles_and_never_drops_original_inputs(self):
        self.build();path=next((self.root/'cache').glob('face-*.zip'));path.write_bytes(b'damaged')
        self.build();self.assertEqual(self.calls,{'card':1,'face':2});self.assertEqual(self.cache.stats['corrupt'],1)
        self.assertEqual((self.assets/self.model).read_bytes(),b'model')
    def test_cached_results_are_independent_and_failures_are_not_cached(self):
        data,_=self.cache.run('card',{'id':1},lambda:({'x':[b'original']},))
        data[0]['x'][0]=b'changed';cached,info=self.cache.run('card',{'id':1},lambda:None)
        self.assertTrue(info['hit']);self.assertEqual(cached[0]['x'][0],b'original')
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'compile error'):
                self.cache.run('face',{},lambda:(_ for _ in()).throw(ValueError('compile error')))
        self.assertEqual(self.cache.stats['misses']['face'],2)
    def test_cache_is_bounded_and_clear_preserves_unrelated_files(self):
        cache=CompileCache(self.root/'small',{},limit=12000)
        for i in range(3):cache.run('card',{'id':i},lambda:os.urandom(7000),encoded=True)
        self.assertLessEqual(sum(p.stat().st_size for p in cache.root.glob('*.zip')),12000)
        self.assertGreater(cache.stats['evicted_bytes'],0)
        sentinel=cache.root/'project.json';sentinel.write_bytes(b'keep');result=clear(cache.root)
        self.assertGreater(result['files'],0);self.assertEqual(sentinel.read_bytes(),b'keep')
    def test_android_source_manifest_fallback_invalidates_after_a_compiler_update(self):
        import json
        manifest=self.root/'compiler-source-hashes.json'
        data={'revision':REVISION,'files':{name:'1'*64 for name in MODULES}};manifest.write_text(json.dumps(data),'utf8')
        loader=SimpleNamespace(get_code=lambda name:None)
        with patch.dict(_CODE,{},clear=True),patch('studio_resources.bundled_resources',return_value=self.root),patch('compile_cache.importlib.import_module',return_value=SimpleNamespace(__loader__=loader)):
            before=code_fingerprint();_CODE.clear();data['files']['native_art']='2'*64;manifest.write_text(json.dumps(data),'utf8')
            after=code_fingerprint();self.assertNotEqual(before,after)

if __name__=='__main__':unittest.main()
