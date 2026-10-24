"""Inspect the APK's literal native installer without executing APK modules."""
import marshal,types
from apk_literals import module_reader,literal_assignments

def read_installer(apk):
    reader=module_reader(apk);root=reader('legends_v10');pending=[root];found=[];count=0
    while pending:
        code=pending.pop();count+=1
        if count>4096:raise ValueError('原生美术安装器包装层过多')
        if code.co_name=='_start_legend_portrait_binding':found.append(code)
        for value in code.co_consts:
            if isinstance(value,types.CodeType):pending.append(value)
            elif isinstance(value,bytes) and value and value[0] in (99,227):
                try:child=marshal.loads(value)
                except (ValueError,EOFError,TypeError):continue
                if isinstance(child,types.CodeType):pending.append(child)
    if len(found)!=1:raise ValueError('原版 APK 的美术安装器不唯一或已改变')
    code=found[0];payload=literal_assignments(code,{'PAYLOAD'})['PAYLOAD']
    if not isinstance(payload,dict) or not {'blob_hex','hooks','offsets','back_fixup'}<=payload.keys():
        raise ValueError('原版 APK 的美术接口资料不完整')
    if 'prepare_binding' in root.co_names and 'diy_runtime' in root.co_names:
        from native_diy_binding import route_layers,compose,PreparedInstaller,verify_protocol
        verify_protocol(reader)
        layers=route_layers(root);routes=[r for layer in layers for r in layer]
        sites=literal_assignments(reader('diy_routes'),{'SITES'})['SITES']
        templates=literal_assignments(reader('diy_route_templates'),{'TEMPLATES'})['TEMPLATES']
        outer=[c for c in reader('diy_binding_outer').co_consts if isinstance(c,types.CodeType) and c.co_name=='_start_legend_portrait_binding']
        if len(outer)!=1:raise ValueError('V16 原生安装器外层不唯一')
        preparer=next(c for c in reader('diy_runtime').co_consts if isinstance(c,types.CodeType) and c.co_name=='prepare_binding')
        allocators=[c for c in preparer.co_consts if isinstance(c,types.CodeType) and c.co_name=='allocate_pages']
        if len(allocators)!=1:raise ValueError('V16 原生分配器准备入口改变')
        effective=payload
        for layer in layers:effective=compose(effective,layer,sites,templates)
        installer=PreparedInstaller(code,outer[0],effective,payload,routes,allocators[0]);installer.route_layers=layers
        return effective,installer
    return payload,code

def installer_metadata(installer):return getattr(installer,'proof',None)

def verify_installer(code,binding):
    from personal_binding import prepare
    calls=[]
    def allocation_stub(libc,rows,base,size,*args):
        calls.append(size);return 0x100000,'preflight_no_native_memory'
    namespace={'__name__':'studio_binding_preflight','allocate_portrait_pages':allocation_stub}
    if hasattr(code,'function'):
        binding=dict(binding,source=code.proof)
        function=code.function(allocation_stub)
    else:function=types.FunctionType(code,namespace)
    modified,report=prepare(function,binding)
    def forbidden(*args,**kwargs):raise RuntimeError('桌面预检禁止分配游戏内存')
    # Exercise the same allocation entry used by the worker. Capturing only
    # its payload missed V16's incompatible allocator-size closure.
    result=modified.__globals__['allocate_portrait_pages'](None,[],0,report['page_bytes'],forbidden,forbidden,forbidden,[])
    if calls!=[report['page_bytes']] or result!=(0x100000,'preflight_no_native_memory'):
        raise ValueError('原生美术分配器协议预检失败')
    return dict(report,allocator_contract_verified=True)
