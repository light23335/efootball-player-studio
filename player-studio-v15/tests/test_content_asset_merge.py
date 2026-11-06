"""Package identity/dependency regressions, independent native containers."""
from pathlib import Path
import hashlib,json,sys,tempfile,types,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from content_asset_merge import merge_material_assets,STEM
from content_delta import PREFIX
from native_iostore import write_container,package_header,Container
from export_payload import FilePayload

NEW=123450;BASE=300000;UNRELATED=900000
def cid(pid,kind=2):return pid.to_bytes(8,'little')+bytes([0,0,0,kind])
def row(pid,imports=()):return dict(id=pid,exports=1,bundles=1,imports=list(imports))

class MergeAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.parts=self.root/'parts';self.parts.mkdir();self.work=self.root/'work';self.work.mkdir()
        self.key=bytes(32);self.refs={};self.source={}
        self.library=types.SimpleNamespace(containers=self.cache)
        self.previous=dict(packages=[],players=[],routes=[],card_suites=[])
        self.wanted=dict(packages=[dict(package_id='delta')],players=[dict(card_id='123456',base_id='12345')],routes=[],card_suites=[])
    def container(self,label,packages,*,source=False,donor=False,metadata=None):
        # packages: PID -> (asset path, main raw, imports, optional bulk raw)
        folder=self.parts/(str(len(list(self.parts.iterdir())))+'-'+label+('-src'if source else'-donor'));folder.mkdir()
        path=folder/(label+'.utoc');chunks=[];paths={};entries=[]
        ident=sum(label.encode())+100
        for pid,(name,raw,imports,bulk)in packages.items():
            paths['PesMobile/Content/'+name+'.uasset']=len(chunks);chunks.append((cid(pid),raw))
            if bulk is not None:
                paths['PesMobile/Content/'+name+'.ubulk']=len(chunks);chunks.append((cid(pid,3),bulk))
            entries.append(row(pid,imports))
        if metadata is not None:entries=metadata
        chunks.append((cid(ident,10),package_header(ident,entries)))
        write_container(path,chunks,paths,ident)
        member=STEM if label=='pc3700_mobile_and'else PREFIX+'livedata/'+label
        if source:
            for ext in('.utoc','.ucas'):self.source[member+ext]=path.with_suffix(ext).read_bytes()
            self.source[member+'.pak']=b'empty native mount'
        if donor:
            for ext in('.utoc','.ucas'):
                cached=self.cache/(label+'_10_P'+ext);cached.write_bytes(path.with_suffix(ext).read_bytes())
                self.refs[member+ext]=FilePayload.from_path(cached)
            self.refs[member+'.pak']=b'empty native mount'
        return path
    def fixture(self,*,source_base=b'base',donor_base=b'base',new_imports=(BASE,),new_bulk=b'bulk',source_new=False,other_path_pid=None):
        base={BASE:('Shared/Base',source_base,[],None)}
        self.container('pc3700_mobile_and',base,source=True)
        donors={BASE:('Shared/Base',donor_base,[],None),NEW:('ui/12345',b'new',list(new_imports),new_bulk),
                UNRELATED:('character/RealFace/SK_99999_Face',b'old card face',[],None)}
        self.container('pc3700_mobile_and',donors,donor=True)
        # An independent source stadium change must never enter validation or
        # be replaced by its unrelated cached snapshot.
        self.container('pc9262_mobile_and',{77:('bg/EntranceSet1',b'user TIFO',[],None),78:('PlayerStudio/Stadium/Tifo',b'custom',[],None)},source=True)
        self.container('pc9262_mobile_and',{77:('bg/EntranceSet1',b'stock',[],None)},donor=True)
        if source_new:self.container('pc9264_mobile_and',{NEW:donors[NEW]},source=True)
        if other_path_pid:self.container('pc9265_mobile_and',{other_path_pid:('ui/12345',b'foreign',[],None)},source=True)
    def merge(self):
        apk=self.root/'source.apk'
        with zipfile.ZipFile(apk,'w')as archive:
            for name,raw in self.source.items():archive.writestr(name,raw)
            archive.writestr(PREFIX+'release-manifest.json',json.dumps(dict(files=[dict(path=name.removeprefix(PREFIX))for name in self.source if name.startswith(PREFIX)])))
        before=hashlib.sha256(apk.read_bytes()).digest()
        with zipfile.ZipFile(apk)as archive:
            result=merge_material_assets(archive,self.refs,self.library,self.key,self.work,self.previous,self.wanted,['delta'],{})
        self.assertEqual(hashlib.sha256(apk.read_bytes()).digest(),before)
        return result
    def test_only_entity_owned_package_and_complete_bulk_are_added(self):
        self.fixture();replacements,report=self.merge()
        self.assertEqual(set(replacements),{STEM+'.utoc',STEM+'.ucas'})
        self.assertEqual(report['added_package_ids'],[NEW]);self.assertEqual(report['added_native_chunks'],2)
        self.assertEqual([r['id']for r in report['unselected_new_main_packages']],[UNRELATED])
        self.assertEqual(report['required_package_ids'],[NEW,BASE])
        self.assertEqual(report['retained_source_packages'],[BASE])
        p=self.work/'check.utoc';p.write_bytes(replacements[STEM+'.utoc'].path.read_bytes())
        c=Container(p,self.key,data=replacements[STEM+'.ucas'])
        self.assertEqual(c.read_chunk(c.by_id[cid(NEW)]),b'new')
        self.assertEqual(c.read_chunk(c.by_id[cid(NEW,3)]),b'bulk')
        self.assertEqual(c.read_chunk(c.by_id[cid(BASE)]),b'base')
    def test_existing_global_package_in_another_container_is_reused(self):
        self.fixture(source_new=True);replacements,report=self.merge()
        self.assertEqual(replacements,{})
        self.assertIn(NEW,report['retained_source_packages'])
    def test_required_modified_dependency_fails_with_concrete_path(self):
        self.fixture(source_base=b'player edited base')
        with self.assertRaisesRegex(ValueError,'Shared/Base'):self.merge()
    def test_required_import_list_change_is_not_hidden_by_identical_bytes(self):
        self.fixture()
        self.source={k:v for k,v in self.source.items()if not k.startswith(STEM)}
        self.container('pc3700_mobile_and',{BASE:('Shared/Base',b'base',[999],None)},source=True)
        with self.assertRaisesRegex(ValueError,'Shared/Base'):self.merge()
    def test_same_asset_path_with_another_native_pid_is_rejected(self):
        self.fixture(other_path_pid=123499)
        with self.assertRaisesRegex(ValueError,'ui/12345'):self.merge()
    def test_unresolved_native_dependency_is_rejected(self):
        self.fixture(new_imports=(987654,))
        with self.assertRaisesRegex(ValueError,'987654'):self.merge()
    def test_pending_receipt_selects_asset_for_an_already_registered_card(self):
        self.fixture();self.previous['players']=list(self.wanted['players'])
        self.previous['packages']=[dict(package_id='delta',pending_entities=['player_card:123456'])]
        replacements,report=self.merge();self.assertEqual(report['added_package_ids'],[NEW])
    def test_existing_card_without_pending_receipt_does_not_pull_old_face_additions(self):
        self.fixture();self.previous['players']=list(self.wanted['players'])
        replacements,report=self.merge();self.assertEqual(replacements,{})
        self.assertEqual(report['root_package_ids'],[])
    def test_suite_only_pending_receipt_selects_actual_prefix_resources(self):
        self.fixture();self.wanted['players']=[]
        suite=dict(nativeType='51',variant='7',id='BT7',resourceIds=['0501_7_b02'])
        self.wanted['card_suites']=[suite];self.previous['card_suites']=[suite]
        self.previous['packages']=[dict(package_id='delta',pending_entities=["card_suite:('51', '7', 'BT7')"])]
        self.refs['assets/card-designer/backgrounds/0501_7_b02.png']=b'suite image'
        replacements,report=self.merge();self.assertEqual(replacements,{})
        self.assertEqual(report['media_paths'],['assets/card-designer/backgrounds/0501_7_b02.png'])
    def test_required_media_conflict_is_not_silently_ignored(self):
        self.fixture();name='assets/card-designer/backgrounds/12345_new.png'
        self.refs[name]=b'donor';self.source[name]=b'player changed'
        with self.assertRaisesRegex(ValueError,'12345_new.png'):self.merge()
    def test_unrelated_media_is_not_selected_or_overwritten(self):
        self.fixture();name='assets/card-designer/backgrounds/99999_old.png'
        self.refs[name]=b'donor';self.source[name]=b'player changed'
        _,report=self.merge();self.assertNotIn(name,report['media_paths'])
    def test_unknown_pending_entity_cannot_be_guessed(self):
        self.fixture();self.previous['packages']=[dict(package_id='delta',pending_entities=['mystery:123'])]
        with self.assertRaisesRegex(ValueError,'mystery'):self.merge()
    def test_nontrivial_required_pak_difference_is_rejected(self):
        self.fixture();self.refs[STEM+'.pak']=b'real PAK difference'+bytes(500)
        with self.assertRaisesRegex(ValueError,'pc3700_mobile_and.pak'):self.merge()
    def test_three_digit_native_base_id_only_selects_face_or_thumbnail(self):
        self.fixture();self.wanted['players']=[dict(card_id='654321',base_id='123')]
        self.container('pc3700_mobile_and',{BASE:('Shared/Base',b'base',[],None),
            NEW:('Assets/character/RealFace/SK_123_Face',b'face',[],None),
            UNRELATED:('ui/UnrelatedWidget_123',b'widget',[],None)},donor=True)
        _,report=self.merge();self.assertEqual(report['added_package_ids'],[NEW])
    def test_valid_distinct_base_and_patch_versions_are_preserved_per_container(self):
        self.fixture()
        self.container('pc9264_mobile_and',{BASE:('Shared/Base',b'patch version',[],None)},source=True)
        self.container('pc9264_mobile_and',{BASE:('Shared/Base',b'patch version',[],None)},donor=True)
        _,report=self.merge();self.assertIn(BASE,report['retained_source_packages'])
    def test_modified_required_patch_cannot_match_a_different_base_version(self):
        self.fixture()
        self.container('pc9264_mobile_and',{BASE:('Shared/Base',b'base',[],None)},source=True)
        self.container('pc9264_mobile_and',{BASE:('Shared/Base',b'expected patch',[],None)},donor=True)
        with self.assertRaisesRegex(ValueError,'Shared/Base'):self.merge()
    def test_unknown_source_container_namespace_is_rejected(self):
        self.fixture()
        for ext in('.utoc','.ucas'):self.source['assets/untrusted/custom'+ext]=self.source[STEM+ext]
        with self.assertRaisesRegex(ValueError,'untrusted'):self.merge()
    def optional(self,label,pid,*,incoming):
        path=self.cache/(label+'_optional_10_P.utoc')
        write_container(path,[(cid(pid,4),b'optional native bulk')],
                        {'PesMobile/Content/NativeOptional.uptnl':0},777)
        if incoming:
            for ext in('.utoc','.ucas'):
                self.refs[PREFIX+'livedata/'+label+'_optional'+ext]=FilePayload.from_path(path.with_suffix(ext))
    def test_profile_companion_dependency_and_optional_bulk_are_external(self):
        external=987654;self.fixture(new_imports=(external,))
        self.container('pc3611_mobile_and',{external:('Native/BaseTexture',b'native base',[],None)},donor=True)
        for ext in('.pak','.utoc','.ucas'):self.refs.pop(PREFIX+'livedata/pc3611_mobile_and'+ext)
        self.optional('pc3611_mobile_and',external,incoming=False)
        _,report=self.merge()
        self.assertEqual(report['added_package_ids'],[NEW])
        providers=report['external_native_dependencies'][str(external)]
        self.assertEqual(providers[0]['containers'],['pc3611_mobile_and','pc3611_mobile_and_optional'])
    def test_incoming_optional_bulk_is_part_of_the_complete_new_package(self):
        self.fixture();self.optional('pc3700_mobile_and',NEW,incoming=True)
        replacements,report=self.merge();self.assertEqual(report['added_native_chunks'],3)
        toc=self.work/'optional-check.utoc';toc.write_bytes(replacements[STEM+'.utoc'].path.read_bytes())
        c=Container(toc,self.key,data=replacements[STEM+'.ucas'])
        self.assertEqual(c.read_chunk(c.by_id[cid(NEW,4)]),b'optional native bulk')
    def test_verified_refs_are_the_incoming_snapshot_not_another_cache_file(self):
        self.fixture()
        for ext in('.utoc','.ucas'):
            self.refs[STEM+ext]=self.refs[STEM+ext].path.read_bytes()
            (self.cache/('pc3700_mobile_and_10_P'+ext)).write_bytes(b'not the verified snapshot')
        _,report=self.merge();self.assertEqual(report['added_package_ids'],[NEW])
    def test_new_card_reusing_existing_suite_does_not_claim_its_old_media(self):
        self.fixture();name='assets/card-designer/backgrounds/0000_0_b02.png'
        self.refs[name]=b'old donor template';self.source[name]=b'player suite edit'
        suite=dict(nativeType='00',variant='0',id='old',resourceIds=['0000_0_b02'])
        self.wanted['card_suites']=[suite];self.previous['card_suites']=[suite]
        _,report=self.merge();self.assertEqual(report['media_paths'],[])
    def test_external_base_dependency_path_cannot_point_to_another_source_pid(self):
        external=987654;self.fixture(new_imports=(external,))
        self.container('pc3611_mobile_and',{external:('Native/BaseTexture',b'base',[],None)},donor=True)
        for ext in('.pak','.utoc','.ucas'):self.refs.pop(PREFIX+'livedata/pc3611_mobile_and'+ext)
        self.container('pc9265_mobile_and',{999:('Native/BaseTexture',b'foreign mapping',[],None)},source=True)
        with self.assertRaisesRegex(ValueError,'Native/BaseTexture'):self.merge()
    def forged_optional(self,chunk_id,path,raw):
        toc=self.cache/'pc3700_mobile_and_optional_10_P.utoc'
        write_container(toc,[(chunk_id,raw)],{'PesMobile/Content/'+path:0},888)
        for ext in('.utoc','.ucas'):
            self.refs[PREFIX+'livedata/pc3700_mobile_and_optional'+ext]=FilePayload.from_path(toc.with_suffix(ext))
    def test_optional_same_chunk_id_different_bytes_fails_before_merge(self):
        self.fixture();self.forged_optional(cid(NEW),'ui/12345.uasset',b'forged different main')
        with self.assertRaisesRegex(ValueError,'ui/12345.uasset'):self.merge()
    def test_optional_same_path_different_chunk_id_fails_before_merge(self):
        self.fixture();self.forged_optional(cid(NEW,4),'ui/12345.uasset',b'forged optional')
        with self.assertRaisesRegex(ValueError,'ui/12345.uasset'):self.merge()
    def test_optional_identical_duplicate_main_chunk_is_reused(self):
        self.fixture();self.forged_optional(cid(NEW),'ui/12345.uasset',b'new')
        _,report=self.merge();self.assertEqual(report['added_native_chunks'],2)

if __name__=='__main__':unittest.main()
