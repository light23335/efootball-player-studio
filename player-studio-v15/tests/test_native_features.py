from pathlib import Path
import copy,json,struct,sys,tempfile,unittest,uuid,sqlite3
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,packs
from native_appearance import FIELDS,decode,patch,profile,compact_table

class NativeFeatureTests(unittest.TestCase):
    def test_imported_native_appearance_is_readable_by_preview(self):
        rows={}
        for ident in (7511,100):
            raw=bytearray(64);struct.pack_into('<Q',raw,0,ident)
            rows[ident]=patch(raw,{'physique':{key:(i%14) for i,(key,_) in enumerate(FIELDS)},'skin_tone':4})
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=compact_table(rows);self.assertEqual(len(data),32)
            (folder/'native-appearance.bin').write_bytes(data)
            for ident,row in rows.items():
                self.assertEqual({k:v for k,v in profile(folder,ident).items() if k!='source_id'},decode(row))

    def test_appearance_changes_only_selected_native_bits(self):
        original=bytearray(range(64));struct.pack_into('<Q',original,0,7511)
        updates={'physique':{key:(i%15) for i,(key,_) in enumerate(FIELDS)},'skin_tone':6}
        result=patch(original,updates);decoded=decode(result)
        self.assertEqual(decoded,updates)
        changed=0
        for i in range(14):changed|=15<<(64+4*i)
        changed|=7<<292
        self.assertEqual((int.from_bytes(original,'little')^int.from_bytes(result,'little'))&~changed,0)
        self.assertEqual(patch(original,{}),original)
        for bad in (-1,15,1.5,True):
            with self.assertRaises(ValueError):patch(original,{'physique':{'leg_length':bad}})

    def test_original_appearance_reference_and_torso_link(self):
        p=profile(app.RESOURCE,7511)
        self.assertEqual([p['physique'][k] for k,_ in FIELDS],[6,9,2,9,9,7,10,5,9,10,3,9,9,9])
        q=app.default_project();q['model'].update(physique={'leg_length':2},torso_length=99,skin_tone=4)
        self.assertEqual(app.normalize_project(q)['model']['torso_length'],12)

    def test_pack_definition_validation_and_permanent_identity(self):
        p={'uuid':str(uuid.uuid4()),'name':'Example','members':[{'kind':'original','id':'7511','name':'Messi','weight':3}]}
        a=packs.compile_packs([p],[],app.RESOURCE)[0];b=packs.compile_packs([dict(p,name='Renamed')],[],app.RESOURCE)[0]
        self.assertEqual(a['agent_id'],b['agent_id']);self.assertEqual(a['members'][0]['weight'],3)
        self.assertTrue(all(v['price']['coin_price']==0 for v in a['price']['price_list']))
        q=copy.deepcopy(p);q['members']*=2
        with self.assertRaises(ValueError):packs.normalize(q)
        q=copy.deepcopy(p);q['members'][0].update(kind='custom',id=str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'勾选'):packs.compile_packs([q],[],app.RESOURCE)

    def test_batch_grants_use_global_serials_and_keep_each_instance(self):
        from personal_runtime import apply_definitions
        c=sqlite3.connect(':memory:')
        c.executescript('''create table meta(key text primary key,value text);
        create table gameplayers(id integer,serial integer unique,json text,source text,acquired_at text,primary key(id,serial));
        create table careerplan(id integer,serial integer,category text,points integer,at text);
        create table owned_identity_aliases(id integer,old_serial integer,new_serial integer,primary key(id,old_serial));
        create table managed_cards(card_id text primary key,fingerprint text,payload text,card_type text,subtype text,evidence text);
        create table managed_serials(card_id text primary key,next_serial integer);''')
        definitions=[]
        for cid in (90000001,90000002):
            uid=str(uuid.uuid4());owned={'gameplayer_id':{'id':cid,'serial':1},'parameters':[0]*147,'level_info':{'level':1,'level_limit':35,'exp_total':0},'_personal_player_uuid':uid,'_personal_design_revision':uid}
            definitions.append({'identity':{'package_id':uid,'card_id':cid,'previous_card_ids':[cid]},'owned':owned,'base_parameters':[0]*147,'allocation':{},'card_type':'Epic','card_series':'Epic'})
        doc={'format':'personal-player-native-v1','players':definitions,'training_groups':[]}
        first=apply_definitions(c,doc);self.assertEqual([p['serial'] for p in first],[1,2])
        before=c.execute('select * from gameplayers order by serial').fetchall()
        apply_definitions(c,doc);self.assertEqual(before,c.execute('select * from gameplayers order by serial').fetchall())

if __name__=='__main__':unittest.main()
