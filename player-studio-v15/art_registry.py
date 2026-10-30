"""One declarative stock/content registry, shared by export and Android startup."""
import copy,json,types


def merged_routes(stock,content):
    result={}
    for route in [*stock,*content]:
        row=copy.deepcopy(route);key=int(row['cardId']);row['cardId']=key
        if key in result and result[key]!=row:raise ValueError('美术注册表同一球员存在冲突：'+str(key))
        result[key]=row
    return [result[k]for k in sorted(result)]


def prepare_registry(raw_code,outer,raw_payload,layers,content,sites,templates,allocator_code):
    from native_diy_binding import compose,PreparedInstaller
    from personal_binding import fingerprint,code_fingerprint
    stock=[r for layer in layers for r in layer]
    original=raw_payload
    for layer in layers:original=compose(original,layer,sites,templates)
    base=PreparedInstaller(raw_code,outer,original,raw_payload,stock,allocator_code)
    routes=merged_routes(stock,content)
    effective=compose(raw_payload,routes,sites,templates) if routes else raw_payload
    installer=PreparedInstaller(raw_code,outer,effective,raw_payload,routes,allocator_code)
    installer.baseline_installer=base
    installer.original_route_layers=copy.deepcopy(layers)
    installer.route_layers=[routes]
    installer.proof['registry']={'version':1,'stock_routes':stock,'content_routes':content,'sites':sites,'templates':templates,
        'base_prepared_fingerprint':fingerprint(original),'base_prepared_code_fingerprint':code_fingerprint(base.code),
        'raw_code_fingerprint':code_fingerprint(raw_code),'allocator_code_fingerprint':code_fingerprint(allocator_code)}
    return effective,installer


def prepare_runtime(previous,binding,allocator_code=None):
    """Recover the actual original worker; never wrap an already prepared worker."""
    from native_diy_binding import PreparedInstaller,compose
    from personal_binding import capture,fingerprint,code_fingerprint
    proof=binding.get('source',{});registry=proof.get('registry')
    if not registry:return previous
    if registry.get('version')!=1:raise ValueError('不支持的美术注册表准备协议')
    if not isinstance(previous,types.FunctionType) or code_fingerprint(previous.__code__)!=registry['base_prepared_code_fingerprint']:
        raise ValueError('原生美术准备入口与导出核对结果不同')
    if fingerprint(capture(previous))!=registry['base_prepared_fingerprint']:raise ValueError('原生分派表在启动前已改变')
    raw=previous.__globals__.get('_start_legend_portrait_binding')
    if not isinstance(raw,types.FunctionType) or code_fingerprint(raw.__code__)!=registry['raw_code_fingerprint']:
        raise ValueError('原生美术原始回退入口不同')
    raw_payload=capture(raw)
    if fingerprint(raw_payload)!=proof['raw_fingerprint'] or fingerprint(raw_payload)!=binding['original_fingerprint']:
        raise ValueError('原生美术原始安装器指纹不同')
    if allocator_code is None:
        import diy_runtime
        candidates=[c for c in diy_runtime.prepare_binding.__code__.co_consts if isinstance(c,types.CodeType)and c.co_name=='allocate_pages']
    else:candidates=[allocator_code]
    if len(candidates)!=1 or code_fingerprint(candidates[0])!=registry['allocator_code_fingerprint']:
        raise ValueError('原生美术分配器与已核对协议不同')
    routes=merged_routes(registry['stock_routes'],registry['content_routes'])
    payload=compose(raw_payload,routes,registry['sites'],registry['templates']) if routes else raw_payload
    if fingerprint(payload)!=binding['prepared_fingerprint']:raise ValueError('美术注册表生成结果与导出不同')
    allocator=raw.__globals__.get('allocate_portrait_pages')
    if not callable(allocator):raise ValueError('原生美术原始分配器缺失')
    installer=PreparedInstaller(raw.__code__,previous.__code__,payload,raw_payload,routes,candidates[0])
    if installer.proof['prepared_worker_fingerprint']!=proof['prepared_worker_fingerprint']:raise ValueError('美术工作器准备结果与导出不同')
    return installer.function(allocator,raw.__globals__)
