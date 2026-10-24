from pathlib import Path
from collections import OrderedDict
from types import SimpleNamespace
import base64,copy,hashlib,io,sys,tempfile,threading,unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from native_thumbnail import render,card_portrait,ThumbnailPreview
from thumbnail_background import background

class LinkedThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'assets').mkdir()
        self.library=SimpleNamespace(store=SimpleNamespace(root=self.root),thumbnail_lock=threading.Lock(),thumbnail_frames=OrderedDict())
    def image(self,color,size=(32,32)):
        raw=io.BytesIO();Image.new('RGBA',size,color).save(raw,'PNG');data=raw.getvalue();name=hashlib.sha256(data).hexdigest()+'.png'
        (self.root/'assets'/name).write_bytes(data);return name
    def project(self):
        p=app.default_project();p['appearance']['thumbnail_mode']='image'
        raw=Image.new('RGBA',(32,32));raw.paste((250,20,20,255),(8,8,24,32));out=io.BytesIO();raw.save(out,'PNG');data=out.getvalue()
        name=hashlib.sha256(data).hexdigest()+'.png';(self.root/'assets'/name).write_bytes(data)
        p['appearance'].update(thumbnail_image=name,portrait=name)
        p['native_card']={'preset_id':'test','layers':[{'slot':'f02','kind':'image','asset_id':self.image((20,180,50,255))}]}
        return p
    def test_transparent_head_keeps_crop_but_gains_the_linked_background(self):
        p=self.project();foreground=render(p,self.root/'assets',None)
        linked=render(p,self.root/'assets',None,background=background(p,self.library))
        self.assertEqual(foreground.getpixel((0,0)),(0,0,0,0))
        self.assertEqual(linked.getpixel((0,0)),(20,180,50,255))
        self.assertEqual(linked.getpixel((256,256)),foreground.getpixel((256,256)))
        self.assertEqual(linked.getchannel('A').getextrema(),(255,255))
    def test_preset_switch_updates_preview_without_changing_the_face_crop(self):
        p=self.project();service=ThumbnailPreview(self.library);first=service.prepare(p)
        p['native_card']['layers'][0]['asset_id']=self.image((40,20,180,255))
        second=service.prepare(p);self.assertNotEqual(first['image'],second['image'])
        def decode(data):return Image.open(io.BytesIO(base64.b64decode(data['image'].split(',')[1])))
        a,b=decode(first),decode(second);self.assertEqual(a.getpixel((256,256)),b.getpixel((256,256)))
        self.assertNotEqual(a.getpixel((0,0)),b.getpixel((0,0)))
        self.assertEqual(p['appearance']['thumbnail_zoom'],1)
    def test_video_background_has_a_cached_poster_and_skips_portraits_and_top_effects(self):
        p=self.project();asset=hashlib.sha256(b'video fixture').hexdigest()+'.webm';(self.root/'assets'/asset).write_bytes(b'fixture')
        calls=[]
        def decode(path,seconds):calls.append((path.name,seconds));return Image.new('RGBA',(16,24),(150,70,10,255))
        self.library.thumbnail_video_frame=decode
        p['native_card']['layers']=[{'slot':'f02','kind':'video','asset_id':asset,'duration':1.5},
            {'slot':'f10','kind':'image','asset_id':self.image((0,0,255,255))},
            {'slot':'portrait','kind':'image','asset_id':self.image((255,0,0,255))}]
        a=background(p,self.library);b=background(p,self.library)
        self.assertEqual(calls,[(asset,.5)]);self.assertEqual(a.tobytes(),b.tobytes());self.assertEqual(a.getpixel((0,0)),(150,70,10,255))
    def test_stock_baked_foreground_is_not_reused_as_the_custom_background(self):
        p=self.project();p['native_card'].pop('preset_id')
        p['native_card']['layers'].append({'slot':'f04','kind':'image','asset_id':self.image((0,0,255,255))})
        self.assertEqual(background(p,self.library).getpixel((0,0)),(20,180,50,255))
    def test_preview_and_export_share_the_same_composition_and_never_mutate_the_project(self):
        p=self.project();before=copy.deepcopy(p);value=ThumbnailPreview(self.library).prepare(p)
        raw=base64.b64decode(value['image'].split(',')[1]);preview=Image.open(io.BytesIO(raw))
        exported=render(p,self.root/'assets',card_portrait(p,self.root/'assets'),background=background(p,self.library))
        self.assertEqual(preview.tobytes(),exported.tobytes());self.assertEqual(before,p)
    def test_missing_background_is_reported_instead_of_silently_exporting_black(self):
        p=self.project();p['native_card']['layers'][0]['asset_id']='a'*64+'.png'
        with self.assertRaisesRegex(ValueError,'背景资源缺失'):background(p,self.library)

    def test_card_crop_can_exclude_the_opaque_design_without_changing_large_portrait(self):
        p=self.project();p['native_card']['layers'].append({'slot':'f04','kind':'image','asset_id':self.image((0,0,255,255))})
        original=card_portrait(p,self.root/'assets');foreground=card_portrait(p,self.root/'assets',include_underlay=False)
        self.assertEqual(original.getchannel('A').getextrema(),(255,255))
        self.assertEqual(foreground.getchannel('A').getextrema()[0],0)
        self.assertEqual(original.tobytes(),card_portrait(p,self.root/'assets').tobytes())

if __name__=='__main__':unittest.main()
