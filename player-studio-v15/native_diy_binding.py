"""Data-only reconstruction of the V16 loader's built-in art dispatch.

APK modules are inspected, never imported. This reproduces their verified
128-byte dispatch format before the personal extension is composed.
"""
import copy,dis,marshal,re,struct,types
from personal_binding import code_fingerprint

# Only the small data-composition protocol is pinned, not the engine or routes.
PROTOCOL={'diy_routes.compose': '23252b61d72435ac8f9740473e1b81c5f4fa7433b544c5815169aaad42528903', 'diy_runtime.prepare_binding': 'bc5e91d38fc77e96b6f647f339dfc2140c81be4b4ef13ea5165e64074db07710', 'diy_runtime.sized_worker': '02edadc079d56b95a5f8299df5748d9be2ebc0861540c41baea152be0e224dd2', 'diy_binding_outer._start_legend_portrait_binding': '7f453f5874e4289b6a4225d14360544225dfdcc5923cd15e24d499e1fb250a6d'}
V17_COMPOSE='13255b3dc09249b8cb23e01705b185436f1c2b257b42c8c9bd4ebf67efbf2b75'


def verify_protocol(reader):
    for module,name in (('diy_routes','compose'),('diy_runtime','prepare_binding'),('diy_runtime','sized_worker'),('diy_binding_outer','_start_legend_portrait_binding')):
        functions=[c for c in reader(module).co_consts if isinstance(c,types.CodeType) and c.co_name==name]
        allowed={PROTOCOL.get(module+'.'+name)}
        if module== 'diy_routes' and name=='compose':allowed.add(V17_COMPOSE)
        if len(functions)!=1 or code_fingerprint(functions[0]) not in allowed:raise ValueError('原版 DIY 美术准备协议改变：'+name)


def literal_routes(code):
    instructions=list(dis.get_instructions(code));starts=[n for n,i in enumerate(instructions) if i.opname=='LOAD_NAME' and i.argval=='_start_legend_portrait_binding']
    if len(starts)!=1:raise ValueError('V16 原版美术准备入口改变')
    stack=[]
    for at,i in enumerate(instructions[starts[0]+1:],starts[0]+1):
        if i.opname=='LOAD_CONST' and type(i.argval) in (str,int,tuple):stack.append(i.argval)
        elif i.opname=='BUILD_CONST_KEY_MAP':
            keys=stack.pop()
            if not isinstance(keys,tuple) or len(keys)!=i.arg or len(stack)<i.arg:raise ValueError('V16 原版绑定字段不完整')
            values=stack[-i.arg:];del stack[-i.arg:];stack.append(dict(zip(keys,values)))
        elif i.opname=='BUILD_LIST':
            if not 1<=i.arg<=1024 or len(stack)!=i.arg or not all(isinstance(r,dict) for r in stack):raise ValueError('V16 原版绑定列表无效')
            tail=instructions[at+1:]
            if len(tail)==6 and tail[-2].opname=='DELETE_NAME':
                aliases={b.argval for a,b in zip(instructions,instructions[1:]) if a.opname=='IMPORT_FROM' and a.argval=='prepare_binding' and b.opname=='STORE_NAME'}
                if tail[-2].argval not in aliases:raise ValueError('原版绑定准备删除了未知名称')
                tail=tail[:-2]+tail[-1:]
            if len(tail)!=5 or [x.opname for x in tail]!=['CALL','LOAD_CONST','BINARY_SUBSCR','STORE_NAME','RETURN_CONST'] or tail[0].arg!=2 or tail[1].argval!=0 or tail[3].argval!='_start_legend_portrait_binding' or tail[4].argval is not None:raise ValueError('V16 原版绑定准备调用改变')
            return stack
        else:raise ValueError('V16 原版绑定不再是可读取的常量列表')
    raise ValueError('V16 缺少原版美术绑定列表')


def route_layers(code):
    """Read nested marshal wrappers in their inner-to-outer execution order."""
    layers=[];count=0
    def visit(node):
        nonlocal count
        count+=1
        if count>4096:raise ValueError('原版美术包装层过多')
        children=[]
        for item in node.co_consts:
            if isinstance(item,bytes) and item and item[0] in (99,227):
                try:child=marshal.loads(item)
                except (ValueError,EOFError,TypeError):continue
                if isinstance(child,types.CodeType) and child.co_name=='<module>':children.append(child)
        for child in children:visit(child)
        if node.co_name=='<module>' and 'diy_runtime' in node.co_names:
            layers.append(literal_routes(node))
            if len(layers)>8:raise ValueError('原版美术分派层过多')
    visit(code)
    if not layers:raise ValueError('缺少原版美术分派层')
    ids=[r['cardId'] for layer in layers for r in layer]
    if len(set(ids))!=len(ids):raise ValueError('原版美术分派层存在重复球员')
    return layers


def compose(payload,routes,sites,templates,capacity=65536):
    if not 1<=len(routes)<=1024 or set(sites)!=set(templates) or len(sites)!=5:raise ValueError('V16 原版美术协议无效')
    rows=bytearray();seen=set();keys=set()
    def small(s):
        raw=s.encode('ascii')
        if not 0<len(raw)<=22:raise ValueError('V16 美术字符串越界')
        return bytes([len(raw)*2])+raw.ljust(23,b'\0')
    for r in sorted(routes,key=lambda r:r['cardId']):
        cid,donor,key,face=r['cardId'],r['suiteDonorId'],r['portraitKey'],r.get('modelFaceKey','1');native=r.get('modelNativeId')
        if any(type(v) is not int or not 0<v<2**63 for v in (cid,donor)) or native is not None and (type(native) is not int or not 0<native<2**63):raise ValueError('V16 原版绑定编号无效')
        if not isinstance(key,str) or not re.fullmatch('[0-9]{7}',key) or not isinstance(face,str) or not (re.fullmatch('[0-9]{1,7}',face) or native is not None and face=='') or cid in seen or key in keys:raise ValueError('V16 原版绑定编号重复')
        seen.add(cid);keys.add(key)
        slot=b'\xff'+bytes(7)+struct.pack('<Q',native)+bytes(8) if native is not None else small(face)
        row=struct.pack('<QQ',cid,donor)+slot+small(key+'_')+small(key+'f')+(key+'_\0').encode('utf-16le')+(key+'f\0').encode('utf-16le')+bytes(4)
        if len(row)!=128:raise ValueError('V16 原版绑定步长改变')
        rows.extend(row)
    rows.extend(bytes(128));out=copy.deepcopy(payload);blob=bytearray.fromhex(out['blob_hex']);prefix=bytes(blob);pending=[]
    for name,address in sites.items():
        hooks=[h for h in out['hooks'] if h['address']==address]
        if len(hooks)!=1:raise ValueError('V16 原版绑定入口不唯一：'+name)
        hook=hooks[0];old=hook['offset'];blob.extend(bytes(-len(blob)%8));base=len(blob);t=templates[name];body=bytearray.fromhex(t['hex']);delta=old-base-t['delegate']
        if delta%4 or not -(1<<27)<=delta<1<<27:raise ValueError('V16 绑定回退分支越界')
        struct.pack_into('<I',body,t['delegate'],0x14000000|((delta//4)&0x3ffffff))
        for at in t['backRefs']:
            delta=out['back_fixup']-base-at
            if delta%4 or not -(1<<20)<=delta<1<<20:raise ValueError('V16 绑定返回引用越界')
            word=struct.unpack_from('<I',body,at)[0];struct.pack_into('<I',body,at,(word&0xff00001f)|(((delta//4)&0x7ffff)<<5))
        pending.extend(base+at for at in t['tableRefs']);blob.extend(body);hook['offset']=base
    blob.extend(bytes(-len(blob)%8));table=len(blob)
    for at in pending:
        delta=table-at
        if not -(1<<20)<=delta<1<<20:raise ValueError('V16 绑定数据引用越界')
        word=struct.unpack_from('<I',blob,at)[0];struct.pack_into('<I',blob,at,(word&0x9f00001f)|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5))
    blob.extend(rows)
    if len(blob)>capacity or not blob.startswith(prefix):raise ValueError('V16 原版绑定容量或前缀改变')
    out['blob_hex']=blob.hex();return out


def sized_worker(code,size):
    """Reproduce only the three page-span substitutions of the V16 loader."""
    ops=list(dis.get_instructions(code));sites=[];uses=0
    for n,i in enumerate(ops):
        if i.opname=='LOAD_FAST' and i.argval=='ps':
            uses+=1
            if n and n+1<len(ops) and ((ops[n-1].opname=='LOAD_FAST' and ops[n-1].argval=='base' and ops[n+1].opname=='LOAD_DEREF' and ops[n+1].argval=='_allocate_near') or (ops[n-1].opname=='LOAD_FAST' and ops[n-1].argval=='page' and ((ops[n+1].opname=='BINARY_OP' and ops[n+1].argrepr=='+') or (ops[n+1].opname=='LOAD_CONST' and ops[n+1].argval==5)))):sites.append(i.offset)
    if len(sites)!=3 or uses!=10 or not 4096<size<=65536 or size%4096 or len(code.co_consts)>=256:raise ValueError('V16 原生页大小协议改变')
    raw=bytearray(code.co_code)
    for at in sites:
        if raw[at]!=dis.opmap['LOAD_FAST'] or at and raw[at-2]==dis.opmap['EXTENDED_ARG']:raise ValueError('V16 原生页编码改变')
        raw[at:at+2]=bytes((dis.opmap['LOAD_CONST'],len(code.co_consts)))
    return code.replace(co_code=bytes(raw),co_consts=code.co_consts+(size,))


class PreparedInstaller:
    def __init__(self,raw_code,outer,payload,raw_payload,routes,allocator_code):
        self.raw_code=raw_code;self.payload=payload;self.raw_payload=raw_payload;self.routes=routes
        nested={c.co_name:c for c in raw_code.co_consts if isinstance(c,types.CodeType)};raw_worker=nested['worker'];size=(len(bytes.fromhex(payload['blob_hex']))+4095)//4096*4096
        if size>4096:nested['worker']=sized_worker(raw_worker,size)
        if outer.co_cellvars!=raw_code.co_cellvars or outer.co_freevars!=raw_code.co_freevars or {c.co_name for c in outer.co_consts if isinstance(c,types.CodeType)}!=set(nested):raise ValueError('V16 原生安装器结构改变')
        self.code=outer.replace(co_consts=tuple(nested[v.co_name] if isinstance(v,types.CodeType) else v for v in outer.co_consts))
        from personal_binding import fingerprint
        self.proof={'kind':'v16-prepared','raw_fingerprint':fingerprint(raw_payload),'raw_worker_fingerprint':code_fingerprint(raw_worker),'prepared_worker_fingerprint':code_fingerprint(nested['worker']),'stock_route_ids':[r['cardId'] for r in routes]}
        self.allocator_code=allocator_code;self.size=size

    def function(self,allocate):
        raw=types.FunctionType(self.raw_code,{'allocate_portrait_pages':allocate})
        def require(ok,message):
            if not ok:raise ValueError(message)
        if self.allocator_code.co_freevars!=('size',):raise ValueError('V16 原生分配器闭包改变')
        # Reconstruct the real prepared allocator, too. No native call is
        # made: verification provides stubs for every memory operation.
        prepared=types.FunctionType(self.allocator_code,{'require':require,'os':types.SimpleNamespace(sysconf=lambda name:4096)},closure=(types.CellType(self.size),)) if self.size>4096 else allocate
        return types.FunctionType(self.code,{'__DIY_PAYLOAD__':self.payload,'allocate_portrait_pages':prepared,'_start_legend_portrait_binding':raw})
