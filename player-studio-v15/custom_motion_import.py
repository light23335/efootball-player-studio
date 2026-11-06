"""Convert user videos to private card movies and content-addressed previews."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
from card_movie_import import encode,mux_ivf

BATCH_ENCODER=None
BACKEND='ffmpeg-vp9-v1'
CACHE_REVISION='card-video-bt601-v3'


def checkpoint(context,**state):
    if context is not None:
        context.check_cancel()
        if state:context.update(**state)


def digest_file(path,context=None):
    h=hashlib.sha256();size=0
    with path.open('rb')as stream:
        for raw in iter(lambda:stream.read(1024*1024),b''):
            checkpoint(context);h.update(raw);size+=len(raw)
            if size>512*1024*1024:raise ValueError('视频不能超过 512 MB')
    return h.hexdigest()


def cached(store,key,context):
    path=store.root/'compiler-cache/card-video-import'/ (key+'.json')
    try:
        entry=json.loads(path.read_text('utf8'))
        if entry.get('revision')!=CACHE_REVISION:return None
        result=entry['result']
        for name in(result['asset_id'],result['preview']['asset_id']):
            if not __import__('re').fullmatch(r'[a-f0-9]{64}\.(usm|webm)',name):return None
            asset=store.root/'assets'/name
            if not asset.is_file()or digest_file(asset,context)!=name.split('.')[0]:return None
        return result
    except (OSError,ValueError,KeyError,TypeError):return None


def cache_result(store,key,result):
    folder=store.root/'compiler-cache/card-video-import';folder.mkdir(parents=True,exist_ok=True)
    target=folder/(key+'.json');temporary=folder/(key+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps({'revision':CACHE_REVISION,'result':result},ensure_ascii=False,separators=(',',':')),'utf8')
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)

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

def convert(store, ffmpeg, source, roles, crop_x=0, crop_y=0,context=None):
    source=Path(source)
    if source.suffix.lower() not in ('.mp4','.mov','.webm') or not source.is_file():raise ValueError('请选择 MP4、MOV 或 WebM 视频')
    if source.stat().st_size>512*1024*1024:raise ValueError('视频不能超过 512 MB')
    if roles not in (['large','mini'],['mini']):raise ValueError('动画转换目标无效')
    if any(type(v)not in(int,float)or not math.isfinite(v)or not -100<=v<=100 for v in(crop_x,crop_y)):raise ValueError('视频裁切位置应在 -100 至 100 之间')
    started=time.monotonic();original=source.stat();result={};specs=[];hit=[]
    checkpoint(context,stage='hash',message='核对视频内容与转换缓存',frames=0,frame_total=0)
    fingerprint=digest_file(source,context)
    for role in roles:
        width,height,seconds=(182,256,10)if role=='large'else(128,128,5)
        params={'role':role,'width':width,'height':height,'fps':30,'frames':30*seconds,
                'crop_x':crop_x if role=='mini'else 0,'crop_y':crop_y if role=='mini'else 0}
        key=hashlib.sha256(json.dumps([CACHE_REVISION,BACKEND,fingerprint,params],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        value=cached(store,key,context)
        if value is not None:result[role]=value;hit.append(role)
        else:specs.append(dict(params,key=key,seconds=seconds))
    hash_ms=round((time.monotonic()-started)*1000)
    checkpoint(context,cache_hits=hit,cache_misses=[s['role']for s in specs],source_sha256=fingerprint,
               role_count=len(roles),stage='cache'if not specs else'decode',message='转换缓存已命中'if not specs else'准备读取视频画面')
    with tempfile.TemporaryDirectory(prefix='card-video-',dir=store.root/'tmp') as tmp:
        folder=Path(tmp)
        encoding={};encode_started=time.monotonic()
        if specs and BATCH_ENCODER is not None:
            encoding=BATCH_ENCODER(source,folder,specs,context=context)or{}
        else:
            for s in specs:
                checkpoint(context,stage='encode',role=s['role'],message='转换'+('大卡'if s['role']=='large'else'小卡')+'视频',frames=0,frame_total=s['frames'])
                if context is None:encode(source,folder/(s['role']+'.ivf'),ffmpeg,s['width'],s['height'],30,s['seconds'],s['crop_x'],s['crop_y'])
                else:encode(source,folder/(s['role']+'.ivf'),ffmpeg,s['width'],s['height'],30,s['seconds'],s['crop_x'],s['crop_y'],context=context)
        encode_ms=round((time.monotonic()-encode_started)*1000)
        current=source.stat()
        if(current.st_size,current.st_mtime_ns)!=(original.st_size,original.st_mtime_ns):raise ValueError('导入期间源视频发生变化，请重新选择')
        mux_started=time.monotonic()
        for s in specs:
            role=s['role'];width,height=s['width'],s['height']
            ivf=folder/(role+'.ivf');usm=folder/(role+'.usm')
            checkpoint(context,stage='mux',role=role,message='封装'+('大卡'if role=='large'else'小卡')+'与动态预览')
            try:
                meta=mux_ivf(ivf,usm)
            except subprocess.CalledProcessError as exc:
                raise ValueError('视频解码或转换失败，请检查文件是否完整、包含视频轨道') from exc
            def save(path):
                checkpoint(context)
                raw=path.read_bytes();name=hashlib.sha256(raw).hexdigest()+path.suffix
                target=store.root/'assets'/name
                if not target.exists():
                    temp=target.with_name('.'+uuid.uuid4().hex+'.tmp')
                    try:temp.write_bytes(raw);temp.replace(target)
                    finally:temp.unlink(missing_ok=True)
                elif hashlib.sha256(target.read_bytes()).hexdigest()!=name.split('.')[0]:raise ValueError('已有动画素材校验失败：'+name)
                return {'asset_id':name}
            result[role]={**save(usm),'preview':save(usm.with_suffix('.webm')),'duration':meta['duration'],'width':width,'height':height}
            if role=='mini':result[role].update(crop_x=crop_x,crop_y=crop_y)
            checkpoint(context);cache_result(store,s['key'],result[role])
    final=source.stat()
    if(final.st_size,final.st_mtime_ns)!=(original.st_size,original.st_mtime_ns):raise ValueError('导入期间源视频发生变化，请重新选择')
    checkpoint(context,stage='verified',message='大小卡视频与动态预览已校验',frames=sum(300 if r=='large' else 150 for r in roles),
               frame_total=sum(300 if r=='large' else 150 for r in roles),metrics={'hash_and_cache_ms':hash_ms,'encode_ms':encode_ms,
               'mux_and_verify_ms':round((time.monotonic()-mux_started)*1000),'total_ms':round((time.monotonic()-started)*1000),**encoding})
    return {role:result[role]for role in roles}
