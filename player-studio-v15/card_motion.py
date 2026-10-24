"""Keep visible card widgets playing; native destruction still releases movies."""
import copy,json,struct
from pathlib import Path
from native_iostore import package_names

ROOT=Path(__file__).parent/'resources'

def patch_tick(raw,profile):
    """Append PlayManaVideo to the existing Tick event's straight-line script.

    The stock Play function checks IsPlaying before calling Play, so this
    resumes a paused visible widget without restarting an active movie.
    Destruct, StopManaVideo and the actor's unused-component cleanup survive.
    """
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
    tick=next(x for x in exports if x['name']=='Tick');play=next(i+1 for i,x in enumerate(exports) if x['name']=='PlayManaVideo')
    start=tick['actual']+profile['script_header'];memory,size=struct.unpack_from('<II',raw,start);script=raw[start+8:start+8+size]
    call=b'\x46'+struct.pack('<i',play)+b'\x16'
    if memory==profile['memory_size']+10 and script==bytes.fromhex(profile['script_hex'])[:-3]+call+b'\x04\x0b\x53':return raw,{'already_applied':True}
    if memory!=profile['memory_size'] or script.hex()!=profile['script_hex']:raise ValueError('此版本的卡面 Tick 事件发生变化，未修改动画')
    out=bytearray(raw);insert=start+8+size-3;out[insert:insert]=call
    struct.pack_into('<II',out,start,memory+10,size+len(call));struct.pack_into('<Q',out,tick['at']+8,tick['size']+len(call))
    for row in exports:
        if row['offset']>tick['offset']:struct.pack_into('<Q',out,row['at'],row['offset']+len(call))
    return bytes(out),{'visible_tick_resumes_playback':True,'active_movies_not_restarted':True,'native_destruct_cleanup_preserved':True}

def packages(assets,resources=None):
    path=(Path(resources) if resources else ROOT)/'native-card-motion.json'
    data=json.loads(path.read_text(encoding='utf8'));result=[];reports=[]
    for row in data['widgets']:
        raw,meta=assets.get(row['path']);patched,report=patch_tick(raw,row)
        result.append((row['path'],patched,meta));reports.append({'path':row['path'],**report})
    return result,reports

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
