from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from export_errors import ExportError,export_context,call


class ExportDiagnosticsTests(unittest.TestCase):
    def test_nested_failure_identifies_player_resource_and_preserves_original_reason(self):
        original=FileNotFoundError('缺少纹理文件')
        with self.assertRaises(ExportError) as caught:
            with export_context('球员',{'identity':{'name':'Salah'},'package_id':'one'},'编译脸模'):
                with export_context('资料文件','face-material.json','读取材质'):raise original
        error=caught.exception
        self.assertIn('Salah',str(error));self.assertIn('face-material.json',str(error));self.assertIn('缺少纹理文件',str(error))
        self.assertEqual(error.contexts[0]['kind'],'球员');self.assertEqual(error.original_type,'FileNotFoundError')
        self.assertIs(error.__cause__.__cause__,original)

    def test_empty_exception_still_has_object_and_error_type(self):
        def broken():raise AssertionError()
        with self.assertRaisesRegex(ExportError,'Coach.*AssertionError'):call('教练','Coach','编译头像',broken)

    def test_coach_failure_names_the_exact_coach_in_a_batch(self):
        from coach_models import compile_models
        from unittest.mock import patch
        with patch('coach_models.prepare',side_effect=ValueError('模板缺失')):
            with self.assertRaisesRegex(ExportError,'Second coach.*模板缺失'):
                compile_models(None,[{'uuid':'two','name':'Second coach'}],[{'id':600001}])

    def test_project_export_identifies_missing_asset_and_player(self):
        import app
        with tempfile.TemporaryDirectory() as folder:
            store=app.Store(folder);p=app.default_project();p['identity']['name']='My player'
            p['appearance']['portrait']='a'*64+'.png'
            with self.assertRaises(ExportError) as caught:store.export_project(p)
            self.assertIn('My player',str(caught.exception));self.assertIn('a'*64+'.png',str(caught.exception))
