"""Inspected card-family mini movies; no player identity or equipment overrides."""
from pathlib import Path
import hashlib,json
from studio_resources import bundled_resources

class MiniMovieCompatibility:
    def __init__(self,assets,resources=None):
        self.assets=assets;self.root=Path(resources)if resources else bundled_resources()
        path=self.root/'card-mini-compat.json'
        data=json.loads(path.read_text('utf8'))if path.is_file()else{'movies':[]}
        self.rows=data['movies'];self.cache={};self.art={};self.movies={};self.native_movies={};self.reports=[]

    def redirect(self,name):
        row=next((r for r in self.rows if name in r['mini_names']),None)
        if row is None:return None
        key=row['source_package']
        if key in self.cache:return self.cache[key]
        try:source,_=self.assets.get(key)
        except ValueError:source=None
        accepted={row['source_package_sha256'],*row.get('repaired_package_sha256',[])}
        if source is None or hashlib.sha256(source).hexdigest()not in accepted:
            self.cache[key]=None;self.reports.append({'mini_compatibility':row['label'],'applied':False,'reason':'source movie package differs'})
            return None
        path=(self.root/row['file']).resolve()
        if not path.is_relative_to(self.root.resolve()):raise ValueError('小头像兼容视频路径无效：'+row['label'])
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('小头像兼容视频损坏：'+row['label'])
        from private_card_motion import movie_packages
        from native_movie import remux_usm
        _,info=remux_usm(raw)
        if (info['width'],info['height'])!=(128,128):raise ValueError('小头像兼容视频尺寸不匹配：'+row['label'])
        seed=row.get('mini_seed','kane-0500-317-mini-compat-v1').encode('ascii')
        name='c'+hashlib.sha256(seed+raw).hexdigest()[:11]+'_v'
        for package,data,meta in movie_packages(self.assets,name,raw):self.art[package]=(package,data,meta)
        self.movies['PlayerCard/'+name+'.usm']=raw;target=name[:-2];self.cache[key]=target
        self.reports.append({'mini_compatibility':row['label'],'applied':True,'dimensions':[128,128],
                             'independent_movie_texture':True,'large_movie_unchanged':True,'gameplay_acceptance':'pending user test'})
        return target

    def prepare_large(self,movie_paths,read_movie=None):
        """Repair both native full-card paths for the audited added movies.

        The original USM bytes and full resolution remain untouched. Only the
        known V17 metadata carrier and its YUV dimensions are rebuilt.
        """
        from private_card_motion import movie_metadata_packages
        available={Path(p).stem for p in movie_paths}
        for row in self.rows:
            path=row['source_package'];name=path.rsplit('/',1)[-1]
            if name not in available or not row.get('large_info'):continue
            try:source,_=self.assets.get(path)
            except ValueError:continue
            digest=hashlib.sha256(source).hexdigest()
            accepted={row['source_package_sha256'],*row.get('repaired_package_sha256',[])}
            if digest not in accepted:
                self.reports.append({'large_movie_compatibility':row['label'],'applied':False,'reason':'source movie package differs'});continue
            if read_movie:
                raw=read_movie(name)
                if hashlib.sha256(raw).hexdigest()!=row['source_movie_sha256']:
                    raise ValueError('新增卡面视频与已核对原始资源不一致：'+row['label'])
                self.native_movies['PlayerCard/'+name+'.usm']=raw
                self.reports.append({'native_movie_mount':name,'source_video_unchanged':True,
                                     'mount':'pc0000/cardstudio_content_100_P.pak'})
            if digest in row.get('repaired_package_sha256',[]):
                self.reports.append({'large_movie_compatibility':row['label'],'applied':False,'already_repaired':True});continue
            packages=movie_metadata_packages(self.assets,name,row['large_info'])
            repaired=next(raw for package,raw,_ in packages if package==path)
            if hashlib.sha256(repaired).hexdigest()not in row['repaired_package_sha256']:
                raise ValueError('大卡视频修复模板与核查记录不一致：'+row['label'])
            for package,raw,meta in packages:self.art[package]=(package,raw,meta)
            self.reports.append({'large_movie_compatibility':row['label'],'applied':True,
                'source_video_unchanged':True,'dimensions':[row['large_info']['width'],row['large_info']['height']],
                'frames':row['large_info']['frames'],'gameplay_acceptance':'pending user test'})
