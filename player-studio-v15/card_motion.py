"""Keep mini movie textures independent from full cards; retain stock widgets."""
import copy,hashlib,json,re,struct
from pathlib import Path
from studio_resources import bundled_resources
from native_iostore import package_names

ROOT=bundled_resources()

def _exports(raw):
    raw=bytes(raw);names=package_names(raw);h=struct.unpack_from('<16I',raw)
    exports=[]
    for at in range(h[11],h[12],72):
        offset,size=struct.unpack_from('<QQ',raw,at);name=names[struct.unpack_from('<I',raw,at+16)[0]&0x3fffffff]
        exports.append({'at':at,'offset':offset,'size':size,'name':name})
    heads=(h[13]-h[12])//8-len(exports)*2;position=h[13]+h[14]
    for at in range(h[12]+heads*8,h[13],8):
        index,kind=struct.unpack_from('<II',raw,at)
        if kind==1:exports[index]['actual']=position;position+=exports[index]['size']
    if position!=len(raw):raise ValueError('卡面蓝图导出范围不同，未修改动画')
    return exports


def restore_widget(raw,profile):
    """Remove only our exact old Tick extension and diagnostic stop bypass."""
    raw=bytes(raw);exports=_exports(raw)
    tick=next(x for x in exports if x['name']=='Tick');play=next(i+1 for i,x in enumerate(exports) if x['name']=='PlayManaVideo')
    start=tick['actual']+profile['script_header'];memory,size=struct.unpack_from('<II',raw,start);script=raw[start+8:start+8+size]
    call=b'\x46'+struct.pack('<i',play)+b'\x16'
    restored=False
    if memory==profile['memory_size']+10 and script==bytes.fromhex(profile['script_hex'])[:-3]+call+b'\x04\x0b\x53':
        out=bytearray(raw);at=start+8+size-3-len(call);del out[at:at+len(call)]
        struct.pack_into('<II',out,start,memory-10,size-len(call));struct.pack_into('<Q',out,tick['at']+8,tick['size']-len(call))
        for row in exports:
            if row['offset']>tick['offset']:struct.pack_into('<Q',out,row['at'],row['offset']-len(call))
        raw=bytes(out);restored=True
    elif memory!=profile['memory_size'] or script.hex()!=profile['script_hex']:
        raise ValueError('此版本的卡面 Tick 事件发生变化，未修改动画')
    stop_restored=False;stop_profile=profile.get('stock_stop')
    if stop_profile:
        row=next(x for x in _exports(raw) if x['name']=='StopManaVideo')
        body=raw[row['actual']:row['actual']+row['size']]
        entry=stop_profile['script_header']+8
        if body[entry:entry+5]==b'\x06'+struct.pack('<I',stop_profile['return_offset']):
            expected=bytearray(body);expected[entry]=0x4c
            if hashlib.sha256(expected).hexdigest()==stop_profile['export_sha256']:
                out=bytearray(raw);out[row['actual']+entry]=0x4c;raw=bytes(out);stop_restored=True
    return raw,{'original_tick_preserved':True,'legacy_tick_removed':restored,
                'diagnostic_stop_bypass_removed':stop_restored,'native_destruct_cleanup_preserved':True}

def packages(assets,resources=None):
    path=(Path(resources) if resources else ROOT)/'native-card-motion.json'
    data=json.loads(path.read_text(encoding='utf8'));result=[];reports=[]
    for row in data['widgets']:
        raw,meta=assets.get(row['path']);patched,report=restore_widget(raw,row)
        result.append((row['path'],patched,meta));reports.append({'path':row['path'],**report})
    return result,reports


class MiniTextures:
    """One private ManaTexture/YUV group per mini movie, reused within minis.

    UManaTexture keeps one component owner. Sharing a full card's texture
    lets either view detach the other's owner; sharing the movie file is safe.
    """
    BASE='/Game/Assets/ui/Data/Thumbnail/Player/'
    def __init__(self,assets,alias):
        self.assets=assets;self.alias=alias;self.art={};self.names={}

    def isolate(self,name):
        if not name:return ''
        if name in self.names:return self.names[name]
        if not isinstance(name,str) or not re.fullmatch('[0-9a-z_]{1,22}',name):raise ValueError('小头像原生动画名称无效')
        private=bool(re.fullmatch(r'smi_[0-9a-f]{12}',name))
        target=name if private else 'smi_'+hashlib.sha256(name.encode('ascii')).hexdigest()[:12]
        candidates=list(dict.fromkeys((name+'_v',self.alias(name+'_v'),self.alias(name)+'_v')))
        available=[]
        for folder in ('','Variation2022/'):
            for stem in candidates:
                path=self.BASE+folder+stem
                try:raw,meta=self.assets.get(path)
                except ValueError:continue
                if not {'ManaTexture','MovieSource'}<=set(package_names(raw)):raise ValueError('小头像动画不是原生视频纹理：'+name)
                available.append((folder,path,raw,meta));break
        if not available:raise ValueError('找不到小头像动画的原生视频纹理：'+name)
        from native_art import clone_group
        for folder in ('','Variation2022/'):
            _,old,raw,meta=next((r for r in available if r[0]==folder),available[0])
            path=self.BASE+folder+target+'_v'
            item=(path,raw,dict(meta)) if path==old else clone_group({old:(raw,meta)},{old:path})[0]
            if path in self.art and self.art[path]!=item:raise ValueError('小头像独立动画资源冲突：'+name)
            self.art[path]=item
        self.names[name]=target
        return target

    def values(self,values,slots):
        result=list(values)
        for slot in slots:result[slot]=self.isolate(result[slot])
        return result


def prepare(library,bindings,inherited_routes,records,enabled,resources=None):
    """Prepare new and inherited personal routes and optional stock minis."""
    assets=library.face_assets();art,reports=packages(assets,resources)
    bindings=copy.deepcopy(bindings);routes=copy.deepcopy(inherited_routes)
    stock=stock_routes(library,records) if enabled else []
    import contextlib
    with contextlib.closing(library.db()) as db:
        mini=MiniTextures(assets,lambda name:library._alias(db,name))
        for row in [*bindings,*routes]:
            values=row.get('thumbnail_names')
            if values is not None and not row.get('private_movie_textures'):
                if len(values)!=6:raise ValueError('小头像原生图层数量无效')
                row['thumbnail_names']=mini.values(values,(1,5))
        for row in stock:row['names']=mini.values(row['names'],(0,1))
    art.extend(mini.art.values())
    reports.append({'mini_video_textures_isolated':len(set(mini.names.values())),
                    'new_packages':len(mini.art),'original_movie_sources_preserved':True,
                    'forced_tick_playback':False,'native_widget_cleanup_preserved':True})
    return {'packages':art,'reports':reports,'bindings':bindings,'routes':routes,'stock_routes':stock}


def replacement_indices(container,art):
    """Update these exact compiled widget/mini packages on repeated exports."""
    result=set()
    for path,_,_ in art:
        name='../../../PesMobile/Content/'+path[6:]+'.uasset'
        if name in container.paths:result.add(container.paths[name])
    return result

def stock_routes(library,records):
    """Use stock mini movies, or the same series' F02 when none is supplied."""
    from pathlib import PurePosixPath
    import contextlib,re
    movies={PurePosixPath(p).stem for p in library.card_media['movies']};seen=set();result=[]
    with contextlib.closing(library.db()) as db:
        for cid in sorted(records):
            key=cid>>28
            if key in seen:continue
            seen.add(key);style=(cid>>40)&255;agent=(cid>>28)&4095;limited=bool(cid&(1<<48));style=f'{style>>4:02d}{style&15:02d}'
            def movie(slots):
                bases=[f'{style}_{agent}_{s}' for s in slots]+[f'{style}_{s}' for s in slots]
                candidates=([b+'_lim' for b in bases] if limited else [])+bases
                for stem in candidates:
                    for value in (stem+'_v',library._alias(db,stem+'_v'),library._alias(db,stem)+'_v'):
                        if value in movies:return value[:-2]
                return ''
            background=movie(['m02']) or movie(['f02']);effect=movie(['m06'])
            if background or effect:
                if any(len(v)>22 or v and not re.fullmatch('[0-9a-z_]+',v) for v in (background,effect)):raise ValueError('原版小卡动画名称超出接口范围')
                result.append({'key':key,'names':[background,effect]})
    return result
