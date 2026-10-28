"""Convert user videos to private card movies and content-addressed previews."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
from card_movie_import import encode,mux_ivf

def upgrade_legacy(project, files):
    """Restore previews for the earlier experimental USM-only project format."""
    from native_movie import remux_usm
    config=(project.get('native_card') or {}).get('custom_motion')
    if not isinstance(config,dict):return project
    for role in ('large','mini'):
        row=config.get(role)
        if not isinstance(row,dict) or row.get('preview'):continue
        raw=files.get('assets/'+row.get('asset_id',''))
        if not raw:raise ValueError('早期动态工程缺少动画素材')
        webm,_=remux_usm(raw);target=hashlib.sha256(webm).hexdigest()+'.webm'
        files['assets/'+target]=webm;row['preview']={'asset_id':target}
    return project

def convert(store, ffmpeg, source, roles, crop_x=0, crop_y=0):
    source=Path(source)
    if source.suffix.lower() not in ('.mp4','.mov','.webm') or not source.is_file():raise ValueError('请选择 MP4、MOV 或 WebM 视频')
    if source.stat().st_size>512*1024*1024:raise ValueError('视频不能超过 512 MB')
    if roles not in (['large','mini'],['mini']):raise ValueError('动画转换目标无效')
    result={}
    with tempfile.TemporaryDirectory(prefix='card-video-',dir=store.root/'tmp') as tmp:
        folder=Path(tmp)
        for role in roles:
            width,height,seconds=(182,256,10) if role=='large' else (128,128,5)
            ivf=folder/(role+'.ivf');usm=folder/(role+'.usm')
            try:
                encode(source,ivf,ffmpeg,width,height,30,seconds,crop_x if role=='mini' else 0,crop_y if role=='mini' else 0)
                meta=mux_ivf(ivf,usm)
            except subprocess.CalledProcessError as exc:
                raise ValueError('视频解码或转换失败，请检查文件是否完整、包含视频轨道') from exc
            def save(path):
                raw=path.read_bytes();name=hashlib.sha256(raw).hexdigest()+path.suffix
                target=store.root/'assets'/name
                if not target.exists():target.write_bytes(raw)
                return {'asset_id':name}
            result[role]={**save(usm),'preview':save(usm.with_suffix('.webm')),'duration':meta['duration'],'width':width,'height':height}
            if role=='mini':result[role].update(crop_x=crop_x,crop_y=crop_y)
    return result
