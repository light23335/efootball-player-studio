"""Layout-preserving DEX string renaming with all string references remapped.

Package constants are ordinary string IDs, not byte blobs: changing their sort
order requires rewriting their consumers. No Java runtime is needed on phones.
"""
import hashlib,struct,zlib


def _uleb(raw,at,signed=False):
    start=at;value=0;shift=0
    while at<len(raw) and at-start<5:
        byte=raw[at];at+=1;value|=(byte&127)<<shift;shift+=7
        if byte<128:
            if signed and byte&64:value-=1<<shift
            return value,at
    raise ValueError('DEX LEB128 数据无效')


def _strings(raw):
    count,table=struct.unpack_from('<II',raw,56);result=[]
    if table+4*count>len(raw):raise ValueError('DEX 字符串索引越界')
    for i in range(count):
        offset=struct.unpack_from('<I',raw,table+i*4)[0];units,at=_uleb(raw,offset);start=at;decoded=[]
        while at<len(raw) and raw[at]:
            a=raw[at];at+=1
            if a<128:decoded.append(a)
            elif a&224==192:
                b=raw[at];at+=1
                if b&192!=128:raise ValueError('DEX MUTF8 数据无效')
                decoded.append(((a&31)<<6)|(b&63))
            elif a&240==224:
                b,c=raw[at:at+2];at+=2
                if b&192!=128 or c&192!=128:raise ValueError('DEX MUTF8 数据无效')
                decoded.append(((a&15)<<12)|((b&63)<<6)|(c&63))
            else:raise ValueError('DEX MUTF8 数据无效')
        if at>=len(raw) or len(decoded)!=units:raise ValueError('DEX 字符串长度无效')
        result.append((offset,start,at,tuple(decoded)))
    return table,result


def _check_header(raw):
    if len(raw)<112 or raw[:4]!=b'dex\n' or raw[7]!=0 or struct.unpack_from('<III',raw,32)!=(len(raw),112,0x12345678):raise ValueError('DEX 格式不支持安全共存修改')
    if hashlib.sha1(raw[32:]).digest()!=raw[12:32] or zlib.adler32(raw[12:])&0xffffffff!=struct.unpack_from('<I',raw,8)[0]:raise ValueError('DEX 校验和无效')


def _check_ids(raw,count):
    def table(at,stride):
        n,offset=struct.unpack_from('<II',raw,at)
        if n and (offset<112 or offset+n*stride>len(raw)):raise ValueError('DEX 索引表越界')
        return n,offset
    n,at=table(64,4);descriptors=[struct.unpack_from('<I',raw,at+4*i)[0] for i in range(n)]
    if any(x>=count for x in descriptors) or descriptors!=sorted(set(descriptors)):raise ValueError('DEX 类型索引顺序无效')
    for location,kind in ((80,'field'),(88,'method')):
        n,at=table(location,8);keys=[]
        for i in range(n):
            owner,other,name=struct.unpack_from('<HHI',raw,at+8*i)
            if name>=count:raise ValueError('DEX 名称索引越界')
            keys.append((owner,name,other))
        if keys!=sorted(set(keys)):raise ValueError('DEX '+kind+' 索引顺序改变，需要重新编译')


def rewrite(raw,replacements):
    """Return (DEX, changed string count); also repairs old unsorted rewrites.

    Equal-sized package constants keep every section and instruction address
    stable. If an index would need a wider instruction/encoding, refuse rather
    than producing a damaged file. Supported stock APKs are regression tested.
    """
    _check_header(raw);out=bytearray(raw);table,original=_strings(raw);changed=0
    for _,start,end,_ in original:
        before=bytes(out[start:end]);after=before
        for source,target in replacements.items():
            a,b=source.encode('ascii'),target.encode('ascii')
            if len(a)!=len(b):raise ValueError('共存包名须保持原生常量长度')
            after=after.replace(a,b)
        if after!=before:out[start:end]=after;changed+=1
    _,strings=_strings(out);order=sorted(range(len(strings)),key=lambda i:strings[i][3]);mapping={old:new for new,old in enumerate(order)}
    if len({x[3] for x in strings})!=len(strings):raise ValueError('共存改名产生重复 DEX 常量，未生成无效安装包')
    if order==list(range(len(strings))):
        _check_ids(out,len(strings))
        if not changed:return raw,0
    else:
        def mapped(value):
            if not 0<=value<len(strings):raise ValueError('DEX 字符串引用越界')
            return mapping[value]
        def fixed(at,width,none=False):
            value=int.from_bytes(out[at:at+width],'little')
            if none and value==0xffffffff:return
            value=mapped(value)
            if value>=1<<(width*8):raise ValueError('DEX 字符串指令需要扩展，未写入不完整的共存代码')
            out[at:at+width]=value.to_bytes(width,'little')
        def leb(at,reference=False,p1=False,signed=False):
            value,end=_uleb(out,at,signed)
            if reference and (not p1 or value):
                new=mapped(value-1 if p1 else value)+(1 if p1 else 0);width=end-at
                if new>=1<<(width*7):raise ValueError('DEX 字符串编码需要扩展，未写入不完整的共存代码')
                for i in range(width):out[at+i]=((new>>(7*i))&127)|(128 if i<width-1 else 0)
            return value,end
        def index_table(header,stride,field):
            n,at=struct.unpack_from('<II',out,header)
            for i in range(n):fixed(at+i*stride+field,4,header==96)
        for header,stride,field in ((64,4,0),(72,12,0),(80,8,4),(88,8,4),(96,32,16)):index_table(header,stride,field)
        map_at=struct.unpack_from('<I',out,52)[0]
        maps={}
        if not 112<=map_at<len(out)-4:raise ValueError('DEX 缺少有效的数据分区表')
        for i in range(struct.unpack_from('<I',out,map_at)[0]):
            kind,_,size,offset=struct.unpack_from('<HHII',out,map_at+4+12*i);maps[kind]=(size,offset)

        def annotation(at):
            _,at=leb(at);count,at=leb(at);last=-1
            for _ in range(count):
                old,pos=leb(at,True);new=mapped(old)
                if new<=last:raise ValueError('DEX 注解名称顺序改变，需要重新编译')
                last=new;at=value(pos)
            return at
        def value(at):
            head=out[at];at+=1;kind=head&31;width=(head>>5)+1
            if kind==0x17:fixed(at,width);return at+width
            if kind==0x1c:
                count,at=leb(at)
                for _ in range(count):at=value(at)
                return at
            if kind==0x1d:return annotation(at)
            if kind in (0x1e,0x1f):return at
            if kind not in (0,2,3,4,6,0x10,0x11,0x15,0x16,0x18,0x19,0x1a,0x1b):raise ValueError('未知 DEX 常量类型')
            return at+width

        count,at=maps.get(0x2004,(0,0))
        for _ in range(count):at=annotation(at+1)
        count,at=maps.get(0x2005,(0,0))
        for _ in range(count):
            size,at=leb(at)
            for _ in range(size):at=value(at)
        count,at=maps.get(0x2003,(0,0))
        for _ in range(count):
            _,at=leb(at);parameters,at=leb(at)
            for _ in range(parameters):_,at=leb(at,True,True)
            while True:
                op=out[at];at+=1
                if op==0:break
                if op in (1,5,6):_,at=leb(at)
                elif op==2:_,at=leb(at,signed=True)
                elif op in (3,4):
                    _,at=leb(at);_,at=leb(at,True,True);_,at=leb(at)
                    if op==4:_,at=leb(at,True,True)
                elif op==9:_,at=leb(at,True,True)
                elif op<7:raise ValueError('未知 DEX 调试指令')
        widths=[0]*256
        for a,b,w in ((0,1,1),(1,2,1),(2,3,2),(3,4,3),(4,5,1),(5,6,2),(6,7,3),(7,8,1),(8,9,2),(9,10,3),(10,19,1),
                      (19,20,2),(20,21,3),(21,23,2),(23,24,3),(24,25,5),(25,27,2),(27,28,3),(28,29,2),(29,31,1),(31,33,2),(33,34,1),
                      (34,36,2),(36,39,3),(39,41,1),(41,42,2),(42,45,3),(45,62,2),(68,110,2),(110,115,3),(116,121,3),
                      (123,144,1),(144,176,2),(176,208,1),(208,227,2),(250,252,4),(252,254,3),(254,256,2)):
            widths[a:b]=[w]*(b-a)
        count,at=maps.get(0x2001,(0,0))
        for _ in range(count):
            at=(at+3)&~3;tries=struct.unpack_from('<H',out,at+6)[0];units=struct.unpack_from('<I',out,at+12)[0];pc=at+16;end=pc+units*2
            while pc<end:
                word=struct.unpack_from('<H',out,pc)[0];op=word&255;size=widths[op]
                if op==0 and word:
                    n=struct.unpack_from('<H',out,pc+2)[0]
                    if word==0x100:size=4+2*n
                    elif word==0x200:size=2+4*n
                    elif word==0x300:size=4+(n*struct.unpack_from('<I',out,pc+4)[0]+1)//2
                    else:raise ValueError('未知 DEX 指令数据区')
                if not size or pc+size*2>end:raise ValueError('DEX 指令长度无效')
                if op==0x1a:fixed(pc+2,2)
                elif op==0x1b:fixed(pc+2,4)
                pc+=size*2
            at=end
            if tries:
                at=(at+3)&~3;at+=tries*8;handlers,at=leb(at)
                for _ in range(handlers):
                    size,at=leb(at,signed=True)
                    for _ in range(abs(size)):_,at=leb(at);_,at=leb(at)
                    if size<=0:_,at=leb(at)
        for new,old in enumerate(order):struct.pack_into('<I',out,table+new*4,strings[old][0])
        _check_ids(out,len(strings))
    out[12:32]=hashlib.sha1(out[32:]).digest();struct.pack_into('<I',out,8,zlib.adler32(out[12:])&0xffffffff)
    inspect(bytes(out))
    return bytes(out),changed


def inspect(raw):
    _check_header(raw);_,strings=_strings(raw);keys=[s[3] for s in strings]
    if keys!=sorted(set(keys)):raise ValueError('DEX 字符串索引未正确排序')
    _check_ids(raw,len(strings))
    return {'strings':len(strings),'sha256':hashlib.sha256(raw).hexdigest(),'ordered_string_ids':True}
