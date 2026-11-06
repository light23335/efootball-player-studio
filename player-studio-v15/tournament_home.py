"""Saved competition -> actual native homepage text, without reward fabrication."""
import copy
import struct
import threading
import tournament_rules as rules

REVISION='v17-tournament-home-native-promotion-v7-match-init'
TEXTS=('goal','fixture','home','away','stage_label','stage','remaining_label','remaining')
SCHEMA={'version':1,'bytes':133184,'header_bytes':64,'capacity':32,'row_bytes':4096,
        'text_offset':16,'text_bytes':256,'texts':list(TEXTS),
        'rendered_event':32,'render_sequence':36,'rental_ids_offset':2080,'rental_capacity':118,
        'membership_offset':3024,'membership_entity_offset':3028,
        'promotion_offset':131136,'promotion_bytes':2048}
_LOCK=threading.RLock()
_CHANNEL=None
_ROWS={}


def model(current,names=None,membership=None):
    names=names or {};stage=current['definition']['stages'][current['stage_index']]
    player=current['definition']['player_team_id'];kind=stage['type']
    rows=[f for f in current['fixtures'] if f['stage']==current['stage_index'] and player in (f['home'],f['away'])]
    pending=[f for f in rows if not f['played'] and not f.get('bye')]
    fixture=pending[0] if pending else None
    remaining=len(pending)
    goal={'groups':'争取小组出线','league':'争取联赛晋级名次','playoff':'争取附加赛晋级','knockout':'争取晋级下一轮'}[kind]
    if kind in ('playoff','knockout') and fixture:
        # Future knockout rounds are generated only after this tie completes.
        # Include the player's possible route to this stage's configured cut.
        size=current['knockout_size']//2
        while size>stage['output_count']:
            remaining+=rules.round_rules(stage,size)['legs'];size//=2
        if current['knockout_size']==2 and stage['output_count']==1:goal='争夺冠军'
    if current['completed']:
        goal='本届锦标赛已结束';remaining=0
    label={'groups':'小组赛','league':'联赛阶段','playoff':'附加赛','knockout':'淘汰赛'}[kind]
    if fixture:
        caption='下一场 · 第 '+str(fixture['round']+1)+' 轮'
        if 'tie' in fixture:caption+=' · 第 '+str(fixture['leg'])+' 回合'
        home='主：'+names.get(str(fixture['home']),'球队 '+str(fixture['home']))
        away='客：'+names.get(str(fixture['away']),'球队 '+str(fixture['away']))
    else:
        caption='本阶段已完成';home='';away='请查看赛程与积分榜'
    out=dict(zip(TEXTS,(goal,caption,home,away,'当前阶段',label,'本阶段剩余',str(remaining)+' 场')))
    from tournament_rewards import catalogue
    out.update(rental_team_id=player,rental_emblem_ids=[r['card_id']for r in catalogue()['cards']])
    if membership is not None:out['membership']=copy.deepcopy(membership)
    return out


def _text(value):
    # Bound UTF-16 code units without cutting a surrogate pair.
    raw=str(value).replace('\0','').encode('utf-16le')[:254]
    raw=raw.decode('utf-16le',errors='ignore').encode('utf-16le')+b'\0\0'
    return raw.ljust(256,b'\0')


def encode(rows):
    if len(rows)>32:raise ValueError('锦标赛主页最多支持 32 项赛事')
    out=bytearray(SCHEMA['capacity']*SCHEMA['row_bytes'])
    for i,(event,texts) in enumerate(sorted(rows.items())):
        if type(event)is not int or not 190000000<=event<240000000:raise ValueError('锦标赛主页编号无效')
        at=i*4096;struct.pack_into('<I',out,at,event)
        team=texts.get('rental_team_id',0);ids=texts.get('rental_emblem_ids',[])
        if type(team)is not int or not 0<=team<2**31 or len(ids)>118 or len(set(ids))!=len(ids):
            raise ValueError('锦标赛租借队标目录无效')
        struct.pack_into('<II',out,at+4,team,len(ids))
        for j,cid in enumerate(ids):
            if type(cid)is not int or not 0<cid<2**63:raise ValueError('锦标赛租借卡号无效')
            struct.pack_into('<Q',out,at+2080+j*8,cid)
        membership=texts.get('membership')
        if membership is not None:
            if not isinstance(membership,dict):raise ValueError('锦标赛候选球队归属无效')
            kind=membership.get('kind');entity=membership.get('entity_id')
            limit=512 if kind=='national'else 2**18 if kind=='club'else 0
            if type(entity)is not int or not 0<entity<limit:raise ValueError('锦标赛候选球队归属无效')
            struct.pack_into('<II',out,at+3024,1 if kind=='national'else 2,entity)
        for j,key in enumerate(TEXTS):out[at+16+j*256:at+16+(j+1)*256]=_text(texts[key])
    return out


def publish(rows):
    """Publish before the event reply leaves Python. No engine object reads."""
    global _ROWS
    encoded=encode(rows)
    with _LOCK:
        _ROWS=copy.deepcopy(rows)
        if _CHANNEL:_CHANNEL.publish(encoded,len(rows))


class Channel:
    def __init__(self,buffer,offset,fence):self.buffer=buffer;self.offset=offset;self.fence=fence
    def publish(self,encoded,count):
        at=self.offset;self.fence()
        seq=struct.unpack_from('<I',self.buffer,at+8)[0]
        seq=(seq+2)&0xfffffffe
        struct.pack_into('<I',self.buffer,at+8,seq|1);self.fence()
        self.buffer[at+64:at+64+SCHEMA['capacity']*SCHEMA['row_bytes']]=encoded
        struct.pack_into('<II',self.buffer,at,1,count);self.fence()
        struct.pack_into('<I',self.buffer,at+8,seq);self.fence()

    def rendered(self):
        self.fence();at=self.offset
        seq=struct.unpack_from('<I',self.buffer,at+36)[0]
        event=struct.unpack_from('<I',self.buffer,at+32)[0]
        self.fence()
        return (seq,event) if seq==struct.unpack_from('<I',self.buffer,at+36)[0]else(0,0)

    def promotion_menu(self):
        at=self.offset+SCHEMA['promotion_offset'];self.fence()
        raw=bytes(self.buffer[at:at+40]);seq,event,parent,ticket,generation,tick=struct.unpack('<IIQQQQ',raw)
        self.fence()
        if not seq or seq&1 or seq!=struct.unpack_from('<I',self.buffer,at)[0]:return None
        return dict(event=event,generation=generation,tick=tick)

    def promotion_enable(self):
        struct.pack_into('<I',self.buffer,self.offset+SCHEMA['promotion_offset']+912,1);self.fence()

    def promotion_request(self,ticket):
        at=self.offset+SCHEMA['promotion_offset']+40
        sequence=(struct.unpack_from('<I',self.buffer,at)[0]+2)&0xfffffffe or 2
        raw=bytearray(808)
        # 7 selects the original generic Others effect. The owned native
        # window suppresses its numbered badge PNG slots before binding.
        struct.pack_into('<IIQ16sII',raw,0,sequence,ticket['event'],ticket['generation'],bytes.fromhex(ticket['token'][:32]),1,7)
        for i,value in enumerate((ticket['view']['title'],ticket['view']['body'],'确认')):raw[40+i*256:40+(i+1)*256]=_text(value)
        struct.pack_into('<I',self.buffer,at,sequence|1);self.fence()
        self.buffer[at+4:at+808]=raw[4:];self.fence();struct.pack_into('<I',self.buffer,at,sequence);self.fence()
        return sequence

    def promotion_status(self):
        at=self.offset+SCHEMA['promotion_offset'];self.fence()
        raw=bytes(self.buffer[at+848:at+912]);seq,status=struct.unpack_from('<II',raw)
        self.fence()
        if not seq or seq&1 or seq!=struct.unpack_from('<I',self.buffer,at+848)[0]:return None
        return {'status':status,'token':raw[8:24].hex(),'reason':struct.unpack_from('<I',raw,52)[0],
                'generation':struct.unpack_from('<Q',raw,56)[0]}

    def promotion_clear(self,ticket):
        at=self.offset+SCHEMA['promotion_offset']+40
        if bytes(self.buffer[at+16:at+32]).hex()!=ticket['token'][:32]:return False
        struct.pack_into('<I',self.buffer,at,0);self.fence();return True

    def promotion_busy(self):
        state=self.promotion_status()
        return bool(state and state['status']in(1,2))


def attach_descriptor(payload,hook,body_offset,locations):
    if payload.get('tournament_home_channel') or hook.get('tournament_home_channel')!=SCHEMA or len(locations)!=1 or locations[0][1]!=SCHEMA['bytes']:
        raise ValueError('锦标赛主页通道布局无效')
    at=hook['helper_entries']['studio_home_fence'];raw=bytes.fromhex(hook['body_hex'])
    if raw[at:at+8]!=bytes.fromhex('bf3b03d5c0035fd6'):raise ValueError('锦标赛主页屏障入口无效')
    payload['tournament_home_channel']={'version':1,'revision':REVISION,'code_region':'root',
         'fence_offset':body_offset+at,'data_offset':locations[0][0],'schema':copy.deepcopy(SCHEMA)}


def register_binding_channel(binding,prefix_address,extension_address):
    global _CHANNEL
    d=binding.payload['tournament_home_channel'];region=d['code_region']
    if d['revision']!=REVISION or d['schema']!=SCHEMA or region not in ('root','extension'):raise ValueError('锦标赛主页重定位无效')
    raw=bytes.fromhex(binding.payload['extension_blob_hex'] if region=='extension' else binding.payload['blob_hex'])
    at=d['fence_offset'];base=extension_address if region=='extension' else prefix_address
    if not base or raw[at:at+8]!=bytes.fromhex('bf3b03d5c0035fd6'):raise ValueError('锦标赛主页执行屏障未核验')
    with _LOCK:
        _CHANNEL=Channel(binding.writable,d['data_offset'],binding.original.CFUNCTYPE(None)(base+at))
        _CHANNEL.publish(encode(_ROWS),len(_ROWS))
    from tournament_reward_ui import channel_ready
    channel_ready(_CHANNEL)
    from tournament_promotion_ui import channel_ready as promotion_ready
    promotion_ready(_CHANNEL)
    from league_availability import channel_ready as league_ready
    league_ready(_CHANNEL)
