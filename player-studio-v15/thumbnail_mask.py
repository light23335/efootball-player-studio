"""Private MobileIcon material selected by an exact personal texture marker.

The original shared mask/material stay untouched. A transparent F03 marker is
compared by UObject identity, never by a stock-card range or a broad wildcard.
"""
from pathlib import Path
import base64,hashlib,json,struct,zlib
from PIL import Image,ImageChops,ImageOps
from studio_resources import bundled_resources

REVISION='personal-mini-left-mask-v5-private-portrait-uv'
MARKER='sm_personal_mask_flag'
BASE='/Game/Assets/effect/PlayerCard/'
MATERIAL=BASE+'Materials/M_UI_MobileIconFront'
INSTANCE=BASE+'Materials/MI_UI_MobileIconFront'
MASK=BASE+'Textures/T_MobileIconPlayerImageMask'
PRIVATE=BASE+'Studio/'
RENAMES={MATERIAL:PRIVATE+'M_StudioMobileIconFront',INSTANCE:PRIVATE+'MI_StudioMobileIconFront',MASK:PRIVATE+'T_StudioMobileIconPlayerMask'}
MARKER_PATH='/Game/Assets/ui/Data/Thumbnail/Player/'+MARKER
MARKER_VARIATION='/Game/Assets/ui/Data/Thumbnail/Player/Variation2022/'+MARKER
WIDGET='/Game/Assets/ui/Data/Widget/Parts/Components/Placeholders/UiPlayerCard/MobileIcon'


def personal_alpha(image):
    alpha=image.convert('RGBA').getchannel('A')
    # Mirror the native right inner edge onto the formerly hidden left side.
    # Keep its exact inset/antialiasing and rounded corners, not a white square.
    return ImageChops.lighter(alpha,ImageOps.mirror(alpha))


def preview_masks(resources=None):
    profile=json.loads(((Path(resources)if resources else bundled_resources())/'native-thumbnail-mask.json').read_text('utf8'))
    def decode(key):
        data=zlib.decompress(base64.b64decode(profile[key]));size=tuple(profile['alpha_size'])
        if size!=(128,128) or len(data)!=16384:raise ValueError('小头像轮廓数据无效')
        return Image.frombytes('L',size,data)
    return decode('personal_alpha_zlib_base64'),decode('outer_alpha_zlib_base64')


def isolate_shader_map(raw,profile):
    """Give the cloned cooked material its own uniform-expression cache key.

    Keep the compiled shader bytecode/resource hashes intact. Only the cooked
    material map identity changes: V17 otherwise reuses the original loaded
    FMaterialShaderMap, including its original default texture resolution.
    """
    old=bytes.fromhex(profile['cooked_shader_map_id_hash'])
    if len(old)!=20 or raw.count(old)!=1:raise ValueError('小头像已编译材质标识不同，未修改原版资源')
    new=hashlib.sha1(b'PlayerStudio/private-mini-mask/v4\0'+old).digest()
    return raw.replace(old,new),{'original_shader_map':old.hex(),'private_shader_map':new.hex(),
                                 'compiled_shader_code_unchanged':True}


def _append_imports(raw,meta,objects,dependencies):
    """Extend only the inspected v2 import map and dependency graph."""
    raw=bytes(raw);h=list(struct.unpack_from('<16I',raw));imports=list(struct.unpack_from('<'+'Q'*((h[11]-h[10])//8),raw,h[10]))
    missing=[v for v in objects if v not in imports]
    dependencies=[v for v in dependencies if v not in meta.get('imports',[])]
    refs=[-(imports.index(v)+1)if v in imports else -(len(imports)+missing.index(v)+1)for v in objects]
    if not missing and not dependencies:return raw,meta,refs
    delta=8*len(missing)
    out=bytearray(raw[:h[11]]+(struct.pack('<'+'Q'*len(missing),*missing)if missing else b'')+raw[h[11]:])
    h[5]+=delta
    for index in (11,12,13):h[index]+=delta
    for at in range(h[11],h[12],72):struct.pack_into('<Q',out,at,struct.unpack_from('<Q',out,at)[0]+delta)
    graph=bytes(out[h[13]:h[13]+h[14]]);count=struct.unpack_from('<I',graph)[0]
    graph=struct.pack('<I',count+len(dependencies))+graph[4:]+b''.join(struct.pack('<QIII',p,1,0,0)for p in dependencies)
    added=len(graph)-h[14];out[h[13]:h[13]+h[14]]=graph;h[14]=len(graph);h[5]+=added
    for at in range(h[11],h[12],72):struct.pack_into('<Q',out,at,struct.unpack_from('<Q',out,at)[0]+added)
    struct.pack_into('<16I',out,0,*h)
    meta=dict(meta);meta['imports']=list(dict.fromkeys([*meta.get('imports',[]),*dependencies]))
    return bytes(out),meta,refs


def _switch_script(script,profile,refs):
    old=bytes.fromhex(profile['front_object_hex'])
    if script.count(old)!=1:raise ValueError('小头像正面材质入口不同')
    marker,variation,material=refs
    start=profile['front_object_memory_offset'];length=109
    # execSwitchValue evaluates IndexTerm with RESULT_PARAM == nullptr and
    # obtains its type/address from MostRecentProperty. A pure CallMath there
    # writes its bool return through nullptr. Use the actual F03 ObjectProperty
    # as the index; native FObjectProperty comparison handles both marker cases.
    selector=bytes.fromhex(profile['f03_expression_hex'])
    switch=b'\x69'+struct.pack('<HI',3,start+length)+selector
    for reference,next_offset in ((marker,start+47),(variation,start+69)):
        switch+=b'\x20'+struct.pack('<i',reference)+struct.pack('<I',next_offset)+b'\x20'+struct.pack('<i',material)
    # V17 reports SwitchValueOutOfBounds when no case matches. A final read
    # of the same immutable property is a typed catch-all (including nullptr),
    # so stock cards do not enter the engine's unmatched-case exception path.
    switch+=selector+struct.pack('<I',start+100)+old
    switch+=old
    if len(switch)!=117:raise ValueError('小头像材质属性选择表达式布局不同')
    delta=length-9
    for prefix,value in ((b'\x69\x02\x00',145),(b'\x28',122),(b'\x27',136)):
        needle=prefix+struct.pack('<I',value)
        if script.count(needle)!=1:raise ValueError('小头像材质分支边界不同')
        script=script.replace(needle,prefix+struct.pack('<I',value+delta))
    return script.replace(old,switch),delta


def _restore_unsafe_script(script,profile):
    """Undo only the exact released v1 selector before applying the safe one."""
    if hashlib.sha256(script).hexdigest()!=profile.get('unsafe_v1_script_sha256'):
        raise ValueError('此游戏的小头像旧材质补丁无法安全识别')
    start=profile['front_object_memory_offset']
    prefix=b'\x69'+struct.pack('<HI',1,start+125)
    # Both nested v1 switches share the same end offset.
    if script.count(prefix)!=2:raise ValueError('旧小头像选择入口不同')
    at=script.index(prefix)
    script=script[:at]+bytes.fromhex(profile['front_object_hex'])+script[at+129:]
    for prefix,value in ((b'\x69\x02\x00',145),(b'\x28',122),(b'\x27',136)):
        old=prefix+struct.pack('<I',value+116)
        if script.count(old)!=1:raise ValueError('旧小头像选择分支边界不同')
        script=script.replace(old,prefix+struct.pack('<I',value))
    return script


def _soft_switch_script(script,profile,load_ref):
    """Resolve new objects by path, independent of a stock package-store entry.

    V17 can use the original MobileIcon package's import dependency list while
    reading the patched export chunk. New hard object constants then become
    nullptr, even though the new packages are present. Native script imports
    have no such package dependency. LoadAsset_Blocking resolves the soft path
    (and normally returns the already cached object).
    """
    old=bytes.fromhex(profile['front_object_hex']);start=profile['front_object_memory_offset']
    if script.count(old)!=1:raise ValueError('小头像正面材质入口不同')
    def load(path):
        object_path=path+'.'+path.rsplit('/',1)[-1]
        value=b'\x68'+struct.pack('<i',load_ref)+b'\x67\x1f'+object_path.encode('ascii')+b'\0\x16'
        return value,len(value)+4 # UFunction package index expands from 4 to 8.
    selector=bytes.fromhex(profile['f03_expression_hex']);parts=[];memory=start+7+18
    for marker in (MARKER_PATH,MARKER_VARIATION):
        case,case_size=load(marker);material,material_size=load(RENAMES[INSTANCE])
        memory+=case_size+4+material_size
        parts.append(case+struct.pack('<I',memory)+material)
    # Typed catch-all: no unmatched SwitchValue exception for stock/null F03.
    memory+=18+4+9;parts.append(selector+struct.pack('<I',memory)+old)
    memory+=9
    switch=b'\x69'+struct.pack('<HI',3,memory)+selector+b''.join(parts)+old
    delta=memory-start-9
    for prefix,value in ((b'\x69\x02\x00',145),(b'\x28',122),(b'\x27',136)):
        needle=prefix+struct.pack('<I',value)
        if script.count(needle)!=1:raise ValueError('小头像材质分支边界不同')
        script=script.replace(needle,prefix+struct.pack('<I',value+delta))
    return script.replace(old,switch),delta


def _restore_v2_script(script,profile):
    start=profile['front_object_memory_offset']
    prefix=b'\x69'+struct.pack('<HI',3,start+109)
    if script.count(prefix)!=1:raise ValueError('旧小头像材质选择入口不同')
    at=script.index(prefix)
    script=script[:at]+bytes.fromhex(profile['front_object_hex'])+script[at+117:]
    for prefix,value in ((b'\x69\x02\x00',145),(b'\x28',122),(b'\x27',136)):
        needle=prefix+struct.pack('<I',value+100)
        if script.count(needle)!=1:raise ValueError('旧小头像材质边界不同')
        script=script.replace(needle,prefix+struct.pack('<I',value))
    return script


def _replace_script(raw,row,header,memory,script):
    from card_motion import _exports
    at=row['actual']+header;old_size=struct.unpack_from('<I',raw,at+4)[0]
    out=bytearray(raw);out[at:at+8+old_size]=struct.pack('<II',memory,len(script))+script
    growth=len(script)-old_size
    for e in _exports(raw):
        if e['name']=='SetMaterialInstance':struct.pack_into('<Q',out,e['at']+8,e['size']+growth)
        elif e['offset']>row['offset']:struct.pack_into('<Q',out,e['at'],e['offset']+growth)
    return bytes(out)


def patch_widget(raw,meta,profile,marker_hash,variation_hash,material_hash,dependencies):
    from card_motion import _exports
    row=next(e for e in _exports(raw)if e['name']=='SetMaterialInstance')
    body=raw[row['actual']:row['actual']+row['size']];header=profile['script_header']
    memory,size=struct.unpack_from('<II',body,header);script=body[header+8:header+8+size]
    # Re-exporting the exact same patch is idempotent; no extra import rows.
    if hashlib.sha256(script).hexdigest() in profile.get('soft_script_sha256',[]):
        return raw,meta,{'private_material_selector':True,'already_patched':True,'soft_material_lookup':True}
    repaired_v1=False
    repaired_v2=False
    if hashlib.sha256(script).hexdigest() in (profile.get('patched_script_sha256'),profile.get('migrated_v1_script_sha256')):
        restored=_restore_v2_script(script,profile)
        restored_body=body[:header]+struct.pack('<II',memory-100,len(restored))+restored+body[header+8+size:]
        if hashlib.sha256(restored_body).hexdigest()!=profile['export_sha256']:raise ValueError('旧小头像材质回退校验失败')
        raw=_replace_script(raw,row,header,memory-100,restored)
        row=next(e for e in _exports(raw)if e['name']=='SetMaterialInstance')
        body=restored_body;script=restored;memory-=100;size=len(restored);repaired_v2=True
    if hashlib.sha256(script).hexdigest()==profile.get('unsafe_v1_script_sha256'):
        restored=_restore_unsafe_script(script,profile)
        restored_body=body[:header]+struct.pack('<II',memory-116,len(restored))+restored+body[header+8+size:]
        if hashlib.sha256(restored_body).hexdigest()!=profile['export_sha256']:
            raise ValueError('旧小头像补丁回退校验失败')
        raw=_replace_script(raw,row,header,memory-116,restored)
        row=next(e for e in _exports(raw)if e['name']=='SetMaterialInstance')
        body=restored_body;script=restored;memory-=116;size=len(restored);repaired_v1=True
    if hashlib.sha256(body).hexdigest()!=profile['export_sha256']:
        raise ValueError('此游戏的小头像材质布局不同，未修改原版遮罩')
    raw,meta,refs=_append_imports(raw,meta,[int(profile['load_asset_script_index'],16)],[])
    row=next(e for e in _exports(raw)if e['name']=='SetMaterialInstance')
    new,delta=_soft_switch_script(script,profile,refs[0])
    out=_replace_script(raw,row,header,memory+delta,new)
    return out,meta,{'private_material_selector':True,'original_back_material_preserved':True,
                    'comparison':'native F03 ObjectProperty switch with soft asset cases','repaired_unsafe_v1':repaired_v1,
                    'repaired_unresolved_hard_imports':repaired_v2,'soft_material_lookup':True,
                    'script_sha256':hashlib.sha256(new).hexdigest()}


def prepare(library,art,bindings,routes,resources=None):
    from native_art import clone_group,texture
    from native_iostore import package_id,export_rebindings
    selected=[r for r in [*bindings,*routes]if r.get('thumbnail_names') is not None]
    if not selected:return art,[]
    assets=library.face_assets();raws={p:assets.get(p)for p in RENAMES}
    profile=json.loads(((Path(resources)if resources else bundled_resources())/'native-thumbnail-mask.json').read_text('utf8'))
    for path,(raw,_) in raws.items():
        if hashlib.sha256(raw).hexdigest()!=profile['assets_sha256'][path]:
            raise ValueError('此游戏的小头像人物材质不同，未修改原版遮罩')
    alpha,_=preview_masks(resources);image=Image.merge('RGBA',(alpha,alpha,alpha,alpha))
    # The stock shader ALSO offsets the portrait UV by 29/128. Opening the
    # alpha alone repeats its clamped left edge. Correct only the private
    # shader's portrait UV, keeping all other layers and clipping intact.
    mask_raw,_=texture(raws[MASK][0],MASK,image)
    from thumbnail_shader import patch_private_shader
    material_raw,shader_report=patch_private_shader(raws[MATERIAL][0],profile)
    packages=clone_group(raws,RENAMES,{MASK:mask_raw,MATERIAL:material_raw})
    marker_raw,marker_meta=texture(raws[MASK][0],MARKER_PATH,Image.new('RGBA',(4,4)))
    packages.append((MARKER_PATH,marker_raw,marker_meta))
    variation=clone_group({MARKER_PATH:(marker_raw,marker_meta)},{MARKER_PATH:MARKER_VARIATION})[0]
    packages.append(variation)
    marker_hash=next(iter(export_rebindings(marker_raw,MARKER_PATH)))
    variation_hash=next(iter(export_rebindings(variation[1],variation[0])))
    instance=next(p for p in packages if p[0]==RENAMES[INSTANCE])
    material_hash=next(iter(export_rebindings(instance[1],instance[0])))
    at=next(i for i,p in enumerate(art)if p[0]==WIDGET)
    path,raw,meta=art[at]
    raw,meta,report=patch_widget(raw,meta,profile,marker_hash,variation_hash,material_hash,
                               [package_id(MARKER_PATH),package_id(MARKER_VARIATION),package_id(RENAMES[INSTANCE])])
    art[at]=(path,raw,meta);art.extend(packages)
    for route in selected:
        values=list(route['thumbnail_names']);values[2]=MARKER;route['thumbnail_names']=values
    return art,[{'revision':REVISION,'personal_routes':len(selected),'stock_routes_unchanged':True,
                 'shared_mask_unchanged':True,'native_inner_edge_and_corners_preserved':True,**shader_report,**report}]
