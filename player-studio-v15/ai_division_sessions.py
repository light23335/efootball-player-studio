"""Explicit pre-match entry rounds and transactional style rotation.

The native game identifier is renewed per entry as well as our private entry
UUID. Original start/result requests already carry that identifier; this lets
the bridge reject late callbacks without adding an unrecognized wire field.
No timer or changing request number is used to infer a new entry.
"""
import copy
import json
import secrets
import time
import uuid

STYLES = ('possession','short_counter','long_counter','side_attack','long_ball','overload')
DRAW_KEY = 'personal_ai_division_draw_v2'
ENTRY_KEY = 'personal_ai_division_entry_v1'
MARKER = '_studio_division_squad_v1'
# Original V17 GateLogic explicitly serves these menu/list flows outside the
# match. Do not include keep-alive, roster views, history or quality requests.
EXIT_COMMANDS = frozenset(('CMD_GET_MAINMENU_INFO','CMD_GET_MYCLUB_MAINMENU_INFO',
                          'CMD_GET_MAINMENU_MATCH_CREATIVE_INFO','CMD_GET_LEAGUE_COM_INFO',
                          'CMD_GET_MYCLUB_MAIN_MENU','CMD_GET_MYCLUB_HOME',
                          'CMD_GET_EVENT_LIST_AND_LOG','CMD_GET_EVENT_LIST_AND_INFO'))
OPPONENT_COMMANDS=frozenset(('CMD_GET_VSCOM_OPPONENT','CMD_GET_MYCLUB_VSCOM_OPPONENT'))
CALLBACK_COMMANDS=frozenset(('CMD_START_GAME','CMD_GET_VSCOM_GAME_RESULT'))
TOURNAMENT_CONTEXT='player_studio_tournament_v1:context'


class Routing:
    """One live gateway's selected mode; saved competitions are not sessions."""
    def __init__(self):
        self.mode=None
        self.tournament=None
        self.selection=None

    def clear(self):
        self.mode=None;self.tournament=None;self.selection=None

    def division(self):
        self.clear();self.mode='division'

    def select_tournament(self,definition,current,entered=False):
        self.selection=definition['uuid']
        if entered:
            self.mode='tournament'
            self.tournament=(definition['uuid'],current['run_id'],definition['player_team_id'])
        else:self.mode=None;self.tournament=None

    def matches(self,definition,current):
        return self.mode=='tournament'and self.tournament==(
            definition['uuid'],current['run_id'],current['definition']['player_team_id'])


def routing(logic):
    value=getattr(logic,'_studio_match_routing',None)
    if value is None:
        value=Routing();logic._studio_match_routing=value
    return value


def game_id(request):
    """Native results nest the ID; reject conflicting top-level identities."""
    values=[]
    nested=request.get('match_result')
    for value in(request.get('game_id'),nested.get('game_id')if isinstance(nested,dict)else None):
        if value is not None and str(value)not in('','0'):values.append(value)
    if len({str(v)for v in values})>1:raise ValueError('比赛编号互相冲突，请重新进入对应模式')
    return values[-1]if values else None


def event_ids(request):
    return [request[key]for key in('event_id','compe_unit_id')
            if request.get(key)is not None and str(request[key])not in('','0')]


def is_division(request):return str(request.get('match_category')or'').startswith('LEAGUE_COM')


def match_owner(conn,gid):
    """Resolve explicit callback IDs without consulting either selected mode."""
    if gid is None:return None
    owners=set();active=read(conn,'ai_division_active_match',{})or{}
    if str(active.get('game_id'))==str(gid)or read(conn,'ai_division_result_'+str(gid)):
        owners.add('division')
    exists=conn.execute("select 1 from sqlite_master where name='personal_ai_entries'").fetchone()
    if exists and conn.execute('select 1 from personal_ai_entries where game_id=?',(str(gid),)).fetchone():
        owners.add('division')
    prefix='player_studio_tournament_v1:'
    # Archived editions can hold thousands of full simulation snapshots.
    # They never own a live route; filter their keys before fetching/decoding
    # the large values. Exact historical receipts are resolved separately.
    for key,raw in conn.execute('select key,value from meta where key like ? and key not like ? and key not like ?',
                                (prefix+'%','%:history:%','%:backup:%')):
        try:value=json.loads(raw)
        except(ValueError,TypeError):continue
        if not isinstance(value,dict)or not isinstance(value.get('definition'),dict):continue
        uid=value['definition'].get('uuid')
        if key!=prefix+str(uid):continue  # Backups/history never become live routes.
        if str((value.get('active')or{}).get('game_id'))==str(gid)or str(gid)in value.get('receipts',{}):
            owners.add('tournament')
    if len(owners)>1:raise ValueError('比赛编号同时属于两个模式，未更改任何赛程')
    return next(iter(owners),None)


def clear_tournament_context(conn):
    with conn:
        conn.execute('update meta set value=? where key=?',('null',TOURNAMENT_CONTEXT))


def invalid_reply(command,request,error):
    return {'msgid':command,'rqid':request.get('rqid'),'result':'ERR_INVALID_PARAM','studio_error':str(error)}


def read(conn,key,default=None):
    row=conn.execute('select value from meta where key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(default)


def write(conn,key,value):
    conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',
                 (key,json.dumps(value,ensure_ascii=False,separators=(',',':'))))


def preview_draw(state,rng,mode='shuffle_bag'):
    """Pure proposed consumption; only a committed opponent consumes a style."""
    out=copy.deepcopy(state or {})
    bag=list(out.get('bag',[]))
    if len(bag)!=len(set(bag)) or any(s not in STYLES for s in bag):
        raise ValueError('AI style rotation state is invalid; original state preserved')
    if mode=='independent':
        style=rng.choice(STYLES)
    elif mode=='shuffle_bag':
        if not bag:
            bag=list(STYLES);rng.shuffle(bag)
            if bag[0]==out.get('last_style'):
                bag[0],bag[1]=bag[1],bag[0]
        style=bag.pop(0)
    else:
        raise ValueError('Unknown AI style rotation mode')
    out.update(bag=bag,last_style=style,style_mode=mode,draw_sequence=out.get('draw_sequence',0)+1)
    return style,out


def preview_formation(state,rng):
    """20 successful entries: 14 four, 4 three, 2 five; no retry consumption.

    Construct the whole remaining bag, including the cross-round history,
    rather than greedily consuming entries and getting stuck at its tail.
    """
    out=copy.deepcopy(state or {});bag=list(out.get('formation_bag',[]))
    history=list(out.get('formation_history',[]))[-2:]
    if any(n not in (3,4,5) for n in bag+history) or any(bag.count(n)>limit for n,limit in ((4,14),(3,4),(5,2))):
        raise ValueError('AI formation rotation state is invalid; state retained')
    def allowed(n,previous):
        return not(n==5 and previous and previous[-1]==5) and not(n!=4 and len(previous)>=2 and all(v!=4 for v in previous[-2:]))
    if not bag:
        for _ in range(512):
            proposed=[4]*14+[3]*4+[5]*2;rng.shuffle(proposed);previous=list(history)
            for n in proposed:
                if not allowed(n,previous):break
                previous=(previous+[n])[-2:]
            else:bag=proposed;break
        else:raise ValueError('Cannot shuffle a legal AI formation rotation; saved state retained')
    selected=bag.pop(0)
    if not allowed(selected,history):raise ValueError('AI formation history disagrees with its bag')
    out.update(formation_bag=bag,formation_history=(history+[selected])[-2:])
    return selected,out


class Entries:
    def __init__(self,process_id=None):
        self.process_id=process_id or secrets.token_hex(16)

    def schema(self,conn):
        # Caller owns the transaction. No executescript: it implicitly commits.
        conn.execute('create table if not exists personal_ai_entries('
                     'entry_id text primary key, game_id text unique not null, base_game_id text,'
                     'draw_sequence integer not null, side text not null, report text not null)')
        conn.execute('create table if not exists personal_ai_events('
                     'event_id integer primary key,entry_id text not null,event text not null,payload text not null)')

    def current(self,conn):return read(conn,ENTRY_KEY,{})

    def reusable(self,conn,active):
        entry=self.current(conn)
        marker=(active or {}).get('opponent',{}).get(MARKER,{})
        return bool(entry and not entry.get('closed') and entry.get('process_id')==self.process_id
                    and str(entry.get('game_id'))==str((active or {}).get('game_id'))
                    and marker.get('entry_id')==entry['entry_id'])

    def recover_committed_entry(self,conn,active):
        """Index a native prepare committed before our post-commit bookkeeping.

        A newer process starting a pre-match flow still draws a new round. An
        explicitly closed entry is never reopened by this recovery path.
        """
        marker=(active or {}).get('opponent',{}).get(MARKER,{})
        current=self.current(conn)
        if marker.get('process_id')!=self.process_id or not marker.get('entry_id'):return False
        if current.get('entry_id')==marker['entry_id']:return False
        after=marker.get('draw_state_after',{})
        if after.get('draw_sequence',0)<=current.get('draw_state_after',{}).get('draw_sequence',0):return False
        entry={'entry_id':marker['entry_id'],'process_id':self.process_id,'game_id':active['game_id'],
               'base_game_id':marker.get('base_game_id'),'side':'AWAY','closed':False,
               'started':bool(active.get('started')),'style':marker['style'],'draw_state_after':after}
        with conn:
            conn.execute('begin immediate');self.commit(conn,entry,marker)
            self.event(conn,entry['entry_id'],'entry_index_recovered',{})
        return True

    def draw(self,conn,active,rng,mode):
        state=read(conn,DRAW_KEY,{})
        # Recover an original prepare committed just before a process failure
        # in our post-commit indexing. The draw state travels in that snapshot.
        marker=(active or {}).get('opponent',{}).get(MARKER,{})
        pending=marker.get('draw_state_after',{})
        if pending.get('draw_sequence',0)>state.get('draw_sequence',0):state=pending
        style,after=preview_draw(state,rng,mode)
        formation_type,after=preview_formation(after,rng)
        entry_id=uuid.uuid4().hex
        return {'entry_id':entry_id,'process_id':self.process_id,'side':'AWAY',
                'base_game_id':(active or {}).get('game_id'),'style':style,'formation_type':formation_type,'draw_state_after':after,
                'previous_starters':state.get('last_starters',[]),'previous_formation':state.get('last_formation'),
                'closed':False,'started':False}

    def replace_active(self,conn,active,opponent,entry):
        """Stage replacement, draw state and new callback ID in one transaction."""
        if not conn.in_transaction:raise ValueError('Entry replacement requires a transaction')
        previous=copy.deepcopy(active)
        sequence=max(int(time.time()*1_000_000),int(read(conn,'ai_division_game_sequence',0))+1)
        active=copy.deepcopy(active);active.update(game_id=sequence,opponent=copy.deepcopy(opponent),started=False)
        active.pop('history_own',None)
        entry.update(game_id=sequence)
        write(conn,'ai_division_game_sequence',sequence)
        write(conn,'ai_division_active_match',active)
        self.commit(conn,entry,opponent[MARKER])
        self.event(conn,entry['entry_id'],'previous_entry_replaced',{'previous_game_id':previous.get('game_id')})
        return active

    def commit(self,conn,entry,report):
        if not conn.in_transaction:raise ValueError('Entry commit requires a transaction')
        self.schema(conn)
        write(conn,DRAW_KEY,entry['draw_state_after'])
        write(conn,ENTRY_KEY,entry)
        conn.execute('insert into personal_ai_entries values(?,?,?,?,?,?) on conflict(entry_id) do update set report=excluded.report',
                     (entry['entry_id'],str(entry['game_id']),str(entry.get('base_game_id') or ''),
                      entry['draw_state_after']['draw_sequence'],entry['side'],
                      json.dumps({k:v for k,v in report.items()if k!='tactical_spec'},ensure_ascii=False,separators=(',',':'))))

    def event(self,conn,entry_id,event,payload):
        self.schema(conn)
        conn.execute('insert into personal_ai_events(entry_id,event,payload) values(?,?,?)',
                     (entry_id,event,json.dumps(payload,ensure_ascii=False,separators=(',',':'))))

    def leave(self,conn,reason):
        entry=self.current(conn)
        if not entry or entry.get('closed'):return False
        entry.update(closed=True,closed_reason=reason)
        with conn:
            write(conn,ENTRY_KEY,entry)
            self.event(conn,entry['entry_id'],'entry_closed',{'reason':reason})
        return True

    def stale_callback(self,conn,request):
        identifier=game_id(request)
        if identifier is None:return False
        if read(conn,'ai_division_result_'+str(identifier)):return False
        entry=self.current(conn)
        active=read(conn,'ai_division_active_match',{})or{}
        if str(identifier)==str(entry.get('game_id')):
            issued=str(active.get('game_id'))==str(identifier)and bool(active.get('started')or active.get('start_reply'))
            return bool(entry.get('closed'))and not issued
        exists=conn.execute("select 1 from sqlite_master where name='personal_ai_entries'").fetchone()
        return bool(exists and conn.execute('select 1 from personal_ai_entries where game_id=?',(str(identifier),)).fetchone())

    def resume_issued(self,conn):
        """Rebind an issued snapshot after navigation/restart without redrawing."""
        active=read(conn,'ai_division_active_match',{})or{}
        if not(active.get('started')or active.get('start_reply')):return False
        entry=self.current(conn);marker=active.get('opponent',{}).get(MARKER,{})
        if not entry or str(entry.get('game_id'))!=str(active.get('game_id'))or marker.get('entry_id')!=entry.get('entry_id'):return False
        if not entry.get('closed')and entry.get('process_id')==self.process_id:return True
        entry.update(closed=False,process_id=self.process_id,started=True)
        with conn:write(conn,ENTRY_KEY,entry)
        return True


def bridge(logic,entries,lock,invalidate=None,enabled=None):
    """Follow accepted menu transitions; failed/retried requests do not draw."""
    cls=type(logic);original=cls.handle
    if getattr(original,'_studio_ai_entries',False):return
    def handle(self,command,request):
        with lock:
            feature_enabled=enabled is None or enabled();session=routing(self)
            try:
                gid=game_id(request);owner=match_owner(self.conn,gid)if gid is not None else None
                division=is_division(request)
                if owner=='tournament'and division:raise ValueError('锦标赛比赛编号不能用于 AI 组别')
                category=request.get('match_category')
                if owner=='division'and(category and not division or event_ids(request)):
                    raise ValueError('AI 组别比赛编号与赛事或模式不符')
                if command in CALLBACK_COMMANDS and feature_enabled and owner!='tournament'and entries.stale_callback(self.conn,request):
                    raise ValueError('AI 组别回调已关闭或已被另一场替换')
                selected=owner=='division'or(division and owner is None)or(
                    owner is None and not category and not event_ids(request)and session.mode=='division')
                if selected and command in CALLBACK_COMMANDS:
                    active=read(self.conn,'ai_division_active_match',{})or{}
                    receipt=read(self.conn,'ai_division_result_'+str(gid))if gid is not None and command=='CMD_GET_VSCOM_GAME_RESULT'else None
                    if gid is None or not receipt and str(active.get('game_id'))!=str(gid):
                        raise ValueError('开赛或结算没有对应的 AI 组别比赛')
                if selected and command in OPPONENT_COMMANDS and gid is not None:
                    active=read(self.conn,'ai_division_active_match',{})or{}
                    if str(active.get('game_id'))!=str(gid):raise ValueError('这场 AI 组别比赛已关闭，请重新进入')
                forwarded=request
                if selected and command in OPPONENT_COMMANDS|CALLBACK_COMMANDS:
                    forwarded=dict(request,match_category=category or'LEAGUE_COM_CUSTOM')
                    if feature_enabled and command in OPPONENT_COMMANDS:entries.resume_issued(self.conn)
            except(ValueError,TypeError,KeyError)as exc:return invalid_reply(command,request,exc)
            response=original(self,command,forwarded)
            if isinstance(response,dict)and response.get('result')=='NOERR'and session.mode is None and session.selection is None:
                clear_tournament_context(self.conn)
            if isinstance(response,dict) and response.get('result')=='NOERR' and command in EXIT_COMMANDS:
                clear_tournament_context(self.conn)
                session.division()if command=='CMD_GET_LEAGUE_COM_INFO'else session.clear()
                if feature_enabled and entries.leave(self.conn,command) and invalidate:invalidate()
            elif isinstance(response,dict)and response.get('result')=='NOERR'and selected and command in OPPONENT_COMMANDS|{'CMD_START_GAME'}:
                clear_tournament_context(self.conn);session.division()
            return response
    handle._studio_ai_entries=True
    cls.handle=handle
