"""Minimal CRI UTF/CPK and current WESYS adapter for the supplied V13 data.

An edit keeps the original archive layout and touches only explicitly selected
files and their numeric TOC cells. Other container formats fail closed.
"""
import struct
import zlib


def utf_xor(raw):
    out=bytearray(raw)
    state=0x655f
    for i in range(len(out)):
        out[i]^=state&255
        state=state*0x4115&0xffffffff
    return bytes(out)


FORMATS={0:('>B',1),1:('>b',1),2:('>H',2),3:('>h',2),4:('>I',4),5:('>i',4),6:('>Q',8),7:('>q',8),8:('>f',4),9:('>d',8),10:('>I',4),11:('>Q',8)}


class Utf:
    def __init__(self,raw):
        self.encrypted=raw[:4]!=b'@UTF'
        self.raw=bytearray(utf_xor(raw) if self.encrypted else raw)
        b=self.raw
        if b[:4]!=b'@UTF':raise ValueError('Unsupported CPK UTF table')
        ro,so,do,no,ncols,rowlen,nrows=struct.unpack_from('>IIIIHHI',b,8)
        if nrows>100000 or ncols>256:raise ValueError('CPK UTF table is too large')
        strings=b[8+so:8+do]
        def string(index):
            end=strings.index(0,index)
            return bytes(strings[index:end]).decode('utf8')
        offset=32
        columns=[]
        cursor=0
        for _ in range(ncols):
            flag=b[offset];name=string(struct.unpack_from('>I',b,offset+1)[0]);offset+=5
            storage,kind=flag&240,flag&15
            fmt,width=FORMATS[kind]
            if storage==0x10:at=None
            elif storage==0x30:at=offset;offset+=width
            elif storage==0x50:at=cursor;cursor+=width
            else:raise ValueError('Unknown CPK UTF storage')
            columns.append((name,storage,kind,fmt,at))
        self.rows=[];self.cells={}
        for row in range(nrows):
            item={}
            for name,storage,kind,fmt,at in columns:
                pos=8+ro+row*rowlen+at if storage==0x50 else at
                value=struct.unpack_from(fmt,b,pos)[0] if pos is not None else 0
                item[name]=string(value) if kind==10 else value
                if pos is not None and kind not in (10,11):self.cells[row,name]=(pos,fmt)
            self.rows.append(item)

    def set(self,row,key,value):
        if (row,key) not in self.cells:raise ValueError('CPK numeric cell cannot be changed')
        offset,fmt=self.cells[row,key]
        struct.pack_into(fmt,self.raw,offset,value)
        self.rows[row][key]=value

    def bytes(self):
        return utf_xor(self.raw) if self.encrypted else bytes(self.raw)


class Cpk:
    def __init__(self,raw):
        self.raw=bytes(raw)
        if raw[:4]!=b'CPK ':raise ValueError('Not a supported CPK archive')
        def table(offset):
            start=offset+16
            prefix=raw[start:start+8]
            decoded=prefix if prefix[:4]==b'@UTF' else utf_xor(prefix)
            length=struct.unpack_from('>I',decoded,4)[0]+8
            result=Utf(raw[start:start+length])
            if result.bytes()!=raw[start:start+length]:raise ValueError('Original CPK index failed byte-exact roundtrip')
            return start,length,result
        self.header_at,self.header_size,self.header=table(0)
        h=self.header.rows[0]
        self.toc_at,self.toc_size,self.toc=table(h['TocOffset'])
        self.base=min(h['TocOffset'],h['ContentOffset'])
        self.align=h.get('Align') or 2048
        self.files={}
        for i,row in enumerate(self.toc.rows):
            name=(row.get('DirName','')+'/').lstrip('/')+row['FileName']
            if name in self.files:raise ValueError('Duplicate CPK file')
            self.files[name]=i

    def read(self,name):
        row=self.toc.rows[self.files[name]]
        if row['FileSize']!=row['ExtractSize']:raise ValueError('Compressed outer CPK entry is not supported by this adapter')
        start=self.base+row['FileOffset'];end=start+row['FileSize']
        if end>len(self.raw):raise ValueError('CPK file is truncated')
        return self.raw[start:end]

    def replace(self,replacements):
        originals={name:self.read(name) for name in self.files}
        out=bytearray(self.raw)
        for name,value in replacements.items():
            index=self.files[name];row=self.toc.rows[index]
            at=self.base+row['FileOffset']
            if len(value)<=row['FileSize']:
                out[at:at+row['FileSize']]=value+b'\0'*(row['FileSize']-len(value))
            else:
                out.extend(b'\0'*((-len(out))%self.align));at=len(out)
                out.extend(value);out.extend(b'\0'*((-len(out))%self.align))
                self.toc.set(index,'FileOffset',at-self.base)
            self.toc.set(index,'FileSize',len(value));self.toc.set(index,'ExtractSize',len(value))
        self.header.set(0,'ContentSize',len(out)-self.header.rows[0]['ContentOffset'])
        out[self.header_at:self.header_at+self.header_size]=self.header.bytes()
        out[self.toc_at:self.toc_at+self.toc_size]=self.toc.bytes()
        check=Cpk(out)
        for name in self.files:
            if check.read(name)!=(replacements[name] if name in replacements else originals[name]):
                raise ValueError('CPK read-back mismatch: '+name)
        return bytes(out)


def wesys_crypt(data,key,size,original):
    seeds={1:(0x168ea000,0x2e2aa6f2,0x0cc8dcd3),2:(0xed5b2960,0x4a523b4e,0xf3a31bad)}
    if key not in seeds:raise ValueError('Unsupported WESYS data version')
    x,y,z=seeds[key];w=((original<<16)|size)&0xffffffff;out=bytearray(data)
    for offset in range(0,len(out)-len(out)%4,4):
        t=(x^(x<<11))&0xffffffff
        x,y,z=y,z,w
        w=(w^(((w>>11)^t)>>8)^t)&0xffffffff
        struct.pack_into('<I',out,offset,struct.unpack_from('<I',out,offset)[0]^w)
    return bytes(out)


def unwrap(raw):
    if raw[:1]!=b'\xff' or raw[3:8]!=b'WESYS':raise ValueError('Unsupported V13 WESYS wrapper')
    size,original=struct.unpack_from('<II',raw,8)
    if len(raw)!=16+size:raise ValueError('WESYS size mismatch')
    if not size:return b''
    decoded=zlib.decompress(wesys_crypt(raw[16:],raw[1]&15,size,original))
    if len(decoded)!=original:raise ValueError('WESYS decoded size mismatch')
    return decoded


def wrap(raw,original_wrapper):
    if unwrap(original_wrapper)==raw:return original_wrapper
    key=original_wrapper[1]&15
    compressed=zlib.compress(raw,1)
    return struct.pack('<BBB5sII',255,0x20|key,0x83,b'WESYS',len(compressed),len(raw))+wesys_crypt(compressed,key,len(compressed),len(raw))
