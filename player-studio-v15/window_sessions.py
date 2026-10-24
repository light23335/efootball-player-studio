"""Exit the desktop service when its last editor window closes."""
import threading,uuid
import copy

def apply_project_delta(project,operations):
    if not isinstance(operations,list) or len(operations)>10000:raise ValueError('关闭时工程变更格式无效')
    result=copy.deepcopy(project)
    for row in operations:
        path=row['path']
        if not isinstance(path,list) or not path or len(path)>32 or any(type(k) not in (str,int) for k in path):raise ValueError('工程变更路径无效')
        target=result
        for key in path[:-1]:target=target[key]
        key=path[-1]
        if row['op']=='set':target[key]=row['value']
        elif row['op']=='remove':del target[key]
        elif row['op']=='splice':
            array=target[key];start,count,items=row['start'],row['count'],row['items']
            if not isinstance(array,list) or type(start) is not int or type(count) is not int or not 0<=start<=len(array) or not 0<=count<=len(array)-start or not isinstance(items,list):raise ValueError('工程列表变更无效')
            array[start:start+count]=items
        else:raise ValueError('工程变更操作无效')
    return result

class WindowSessions:
    def __init__(self, shutdown, grace=2):
        self.shutdown=shutdown;self.grace=grace;self.sessions=set();self.lock=threading.RLock();self.timer=None
    def open(self, session):
        session=str(uuid.UUID(session))
        with self.lock:
            self.sessions.add(session)
            if self.timer:self.timer.cancel();self.timer=None
        return {'opened':True}
    def close(self, session, save):
        session=str(uuid.UUID(session))
        with self.lock:
            if session not in self.sessions:return {'closed':False}
            save()
            self.sessions.remove(session)
            if self.timer:self.timer.cancel()
            if not self.sessions:
                self.timer=threading.Timer(self.grace,self.finish)
                self.timer.daemon=True;self.timer.start()
        return {'closed':True}
    def finish(self):
        with self.lock:
            if self.sessions:return
        self.shutdown()
