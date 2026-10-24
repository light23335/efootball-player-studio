"""Read our own APK metadata as data; preserve owners across repeated builds."""
import copy,json,uuid
from native_models import person_keys
from player_identity_binding import owned_person_aliases,BOUND_AGENT_MIN

PATH='assets/gateway-release/custom-resources/personal-player-studio/players.json'

def read(archive,release):
    if not release.get('personal_player_revision'):return {}
    if archive.getinfo(PATH).file_size>256*1024*1024:raise ValueError('个人包清单过大')
    doc=json.loads(archive.read(PATH))
    if doc.get('format')!='personal-player-native-v1' or doc.get('revision')!=release['personal_player_revision']:
        raise ValueError('个人包清单与版本标识不一致')
    players=doc.get('players',[]);seen=set();ids=set()
    if len(players)>10000:raise ValueError('个人包球员超过 10000 名上限')
    for p in players:
        identity=p['identity'];uid=str(uuid.UUID(identity['package_id']));cid=int(identity['card_id'])
        if uid in seen or cid in ids or p['owned'].get('_personal_player_uuid')!=uid or p['owned']['gameplayer_id']['id']!=cid:
            raise ValueError('个人包包含重复或不一致的球员身份')
        seen.add(uid);ids.add(cid)
    return doc

def merge(old,new,key):
    result={str(p[key]):copy.deepcopy(p) for p in old}
    for p in new:result[str(p[key])]=copy.deepcopy(p)
    return list(result.values())

def ownership(doc):
    custom_ids={int(v) for v in doc.get('editor_registries',{}).get('boosters',{}).values()}|{int(v) for v in doc.get('preview_boosters',{})}
    routes={int(r['cardId']):r for r in doc.get('native_binding',{}).get('routes',[])}
    result={}
    for p in doc.get('players',[]):
        i=p['identity'];uid=i['package_id'];cid=int(i['card_id']);pid=int(i['person_id'])
        route=routes.get(cid)
        if not route:raise ValueError('个人包缺少球员绑定记录')
        art=int(route['portraitKey'])
        history=set(map(int,i.get('previous_card_ids',[])))|{cid}
        independent=i.get('independent_person_id',pid);bound=i.get('bound_original_player_id')
        bound_valid=type(bound) is int and 0<bound<2**63 and pid==(bound&0xfffffff)
        bound_people=set(i.get('bound_person_ids',[]))
        if bound_valid:bound_people.add(pid)
        if not 90000000<=independent<99000000 or not (90000000<=pid<99000000 or bound_valid) or not 8000000<=art<9000000 or any((k&0xfffffff)!=independent and not ((k>>28)&4095>=BOUND_AGENT_MIN and (k&0xfffffff) in bound_people) for k in history):
            raise ValueError('个人包永久编号不在工坊专用范围内')
        aliases={cid,*owned_person_aliases(i),art,*history}
        result[uid]={'identity':i,'asset_key':art,'aliases':aliases,
                     'boosters':{int(b) for b in p['base_parameters'][144:147] if int(b) in custom_ids or 1000<=int(b)<1024}}
    used={}
    for uid,p in result.items():
        for alias in p['aliases']:
            if alias in used and used[alias]!=uid:raise ValueError('个人包球员槽位编号重叠')
            used[alias]=uid
    return result

def seed(doc,registry,assets):
    owners=ownership(doc)
    for uid,p in owners.items():
        i=p['identity'];old=registry.get(uid)
        if old and old['person_id']!=i['person_id'] and (old.get('independent_person_id') is None or old.get('independent_person_id')!=i.get('independent_person_id')):
            raise ValueError('同一球员在本机和个人包中的永久编号不同，请先核对工程来源')
        registry[uid]={'person_id':i['person_id'],'card_id':i['card_id'],
                       'independent_person_id':i.get('independent_person_id',i['person_id']),
                       'bound_original_player_id':i.get('bound_original_player_id'),
                       'bound_person_ids':list(i.get('bound_person_ids',[])),
                       'card_ids':sorted(set((old or {}).get('card_ids',[]))|{i['card_id'],*i.get('previous_card_ids',[])})}
        if uid in assets and int(assets[uid])!=p['asset_key']:raise ValueError('同一球员的美术槽位与个人包不同')
        assets[uid]=p['asset_key']
    return owners

def owned_art_paths(container,owners):
    import re
    keys={str(p['asset_key']) for p in owners}
    allowed=set()
    for path,index in container.paths.items():
        name=path.rsplit('/',1)[-1]
        if '/character/RealFace/' in path:
            match=re.match(r'(?:SK_|MI_|T_)(\d+)_',name)
        elif '/ui/Data/Thumbnail/Player/' in path:match=re.match(r'(\d+)(?:_|f\.)',name)
        else:continue
        if match and match[1] in keys:allowed.add(index)
    return allowed
