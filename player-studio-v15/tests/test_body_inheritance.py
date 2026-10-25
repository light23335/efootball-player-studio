from pathlib import Path
import copy,json,re,struct,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_appearance import donor,patch,decode
from native_models import resolve_face

ROOT=Path(__file__).resolve().parents[2]
CACHE=ROOT/'球员工坊-V17/library/versions/V17-1f38a585/containers'


class AppearanceInheritanceTests(unittest.TestCase):
    def test_original_body_source_survives_a_different_card_decoration_and_legacy_projects(self):
        records={7511:bytes(64),40352:bytes(64),900:bytes(64)}
        p={'source_player':{'id':'7511'},'model':{}}
        self.assertEqual(donor(p,records,40352),7511)
        p['model']['appearance_source_id']='900'
        self.assertEqual(donor(p,records,40352),900)
        p['model']['appearance_source_id']='999'
        with self.assertRaises(ValueError):donor(p,records,40352)
        self.assertEqual(donor({'source_player':{'id':str((12<<40)|7511)}},records,40352),7511)
        self.assertEqual(donor({},records,40352),40352)

    def test_native_default_skin_and_every_other_unedited_byte_are_preserved(self):
        row=bytearray(bytes(range(64)));value=int.from_bytes(row,'little')&~(7<<292);row=value.to_bytes(64,'little')
        self.assertEqual(patch(row,{'skin_tone':1}),row)
        changed=patch(row,{'skin_tone':1,'skin_tone_edited':True})
        self.assertEqual(int.from_bytes(row,'little')^int.from_bytes(changed,'little'),1<<292)
        self.assertEqual(decode(patch(row,{'skin_tone':4}))['skin_tone'],4)

    def test_highlight_and_showtime_faces_use_their_actual_native_variant(self):
        for family in ('hi','sp'):
            rows=[{'name':'SK_7511_Face','id':'base'},
                  {'name':f'SK_7511{family}00v0556_Face','id':'special'}]
            selected,proof=resolve_face(rows,(556<<28)|7511)
            self.assertEqual(selected['id'],'special');self.assertTrue(proof['exact'])


@unittest.skipUnless(CACHE.is_dir(),'requires prepared original V17 resource cache')
class NativeBodyResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native_art import Assets
        cls.assets=Assets(CACHE)

    def test_every_stock_unique_armleg_family_keeps_all_native_pixel_blocks_and_mips(self):
        from native_body import compile_body,texture_mips,container_parts
        from native_iostore import Container,write_container,package_header,append_container
        paths=sorted(p for p in self.assets.files if re.search(r'/T_[^/]+_ArmLeg_D\.uasset$',p))
        self.assertEqual(len(paths),56)
        art=[];expected={}
        for i,path in enumerate(paths):
            family=path.rsplit('/',1)[-1][2:].removesuffix('_ArmLeg_D.uasset')
            face='/Game/Assets/character/RealFace/SK_'+family+'_Face'
            raw,_,_=self.assets.face(face);key=str(8000000+i)
            parts,report=compile_body(self.assets,raw,face,key)
            self.assertEqual(report['source_family'],family)
            self.assertTrue(report['unique_arm'] and report['mips_preserved'])
            self.assertEqual(len(parts),1)
            expected[parts[0][0]]=report;art+=parts
        additions,directory,packages=container_parts(art)
        # Exercise the actual IoStore appender and package store, including
        # .ubulk directory entries under each newly allocated texture key.
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);cid=123;header_id=struct.pack('<QHBB',cid,0,0,10)
            source=write_container(tmp/'source.utoc',[(header_id,package_header(cid,[]))],{},cid)
            output=append_container(source,tmp/'result.utoc',additions,directory,packages)
            for name,raw,meta in art:
                prefix='../../../PesMobile/Content/'+name[6:]
                self.assertEqual(output.read(prefix+'.uasset'),raw)
                bulk={}
                for chunk in meta['external_chunks']:
                    data=output.read(prefix+chunk['suffix'])
                    self.assertEqual(data,chunk['data']);bulk[chunk['suffix']]=data
                parsed=texture_mips(output.read(prefix+'.uasset'),bulk)
                self.assertEqual([m['sha256'] for m in parsed['mips']],
                                 [m['sha256'] for m in expected[name]['mips']])

    def test_legacy_renamed_head_recovers_its_exact_material_family_without_guessing_age(self):
        from native_body import compile_body
        from native_iostore import rename_package
        original='/Game/Assets/character/RealFace/SK_7511ep01v0291_Face'
        raw,_,_=self.assets.face(original)
        renamed,_=rename_package(raw,'/Game/Assets/character/RealFace/SK_8900001_Face')
        _,report=compile_body(self.assets,renamed,'/Game/Assets/character/RealFace/SK_8900001_Face','8900002')
        self.assertEqual(report['source_family'],'7511ep01v0291')

    def test_players_without_unique_arm_texture_do_not_receive_another_players_tattoos(self):
        from native_body import compile_body
        for ident in (4522,133543):
            path=f'/Game/Assets/character/RealFace/SK_{ident}_Face';raw,_,_=self.assets.face(path)
            parts,report=compile_body(self.assets,raw,path,'8900001')
            self.assertFalse(parts);self.assertFalse(report['unique_arm'])

    def test_missing_external_bulk_is_reported_instead_of_exporting_an_incomplete_tattoo(self):
        from native_body import texture_mips
        raw,_=self.assets.get('/Game/Assets/character/RealFace/T_7511_ArmLeg_D')
        with self.assertRaisesRegex(ValueError,'完整的 .ubulk'):texture_mips(raw,{})

    def test_custom_head_inherits_native_skin_and_tattoo_flags_without_changing_any_geometry(self):
        from native_body import transfer_body_settings,_body_properties,unique_arm,face_body_source
        from native_skeletal import face_details
        target,_,_=self.assets.face('/Game/Assets/character/RealFace/SK_133543_Face')
        before=face_details(target);target_body=_body_properties(target)
        for ident,tone in ((7511,1),(40352,4),(4522,3)):
            found=face_body_source(self.assets,{'source_player':{'id':str(ident)}})
            self.assertIsNotNone(found);source,path,proof=found
            result=transfer_body_settings(target,source,{'skin_tone':tone},ROOT/'player-studio-v15/resources',ident)
            self.assertEqual(unique_arm(result),unique_arm(source))
            after=_body_properties(result)
            self.assertEqual(result[after[3]:],target[target_body[3]:])
            self.assertEqual(face_details(result),before)
            fields=lambda p:{n:(k,v) for n,k,v,_,_ in _body_properties(p)[4] if n in ('SkinColor','bHasUniqueArm')}
            self.assertEqual(fields(result),fields(source))
        # Explicit edits affect only skin, leaving the original tattoo flag.
        source,_,_=self.assets.face('/Game/Assets/character/RealFace/SK_40352_Face')
        result=transfer_body_settings(target,source,{'skin_tone':2},ROOT/'player-studio-v15/resources',40352)
        self.assertTrue(unique_arm(result))
        self.assertEqual(next(v for n,k,v,a,b in _body_properties(result)[4] if n=='SkinColor'),2)


if __name__=='__main__':unittest.main()
