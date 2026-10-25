"""Reject malformed repacked DEX files before signing an editor release."""
import hashlib,struct,zlib

def inspect_dex(raw):
    if len(raw)<112 or raw[:4]!=b'dex\n' or raw[7]!=0:raise ValueError('Invalid DEX header')
    if struct.unpack_from('<III',raw,32)!=(len(raw),112,0x12345678):raise ValueError('Invalid DEX size or endian tag')
    if hashlib.sha1(raw[32:]).digest()!=raw[12:32] or zlib.adler32(raw[12:])&0xffffffff!=struct.unpack_from('<I',raw,8)[0]:raise ValueError('Invalid DEX checksum')
    def table(size_at,offset_at,stride):
        n=struct.unpack_from('<I',raw,size_at)[0];at=struct.unpack_from('<I',raw,offset_at)[0]
        if n and (at<112 or at+n*stride>len(raw)):raise ValueError('DEX table out of bounds')
        return n,at
    n,at=table(56,60,4);strings=[];previous=None
    for i in range(n):
        pos=struct.unpack_from('<I',raw,at+i*4)[0];units=0;shift=0
        while True:
            value=raw[pos];pos+=1;units|=(value&127)<<shift
            if value<128:break
            shift+=7
            if shift>28:raise ValueError('DEX string length overflow')
        decoded=[]
        while raw[pos]:
            value=raw[pos];pos+=1
            if value<128:decoded.append(value)
            elif value&0xe0==0xc0:
                b=raw[pos];pos+=1
                if b&0xc0!=0x80:raise ValueError('Invalid DEX MUTF8')
                decoded.append(((value&31)<<6)|(b&63))
            elif value&0xf0==0xe0:
                b,c=raw[pos:pos+2];pos+=2
                if b&0xc0!=0x80 or c&0xc0!=0x80:raise ValueError('Invalid DEX MUTF8')
                decoded.append(((value&15)<<12)|((b&63)<<6)|(c&63))
            else:raise ValueError('Invalid DEX MUTF8 lead byte')
        if len(decoded)!=units:raise ValueError('DEX UTF16 length mismatch')
        key=tuple(decoded)
        if previous is not None and key<=previous:raise ValueError('DEX string_ids out of order: rebuild with D8; do not replace class-name bytes')
        previous=key
        strings.append(b''.join(struct.pack('<H',v) for v in decoded).decode('utf-16-le','surrogatepass'))
    n,at=table(64,68,4);types=[];previous=-1
    for i in range(n):
        index=struct.unpack_from('<I',raw,at+i*4)[0]
        if not previous<index<len(strings):raise ValueError('Invalid DEX type_ids order')
        previous=index;types.append(strings[index])
    n,at=table(96,100,32);classes=[];seen=set()
    for i in range(n):
        index=struct.unpack_from('<I',raw,at+i*32)[0]
        # Class definitions are in dependency order, not type-index order.
        if not 0<=index<len(types) or index in seen:raise ValueError('Invalid or duplicate DEX class definition')
        seen.add(index);classes.append(types[index])
    return {'strings':len(strings),'classes':classes,'sha256':hashlib.sha256(raw).hexdigest()}

def inspect_runtime(files):
    classes=set();reports={}
    for name,raw in files.items():
        report=inspect_dex(raw);duplicate=classes.intersection(report['classes'])
        if duplicate:raise ValueError('Duplicate Android runtime classes: '+str(sorted(duplicate)[:5]))
        classes.update(report['classes']);reports[name]={'strings':report['strings'],'classes':len(report['classes']),'sha256':report['sha256']}
    required={f'Lcom/playerstudio/editor/{name};' for name in ('MainActivity','BaseActivity','ExportProvider','StudioService','InstalledGames','NativeFiles','ControllerBridge','MovieBridge')}
    if required-classes:raise ValueError('Missing compiled Android components: '+str(sorted(required-classes)))
    return {'dex':reports,'required_components_present':True,'ordered_string_tables':True,'duplicate_classes':False}
