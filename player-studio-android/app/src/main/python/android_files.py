"""Independent seekable views of SAF file descriptors, without APK copies.

Android may deny reopening /proc/self/fd links. pread on a duplicated, already
authorized descriptor also avoids shared seek positions across ZipFile users.
"""
import builtins,io,json,os,threading

_files={};_lock=threading.RLock();_installed=False
_open=builtins.open;_io_open=io.open;_stat=os.stat

def path_key(path):
    # Android exposes the same private directory through /data/user/0 and
    # /data/data. Java's canonical paths and Python's paths must agree.
    return os.path.realpath(os.path.abspath(os.fsdecode(os.fspath(path))))

def register(path,fd):
    with _lock:_files[path_key(path)]=int(fd)

def unregister(path):
    with _lock:_files.pop(path_key(path),None)

def descriptor(path):
    if isinstance(path,int):return None
    try:key=path_key(path)
    except (TypeError,ValueError):return None
    with _lock:return _files.get(key)

class ReadOnlyDocument(io.RawIOBase):
    def __init__(self,path,fd):
        super().__init__();self.name=os.fspath(path);self.mode='rb';self.fd=os.dup(fd);self.position=0;self.size=os.fstat(self.fd).st_size
    def readable(self):return True
    def seekable(self):return True
    def fileno(self):return self.fd
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        self._checkClosed()
        position=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if position<0:raise ValueError('Invalid document seek')
        self.position=position;return position
    def readinto(self,buffer):
        self._checkClosed();count=min(len(buffer),max(0,self.size-self.position))
        if not count:return 0
        value=os.pread(self.fd,count,self.position);buffer[:len(value)]=value;self.position+=len(value);return len(value)
    def close(self):
        if not self.closed:os.close(self.fd)
        super().close()

def document_open(file,mode='r',buffering=-1,encoding=None,errors=None,newline=None,closefd=True,opener=None):
    with _lock:
        fd=descriptor(file)
        stream=ReadOnlyDocument(file,fd) if fd is not None else None
    if fd is None:return _io_open(file,mode,buffering,encoding,errors,newline,closefd,opener)
    if any(c in mode for c in 'wax+') or opener is not None:
        stream.close();raise PermissionError('导入的原 APK 仅可读取')
    if buffering!=0:stream=io.BufferedReader(stream,buffer_size=512*1024 if buffering<0 else buffering)
    if 'b' not in mode:stream=io.TextIOWrapper(stream,encoding=encoding or 'utf8',errors=errors,newline=newline)
    return stream

def document_stat(path,*args,**kwargs):
    with _lock:
        fd=descriptor(path)
        if fd is not None and kwargs.get('follow_symlinks',True) is not False:return os.fstat(fd)
    return _stat(path,*args,**kwargs)

def install():
    global _installed
    if _installed:return
    from java import jclass
    for path,fd in json.loads(str(jclass('com.playerstudio.editor.NativeFiles').descriptorSnapshot())).items():register(path,fd)
    builtins.open=document_open;io.open=document_open;os.stat=document_stat;_installed=True
