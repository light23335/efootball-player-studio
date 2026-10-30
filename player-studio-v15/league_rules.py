"""V17 offline league policy. Settlement keeps native history and receipts.

The exact official rating formula and a complete official lower-division table
are not shipped in the supplied offline APK. Lower bands retain its published
offline thresholds except D10 (native capture) and D4 (requested 23 points).
Those fallback values must never be advertised as verified KONAMI rules.
"""
import copy
import hashlib
import json
import uuid

REVISION='studio-league-v4'
FLOORS={3:1200,2:1500,1:1800}
PROMOTION={10:3,9:13,8:15,7:16,6:17,5:18,4:23}
STAYING={10:0,9:4,8:4,7:4,6:4,5:4,4:4}
ROUND_GAMES=10
PROCESS_TOKEN=uuid.uuid4().hex


def initial_points(division):return FLOORS.get(division,0)
def threshold(division):return {3:1500,2:1800,1:1800}.get(division,PROMOTION.get(division,0))
def quota(division):return ROUND_GAMES if division>=4 else 0


def load_state(raw):
    s=json.loads(raw) if raw else dict(division=10,best=10,points=0,matches=0,wins=0,draws=0,losses=0,round=1)
    # Reading or upgrading never resets points, W/D/L or the active round.
    if s['division']<=3:s['points']=max(FLOORS[s['division']],s['points'])
    return s


def transition(s,early=False):
    d,p=s['division'],s['points']
    if d<=3:
        if early:return None  # Skip never promotes a rated division.
        if d>1 and p>=threshold(d):return d-1,'PROMOTED'
        return None
    if not s['matches']:return None
    remaining=max(0,ROUND_GAMES-s['matches'])
    if s['matches']>=ROUND_GAMES or early:
        if p>=PROMOTION[d]:return d-1,'PROMOTED'
        if p+remaining*3<STAYING[d]:return min(10,d+1),'RELEGATED' if d<10 else 'STAYING'
        if not remaining or early and p>=STAYING[d] and p+remaining*3<PROMOTION[d]:return d,'STAYING'
    return None


def advance(s,result,delta=None):
    old=s['division'];before=s['points']
    change=({'WIN':3,'DRAW':1,'LOSE':0}[result] if old>=4 else delta)
    s['points']+=change
    if old<=3:s['points']=max(FLOORS[old],s['points'])
    s['matches']+=1;s[{'WIN':'wins','DRAW':'draws','LOSE':'losses'}[result]]+=1
    completed=copy.deepcopy(s);step=transition(s)
    outcome=''
    if step:
        d,outcome=step;reset(s,d,s['points'] if old<=3 else None)
    return completed,outcome,completed['points']-before


def reset(s,division,points=None):
    s.update(division=division,best=min(s.get('best',10),division),
             points=initial_points(division) if points is None else points,
             matches=0,wins=0,draws=0,losses=0,round=s['round']+1)


def opponent_rating(active):
    opponent=active.get('opponent') or {};marker=opponent.get('_studio_division_squad_v1') or {}
    strength=marker.get('native_lower_bound_strength')
    if type(strength) is int and 1000<=strength<=5000:
        return round(max(1000,min(2400,1200+(strength-3200)*2)))
    # Legacy/original opponents may have no verified strength metadata.
    return {1:1800,2:1650,3:1400}.get(active.get('division'),1200)


def rating_delta(rating,frozen_opponent,result):
    expected=1/(1+10**(max(-1600,min(1600,frozen_opponent-rating))/400))
    return round(48*({'WIN':1,'DRAW':.5,'LOSE':0}[result]-expected))


def install():
    import ai_division as ai
    if getattr(ai,'_studio_league_rules',False):return
    store=ai.store;old_view=ai.view;old_rules=ai.rules;old_start=ai.start
    ai.RATING_START=FLOORS.copy();ai.RATING_FLOOR=FLOORS.copy()
    ai.initial_points=initial_points;ai.threshold=threshold;ai.quota=quota;ai._reset=reset
    ai.state=lambda conn:load_state(store.get_meta(conn,ai.STATE_KEY,''))
    def rules():
        out=old_rules();out.update(schema=REVISION,matches_per_division={str(d):quota(d) for d in range(1,11)},
            promotion_points={str(d):threshold(d) for d in range(1,11)},rating_start=FLOORS.copy(),rating_floor=FLOORS.copy(),
            staying_points={str(d):v for d,v in STAYING.items()},
            rating_formula='offline Elo approximation (K=48), not the official formula',
            lower_threshold_evidence='D10 native capture; D4 requested 23; other promotion thresholds from supplied offline table; staying fallback from offline service')
        return out
    ai.rules=rules
    def view(template,s,outcome='',pre_rating=None,match_history=None):
        out=old_view(template,s,outcome,pre_rating,match_history)
        d=s['division'];stay=FLOORS[d] if d<=3 else STAYING[d]
        out.update(point_promoted=threshold(d),point_staying=stay,
                   point_relegated=stay if d<=3 else max(0,stay-1),
                   can_skip='YES' if transition(s,True) else 'NO')
        return out
    ai.view=view
    def start(conn,req,*args,**kwargs):
        result=old_start(conn,req,*args,**kwargs)
        # The roster is already frozen by the generator before START arrives.
        active=json.loads(store.get_meta(conn,'ai_division_active_match','null'))
        if active and active.get('started') and '_studio_rating_opponent' not in active:
            with conn:
                active['_studio_rating_opponent']=opponent_rating(active)
                store.set_meta(conn,'ai_division_active_match',json.dumps(active))
        return result
    ai.start=start
    def finish(conn,resp,req):
        mid='CMD_GET_VSCOM_GAME_RESULT';mr=req.get('match_result') or {};gid=mr.get('game_id',req.get('game_id'))
        key='ai_division_result_'+str(gid)
        invalid=lambda:{'msgid':mid,'rqid':req.get('rqid'),'result':'ERR_INVALID_PARAM'}
        def replay(raw):
            out=json.loads(raw);out['rqid']=req.get('rqid');return ai._refresh_phase(out)
        cached=store.get_meta(conn,key,'') if gid else ''
        if cached:return replay(cached)
        active=json.loads(store.get_meta(conn,'ai_division_active_match','null'))
        if not active or gid!=active['game_id']:return invalid() if ai.is_league(req) else resp
        try:
            if not active.get('started'):return invalid()
            home,away=ai._scores(req);result=ai.vscom_result.outcome(req,active['side'],home,away)
            ai._begin(conn)
            try:
                cached=store.get_meta(conn,key,'')
                if cached:conn.rollback();return replay(cached)
                current=json.loads(store.get_meta(conn,'ai_division_active_match','null'))
                if not current or current['game_id']!=gid:raise ValueError('active match changed')
                s=ai.state(conn)
                if current['round']!=s['round']:raise ValueError('stale round')
                if 'history_own' not in current:current['history_own']=ai.division_history.own_snapshot(conn,current.get('user_id',req.get('user_id',0)))
                current['history_cpu_level']=(current.get('opponent') or {}).get('cpu_level') or ai.LEVELS[current['division']]
                pre=s['points'] if s['division']<=3 else 0
                frozen=current.get('_studio_rating_opponent',opponent_rating(current))
                completed,outcome,points=advance(s,result,rating_delta(pre,frozen,result))
                ai.save(conn,s);ai.division_history.record(conn,current,req,result)
                out=ai._result_response(resp,req,s,outcome,home,away,result,pre,current['side'],ai.division_history.records(conn,s['round']))
                ai.player_match_stats.record(conn,req,gid)
                store.set_meta(conn,key,json.dumps(out));store.set_meta(conn,'ai_division_active_match','null')
                store.log_event(conn,'ai_division_result',{'game_id':gid,'result':result,'points_added':points,
                    'completed_round':completed,'outcome':outcome,'state':s,'rating_algorithm':REVISION,
                    'opponent_rating':frozen})
                conn.commit();return out
            except Exception:conn.rollback();raise
        except (ValueError,TypeError):return invalid()
    ai.finish=finish
    def skip(conn,resp,req):
        invalid={'msgid':'CMD_SKIP_LEAGUE_COM_DIVISION','rqid':req.get('rqid'),'result':'ERR_INVALID_PARAM'}
        identity=[req.get('user_id',0),req.get('session_id') or PROCESS_TOKEN,req.get('rqid')]
        key='studio_league_skip_v4_'+hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        ai._begin(conn)
        try:
            cached=store.get_meta(conn,key,'')
            if cached:conn.rollback();return json.loads(cached)
            active=json.loads(store.get_meta(conn,'ai_division_active_match','null'))
            s=ai.state(conn);step=transition(s,True)
            if not step or active and active.get('started') is not False:conn.rollback();return invalid
            old=s['division'];d,outcome=step;reset(s,d);ai.save(conn,s)
            if active:store.set_meta(conn,'ai_division_active_match','null')
            resp['league_info']=view(resp.get('league_info'),s,outcome,match_history=ai.division_history.records(conn,s['round']))
            resp['result']='NOERR';store.set_meta(conn,key,json.dumps(resp))
            store.log_event(conn,'ai_division_skip',{'from':old,'to':d,'outcome':outcome})
            conn.commit();return resp
        except Exception:conn.rollback();raise
    ai.skip=skip;ai._studio_league_rules=True
