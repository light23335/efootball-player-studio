"""Manager replacements must remain explicit, isolated and recoverable."""
from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coach_heads import normalize,CoachHeadStore,catalogue,replacement_indices,opaque_materials,lod_material_bindings
from native_iostore import package_id
from types import SimpleNamespace
import struct

FOLDER='PesMobile/Content/Assets/character/DemoFace/Manager/'
A=FOLDER+'SK_437sp00v0039_Face.uasset'
B=FOLDER+'SK_135sp00v0043_Face.uasset'


class CoachHeadTests(unittest.TestCase):
    def test_mobile_lod_redirect_uses_its_own_material_not_slot_zero(self):
        materials=[{'extras':{'studio_material_path':f'/Game/Material{i}'}} for i in range(5)]
        mesh={'Properties':{'LODInfo':[{'LODMaterialMap':[]},{'LODMaterialMap':[3,4]}]}}
        self.assertEqual([r['material_slot'] for r in lod_material_bindings(mesh,materials,2)],[0,3])
        self.assertEqual(lod_material_bindings(mesh,materials,2)[1]['source_material'],'/Game/Material3')
        mesh['Properties']['LODInfo'][1]['LODMaterialMap']=[-1]
        self.assertEqual(lod_material_bindings(mesh,materials,2)[1]['material_slot'],0)
        mesh['Properties']['LODInfo'][1]['LODMaterialMap']=[5]
        with self.assertRaises(ValueError):lod_material_bindings(mesh,materials,2)
        with self.assertRaises(ValueError):lod_material_bindings({'Properties':{'LODInfo':[]}},materials,2)

    def test_targets_cannot_escape_manager_resources(self):
        for value in ('../x',A+'/../x',A.replace('Manager/','RealFace/'),None):
            with self.assertRaises(ValueError):normalize({'target':value,'mode':'native','source':B})
        for asset in ('../head.glb','x.glb','a'*64+'.obj'):
            with self.assertRaises(ValueError):normalize({'target':A,'mode':'custom','asset_id':asset})

    def test_changes_replace_one_target_and_back_up_previous_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            store=CoachHeadStore(folder)
            one={'target':A,'mode':'native','source':B};two={'target':B,'mode':'native','source':A}
            store.save(one);store.save(two)
            custom={'target':A,'mode':'custom','asset_id':'a'*64+'.glb'}
            store.save(custom)
            self.assertEqual(store.list(),[two,custom])
            self.assertTrue(list((Path(folder)/'backups').glob('coach-heads-*.json')))
            before=store.path.read_bytes()
            with self.assertRaises(ValueError):store.save({'target':A,'mode':'custom','asset_id':'missing'})
            self.assertEqual(store.path.read_bytes(),before)
            store.delete(A);self.assertEqual(store.list(),[two])

    def test_catalogue_labels_exact_card_variant_without_inventing_missing_models(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=SimpleNamespace(state={'phase':'ready'},store=SimpleNamespace(root=Path(folder)),face_assets=lambda:SimpleNamespace(files={'../../../'+A,'../../../'+B,'../../../'+FOLDER+'T_437_Face_D.uasset'}))
            coaches=[{'id':str((1<<44)|(39<<28)|437),'name':'Allegri'},{'id':str((1<<44)|(43<<28)|135),'name':'Kovac'},{'id':'999','name':'No model'}]
            result=catalogue(lib,coaches)
            self.assertEqual(len(result['rows']),2)
            row=next(r for r in result['rows'] if r['path']==A)
            self.assertEqual(row['label'],'Allegri');self.assertEqual(row['coach_ids'],[coaches[0]['id']])

    def test_replacement_permission_covers_only_the_exact_packages(self):
        name='/Game/Assets/character/DemoFace/Manager/SK_437sp00v0039_Face'
        other='/Game/Assets/character/RealFace/SK_7511_Face'
        chunks=[struct.pack('<QHBB',package_id(p),0,0,t) for p,t in ((name,2),(name,3),(other,2),(name,10))]
        result=replacement_indices(SimpleNamespace(chunk_ids=chunks),[(name,b'',{})])
        self.assertEqual(result,{0,1})

    def test_atlas_makes_packed_face_alpha_opaque_but_keeps_hair_opacity(self):
        import io,copy
        from PIL import Image
        from glb_import import encode
        from native_glb import Glb
        buffer=io.BytesIO();Image.new('RGBA',(2,2),(70,50,30,19)).save(buffer,format='PNG');png=buffer.getvalue()
        material={'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}
        doc={'asset':{'version':'2.0'},'bufferViews':[{'buffer':0,'byteLength':len(png)}],
             'images':[{'bufferView':0,'mimeType':'image/png'}],'textures':[{'source':0}],
             'materials':[copy.deepcopy(material),dict(copy.deepcopy(material),alphaMode='MASK')]}
        source=Glb(encode(doc,png));result=opaque_materials(source)
        def alpha(g,index):return Image.open(io.BytesIO(g.image({'material':index}))).getpixel((0,0))[3]
        self.assertEqual(alpha(result,0),255);self.assertEqual(alpha(result,1),19)
        self.assertEqual(alpha(source,0),19)

    def test_original_mount_is_replaced_inside_nested_apk_without_changing_other_assets(self):
        import io,zipfile
        from coach_heads import patch_stock_containers
        from native_body import container_parts
        from native_iostore import Container,write_container,package_header
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'cache';cache.mkdir();(cache/'resource-key.bin').write_bytes(bytes(32))
            name='/Game/Assets/character/DemoFace/Manager/SK_437sp00v0039_Face'
            other='/Game/Assets/character/RealFace/SK_7511_Face'
            meta=lambda n:{'id':package_id(n),'exports':1,'bundles':1,'imports':[]}
            old=[(name,b'old-head',meta(name)),(other,b'keep-player',meta(other))]
            chunks,paths,entries=container_parts(old);cid=12345
            chunks.append((struct.pack('<QHBB',cid,0,0,10),package_header(cid,entries)+bytes(256)))
            index=cache/'pakchunk0.utoc';write_container(index,chunks,paths,cid)
            nested=io.BytesIO()
            with zipfile.ZipFile(nested,'w') as z:
                z.writestr('Paks/pakchunk0.utoc',index.read_bytes());z.writestr('Paks/pakchunk0.ucas',index.with_suffix('.ucas').read_bytes());z.writestr('keep.txt',b'unchanged')
            apk=io.BytesIO()
            with zipfile.ZipFile(apk,'w') as z:z.writestr('assets/pc0000_mobile_and.pak',nested.getvalue())
            new=[(name,b'new-head',meta(name))]
            with zipfile.ZipFile(apk) as z:
                changes,report=patch_stock_containers(z,SimpleNamespace(containers=cache),new,[{'target':A}],root)
                self.assertEqual(z.read('assets/pc0000_mobile_and.pak'),nested.getvalue())
            self.assertEqual(len(report),1)
            with zipfile.ZipFile(io.BytesIO(changes['assets/pc0000_mobile_and.pak'])) as z:
                self.assertEqual(z.read('keep.txt'),b'unchanged')
                target=root/'verified.utoc';target.write_bytes(z.read('Paks/pakchunk0.utoc'));target.with_suffix('.ucas').write_bytes(z.read('Paks/pakchunk0.ucas'))
            c=Container(target)
            self.assertEqual(c.read('../../../'+A),b'new-head')
            self.assertEqual(c.read('../../../PesMobile/Content/Assets/character/RealFace/SK_7511_Face.uasset'),b'keep-player')


if __name__=='__main__':unittest.main()
