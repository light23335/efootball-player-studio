"""Strict UE4.26 PAK v11 and IoStore reader shared by Android conversion.

Serialization reference: CUE4Parse FPakInfo/FPakEntry/PakFileReader (Apache-2.0).
Only the original game's AES-ECB, uncompressed, zlib and gzip layouts apply.
"""
from pathlib import Path
import hashlib,struct,zlib
from native_art import Assets
from native_iostore import aes,read_string

class Cursor:
    def __init__(self,data,at=0):self.data=data;self.at=at
    def read(self,fmt):
        size=struct.calcsize('<'+fmt)
        if self.at+size>len(self.data):raise ValueError('原版 PAK 索引不完整')
        value=struct.unpack_from('<'+fmt,self.data,self.at);self.at+=size
        return value[0] if len(value)==1 else value
    def string(self):
        value,self.at=read_string(self.data,self.at);return value
    def bytes(self,count):
        if count<0 or self.at+count>len(self.data):raise ValueError('原版 PAK 数据长度无效')
        value=self.data[self.at:self.at+count];self.at+=count;return value

class Pak:
    def __init__(self,path,key):
        self.path=Path(path);self.key=key
        with self.path.open('rb') as f:
            f.seek(max(0,self.path.stat().st_size-4096));tail=f.read()
        at=tail.rfind(struct.pack('<I',0x5a6f12e1))
        if at<17 or len(tail)-at!=204:raise ValueError('未适配的原版 PAK 页脚：'+path.name)
        version,offset,size=struct.unpack_from('<IQQ',tail,at+4)
        if version!=11 or not 0<size<=128*1024*1024:raise ValueError('未适配的原版 PAK 索引')
        self.encrypted=bool(tail[at-1]);self.methods=['None']+[tail[at+44+i*32:at+76+i*32].split(b'\0')[0].decode() for i in range(5)]
        primary=self._index(offset,size);cur=Cursor(primary)
        self.mount=cur.string();count=cur.read('I');cur.read('Q')
        if count==0:self.files={};self.encoded=b'';return
        if count>2000000 or not self.mount.startswith('../../../'):raise ValueError('原版 PAK 挂载路径或文件数量异常')
        if not cur.read('I'):raise ValueError('原版 PAK 缺少路径索引')
        cur.bytes(36)
        if not cur.read('I'):raise ValueError('原版 PAK 缺少目录索引')
        directory_offset,directory_size=cur.read('QQ');cur.bytes(20)
        self.encoded=cur.bytes(cur.read('I'))
        if cur.read('I')!=0:raise ValueError('此 PAK 的非压缩索引条目尚未适配')
        directory=Cursor(self._index(directory_offset,directory_size));self.files={}
        ndirs=directory.read('I')
        if ndirs>1000000:raise ValueError('原版 PAK 目录数量异常')
        for _ in range(ndirs):
            folder=directory.string();entries=directory.read('I')
            if entries>2000000:raise ValueError('原版 PAK 文件数量异常')
            for _ in range(entries):
                name=directory.string();location=directory.read('i')
                if location==-2147483648:continue
                if location<0:raise ValueError('原版 PAK 条目不是已适配的编码格式')
                self.files[self.mount+folder.lstrip('/')+name]=location
        if len(self.files)!=count:raise ValueError('原版 PAK 目录数量校验失败')
    def _index(self,offset,size):
        if offset<0 or size<0 or offset+size>self.path.stat().st_size:raise ValueError('PAK 索引偏移越界')
        with self.path.open('rb') as f:f.seek(offset);value=f.read(size)
        return aes(value,self.key) if self.encrypted else value
    def read(self,path):
        cur=Cursor(self.encoded,self.files[path]);flags=cur.read('I')
        block_size=cur.read('I') if flags&63==63 else (flags&63)<<11
        method=(flags>>23)&63;offset=cur.read('I' if flags&1<<31 else 'Q')
        size=cur.read('I' if flags&1<<30 else 'Q');encrypted=bool(flags&1<<22)
        compressed=cur.read('I' if flags&1<<29 else 'Q') if method else size
        count=(flags>>6)&0xffff;header=53+(4+16*count if method else 0)
        if size>128*1024*1024 or method>=len(self.methods):raise ValueError('原版 PAK 资源格式或大小不受支持')
        if count==1 and not encrypted:lengths=[compressed]
        else:lengths=[cur.read('I') for _ in range(count)]
        with self.path.open('rb') as f:
            f.seek(offset+header)
            if not method:
                data=f.read((size+15)//16*16 if encrypted else size)
                data=aes(data,self.key) if encrypted else data
                return data[:size]
            result=[]
            for length in lengths:
                value=f.read((length+15)//16*16 if encrypted else length)
                if encrypted:value=aes(value,self.key)
                value=value[:length]
                if self.methods[method]=='Zlib':value=zlib.decompress(value)
                elif self.methods[method]=='Gzip':value=zlib.decompress(value,31)
                else:raise ValueError('此原版 PAK 压缩方法未适配：'+self.methods[method])
                result.append(value)
        data=b''.join(result)
        if len(data)!=size:raise ValueError('原版 PAK 资源解压长度校验失败')
        return data

class PortableAssets(Assets):
    def __init__(self,folder):
        super().__init__(folder);self.folder=Path(folder);self.paks=None
    @staticmethod
    def normalize(path):
        if path.startswith('/Game/'):return '../../../PesMobile/Content/'+path[6:]+('' if path.endswith(('.uasset','.ubulk','.uptnl')) else '.uasset')
        return path if path.startswith('../../../') else '../../../'+path
    def _prepare_paks(self):
        if self.paks is not None:return
        key=(self.folder/'resource-key.bin').read_bytes();self.paks={}
        for path in sorted(self.folder.glob('*.pak'),key=lambda p:('_P' in p.stem,p.name)):
            pak=Pak(path,key)
            for name in pak.files:self.paks[name]=pak
    def raw_paths(self):
        self._prepare_paks();return [p.removeprefix('../../../') for p in self.paks]
    def raw(self,path):
        normalized=self.normalize(path)
        if normalized in self.files:
            container,index=self.files[normalized];return container.read_chunk(index)
        self._prepare_paks()
        if normalized not in self.paks:raise ValueError('原版资源缺失：'+path)
        return self.paks[normalized].read(normalized)
