"""V22 multi-draw scenes; 2.1.8 actor selection, lighting and result order.

Audio is handled separately by native_draw_v22. This layer never computes
preview OVR, moves cards to the front or chooses a random spotlight.
"""
import copy,sys,types

META='_draw_gacha_v1'
SCORE='_draw_preview_overall_v1'
REVISION='v22-multi-audio-218-selection-light-order-v4'
MULTI=(10,20,30)


def native_actor(player):
    pid=int(player['gameplayer_id']['id']);family=(pid>>44)&15
    return family in(1,5)or family==6 and((pid>>40)&15)==1


def reveal_players(players):return players[:10]if len(players)==30 else players


def freeze(players,preview=None,lighting=None):
    """Stamp new receipts while preserving their exact identities and order."""
    result=copy.deepcopy(players)
    for row in result:
        meta=row.setdefault(META,{})
        for key in('lighting_version','lighting_effect'):meta.pop(key,None)
        meta['presentation_version']=4;row.pop(SCORE,None)
    return result


def response_fields(players,series=None,profiles=None):
    from personal_runtime import draw_response_fields
    profiles=dict(profiles or{});profiles.setdefault('player_selection','auto')
    result=draw_response_fields(players,profiles,series)
    if len(players)not in MULTI:return result
    count=min(4,sum(native_actor(p)for p in reveal_players(players)))
    old=result['effect_list'];opening=[e for e in old if e.startswith('OPENING_')]
    spotlight=next((e for e in old if e in('SPOTLIGHT_WIN','SPOTLIGHT_BIGWIN')),'SPOTLIGHT_WIN')
    if not count:effects=[]
    else:
        effects=opening+['WIN_SCREEN',spotlight,'RED_CARPET']
        if count==1:effects+=['PROMOTION_DRIBBLE','REVIVAL_SOLO']
        else:
            effects+=['GORGEOUS_STADIUM_ROOF','ENTRANCE_TWO']
            if count==3:effects.append('REVIVAL_SOLO')
            elif count==4:effects.append('REVIVAL_TWO')
    result['effect_list']=effects
    return result


def install(document):
    import draw_presentation
    original=draw_presentation.freeze_gacha;old_response=draw_presentation.response_fields
    if getattr(original,'_studio_draw_hybrid',False):return
    def freeze_gacha(conn,agent_id,players,pool=None):
        if not players or all(isinstance(p.get(META),dict)for p in players):return players
        result=original(conn,agent_id,players,pool)
        if not result or(pool or{}).get('mode')=='ANIMATION_TEST'or any((p.get(META)or{}).get('test_profile')for p in result):return result
        # Undo a V22-derived source's freezer sort without reassigning cards.
        queues={}
        for p in result:
            gid=p['gameplayer_id'];queues.setdefault((gid['id'],gid.get('serial',0)),[]).append(p)
        restored=[]
        for p in players:
            gid=p['gameplayer_id'];key=(gid['id'],gid.get('serial',0))
            if not queues.get(key):raise ValueError('抽卡元数据处理改变了球员身份，未改写结果')
            restored.append(queues[key].pop(0))
        if any(queues.values()):raise ValueError('抽卡元数据处理改变了球员数量，未改写结果')
        return freeze(restored)
    def fields(players):
        if any((p.get(META)or{}).get('test_profile')for p in players):return old_response(players)
        current=document()
        return response_fields(players,current.get('card_series_by_id',{}),current.get('draw_profiles',{}))
    freeze_gacha._studio_draw_hybrid=True
    for module in tuple(sys.modules.values()):
        if not isinstance(module,types.ModuleType):continue
        for key,value in tuple(vars(module).items()):
            if value is original:setattr(module,key,freeze_gacha)
            elif value is old_response:setattr(module,key,fields)
    draw_presentation.freeze_gacha=freeze_gacha;draw_presentation.response_fields=fields
