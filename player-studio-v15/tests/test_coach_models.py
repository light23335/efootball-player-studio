from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy,io,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coach_models import native_key,normalize,template,prepare,current,compile_models,verify_loader
from coach_heads import FOLDER

SOURCE=17602655027637
PATH=FOLDER+'SK_437sp00v0039_Face.uasset'


class CoachModelTests(unittest.TestCase):
    def test_native_manager_id_layout_matches_original_and_private_ids(self):
        self.assertEqual(native_key(SOURCE),'437sp00v0039')
        for ident in (600000,600123,999999):self.assertEqual(native_key(ident),str(ident))
        with self.assertRaises(ValueError):native_key((1<<23)|437)
        self.assertEqual(native_key((15<<44)|437),'437')

    def test_template_does_not_substitute_a_different_variant(self):
        lib=SimpleNamespace(state={'phase':'ready'},face_assets=lambda:SimpleNamespace(files={'../../../'+PATH}))
        self.assertEqual(template(lib,SOURCE)['template_path'],PATH)
        self.assertFalse(template(lib,(1<<44)|(38<<28)|437)['available'])
        self.assertFalse(template(lib,437)['available'])

    def test_two_copies_of_same_template_get_different_destinations(self):
        lib=SimpleNamespace(state={'phase':'ready'},face_assets=lambda:SimpleNamespace(files={'../../../'+PATH}))
        coaches=[{'uuid':'one','name':'One','native_source_id':str(SOURCE),'head_model':{'template_path':PATH,'asset_id':'a'*64+'.glb'}},
                 {'uuid':'two','name':'Two','native_source_id':str(SOURCE),'head_model':{'template_path':PATH,'asset_id':'b'*64+'.glb'}}]
        original=copy.deepcopy(coaches);calls=[]
        def compile(library,config,destination):
            calls.append((config,destination))
            return [(destination,b'raw',{})],{'private_packages':[]},b'',None
        with patch('coach_models.compile_head',side_effect=compile):
            art,reports=compile_models(lib,coaches,[{'id':600001},{'id':600002}])
        self.assertNotEqual(calls[0][1],calls[1][1]);self.assertNotEqual(calls[0][0]['asset_id'],calls[1][0]['asset_id'])
        self.assertEqual(coaches,original);self.assertTrue(all(r['independent'] for r in reports))
        self.assertTrue(all('/SK_6' in p[0] for p in art))

    def test_new_coach_gets_real_default_template_without_requiring_a_stock_copy(self):
        lib=SimpleNamespace(state={'phase':'ready'},face_assets=lambda:SimpleNamespace(files={'../../../'+PATH}))
        row={'type':'custom','name':'My coach','head_model':None}
        result=prepare(row,lib)
        self.assertEqual(result['head_model'],{'template_path':PATH})
        self.assertIsNone(row['head_model'])
        self.assertFalse(template(lib,437)['available'],'Stock-only lookup must stay exact')

    def test_current_custom_coach_uses_its_uploaded_head_not_the_donor_or_shared_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=SimpleNamespace(state={'phase':'ready'},store=SimpleNamespace(root=Path(folder)),face_assets=lambda:SimpleNamespace(files={'../../../'+PATH}))
            head={'template_path':PATH,'asset_id':'a'*64+'.glb'}
            coach={'id':'custom:one','type':'custom','head_model':head,'native_source_id':str(SOURCE)}
            with patch('coach_models.preview_coach',return_value={'asset_id':'b'*64+'.glb'}) as render:
                result=current(lib,coach)
            render.assert_called_once_with(lib,head)
            self.assertTrue(result['personal']);self.assertEqual(result['head_model'],head)

    def test_current_stock_coach_shows_saved_replacement_before_original(self):
        with tempfile.TemporaryDirectory() as folder:
            from coach_heads import CoachHeadStore
            lib=SimpleNamespace(state={'phase':'ready'},store=SimpleNamespace(root=Path(folder)),face_assets=lambda:SimpleNamespace(files={'../../../'+PATH}))
            replacement={'target':PATH,'mode':'custom','asset_id':'a'*64+'.glb'}
            CoachHeadStore(folder).save(replacement)
            with patch('coach_models.preview',return_value={'asset_id':'b'*64+'.glb'}) as render,patch('coach_models.original') as stock:
                result=current(lib,{'id':str(SOURCE),'type':'original'})
            render.assert_called_once_with(lib,replacement);stock.assert_not_called()
            self.assertFalse(result['personal']);self.assertEqual(result['replacement'],replacement)

    def test_head_settings_reject_bad_paths_and_external_files(self):
        for value in ({'template_path':'../x'},{'template_path':PATH,'asset_id':'../../a.glb'}):
            with self.assertRaises(ValueError):normalize(value)

    def test_engine_loader_preflight_rejects_changed_instructions(self):
        with tempfile.TemporaryDirectory() as folder:
            import hashlib
            data=b'native-code';info={'resolver_address':'0x123','regions':[{'file_offset':2,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}
            Path(folder,'native-coach-model-loader.json').write_text(json.dumps(info))
            self.assertTrue(verify_loader(io.BytesIO(b'xx'+data),folder)['native_id_to_path_verified'])
            with self.assertRaises(ValueError):verify_loader(io.BytesIO(b'xx'+b'wrong-code'),folder)

    def test_project_references_include_the_personal_coach_glb(self):
        import app,uuid
        p=app.default_project();asset='a'*64+'.glb'
        p['custom_coaches']=[{'uuid':str(uuid.uuid4()),'name':'My face','head_model':{'template_path':PATH,'asset_id':asset}}]
        p=app.normalize_project(p)
        self.assertIn(asset,app.referenced_assets(p))


if __name__=='__main__':unittest.main()
