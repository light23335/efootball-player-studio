"""Keep bound identity variants separate from the original card art series."""
import re

def key(cid):return ((cid>>40)&255,(cid>>28)&4095,bool(cid&(1<<48)))

def index(records):
    result={}
    for cid in sorted(records):result.setdefault(key(cid),[]).append(cid)
    return result

def donor(definition,route,records,series):
    identity=definition['identity'];cid=identity['card_id']
    if not identity.get('bound_original_player_id'):return cid
    source=definition.get('card_art_source') or {};style=source.get('native_style');agent=source.get('native_agent')
    if not style or agent is None:
        match=next((m for name in route.get('thumbnail_names',[]) if (m:=re.match(r'^(\d{4})_(\d+)_(?:f02|m02)(?:_lim)?$',name))),None)
        if not match:
            current=key(cid)
            previous=[old for old in reversed(identity.get('previous_card_ids',[])) if key(old)[0::2]==current[0::2] and key(old)[1]<4048]
            if previous:
                candidates=[previous[0]] if previous[0] in records else series.get(key(previous[0]),[])
                if candidates:return candidates[0]
            raise ValueError('绑定球员缺少原始卡面系列，请重新选择卡面预设')
        style,agent=match[1],int(match[2])
    expected=(int(style[:2])*16+int(style[2:]),int(agent),bool(cid&(1<<48)))
    original=int(source.get('source_id') or 0)
    if original in records and key(original)==expected:return original
    candidates=series.get(expected,[])
    if not candidates:raise ValueError('当前 APK 没有这张绑定卡使用的原始卡面系列，请重新选择预设')
    bound=identity['bound_original_player_id']
    return bound if bound in candidates else candidates[0]

def repair_routes(routes,definitions,records):
    owned={cid:d for d in definitions for cid in {d['identity']['card_id'],*d['identity'].get('previous_card_ids',[])}}
    series=index(records)
    for route in routes:
        definition=owned.get(route['suiteDonorId']) or owned.get(route['cardId'])
        if definition and definition['identity'].get('bound_original_player_id'):
            route['suiteDonorId']=donor(definition,route,records,series)
    return routes
