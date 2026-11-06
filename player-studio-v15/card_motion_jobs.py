"""Observable, cancellable video imports; no project edits before completion."""
import copy
import json
import logging
import threading
import time
import uuid
from pathlib import Path


class Cancelled(ValueError):pass


class VideoImports:
    def __init__(self,store,ffmpeg,converter=None):
        self.store=store;self.ffmpeg=ffmpeg;self.converter=converter;self.lock=threading.RLock()
        self.state={'phase':'idle'};self.cancel_event=threading.Event();self.native=None

    def update(self,**values):
        with self.lock:self.state.update(values)

    def check_cancel(self):
        if self.cancel_event.is_set():raise Cancelled('视频导入已取消')

    def native_job(self,value):
        with self.lock:self.native=value
        if self.cancel_event.is_set()and value is not None:value.cancel()

    def status(self,identity=None):
        with self.lock:
            if identity and identity!=self.state.get('job_id'):raise ValueError('视频任务已更新，请重新选择视频')
            result=copy.deepcopy(self.state);native=self.native
        if result['phase']=='working':
            result['elapsed_ms']=round((time.monotonic()-result['started'])*1000)
            if native is not None:
                try:
                    info=json.loads(str(native.status()))
                    result.update({k:v for k,v in info.items()if k not in('phase','result','job_id','started')})
                    label={'decode':'读取与裁切视频','encode':'编码'+('大卡'if info.get('role')=='large'else'小卡')+'视频','encoded':'编码完成，准备封装'}.get(info.get('stage'))
                    if label:result['message']=label
                except Exception:logging.exception('Could not read video conversion progress')
        return result

    def start(self,body):
        if not isinstance(body,dict)or body.get('role','both')not in('both','mini'):raise ValueError('动画转换目标无效')
        path=Path(body['path'])
        if not path.is_file()or path.suffix.lower()not in('.mp4','.mov','.webm'):raise ValueError('请选择完整的 MP4、MOV 或 WebM 视频')
        if not 0<path.stat().st_size<=512*1024*1024:raise ValueError('视频须非空且不超过 512 MB')
        crop=[body.get(k,0)for k in('crop_x','crop_y')]
        if any(type(v)not in(int,float)or not -100<=v<=100 for v in crop):raise ValueError('视频裁切位置应在 -100 至 100 之间')
        with self.lock:
            if self.state['phase']=='working':raise ValueError('已有视频正在导入，可等待完成或取消')
            self.cancel_event=threading.Event();self.native=None
            self.state={'phase':'working','job_id':uuid.uuid4().hex,'message':'准备导入视频','stage':'queued',
                        'started':time.monotonic(),'frames':0,'frame_total':0,'role':body.get('role','both')}
            value=copy.deepcopy(body);identity=self.state['job_id']
            threading.Thread(target=self.run,args=(identity,value),name='card-video-import',daemon=True).start()
        return self.status(identity)

    def cancel(self,identity):
        with self.lock:
            if identity!=self.state.get('job_id'):raise ValueError('视频任务已更新，未取消其它任务')
            if self.state['phase']!='working':return self.status(identity)
            self.cancel_event.set();native=self.native;self.state['message']='正在取消并清理视频临时文件'
        if native is not None:native.cancel()
        return self.status(identity)

    def run(self,identity,body):
        from custom_motion_import import convert
        terminal={}
        try:
            result=(self.converter or convert)(self.store,self.ffmpeg,body['path'],['large','mini']if body.get('role','both')=='both'else['mini'],body.get('crop_x',0),body.get('crop_y',0),context=self)
            self.check_cancel();terminal={'phase':'done','message':'动态卡面已转换并校验','result':result}
        except Exception as exc:
            if self.cancel_event.is_set():terminal={'phase':'cancelled','message':'视频导入已取消；原卡面保持'}
            else:logging.exception('Card video import failed');terminal={'phase':'error','message':str(exc)}
        finally:
            with self.lock:
                self.native=None;self.state.update(terminal,elapsed_ms=round((time.monotonic()-self.state['started'])*1000))
                report=copy.deepcopy(self.state);report.pop('started',None)
            try:
                folder=self.store.root/'video-import-reports';folder.mkdir(exist_ok=True)
                (folder/(identity+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
            except Exception:logging.exception('Could not save video import report')
