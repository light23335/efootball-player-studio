"""Bounded-memory export payloads with independently checkable content identity."""
from contextlib import contextmanager
from dataclasses import dataclass,field
import hashlib
import io
import os
from pathlib import Path
import struct,threading,zipfile
import zlib

BLOCK = 1024 * 1024


class FileView(io.RawIOBase):
    """Seekable bounded view; never exposes surrounding APK/cache ZIP bytes."""
    def __init__(self,stream,offset,size):
        super().__init__();self.stream=stream;self.offset=offset;self.size=size;self.position=0
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        target=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if target<0:raise ValueError('Invalid payload seek')
        self.position=target;return target
    def read(self,size=-1):
        size=max(0,self.size-self.position)if size is None or size<0 else min(size,max(0,self.size-self.position))
        self.stream.seek(self.offset+self.position);raw=self.stream.read(size);self.position+=len(raw);return raw
    def readinto(self,buffer):
        raw=self.read(len(buffer));buffer[:len(raw)]=raw;return len(raw)


class FileLease:
    """Keep a cache inode open until the export finishes, including on POSIX."""
    def __init__(self,path):
        self.stream=Path(path).open('rb');self.file_identity=identity(os.fstat(self.stream.fileno()));self.lock=threading.RLock()
    @contextmanager
    def open(self):
        with self.lock:
            if self.stream.closed:raise ValueError('导出缓存已释放')
            if identity(os.fstat(self.stream.fileno()))!=self.file_identity:raise ValueError('导出缓存已变化')
            yield self.stream
            if identity(os.fstat(self.stream.fileno()))!=self.file_identity:raise ValueError('导出缓存在读取时发生变化')
    def close(self):
        with self.lock:self.stream.close()


def identity(stat):
    # Windows path.stat and fstat may expose different ctime semantics.
    # Content is additionally checked by SHA-256 during every payload copy.
    return stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev


def measure(stream, destination=None):
    digest = hashlib.sha256(); size = crc = 0
    while True:
        block = stream.read(BLOCK)
        if not block: break
        if destination is not None and destination.write(block) != len(block):
            raise OSError('导出临时文件写入不完整')
        digest.update(block); size += len(block); crc = zlib.crc32(block, crc)
    return {'bytes': size, 'sha256': digest.hexdigest(), 'crc32': crc & 0xffffffff}


@dataclass(frozen=True)
class FilePayload:
    path: Path
    bytes: int
    sha256: str
    crc32: int
    file_identity: tuple
    offset: int=0
    lease: object=field(default=None,compare=False,repr=False)

    @classmethod
    def from_path(cls, path):
        path = Path(path)
        with path.open('rb') as stream:
            before = identity(os.fstat(stream.fileno())); info = measure(stream)
            if identity(os.fstat(stream.fileno())) != before:
                raise ValueError('导出资源在计算校验时发生变化：' + path.name)
        if identity(path.stat()) != before:
            raise ValueError('导出资源在计算校验时被替换：' + path.name)
        return cls(path, **info, file_identity=before)

    @classmethod
    def from_zip(cls,archive,member,*,lease=None):
        """Hash actual member bytes once, retaining a file/ZIP reference, not a copy."""
        if archive.filename is None:raise ValueError('ZIP 引用需要实际来源路径')
        path=Path(archive.filename);before=identity(path.stat());entry=archive.getinfo(member)
        if identity(os.fstat(archive.fp.fileno()))!=before or(lease and lease.file_identity!=before):raise ValueError('ZIP 来源在打开后被替换')
        if entry.flag_bits&1 or sum(i.filename==member for i in archive.infolist())!=1:raise ValueError('ZIP 资源索引无效')
        with archive.open(entry)as stream:info=measure(stream)
        if info['bytes']!=entry.file_size or info['crc32']!=entry.CRC:raise ValueError('ZIP 资源内容校验失败')
        if identity(path.stat())!=before:raise ValueError('ZIP 来源在核对时发生变化')
        if entry.compress_type!=zipfile.ZIP_STORED:
            return ZipPayload(path,**info,file_identity=before,member=member)
        with path.open('rb')as stream:
            stream.seek(entry.header_offset);head=stream.read(30)
            if len(head)!=30 or head[:4]!=b'PK\x03\x04':raise ValueError('ZIP 本地索引无效')
            flags,method=struct.unpack_from('<HH',head,6);n,e=struct.unpack_from('<HH',head,26)
            name=stream.read(n).decode('utf8'if flags&0x800 else'cp437')
        offset=entry.header_offset+30+n+e
        if name!=member or method!=zipfile.ZIP_STORED or offset+entry.file_size>archive.start_dir:raise ValueError('ZIP 文件区间越界')
        return cls(path,**info,file_identity=before,offset=offset,lease=lease)

    @contextmanager
    def open(self):
        with (self.lease.open()if self.lease else self.path.open('rb')) as stream:
            if identity(os.fstat(stream.fileno())) != self.file_identity:
                raise ValueError('导出资源已变化：' + self.path.name)
            if self.offset<0 or self.offset+self.bytes>self.file_identity[0]:raise ValueError('导出文件区间越界')
            yield FileView(stream,self.offset,self.bytes)
            if identity(os.fstat(stream.fileno())) != self.file_identity or(not self.lease and identity(self.path.stat()) != self.file_identity):
                raise ValueError('导出资源在读取时发生变化：' + self.path.name)

    def copy_to(self, destination):
        with self.open() as stream:
            actual = measure(stream, destination)
        if actual != {'bytes': self.bytes, 'sha256': self.sha256, 'crc32': self.crc32}:
            raise ValueError('导出资源内容校验失败：' + self.path.name)


@dataclass(frozen=True)
class ZipPayload(FilePayload):
    member: str=''
    @contextmanager
    def open(self):
        with self.path.open('rb')as source:
            if identity(os.fstat(source.fileno()))!=self.file_identity:raise ValueError('ZIP 来源已变化')
            with zipfile.ZipFile(source)as archive,archive.open(self.member)as stream:yield stream
            if identity(os.fstat(source.fileno()))!=self.file_identity or identity(self.path.stat())!=self.file_identity:raise ValueError('ZIP 来源在读取时发生变化')


def payload(value):
    if isinstance(value, Path): return FilePayload.from_path(value)
    if isinstance(value,(bytearray,memoryview)):return bytes(value)
    if not isinstance(value, (FilePayload, bytes, bytearray, memoryview)):
        raise TypeError('APK 替换资源必须是字节或文件路径')
    return value


def metadata(value):
    value = payload(value)
    if isinstance(value, FilePayload): return {'bytes': value.bytes, 'sha256': value.sha256}
    return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}


def extract(archive, member, path):
    """Read to EOF, so ZipExtFile also verifies the original ZIP CRC."""
    path = Path(path)
    try:
        with archive.open(member) as source, path.open('xb') as destination:
            info = measure(source, destination)
        if archive.getinfo(member).file_size != info['bytes']:
            raise ValueError('APK 资源长度不完整：' + member)
        # The buffered file's final size/mtime is authoritative after close.
        file_identity = identity(path.stat())
        return FilePayload(path, **info, file_identity=file_identity)
    except Exception:
        # Do not delete another caller's pre-existing target on exclusive-open failure.
        if 'destination' in locals(): path.unlink(missing_ok=True)
        raise


def verified_engine(archive, work, expected):
    result = extract(archive, 'lib/arm64-v8a/libUE4.so', Path(work) / 'verified-libUE4.so')
    if result.sha256 != expected:
        result.path.unlink(missing_ok=True)
        raise ValueError('此 APK 的完整引擎指纹与已验证模板不同，未生成安装包')
    return result


def verify_replacements(archive, replacements,*,capture=()):
    digests={};captured={}
    for name, value in replacements.items():
        expected = metadata(value)
        if archive.getinfo(name).file_size != expected['bytes']:
            raise ValueError('生成的 APK 文件长度校验失败：' + name)
        buffer=io.BytesIO()if name in capture and expected['bytes']<=16*1024**2 else None
        with archive.open(name) as stream:actual=measure(stream,buffer)
        if any(actual[key] != expected[key] for key in expected):
            raise ValueError('生成的 APK 文件校验失败：' + name)
        digests[name]={key:actual[key]for key in('bytes','sha256')}
        if buffer is not None:captured[name]=buffer.getvalue()
    return {'digests':digests,'captured':captured}
