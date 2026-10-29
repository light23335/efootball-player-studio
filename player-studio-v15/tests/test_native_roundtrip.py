from pathlib import Path
import copy,io,json,sqlite3,struct,sys,tempfile,unittest,contextlib
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_glb import Glb
from glb_import import normalize_head,encode
from test_head_preview import fixture
from project_resource_migration import prepare

class NativeRoundtripTests(unittest.TestCase):
    def test_exporter_sections_keep_every_triangle_texture_and_skin_influence(self):
        original=Glb(fixture(1.38));d=copy.deepcopy(original.doc);b=bytearray(original.binary)
        png=io.BytesIO();Image.new('RGBA',(8,8),(240,160,80,128)).save(png,format='PNG')
        at=len(b);b.extend(png.getvalue());view=len(d['bufferViews']);d['bufferViews'].append({'buffer':0,'byteOffset':at,'byteLength':len(png.getvalue())})
        d.update(images=[{'bufferView':view,'mimeType':'image/png'}],textures=[{'source':0}],materials=[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}])
        d['meshes']*=2;d['skins']*=2
        d['nodes'] += [{'name':'ImportedPlayerPreview','extras':{'normalizedScale':4},'scale':[4,4,4]}, {'mesh':0,'skin':0},{'mesh':1,'skin':1}]
        source=Glb(encode(d,b));g,report=normalize_head(source)
        self.assertEqual(len(g.doc['skins']),1);self.assertEqual(report['sections'],2)
        self.assertTrue(report['facial_weights_preserved'])
        a=original.head()['attributes'];target=g.head()['attributes']
        triangles=original.read(original.head()['indices']).reshape(-1)
        merged=g.read(g.head()['indices']).reshape(-1)
        for name in ('POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'):
            expected=original.read(a[name])[triangles]
            np.testing.assert_array_equal(g.read(target[name])[merged],np.concatenate((expected,expected)))
        self.assertEqual(g.image(),png.getvalue())
        self.assertEqual(source.doc,d)
    def test_distinct_skins_are_not_silently_combined(self):
        g=Glb(fixture(1.38));d=copy.deepcopy(g.doc);d['meshes']*=2
        skin=copy.deepcopy(d['skins'][0]);skin['joints']=list(reversed(skin['joints']));d['skins'].append(skin)
        d['nodes'] += [{'mesh':0,'skin':0},{'mesh':1,'skin':1}]
        with self.assertRaisesRegex(ValueError,'不同骨架'):normalize_head(Glb(encode(d,g.binary)))
    def test_explicit_new_identity_repairs_only_missing_body_and_card_references(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.work') as temp:
            root=Path(temp)
            with contextlib.closing(sqlite3.connect(root/'library.sqlite3')) as db:
                db.execute('create table players(id text)');db.executemany('insert into players values(?)',[('42',),('43',)])
                db.commit()
            (root/'native-appearance.bin').write_bytes(struct.pack('<Q',42)+bytes(8)+struct.pack('<Q',43)+bytes(8))
            p={'identity':{'bind_original_player':True,'original_player_id':'42'},'model':{'appearance_source_id':'99','asset':'authored.glb','physique':{'neck_length':3}},'native_card':{'source_id':'99','layers':[{'path':'authored.png'}]}}
            snapshot=copy.deepcopy(p);new,report=prepare(p,root)
            self.assertEqual(p,snapshot);self.assertEqual(new['model']['asset'],'authored.glb');self.assertEqual(new['model']['physique'],p['model']['physique'])
            self.assertEqual(new['model']['appearance_source_id'],'42');self.assertEqual(new['native_card']['source_id'],'42');self.assertEqual(len(report),2)
            p['model']['appearance_source_id']='43';new,_=prepare(p,root);self.assertEqual(new['model']['appearance_source_id'],'43')
            p['identity']['bind_original_player']=False;new,report=prepare(p,root);self.assertEqual(new,p);self.assertEqual(report,[])

if __name__=='__main__':unittest.main()
