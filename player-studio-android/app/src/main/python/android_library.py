"""Portable resource conversion and indexing for the native Android host."""
from pathlib import Path
import collections,contextlib,hashlib,json,re,shutil,sqlite3,threading,zipfile
from native_library import NativeLibrary as BaseLibrary
from native_movie import convert_movie,extract_ivf,remux_usm

class AndroidLibrary(BaseLibrary):
    def thumbnail_video_frame(self,path,seconds):
        import io
        from PIL import Image
        from java import jclass
        Retriever=jclass('android.media.MediaMetadataRetriever');reader=Retriever();bitmap=None
        try:
            reader.setDataSource(str(path));bitmap=reader.getFrameAtTime(round(seconds*1000000),Retriever.OPTION_CLOSEST)
            if bitmap is None:bitmap=reader.getFrameAtTime()
            if bitmap is None:raise ValueError('手机无法读取卡面背景动画的静态帧')
            stream=jclass('java.io.ByteArrayOutputStream')()
            bitmap.compress(jclass('android.graphics.Bitmap$CompressFormat').PNG,100,stream)
            with Image.open(io.BytesIO(bytes(stream.toByteArray()))) as im:return im.convert('RGBA')
        finally:
            if bitmap is not None:bitmap.recycle()
            reader.release()
    def __init__(self,resources,home,store):
        super().__init__(resources,home,store)
        self.tool=Path(home)/'bundle/.android-bundle.sha256'
        self._decoder=None
    @property
    def decoder(self):
        if self._decoder is None:
            from portable_assets import PortableAssets
            self._decoder=PortableAssets(self.containers)
        return self._decoder
    def summary(self):
        result=super().summary();result['tools_ready']=True;result['platform']='android';return result
    def _setup(self,main,companion):
        existing=set(self.root.glob('prepare-*')) if self.root.exists() else set()
        try:
            sizes={}
            def collect(archive,member,priority=0):
                item=archive.getinfo(member);name=Path(member).name
                if priority and not name.startswith('global.'):
                    p=Path(name);name=p.stem+'_10_P'+p.suffix
                sizes[name]=item.file_size
            with zipfile.ZipFile(main) as archive:
                with archive.open('assets/pc0000_mobile_and.pak') as raw,zipfile.ZipFile(raw) as nested:
                    for name in nested.namelist():
                        if name.endswith(('.pak','.utoc','.ucas')):collect(nested,name,10)
                for name in archive.namelist():
                    if name.startswith(('assets/pc0010_mobile_and.','assets/gateway-release/livedata/','assets/gateway-release/custom-resources/')) and name.endswith(('.pak','.utoc','.ucas')):collect(archive,name,10)
            with zipfile.ZipFile(companion) as archive,archive.open('assets/resource-bootstrap/resources.zip') as raw,zipfile.ZipFile(raw) as nested:
                for name in nested.namelist():
                    if name.endswith(('.pak','.utoc','.ucas')):collect(nested,name)
            need=sum(sizes.values())+256*1024*1024;free=shutil.disk_usage(self.home).free
            if free<need:raise ValueError(f'准备原版资源至少需要 {need/1024**3:.1f} GB 可用空间，目前为 {free/1024**3:.1f} GB')
            super()._setup(main,companion)
        except Exception as exc:self.state={'phase':'error','message':str(exc)}
        finally:
            for path in set(self.root.glob('prepare-*'))-existing:
                if path.parent.resolve()==self.root.resolve() and not path.is_symlink():shutil.rmtree(path)
    def run(self,paths,mode='auto'):
        self.converted.mkdir(parents=True,exist_ok=True)
        from portable_decode import convert
        for path in paths:convert(self.decoder,path,self.converted,mode)
    def face_assets(self):return self.decoder
    def texture_model(self,path,row):
        from native_glb import Glb
        from native_library import glb_textures
        from portable_decode import material_json,texture_image
        document=Glb(path.read_bytes()).doc;bindings={}
        folder=row['path'].rsplit('/',1)[0]
        for material in document.get('materials',[]):
            name=material.get('name','')
            source=material.get('extras',{}).get('studio_material_path') or folder+'/'+name+'.uasset'
            props=material_json(self.decoder,source)[0]['Properties']
            for param in props.get('TextureParameterValues',[]):
                if param.get('ParameterInfo',{}).get('Name','').casefold() not in ('basecolormap','basecolor','diffuse','diffusemap'):continue
                ref=param.get('ParameterValue',{}).get('ObjectPath','')
                if not ref.startswith('/Game/'):continue
                import io
                png=io.BytesIO();texture_image(self.decoder,ref).save(png,format='PNG')
                bindings[name]=(png.getvalue(),props);break
        target=path.with_name(path.stem+'-native.glb')
        return target,glb_textures(path,bindings,target)

def index_assets(library):
    listed={p.removeprefix('../../../') for p in library.decoder.files}
    listed.update(library.decoder.raw_paths())
    rows=[]
    for asset in sorted(listed):
        if not asset.endswith('.uasset'):continue
        name=asset.rsplit('/',1)[-1][:-7]
        if '/Thumbnail/Player/' in asset or ('/RealFace/' in asset and re.fullmatch(r'\d+(?:_|f)',name)):
            kind='portrait' if re.fullmatch(r'\d+_(?:l)?',name) else 'card'
            match=re.match(r'(\d+)',name) if kind=='portrait' or re.fullmatch(r'\d+f',name) else re.search(r'(\d{6,})',name)
        elif '/character/' in asset.casefold() and name.startswith('SK_'):
            kind='model';match=re.match(r'SK_(\d+)',name)
        else:continue
        rows.append((hashlib.sha256(asset.encode()).hexdigest()[:24],asset,name,kind,match.group(1) if match else ''))
    if len(rows)<1000:raise ValueError('新版美术索引数量异常，未替换旧数据库')
    with contextlib.closing(sqlite3.connect(library.resources/'library.sqlite3')) as db,db:
        db.execute('delete from assets');db.executemany('insert into assets values(?,?,?,?,?)',rows)
        summary=json.loads(db.execute('select value from meta where key="summary"').fetchone()[0])
        summary.update(assets=len(rows),by_asset_kind=dict(collections.Counter(row[3] for row in rows)))
        db.execute('update meta set value=? where key="summary"',(json.dumps(summary,ensure_ascii=False),))
    media=json.loads((library.resources/'native-card-media.json').read_text(encoding='utf8'))
    media['movies']=sorted(p for p in listed if p.lower().endswith(('.usm','.webm','.mp4','.m2v')) and '/playercard/' in p.lower())
    (library.resources/'native-card-media.json').write_text(json.dumps(media,ensure_ascii=False),encoding='utf8')
    return len(rows)

def android_movie(source,destination,ffmpeg=None):
    source,destination=Path(source),Path(destination)
    raw=source.read_bytes();stream=extract_ivf(raw)
    if stream.startswith(b'DKIF'):
        result,meta=remux_usm(raw);destination.write_bytes(result);return meta
    if not stream.startswith(b'\0\0\x01\xb3'):raise ValueError('原版视频不是支持的 VP9 或 MPEG-2')
    from java import jclass
    mpeg=destination.with_suffix('.source.m2v');mpeg.write_bytes(stream)
    try:
        result=json.loads(str(jclass('com.playerstudio.editor.MovieBridge').transcode(str(mpeg),str(destination))))
        if not destination.is_file() or destination.read_bytes()[:4]!=b'\x1aE\xdf\xa3':raise ValueError('手机视频转换结果不完整')
        result.update(original_usm_sha256=hashlib.sha256(raw).hexdigest(),source_codec='MPEG-2',reencoded=True)
        return result
    finally:mpeg.unlink(missing_ok=True)
