"""Per-competition cover: durable design -> packaged JPEG -> native banners."""
import copy,hashlib,io,json,sqlite3,tempfile,threading,types,unittest,uuid
from pathlib import Path
from urllib.request import urlopen
from PIL import Image
import tournament_entry as entry
import tournament_rules as rules
import tournament_runtime as runtime
import world_workspace as world


class TournamentCoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=types.SimpleNamespace(root=Path(self.tmp.name),lock=threading.RLock())
        (self.store.root/'assets').mkdir()
        image=Image.new('RGBA',(160,160),(255,0,0,255))
        image.paste((0,0,255,255),(80,0,160,160))
        out=io.BytesIO();image.save(out,'PNG');raw=out.getvalue()
        self.asset=hashlib.sha256(raw).hexdigest()+'.png'
        (self.store.root/'assets'/self.asset).write_bytes(raw)
        self.cover={'asset_id':self.asset,'zoom':1,'x':0,'y':0}
        self.cup={'uuid':str(uuid.uuid4()),'name':'Custom Cup','enabled':True,
                  'team_ids':[1,2,3,4],'player_team_id':1,
                  'stages':[{'type':'knockout','legs':1,'advance':1}]}

    def test_design_roundtrip_normalizes_crop_and_never_accepts_exported_artwork_as_local(self):
        doc=world.default();cup=dict(self.cup,cover={'asset_id':self.asset},cover_artwork={'request':'stale'})
        doc['tournaments']=[cup]
        result=world.save(self.store,doc)['document']
        self.assertEqual(result['tournaments'][0]['cover'],self.cover)
        self.assertNotIn('cover_artwork',result['tournaments'][0])
        self.assertEqual(world.load(self.store),result)
        self.assertEqual(cup['cover_artwork'],{'request':'stale'})
        for cover in ({'asset_id':'../outside.png'},{**self.cover,'zoom':float('nan')},
                      {**self.cover,'x':101},{**self.cover,'zoom':True}):
            with self.subTest(cover=cover),self.assertRaises(ValueError):rules.normalize_cover(cover)
        doc['tournaments'][0]['cover']={'asset_id':'b'*64+'.png'}
        with self.assertRaisesRegex(ValueError,'封面图片缺失'):world.save(self.store,doc)
        self.assertEqual(world.load(self.store),result)

    def test_replacing_entry_pixels_removes_only_stale_routes_for_the_replaced_files(self):
        previous={'/old-entry':{'path':entry.RELATIVE.replace('.jpg','-portrait.jpg'),'sha256':'old'},
                  '/other-pack':{'path':'other.jpg','sha256':'keep'}}
        before=copy.deepcopy(previous)
        updated={'/new-entry':{'path':entry.RELATIVE.replace('.jpg','-portrait.jpg'),'sha256':'new'}}
        merged=entry.merge_image_routes(previous,updated)
        self.assertEqual(set(merged),{'/new-entry','/other-pack'})
        self.assertEqual(previous,before)

    def test_wide_entry_retains_top_and_bottom_of_portrait_art_and_both_menu_tiles_share_image(self):
        image=Image.new('RGB',(100,200),(230,20,20));image.paste((20,220,20),(0,160,100,200))
        wide=entry.entry_pixels(image,(320,180))
        self.assertEqual(wide.size,(320,180))
        self.assertGreater(wide.getpixel((160,5))[0],200)
        self.assertGreater(wide.getpixel((160,175))[1],200)
        response={'result':'NOERR','event_info_list':[{'event_info_type':'AI_MATCH'}]}
        runtime.mainmenu(response,'/new-art')
        self.assertEqual({r['event_info_type']for r in response['event_info_list']},{'BOTH','AI_MATCH'})
        self.assertTrue(all(r['event_banner']=='/new-art'for r in response['event_info_list']))

    def test_default_artwork_unchanged_and_custom_covers_content_addressed(self):
        default_files,default_routes=entry.image_files()
        definitions=runtime.configuration([dict(self.cup,cover=self.cover),
            dict(self.cup,uuid=str(uuid.uuid4()),cover=self.cover),
            dict(self.cup,uuid=str(uuid.uuid4()),name='Default Cup')])
        files,routes=entry.image_files(definitions,self.store)
        self.assertEqual({p:files[p]for p in default_files},default_files)
        self.assertEqual({p:routes[p]for p in default_routes},default_routes)
        self.assertEqual(len(files),3);self.assertEqual(len(routes),3)
        art=definitions[0]['cover_artwork'];self.assertEqual(art,definitions[1]['cover_artwork'])
        self.assertNotIn('cover_artwork',definitions[2])
        raw=files[art['path']]
        self.assertEqual(hashlib.sha256(raw).hexdigest(),art['sha256'])
        self.assertEqual(art['bytes'],len(raw));self.assertEqual(art['mime'],'image/jpeg')
        with Image.open(io.BytesIO(raw))as image:
            self.assertEqual(image.size,(1024,576));self.assertEqual(image.mode,'RGB')
            self.assertGreater(image.getpixel((100,200))[0],240)
            self.assertGreater(image.getpixel((900,200))[2],240)

    def test_crop_position_and_zoom_change_actual_pixels_and_alpha_is_composited(self):
        left=entry.cover_image(self.store.root/'assets'/self.asset,{**self.cover,'zoom':4,'x':-100})
        right=entry.cover_image(self.store.root/'assets'/self.asset,{**self.cover,'zoom':4,'x':100})
        self.assertNotEqual(left,right)
        with Image.open(io.BytesIO(left))as image:self.assertGreater(image.getpixel((512,288))[0],240)
        with Image.open(io.BytesIO(right))as image:self.assertGreater(image.getpixel((512,288))[2],240)
        transparent=self.store.root/'transparent.png';Image.new('RGBA',(16,9),(255,255,255,0)).save(transparent)
        with Image.open(io.BytesIO(entry.cover_image(transparent,self.cover)))as image:
            self.assertTrue(all(abs(a-b)<3 for a,b in zip(image.getpixel((512,288)),(16,26,44))))

    def test_source_only_reexport_keeps_routes_without_original_and_stale_crops_fail(self):
        definition=runtime.configuration([dict(self.cup,cover=self.cover)])[0]
        files,routes=entry.compile_covers([definition],self.store)
        (self.store.root/'assets'/self.asset).unlink()
        # Full selection and incremental carry both pass through configuration.
        for mode,selected in (('full',[definition['uuid']]),('incremental',[])):
            with self.subTest(mode=mode):
                carried=runtime.export_selection([], [definition],selected,mode)
                self.assertEqual(entry.compile_covers(carried,self.store),({},routes))
        changed=copy.deepcopy(definition);changed['cover']['x']=10
        with self.assertRaisesRegex(ValueError,'封面文件缺失'):entry.compile_covers([changed],self.store)
        changed['cover']=None
        self.assertEqual(entry.compile_covers([changed],self.store),({},{}))
        self.assertNotIn('cover_artwork',changed)

    def test_native_event_banners_and_local_image_service_use_the_packaged_bytes(self):
        definition=runtime.configuration([dict(self.cup,cover=self.cover)])[0]
        files,routes=entry.image_files([definition],self.store)
        for path,raw in files.items():
            target=self.store.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        from personal_runtime import PackImageService
        service=PackImageService(self.store.root,routes);self.addCleanup(service.close)
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('create table meta(key text primary key,value text)')
        response={'result':'NOERR','event_list':[{'event_id':1120005,'match_env':{},'ch_event_type':'TOURNAMENT'}]}
        row=runtime.project_events(types.SimpleNamespace(conn=conn),response,[definition],landscape='/default.jpg')['event_list'][0]
        request=definition['cover_artwork']['request']
        self.assertEqual(row['banner_file_name'],request);self.assertEqual(row['event_menu_banner_file_name'],request)
        with urlopen(service.url+request,timeout=5)as response:
            self.assertEqual(response.headers['Content-Type'],'image/jpeg')
            self.assertEqual(response.read(),files[definition['cover_artwork']['path']])
        current=runtime.state(conn,definition);before=copy.deepcopy(current)
        updated=copy.deepcopy(definition);updated.update(cover=None);updated.pop('cover_artwork')
        current=runtime.state(conn,updated)
        for key in ('run_id','seed','fixtures','receipts','stage_index'):
            self.assertEqual(current[key],before[key])
        reset={'result':'NOERR','event_list':[{'event_id':1120005,'match_env':{},'ch_event_type':'TOURNAMENT'}]}
        row=runtime.project_events(types.SimpleNamespace(conn=conn),reset,[updated],landscape='/default.jpg')['event_list'][0]
        self.assertEqual(row['banner_file_name'],'/default.jpg')


if __name__=='__main__':unittest.main()
