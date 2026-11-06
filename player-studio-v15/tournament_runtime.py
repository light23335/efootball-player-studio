"""Persistent custom competitions over the native offline event protocol.

Each fixture owns one START and one result receipt. Club squads are private
match copies; player ownership and the AI division's progress are untouched.
"""
import copy,hashlib,json,logging,random,threading,time,uuid,zlib
from contextlib import nullcontext
from pathlib import Path
import tournament_rules as rules
import tournament_promotion as promotion
import tournament_rewards as rewards
from tournament_squads import ClubGenerator,bind_team_identity

LOCK=threading.RLock()
PREFIX='player_studio_tournament_v1:'
CONTEXT=PREFIX+'context'
BLOB_PREFIX='studio_tournament_contract_blob_v1:'
MAX_CONTRACT_BYTES=32*1024*1024
# Concrete native navigation is shared with the division's outer/inner bridge.
# A process-local accepted entry, rather than this persisted legacy key, owns
# subsequent requests which omit an event ID.
from ai_division_sessions import EXIT_COMMANDS as EXITS
ENTRY_IMAGE='/banner/event/990000/3dad1fe746df39d8cd5b999a6a0995d512d719b3ec42553e66eea098648475b7'
EVENT_END=1999999999


def mainmenu(response,image=ENTRY_IMAGE):
    """Populate the native aggregate Events tile, not an inert web link."""
    if response.get('result')!='NOERR':return response
    rows=response.setdefault('event_info_list',[])
    if not isinstance(rows,list):raise ValueError('原生主页活动入口布局改变')
    template=next((r for r in rows if r.get('event_info_type')=='BOTH'),{})
    row=copy.deepcopy(template)
    row.update(event_banner=image,event_match_label='DREAM',event_info_type='BOTH',
               event_end_time=EVENT_END,event_recommend_kind='NONE',
               event_recommend_str='锦标赛模式',event_recommend_info_type='BOTH')
    rows[:]=[r for r in rows if r.get('event_info_type')=='AI_MATCH'];rows.insert(0,row)
    # BOTH opens a second native page. That page does not request an event
    # list until its AI_MATCH tile is enabled, independently of the parent.
    child=next((r for r in rows if r.get('event_info_type')=='AI_MATCH'),None)
    if child is None:
        child=copy.deepcopy(row);child['event_info_type']='AI_MATCH';rows.append(child)
    child.update(event_banner=image,event_match_label='DREAM',event_end_time=EVENT_END,
                 event_recommend_kind='NONE',event_recommend_str='锦标赛模式',event_recommend_info_type='AI_MATCH')
    return response


def get(conn,key,default=None):
    row=conn.execute('select value from meta where key=?',(key,)).fetchone()
    return json.loads(row[0])if row else copy.deepcopy(default)


def put(conn,key,value):
    conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',(key,json.dumps(value,ensure_ascii=False,separators=(',',':'))))


def contract_blob_key(current,fixture,sha256):
    return BLOB_PREFIX+':'.join((current['definition']['uuid'],current['run_id'],str(fixture['id']),sha256))


def _contract_limits(reference):
    if reference.get('codec')!='zlib-json-v1':raise ValueError('锦标赛阵容快照压缩版本不可用，原存档保持不变')
    size=reference.get('raw_bytes')
    if type(size)is not int or not 0<size<=MAX_CONTRACT_BYTES:raise ValueError('锦标赛阵容快照长度无效')
    compressed=reference.get('compressed_bytes')
    if type(compressed)is not int or not 0<compressed<=size+size//100+1024:raise ValueError('锦标赛阵容快照压缩长度无效')
    return size


def _read_contract_blob(conn,reference):
    _contract_limits(reference)
    # typeof/length are resolved before fetching the value, so a corrupt huge
    # row cannot force allocation of its entire payload merely to reject it.
    row=conn.execute("select value from meta where key=? and typeof(value)='blob' and length(value)=?",
                     (reference['key'],reference['compressed_bytes'])).fetchone()
    if row is None:raise ValueError('锦标赛阵容快照缺失或长度损坏，原比分保留且未重新模拟')
    return row[0]


def _unpack_contract(payload,reference):
    size=_contract_limits(reference)
    if not isinstance(payload,bytes)or len(payload)!=reference.get('compressed_bytes'):raise ValueError('锦标赛阵容快照数据缺失或长度损坏')
    try:
        decoder=zlib.decompressobj();raw=decoder.decompress(payload,size+1)
        if len(raw)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError('锦标赛阵容快照压缩数据损坏')
        if hashlib.sha256(raw).hexdigest()!=reference.get('sha256'):raise ValueError('锦标赛阵容快照校验失败，未重新模拟')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('锦标赛阵容快照格式无效')
        return value
    except(zlib.error,UnicodeError,json.JSONDecodeError)as exc:raise ValueError('锦标赛阵容快照无法读取，未重新模拟')from exc


def hydrate_contract(conn,current,fixture):
    """Read one complete saved audit/roster, never redraw or update SQL."""
    summary=fixture.get('simulation_v1')
    if not isinstance(summary,dict):return copy.deepcopy(summary)
    reference=summary.get('blob_v1')
    if reference is None:return copy.deepcopy(summary)  # Original full saves.
    if not isinstance(reference,dict)or reference.get('key')!=contract_blob_key(current,fixture,reference.get('sha256','')):
        raise ValueError('锦标赛阵容快照不属于此届比赛')
    full=_unpack_contract(_read_contract_blob(conn,reference),reference)
    for key,value in summary.items():
        if key=='blob_v1':continue
        original=full.get(key)
        if key in('ratings','result'):
            if key=='ratings':
                original={side:{k:v for k,v in ratings.items()if k!='audit'}for side,ratings in(original or{}).items()}
            else:original={k:v for k,v in(original or{}).items()if k in value}
        if value!=original:raise ValueError('锦标赛阵容快照与比赛摘要不一致')
    return full


def hydrate_state(conn,current):
    """Explicit audit helper; normal gameplay reads scores without hydrating."""
    value=copy.deepcopy(current)
    for fixture in value['fixtures']:
        if 'simulation_v1'in fixture:fixture['simulation_v1']=hydrate_contract(conn,current,fixture)
    return value


def compact_contracts(conn,current,fixture_ids):
    """Blob and its state reference must share the caller's result transaction."""
    if not conn.in_transaction:raise ValueError('阵容快照必须与赛果一起原子保存')
    selected=set(fixture_ids)
    for fixture in current['fixtures']:
        if fixture['id']not in selected or not fixture.get('played'):continue
        contract=fixture.get('simulation_v1')
        if not contract or contract.get('blob_v1')or not contract.get('settled'):continue
        raw=json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
        if not 0<len(raw)<=MAX_CONTRACT_BYTES:raise ValueError('单场锦标赛阵容快照超出有效大小，原存档保持不变')
        payload=zlib.compress(raw,6);sha=hashlib.sha256(raw).hexdigest();key=contract_blob_key(current,fixture,sha)
        reference=dict(key=key,sha256=sha,raw_bytes=len(raw),compressed_bytes=len(payload),codec='zlib-json-v1')
        previous=conn.execute('select typeof(value),length(value) from meta where key=?',(key,)).fetchone()
        if previous is None:conn.execute('insert into meta values(?,?)',(key,payload))
        else:
            if previous[0]!='blob':raise ValueError('锦标赛阵容快照存储类型损坏')
            reference['compressed_bytes']=previous[1];_unpack_contract(_read_contract_blob(conn,reference),reference)
        summary={k:copy.deepcopy(contract[k])for k in('model_version','strength_version','seeds','frozen','settled','source','xg')if k in contract}
        if 'ratings'in contract:summary['ratings']={side:{k:v for k,v in rating.items()if k!='audit'}for side,rating in contract['ratings'].items()}
        if 'result'in contract:summary['result']={k:copy.deepcopy(v)for k,v in contract['result'].items()
            if k in('raw_score','corrected_score','final_score','extra_time_score','penalties','correction','source')}
        summary['blob_v1']=reference;fixture['simulation_v1']=summary


def remember_plan(current,active):
    """Keep the user's private rentals and edits across fixtures, by team."""
    own=active.get(active.get('player_side','HOME').lower())
    if not own or not own.get('squad_data'):return
    team=own.get('_studio_tournament_squad',{}).get('team_id')or own['squad_data'].get('team_id')
    if not team:return
    current.setdefault('team_plans_v1',{})[str(team)]={
        'team':copy.deepcopy(own),'squad':copy.deepcopy(active.get('own_plan')or own['squad_data'])}


def borrowed_standard_in_initial_xi(team,squad):
    """Only explicitly auto-added fallback copies are restricted to the bench."""
    fallback=team.get('_studio_tournament_squad',{}).get('fallback')or{}
    added=set(fallback.get('added_standard_card_ids')or[])
    if not added:return False
    rows=fallback.get('players')or team.get('player_list',[])
    borrowed={(r['gameplayer_id']['id'],r['gameplayer_id']['serial'])for r in rows
              if r.get('gameplayer_id',{}).get('id')in added
              and r.get('standard_bench_added',True)}
    order=squad['squad_gameplan']['match_plan_settings']['order']
    return any((squad['player_list'][i]['gameplayer_id']['id'],
                squad['player_list'][i]['gameplayer_id']['serial'])in borrowed for i in order[:11])


FALLBACK_BENCH_NOTICE='随机补入的普卡只用于初始替补；首发须保留本队／同国籍真实球员。已保留上一份合法比赛计划，比赛中的正常换人不受影响。'


def event_id(t):return int(t['event_id'])


def progress_signature(t):
    """Only competition rules and participant membership start a new run."""
    normalized=rules.normalize(t)
    value={'team_ids':sorted(normalized['team_ids']),
           'stages':[{k:v for k,v in stage.items() if k not in ('uuid','name')}
                     for stage in normalized['stages']]}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def configuration(rows):
    out=[];ids=set()
    for raw in rows:
        if not raw.get('enabled'):continue
        design=copy.deepcopy(raw)
        for key in ('event_id','compe_unit_id','definition_revision'):design.pop(key,None)
        for i,s in enumerate(design.get('stages',[])):
            s.setdefault('uuid',str(uuid.uuid5(uuid.UUID(design['uuid']),f'stage:{i}:{s.get("type","knockout")}')))
        try:value=rules.normalize(design)
        except (ValueError,KeyError,TypeError)as exc:raise ValueError('锦标赛 '+str(raw.get('name')or raw.get('uuid'))+'：'+str(exc))from exc
        ident=190000000+int(hashlib.sha256(value['uuid'].encode()).hexdigest()[:7],16)%50000000
        if ident in ids:raise ValueError('锦标赛事件编号冲突，请复制其中一个赛事为新工程')
        ids.add(ident);value.update(event_id=ident,compe_unit_id=ident,definition_revision=progress_signature(value))
        out.append(value)
    return out


def export_rows(local,source):
    rows={t['uuid']:dict(uuid=t['uuid'],name=t['name'],difficulty=rules.difficulty(t),teams=len(t['team_ids']),source_only=True)for t in source}
    for t in local:
        if t.get('enabled'):rows[t['uuid']]=dict(uuid=t['uuid'],name=t.get('name')or'未命名锦标赛',difficulty=rules.difficulty(t),teams=len(t.get('team_ids',[])),source_only=False)
    return list(rows.values())


def export_selection(local,source,selected,writing):
    if not isinstance(selected,list)or len(selected)!=len(set(selected))or len(selected)>32:raise ValueError('锦标赛选择无效')
    available={t['uuid']:t for t in source}
    available.update({t['uuid']:t for t in local if t.get('enabled')})
    if not set(selected)<=available.keys():raise ValueError('所选锦标赛不存在或尚未启用，请重新读取列表')
    chosen={t['uuid']:t for t in source}if writing=='incremental'else{}
    chosen.update({uid:available[uid]for uid in selected})
    return configuration(list(chosen.values()))


def state(conn,t,*,persist=True):
    old=get(conn,PREFIX+t['uuid'])
    if old and progress_signature(old['definition'])==progress_signature(t):
        current=rules.State(old);definition=copy.deepcopy(t)
        active=current.get('active')or{}
        if active.get('started')or active.get('start_reply'):
            # Earlier builds may have saved the explicit configuration but
            # not copied it into the issued fixture's environment yet.
            minutes=rules.match_minutes(old['definition'])
            if minutes:active.setdefault('match_env',{}).setdefault('match_time',minutes)
        for previous,stage in zip(old['definition']['stages'],definition['stages']):
            stage['uuid']=previous['uuid']  # Keep reward/phase identities within this edition.
        previous_team=old['definition']['player_team_id']
        if previous_team!=t['player_team_id']:
            if active.get('started')or active.get('start_reply'):
                # An interrupted match must settle with its actual original side.
                definition['player_team_id']=previous_team
                current['pending_player_team_id']=t['player_team_id']
            else:
                if current.get('active'):remember_plan(current,current['active'])
                # The rental and CPU protocols have different identity and
                # coach contracts. An explicit pre-kickoff control-team edit
                # reissues provisional squads under the same fixture seeds.
                for fixture in current['fixtures']:
                    contract=fixture.get('simulation_v1')or{}
                    if not fixture.get('played')and not contract.get('frozen'):
                        contract.pop('teams',None)
                current.pop('active',None);current.pop('plan_notice',None)
                current.pop('pending_player_team_id',None)
        else:current.pop('pending_player_team_id',None)
        current['definition']=definition;current['difficulty']=rules.difficulty(t)
        job=current.get('cpu_remainder_v1')
        if job and job.get('binding')!=remainder_binding(current):current.pop('cpu_remainder_v1',None)
        current.pop('division',None);current.pop('next_division',None);current.pop('promoted',None)
        if persist:put(conn,PREFIX+t['uuid'],current)
        return current
    if old and persist:put(conn,PREFIX+t['uuid']+':backup:'+old['run_id'],old)
    current=rules.start(t,random.SystemRandom().getrandbits(63))
    if persist:put(conn,PREFIX+t['uuid'],current)
    return current


def _strength_snapshot(team,generator,conn,**options):
    from tournament_sim_strength import snapshot_for_ratings
    return snapshot_for_ratings(team,generator,conn,**options)


def _team_ratings(team,document=None):
    from tournament_sim_strength import ratings
    return ratings(team,document=document)


def simulation_contract(current,fixture):
    """An edition pins its model; settled old fixtures are never migrated."""
    import tournament_simulation as simulation
    from tournament_sim_strength import REVISION as strength_version
    if fixture.get('played'):return fixture.get('simulation_v1')
    policy=current.setdefault('simulation_policy_v1',{'model_version':simulation.MODEL_VERSION,
                                                    'strength_version':strength_version})
    contract=fixture.setdefault('simulation_v1',dict(policy,
        seeds={key:rules.seed_number(current['seed'],current['run_id'],fixture['id'],key)
               for key in ('lineup','regulation','extra_time','penalties')},frozen=False))
    if contract['model_version']!=simulation.MODEL_VERSION:
        raise ValueError('本届锦标赛的赛果算法暂不可用，已保留原存档：'+str(contract['model_version']))
    if contract.get('strength_version')!=strength_version:
        raise ValueError('本届锦标赛的阵容评分版本暂不可用，已保留原存档')
    return contract


def prior_form(current,team,fixture):
    """Only previously settled appearances count; byes are not matches."""
    import tournament_simulation as simulation
    history=[]
    for row in current['fixtures']:
        if row['id']==fixture['id']or not row.get('played')or row.get('bye')or team not in(row['home'],row['away']):continue
        i=0 if row['home']==team else 1
        own,other=row['score'][i],row['score'][1-i]
        # A shootout decides progression, not the football W/D/L streak.
        history.append('W'if own>other else'D'if own==other else'L')
    return simulation.form_state(history)


def _next_fixture(current,simulate=None):
    player=current['definition']['player_team_id']
    while not current['completed']:
        pending=rules.due(current)
        if not pending:rules.advance(current);continue
        own=next((f for f in pending if player in(f['home'],f['away'])),None)
        if own:return own
        if simulate is None:
            raise ValueError('推进电脑赛程需要真实锦标赛阵容上下文；赛事进度未重抽')
        for f in pending:
            if simulate(f)is False:return None
    return None


def settle_progression(current,before,game_id=None):
    decisions=promotion.settle(current,before,game_id)
    rewards.settle(current,decisions)


def player_eliminated(current):
    """A completed table/tie decides this; a loss or empty due list does not."""
    return any(row['outcome']=='eliminated'for row in promotion.resolved(current).values())


def remainder_binding(current):
    t=current['definition']
    return [t['uuid'],current['run_id'],progress_signature(t),t['player_team_id']]


def next_fixture(current,simulate=None):
    before=promotion.capture(current)
    fixture=_next_fixture(current,simulate)
    settle_progression(current,before)
    return fixture


def team_name(team,names=None):return (names or{}).get(str(team),'球队 '+str(team))


def cover_image(definition,fallback=None):
    return (definition.get('cover_artwork')or{}).get('request')or fallback


def team_membership(definition,nations=None):
    team=definition['player_team_id'];nation=(nations or{}).get(str(team))
    return {'kind':'national'if nation is not None else'club','entity_id':nation if nation is not None else team}


def entry_log(current,fixture,template=None,status='NO_ENTRY'):
    """One native event-log projection for both LIST and successful ENTER."""
    t=current['definition'];player=t['player_team_id']
    log=copy.deepcopy(template or{})
    log.update(event_id=event_id(t),entry_status=status,use_preset_team_id=player)
    for mission in log.get('ch_mission_log',[]):
        mission.update(com_level=rules.difficulty(current),win_num=0,win_point=0,goals=0,goal_diff=0,
                       played_match_num=0,cleared_count=0,
                       ch_rival_team_id=(fixture['away']if fixture['home']==player else fixture['home'])if fixture else 0,
                       vscom_event_reward=[])
        for key in('first_clear_reward_list','first_reward_second_list'):
            if isinstance(mission.get(key),dict):mission[key].update(reward_count=0,event_reward_list=[])
    return log


def summary(current,names=None):
    stage=current['definition']['stages'][current['stage_index']]
    rows=[f for f in current['fixtures']if f['stage']==current['stage_index']]
    player=current['definition']['player_team_id'];own=[f for f in rows if player in(f['home'],f['away'])]
    remaining=sum(not f['played'] and not f.get('bye') for f in own)
    text=[rules.DIFFICULTIES[rules.difficulty(current)]+' · '+stage['name'],team_name(player,names)+f" · 本阶段剩余 {remaining} 场",
          '仅可使用'+team_name(player,names)+'队套，可选择下发球员或自己已持有的同队球员；同人不能重复入选。可调整首发、替补及战术。']
    if current.get('pending_player_team_id'):
        text.append('已开场比赛保留原控制队，结算后切换为'+team_name(current['pending_player_team_id'],names)+'；本届进度保留。')
    if current['completed']:text.append('本届冠军：'+team_name(current['champion'],names)+'。重新报名可开始下一届。')
    elif current.get('cpu_remainder_v1'):
        text.append('本届已被淘汰，剩余电脑赛程正在结算；可重新报名开始下一届，旧届赛果会继续保存。')
    else:
        fixture=next((f for f in own if not f['played']),None)
        if fixture:text.append('下一场：'+team_name(fixture['home'],names)+' vs '+team_name(fixture['away'],names))
    if stage['type']in('groups','league'):
        group=next((i for i,teams in enumerate(current['groups'])if player in teams),None)
        if group is not None:
            table=rules.standings(current,group);rank=next(i+1 for i,r in enumerate(table)if r['team']==player)
            text.append(f"当前排名：第 {rank}/{len(table)} 名 · {table[rank-1]['points']} 分")
    return '\n'.join(text)


def overview_html(current,names=None):
    """Full saved competition, also usable when a league exceeds native brackets."""
    from html import escape
    def name(team):return escape(team_name(team,names))
    definition=current['definition'];player=definition['player_team_id'];parts=[]
    for index,stage in enumerate(definition['stages']):
        rows=[f for f in current['fixtures']if f['stage']==index]
        if not rows:continue
        parts.append('<section><h2>'+escape(stage['name'])+'</h2>')
        if index==current['stage_index']and stage['type']in('groups','league'):
            for group in range(len(current['groups'])):
                parts.append('<h3>'+('积分榜'if stage['type']=='league'else'第 '+str(group+1)+' 组')+'</h3><table><tr><th>排名</th><th>球队</th><th>场</th><th>胜</th><th>平</th><th>负</th><th>净胜</th><th>分</th></tr>')
                for rank,row in enumerate(rules.standings(current,group),1):
                    parts.append('<tr'+(' class="own"'if row['team']==player else'')+'><td>'+str(rank)+'</td><td>'+name(row['team'])+'</td>'+''.join('<td>'+str(row[key])+'</td>'for key in('played','wins','draws','losses','goal_difference','points'))+'</tr>')
                parts.append('</table>')
        last=None
        for fixture in rows:
            if fixture['round']!=last:
                last=fixture['round'];parts.append('<h3>第 '+str(last+1)+' 轮</h3>')
            score=' — '.join(map(str,fixture['score']))if fixture['played']else'vs'
            if fixture.get('penalties'):score+='（点球 '+':'.join(map(str,fixture['penalties']))+'）'
            parts.append('<div class="match'+(' own'if player in(fixture['home'],fixture['away'])else'')+'"><span>'+name(fixture['home'])+'</span><b>'+escape(score)+'</b><span>'+name(fixture['away'])+'</span></div>')
        parts.append('</section>')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>赛程与积分榜</title><style>
    *{box-sizing:border-box}body{margin:0;background:#101a2a;color:#e8eef9;font:16px/1.6 sans-serif;padding:24px;max-width:1100px;margin:auto}h1{font-size:28px}h2{color:#70decc}h3{font-size:18px}section{background:#1b293e;border-radius:18px;padding:20px;margin-top:24px;overflow:auto}p{white-space:pre-line;color:#c7d3e5}table{border-collapse:collapse;width:100%;min-width:500px}td,th{padding:10px;text-align:center;border-bottom:1px solid #40506a}td:nth-child(2){text-align:left}.own{color:#88f3d8;background:#243d4a}.match{display:grid;grid-template-columns:1fr auto 1fr;gap:16px;padding:12px;border-bottom:1px solid #40506a}.match span:last-child{text-align:right}</style><h1>'''+escape(definition['name'])+'</h1><p>'+escape(summary(current,names))+'</p>'+''.join(parts)+'<p>本页显示已保存的赛事进度，返回游戏可继续比赛。</p></html>'
    return html.encode('utf8')


def project_events(logic,response,definitions,image=ENTRY_IMAGE,names=None,landscape=None,overview_url=None,nations=None,service=None):
    rows=response.get('event_list')
    if response.get('result')!='NOERR'or not isinstance(rows,list):return response
    proto=next((e for e in rows if e.get('event_id')==1120005),None)
    if proto is None:proto=next((e for e in rows if isinstance(e.get('match_env'),dict)and e.get('ch_event_type')in('TOURNAMENT','CHALLENGE')),None)
    if proto is None:raise ValueError('原生赛事页面模板缺失')
    proto=copy.deepcopy(proto);logs=response.get('event_log_list');log_proto=copy.deepcopy(next((r for r in logs or[]if r.get('event_id')==1120005),{}))
    if service is not None:service.entry_log_template=copy.deepcopy(log_proto)
    rows[:]=[]
    if isinstance(logs,list):logs[:]=[]
    home_rows={}
    for t in definitions:
        current=state(logic.conn,t);t=current['definition'];row=copy.deepcopy(proto);eid=event_id(t)
        minutes=(proto.get('match_env')or{}).get('match_time')
        if type(minutes)is int and 0<=minutes<=30:current['native_default_match_time']=minutes
        fixture=service.next_fixture(logic.conn,current)if service else next_fixture(current)
        put(logic.conn,PREFIX+t['uuid'],current)
        from tournament_home import model
        home_rows[eid]=model(current,names,membership=team_membership(t,nations))
        row.update(event_id=eid,compe_unit_id=eid,event_name=t['name'],event_list_disp_name=t['name']+' · '+rules.DIFFICULTIES[rules.difficulty(current)],
                   description_text=summary(current,names),rule_detail_text=summary(current,names),ch_event_type='CHALLENGE',
                   ch_enable_change_cpu_level='NO',is_official_competition='NO',main_reward_list=[],pt_reward_list=[],useable_team_list=[t['player_team_id']],useable_compe_list=[])
        row.update(is_vs_user='NO',is_nonsupport='NO',ch_is_challenge_unlocked='YES',
                   event_start_time=1700000000,event_end_time=EVENT_END,
                   event_panel_open_time=1700000000,event_panel_close_time=EVENT_END,
                   banner_file_name=cover_image(t,landscape or image),announce_banner_file_name='',detail_banner_file_name='',
                   event_menu_banner_file_name=cover_image(t,landscape or image),is_limit_control_style='NO',is_vsai_force_no_substitute='NO',
                   is_vsai_custom_team='NO',is_vsai_gameplan_disp='YES',
                   vsai_team_id_for_emblem=(fixture['away']if fixture['home']==t['player_team_id']else fixture['home'])if fixture else 0)
        # This native flag does NOT mean "accept our generated CPU squad".
        # At 0x7769a88, YES enters 0x7769b44: rebuild a stock club at
        # 0x82d66cc, replace the received gameplan via 0x7652c74, then try
        # matching those stock IDs against our selected full-player rows.
        # The IDs differ and the match roster becomes empty. NO keeps the
        # received 23-player plan, as required by the AI division generator.
        nation=(nations or{}).get(str(t['player_team_id']))
        row['match_entry']={'entry_type':'NATIONALITY'if nation is not None else'CLUB','entity_id_list':[nation if nation is not None else t['player_team_id']],
                            'extra_entity_id':[],'player_num':23,'range_low':0,'range_high':0}
        row.setdefault('match_env',{}).update(match_environment(current,fixture))
        # The native TOURNAMENT page only renders its stock knockout tree.
        # Arbitrary leagues/two-leg stages cannot use that tree (630 valid
        # rows parse successfully but leave its view blank). Use the native
        # single-match shell and the full persistent schedule/table link.
        # Reuse the native single-fixture entry shell, not its old four-win
        # cup counters. The complete stage/table/bracket remains our saved
        # competition; the native entry points at the next concrete fixture.
        phase_rows=[f for f in current['fixtures']if f['stage']==current['stage_index']]
        pending=rules.due(current);round_no=pending[0]['round']if pending else current['round']
        for mission in row.get('ch_mission_info_list',[]):
            mission.update(match_count=1,clear_condition={'type':'TOTAL_WIN','value':1},
                           ch_ai_com_level_list=[rules.difficulty(current)],
                           compe_phase_info={'compe_phase_id':current['stage_index']+1,'mission_number':round_no+1,
                                             'total_mission_count':max((f['round']for f in phase_rows),default=0)+1})
        row.update(achievement_name_list=[],link_title_list=[],link_url_list=[])
        if overview_url:row.update(link_title_list=['赛程与积分榜：查看全部轮次和赛果'],link_url_list=[overview_url+'/'+t['uuid']])
        rows[:]=[r for r in rows if r.get('event_id')!=eid];rows.append(row)
        logs=response.get('event_log_list')
        if isinstance(logs,list):
            # A persisted competition is not the native client's special
            # slot. Cold entry reinstalls it, but later LIST replies must not
            # erase the successful registration in this gateway session.
            status='ENTRY'if service is not None and service.is_entered(current,fixture)else'NO_ENTRY'
            log=entry_log(current,fixture,log_proto,status)
            logs[:]=[r for r in logs if r.get('event_id')!=eid];logs.append(log)
    response['event_num']=len(rows)
    from tournament_home import publish
    publish(home_rows)
    return response


def publish_saved_home(conn,definitions,names,nations=None):
    """Refresh native homepage text after a fixture changes, before its reply."""
    from tournament_home import model,publish
    rows={}
    for t in definitions:
        current=get(conn,PREFIX+t['uuid'])
        if current:rows[event_id(t)]=model(current,names,membership=team_membership(current['definition'],nations))
    publish(rows)


def match_environment(current,fixture):
    knockout=bool(fixture and 'tie'in fixture and fixture['leg']==fixture['legs'])
    env={'cpu_level':rules.difficulty(current),
         'exTime':'YES'if knockout and fixture.get('extra_time')else'NO','pk':'YES'if knockout else'NO'}
    active=current.get('active')or{}
    if (active.get('started')or active.get('start_reply'))and fixture and active.get('fixture_id')==fixture['id']:
        # A resumed match keeps the duration with which it was issued.
        minutes=active.get('match_env',{}).get('match_time',0)
    else:minutes=rules.match_minutes(current.get('definition',current))or current.get('native_default_match_time',0)
    if minutes:env['match_time']=minutes
    return env


def refresh_match_time(definition,active,current):
    """Refresh an unissued fixture; an issued START owns its original time."""
    if active.get('started')or active.get('start_reply'):return
    minutes=rules.match_minutes(definition)or current.get('native_default_match_time',0)
    env=active.setdefault('match_env',{})
    if minutes:env['match_time']=minutes
    else:env.pop('match_time',None)


def refresh_difficulty(definition,active):
    """Refresh the explicit difficulty without regenerating frozen squads."""
    level=rules.difficulty(definition)
    env=active.setdefault('match_env',{})
    previous={'match_env':env.get('cpu_level')}
    env['cpu_level']=level
    for side in ('home','away'):
        team=active.get(side)
        if isinstance(team,dict):
            previous[side]=team.get('cpu_level');team['cpu_level']=level
    reply=active.get('start_reply')
    if isinstance(reply,dict)and 'cpu_level'in reply:reply['cpu_level']=level
    if any(v!=level for v in previous.values()):
        logging.getLogger(__name__).info('Tournament cached difficulty refreshed: game=%s previous=%s current=%s',
                                        active['game_id'],previous,level)
    return level


def native_rules(current,fixture):
    """Prior goals follow this leg's HOME/AWAY teams, not first-leg order."""
    pair=fixture.get('legs')==2;second=pair and fixture['leg']==2
    previous=[0,0]
    if second:
        first=next(f for f in current['fixtures']if f.get('tie')==fixture['tie']and f['leg']==1)
        if not first['played']:raise ValueError('首回合尚未结算')
        scored={first['home']:first['score'][0],first['away']:first['score'][1]}
        previous=[scored[fixture['home']],scored[fixture['away']]]
    final=bool('tie'in fixture and fixture['leg']==fixture['legs'])
    return dict(two_leg=pair,first_leg=pair and not second,second_leg=second,prior_goals=previous,
                extra_time=final and fixture.get('extra_time',False),penalties=final,
                away_goals=second and fixture.get('away_goals',False),
                away_goals_extra_time=fixture.get('away_goals_extra_time',False))


class Service:
    def __init__(self,document,root,generator):
        self.document=document;self.root=root;self.generator=generator
        self.entry_binding=None;self.entry_log_template={}
        self._remainder_workers={};self._remainder_targets=set();self._recovered_databases=set()
        self._remainder_overflow=set();self._round_cache={};self._prewarm_workers={}
        self._cache_lock=threading.RLock();self._prewarm_pending={};self._prewarm_tokens={};self._round_source_token=None

    def database_path(self,conn):
        # A worker must never share the gateway's connection, even if it was
        # created with check_same_thread=False. In-memory callers stay synchronous.
        return next((row[2]for row in conn.execute('pragma database_list')if row[1]=='main'and row[2]),None)

    def worker_generator(self,document):
        g=self.generator
        return ClubGenerator(lambda:document,g.developed,g.wire,g.caps,g.formation,g.teams,g.normalize,g.root)

    def source_context(self,conn,document=None):
        """Exact generation inputs, independent of unrelated meta commits."""
        document=self.document()if document is None else document;digest=hashlib.sha256()
        queries=['select card_id,fingerprint,payload from managed_cards order by card_id',
                 'select coach_id,serial,json from coaches order by coach_id,serial,json']
        if conn.execute("select 1 from sqlite_master where name='excluded_catalog_ids'").fetchone():
            queries.append("select card_id,reason from excluded_catalog_ids where reason!='China edition' order by card_id,reason")
        for query in queries:
            for row in conn.execute(query):
                for value in row:
                    raw=str(value).encode('utf8');digest.update(len(raw).to_bytes(8,'little'));digest.update(raw)
        keys=('players','native_player_catalogue','tournament_standard_cards','tournament_national_team_nations',
              'division_squads','preview_boosters','native_booster_catalogue','coaches',
              'tournament_fallback_standard_cards','catalogue_recycle_bin','revision')
        digest.update(json.dumps({k:document.get(k)for k in keys},separators=(',',':')).encode())
        return digest.hexdigest()

    def round_cache_key(self,current,fixture,source=None):
        teams=(fixture['home'],fixture['away'])
        previous=[(f['id'],f['home'],f['away'],f['score'],f.get('extra_time_score'),f.get('penalties'))
                  for f in current['fixtures']if f.get('played')and not f.get('bye')
                  and any(team in(f['home'],f['away'])for team in teams)]
        original={k:v for k,v in fixture.items()if k not in('played','score','penalties','extra_time_score')}
        value=[remainder_binding(current),current['definition']['include_diy'],current.get('simulation_policy_v1'),
               self.document().get('revision'),self._round_source_token if source is None else source,original,previous]
        return hashlib.sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()

    def prewarm_round(self,conn,current):
        """Prepare only current due CPU games, without publishing a score."""
        path=self.database_path(conn)
        if not path or current['completed']or player_eliminated(current):return
        source=self.source_context(conn);self._round_source_token=source
        player=current['definition']['player_team_id']
        pending=[f for f in rules.due(current)if player not in(f['home'],f['away'])]
        rows=[(f['id'],self.round_cache_key(current,f))for f in pending]
        identity=(path,current['run_id'],tuple(key for _,key in rows))
        with self._cache_lock:
            old=self._prewarm_workers.get(path)
            if self._prewarm_tokens.get(path)==identity and old is not None and old.is_alive():return
            self._prewarm_tokens[path]=identity
            rows=[row for row in rows if row[1]not in self._round_cache]
            self._prewarm_pending[path]=(copy.deepcopy(current),rows,identity)
            self.launch_prewarm(path)

    def launch_prewarm(self,path):
        # Called with the independent cache lock. One CPU prewarm per DB;
        # a changed run replaces only the pending request, never spawns peers.
        old=self._prewarm_workers.get(path)
        if old is not None and old.is_alive():return
        pending=self._prewarm_pending.pop(path,None)
        if pending is None or not pending[1]:return
        current,rows,identity=pending
        thread=threading.Thread(target=self.run_prewarm,args=(path,current,rows,identity),
                                name='tournament-current-round',daemon=True)
        self._prewarm_workers[path]=thread;thread.start()

    def run_prewarm(self,path,current,rows,identity):
        import sqlite3
        conn=None
        try:
            conn=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
            document=copy.deepcopy(self.document());worker=Service(lambda:document,self.root,self.worker_generator(document))
            worker._round_source_token=self.source_context(conn,document)
            for fid,key in rows:
                with self._cache_lock:
                    token=self._prewarm_tokens.get(path)
                    if token is not None and token!=identity:return
                fixture=next(f for f in rules.due(current)if f['id']==fid)
                if worker.round_cache_key(current,fixture)!=key:return
                worker.simulate_fixture(conn,current,fixture)
                with self._cache_lock:
                    token=self._prewarm_tokens.get(path)
                    if token is not None and token!=identity:return
                    self._round_cache[key]=copy.deepcopy(fixture)
                    while len(self._round_cache)>128:self._round_cache.pop(next(iter(self._round_cache)))
        except Exception:
            # This is an optional read-only optimization. The result path uses
            # its normal deterministic algorithm if any ready contract is absent.
            logging.getLogger(__name__).exception('Tournament current-round preparation skipped')
        finally:
            if conn is not None:conn.close()
            with self._cache_lock:
                if self._prewarm_workers.get(path)is threading.current_thread():self._prewarm_workers.pop(path,None)
                self.launch_prewarm(path)

    def remainder_state(self,conn,binding):
        uid,run,_,_=binding
        for key in(PREFIX+uid,PREFIX+uid+':history:'+run):
            current=get(conn,key)
            if current and current.get('run_id')==run:return key,rules.State(current)
        return None,None

    def valid_remainder(self,current,binding):
        job=(current or{}).get('cpu_remainder_v1')or{}
        return job.get('binding')==list(binding)and remainder_binding(current)==list(binding)

    def stop_remainder(self,conn,key,current,identity):
        current['cpu_remainder_v1'].update(status='superseded',error='赛事规则或控制队已改变；后台任务停止，原赛果保留')
        with conn:put(conn,key,current)
        self._remainder_targets.discard(identity)

    def launch_remainder(self,path,binding):
        identity=(str(path),tuple(binding));self.remember_remainder(path,binding)
        # The persistent histories are the queue. At most one remainder and
        # one read-only prewarm compute per database, regardless of run count.
        if any(key[0]==str(path)and thread.is_alive()for key,thread in self._remainder_workers.items()):return
        thread=threading.Thread(target=self.run_remainder,args=(str(path),tuple(binding)),
                                name='tournament-remainder',daemon=True)
        self._remainder_workers[identity]=thread;thread.start()

    def remember_remainder(self,path,binding):
        identity=(str(path),tuple(binding))
        if identity in self._remainder_targets:return
        if sum(key[0]==str(path)for key in self._remainder_targets)>=64:self._remainder_overflow.add(str(path))
        else:self._remainder_targets.add(identity)

    def resume_remainders(self,conn):
        path=self.database_path(conn)
        if not path:return
        if path not in self._recovered_databases:
            # Recovery is once per gateway/database, not a megabyte JSON scan
            # on every native request. New jobs register their target at commit.
            for key,raw in conn.execute('select key,value from meta where key like ? and value like ?',
                                        (PREFIX+'%','%"cpu_remainder_v1":%')):
                current=json.loads(raw);job=current.get('cpu_remainder_v1')or{}
                if job.get('status')in('pending','failed')and self.valid_remainder(current,job.get('binding',[])):
                    self.remember_remainder(path,job['binding'])
                    if path in self._remainder_overflow:break
            self._recovered_databases.add(path)
        for identity in tuple(self._remainder_targets):
            target_path,binding=identity
            if target_path!=path:continue
            thread=self._remainder_workers.get(identity)
            if thread is None or not thread.is_alive():
                _,current=self.remainder_state(conn,binding)
                job=(current or{}).get('cpu_remainder_v1')or{}
                if self.valid_remainder(current,binding)and job['status']in('pending','failed')and job.get('retry_after',0)<=time.time():
                    self.launch_remainder(path,binding)
                elif not self.valid_remainder(current,binding)or job.get('status')not in('pending','failed'):self._remainder_targets.discard(identity)
        if not any(identity[0]==path for identity in self._remainder_targets)and path in self._remainder_overflow:
            self._remainder_overflow.discard(path);self._recovered_databases.discard(path)

    def run_remainder(self,path,binding):
        """Resume one old edition, committing one deterministic CPU fixture at a time."""
        import sqlite3
        identity=(str(path),tuple(binding));conn=None
        try:
            conn=sqlite3.connect(path,timeout=5)
            document=copy.deepcopy(self.document());worker=Service(lambda:document,self.root,self.worker_generator(document))
            worker_source=self.source_context(conn,document)
            while True:
                with LOCK:
                    key,current=self.remainder_state(conn,binding)
                    if not self.valid_remainder(current,binding):return
                    job=current['cpu_remainder_v1']
                    if job['status']=='completed':return
                    # A definition/control-team edit invalidates an unarchived
                    # task. A normal new ENTRY archives its exact original run.
                    definition=next((t for t in self.definitions()if t['uuid']==binding[0]),None)
                    if definition is None or progress_signature(definition)!=binding[2]or definition['player_team_id']!=binding[3]:
                        self.stop_remainder(conn,key,current,identity);return
                    if not player_eliminated(current):raise ValueError('后台余赛没有已确认的淘汰结果')
                    if current['completed']:
                        job.update(status='completed',error=None)
                        with conn:put(conn,key,current)
                        return
                    pending=rules.due(current)
                    if not pending:raise ValueError('后台余赛没有可结算赛程')
                    fixture=pending[0];fid=fixture['id'];cursor=job['settled_cpu']
                    include_diy=current['definition']['include_diy'];source=self.source_context(conn)
                    if source!=worker_source:
                        document=copy.deepcopy(self.document());worker=Service(lambda:document,self.root,self.worker_generator(document))
                        worker_source=self.source_context(conn,document)
                    if binding[3]in(fixture['home'],fixture['away']):raise ValueError('后台余赛不能替玩家比赛')
                # No gateway LOCK or SQL transaction during real lineup/rating.
                worker.simulate_fixture(conn,current,fixture)
                with LOCK:
                    key,latest=self.remainder_state(conn,binding)
                    if not self.valid_remainder(latest,binding):return
                    if latest['cpu_remainder_v1']['settled_cpu']!=cursor:continue
                    if latest['definition']['include_diy']!=include_diy or self.source_context(conn)!=source:
                        document=copy.deepcopy(self.document());worker=Service(lambda:document,self.root,self.worker_generator(document))
                        worker_source=self.source_context(conn,document)
                        continue
                    definition=next((t for t in self.definitions()if t['uuid']==binding[0]),None)
                    if definition is None or progress_signature(definition)!=binding[2]or definition['player_team_id']!=binding[3]:
                        self.stop_remainder(conn,key,latest,identity);return
                    target=next((f for f in rules.due(latest)if f['id']==fid),None)
                    if target is None:raise ValueError('后台赛程身份已变化，未覆盖旧赛果')
                    before=promotion.capture(latest)
                    target['simulation_v1']=fixture['simulation_v1']
                    rules.record(latest,fid,*fixture['score'],penalties=fixture.get('penalties'),extra=fixture.get('extra_time_score',[0,0]))
                    settle_progression(latest,before)
                    latest['cpu_remainder_v1'].update(settled_cpu=cursor+1,last_fixture_id=fid,error=None,
                        status='completed'if latest['completed']else'pending',attempts=0,retry_after=0)
                    with conn:
                        conn.execute('begin immediate');compact_contracts(conn,latest,[fid]);put(conn,key,latest)
                    if latest['completed']:
                        if key==PREFIX+binding[0]:publish_saved_home(conn,self.definitions(),self.names(),self.document().get('tournament_national_team_nations',{}))
                        return
        except Exception as exc:
            logging.getLogger(__name__).exception('Tournament background remainder retained for retry: %s',binding)
            if conn is not None:
                conn.rollback()
                with LOCK:
                    key,current=self.remainder_state(conn,binding)
                    if self.valid_remainder(current,binding)and not current['completed']:
                        attempts=current['cpu_remainder_v1'].get('attempts',0)+1
                        current['cpu_remainder_v1'].update(status='failed',error=str(exc)[:512],attempts=attempts,
                            retry_after=time.time()+min(300,2**min(attempts,8)))
                        with conn:put(conn,key,current)
        finally:
            with LOCK:
                if self._remainder_workers.get(identity)is threading.current_thread():self._remainder_workers.pop(identity,None)
                if conn is not None:self.resume_remainders(conn)
            if conn is not None:conn.close()

    def entry_key(self,current,fixture):
        return (current['definition']['uuid'],current['run_id'],current['definition']['player_team_id'],
                fixture['id']if fixture else None)

    def is_entered(self,current,fixture):
        # The game has one special slot: entering another competition replaces
        # it. Do not persist this client-session acknowledgement into saves.
        return fixture is not None and self.entry_binding==self.entry_key(current,fixture)

    def definitions(self):return self.document().get('tournaments',[])

    def names(self):return self.document().get('tournament_team_names',{})

    def overview_url(self):
        import sys
        state=getattr(sys.modules.get('embedded_gateway'),'_studio_pack_image_service',None)
        service=state and state.get('service')
        if service:
            service.tournament_overview=lambda uid:self.overview(uid)
            return service.url+'/player-studio/tournaments'

    def overview(self,uid):
        from tournament_schedule_ui import saved_overview
        if not any(t['uuid']==uid for t in self.definitions()):return None
        return saved_overview(self.root,uid,self.names(),self.document().get('tournament_emblems',{}))

    def special(self,conn,t,current,request):
        active=self.prepare(conn,t,current,request);own=active[active['player_side'].lower()]
        # Only unissued rentals may migrate; a saved START owns its abilities.
        self.repair_rentals(conn,current,active,entering=True)
        squad=copy.deepcopy(active.get('own_plan')or own['squad_data'])
        squad['team_id']=t['player_team_id']
        rental={p['gameplayer_id']['id']:copy.deepcopy(p)for p in own['player_list']}
        rental.update({p['gameplayer_id']['id']:p for p in self.reinforcements(conn,t,current)})
        rental=list(rental.values())
        for player in rental:player.update(type='RENTAL',rental_match_left=99,parameters=player['parameters'][:147])
        return {'squad_data':squad,'rental_team_id':t['player_team_id'],
                'rental_gameplayer_list':rental,'initial_settings':'YES',
                'liveupdate_version':self.document().get('live_data',{}).get('version',0)}

    def reinforcements(self,conn,t,current):
        """Native rental rows, with club identity scoped to this event only."""
        result=[]
        available={int(p['gameplayer_id']['id']):p for p in rewards.available(conn,self.document())[0]}
        for cid in rewards.rental_ids(current):
            card=available.get(cid)
            if card is None:continue
            player=copy.deepcopy(self.generator.rental_prepared(card,rules.seed_number(current['seed'],cid,'rental-reinforcement-booster')))
            player.update(gameplayer_id={'id':cid,'serial':0},type='RENTAL',rental_match_left=99,
                          initial_base_team_id=t['player_team_id'])
            nation=self.document().get('tournament_national_team_nations',{}).get(str(t['player_team_id']))
            if nation is not None:player.update(_nation_id=nation,initial_base_national_team_id=t['player_team_id'])
            player['parameters']=player['parameters'][:147]
            result.append(player)
        return result

    def player_pool(self,conn,t,active):
        """Borrowed team plus actual owned members of the represented team."""
        own=active[active['player_side'].lower()]
        from tournament_squads import authoritative_membership,membership_index
        document=self.document();index=membership_index(document)
        strict=index['native_ids']is not None
        fallback=own.get('_studio_tournament_squad',{}).get('fallback')or{}
        borrowed=set(fallback.get('added_standard_card_ids')or[])
        def member(p):
            return authoritative_membership(conn,document,p,t['player_team_id'],t.get('include_diy',True),index=index)
        # Old private rentals are not membership evidence. The immutable card
        # source must agree even when a cached outgoing row was painted with
        # the newly selected representative team's ID.
        pool={(p['gameplayer_id']['id'],p['gameplayer_id']['serial']):p for p in own['player_list']
              if not strict or p['gameplayer_id']['id']in borrowed or member(p)}
        if 'uuid'in t:
            current=get(conn,PREFIX+t['uuid'])
            if current:
                pool.update({(p['gameplayer_id']['id'],0):p for p in self.reinforcements(conn,t,current)})
        if not conn.execute("select 1 from sqlite_master where name='gameplayers'").fetchone():return pool
        import club_store
        for player in club_store.players(conn):
            if not member(player):continue
            wired=club_store.wire_player(copy.deepcopy(player));key=wired['gameplayer_id']
            if len(wired.get('parameters',[]))<147:continue
            pool[(key['id'],key['serial'])]=wired
        return pool

    def cached_roster_errors(self,conn,t,team,represented):
        """Validate private cached inputs against current authoritative sources."""
        from tournament_squads import membership_index,authoritative_membership
        document=self.document();index=membership_index(document)
        # Legacy fixtures with no source catalogue cannot be authoritatively
        # migrated. Every current game export supplies this native catalogue.
        if index['native_ids']is None:return[]
        rows=team.get('player_list')or[];keys=[];errors=[]
        fallback=team.get('_studio_tournament_squad',{}).get('fallback')or{}
        borrowed=set(fallback.get('added_standard_card_ids')or[])
        for row in rows:
            key=row.get('gameplayer_id')or{};cid=key.get('id');keys.append((cid,key.get('serial')))
            if cid not in borrowed and not authoritative_membership(conn,document,row,represented,t.get('include_diy',True),index=index):
                errors.append('foreign_or_unproven_card:'+str(cid))
        if len(keys)!=23 or len(set(keys))!=23:errors.append('incomplete_private_23')
        from tournament_identity import native_person_key
        people=[native_person_key(cid)if type(cid)is int else None for cid,_ in keys]
        if len(people)!=23 or len(set(people))!=23:errors.append('duplicate_private_person')
        refs=team.get('squad_data',{}).get('player_list')or[]
        referenced=[(r.get('gameplayer_id',{}).get('id'),r.get('gameplayer_id',{}).get('serial'))for r in refs]
        if len(referenced)!=23 or len(set(referenced))!=23 or set(referenced)!=set(keys):errors.append('private_reference_mismatch')
        return errors

    def remember_roster_repair(self,current,key,value,reasons):
        backups=current.setdefault('private_roster_repair_backups_v1',{})
        backups.setdefault(str(key),{'reasons':list(reasons),'original':copy.deepcopy(value)})
        current['plan_notice']='已修复本赛事旧比赛计划的球队或球员登记；赛程、积分、已完成比赛及球员培养均保留，请确认本场比赛计划。'
        logging.getLogger(__name__).warning('Tournament private roster repaired: %s %s',key,','.join(reasons))

    def repair_unissued_roster(self,conn,t,current,active,fixture):
        """Never replace an issued match; repair only proven bad private caches."""
        if active.get('started')or active.get('start_reply')or self.document().get('native_player_catalogue')is None:return
        contract=simulation_contract(current,fixture);player=t['player_team_id']
        for side in('home','away'):
            represented=fixture[side];old=active[side]
            errors=self.cached_roster_errors(conn,t,old,represented)
            if not errors:continue
            self.remember_roster_repair(current,str(active['game_id'])+':'+side,old,errors)
            import ziru_data
            rng=random.Random(rules.seed_number(contract['seeds']['lineup'],represented))
            rebuilt=self.generator.build_club(conn,ziru_data.vscom_opponent(),represented,t['include_diy'],rng,cpu=represented!=player)
            remaining=self.cached_roster_errors(conn,t,rebuilt,represented)
            if remaining:raise ValueError('锦标赛球队登记仍不完整，已保留原存档：'+','.join(remaining))
            rebuilt.update(game_id=active['game_id'],side=side.upper(),result='NOERR',cpu_level=rules.difficulty(current))
            bind_team_identity(rebuilt,represented,self.names());active[side]=rebuilt
            if not contract.get('frozen'):contract.setdefault('teams',{})[side]=copy.deepcopy(rebuilt)
            if represented==player:
                active.pop('own_plan',None);active.pop('last_legal_initial_plan',None)
                current.get('team_plans_v1',{}).pop(str(player),None)
        own=active[active['player_side'].lower()];plan=active.get('own_plan')
        if plan and self.document().get('native_player_catalogue'):
            pool=self.player_pool(conn,t,active)
            keys=[(r.get('gameplayer_id',{}).get('id'),r.get('gameplayer_id',{}).get('serial'))for r in plan.get('player_list',[])]
            from tournament_identity import native_person_key
            people=[native_person_key(cid)if type(cid)is int else None for cid,_ in keys]
            if len(keys)!=23 or len(set(keys))!=23 or len(set(people))!=23 or not set(keys)<=pool.keys():
                self.remember_roster_repair(current,str(active['game_id'])+':own_plan',plan,['foreign_or_incomplete_saved_plan'])
                active['own_plan']=copy.deepcopy(own['squad_data'])
                active.pop('last_legal_initial_plan',None)

    def save_plan(self,conn,t,current,request):
        patch=request.get('special_squad_data')
        if not isinstance(patch,dict)or not isinstance(patch.get('squad_data'),dict)or not patch['squad_data']:
            raise ValueError('锦标赛比赛计划缺少 squad_data')
        active=current.get('active')
        if not active or active.get('started')or active.get('start_reply'):
            # Native navigation may flush a dedicated-plan save after result
            # settlement. Never draw the next opponent from this save path.
            # In particular, a failed next-club generation must not trap the
            # client on the completed match's lineup screen.
            if active or current.get('receipts'):
                return {'result':'NOERR','studio_notice':'本场比赛计划已关闭，未改写阵容。'}
            raise ValueError('请先进入锦标赛并读取本场比赛计划')
        own=active[active['player_side'].lower()];squad=copy.deepcopy(active.get('own_plan')or own['squad_data'])
        sd=patch['squad_data']
        for key,kind in(('player_list',list),('coach',list),('squad_gameplan',dict)):
            if key in sd and not isinstance(sd[key],kind):raise ValueError('锦标赛比赛计划字段类型错误：'+key)
        pool=self.player_pool(conn,t,active);allowed=set(pool)
        if 'player_list'in sd:
            identities=[(p['gameplayer_id']['id'],p['gameplayer_id']['serial'])for p in sd['player_list']]
            from tournament_identity import native_person_key
            people=[native_person_key(key[0])for key in identities]
            if len(identities)!=23 or not set(identities)<=allowed or len(set(people))!=23:
                # Older native entry initialized its dedicated slot from the
                # user's main squad. A navigation save must not trap that
                # client in a network-error loop. Preserve the legal team;
                # the next entry reissues it and START always uses it.
                current['plan_notice']='本赛事仅可使用'+team_name(t['player_team_id'],self.names())+'队套；已保留本场合法阵容。'
                logging.getLogger(__name__).warning('Tournament plan ignored: stale/foreign roster; expected %s, received %s',len(allowed),len(identities))
                return {'result':'NOERR','studio_notice':current['plan_notice']}
        coach=None
        if 'coach'in sd:
            rows=sd['coach']
            if len(rows)!=1 or not isinstance(rows[0],dict):raise ValueError('锦标赛比赛计划需要一名已持有的教练')
            coach=next((c for c in self.generator.owned_coaches(conn)if c['payload']['coach_id']==rows[0].get('coach_id')),None)
            if coach is None:raise ValueError('锦标赛教练不在已持有名单中，请重新选择')
        # Native requests may only include changed settings. Preserve the
        # other formation, duties and options rather than replacing them.
        def merge(target,patch):
            for key,value in patch.items():
                if isinstance(value,dict)and isinstance(target.get(key),dict):merge(target[key],value)
                else:target[key]=copy.deepcopy(value)
        merge(squad,sd);squad['team_id']=t['player_team_id']
        order=squad['squad_gameplan']['match_plan_settings']['order']
        if not isinstance(order,list)or len(order)!=40 or any(type(i)is not int or i!=255 and not 0<=i<23 for i in order)or len(set(order[:23]))!=23 or 255 in order[:23]:
            raise ValueError('锦标赛比赛计划的首发替补顺序无效')
        if borrowed_standard_in_initial_xi(own,squad):
            current['plan_notice']=FALLBACK_BENCH_NOTICE
            logging.getLogger(__name__).warning('Tournament plan ignored: fallback Standard moved into initial XI; game=%s',active['game_id'])
            return {'result':'NOERR','studio_notice':FALLBACK_BENCH_NOTICE}
        active['own_plan']=squad
        self.repair_rentals(conn,current,active)
        if own.get('_studio_tournament_squad',{}).get('fallback'):
            active['last_legal_initial_plan']=copy.deepcopy(active['own_plan'])
        active.pop('start_reply',None);active.pop('start_contract',None)
        remember_plan(current,active)
        logging.getLogger(__name__).info('Tournament plan saved: game=%s team=%s coach=%s',active['game_id'],squad['team_id'],squad.get('coach'))
        return {'result':'NOERR'}

    def next_fixture(self,conn,current):
        if self.defer_remainder(conn,current):return None
        with self._cache_lock:ready=bool(self._round_cache)
        if ready:self._round_source_token=self.source_context(conn)
        def simulate(fixture):
            self.simulate_fixture(conn,current,fixture)
            if self.defer_remainder(conn,current):return False
        return next_fixture(current,simulate)

    def defer_remainder(self,conn,current):
        if current['completed']or not player_eliminated(current):return False
        path=self.database_path(conn)
        if not path:return False
        binding=remainder_binding(current)
        current.setdefault('cpu_remainder_v1',dict(binding=binding,status='pending',settled_cpu=0,error=None,attempts=0,retry_after=0))
        self.remember_remainder(path,binding)
        with self._cache_lock:
            self._prewarm_tokens[path]=('retired',current['run_id']);self._prewarm_pending.pop(path,None)
        return True

    def fixture_teams(self,conn,current,fixture,*,simulation_only=False):
        """Draw real club squads once, then share them with native entry."""
        contract=simulation_contract(current,fixture)
        if contract.get('teams'):return contract['teams']
        if self.generator is None:raise ValueError('锦标赛缺少真实球队组队器')
        import ziru_data
        proto=ziru_data.vscom_opponent();t=current['definition'];player=t['player_team_id']
        saved=current.get('team_plans_v1',{}).get(str(player))
        teams={}
        for physical,key in(('home','home'),('away','away')):
            team=fixture[key];own=team==player
            if own and saved and not self.cached_roster_errors(conn,t,saved['team'],team):value=copy.deepcopy(saved['team'])
            else:
                if own and saved:self.remember_roster_repair(current,'saved:'+str(team),saved,['foreign_or_incomplete_saved_team'])
                rng=random.Random(rules.seed_number(contract['seeds']['lineup'],team))
                options={'simulation_only':True}if simulation_only else{}
                value=self.generator.build_club(conn,proto,team,t['include_diy'],rng,cpu=not own,**options)
            bind_team_identity(value,team,self.names());teams[physical]=value
        contract['teams']=teams
        return teams

    def freeze_fixture(self,conn,current,fixture,active=None):
        """Freeze accepted game-plan abilities and their one-time effect inputs."""
        contract=simulation_contract(current,fixture)
        if contract.get('frozen')and(not active or active.get('started')or active.get('start_reply')):return contract
        cpu_only=active is None and current['definition']['player_team_id']not in(fixture['home'],fixture['away'])
        teams=self.fixture_teams(conn,current,fixture,simulation_only=cpu_only);snapshots={};ratings={}
        # A failed first START must not freeze an unissued plan. Publish its
        # contract only after the complete native reply has been validated.
        if active:contract=copy.deepcopy(contract)
        for physical in('home','away'):
            team=(active or{}).get(physical)or teams[physical];options={}
            if active and physical==active.get('player_side','HOME').lower():
                options=dict(squad=active.get('own_plan')or team['squad_data'],
                             player_pool=team['player_list']if active.get('started')or active.get('start_reply')
                             else self.player_pool(conn,current['definition'],active))
            snapshots[physical]=_strength_snapshot(team,self.generator,conn,**options)
            ratings[physical]=_team_ratings(snapshots[physical])
        forms={side:prior_form(current,fixture[side],fixture)for side in('home','away')}
        import tournament_simulation as simulation
        expected=simulation.expected_goals(ratings['home'],ratings['away'],neutral=bool(fixture.get('neutral')),
            form_home=forms['home'],form_away=forms['away'],model_version=contract['model_version'])
        contract.update(teams=snapshots,ratings=ratings,form=forms,frozen=True,
                        xg=expected['xg'],expected=expected,source='native'if active else'cpu')
        return contract

    def simulate_fixture(self,conn,current,fixture):
        """Rules own aggregate/away-goals decisions; the model only draws periods."""
        if fixture.get('played'):return
        with self._cache_lock:ready=bool(self._round_cache)
        key=self.round_cache_key(current,fixture)if ready else None
        with self._cache_lock:cached=self._round_cache.get(key)
        if cached is not None:
            fixture['simulation_v1']=copy.deepcopy(cached['simulation_v1'])
            rules.record(current,fixture['id'],*cached['score'],penalties=cached.get('penalties'),
                         extra=cached.get('extra_time_score',[0,0]))
            return
        import tournament_simulation as simulation
        contract=self.freeze_fixture(conn,current,fixture)
        options=dict(neutral=bool(fixture.get('neutral')),form_home=contract['form']['home'],
                     form_away=contract['form']['away'],model_version=contract['model_version'])
        home,away=contract['ratings']['home'],contract['ratings']['away']
        regulation=simulation.sample_period(home,away,seed=contract['seeds']['regulation'],**options)
        score=list(regulation['score']);extra=[0,0];et=None;pk=None
        if rules.needs_decision(current,fixture,score)and fixture.get('extra_time'):
            et=simulation.sample_period(home,away,seed=contract['seeds']['extra_time'],minutes=30,**options)
            extra=list(et['score']);score=[score[i]+extra[i]for i in range(2)]
        if rules.needs_decision(current,fixture,score,extra):
            pk=simulation.penalty_shootout(home,away,seed=contract['seeds']['penalties'],
                                          model_version=contract['model_version'])
        result=dict(regulation=regulation,extra_time=et,shootout=pk,raw_score=list(regulation['score']),
                    corrected_score=list(regulation['score']),final_score=score,extra_time_score=extra,
                    penalties=pk['score']if pk else None,correction='Dixon-Coles joint sampling; no post-draw score rewrite')
        rules.record(current,fixture['id'],*score,penalties=result['penalties'],extra=extra)
        contract.update(result=result,settled=True)

    def prepare(self,conn,t,current,request):
        f=self.next_fixture(conn,current)
        if f is None:raise ValueError('本届赛事已经结束，请重新报名')
        old=current.get('active')
        if old and old['fixture_id']==f['id']:
            if old.get('started')or old.get('start_reply'):
                # Issued native contracts survive re-entry byte-for-byte.
                return old
            self.repair_unissued_roster(conn,t,current,old,f)
            # Repair older cached fixtures without redrawing either club.
            for physical in('home','away'):
                old[physical].update(game_id=old['game_id'],side=physical.upper(),result='NOERR')
                if not old.get('started'):old[physical]['cpu_level']=rules.difficulty(current)
            if not old.get('started'):old['match_env']=match_environment(current,f)
            refresh_difficulty(t,old)
            if not old.get('started'):
                opponent=old['away']if old.get('player_side','HOME')=='HOME'else old['home']
                if self.generator.repair_cpu_boosters(opponent,rules.seed_number(current['seed'],f['id'],'cpu-boosters'),conn):
                    old.pop('start_reply',None);old.pop('start_contract',None)
            self.repair_rentals(conn,current,old)
            for physical in('home','away'):
                bind_team_identity(old[physical],old[physical]['_studio_tournament_squad']['team_id'],self.names())
            remember_plan(current,old)
            return old
        player=t['player_team_id'];side='HOME'if f['home']==player else'AWAY'
        saved=current.get('team_plans_v1',{}).get(str(player))
        teams=self.fixture_teams(conn,current,f)
        home=copy.deepcopy(teams['home']);away=copy.deepcopy(teams['away'])
        gid=700000000000000+rules.seed_number(current['run_id'],f['id'])%100000000000000
        for team,physical in((home,'HOME'),(away,'AWAY')):
            team.update(game_id=gid,cpu_level=rules.difficulty(current),side=physical,result='NOERR')
        active={'fixture_id':f['id'],'game_id':gid,'home':home,'away':away,'started':False,
                'match_env':match_environment(current,f),'player_side':side,'native_rules':native_rules(current,f)}
        if saved:active['own_plan']=copy.deepcopy(saved['squad'])
        current['active']=active
        self.repair_unissued_roster(conn,t,current,active,f)
        self.repair_rentals(conn,current,active)
        for physical in('home','away'):
            bind_team_identity(active[physical],active[physical]['_studio_tournament_squad']['team_id'],self.names())
        remember_plan(current,active)
        return active

    def repair_rentals(self,conn,current,active,entering=False):
        """Migrate an existing fixture without rerolling teams or owned cards."""
        if active.get('started')or active.get('start_reply'):return
        own=active[active.get('player_side','HOME').lower()];remap={};changed=False
        for p in own['player_list']:
            ident=p['gameplayer_id'];key=(ident['id'],ident['serial'])
            if ident['serial']!=0:
                remap[key]={'id':ident['id'],'serial':0};ident['serial']=0;changed=True
            p.update(type='RENTAL',rental_match_left=99)
        for plan in (own['squad_data'],active.get('own_plan')):
            if not plan:continue
            for row in plan['player_list']:
                ident=row['gameplayer_id'];new=remap.get((ident['id'],ident['serial']))
                if new:row['gameplayer_id']=new.copy()
        coaches=self.generator.owned_coaches(conn)
        selected=(active.get('own_plan')or own['squad_data']).get('coach',[])
        selected_id=selected[0].get('coach_id')if len(selected)==1 else own['coach_data']['coach_id']
        coach=next((c for c in coaches if c['payload']['coach_id']==selected_id),None)
        meta=own['_studio_tournament_squad'];style=meta['style']
        old_coach=own['coach_data']['coach_id'];old_style=style
        if coach is None:
            from tournament_squads import STYLES,STYLE_WIRE
            pairs=[(s,c)for s in (style,*[s for s in STYLES if s!=style])for c in coaches if c['payload'].get(s,0)>=85]
            if not pairs:raise ValueError('锦标赛租借阵容需要一名已持有且战术熟练度至少 85 的教练，请先在游戏中获得教练')
            style,coach=pairs[0];changed=True
            meta.update(style=style,coach_proficiency=coach['payload'][style])
            for plan in (own['squad_data'],active.get('own_plan')):
                if not plan:continue
                plan['coach']=[{'coach_id':coach['payload']['coach_id'].copy()}]
                for formation in plan['squad_gameplan']['formation']:formation['team_style']=STYLE_WIRE[style]
            for p in own['player_list']:
                p['disp_overall']=p['disp_max_overall']=self.generator.payload_rating(p['parameters'][:147],coach,style)
        from tournament_squads import STYLE_WIRE
        formations=(active.get('own_plan')or own['squad_data']).get('squad_gameplan',{}).get('formation',[])
        if formations:
            style=next((s for s,value in STYLE_WIRE.items()if value==formations[0].get('team_style')),style)
        if old_coach!=coach['payload']['coach_id']or old_style!=style:
            meta.update(style=style,coach_proficiency=coach['payload'].get(style,0))
            for p in own['player_list']:
                p['disp_overall']=p['disp_max_overall']=self.generator.payload_rating(p['parameters'][:147],coach,style)
        own['coach_data']=copy.deepcopy(coach['payload'])
        seed=rules.seed_number(current.get('seed',active['game_id']),active.get('fixture_id',''),'rental-boosters')
        boosters_changed=self.generator.repair_rental_boosters(own,seed,conn)
        if changed:
            active.pop('start_reply',None);active.pop('start_contract',None)
            logging.getLogger(__name__).info('Tournament cached rental squad repaired: game=%s identities=%s coach=%s',active['game_id'],len(remap),coach['payload']['coach_id'])
        elif boosters_changed:
            active.pop('start_contract',None)

    def activate_coaching(self,t,current,active):
        import ai_match_runtime
        opponent=active['away']if active.get('player_side','HOME')=='HOME'else active['home']
        spec=copy.deepcopy(opponent['_studio_tournament_squad']['tactical_spec'])
        spec.update(game_id=active['game_id'],entry_id='tournament:'+current['run_id']+':'+str(active['fixture_id']),
                    auto_coaching=t.get('auto_coaching',True),tournament_rules=active['native_rules'],
                    tournament_difficulty=active.get('match_env',{}).get('cpu_level',rules.difficulty(t)))
        native=active['native_rules'];cpu_home=active.get('player_side','HOME')=='AWAY'
        previous=native['prior_goals']
        spec['advancement']=dict(first_leg=native['first_leg'],second_leg=native['second_leg'],
            deciding=native['penalties'] or native['extra_time'],cpu_home=cpu_home,
            prior_score=list(previous if cpu_home else reversed(previous)),
            away_goals=native['away_goals'],away_goals_extra_time=native['away_goals_extra_time'],
            extra_time=native['extra_time'],penalties=native['penalties'])
        spec['native_identity']={'layout':'serial32-padding32-card64','cpu_serial':-3 if cpu_home else -2,'execution_verified':True,
            'source':'V17 tournament callback roster: HOME CPU -3; AWAY CPU -2'}
        try:status=ai_match_runtime.activate(spec,self.root)
        except Exception as exc:
            # A coaching-channel error must not undo an otherwise valid
            # native match, as with the main AI division bridge.
            ai_match_runtime.deactivate('tournament coaching configuration failed')
            status={'status':'unavailable','execution_enabled':False,'error':str(exc)}
            logging.getLogger(__name__).exception('Tournament coaching configuration failed')
        if isinstance(status,dict):active['coaching']=copy.deepcopy(status)
        logging.getLogger(__name__).info('Tournament AI handoff: game=%s team=%s roster=%s style=%s formation=%s automatic=%s channel=%s',
            active['game_id'],opponent['_studio_tournament_squad']['team_id'],len(spec['players']),
            spec['style'],spec['base_profile']['id'],spec['auto_coaching'],status)

    def start(self,logic,t,current,request):
        a=current.get('active')
        if not a and player_eliminated(current):raise ValueError('本届赛事已被淘汰，请重新报名')
        if not a or str(request.get('game_id'))!=str(a['game_id']):raise ValueError('比赛编号不属于当前赛事')
        side=a.get('player_side','HOME')
        if request.get('side',side)!=side:raise ValueError('赛事主客队通道不一致，请重新读取对手')
        refresh_difficulty(t,a)
        if a.get('start_reply'):
            # The persisted reply survives process exit, the native coaching
            # channel does not. Re-arm the same entry; configure is idempotent.
            out=copy.deepcopy(a['start_reply'])
            self.activate_coaching(t,current,a)
            return out
        if not a.get('started'):
            refresh_difficulty(t,a)
            refresh_match_time(t,a,current)
            self.repair_rentals(logic.conn,current,a,entering=True)
        notice=None
        if not a.get('started'):
            own=a[side.lower()]
            if borrowed_standard_in_initial_xi(own,a.get('own_plan')or own['squad_data']):
                retained=copy.deepcopy(a.get('last_legal_initial_plan')or own['squad_data'])
                current['plan_notice']=notice=FALLBACK_BENCH_NOTICE
                if borrowed_standard_in_initial_xi(own,retained):
                    return {'result':'NOERR','studio_notice':notice,'studio_start_blocked':True}
                a['own_plan']=retained
                self.repair_rentals(logic.conn,current,a)
                remember_plan(current,a)
                logging.getLogger(__name__).warning('Tournament START retained legal fallback XI; game=%s',a['game_id'])
        template=logic.responses.get('CMD_START_GAME')or logic.templates.get('CMD_START_GAME')
        if not isinstance(template,dict):raise ValueError('原生开赛模板缺失')
        fixture=next(f for f in current['fixtures']if f['id']==a['fixture_id'])
        if not a.get('started'):
            self.repair_unissued_roster(logic.conn,t,current,a,fixture)
            self.repair_rentals(logic.conn,current,a,entering=True)
        contract=self.freeze_fixture(logic.conn,current,fixture,a)
        out=copy.deepcopy(template);own=contract['teams'][side.lower()];squad=copy.deepcopy(own['squad_data'])
        players={(p['gameplayer_id']['id'],p['gameplayer_id']['serial']):p for p in own['player_list']}
        squad['player_list']=[{'gameplayer_id':r['gameplayer_id'].copy(),'parameters':players[(r['gameplayer_id']['id'],r['gameplayer_id']['serial'])]['parameters'][:147],'averaged_overall':0}for r in squad['player_list']]
        squad['coach']=copy.deepcopy(own['coach_data'])
        opponent=contract['teams']['away'if side=='HOME'else'home']
        cpu_squad=copy.deepcopy(opponent['squad_data'])
        # The native My League START contract sends full local-user rows,
        # but CPU references (including uniform_number) and a coach-ID list.
        # CPU abilities and its complete coach have already been supplied by
        # GET_VSCOM_OPPONENT; do not replace this with the user's wire shape.
        # These fields mean the local user and the CPU, respectively, even
        # when the local user is physically AWAY. Only kit fields follow
        # physical HOME/AWAY. This is the native My League START contract.
        out.update(result='NOERR',game_id=a['game_id'],squad_data_home=squad,squad_data_away=cpu_squad)
        from club_store import default_uniforms
        for key,team in(('uniform_list_home',a['home']['_studio_tournament_squad']['team_id']),('uniform_list_away',a['away']['_studio_tournament_squad']['team_id'])):
            uniform=out[key]
            if not isinstance(uniform,dict):raise ValueError('原生球衣字段格式改变')
            uniform.update(base_team_id=team,uniform_list=default_uniforms(team))
        order=squad['squad_gameplan']['match_plan_settings']['order']
        out.setdefault('commentary_info',{})['first_match_player_list']=[squad['player_list'][i]['gameplayer_id'].copy()for i in order[:11]]
        # The ordinary GateLogic finalizer refreshes these slots. Tournament
        # START bypasses that finalizer and must perform the same projection.
        import custom_stadium
        custom_stadium.apply(logic.conn,out)
        if notice:out['studio_notice']=notice
        fixture['simulation_v1']=contract
        a.update(started=True,start_contract=5,start_reply=copy.deepcopy(out))
        self.activate_coaching(t,current,a)
        return out

    def finish(self,logic,t,current,request):
        from ai_division_sessions import game_id
        gid=str(game_id(request));receipt=current.setdefault('receipts',{}).get(gid)
        if receipt:return copy.deepcopy(receipt)
        settled=self.settle_result(logic,t,current,request)
        out=self.result_reply(logic,t,current,request,settled)
        self.close_result(settled)
        return out

    def settle_result(self,logic,t,current,request):
        """Compute on a private state before opening the result write transaction."""
        from cup16_mode import _scores
        from ai_division_sessions import game_id
        gid=str(game_id(request))
        already_played={f['id']for f in current['fixtures']if f.get('played')}
        a=current.get('active')
        if not a or str(a['game_id'])!=gid or not a.get('started'):raise ValueError('结算没有对应已开始的比赛')
        # Native result requests keep score at the top level. match_result
        # contains game_id, player_data and pk_flag, not the score rows.
        match=request.get('match_result')or{};home,away=_scores(request)
        extra=[sum(r.get(k,0)for k in('score_ex1st','score_ex2nd'))for r in request['score']]
        f=next(f for f in current['fixtures']if f['id']==a['fixture_id']);penalties=None
        if match.get('pk_flag')=='YES':penalties=[r.get('score_pk',0)for r in request['score']]
        # Consume PK only when the aggregate (including away goals) needs it.
        needed=rules.needs_decision(current,f,[home,away],extra)
        before=promotion.capture(current)
        rules.record(current,f['id'],home,away,penalties=penalties if needed else None,extra=extra)
        contract=f.get('simulation_v1')
        if contract and contract.get('frozen'):
            regular=[home-extra[0],away-extra[1]]
            contract.update(settled=True,result=dict(raw_score=regular,corrected_score=regular,
                final_score=[home,away],extra_time_score=extra,penalties=penalties if needed else None,
                correction='native result; no simulated score substitution',source='native'))
        import vscom_result
        outcome=vscom_result.outcome(request,a.get('player_side','HOME'),home,away)
        # Keep the client's report distinct from our requested difficulty.
        # A missing native field is unknown, never proof that HARDEST ran.
        reported=match.get('game_use_cpu_level')
        current['last_match_diagnostic']={'game_id':a['game_id'],
            'requested_cpu_level':a.get('match_env',{}).get('cpu_level'),
            'native_reported_cpu_level':reported[:64]if isinstance(reported,str)else None}
        logging.getLogger(__name__).info('Tournament difficulty result: %s',current['last_match_diagnostic'])
        remember_plan(current,a)
        current.pop('active',None);self.next_fixture(logic.conn,current)
        settle_progression(current,before,gid)
        return dict(game_id=a['game_id'],player_side=a.get('player_side','HOME'),
                    home=home,away=away,outcome=outcome,
                    newly_settled_ids=[f['id']for f in current['fixtures']if f.get('played')and f['id']not in already_played])

    def result_reply(self,logic,t,current,request,settled):
        """Native rewards/statistics and the receipt share the caller's transaction."""
        import cup16_service
        # Constructing Cup16Service would initialize its unrelated mode.
        out=cup16_service.Cup16Service._result_reply(logic,request,dict(own_team_id=t['player_team_id']),
            settled['home'],settled['away'],settled['outcome'])
        out['game_end_result']['match_result']['player_data']['side']=settled['player_side']
        current.setdefault('receipts',{})[str(settled['game_id'])]=copy.deepcopy(out)
        return out

    def close_result(self,settled):
        import ai_match_runtime
        ai_match_runtime.deactivate_for_match(settled['game_id'],'custom tournament fixture finished')

    def handle(self,logic,command,request,original):
        definitions=self.definitions();conn=logic.conn
        self.resume_remainders(conn)
        from ai_division_sessions import routing,game_id,event_ids,is_division,match_owner,clear_tournament_context,CALLBACK_COMMANDS,OPPONENT_COMMANDS
        session=routing(logic)
        def native():
            response=original(logic,command,request)
            if isinstance(response,dict)and response.get('result')=='NOERR':
                identifiers=event_ids(request);category=request.get('match_category')
                if session.mode is None and session.selection is None:clear_tournament_context(conn)
                if command in EXITS:
                    clear_tournament_context(conn)
                    session.division()if command=='CMD_GET_LEAGUE_COM_INFO'else session.clear()
                    if command=='CMD_GET_LEAGUE_COM_INFO':self.entry_binding=None
                elif identifiers and command in('CMD_GET_EVENT_INFO','CMD_GET_EVENT_COMPE_INFO','CMD_SET_EVENT_ENTER','CMD_ENTER_EVENT_COMPE'):
                    clear_tournament_context(conn);session.clear();self.entry_binding=None
                elif command in OPPONENT_COMMANDS|{'CMD_START_GAME'}and(category or session.mode=='division'):
                    clear_tournament_context(conn)
                    session.division()if is_division(request)or session.mode=='division'else session.clear()
                    self.entry_binding=None
            return response
        import tournament_agents
        if command==tournament_agents.LIST:
            with conn:return tournament_agents.decorate(self,logic,original(logic,command,request))
        if command in tournament_agents.COMMANDS:
            with conn:
                response=tournament_agents.handle(self,logic,command,request,original)
                if response is not None:return response
        image=self.document().get('tournament_entry_image',ENTRY_IMAGE)
        if command=='CMD_GET_MAINMENU_MATCH_CREATIVE_INFO':return mainmenu(native(),image)
        if command in('CMD_GET_EVENT_LIST_AND_LOG','CMD_GET_EVENT_LIST_AND_INFO'):
            out=native()
            if not isinstance(out,dict)or out.get('result')!='NOERR':return out
            with conn:
                out=project_events(logic,out,definitions,image,self.names(),self.document().get('tournament_entry_images',{}).get('landscape'),self.overview_url(),self.document().get('tournament_national_team_nations',{}),self)
            self.resume_remainders(conn);return out
        if command in EXITS:return native()
        gid=game_id(request);identifiers=event_ids(request)
        explicit=identifiers[0]if identifiers else None
        t=next((t for t in definitions if any(str(eid)==str(event_id(t))for eid in identifiers)),None)
        if t is not None and any(str(eid)!=str(event_id(t))for eid in identifiers):
            raise ValueError('赛事编号互相冲突，未切换比赛模式')
        owner=match_owner(conn,gid)if gid is not None else None
        by_game=None;matched_state=None
        if gid is not None:
            for candidate in definitions:
                saved=get(conn,PREFIX+candidate['uuid'],{})
                if str(gid)==str((saved.get('active')or{}).get('game_id'))or str(gid)in saved.get('receipts',{}):
                    by_game=candidate;matched_state=saved;break
            if by_game is None:
                # Previous editions retain their exact receipts after a new
                # registration. This read-only callback never selects that run.
                for candidate in definitions:
                    rows=conn.execute('select value from meta where key like ? and value like ?',
                        (PREFIX+candidate['uuid']+':history:%','%"'+str(gid)+'":%'))
                    for raw, in rows:
                        saved=json.loads(raw)
                        if str(gid)in saved.get('receipts',{}):by_game=candidate;matched_state=saved;break
                    if by_game is not None:break
        if by_game is not None:
            if owner=='division':raise ValueError('比赛编号同时属于两个模式，未更改任何赛程')
            if identifiers and any(str(eid)!=str(event_id(by_game))for eid in identifiers):
                raise ValueError('比赛编号不属于所选赛事')
            if is_division(request):raise ValueError('锦标赛比赛编号不能用于 AI 组别')
            if request.get('match_category')and not str(request['match_category']).startswith('EVENT_'):
                raise ValueError('锦标赛比赛编号与比赛模式不符')
            if command in OPPONENT_COMMANDS:
                active=get(conn,PREFIX+by_game['uuid'],{}).get('active')or{}
                if str(active.get('game_id'))!=str(gid):raise ValueError('这场锦标赛已结束，请重新报名或进入下一场比赛')
            t=by_game
        elif gid is not None and t is not None:
            raise ValueError('比赛编号不属于所选锦标赛')
        elif command in CALLBACK_COMMANDS and t is not None:
            raise ValueError('开赛或结算没有对应的锦标赛比赛')
        elif owner=='tournament':raise ValueError('该锦标赛已不在当前活动目录，已保存进度保持原样')
        elif owner=='division':
            if identifiers:raise ValueError('AI 组别比赛编号不能用于锦标赛')
            return native()
        if is_division(request):
            if t is not None:raise ValueError('锦标赛赛事编号不能用于 AI 组别')
            return native()
        category=request.get('match_category')
        if t is None and not explicit and category and not str(category).startswith('EVENT_'):
            return native()
        context=session.selection
        if t is None and context and not explicit:
            candidate=next((t for t in definitions if t['uuid']==context),None)
            saved=get(conn,PREFIX+context,{})
            selected_commands=('CMD_GET_EVENT_INFO','CMD_GET_EVENT_COMPE_INFO','CMD_ENTER_EVENT_COMPE',
                               'CMD_GET_EVENT_MISSION_AI_MATCH_LIST','CMD_GET_EVENT_COMPE_TOURNAMENT_MATCH_LIST')
            entered_commands=OPPONENT_COMMANDS|{'CMD_SET_MYCLUB_SPECIAL_DREAM_SQUAD_INFO'}
            if candidate and(command in selected_commands or command in entered_commands and saved and session.matches(candidate,saved)):
                t=candidate
            elif command in CALLBACK_COMMANDS and session.mode=='tournament':
                raise ValueError('开赛或结算没有对应的锦标赛比赛')
        if t is None:
            return native()
        if command in('CMD_GET_VSCOM_GAME_RESULT','CMD_CHECK_GAME_RESULT'):
            receipt=(matched_state or{}).get('receipts',{}).get(str(gid))
            if receipt:
                # A successful durable settlement is authoritative. Retries do
                # not rewrite megabytes of state, advance CPU games or grant
                # native rewards again. CHECK uses the real saved result DTO.
                out=copy.deepcopy(receipt);out.update(msgid=command,rqid=request.get('rqid'))
                return out
            if command=='CMD_CHECK_GAME_RESULT':return native()
            # Preserve an existing wrapped transaction's ownership/rollback
            # semantics. Never COMMIT somebody else's work just to move CPU
            # calculation outside it, and never issue a nested BEGIN.
            inherited_transaction=conn.in_transaction
            if inherited_transaction:
                logging.getLogger(__name__).warning('Tournament result inherited an open transaction; retaining its atomic boundary')
            with conn if inherited_transaction else nullcontext():
                current=state(conn,t,persist=False);t=current['definition']
                settled=self.settle_result(logic,t,current,request)
                with conn:
                    if not conn.in_transaction:conn.execute('begin immediate')
                    out=self.result_reply(logic,t,current,request,settled)
                    compact_contracts(conn,current,settled.get('newly_settled_ids',[]))
                    put(conn,PREFIX+t['uuid'],current)
            self.close_result(settled)
            publish_saved_home(conn,definitions,self.names(),self.document().get('tournament_national_team_nations',{}))
            self.resume_remainders(conn)
            out.update(msgid=command,rqid=request.get('rqid'));return out
        if command=='CMD_GET_EVENT_COMPE_TOURNAMENT_MATCH_LIST':
            # Viewing a schedule is not entry/advance. In particular, do not
            # simulate CPU fixtures or reset a changed definition from here.
            current=get(conn,PREFIX+t['uuid'])
            matches=[{'home_team_id':f['home'],'away_team_id':f['away']or f['home']}
                     for f in current['fixtures']if f['stage']==current['stage_index']]if current else[]
            return dict(result='NOERR',msgid=command,rqid=request.get('rqid'),
                        compe_unit_id=event_id(t),match_count=len(matches),tournament_match_list=matches)
        pending_entry=None
        if command in('CMD_SET_EVENT_ENTER','CMD_ENTER_EVENT_COMPE'):self.entry_binding=None
        with conn:
            current=state(conn,t);t=current['definition']
            if command!='CMD_GET_VSCOM_GAME_RESULT':put(conn,CONTEXT,t['uuid'])
            out={'result':'NOERR'}
            if command in('CMD_SET_EVENT_ENTER','CMD_ENTER_EVENT_COMPE'):
                if current['completed']or player_eliminated(current):
                    put(conn,PREFIX+t['uuid']+':history:'+current['run_id'],current)
                    current=rules.start(t,random.SystemRandom().getrandbits(63))
                special=self.special(conn,t,current,request)
                fixture=next(f for f in current['fixtures']if f['id']==current['active']['fixture_id'])
                out.update(special_dream_squad_data=special,is_invalid='NO',event_account_type='GAME_PLAYER',
                           event_log=entry_log(current,fixture,self.entry_log_template,'ENTRY'))
                pending_entry=self.entry_key(current,fixture)
            elif command=='CMD_SET_MYCLUB_SPECIAL_DREAM_SQUAD_INFO':out=self.save_plan(conn,t,current,request)
            elif command in('CMD_GET_EVENT_INFO','CMD_GET_EVENT_COMPE_INFO'):
                template=copy.deepcopy(logic.responses.get(command)or logic.templates.get(command)or{})
                out=template;out.update(result='NOERR',event_id=event_id(t),compe_unit_id=event_id(t),description_text=summary(current,self.names()),rule_detail_text=summary(current,self.names()))
                active=current.get('active')or{}
                fixture=next((f for f in current['fixtures']if f['id']==active.get('fixture_id')),None)
                if fixture is None:
                    fixture=next((f for f in rules.due(current)if t['player_team_id']in(f['home'],f['away'])),None)
                out.setdefault('match_env',{}).update(match_environment(current,fixture))
            elif command=='CMD_GET_EVENT_MISSION_AI_MATCH_LIST':
                self.next_fixture(conn,current);out['match_list']=[{'team_id':f['away']if f['home']==t['player_team_id']else f['home'],'my_side':'HOME'if f['home']==t['player_team_id']else'AWAY'}for f in rules.due(current)if t['player_team_id']in(f['home'],f['away'])]
            elif command in('CMD_GET_VSCOM_OPPONENT','CMD_GET_MYCLUB_VSCOM_OPPONENT'):
                active=self.prepare(conn,t,current,request)
                out=copy.deepcopy(active['away']if active.get('player_side','HOME')=='HOME'else active['home']);out.pop('_studio_tournament_squad',None)
            elif command=='CMD_START_GAME':out=self.start(logic,t,current,request)
            else:return original(logic,command,request)
            put(conn,PREFIX+t['uuid'],current)
        publish_saved_home(conn,definitions,self.names(),self.document().get('tournament_national_team_nations',{}))
        # A failed database commit or homepage publication must not make a
        # later LIST claim the client received a special slot it never got.
        if pending_entry is not None:self.entry_binding=pending_entry
        self.resume_remainders(conn)
        if command in('CMD_SET_EVENT_ENTER','CMD_ENTER_EVENT_COMPE','CMD_START_GAME'):self.prewarm_round(conn,current)
        if command!='CMD_GET_VSCOM_GAME_RESULT':
            active=current.get('active')or{}
            fixture=next((f for f in current['fixtures']if f['id']==active.get('fixture_id')),None)
            entered=command in('CMD_SET_EVENT_ENTER','CMD_ENTER_EVENT_COMPE','CMD_START_GAME')or command in OPPONENT_COMMANDS or self.is_entered(current,fixture)
            session.select_tournament(t,current,entered=entered)
        out.update(msgid=command,rqid=request.get('rqid'));return out


def install(document,root,logic):
    if logic is None:return
    cls=type(logic);previous=cls.handle
    if getattr(previous,'_studio_tournaments',False):return
    import developed_preview,club_store,opponent_squad,ziru_data
    generator=ClubGenerator(document,developed_preview,club_store.wire_player,opponent_squad.external_caps,
                            opponent_squad.formation_for_roles,ziru_data.teams,ziru_data.normalize_opponent_team,root)
    service=Service(document,root,generator)
    from tournament_promotion_ui import configure as configure_promotion
    configure_promotion(service)
    from native_tournament_schedule_ui import configure as configure_schedule
    configure_schedule(service)
    from tournament_reward_ui import configure as configure_rewards
    configure_rewards(service)
    def handle(self,command,request):
        # Keep stale tournament chance IDs guarded after the last event has
        # been removed; they must never fall through to permanent grants.
        if not service.definitions()and command not in __import__('tournament_agents').COMMANDS|{__import__('tournament_agents').LIST,'CMD_START_GAME','CMD_GET_VSCOM_GAME_RESULT'}:
            return previous(self,command,request)
        with LOCK:
            try:return service.handle(self,command,request,previous)
            except (ValueError,KeyError,TypeError,IndexError)as exc:
                logging.getLogger(__name__).exception('Custom tournament request %s failed: %s',command,exc)
                return {'msgid':command,'rqid':request.get('rqid'),'result':'ERR_INVALID_PARAM','studio_error':str(exc)}
    handle._studio_tournaments=True;cls.handle=handle
