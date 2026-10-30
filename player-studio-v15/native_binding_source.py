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
        # Content packs contribute only declarative routes. Rebuild them with
        # the inspected V17 composer; never copy native code from the ZIP.
        import zipfile
        from content_delta import read_catalogue
        with zipfile.ZipFile(apk) as archive:extra=read_catalogue(archive).get('routes',[])
        from art_registry import prepare_registry
        effective,installer=prepare_registry(code,outer[0],payload,layers,extra,sites,templates,allocators[0])
        from native_diy_binding import code_fingerprint,V17_COMPOSE
        composer=next(c for c in reader('diy_routes').co_consts if isinstance(c,types.CodeType)and c.co_name=='compose')
        installer.proof['interface_family']='V17'if code_fingerprint(composer)==V17_COMPOSE else'V16'
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
        if code.proof.get('registry') and hasattr(code,'baseline_installer'):
            from art_registry import prepare_runtime
            from personal_binding import fingerprint
            binding.update(original_fingerprint=code.proof['raw_fingerprint'],prepared_fingerprint=fingerprint(code.payload))
            function=prepare_runtime(code.baseline_installer.function(allocation_stub),binding,code.allocator_code)
        else:function=code.function(allocation_stub)
    else:function=types.FunctionType(code,namespace)
    modified,report=prepare(function,binding)
    def forbidden(*args,**kwargs):raise RuntimeError('桌面预检禁止分配游戏内存')
    # Exercise the same allocation entry used by the worker. Capturing only
    # its payload missed V16's incompatible allocator-size closure.
    near_calls=[]
    def near(libc,rows,base,size):near_calls.append(size);return 0x100000
    result=modified.__globals__['allocate_portrait_pages'](None,[],0,report['page_bytes'],near,forbidden,forbidden,[])
    valid=(calls==[4096]and not near_calls and result==(0x100000,'preflight_no_native_memory'))if report['page_bytes']==4096 else(not calls and near_calls==[report['page_bytes']*2]and result==(0x100000,'personal_private_mmap'))
    if not valid:
        raise ValueError('原生美术分配器协议预检失败')
    return dict(report,allocator_contract_verified=True,shared_registry_pipeline=bool(getattr(code,'proof',{}).get('registry')))
