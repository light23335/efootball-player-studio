"""Personal language rows in the supplied game's unencrypted STR delta format."""
import struct,zlib
from custom_boosters import canonical,context,text_key

def read(raw):
    count,offset=struct.unpack_from('<II',raw)
    if offset!=8 or not 0<count<1024:raise ValueError('游戏文本目录格式改变')
    result=[]
    for i in range(count):
        at,size,name=struct.unpack_from('<III',raw,offset+i*12)
        label=raw[name:raw.index(0,name)].decode('ascii');group=raw[at:at+size]
        n,gid=struct.unpack_from('<II',group);items={}
        for j in range(n):
            key,length,chars,start=struct.unpack_from('<IHHI',group,8+j*12)
            value=group[start:start+length]
            if not value.endswith(b'\0') or key in items:raise ValueError('游戏文本记录无效')
            items[key]=value[:-1].decode('utf8')
        result.append({'name':label,'id':gid,'items':items})
    return result

def write(groups):
    out=bytearray(struct.pack('<II',len(groups),8)+bytes(len(groups)*12))
    names=[]
    for g in groups:names.append(len(out));out.extend(g['name'].encode()+b'\0')
    out.extend(bytes(-len(out)%16))
    for i,g in enumerate(groups):
        start=len(out);items=sorted(g['items'].items());body=bytearray(struct.pack('<II',len(items),g['id'])+bytes(12*len(items)))
        for j,(key,text) in enumerate(items):
            value=text.encode('utf8')+b'\0';chars=len(text.encode('utf-16le'))//2
            if len(value)>65535 or chars>65535:raise ValueError('自定义游戏文本过长')
            struct.pack_into('<IHHI',body,8+j*12,key,len(value),chars,len(body));body.extend(value)
        struct.pack_into('<III',out,8+i*12,start,len(body),names[i]);out.extend(body);out.extend(bytes(-len(out)%16))
    if read(out)!=groups:raise ValueError('游戏文本写入校验失败')
    return bytes(out)

def unwrap(raw):
    if raw[:8]!=bytes.fromhex('ff20d15745535953'):raise ValueError('未验证的游戏文本压缩格式')
    size,decoded=struct.unpack_from('<II',raw,8)
    value=zlib.decompress(raw[16:])
    if size!=len(raw)-16 or len(value)!=decoded:raise ValueError('游戏文本压缩长度无效')
    return value

def wrap(raw):
    data=zlib.compress(raw,1)
    return bytes.fromhex('ff20d15745535953')+struct.pack('<II',len(data),len(raw))+data

def booster_rows(projects,abilities):
    custom={}
    for p in projects:
        for b in p.get('custom_boosters',[]):
            if b['id'] not in p['booster_ids']:continue
            if b['id'] in custom and canonical(custom[b['id']])!=canonical(b):raise ValueError(context(p,b)+'：自建增能文字编号冲突')
            custom[b['id']]=b
    texts={};routes=[]
    for bid,b in sorted(custom.items()):
        key=text_key(bid)
        effect='、'.join(abilities[str(k)]+f' +{v}' for k,v in b['effects'].items() if v)
        texts[key]=b['label'];texts[key+1]=effect+'。' if effect else '未设置能力加成。'
        routes.append({'id':bid,'name':(1142<<16)|key,'description':(1142<<16)|(key+1)})
    return texts,routes

def merge(raw,texts,replace_ids=()):
    groups=read(unwrap(raw));group=next((g for g in groups if g['name']=='Any3W'),None)
    if group is None:group={'name':'Any3W','id':1142,'items':{}};groups.append(group)
    if group['id']!=1142 or (group['items'].keys()&texts.keys())-set(replace_ids):raise ValueError('自建增能文字占用了原版条目')
    group['items'].update(texts)
    return wrap(write(groups))
