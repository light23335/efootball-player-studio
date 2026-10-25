"""Route personal art through the existing, build-checked native installer.

Shared by the desktop compiler and the Android gateway. No player identity or
save serial is changed. Original native hooks remain the fallback for all
unregistered IDs.
"""
import copy
import hashlib
import json
import struct
import sys
import types

_RESIDENT_TABLES=[]
_EXTENSION_PAGES=[]
_PREVIEW_TABLES=[]
_PREVIEW_SCORES={}
PREVIEW_CAPACITY=65536


def set_preview_score(cid,score):
    if type(cid) is not int or not 0<cid<2**63 or type(score) is not int or not 1<=score<=127:
        raise ValueError('卡包预览总评编号或数值无效')
    _PREVIEW_SCORES[cid]=score
    for table in _PREVIEW_TABLES[-1:]:_write_preview(table,cid,score)


def _write_preview(table,cid,score):
    slot=(cid^(cid>>32))&(PREVIEW_CAPACITY-1)
    for _ in range(PREVIEW_CAPACITY):
        at=slot*16;key=struct.unpack_from('<Q',table,at)[0]
        if key in (0,cid):
            # Publish the aligned value before a new aligned identity. Native
            # readers see either the old entry or the complete new entry.
            struct.pack_into('<I',table,at+8,score)
            struct.pack_into('<Q',table,at,cid)
            return
        slot=(slot+1)&(PREVIEW_CAPACITY-1)
    raise ValueError('卡包预览总评缓存已满')


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def code_fingerprint(code):
    def value(v):
        if isinstance(v,types.CodeType):return signature(v)
        if isinstance(v,bytes):return {'bytes':v.hex()}
        if isinstance(v,(tuple,list)):return [value(x) for x in v]
        if isinstance(v,frozenset):return {'set':sorted(value(x) for x in v)}
        if v is None or type(v) in (str,int,float,bool):return v
        raise ValueError('原生安装器含未知代码常量')
    def signature(c):return {'code':c.co_code.hex(),'consts':value(c.co_consts),'names':c.co_names,'vars':c.co_varnames,'free':c.co_freevars,'cells':c.co_cellvars,'args':c.co_argcount,'kwonly':c.co_kwonlyargcount,'flags':c.co_flags}
    return hashlib.sha256(json.dumps(signature(code),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def reserve_asset_key(uid,occupied,registry):
    if uid in registry:
        value=registry[uid]
        if value in occupied:raise ValueError('个人美术资源编号与原库冲突')
        return str(value)
    start=8000000+int(hashlib.sha256(uid.encode()).hexdigest()[:12],16)%1000000
    value=start
    while value in occupied or value in registry.values():
        value=8000000+(value-8000000+1)%1000000
        if value==start:raise ValueError('个人美术资源编号空间已用完')
    registry[uid]=value
    return str(value)


def compose(payload,routes,profile,capacity=4194304):
    if not 0<=len(routes)<=10000:raise ValueError('个人美术绑定数量不能超过 10000')
    seen=set();rows=bytearray();stride=144 if profile.get('acquisition_hook') else (136 if profile.get('club_emblems') or profile.get('position_hook') else 128)
    external=bool(profile.get('external_routes'))
    def small(value):
        raw=value.encode('ascii')
        if not 0<len(raw)<=22:raise ValueError('个人美术名称超出原生短字符串范围')
        return bytes([len(raw)*2])+raw.ljust(23,b'\0')
    for route in sorted(routes,key=lambda r:r['cardId']):
        cid,donor=route['cardId'],route['suiteDonorId']
        if any(type(n) is not int or not 0<n<2**63 for n in (cid,donor)) or cid in seen:
            raise ValueError('个人美术绑定编号重复或无效')
        seen.add(cid)
        portrait,face=route['portraitKey'],route['modelFaceKey']
        if not (portrait.isascii() and portrait.isdigit() and len(portrait)==7 and face.isascii() and face.isdigit() and 1<=len(face)<=7):
            raise ValueError('个人美术绑定必须使用独立的七位资源编号')
        row=struct.pack('<QQ',cid,donor)+small(face)+small(portrait+'_')+small(portrait+'f')
        row+=(portrait+'_\0').encode('utf-16le')+(portrait+'f\0').encode('utf-16le')+bytes(4)
        if len(row)!=128:raise ValueError('个人美术绑定记录长度异常')
        if stride>=136:
            club=route.get('club_id',0)
            if type(club) is not int or not 0<=club<=65535:raise ValueError('个人俱乐部徽章编号无效')
            position=route.get('position',13)
            if type(position) is not int or not 0<=position<=13:raise ValueError('个人原生位置编号无效')
            # Native team getters return a packed value: the badge ID is
            # extracted with >> 14 by the contract card converter.
            row+=struct.pack('<II',club<<14,position)
        if stride==144:
            maximum=route.get('maximum_overall')
            if type(maximum) is not int or not 1<=maximum<=127:raise ValueError('抽卡最高总评分值无效')
            rarity=route.get('presentation_rarity',0)
            if type(rarity) is not int or rarity not in (0,10):raise ValueError('抽卡演出稀有度无效')
            row+=struct.pack('<II',maximum,rarity)
        rows.extend(row)
    rows.extend(bytes(stride))
    out=copy.deepcopy(payload);blob=bytearray.fromhex(out['blob_hex']);prefix=bytes(blob);pending=[];delegates=[];back_refs=[]
    def word(at):return struct.unpack_from('<I',blob,at)[0]
    for name,address in profile['sites'].items():
        matches=[h for h in out['hooks'] if h['address']==address]
        if len(matches)!=1:raise ValueError('原生美术接口版本不匹配：'+name)
        hook=matches[0];old=hook['offset'];blob.extend(bytes(-len(blob)%8));base=len(blob)
        template=profile['templates'][name];body=bytearray.fromhex(template['hex'])
        if stride!=128:
            count=0
            for at in range(0,len(body)-3,4):
                value=struct.unpack_from('<I',body,at)[0]
                if value==0x91020108:
                    struct.pack_into('<I',body,at,0x91000108|(stride<<10));count+=1
            if count!=1:raise ValueError('个人美术绑定表步长接口改变')
        at=template['delegate'];delta=old-(base+at)
        if delta%4 or not -(1<<27)<=delta<(1<<27):raise ValueError('原生美术回退分支越界')
        struct.pack_into('<I',body,at,0x14000000|((delta//4)&0x3ffffff))
        delegates.append((base+at,old))
        for at in template['backRefs']:
            back_refs.append(base+at)
            delta=out['back_fixup']-(base+at)
            if delta%4 or not -(1<<20)<=delta<(1<<20):raise ValueError('原生美术常量引用越界')
            value=struct.unpack_from('<I',body,at)[0]
            struct.pack_into('<I',body,at,(value&0xff00001f)|(((delta//4)&0x7ffff)<<5))
        pending.extend(base+at for at in template['tableRefs']);blob.extend(body);hook['offset']=base
    blob.extend(bytes(-len(blob)%8));table=len(blob)
    for at in pending:
        delta=table-at
        if not -(1<<20)<=delta<(1<<20):raise ValueError('原生美术表引用越界')
        if external:
            struct.pack_into('<I',blob,at,0x58000000|(word(at)&31)|(((delta//4)&0x7ffff)<<5))
        else:struct.pack_into('<I',blob,at,(word(at)&0x9f00001f)|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5))
    if external:
        out['route_table_hex']=rows.hex();out['route_pointer_fixup']=table;out['route_header_bytes']=144 if profile.get('overall_hook') else (96 if profile.get('rarity_hook') else 64);blob.extend(bytes(8))
    else:blob.extend(rows)
    if profile.get('boosters'):
        _booster_hooks(out,blob,profile['boosters'],profile['text_hooks'])
    if profile.get('club_emblems'):_emblem_hooks(out,blob,table,stride,external,delegates)
    if profile.get('position_hook'):_position_hook(out,blob,table,stride,profile['position_hook'],external)
    if profile.get('acquisition_hook'):_acquisition_hook(out,blob,table,stride,profile['acquisition_hook'],external)
    if profile.get('rarity_hook'):_rarity_hook(out,blob,table,stride,profile['rarity_hook'])
    if profile.get('overall_hook'):_overall_hook(out,blob,table,stride,profile['overall_hook'])
    if profile.get('thumbnail_hook'):_thumbnail_hook(out,blob,routes,profile['thumbnail_hook'])
    for hook in profile.get('native_hooks',[]):
        if any(h['address']==hook['address'] for h in out['hooks']):raise ValueError('原生扩展接口重复')
        blob.extend(bytes(-len(blob)%8));at=len(blob);body=bytes.fromhex(hook['body_hex'])
        out['hooks'].append({'name':hook['name'],'address':hook['address'],'offset':at,'expected_hex':hook['expected_hex']})
        out.setdefault('absolute_fixups',[]).extend([[at+offset,target] for offset,target in hook['absolute_fixups']])
        blob.extend(body)
    if len(blob)>capacity:raise ValueError('个人美术绑定超出已分配容量')
    if bytes(blob[:len(prefix)])!=prefix:raise ValueError('原版传奇美术绑定被改变')
    out['blob_hex']=blob.hex()
    if external and len(blob)>4096:
        split_prefix=profile.get('root_prefix_bytes',len(prefix))
        if type(split_prefix) is not int or not 1024<=split_prefix<=len(prefix) or split_prefix%8:
            raise ValueError('原生入口前缀范围无效')
        _split_code(out,split_prefix,delegates,back_refs,payload)
    return out


def _native_references(payload):
    """Follow original A64 control flow; literal pools are never instructions."""
    raw=bytes.fromhex(payload['blob_hex']);pending=[h['offset'] for h in payload['hooks']]+list(payload['offsets'].values());seen=set();refs=[]
    def signed(value,bits):return value-(1<<bits) if value&(1<<(bits-1)) else value
    while pending:
        pc=pending.pop()
        if pc in seen:continue
        if pc%4 or not 0<=pc<=len(raw)-4:raise ValueError('原版美术代码分支超出有效范围')
        seen.add(pc);word=struct.unpack_from('<I',raw,pc)[0];target=None;kind=None;bits=None;fall=True
        if word&0x7c000000==0x14000000:
            target=pc+signed(word&0x3ffffff,26)*4;kind='branch';bits=26;fall=bool(word&0x80000000)
        elif word&0xff000010==0x54000000 or word&0x7e000000==0x34000000:
            target=pc+signed((word>>5)&0x7ffff,19)*4;kind='branch';bits=19
        elif word&0x7e000000==0x36000000:
            target=pc+signed((word>>5)&0x3fff,14)*4;kind='branch';bits=14
        elif word&0x9f000000==0x10000000:
            target=pc+signed(((word>>5)&0x7ffff)*4+((word>>29)&3),21);kind='address'
        elif word&0x9f000000==0x90000000:
            raise ValueError('原版美术代码出现未支持的跨页地址指令')
        elif word&0x3b000000==0x18000000:
            target=pc+signed((word>>5)&0x7ffff,19)*4;kind='literal'
            opc=word>>30;bits=(4,8,16)[opc] if word&(1<<26) and opc<3 else (8 if opc==1 else 4)
        elif word&0xfffffc1f in (0xd61f0000,0xd65f0000):fall=False
        if target is not None:
            if not 0<=target<len(raw):raise ValueError('原版美术代码的相对引用超出范围')
            refs.append((pc,target,kind,bits))
            if kind=='branch':pending.append(target)
        if fall:pending.append(pc+4)
    return refs


def _move_native_appendix(source,cut,extension,payload):
    """Relocate V15's added native cases while retaining its original fallback."""
    size=len(bytes.fromhex(source['blob_hex']))
    payload['extension_root_copy_fixups']=[];payload['native_appendix_relocations']=[];jumps={}
    for pc,target,kind,bits in _native_references(source):
        if pc<cut:
            if target>=cut:raise ValueError('原版入口前缀不独立，未移动代码')
            continue
        if target>=cut:continue
        at=pc-cut;word=struct.unpack_from('<I',extension,at)[0]
        if kind=='branch':
            if target not in jumps:
                extension.extend(bytes(-len(extension)%8));slot=len(extension);jumps[target]=slot
                extension.extend(struct.pack('<IIQ',0x58000050,0xd61f0200,0));payload['extension_prefix_fixups'].append([slot+8,target])
            delta=(jumps[target]-at)//4
            if not -(1<<(bits-1))<=delta<(1<<(bits-1)):raise ValueError('原版扩展分支重定位越界')
            mask=0x3ffffff if bits==26 else ((1<<bits)-1)<<5
            value=(delta&((1<<bits)-1))<<(0 if bits==26 else 5);word=(word&~mask)|value
        elif kind=='address':
            extension.extend(bytes(-len(extension)%8));slot=len(extension);extension.extend(bytes(8));payload['extension_prefix_fixups'].append([slot,target])
            word=0x58000000|(word&31)|((((slot-at)//4)&0x7ffff)<<5)
        else:
            if target+bits>cut:raise ValueError('原版常量跨越入口边界')
            extension.extend(bytes(-len(extension)%8));slot=len(extension);extension.extend(bytes(bits));payload['extension_root_copy_fixups'].append([slot,target,bits])
            word=(word&0xff00001f)|((((slot-at)//4)&0x7ffff)<<5)
        struct.pack_into('<I',extension,at,word);payload['native_appendix_relocations'].append({'offset':pc,'target':target,'kind':kind})
    payload['original_appendix_bytes']=size-cut


def _split_code(payload,prefix_bytes,delegates,back_refs,source=None):
    """Keep the verified native page; reach a separate code page absolutely.

    V14's original legend code nearly fills its 4 KiB loader gap. A larger
    nearby mmap is not available on some native-bridge emulators. Only the
    branch entry stubs must be nearby; extension code can reside anywhere.
    """
    original=bytes.fromhex(payload['blob_hex']);root=bytearray(original[:prefix_bytes]);extension=bytearray(original[prefix_bytes:])
    payload['extension_native_fixups']=[];root_fixups=[]
    for at,value in payload.get('absolute_fixups',[]):
        if at<prefix_bytes:root_fixups.append([at,value])
        else:payload['extension_native_fixups'].append([at-prefix_bytes,value])
    payload['absolute_fixups']=root_fixups
    legacy={};payload['extension_prefix_fixups']=[]
    if source and prefix_bytes<len(bytes.fromhex(source['blob_hex'])):
        _move_native_appendix(source,prefix_bytes,extension,payload)
    for at,target in delegates:
        if target>=prefix_bytes:
            struct.pack_into('<I',extension,at-prefix_bytes,0x14000000|(((target-at)//4)&0x3ffffff));continue
        if target not in legacy:
            extension.extend(bytes(-len(extension)%8));stub=len(extension);legacy[target]=stub
            extension.extend(struct.pack('<IIQ',0x58000050,0xd61f0200,0))
            payload['extension_prefix_fixups'].append([stub+8,target])
        at-=prefix_bytes;delta=legacy[target]-at
        struct.pack_into('<I',extension,at,0x14000000|((delta//4)&0x3ffffff))
    if back_refs:
        extension.extend(bytes(-len(extension)%8));copy_at=len(extension);extension.extend(bytes(8))
        payload['extension_back_copy_fixups']=[copy_at]
        for at in back_refs:
            at-=prefix_bytes;value=struct.unpack_from('<I',extension,at)[0]
            struct.pack_into('<I',extension,at,(value&0xff00001f)|((((copy_at-at)//4)&0x7ffff)<<5))
    payload['extension_route_pointer_fixup']=payload.pop('route_pointer_fixup')-prefix_bytes
    payload['extension_entry_fixups']=[]
    for hook in payload['hooks']:
        if hook['offset']<prefix_bytes:continue
        root.extend(bytes(-len(root)%8));stub=len(root);target=hook['offset']-prefix_bytes
        root.extend(struct.pack('<IIQ',0x58000050,0xd61f0200,0))
        payload['extension_entry_fixups'].append([stub+8,target]);hook['offset']=stub
    if len(root)>4096:raise ValueError('原生绑定入口超出可用的 4 KiB 页面')
    payload['root_prefix_bytes']=prefix_bytes
    payload['blob_hex']=root.hex();payload['extension_blob_hex']=extension.hex()


def relocate_code(payload,source,prefix_address,extension_address,route_address):
    """Pure relocation, also used by the native-memory regression checks."""
    root=bytearray(source);base=struct.unpack_from('<Q',root,payload['back_fixup'])[0]-payload['hooks'][0]['address']-4
    for at,relative in payload.get('absolute_fixups',[]):struct.pack_into('<Q',root,at,base+relative)
    extension=bytearray.fromhex(payload.get('extension_blob_hex',''))
    if extension:
        for at,relative in payload['extension_entry_fixups']:struct.pack_into('<Q',root,at,extension_address+relative)
        for at,relative in payload['extension_native_fixups']:struct.pack_into('<Q',extension,at,base+relative)
        for at,relative in payload['extension_prefix_fixups']:struct.pack_into('<Q',extension,at,prefix_address+relative)
        for at,relative,size in payload.get('extension_root_copy_fixups',[]):extension[at:at+size]=root[relative:relative+size]
        for at in payload.get('extension_back_copy_fixups',[]):struct.pack_into('<Q',extension,at,struct.unpack_from('<Q',root,payload['back_fixup'])[0])
        struct.pack_into('<Q',extension,payload['extension_route_pointer_fixup'],route_address)
    elif route_address:struct.pack_into('<Q',root,payload['route_pointer_fixup'],route_address)
    return bytes(root),bytes(extension)


def _thumbnail_hook(payload,blob,routes,profile):
    """Replace only registered cards' six mini names before native alias lookup.

    The stock C++ string assigner releases any previous heap storage. All
    arguments, SIMD values and flags survive our calls; the displaced native
    call runs with its original arguments and exact return address.
    """
    rows=bytearray()
    for route in sorted(routes,key=lambda r:r['cardId']):
        values=route.get('thumbnail_names')
        if values is None:continue
        if not isinstance(values,list) or len(values)!=6:raise ValueError('小头像原生图层数量无效')
        rows.extend(struct.pack('<Q',route['cardId']))
        for value in values:
            if not isinstance(value,str) or len(value)>22 or any(c not in '0123456789abcdefghijklmnopqrstuvwxyz_' for c in value):
                raise ValueError('小头像原生图层名称无效')
            raw=value.encode('ascii');rows.extend(bytes([len(raw)*2])+raw.ljust(23,b'\0'))
    stock=bytearray()
    for route in sorted(profile.get('stock_routes',[]),key=lambda r:r['key']):
        if type(route['key']) is not int or not 0<=route['key']<2**35 or len(route['names'])!=2:raise ValueError('原版小卡动画索引无效')
        stock.extend(struct.pack('<Q',route['key']+1))
        for value in route['names']:
            if not isinstance(value,str) or len(value)>22 or any(c not in '0123456789abcdefghijklmnopqrstuvwxyz_' for c in value):raise ValueError('原版小卡动画名称无效')
            raw=value.encode('ascii');stock.extend(bytes([len(raw)*2])+raw.ljust(23,b'\0'))
    if not rows and not stock:return
    stock.extend(bytes(56))
    rows.extend(bytes(152));blob.extend(bytes(-len(blob)%8));start=len(blob);words=[];labels={};branches=[];calls=[]
    def emit(w):words.append(w)
    def pair(op,a,b,off,scale):return op|((off//scale)<<15)|(b<<10)|(31<<5)|a
    def branch(kind,label,reg=0):branches.append((len(words),kind,label,reg));emit(0)
    emit(0xd10703ff) # sub sp, sp, #448
    for reg in range(0,18,2):emit(pair(0xa9000000,reg,reg+1,reg*8,8))
    emit(pair(0xa9000000,18,30,144,8));emit(0xd53b4208);emit(0xf90053e8)
    for reg in range(0,8,2):emit(pair(0xad000000,reg,reg+1,176+reg*16,16))
    table_ref=len(words);emit(0)
    labels['loop']=len(words);emit(0xf9400128);branch('cbz','stock',8)
    emit(0xeb0802ff);branch('eq','match');emit(0x91026129);branch('b','loop') # cmp x23,x8; add x9,x9,#152
    labels['match']=len(words);emit(0xf900a3e9) # resident source record at sp+320
    for slot in range(6):
        offset=8+slot*24
        emit(0xf940a3e1);emit(0x39400022|(offset<<10));emit(0x53017c42) # ldrb w2,[x1,#offset]; lsr w2,w2,#1
        emit(0x91000021|((offset+1)<<10));emit(0x91000260|((profile['mini_offset']+slot*24)<<10))
        calls.append(len(words));emit(0);emit(0xd63f0200)
    branch('b','done')
    labels['stock']=len(words);stock_ref=len(words);emit(0);emit(0xd35cfeea);emit(0x9100054a)
    labels['stock_loop']=len(words);emit(0xf9400128);branch('cbz','done',8)
    emit(0xeb08015f);branch('eq','stock_match');emit(0x9100e129);branch('b','stock_loop')
    labels['stock_match']=len(words);emit(0xf900a3e9)
    for entry,slot in enumerate((1,5)):
        offset=8+entry*24
        emit(0xf940a3e1);emit(0x39400022|(offset<<10));emit(0x53017c42)
        # An empty stock entry leaves the game's original layer intact.
        branch('cbz','stock_next_'+str(entry),2)
        emit(0x91000021|((offset+1)<<10));emit(0x91000260|((profile['mini_offset']+slot*24)<<10))
        calls.append(len(words));emit(0);emit(0xd63f0200)
        labels['stock_next_'+str(entry)]=len(words)
    labels['done']=len(words)
    for reg in range(0,8,2):emit(pair(0xad400000,reg,reg+1,176+reg*16,16))
    emit(0xf94053e8);emit(0xd51b4208)
    for reg in range(0,18,2):emit(pair(0xa9400000,reg,reg+1,reg*8,8))
    emit(pair(0xa9400000,18,30,144,8));emit(0x910703ff)
    resume=len(words);emit(0);original_call=len(words);emit(0);emit(0xd61f0200)
    if len(words)%2:emit(0xd503201f)
    literals={}
    for name,value in [('assign',profile['assign']),('resume',profile['address']+4),('call',profile['original_call'])]:
        literals[name]=len(words);payload.setdefault('absolute_fixups',[]).append([start+len(words)*4,value]);words.extend([0,0])
    stock_at=start+len(words)*4;row_at=stock_at+len(stock);delta=row_at-(start+table_ref*4)
    if not -(1<<20)<=delta<(1<<20):raise ValueError('小卡动画索引超出代码引用范围')
    words[table_ref]=0x10000009|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5)
    delta=stock_at-(start+stock_ref*4)
    if not -(1<<20)<=delta<(1<<20):raise ValueError('原版小卡动画索引超出代码引用范围')
    words[stock_ref]=0x10000009|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5)
    for at,target,reg in [(at,literals['assign'],16) for at in calls]+[(resume,literals['resume'],30),(original_call,literals['call'],16)]:
        words[at]=0x58000000|(((target-at)&0x7ffff)<<5)|reg
    for at,kind,label,reg in branches:
        delta=labels[label]-at;words[at]=(0x14000000|(delta&0x3ffffff) if kind=='b' else
            (0xb4000000|reg if kind=='cbz' else 0x54000000)|((delta&0x7ffff)<<5))
    blob.extend(struct.pack('<'+'I'*len(words),*words));blob.extend(stock);blob.extend(rows)
    payload['hooks'].append({'name':'personal_mobile_icon_layers','address':profile['address'],'offset':start,'expected_hex':profile['expected_hex']})


def _acquisition_hook(payload,blob,table,stride,profile,external):
    """Override the draw scene's private card copy, never the owned object."""
    blob.extend(bytes(-len(blob)%8));start=len(blob)
    delta=table-start
    words=[0x58000009|(((delta//4)&0x7ffff)<<5) if external else
           0x10000009|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5),0xf9400428]
    labels={};branches=[]
    def branch(kind,label):branches.append((len(words),kind,label));words.append(0)
    labels['loop']=len(words);words.append(0xf9400130);branch('cbz','delegate')
    words.append(0xeb10011f);branch('eq','match');words.append(0x91000129|(stride<<10));branch('b','loop')
    labels['match']=len(words);words.append(0xb9408928)
    # The stack-local acquisition object has its display rating at +0xcc.
    # The earned level, parameters and SQLite owned rows are untouched.
    words.append(0xb900cc28)
    labels['delegate']=len(words);return_at=len(words);words.extend([0,0,0])
    literal=start+len(words)*4
    words[return_at]=0x5800001e|(((literal-(start+return_at*4))//4)<<5)
    words[return_at+1]=0x58000010|(((literal+8-(start+(return_at+1)*4))//4)<<5)
    words[return_at+2]=0xd61f0200
    for at,kind,label in branches:
        delta=labels[label]-at
        words[at]=(0x14000000|(delta&0x3ffffff) if kind=='b' else
                   (0xb4000010 if kind=='cbz' else 0x54000000)|((delta&0x7ffff)<<5))
    blob.extend(struct.pack('<'+'I'*len(words),*words));blob.extend(bytes(16))
    payload.setdefault('absolute_fixups',[]).extend([[literal,profile['address']+4],[literal+8,profile['converter']]])
    payload['hooks'].append({'name':'personal_draw_maximum_rating','address':profile['address'],
                            'offset':start,'expected_hex':profile['expected_hex']})


def _position_hook(payload,blob,table,stride,profile,external=False):
    blob.extend(bytes(-len(blob)%8));start=len(blob)
    # x0 is the game's player-card object. Its stable card ID is at +8.
    # Return the native 0..12 position enum for registered personal cards.
    delta=table-(start+16)
    adr=0x10000009|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5)
    if external:adr=0x58000009|(((delta//4)&0x7ffff)<<5)
    words=[0xa9be27e8,0xf9000bea,0xd53b420a,0xf9400408,adr]
    if external:_call_diagnostic(words,-64,212)
    loop=len(words)
    words.extend([0xf9400130,0,0xeb10011f,0x54000060,0x91000129|(stride<<10),0x17fffffb,0xb9408520,
                  0xd51b420a,0xf9400bea,0xa8c227e8,0xd65f03c0,
                  0xd51b420a,0xf9400bea,0xa8c227e8,0xb940d400,0xd65f03c0])
    words[loop+1]=0xb4000000|((11-1)<<5)|16
    blob.extend(struct.pack('<'+'I'*len(words),*words))
    payload['hooks'].append({'name':'personal_walkout_position','address':profile['address'],
                            'offset':start,'expected_hex':profile['expected_hex']})


def _rarity_hook(payload,blob,table,stride,profile):
    """V14 restored the native rarity getter; keep legacy personal walkouts.

    Common player identity is read through the original encrypted-ID getter.
    Foreign players and personal nonspecial cards keep the original byte.
    """
    blob.extend(bytes(-len(blob)%8));start=len(blob);words=[];labels={};branches=[]
    def emit(x):words.append(x)
    def branch(kind,label,reg=0):branches.append((len(words),kind,label,reg));emit(0)
    def pair(op,a,b,off,scale):return op|((off//scale)<<15)|(b<<10)|(31<<5)|a
    emit(0xd106c3ff) # sub sp, sp, #432
    for reg in range(0,18,2):emit(pair(0xa9000000,reg,reg+1,reg*8,8))
    emit(pair(0xa9000000,18,30,144,8));emit(0xd53b4208);emit(0xf90053e8)
    for reg in range(0,8,2):emit(pair(0xad000000,reg,reg+1,176+reg*16,16))
    call_at=len(words);emit(0);emit(0xd63f0200);emit(0x2a0003e8)
    table_at=start+len(words)*4;emit(0x58000009|((((table-table_at)//4)&0x7ffff)<<5))
    _call_diagnostic(words,-96)
    emit(0xf94003e0);emit(0x39453810);emit(0xf8000000|((-80&511)<<12)|(9<<5)|16)
    labels['loop']=len(words);emit(0xb940012a);branch('cbz','foreign',10)
    emit(0x6b0a011f);branch('eq','match');emit(0x91000129|(stride<<10));branch('b','loop')
    labels['match']=len(words);emit(0xb9408d20);branch('cbz','foreign',0);branch('b','done')
    labels['foreign']=len(words);emit(0xf94003e0);emit(0x39453800)
    labels['done']=len(words);emit(0xb900abe0)
    for reg in range(0,8,2):emit(pair(0xad400000,reg,reg+1,176+reg*16,16))
    emit(0xf94053e8);emit(0xd51b4208)
    for reg in range(0,18,2):emit(pair(0xa9400000,reg,reg+1,reg*8,8))
    emit(pair(0xa9400000,18,30,144,8));emit(0xb940abe0);emit(0x9106c3ff);emit(0xd65f03c0)
    for at,kind,label,reg in branches:
        delta=labels[label]-at
        words[at]=(0x14000000|(delta&0x3ffffff) if kind=='b' else
                   (0x34000000|reg if kind=='cbz' else 0x54000000)|((delta&0x7ffff)<<5))
    literal=start+len(words)*4
    words[call_at]=0x58000010|((((literal-start-call_at*4)//4)&0x7ffff)<<5)
    blob.extend(struct.pack('<'+'I'*len(words),*words));blob.extend(bytes(8))
    payload.setdefault('absolute_fixups',[]).append([literal,profile['identity_getter']])
    payload['hooks'].append({'name':'personal_v14_walkout_rarity','address':profile['address'],
                            'offset':start,'expected_hex':profile['expected_hex']})


def _overall_hook(payload,blob,table,stride,profile):
    """Keep earned-card ratings; override only verified preview callers."""
    if profile.get('global_preview'):
        _global_overall_hook(payload,blob,table,profile);return
    blob.extend(bytes(-len(blob)%8));start=len(blob)
    words=[0xa9bc27e8,0xa90143ea,0xa9024bf1,0xd53b420a,0xf9001bea,0xf9400408]
    labels={};branches=[];constants=[]
    def emit(x):words.append(x)
    def load_table():
        at=start+len(words)*4;emit(0x58000009|((((table-at)//4)&0x7ffff)<<5))
    def branch(kind,label):branches.append((len(words),kind,label));emit(0)
    def store(reg,offset):emit(0xf8000000|((offset&511)<<12)|(9<<5)|reg)
    load_table();labels['loop']=len(words);emit(0xf9400130);branch('cbz','foreign')
    emit(0xeb10011f);branch('eq','match');emit(0x91000129|(stride<<10));branch('b','loop')
    labels['match']=len(words);emit(0xaa0903f1);load_table()
    emit(0xf8400000|((-144&511)<<12)|(9<<5)|16);emit(0x91000610);store(16,-144);store(8,-136);store(30,-128)
    emit(0xf94007b0);store(16,-120);emit(0xb940cc12);store(18,-112)
    for caller in profile.get('callers',[]):
        constants.append((len(words),caller));emit(0);emit(0xeb12021f);branch('eq','override')
    branch('b','foreign');labels['override']=len(words);emit(0xb9408a20);branch('b','done')
    labels['foreign']=len(words);emit(0xb940cc00)
    labels['done']=len(words);emit(0xf9401bea);emit(0xd51b420a);emit(0xa9424bf1);emit(0xa94143ea);emit(0xa8c427e8);emit(0xd65f03c0)
    for at,kind,label in branches:
        delta=labels[label]-at
        words[at]=(0x14000000|(delta&0x3ffffff) if kind=='b' else
                   (0xb4000010 if kind=='cbz' else 0x54000000)|((delta&0x7ffff)<<5))
    if len(words)%2:emit(0xd503201f)
    for at,value in constants:
        literal=start+len(words)*4;words[at]=0x58000012|((((literal-start-at*4)//4)&0x7ffff)<<5)
        payload.setdefault('absolute_fixups',[]).append([literal,value]);words.extend([0,0])
    blob.extend(struct.pack('<'+'I'*len(words),*words))
    payload['hooks'].append({'name':'personal_preview_overall','address':profile['address'],'offset':start,'expected_hex':profile['expected_hex']})


def _global_overall_hook(payload,blob,table,profile):
    """Use dynamically registered scores only in the pack-banner converter."""
    blob.extend(bytes(-len(blob)%8));start=len(blob)
    words=[0xa9bc27e8,0xa90143ea,0xa9024bf1,0xd53b420a,0xf9001bea,0xf9400408]
    labels={};branches=[];constants=[]
    def emit(value):words.append(value)
    def branch(kind,label,reg=0):branches.append((len(words),kind,label,reg));emit(0)
    def store(reg,offset):emit(0xf8000000|((offset&511)<<12)|(9<<5)|reg)
    value_offset=profile.get('value_offset',0xcc)
    if value_offset not in (0xcc,0xd0):raise ValueError('卡包总评字段偏移无效')
    if not profile.get('converter_returns') or (not profile.get('direct_only') and not profile.get('callers')):
        raise ValueError('原版卡包预览缺少已核对的调用范围')
    for caller in profile['converter_returns']:
        constants.append((len(words),caller));emit(0);emit(0xeb1203df);branch('eq','converter')
    branch('b','foreign');labels['converter']=len(words)
    at=start+len(words)*4;emit(0x58000009|((((table-at)//4)&0x7ffff)<<5))
    emit(0xf8400000|((-144&511)<<12)|(9<<5)|16);emit(0x91000610)
    store(16,-144);store(8,-136);store(30,-128)
    emit(0xf94007b0);store(16,-120);emit(0xb9400000|((value_offset//4)<<10)|18);store(18,-112)
    if profile.get('direct_only'):branch('b','preview')
    for caller in (() if profile.get('direct_only') else profile['callers']):
        constants.append((len(words),caller));emit(0);emit(0xeb12021f);branch('eq','preview')
    branch('b','foreign');labels['preview']=len(words)
    emit(0xf8400000|((-104&511)<<12)|(9<<5)|9) # Header holds resident hash table pointer.
    emit(0xd360fd10);emit(0xca080210);emit(0x92403e10);emit(0xd37cee10)
    emit(0x52a0002a) # Bound probes even if the hash table is full.
    labels['loop']=len(words);emit(0x8b100131);emit(0xf9400232);branch('cbz','foreign',18)
    emit(0xeb12011f);branch('eq','match');emit(0x7100054a);branch('eq','foreign')
    emit(0x91004210);emit(0x92404e10);branch('b','loop')
    labels['match']=len(words);emit(0xb9400a20);branch('b','done')
    labels['foreign']=len(words);emit(0xb9400000|((value_offset//4)<<10))
    labels['done']=len(words)
    for value in (0xf9401bea,0xd51b420a,0xa9424bf1,0xa94143ea,0xa8c427e8,0xd65f03c0):emit(value)
    for at,kind,label,reg in branches:
        delta=labels[label]-at
        words[at]=(0x14000000|(delta&0x3ffffff) if kind=='b' else
                   (0xb4000000|reg if kind=='cbz' else 0x54000000)|((delta&0x7ffff)<<5))
    if len(words)%2:emit(0xd503201f)
    for at,value in constants:
        literal=start+len(words)*4;words[at]=0x58000012|((((literal-start-at*4)//4)&0x7ffff)<<5)
        payload.setdefault('absolute_fixups',[]).append([literal,value]);words.extend([0,0])
    blob.extend(struct.pack('<'+'I'*len(words),*words));payload['global_preview']=True
    payload['hooks'].append({'name':'pack_preview_overall','address':profile['address'],'offset':start,'expected_hex':profile['expected_hex']})


def _call_diagnostic(words,offset,member=None):
    def unscaled(op,at,reg):return op|((at&511)<<12)|(9<<5)|reg
    words.extend([unscaled(0xf8400000,offset,16),0x91000610,
                  unscaled(0xf8000000,offset,16),unscaled(0xf8000000,offset+8,8)])
    if member is not None:
        words.extend([0xb9400010|((member//4)<<10),unscaled(0xf8000000,offset+16,16)])


def _emblem_hooks(payload,blob,table,stride,external=False,delegates=None):
    for name in ('henry_arsenal_card_emblem','henry_arsenal_squad_emblem'):
        hook=next(h for h in payload['hooks'] if h['name']==name);old=hook['offset']
        blob.extend(bytes(-len(blob)%8));start=len(blob);words=[];labels={};branches=[]
        def emit(value):words.append(value)
        def branch(kind,label,reg=0):branches.append((len(words),kind,label,reg));emit(0)
        card=name.endswith('card_emblem')
        for value in ((0xa9be27e8,0xf9000bea,0xd53b420a,0xf9400408) if card else (0xa9bf2be9,0xd53b420a,0xf9401268)):emit(value)
        # The existing entry point also serves national-team badges. Its
        # original discriminator must remain intact for those calls.
        at=start+len(words)*4;delta=table-at
        emit(0x58000009|(((delta//4)&0x7ffff)<<5) if external else 0x10000009|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5))
        if external:_call_diagnostic(words,-40 if card else -16,0 if card else None)
        if card:emit(0xb9400010);branch('cbnz','fallback',16)
        labels['loop']=len(words);emit(0xf9400130);branch('cbz','fallback',16);emit(0xeb10011f);branch('eq','match')
        emit(0x91000129|(stride<<10));branch('b','loop');labels['match']=len(words)
        if card:
            emit(0xb9408120)
            for value in (0xd51b420a,0xf9400bea,0xa8c227e8,0xd65f03c0):emit(value)
        else:emit(0x91020137)
        labels['fallback']=len(words)
        for value in ((0xd51b420a,0xf9400bea,0xa8c227e8) if card else (0xd51b420a,0xa8c12be9)):emit(value)
        at=start+len(words)*4;emit(0x14000000|(((old-at)//4)&0x3ffffff))
        if delegates is not None:delegates.append((at,old))
        for at,kind,label,reg in branches:
            delta=labels[label]-at
            if kind=='b':words[at]=0x14000000|(delta&0x3ffffff)
            elif kind=='cbz':words[at]=0xb4000000|((delta&0x7ffff)<<5)|reg
            elif kind=='cbnz':words[at]=0x35000000|((delta&0x7ffff)<<5)|reg
            else:words[at]=0x54000000|((delta&0x7ffff)<<5)
        blob.extend(struct.pack('<'+'I'*len(words),*words));hook['offset']=start


def _booster_hooks(payload,blob,routes,profile):
    pending=[]
    def adr(reg,delta):return 0x10000000|reg|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5)
    for kind in ('name','description'):
        h=profile[kind];blob.extend(bytes(-len(blob)%8));start=len(blob)
        # x9 points to {booster ID, name StringID, description StringID}.
        words=[0x10000009,0xb940012a,0x3400016a,0x6b14015f,0x54000060,
               0x91003129,0x17fffffb,0xb9400521 if kind=='name' else 0xb9400921,
               0xaa1303e0,0x580000f0,0xd63f0200,0x58000130,0xd61f0200,
               int(h['original_word'],16),0x58000130,0xd61f0200,
               0xd503201f,0xd503201f]
        # 72-byte code, followed by three relocated absolute pointers.
        # LDR positions: 36 -> 72, 44 -> 80, 56 -> 88.
        words[9]=0x58000010|(((72-36)//4)<<5)
        words[11]=0x58000010|(((80-44)//4)<<5)
        words[14]=0x58000010|(((88-56)//4)<<5)
        for value in words:blob.extend(struct.pack('<I',value))
        for at,value in ((72,profile['translate']),(80,h['return']),(88,h['address']+4)):
            blob.extend(bytes(8));payload.setdefault('absolute_fixups',[]).append([start+at,value])
        payload['hooks'].append({'name':'personal_booster_'+kind,'address':h['address'],'offset':start,'expected_hex':h['expected_hex']})
        pending.append(start)
    blob.extend(bytes(-len(blob)%8));table=len(blob)
    for start in pending:struct.pack_into('<I',blob,start,adr(9,table-start))
    for row in routes:blob.extend(struct.pack('<III',row['id'],row['name'],row['description']))
    blob.extend(bytes(12))


def capture(function):
    """Read the literal payload, aborting before allocation or thread startup."""
    class Captured(BaseException):pass
    result={}
    def trace(frame,event,arg):
        if frame.f_code is function.__code__ and 'PAYLOAD' in frame.f_locals:
            result.update(copy.deepcopy(frame.f_locals['PAYLOAD']));raise Captured()
        return trace
    previous=sys.gettrace()
    try:
        sys.settrace(trace)
        try:function(None)
        except Captured:pass
    finally:sys.settrace(previous)
    if not result:raise ValueError('未能识别原生美术安装器')
    return result


class _PageOS:
    def __init__(self,original,unit):self.original=original;self.unit=unit
    def __getattr__(self,name):return getattr(self.original,name)
    def sysconf(self,name):
        actual=self.original.sysconf(name)
        if name=='SC_PAGE_SIZE':
            if actual!=4096:raise ValueError('尚未验证此设备的原生页大小')
            return self.unit
        return actual


class _BindingCtypes:
    def __init__(self,original,payload):
        self.original=original;self.payload=payload;self.table=None
        if payload.get('route_table_hex'):
            self.table=original.create_string_buffer(bytes(payload.get('route_header_bytes',0))+bytes.fromhex(payload['route_table_hex']))
            _RESIDENT_TABLES.append(self.table)
        if payload.get('global_preview'):
            preview=original.create_string_buffer(PREVIEW_CAPACITY*16)
            for cid,score in _PREVIEW_SCORES.items():_write_preview(preview,cid,score)
            _PREVIEW_TABLES.append(preview)
            struct.pack_into('<Q',self.table,40,original.addressof(preview))
    def __getattr__(self,name):return getattr(self.original,name)
    def memmove(self,dest,source,size):
        if isinstance(source,bytes) and size==len(bytes.fromhex(self.payload['blob_hex'])):
            extension_address=0;libc=None;length=0
            if self.payload.get('extension_blob_hex'):
                libc=self.original.CDLL('libc.so',use_errno=True)
                libc.mmap.restype=self.original.c_void_p
                libc.mmap.argtypes=(self.original.c_void_p,self.original.c_size_t,self.original.c_int,self.original.c_int,self.original.c_int,self.original.c_long)
                libc.mprotect.restype=self.original.c_int
                libc.mprotect.argtypes=(self.original.c_void_p,self.original.c_size_t,self.original.c_int)
                length=(len(bytes.fromhex(self.payload['extension_blob_hex']))+4095)//4096*4096
                extension_address=libc.mmap(None,length,3,0x22,-1,0)
                if extension_address in (None,self.original.c_void_p(-1).value):
                    raise OSError(self.original.get_errno(),'personal code page allocation failed')
            route=0 if self.table is None else self.original.addressof(self.table)+self.payload.get('route_header_bytes',0)
            address=dest if isinstance(dest,int) else dest.value
            source,extension=relocate_code(self.payload,source,address,extension_address,route)
            if extension:self.original.memmove(extension_address,extension,len(extension))
            result=self.original.memmove(dest,source,size)
            if extension:
                if libc.mprotect(extension_address,length,5):raise OSError(self.original.get_errno(),'personal code page protection failed')
                # The original installer protects the root after memmove returns.
                # Its cache routine must already be executable before this call.
                root_size=(len(bytes.fromhex(self.payload['blob_hex']))+4095)//4096*4096
                if libc.mprotect(address,root_size,5):raise OSError(self.original.get_errno(),'personal entry page protection failed')
                clear=self.original.CFUNCTYPE(None,self.original.c_void_p,self.original.c_void_p)(address+self.payload['offsets']['clear_cache'])
                clear(extension_address,extension_address+len(extension))
                _EXTENSION_PAGES.append((libc,extension_address,length))
            return result
        return self.original.memmove(dest,source,size)


def _outer(root):
    # These placeholders describe the closure only. Every one is replaced with
    # the supplied game's original code after its layout is checked.
    import ctypes,json,os,struct,threading,time
    from pathlib import Path
    os=_PageOS(os,__PERSONAL_PAGE_SIZE__)
    PAYLOAD=__PERSONAL_PAYLOAD__
    ctypes=_BindingCtypes(ctypes,PAYLOAD)
    def parse_maps(source):raise RuntimeError('Original installer required')
    def library_base(rows):raise RuntimeError('Original installer required')
    class ProcessMemory:
        def read(self,address,size):
            ctypes
            raise RuntimeError('Original installer required')
    def branch_word(source,target):raise RuntimeError('Original installer required')
    def _api():
        ctypes
        raise RuntimeError('Original installer required')
    def _allocate_near(libc,rows,base,size):
        PAYLOAD,branch_word,ctypes
        raise RuntimeError('Original installer required')
    _resident=[]
    def report(value):
        Path,json,root
        raise RuntimeError('Original installer required')
    def worker():
        PAYLOAD,Path,ProcessMemory,_allocate_near,_api,_resident,branch_word,ctypes,library_base,os,parse_maps,report,struct,time
        raise RuntimeError('Original installer required')
    threading.Thread(target=worker,daemon=True).start()


def prepare(function,binding):
    original=capture(function)
    if fingerprint(original)!=binding['original_fingerprint']:raise ValueError('原生美术接口指纹改变，未写入运行时')
    payload=compose(original,binding['routes'],binding['profile'])
    old=function.__code__;replacement=_outer.__code__
    if (old.co_cellvars,old.co_freevars)!=(replacement.co_cellvars,replacement.co_freevars):
        raise ValueError('原生美术安装器闭包版本改变')
    nested={v.co_name:v for v in old.co_consts if isinstance(v,types.CodeType)}
    allocate=function.__globals__.get('allocate_portrait_pages')
    proof=binding.get('source') or {}
    if proof.get('kind')=='v16-prepared':
        # The game's loader has already enlarged three worker spans for its
        # own inline code. Our split code keeps a 4-KiB entry page, so recover
        # the verified original worker before applying our page-size adapter.
        worker=nested.get('worker');raw=function.__globals__.get('_start_legend_portrait_binding')
        if worker is None or code_fingerprint(worker)!=proof.get('prepared_worker_fingerprint'):raise ValueError('V16 美术安装器页大小协议改变')
        if not isinstance(raw,types.FunctionType) or fingerprint(capture(raw))!=proof.get('raw_fingerprint'):raise ValueError('V16 原版美术回退入口不一致')
        raw_worker=next((c for c in raw.__code__.co_consts if isinstance(c,types.CodeType) and c.co_name=='worker'),None)
        if raw_worker is None or code_fingerprint(raw_worker)!=proof.get('raw_worker_fingerprint'):raise ValueError('V16 原版美术工作器不一致')
        nested['worker']=raw_worker
        # V16 also replaces the allocator with a closure requiring its 8-KiB
        # block. Restore the allocator from the verified original installer
        # together with its worker; our split layout uses a 4-KiB entry page.
        allocate=raw.__globals__.get('allocate_portrait_pages')
    if not callable(allocate):raise ValueError('原版美术页分配器缺失')
    expected={v.co_name:v for v in replacement.co_consts if isinstance(v,types.CodeType)}
    if nested.keys()!=expected.keys() or any(nested[k].co_freevars!=expected[k].co_freevars for k in nested):
        raise ValueError('原生美术安装器结构改变')
    replacement=replacement.replace(co_consts=tuple(nested[v.co_name] if isinstance(v,types.CodeType) else v for v in replacement.co_consts))
    unit=(len(bytes.fromhex(payload['blob_hex']))+4095)//4096*4096
    namespace=dict(function.__globals__,__PERSONAL_PAYLOAD__=payload,__PERSONAL_PAGE_SIZE__=unit,_PageOS=_PageOS,_BindingCtypes=_BindingCtypes)
    def pages(libc,rows,base,ps,near,read,branch,hooks):
        if ps==4096:return allocate(libc,rows,base,ps,near,read,branch,hooks)
        # Larger batches need a real private allocation. Never write beyond the
        # original verified loader gap if no sufficiently large page is free.
        return near(libc,rows,base,ps*2),'personal_private_mmap'
    namespace['allocate_portrait_pages']=pages
    modified=types.FunctionType(replacement,namespace,function.__name__,function.__defaults__,function.__closure__)
    if capture(modified)!=payload:raise ValueError('个人美术绑定自检失败')
    return modified,{'routes':len(binding['routes']),'code_bytes':len(bytes.fromhex(payload['blob_hex'])),'page_bytes':unit,
                     'extension_code_bytes':len(bytes.fromhex(payload.get('extension_blob_hex',''))),
                     'stock_routes_preserved':len(proof.get('stock_route_ids',[]))}


def install(module,binding,root):
    previous=module._start_legend_portrait_binding
    if getattr(previous,'_personal_binding',False):return
    function,report=prepare(previous,binding)
    def start(resource_root):return function(resource_root)
    start._personal_binding=True
    module._start_legend_portrait_binding=start
    if binding['profile'].get('overall_hook',{}).get('global_preview'):
        for route in binding['routes']:set_preview_score(route['cardId'],route['maximum_overall'])
    from pathlib import Path
    target=Path(root)/'outputs/efootball/personal-art-binding.json';target.parent.mkdir(parents=True,exist_ok=True)
    report.update(status='configured',player_ids=[r['cardId'] for r in binding['routes']])
    target.write_text(json.dumps(report),encoding='utf8')
    if binding['profile'].get('external_routes'):
        import threading,time
        def observe():
            destination=target.with_name('personal-native-calls.json')
            while True:
                if _RESIDENT_TABLES:
                    header=144 if binding['profile'].get('overall_hook') else (96 if binding['profile'].get('rarity_hook') else 64)
                    values=struct.unpack_from('<8Q',_RESIDENT_TABLES[-1].raw,header-64)
                    value={'position':dict(zip(('calls','card_id','original_enum'),values[:3])),
                           'card_club':dict(zip(('calls','card_id','flags'),values[3:6])),
                           'squad_club':dict(zip(('calls','card_id'),values[6:8]))}
                    if binding['profile'].get('rarity_hook'):value['rarity']=dict(zip(('calls','common_player_id','original_enum'),struct.unpack_from('<3Q',_RESIDENT_TABLES[-1].raw,header-96)))
                    if binding['profile'].get('overall_hook'):value['overall']=dict(zip(('calls','card_id','return','parent','original'),struct.unpack_from('<5Q',_RESIDENT_TABLES[-1].raw)))
                    if binding['profile'].get('overall_hook',{}).get('global_preview'):
                        value['preview_scores_registered']=len(_PREVIEW_SCORES)
                    destination.write_text(json.dumps(value),encoding='utf8')
                time.sleep(1)
        threading.Thread(target=observe,daemon=True).start()
