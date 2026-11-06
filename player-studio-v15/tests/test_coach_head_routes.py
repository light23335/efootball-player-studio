"""Head-route regressions. No workshop launch, game execution or APK build."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import ast,copy,json,struct,sys,tempfile,threading,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coach_heads import CoachHeadStore,FOLDER
from coach_models import CoachModelStore,current,save_stock,delete_stock,compile_models,compile_stock_models,collect_head_resources
from native_body import container_parts,deduplicate_art
from native_iostore import package_id

CORE=Path(__file__).resolve().parents[1]
SOURCE=17602655027637
PATH=FOLDER+'SK_437sp00v0039_Face.uasset'
PERSONAL=FOLDER+'SK_600001_Face.uasset'
NAME='/Game/Assets/character/DemoFace/Manager/SK_600001_Face'
CATALOG=[{'id':str(SOURCE),'name':'Stock coach'}]

def package(name=NAME,raw=b'head',**values):
    return name,raw,dict(id=package_id(name),exports=1,bundles=1,imports=[],**values)


class HeadRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.lib=SimpleNamespace(state={'phase':'ready'},store=SimpleNamespace(root=self.root),
            face_assets=lambda:SimpleNamespace(files={'../../../'+PATH,'../../../'+PERSONAL}))
        self.head={'target':PATH,'mode':'custom','asset_id':'a'*64+'.glb'}

    def test_old_global_is_inert_in_current_model_and_catalogue(self):
        from coach_heads import catalogue
        legacy=CoachHeadStore(self.root);legacy.save(self.head);before=legacy.path.read_bytes()
        with patch('coach_models.original',return_value={'asset_id':'stock.glb'}) as stock,patch('coach_models.preview') as render:
            result=current(self.lib,{'id':str(SOURCE)})
        stock.assert_called_once_with(self.lib,PATH);render.assert_not_called()
        self.assertTrue(result['legacy_available']);self.assertIsNone(result['replacement'])
        self.assertNotIn('saved',catalogue(self.lib,CATALOG));self.assertEqual(legacy.path.read_bytes(),before)

    def test_selected_stock_save_preview_export_and_delete_use_one_identity(self):
        with patch('coach_models.preview',return_value={'asset_id':'rendered.glb'}):
            saved=save_stock(self.lib,CATALOG[0],self.head,CATALOG)['head']
            self.assertEqual(current(self.lib,CATALOG[0])['replacement'],saved)
        name='/Game/'+PATH.removeprefix('PesMobile/Content/').removesuffix('.uasset')
        with patch('coach_models.compile_head',return_value=([package(name)],{},None,None)) as build:
            art,reports=compile_stock_models(self.lib,CoachModelStore(self.root).list(),CATALOG)
        self.assertEqual(build.call_args.args[1]['asset_id'],self.head['asset_id'])
        self.assertEqual(reports[0]['coach_id'],str(SOURCE));self.assertEqual(reports[0]['source'],'per-coach-editor')
        self.assertEqual(art[0][0],name);delete_stock(self.lib,CATALOG[0],CATALOG)
        self.assertEqual(CoachModelStore(self.root).list(),[])

    def test_explicit_migration_matches_selected_target_and_never_overwrites(self):
        legacy=CoachHeadStore(self.root);legacy.save(self.head);before=legacy.path.read_bytes()
        with patch('coach_models.preview',return_value={'asset_id':'preview.glb'}):
            saved=save_stock(self.lib,CATALOG[0],None,CATALOG,migrate=True)['head']
            with self.assertRaisesRegex(ValueError,'已有独立编辑'):
                save_stock(self.lib,CATALOG[0],None,CATALOG,migrate=True)
        self.assertEqual(saved['asset_id'],self.head['asset_id']);self.assertEqual(legacy.path.read_bytes(),before)
        self.assertTrue(list((self.root/'backups').glob('coach-heads-*'))==[])

    def test_migration_missing_target_or_unknown_coach_cannot_write(self):
        CoachHeadStore(self.root).save(dict(self.head,target=PERSONAL))
        with self.assertRaisesRegex(ValueError,'目标完全匹配'):
            save_stock(self.lib,CATALOG[0],None,CATALOG,migrate=True)
        with self.assertRaisesRegex(ValueError,'没有这名原版教练'):
            save_stock(self.lib,{'id':'600001'},dict(self.head,target=PERSONAL),CATALOG)
        with self.assertRaisesRegex(ValueError,'不一致'):
            save_stock(self.lib,CATALOG[0],dict(self.head,target=PERSONAL),CATALOG)
        self.assertFalse(CoachModelStore(self.root).path.exists())

    def test_failed_preview_leaves_existing_edit_unchanged(self):
        store=CoachModelStore(self.root);store.save(dict(self.head,coach_id=str(SOURCE)));before=store.path.read_bytes()
        with patch('coach_models.preview',side_effect=ValueError('invalid GLB')):
            with self.assertRaisesRegex(ValueError,'invalid GLB'):save_stock(self.lib,CATALOG[0],self.head,CATALOG)
        self.assertEqual(store.path.read_bytes(),before)

    def test_stale_target_remains_editable_but_is_not_silently_retargeted_on_export(self):
        store=CoachModelStore(self.root);store.save(dict(self.head,target=PERSONAL,coach_id=str(SOURCE),name='Stock coach'))
        before=store.path.read_bytes()
        with patch('coach_models.original',return_value={'asset_id':'source.glb'}),patch('coach_models.preview') as render:
            result=current(self.lib,CATALOG[0])
        self.assertTrue(result['stale_replacement']);self.assertEqual(result['template_path'],PATH);render.assert_not_called()
        with self.assertRaisesRegex(ValueError,'Stock coach.*不一致'):
            compile_stock_models(self.lib,store.list(),CATALOG)
        self.assertEqual(store.path.read_bytes(),before)

    def test_malformed_inert_legacy_file_cannot_block_current_source_preview(self):
        CoachHeadStore(self.root).path.write_text('[]',encoding='utf8')
        with patch('coach_models.original',return_value={'asset_id':'source.glb'}):result=current(self.lib,CATALOG[0])
        self.assertFalse(result['legacy_available']);self.assertEqual(result['asset_id'],'source.glb')

    def test_shared_stock_route_browses_effective_model_without_claiming_ownership(self):
        # Two native card IDs can fall back to the same plain-person package.
        shared_path=FOLDER+'SK_437_Face.uasset'
        self.lib.face_assets=lambda:SimpleNamespace(files={'../../../'+shared_path})
        row=CoachModelStore(self.root).save(dict(self.head,target=shared_path,coach_id=str(SOURCE),name='Shared owner'))
        with patch('coach_models.preview',return_value={'asset_id':'shared.glb'}) as render:
            result=current(self.lib,{'id':'437'})
        render.assert_called_once_with(self.lib,row);self.assertIsNone(result['replacement'])
        self.assertEqual(result['shared_with'],['Shared owner']);self.assertEqual(result['asset_id'],'shared.glb')

    def test_private_600001_and_old_global_same_target_collect_only_private(self):
        CoachHeadStore(self.root).save(dict(self.head,target=PERSONAL))
        coach={'uuid':'mine','name':'My coach','head_model':{'template_path':PATH,'asset_id':'b'*64+'.glb'}}
        with patch('coach_models.compile_head',return_value=([package()],{},None,None)) as build:
            personal,reports=compile_models(self.lib,[coach],[{'id':600001}],{600001})
            # Execute the actual two collection statements from the worker.
            tree=ast.parse((CORE/'native_package.py').read_text(encoding='utf8'))
            worker=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_worker')
            stock_node=next(n for n in ast.walk(worker) if isinstance(n,ast.Assign) and
                any(isinstance(t,ast.Tuple) and [getattr(x,'id',None) for x in t.elts]==['head_art','coach_head_report'] for t in n.targets))
            collect_node=next(n for n in ast.walk(worker) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
                isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='extend' and
                n.value.args and isinstance(n.value.args[0],ast.Call) and getattr(n.value.args[0].func,'id',None)=='collect_head_resources')
            scope=dict(compile_stock_models=compile_stock_models,collect_head_resources=collect_head_resources,
                self=SimpleNamespace(library=self.lib),body={'coach_heads':CoachHeadStore(self.root).list()},
                coach_catalog=CATALOG,coach_model_art=personal,coach_model_report=reports,art=[])
            exec(compile(ast.Module(body=[stock_node,collect_node],type_ignores=[]),'<worker-head-collection>','exec'),scope)
        self.assertEqual(build.call_count,1);self.assertEqual(len(scope['art']),1)
        chunks,paths,entries=container_parts(scope['art'])
        self.assertEqual((len(chunks),len(paths),len(entries)),(1,1,1))

    def test_identical_coach_targets_reuse_and_conflicts_name_both_coaches(self):
        a=package();personal=[{'id':600001,'name':'My coach','packages':[NAME]}]
        stock=[{'coach_id':'437','name':'Stock coach','packages':[NAME]}]
        self.assertEqual(collect_head_resources([a],personal,[copy.deepcopy(a)],stock),[a])
        for b in (package(raw=b'other'),(NAME,a[1],dict(a[2],imports=[99]))):
            with self.assertRaisesRegex(ValueError,'SK_600001_Face.*My coach.*600001.*Stock coach.*437'):
                collect_head_resources([a],personal,[b],stock)

    def test_bulk_conflicts_across_coach_targets_also_identify_both_producers(self):
        other='/Game/Assets/character/DemoFace/Manager/SK_437_Face'
        cid=struct.pack('<QHBB',package_id(NAME),0,0,3)
        bulk={'suffix':'.ubulk','chunk_id':cid,'data':b'pixels'}
        personal=[{'id':600001,'name':'My coach','packages':[NAME]}]
        stock=[{'coach_id':'437','name':'Stock coach','packages':[other]}]
        with self.assertRaisesRegex(ValueError,'chunk 内容冲突.*My coach.*Stock coach'):
            collect_head_resources([package(external_chunks=[bulk])],personal,
                [package(other,external_chunks=[dict(bulk,data=b'other pixels')])],stock)

    def test_incremental_legacy_metadata_does_not_get_replayed_for_either_platform(self):
        from native_package import NativePackage
        import write_modes,game_settings
        legacy=CoachHeadStore(self.root);legacy.save(dict(self.head,target=PERSONAL));before=legacy.path.read_bytes()
        old={'players':[],'coaches':[],'packs':[],'coach_heads':[dict(self.head,target=PERSONAL)]}
        for platform in ('pc','android'):
            with self.subTest(platform=platform):
                exporter=NativePackage.__new__(NativePackage);exporter.lock=threading.RLock();exporter.state={'phase':'idle'}
                exporter.store=SimpleNamespace(root=self.root);exporter.library=self.lib;exporter.resources=CORE/'resources'
                exporter.coach_candidates=lambda current:[];exporter._booster_labels=lambda:{}
                exporter.status=lambda:exporter.state;exporter._worker=Mock()
                world={'stadium':{'enabled':False,'unlock_all':False},'tournaments':[]}
                with patch('native_package.threading.Thread') as thread,patch('write_modes.source',return_value=(old,{'token':'old'})),\
                     patch('write_modes.requirements',return_value={}),patch('write_modes.statuses',return_value={}),\
                     patch('write_modes.designs',return_value={'players':{},'coaches':{},'packs':{}}),\
                     patch('native_package.load_packs',return_value=[]),patch('native_package.validate_boosters'),\
                     patch('game_settings.settings',return_value=game_settings.normalize({})),patch('workspace_tools.game_options',return_value={'enabled':False}),\
                     patch('world_workspace.load',return_value=world),patch('world_workspace.normalize',return_value=world):
                    exporter.start({'platform':platform,'project':{'package_id':'p'},'selected_ids':[],
                        'write_mode':'incremental','apk':'old.apk','include_coach_heads':True,
                        'coach_heads':old['coach_heads'],'stock_coach_models':old['coach_heads']})
                queued=thread.call_args.kwargs['args'][0]
                self.assertEqual(queued['stock_coach_models'],[]);exporter._worker.assert_not_called()
        self.assertEqual(legacy.path.read_bytes(),before)

    def test_android_uses_this_same_core_without_head_route_overlay(self):
        android=CORE.parent/'player-studio-android'
        tree=ast.parse((android/'prepare_build.py').read_text(encoding='utf8'))
        self.assertTrue(any(isinstance(n,ast.Constant) and n.value=='player-studio-v15' for n in ast.walk(tree)))
        for name in ('coach_models.py','coach_heads.py','native_package.py','native_body.py'):
            self.assertFalse((android/'app/src/main/python'/name).exists())
        for name in ('coach-heads.js','coach-ui.js','native-package-ui.js'):
            self.assertFalse((android/'web'/name).exists())


class ContainerPartsConflictTests(unittest.TestCase):
    def test_identical_package_has_one_chunk_directory_and_store_entry(self):
        chunks,paths,entries=container_parts([package(),copy.deepcopy(package())])
        self.assertEqual((len(chunks),len(paths),len(entries)),(1,1,1))

    def test_different_bytes_or_metadata_never_select_last(self):
        a=package()
        for b in (package(raw=b'other'),(a[0],a[1],dict(a[2],imports=[12]))):
            with self.assertRaisesRegex(ValueError,'资源目标冲突'):container_parts([a,b])
        with self.assertRaisesRegex(ValueError,'package ID 不一致'):deduplicate_art([(a[0],a[1],dict(a[2],id=0))])

    def test_bulk_duplicate_reuses_identical_data_and_rejects_different_bytes_or_paths(self):
        cid=struct.pack('<QHBB',package_id(NAME),0,0,3)
        bulk={'suffix':'.ubulk','chunk_id':cid,'data':b'pixels'}
        chunks,paths,entries=container_parts([package(external_chunks=[bulk,copy.deepcopy(bulk)])])
        self.assertEqual((len(chunks),len(paths),len(entries)),(2,2,1))
        with self.assertRaisesRegex(ValueError,'chunk 内容冲突'):
            container_parts([package(external_chunks=[bulk,dict(bulk,data=b'changed')])])
        with self.assertRaisesRegex(ValueError,'路径对应不同 chunk'):
            container_parts([package(external_chunks=[bulk,dict(bulk,chunk_id=struct.pack('<QHBB',package_id(NAME),1,0,3))])])


if __name__=='__main__':unittest.main()
