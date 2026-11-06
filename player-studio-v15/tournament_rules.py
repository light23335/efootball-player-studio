"""Portable tournament rules and deterministic fixtures, shared by editor/game.

No game globals, native calls, or third-party dependencies are used here.
Every result belongs to a fixture and is committed only once by its caller.
"""
import copy
import hashlib
import math
import random
import re
import uuid

FORMAT='player-studio-tournament'
TYPES=('groups','league','playoff','knockout')
SORTS=('points','goal_difference','goals_for','head_to_head','wins','seed')
MAX_TEAMS=128


def normalize_cover(value):
    """Portable cover design validation, also used by the game rules reader."""
    if value is None:return None
    if not isinstance(value,dict)or not re.fullmatch(r'[a-f0-9]{64}\.(?:png|jpg|jpeg|webp)',str(value.get('asset_id',''))):
        raise ValueError('锦标赛封面图片引用无效')
    out={'asset_id':value['asset_id']}
    for key,low,high,default in (('zoom',1,4,1),('x',-100,100,0),('y',-100,100,0)):
        number=value.get(key,default)
        if type(number)not in(int,float)or not math.isfinite(number)or not low<=number<=high:raise ValueError('锦标赛封面裁切参数超出范围')
        out[key]=number
    return out
DIFFICULTIES={'VERYEASY':'新手','EASY':'业余','NORMAL':'标准','HARD':'专业','VERYHARD':'顶尖','HARDEST':'超级球星','LEGEND':'传奇'}
LEGACY_LEVELS={10:'VERYEASY',9:'EASY',8:'EASY',7:'NORMAL',6:'HARD',5:'VERYHARD',4:'VERYHARD',3:'VERYHARD',2:'HARDEST',1:'LEGEND'}


def difficulty(value):
    level=value.get('difficulty') or LEGACY_LEVELS.get(value.get('division',10),'VERYEASY')
    if level not in DIFFICULTIES:raise ValueError('锦标赛游戏难度无效')
    return level

class State(dict):
    """Transient indexes are attributes, never part of the persisted save."""
    pass


def indexes(state):
    stamp=(id(state['fixtures']),len(state['fixtures']),state['stage_index'])
    cached=getattr(state,'fixture_index',None)
    if cached and cached['stamp']==stamp:return cached
    by_id={f['id']:f for f in state['fixtures']};ties={};rounds={}
    for f in state['fixtures']:
        if 'tie'in f:ties.setdefault(f['tie'],[]).append(f)
        if f['stage']==state['stage_index']:rounds.setdefault(f['round'],[]).append(f)
    cached={'stamp':stamp,'by_id':by_id,'ties':ties,'rounds':rounds,'ordered':sorted(rounds),'cursor':0}
    if isinstance(state,State):state.fixture_index=cached
    return cached


def integer(value,low,high,label):
    if type(value)is not int or not low<=value<=high:raise ValueError(label+f'应为 {low}–{high} 的整数')
    return value


def match_minutes(value):
    minutes=value.get('match_minutes',0)
    if type(minutes)is int and minutes==0:return 0
    return integer(minutes,3,30,'单场比赛时长（分钟）')


def uid(value=None):return str(uuid.UUID(value))if value else str(uuid.uuid4())


def stage(value,count):
    if not isinstance(value,dict):raise ValueError('赛事阶段格式不正确')
    s=copy.deepcopy(value);s['uuid']=uid(s.get('uuid'))
    kind=s.get('type','knockout')
    if kind not in TYPES:raise ValueError('未知赛事阶段')
    s['type']=kind;s['name']=str(s.get('name')or{'groups':'小组赛','league':'联赛阶段','playoff':'附加赛','knockout':'淘汰赛'}[kind])[:60]
    if kind in ('groups','league'):
        groups=integer(s.get('groups',1)if kind=='groups'else 1,1,count//2,'分组数')
        if count%groups:raise ValueError(s['name']+'：球队数量必须能按组数均分')
        size=count//groups;s['groups']=groups
        s['cycles']=integer(s.get('cycles',1),1,4,'循环次数')
        available=(size if size%2 else size-1)*s['cycles']
        s['rounds']=integer(s.get('rounds')or available,1,(size if size%2 else size-1)*s['cycles'],'比赛轮数')
        s['advance_per_group']=integer(s.get('advance_per_group',1),0,size,'每组直接晋级人数')
        s['playoff_per_group']=integer(s.get('playoff_per_group',0),0,size-s['advance_per_group'],'每组附加赛人数')
        for k,d in (('win_points',3),('draw_points',1),('loss_points',0)):
            s[k]=integer(s.get(k,d),0,10,'积分')
        s['tiebreakers']=list(s.get('tiebreakers')or SORTS)
        if len(set(s['tiebreakers']))!=len(s['tiebreakers'])or any(k not in SORTS for k in s['tiebreakers']):raise ValueError('同分排序项目无效或重复')
        if 'points'not in s['tiebreakers']:s['tiebreakers'].insert(0,'points')
        output=groups*(s['advance_per_group']+s['playoff_per_group'])
        if not output:raise ValueError(s['name']+'：至少设置一个晋级名额')
        s['direct_count']=groups*s['advance_per_group'];s['playoff_count']=groups*s['playoff_per_group']
    else:
        if count<2:raise ValueError(s['name']+'：至少需要两支球队')
        output=integer(s.get('advance',1 if kind=='knockout'else max(1,count//2)),1,count-1,'晋级队数')
        # A knockout reduces through complete rounds; arbitrary cuts require a league stage.
        power=1<<(count-1).bit_length();reachable=[]
        while power>1:power//=2;reachable.append(power)
        if output not in reachable:raise ValueError(s['name']+'：晋级队数必须能由完整淘汰轮次产生')
        s['advance']=output;s['legs']=integer(s.get('legs',1),1,2,'回合数')
        for key,default in (('away_goals',False),('away_goals_extra_time',False),('extra_time',True),('penalties',True),('neutral_final',True)):
            s[key]=s.get(key,default)
            if type(s[key])is not bool:raise ValueError(key+'必须为开关')
        if not s['penalties']:raise ValueError('淘汰赛必须允许点球决胜，避免无法晋级')
        overrides=s.get('round_overrides',{})
        if not isinstance(overrides,dict):raise ValueError('单轮例外格式错误')
        clean={}
        for name,options in overrides.items():
            if not str(name).isdigit()or int(name)<2 or int(name)&(int(name)-1):raise ValueError('单轮例外请按 32／16／8／4／2 强填写')
            if not isinstance(options,dict)or set(options)-{'legs','away_goals','away_goals_extra_time','extra_time','penalties','neutral'}:raise ValueError('单轮例外包含未知规则')
            row=dict(options)
            if 'legs'in row:integer(row['legs'],1,2,'例外回合数')
            for key,v in row.items():
                if key!='legs'and type(v)is not bool:raise ValueError('例外规则须为开关')
            if row.get('penalties')is False:raise ValueError('淘汰赛必须有最终决胜方式')
            clean[str(int(name))]=row
        s['round_overrides']=clean
    s['input_count']=count;s['output_count']=output
    return s


def normalize(value,allow_incomplete=False):
    if not isinstance(value,dict):raise ValueError('锦标赛须为对象')
    t=copy.deepcopy(value)
    if t.get('format',FORMAT)!=FORMAT or t.get('version',1)!=1:raise ValueError('锦标赛工程版本不支持')
    t.update(format=FORMAT,version=1,uuid=uid(t.get('uuid')))
    if 'cover'in t:t['cover']=normalize_cover(t['cover'])
    t['name']=str(t.get('name')or'').strip()[:80]
    if not t['name']and not allow_incomplete:raise ValueError('请填写锦标赛名称')
    for key,default in (('enabled',True),('include_diy',True),('auto_coaching',True)):
        t[key]=t.get(key,default)
        if type(t[key])is not bool:raise ValueError(key+'必须为开关')
    t['difficulty']=difficulty(t)
    t['match_minutes']=match_minutes(t)
    t.pop('division',None)
    teams=t.get('team_ids',[])
    if not isinstance(teams,list)or any(type(v)is not int or not 0<v<2**31 for v in teams):raise ValueError('球队编号无效')
    if len(teams)!=len(set(teams)):raise ValueError('参赛球队不能重复')
    if not 2<=len(teams)<=MAX_TEAMS and not allow_incomplete:raise ValueError(f'请选择 2–{MAX_TEAMS} 支参赛球队')
    t['team_ids']=teams
    player=t.get('player_team_id')or(teams[0]if teams else None)
    if player not in teams and not allow_incomplete:raise ValueError('玩家代表球队必须在参赛名单中')
    t['player_team_id']=player
    if not isinstance(t.get('stages'),list)or not t['stages']:
        if allow_incomplete:return t
        raise ValueError('请至少添加一个赛事阶段')
    count=len(teams);stages=[]
    if allow_incomplete and count<2:return t
    for raw in t['stages']:
        if stages and stages[-1].get('playoff_count',0):
            if raw.get('type')!='playoff':raise ValueError('设有附加赛名额时，下一阶段应为附加赛')
            # Direct entrants bypass this playoff and rejoin its winners.
            direct=stages[-1]['direct_count'];play=stages[-1]['playoff_count']
            current=stage(raw,play);current['bypass_count']=direct
            count=direct+current['output_count'];current['combined_output_count']=count
        else:
            current=stage(raw,count);count=current['output_count']
        stages.append(current)
    if count!=1:raise ValueError('最后阶段必须决出一名冠军，当前最终仍有 '+str(count)+' 支球队')
    if len({s['uuid']for s in stages})!=len(stages):raise ValueError('阶段身份重复')
    t['stages']=stages
    return t


def round_robin(teams,cycles=1,rounds=None):
    teams=list(teams)
    if len(teams)<2:raise ValueError('循环赛至少需要两支球队')
    if len(teams)%2:teams.append(None)
    n=len(teams);base=[]
    for r in range(n-1):
        games=[]
        for i in range(n//2):
            a,b=teams[i],teams[n-1-i]
            if r%2:a,b=b,a
            if a is not None and b is not None:games.append((a,b))
        base.append(games);teams=[teams[0],teams[-1],*teams[1:-1]]
    result=[]
    for cycle in range(cycles):result.extend([[(b,a)if cycle%2 else(a,b)for a,b in row]for row in base])
    return result[:rounds]if rounds is not None else result


def round_rules(s,count):
    rules={k:s.get(k)for k in('legs','away_goals','away_goals_extra_time','extra_time','penalties')}
    rules['neutral']=bool(count==2 and s.get('neutral_final') and rules['legs']==1)
    override=s.get('round_overrides',{}).get(str(count),{})
    rules.update(override)
    if 'neutral'not in override:rules['neutral']=bool(count==2 and s.get('neutral_final')and rules['legs']==1)
    if rules['legs']==1:rules['away_goals']=False;rules['away_goals_extra_time']=False
    return rules


def seed_number(*values):return int.from_bytes(hashlib.sha256('|'.join(map(str,values)).encode()).digest()[:8],'little')


def start(definition,seed,division=None):
    definition=normalize(definition);teams=list(definition['team_ids']);random.Random(seed).shuffle(teams)
    state=State({'version':1,'uuid':definition['uuid'],'run_id':str(uuid.uuid4()),'seed':seed,'definition':definition,
           'difficulty':difficulty(definition),'stage_index':0,'round':0,'entrants':teams,
           'fixtures':[],'completed':False,'champion':None,'bypass':[],'receipts':{},'stage_history':[]})
    enter_stage(state);return state


def fixture(state,home,away,**options):
    ident=len(state['fixtures'])+1
    row=dict(id=ident,stage=state['stage_index'],round=state['round'],home=home,away=away,
             played=False,score=None,extra_time_score=[0,0],penalties=None)
    row.update(options);return row


def enter_stage(state):
    s=state['definition']['stages'][state['stage_index']];teams=list(state['entrants'])
    state['round']=0
    if s['type']in('groups','league'):
        groups=[teams[i::s['groups']]for i in range(s['groups'])];state['groups']=groups
        for g,roster in enumerate(groups):
            for r,games in enumerate(round_robin(roster,s['cycles'],s['rounds'])):
                for home,away in games:state['fixtures'].append(fixture(state,home,away,round=r,group=g,legs=1,leg=1,neutral=False))
    else:
        state['groups']=[];enter_knockout_round(state,teams)


def enter_knockout_round(state,teams):
    s=state['definition']['stages'][state['stage_index']];n=1<<(len(teams)-1).bit_length()
    rules=round_rules(s,n);state['knockout_size']=n
    slots=list(teams)+[None]*(n-len(teams))
    # Give byes to the first seeded entrants; never create an empty-empty tie.
    pairs=[(slots[i],slots[n-1-i])for i in range(n//2)]
    for pair,(a,b)in enumerate(pairs):
        tie=f'{state["stage_index"]}:{state["round"]}:{pair}'
        if b is None:
            row=fixture(state,a,b,tie=tie,leg=1,**rules);row.update(played=True,score=[0,0],winner=a,bye=True)
            state['fixtures'].append(row);continue
        for leg in range(1,rules['legs']+1):
            home,away=(a,b)if leg==1 else(b,a)
            state['fixtures'].append(fixture(state,home,away,tie=tie,leg=leg,**rules))


def standings(state,group):
    s=state['definition']['stages'][state['stage_index']]
    stats={team:dict(team=team,points=0,played=0,wins=0,draws=0,losses=0,goals_for=0,goals_against=0,goal_difference=0,seed=i)for i,team in enumerate(state['groups'][group])}
    games=[f for f in state['fixtures']if f['stage']==state['stage_index']and f.get('group')==group and f['played']]
    for f in games:
        a,b=f['score']
        for tid,gf,ga in ((f['home'],a,b),(f['away'],b,a)):
            r=stats[tid];r['played']+=1;r['goals_for']+=gf;r['goals_against']+=ga;r['goal_difference']+=gf-ga
            key='wins'if gf>ga else'draws'if gf==ga else'losses';r[key]+=1
            r['points']+=s['win_points']if gf>ga else s['draw_points']if gf==ga else s['loss_points']
    # Mini-tables are calculated among teams tied on all preceding criteria.
    def resolve(rows,criteria):
        if len(rows)<2 or not criteria:return sorted(rows,key=lambda r:r['seed'])
        key,*rest=criteria
        if key=='head_to_head':
            ids={r['team']for r in rows};mini={tid:[0,0,0]for tid in ids}
            for f in games:
                if f['home']not in ids or f['away']not in ids:continue
                a,b=f['score']
                for tid,gf,ga in((f['home'],a,b),(f['away'],b,a)):
                    p=mini[tid];p[0]+=s['win_points']if gf>ga else s['draw_points']if gf==ga else s['loss_points'];p[1]+=gf-ga;p[2]+=gf
            value=lambda r:tuple(mini[r['team']])
        else:value=lambda r:-r['seed']if key=='seed'else r[key]
        buckets={}
        for row in rows:buckets.setdefault(value(row),[]).append(row)
        return [r for score in sorted(buckets,reverse=True)for r in resolve(buckets[score],rest)]
    return resolve(list(stats.values()),s['tiebreakers'])


def tie_winner(rows):
    rows=sorted(rows,key=lambda f:f['leg'])
    if any(not r['played']for r in rows):return None
    if rows[0].get('bye'):return rows[0]['winner']
    first,last=rows[0],rows[-1];teams=(first['home'],first['away']);total={t:0 for t in teams};away={t:0 for t in teams}
    for r in rows:
        for i,k in enumerate(('home','away')):total[r[k]]+=r['score'][i]
        extra=r.get('extra_time_score',[0,0])
        away[r['away']]+=r['score'][1]-(0 if r.get('away_goals_extra_time')else extra[1])
    if total[teams[0]]!=total[teams[1]]:return max(teams,key=total.get)
    if last['away_goals']and away[teams[0]]!=away[teams[1]]:return max(teams,key=away.get)
    p=last.get('penalties')
    if p and p[0]!=p[1]:return last['home']if p[0]>p[1]else last['away']
    return None


def due(state):
    index=indexes(state)
    while index['cursor']<len(index['ordered']):
        pending=[f for f in index['rounds'][index['ordered'][index['cursor']]]if not f['played']]
        if pending:
            if any(f.get('leg')==1 for f in pending):pending=[f for f in pending if f.get('leg')==1]
            return pending
        index['cursor']+=1
    return []


def needs_decision(state,f,score,extra=(0,0)):
    if 'tie'not in f:return False
    same=indexes(state)['ties'][f['tie']]
    if f['leg']!=f['legs']:return False
    trial=[dict(r,played=True,score=list(score),extra_time_score=list(extra),penalties=None)if r['id']==f['id']else r for r in same]
    return tie_winner(trial)is None


def record(state,fixture_id,home,away,penalties=None,extra=(0,0)):
    target=indexes(state)['by_id'].get(fixture_id)
    if target is None:raise ValueError('比赛不属于当前赛事')
    score=[integer(home,0,99,'进球'),integer(away,0,99,'进球')]
    if target['played']:
        if target['score']==score and target.get('penalties')==(list(penalties) if penalties is not None else None):return False
        raise ValueError('比赛已经结算，不能覆盖旧结果')
    if state['completed']:raise ValueError('本届赛事已经结束')
    if target not in due(state):raise ValueError('比赛尚未到可结算轮次')
    if not isinstance(extra,(list,tuple))or len(extra)!=2:raise ValueError('加时比分格式错误')
    extra=[integer(v,0,score[i],'加时进球')for i,v in enumerate(extra)]
    decisive=needs_decision(state,target,score,extra)
    if penalties is not None:
        if not decisive:raise ValueError('本场不应进行点球决胜')
        if not isinstance(penalties,(list,tuple))or len(penalties)!=2 or penalties[0]==penalties[1]:raise ValueError('点球赛必须决出胜负')
        penalties=[integer(v,0,99,'点球进球')for v in penalties]
    if decisive and penalties is None:raise ValueError('本轮总比分相同，需要点球结果')
    target.update(played=True,score=score,penalties=penalties,extra_time_score=extra)
    advance(state);return True


def advance(state):
    s=state['definition']['stages'][state['stage_index']]
    if due(state):return
    if s['type']in('groups','league'):
        direct=[];play=[];tables=[]
        for g in range(s['groups']):
            table=standings(state,g);tables.append(table)
            direct.extend(r['team']for r in table[:s['advance_per_group']])
            play.extend(r['team']for r in table[s['advance_per_group']:s['advance_per_group']+s['playoff_per_group']])
        state['stage_history'].append({'stage':state['stage_index'],'tables':tables})
        if play:state['bypass']=direct;winners=play
        else:winners=direct
    else:
        rows=[f for f in state['fixtures']if f['stage']==state['stage_index']and f['round']==state['round']]
        ties={f['tie']for f in rows};winners=[tie_winner([f for f in rows if f['tie']==key])for key in sorted(ties)]
        if any(v is None for v in winners):raise ValueError('淘汰赛有未决出的胜者')
        if len(winners)>s['output_count']:
            state['round']+=1;enter_knockout_round(state,winners);advance(state);return
        if s.get('bypass_count'):winners=state['bypass']+winners;state['bypass']=[]
    if state['stage_index']+1==len(state['definition']['stages']):
        if len(winners)!=1:raise ValueError('最终冠军人数异常')
        state.update(completed=True,champion=winners[0]);return
    state['stage_index']+=1;state['entrants']=winners;enter_stage(state);advance(state)


def preview(value):
    definition=normalize(value);state=start(definition,0);count=0;player=definition['player_team_id'];played=0
    while not state['completed']:
        pending=due(state)
        if not pending:advance(state);continue
        f=pending[0];count+=1;played+=int(player in (f['home'],f['away']))
        # Keep the representative alive to count its maximum path.
        score=(1,0)if f['home']==player or f['away']!=player else(0,1)
        penalty=[5,4]if f['home']==player or f['away']!=player else[4,5]
        record(state,f['id'],*score,penalties=penalty if needs_decision(state,f,score)else None)
        if count>100000:raise ValueError('赛程规模过大')
    return {'teams':len(definition['team_ids']),'matches':count,'player_matches':played,
            'stages':[{'name':s['name'],'type':s['type'],'input':s['input_count'],'output':s.get('combined_output_count',s['output_count'])}for s in definition['stages']]}
