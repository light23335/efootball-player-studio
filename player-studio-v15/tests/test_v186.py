import copy,hashlib,http.client,io,json,struct,sys,tempfile,unittest,uuid,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,personal_source
from native_equipment import patch_sleeves,SLEEVE_BIT
from native_tables import weekly_table
from pack_covers import compile_covers,normalize
from personal_runtime import PackImageService,install_pack_images

class NewFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=app.Store(self.root/'data')
    def test_new_slots_keep_old_design_and_start_without_old_assets(self):
        p=copy.deepcopy(self.store.project);p['identity']['name']='旧球员';p['equipment']={'boots_id':2,'sleeves':'long'}
        p['base_abilities']['20']=91;self.store.save(p)
        first=self.store.new_player_slot()['project'];second=self.store.new_player_slot()['project']
        self.assertEqual(len({p['package_id'],first['package_id'],second['package_id']}),3)
        self.assertEqual(self.store.saved_player(p['package_id'])['project']['base_abilities']['20'],91)
        self.assertEqual(self.store.saved_player(p['package_id'])['project']['equipment']['sleeves'],'long')
        self.assertEqual(first['equipment'],{'boots_id':None,'sleeves':'keep'})
        self.assertFalse(first['model']['asset']);self.assertFalse(first['appearance']['portrait'])
        self.assertNotEqual(first['identity']['name'],second['identity']['name'])
        self.assertEqual(len(self.store.list_players()['rows']),3)
    def test_sleeves_change_only_the_verified_two_bits(self):
        raw=bytes(range(64));mask=3<<SLEEVE_BIT
        self.assertEqual(patch_sleeves(raw,{'sleeves':'keep'}),raw)
        for name,value in [('seasonal',0),('short',1),('long',2)]:
            actual=int.from_bytes(patch_sleeves(raw,{'sleeves':name}),'little')
            self.assertEqual(actual&~mask,int.from_bytes(raw,'little')&~mask)
            self.assertEqual((actual>>SLEEVE_BIT)&3,value)
    def test_opening_another_project_keeps_the_previous_slot(self):
        old=copy.deepcopy(self.store.project);old['identity']['name']='未保存的旧球员';self.store.save(old)
        other=app.Store(self.root/'other');new=copy.deepcopy(other.project);new['identity']['name']='导入的新球员'
        bundle=other.export_project(new);self.store.import_project(bundle['path'])
        self.assertEqual(self.store.saved_player(old['package_id'])['project']['identity']['name'],'未保存的旧球员')
        self.assertEqual(self.store.project['package_id'],new['package_id'])
    def test_personal_owned_metadata_reseeds_same_slot_and_preserves_others(self):
        uid=str(uuid.uuid4());pid=95012443;cid=(0x51<<40)|pid
        d={'identity':{'package_id':uid,'person_id':pid,'card_id':cid,'previous_card_ids':[cid]},
           'owned':{'_personal_player_uuid':uid,'gameplayer_id':{'id':cid}},'base_parameters':[0]*147}
        doc={'format':'personal-player-native-v1','revision':'abc','players':[d],
             'native_binding':{'routes':[{'cardId':cid,'portraitKey':'8012443'}]}}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr(personal_source.PATH,json.dumps(doc))
        with zipfile.ZipFile(buffer) as z:loaded=personal_source.read(z,{'personal_player_revision':'abc'})
        registry={};assets={};owners=personal_source.seed(loaded,registry,assets)
        self.assertEqual(registry[uid]['person_id'],pid);self.assertIn(pid,owners[uid]['aliases'])
        self.assertEqual(assets[uid],8012443)
        self.assertEqual(personal_source.merge([{'uuid':'a','v':1},{'uuid':'b','v':2}],[{'uuid':'a','v':3}],'uuid'),[{'uuid':'a','v':3},{'uuid':'b','v':2}])
        registry[uid]['person_id']=90000001
        with self.assertRaises(ValueError):personal_source.seed(doc,registry,assets)
    def test_rebuilding_owned_weekly_does_not_duplicate_or_touch_stock(self):
        cid=(0x51<<40)|95012443;d={'identity':{'card_id':cid,'person_id':95012443,'previous_card_ids':[cid]}}
        stock=struct.pack('<QII',7511,1,2)
        first,_=weekly_table(stock,[{'card_type':'BigTime'}],[d])
        second,_=weekly_table(first,[{'card_type':'BigTime','weekly_condition':'A'}],[d],replace_ids={cid,95012443})
        self.assertTrue(second.startswith(stock))
        entries=list(struct.iter_unpack('<QII',second));self.assertEqual(len(entries),3)
        self.assertEqual({r[2] for r in entries[1:]},{4})
    def test_custom_cover_crops_embeds_and_serves_without_changing_stock_origin(self):
        from PIL import Image
        image=Image.new('RGB',(1600,600),(120,50,200));raw=io.BytesIO();image.save(raw,'PNG')
        asset=hashlib.sha256(raw.getvalue()).hexdigest()+'.png';(self.store.root/'assets'/asset).write_bytes(raw.getvalue())
        pack={'uuid':str(uuid.uuid4()),'name':'封面','cover':{'asset_id':asset,'zoom':1.5,'x':30,'y':-10}}
        files,bindings,routes=compile_covers([pack],self.store)
        for name,content in files.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
            with Image.open(io.BytesIO(content)) as im:self.assertEqual(im.size,(1200,480))
        service=PackImageService(self.root,routes);self.addCleanup(service.close)
        env={'ulist':[{'type':'IMAGE_DATA','url':'https://images.example/prd'}]};service.rewrite(env)
        self.assertEqual(env['ulist'][0]['url'],service.url)
        client=http.client.HTTPConnection('127.0.0.1',service.server.server_port)
        client.request('GET',bindings[pack['uuid']]['c']);response=client.getresponse();self.assertEqual(response.status,200)
        self.assertEqual(response.read(),next(iter(files.values())))
        client.request('GET','/old.png');response=client.getresponse();self.assertEqual(response.status,302)
        self.assertEqual(response.getheader('Location'),'https://images.example/prd/old.png');response.read();client.close()
        with self.assertRaises(ValueError):normalize({'asset_id':'../../x.png'})

if __name__=='__main__':unittest.main()
