"""Club-constrained, max-trained squads; no writes to owned players/coaches."""
import copy,hashlib,json,logging,random
from collections import OrderedDict
import ai_tactical_profiles as tactics
from division_squads import (Generator,STYLES,STYLE_WIRE,
    native_card_ids,APTITUDE_INDEX,STOCK_TEST_PERSON_IDS as _STOCK_TEST_PERSON_IDS,STOCK_AI_EXCLUDED_CARD_IDS,
    native_rating,proficiency_factor,f32)
from tournament_identity import native_person_key,person,personal_identities,REVISION as PERSON_IDENTITY_REVISION

STOCK_TEST_PERSON_IDS=frozenset(map(native_person_key,_STOCK_TEST_PERSON_IDS))

LEVELS={10:'VERYEASY',9:'EASY',8:'EASY',7:'NORMAL',6:'HARD',5:'VERYHARD',4:'VERYHARD',3:'VERYHARD',2:'HARDEST',1:'LEGEND'}
BOOSTER_REVISION='tournament-cpu-original-constant-v1'
RENTAL_BOOSTER_REVISION='tournament-rental-original-constant-v1'


def bind_team_identity(team,team_id,names):
    """The stock normalizer falls back to Spain for unlisted national teams."""
    data=team.setdefault('team_data',{})
    if data.get('base_team_id')!=team_id:
        name=names.get(str(team_id))or str(team_id)
        data.update(base_team_id=team_id,base_team_license='UNKNOWN',team_name=name,team_name_short=name)
        for user in team.get('user_info',[]):
            if isinstance(user,dict):user['user_name']=name[:20]
    team['squad_data']['team_id']=team_id
    return team


def assignment(cost):
    """Rectangular Hungarian assignment: a distinct person for each role."""
    n=len(cost);m=len(cost[0])if n else 0
    if m<n:return None
    u=[0]*(n+1);v=[0]*(m+1);p=[0]*(m+1);way=[0]*(m+1)
    for i in range(1,n+1):
        p[0]=i;j0=0;mins=[float('inf')]*(m+1);used=[False]*(m+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,m+1):
                if used[j]:continue
                cur=cost[i0-1][j-1]-u[i0]-v[j]
                if cur<mins[j]:mins[j]=cur;way[j]=j0
                if mins[j]<delta:delta=mins[j];j1=j
            if not j1 or delta==float('inf'):return None
            for j in range(m+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:mins[j]-=delta
            j0=j1
            if p[j0]==0:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if not j0:break
    out=[None]*n
    for j in range(1,m+1):
        if p[j]:out[p[j]-1]=j-1
    return out if all(j is not None and cost[i][j]<100000 for i,j in enumerate(out))else None


def national_family(document,team):
    nations=document.get('tournament_national_team_nations',{});nation=nations.get(str(team))
    return {int(key)for key,value in nations.items()if value==nation}if nation is not None else set()


def belongs_to_team(card,team,nation=None,family=()):
    if nation is not None:
        country=int(card.get('_nation_id')or 0)
        # A real Country cannot be overwritten by a representative-team
        # decoration. Native/preset references are only a missing-Country
        # fallback, not permission to admit a known foreign national.
        if country>0:return country==int(nation)
        return (int(card.get('initial_base_national_team_id')or 0)in {int(team),*family}
                or int(card.get('initial_base_team_id')or 0)in set(family))
    return int(card.get('initial_base_team_id')or 0)==int(team)


def membership_index(document):
    """Build once per roster projection, not once per owned player."""
    definitions={};diy=set();bindings=personal_identities(document)
    for definition in document.get('players',[]):
        identity=definition.get('identity')or{};owned=definition.get('owned')or{}
        current=(owned.get('gameplayer_id')or{}).get('id')
        if type(current)is int:definitions[current]=owned
        for cid in (identity.get('card_id'),current,*identity.get('previous_card_ids',[])):
            if type(cid)is int:diy.add(cid)
    return {'native_ids':native_card_ids(document),'definitions':definitions,'diy_ids':diy,'bindings':bindings,
            'nations':document.get('tournament_national_team_nations',{}),
            'standards':document.get('tournament_standard_cards',{}),
            'standard_extension':document.get('tournament_fallback_standard_cards',{})}


def membership_evidence(conn,document,card,team,include_diy=True,*,index=None):
    """Resolve actual membership before trusting any decorated outgoing row.

    No source/owned data is changed. Explicit event-reward or borrowed-bench
    exceptions belong to the runtime and must not become ordinary membership.
    """
    index=membership_index(document)if index is None else index
    ident=(card.get('gameplayer_id')or{}).get('id')
    result={'belongs':False,'card_id':ident,'team_id':int(team),'source':None,'reason':None}
    if type(ident)is not int or ident<=0:
        result['reason']='invalid_card_identity';return result
    if index['native_ids']is not None and ident not in index['native_ids']:
        result['reason']='not_in_current_native_catalogue';return result
    record=index['definitions'].get(ident);source='compiled_diy'if record is not None else None
    if record is None and conn.execute("select 1 from sqlite_master where name='managed_cards'").fetchone():
        row=conn.execute('select payload from managed_cards where card_id=?',(str(ident),)).fetchone()
        if row:
            try:record=json.loads(row[0])
            except (ValueError,TypeError):record=None
            if not isinstance(record,dict)or(record.get('gameplayer_id')or{}).get('id')!=ident:record=None
            if record is not None:source='managed_cards'
    if record is None:
        for key in('standards','standard_extension'):
            candidate=index[key].get(str(ident))
            if isinstance(candidate,dict)and(candidate.get('gameplayer_id')or{}).get('id')==ident:
                record=candidate;source='native_standard'if key=='standards'else'native_standard_extension';break
    elif source=='managed_cards'and index['nations'].get(str(team))is not None and not record.get('_nation_id'):
        # Some captured managed definitions omit private Country metadata.
        # Join only that missing fact from the exact native Standard ID;
        # preserve all real training, club fields and any explicit Country.
        for key in('standards','standard_extension'):
            candidate=index[key].get(str(ident))
            if isinstance(candidate,dict)and(candidate.get('gameplayer_id')or{}).get('id')==ident and candidate.get('_nation_id'):
                record=dict(record,_nation_id=candidate['_nation_id']);source+='+'+key+'_country';break
    trusted=record is not None
    if not trusted:record=card;source='wire_metadata_only'
    result['source']=source
    if not trusted and index['native_ids']is not None:
        result['reason']='source_missing';return result
    diy=ident in index['diy_ids']or bool(record.get('_personal_player_uuid'))or bool(card.get('_personal_player_uuid'))
    if diy and not include_diy:
        result['reason']='diy_disabled';return result
    nation=index['nations'].get(str(team));family={int(t)for t,n in index['nations'].items()if n==nation}if nation is not None else set()
    try:
        country=int(record.get('_nation_id')or 0)
        club=int(record.get('initial_base_team_id')or 0)
        native_nation=int(record.get('initial_base_national_team_id')or 0)
        result.update(nation_id=country,club_id=club,native_national_team_id=native_nation,
                      person_id=index['bindings'].get(ident,person(record)),trusted_source=trusted)
        if nation is not None and not trusted and country<=0:
            result['reason']='unproven_nationality';return result
        if nation is None and not trusted and(card.get('type')=='RENTAL'or(card.get('gameplayer_id')or{}).get('serial')==0):
            result['reason']='unproven_rental_membership';return result
        result['belongs']=belongs_to_team(record,team,nation,family)
        result['reason']='source_membership'if result['belongs']else'source_country_mismatch'if nation is not None and country>0 else'source_team_mismatch'
    except (ValueError,TypeError,KeyError):result['reason']='invalid_membership_metadata'
    return result


def authoritative_membership(conn,document,card,team,include_diy=True,*,index=None):
    return membership_evidence(conn,document,card,team,include_diy,index=index)['belongs']


def export_standard_cards(library,document,*,all_teams=False):
    """Include actual native Standard cards missing from the Contract catalogue.

    Unknown caps use the user's explicit 35-level tournament policy. These
    definitions are private fixture inputs, never permanent owned-card grants.
    """
    from contextlib import closing
    valid=native_card_ids(document)
    teams={team for t in document.get('tournaments',[])for team in t['team_ids']}
    nations=document.get('tournament_national_team_nations',{})
    recycled={str(r['id'])for r in document.get('catalogue_recycle_bin',[])}
    custom={int(p['identity']['card_id'])for p in document.get('players',[])}
    result={}
    with closing(library.db())as conn:
        for cid,raw in conn.execute("select id,payload from players where card_type='Standard'"):
            cid=str(cid)
            if cid in recycled or int(cid)in custom or valid is not None and int(cid)not in valid:continue
            p=json.loads(raw)
            if not all_teams and not any(belongs_to_team(p,team,nations.get(str(team)),national_family(document,team))for team in teams):continue
            params=p.get('parameters')
            if int(p.get('gameplayer_id',{}).get('id',0))!=int(cid)or not isinstance(params,list)or len(params)!=147 or any(type(n)is not int for n in params):
                raise ValueError('锦标赛普卡原生资料无效：'+cid)
            info=p.setdefault('level_info',{});cap=info.get('level_limit')
            if cap is None:
                info['level_limit']=35;p['_studio_tournament_level_limit_source']='user-default-35'
            elif type(cap)is not int or not 1<=cap<=100:raise ValueError('锦标赛普卡等级上限无效：'+cid)
            else:p['_studio_tournament_level_limit_source']='verified-source'
            result[cid]=p
    return result


def export_fallback_standard_cards(library,document):
    """Shared Standard extension; reuse the already exported team definitions."""
    cards=export_standard_cards(library,document,all_teams=True)
    existing=set(map(str,document.get('tournament_standard_cards',{})))
    cards={cid:card for cid,card in cards.items()if cid not in existing}
    for card in cards.values():card['_studio_tournament_source_card_type']='Standard'
    return cards


def standard_bench_cards(conn,document,cpu=True):
    """Validated original Standard cards; never part of a team's XI pool."""
    valid=native_card_ids(document);bindings=personal_identities(document)
    custom={int(p['identity']['card_id'])for p in document.get('players',[])}
    blocked=set(map(str,document.get('division_squads',{}).get('excluded_ids',[])))
    blocked.update(str(row['id'])for row in document.get('catalogue_recycle_bin',[]))
    if conn.execute("select 1 from sqlite_master where name='excluded_catalog_ids'").fetchone():
        blocked.update(str(r[0])for r in conn.execute("select card_id from excluded_catalog_ids where reason!='China edition'"))
    out=[]
    sources=dict(document.get('tournament_fallback_standard_cards',{}))
    # tournament_standard_cards is already export-validated as native
    # Standard. Its original payload stays intact; provenance is private.
    for cid,card in document.get('tournament_standard_cards',{}).items():
        if isinstance(card,dict):sources[str(cid)]=dict(card,_studio_tournament_source_card_type='Standard')
    for cid,source in sorted(sources.items()):
        try:
            ident=int(cid)
            if str(cid)in blocked or ident in custom or valid is not None and ident not in valid:continue
            if cpu and ident in STOCK_AI_EXCLUDED_CARD_IDS:continue
            # Candidate validation does not mutate nested source data. Make
            # the full private/training copy only for the few drawn reserves.
            card=dict(source);params=card['parameters']
            if card.get('_studio_tournament_source_card_type')!='Standard':continue
            if len(params)!=147 or any(type(n)is not int for n in params)or not 0<=params[0]<13:continue
            if int(card['gameplayer_id']['id'])!=ident or person(card)in STOCK_TEST_PERSON_IDS:continue
            if ident in bindings:card['_studio_squad_person_id']=bindings[ident]
            out.append(card)
        except (TypeError,ValueError,KeyError):continue
    return out


def club_cards(conn,document,team,include_diy=True,cpu=True):
    valid=native_card_ids(document);bindings=personal_identities(document)
    custom={int(p['identity']['card_id'])for p in document.get('players',[])}
    blocked=set(map(str,document.get('division_squads',{}).get('excluded_ids',[])))
    if conn.execute("select 1 from sqlite_master where name='excluded_catalog_ids'").fetchone():
        blocked.update(str(r[0])for r in conn.execute("select card_id from excluded_catalog_ids where reason!='China edition'"))
    out=[]
    nation=document.get('tournament_national_team_nations',{}).get(str(team))
    family=national_family(document,team)
    # The ordinary Contract catalogue is incomplete for Standard cards. Merge
    # export-validated native definitions only inside this tournament pool.
    sources={str(cid):(fingerprint,raw)for cid,fingerprint,raw in conn.execute('select card_id,fingerprint,payload from managed_cards order by card_id')}
    for cid,payload in document.get('tournament_standard_cards',{}).items():
        if cid in sources:
            try:existing=json.loads(sources[cid][1])
            except (ValueError,TypeError):existing=None
            if isinstance(existing,dict)and isinstance(existing.get('level_info',{}),dict):
                info=existing.setdefault('level_info',{})
                if info.get('level_limit')is not None:continue
                info['level_limit']=payload['level_info']['level_limit']
                existing['_studio_tournament_level_limit_source']=payload['_studio_tournament_level_limit_source']
                payload=existing
        raw=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        sources[cid]=(hashlib.sha256(raw.encode()).hexdigest(),raw)
    for cid,(fingerprint,raw)in sorted(sources.items()):
        if str(cid)in blocked or valid is not None and int(cid)not in valid:continue
        if cpu and int(cid)in STOCK_AI_EXCLUDED_CARD_IDS and int(cid)not in custom:continue
        try:
            card=json.loads(raw);params=card['parameters']
            if len(params)!=147 or any(type(n)is not int for n in params):continue
            if int(card['gameplayer_id']['id'])!=int(cid)or not 0<=params[0]<13:continue
            if not belongs_to_team(card,team,nation,family):continue
            if not include_diy and(int(cid)in custom or card.get('_personal_player_uuid')):continue
            if person(card)in STOCK_TEST_PERSON_IDS and int(cid)not in custom:continue
            card['_studio_fingerprint']=fingerprint or hashlib.sha256(raw.encode()).hexdigest()
            if int(cid)in bindings:card['_studio_squad_person_id']=bindings[int(cid)]
            out.append(card)
        except (ValueError,TypeError,KeyError):continue
    return out


def _club_pool_document(document):
    # These are precisely the exported inputs consumed by club_cards. A
    # detached snapshot also detects in-place edits without trusting revision.
    return {'players':document.get('players',[]),
            'native_player_catalogue':document.get('native_player_catalogue'),
            'tournament_standard_cards':document.get('tournament_standard_cards',{}),
            'tournament_national_team_nations':document.get('tournament_national_team_nations',{}),
            'division_squads':{'excluded_ids':document.get('division_squads',{}).get('excluded_ids',[])}}


def _copy_player(card):
    """Exact deepcopy, with native scalar arrays copied by list slicing.

    Pre-filling deepcopy's memo preserves aliases (including parameters/base
    parameters referring to one list). Unknown/nested values still use the
    ordinary copier; no JSON conversion or ability transformation occurs.
    """
    memo={}
    for value in card.values():
        if type(value)is list and len(value)>=13 and all(type(n)in(int,float,str,bool,bytes,type(None))for n in value):
            if id(value)not in memo:memo[id(value)]=value[:]
    return copy.deepcopy(card,memo)


class _ClubCardCatalogue:
    """Decoded immutable source rows, indexed in the original lexical order."""
    def __init__(self,rows,excluded,document):
        self.rows=rows;self.excluded=excluded;self.document=copy.deepcopy(document)
        valid=native_card_ids(document);bindings=personal_identities(document)
        custom={int(p['identity']['card_id'])for p in document.get('players',[])}
        blocked=set(map(str,document.get('division_squads',{}).get('excluded_ids',[])))|set(excluded)
        sources={str(cid):(fingerprint,raw)for cid,fingerprint,raw in rows}
        for cid,payload in document.get('tournament_standard_cards',{}).items():
            if cid in sources:
                try:existing=json.loads(sources[cid][1])
                except (ValueError,TypeError):existing=None
                if isinstance(existing,dict)and isinstance(existing.get('level_info',{}),dict):
                    info=existing.setdefault('level_info',{})
                    if info.get('level_limit')is not None:continue
                    info['level_limit']=payload['level_info']['level_limit']
                    existing['_studio_tournament_level_limit_source']=payload['_studio_tournament_level_limit_source']
                    payload=existing
            raw=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
            sources[cid]=(hashlib.sha256(raw.encode()).hexdigest(),raw)
        self.cards=[];self.clubs={};self.nations={};self.native={};self.national_clubs={}
        for cid,(fingerprint,raw)in sorted(sources.items()):
            if str(cid)in blocked or valid is not None and int(cid)not in valid:continue
            try:
                card=json.loads(raw);params=card['parameters'];ident=int(cid)
                if len(params)!=147 or any(type(n)is not int for n in params):continue
                if int(card['gameplayer_id']['id'])!=ident or not 0<=params[0]<13:continue
                if person(card)in STOCK_TEST_PERSON_IDS and ident not in custom:continue
                card['_studio_fingerprint']=fingerprint or hashlib.sha256(raw.encode()).hexdigest()
                if ident in bindings:card['_studio_squad_person_id']=bindings[ident]
                index=len(self.cards)
                self.cards.append((card,ident in custom or bool(card.get('_personal_player_uuid')),
                                   ident in STOCK_AI_EXCLUDED_CARD_IDS and ident not in custom))
                # Membership checks short-circuit. Invalid club metadata must
                # not remove a valid Country-positive national-team card.
                def integer(key):
                    try:return int(card.get(key)or 0)
                    except (ValueError,TypeError):return None
                club=integer('initial_base_team_id');country=integer('_nation_id');nation=integer('initial_base_national_team_id')
                if club is not None:self.clubs.setdefault(club,[]).append(index)
                if country is not None and country>0:self.nations.setdefault(country,[]).append(index)
                elif country is not None and nation is not None:
                    self.native.setdefault(nation,[]).append(index)
                    if club is not None:self.national_clubs.setdefault(club,[]).append(index)
            except (ValueError,TypeError,KeyError):continue

    def select(self,team,include_diy,cpu,private_copy=True):
        nation=self.document['tournament_national_team_nations'].get(str(team))
        if nation is None:indices=self.clubs.get(int(team),[])
        else:
            family=national_family(self.document,team)
            indices=set(self.nations.get(int(nation),[]))
            for ident in {int(team),*family}:
                indices.update(self.native.get(ident,[]))
            for ident in family:indices.update(self.national_clubs.get(ident,[]))
            indices=sorted(indices)
        return [(_copy_player(card)if private_copy else card)for i in indices for card,diy,stock_excluded in(self.cards[i],)
                if(include_diy or not diy)and(not cpu or not stock_excluded)]


class ClubGenerator(Generator):
    def payload_rating(self,parameters,coach,style,position=None):
        # Position only affects the final native integer kernel. Reuse the
        # exact position-independent booster/float32 coach transformation.
        if len(parameters)!=147:raise ValueError('AI 球员能力布局不完整')
        document=self.document();effects=coach.get('effects',{});proficiency=coach['payload'][style]
        definitions=[(bid,document.get('preview_boosters',{}).get(str(bid),{}))for bid in set(parameters[144:147])]
        key=(tuple(parameters),proficiency,tuple(effects.items()),document.get('revision'),
             tuple((bid,bool(bonus.get('conditional')),tuple(bonus.get('effects',{}).items()))for bid,bonus in definitions))
        cache=getattr(self,'_coached_payloads',None)
        if cache is None:cache=self._coached_payloads=OrderedDict()
        if key not in cache:
            params=list(parameters);boosts={}
            for bid,bonus in definitions:
                for i,n in bonus.get('effects',{}).items():boosts[int(i)]=boosts.get(int(i),0)+(min(0,n)if bonus.get('conditional')else n)
            for i,amount in effects.items():boosts[int(i)]=boosts.get(int(i),0)+amount
            factor=proficiency_factor(proficiency)
            for i in range(14,41):
                if i==33:continue
                value=params[i];params[i]=max(40,min(99,value+int(f32(f32(factor*f32(value))-f32(value)))))
            cache[key]=(tuple(params),boosts)
            if len(cache)>4096:cache.popitem(last=False)
        else:cache.move_to_end(key)
        params,boosts=cache[key]
        return native_rating(params,position,boosts)

    def trained(self,card):
        # Same cache key/cap validation and development pipeline as Generator;
        # only the private card copy uses the equivalent scalar-array copier.
        key=(int(card['gameplayer_id']['id']),card['_studio_fingerprint'])
        cap=self.caps().get(key[0]);required=max(cap or 1,card.get('level_info',{}).get('level_limit')or 1)
        cached=self._trained.get(key)
        if cached:
            level=cached.get('level_info',{})
            if level.get('level_limit',1)!=required or level.get('level',1)!=required:self._trained.pop(key,None)
        if key not in self._trained:
            p=_copy_player(card);p.pop('_studio_ai_booster',None)
            if cap and cap>(p.get('level_info',{}).get('level_limit')or 1):p.setdefault('level_info',{})['level_limit']=cap
            trained=self.developed.developed(p,{});level=trained.get('level_info',{})
            if level.get('level',1)!=level.get('level_limit',1):raise ValueError('AI 球员满级培养失败，未下发未完成培养的球员')
            self._trained[key]=trained
        return self._trained[key]

    def prepared(self,card):
        key=(int(card['gameplayer_id']['id']),card['_studio_fingerprint'],self.document().get('revision'))
        if key not in self._prepared:self._prepared[key]=self.wire(_copy_player(self.trained(card)),'list')
        extra=card.get('_studio_ai_booster')
        if not extra:return self._prepared[key]
        boosted=key+(extra['slot'],extra['id'])
        if boosted not in self._boosted_prepared:
            p=_copy_player(self._prepared[key]);p['parameters'][144+extra['slot']]=extra['id']
            p['initial_booster_id_list']=list(p['parameters'][144:147]);self._boosted_prepared[boosted]=p
        return self._boosted_prepared[boosted]

    def _club_cards(self,conn,team,include_diy,cpu,*,private_copy=True):
        # Reading raw rows is substantially cheaper than decoding/validating
        # every card for every team. Compare the exact contents (not COUNT,
        # total_changes or a possibly stale fingerprint) so edits, rollback,
        # other connections and same-length payload changes all invalidate.
        rows=tuple(conn.execute('select card_id,fingerprint,payload from managed_cards order by card_id'))
        excluded=tuple(r[0]for r in conn.execute("select card_id from excluded_catalog_ids where reason!='China edition'"))if conn.execute("select 1 from sqlite_master where name='excluded_catalog_ids'").fetchone()else()
        document=_club_pool_document(self.document());cached=getattr(self,'_club_card_catalogue',None)
        if cached is None or rows!=cached.rows or excluded!=cached.excluded or document!=cached.document:
            cached=self._club_card_catalogue=_ClubCardCatalogue(rows,excluded,document)
        return cached.select(team,include_diy,cpu,private_copy)

    def owned_coaches(self,conn):
        # The special/rental squad protocol carries a coach reference only.
        # Unlike the CPU opponent reply, it cannot create a catalogue coach
        # in the client's owned-coach registry.
        effects={int(c['payload']['coach_id']['id']):c.get('effects',{})for c in self.coaches(conn)}
        rows=[]
        for raw, in conn.execute('select json from coaches'):
            payload=json.loads(raw);cid=int(payload['coach_id']['id'])
            rows.append({'payload':payload,'effects':copy.deepcopy(effects.get(cid,{}))})
        return rows

    def build_club(self,conn,template,team,include_diy=True,rng=None,cpu=True,*,simulation_only=False):
        if simulation_only and not cpu:raise ValueError('仅不入场的电脑模拟阵容可省略教练预检')
        # The selection/development path only reads these source cards; both
        # training and outgoing payloads create private copies below. External
        # pool consumers still receive isolated cards via _club_cards default.
        rng=rng or random.SystemRandom();cards=self._club_cards(conn,team,include_diy,cpu,private_copy=False)
        try:rng_state=repr(rng.getstate())
        except NotImplementedError:rng_state=str(rng.getrandbits(128))
        fallback_seed=int(hashlib.sha256((str(team)+':'+rng_state).encode()).hexdigest()[:16],16)
        # Same private, per-fixture additions as AI divisions. Fill before
        # ranking so selection, displayed rating and tactical preflight all
        # evaluate the actual outgoing slots, for CPU and player rentals alike.
        # These remain private match copies; source/owned cards are untouched.
        self._boosted_prepared.clear()
        cards=[self.fill_booster(card,rng)for card in cards]
        people={}
        for card in cards:
            try:self.prepared(card)
            except ValueError as exc:
                # One unusable variant must not prevent the entire club from
                # entering. Do not replace it with an untrained or foreign card.
                logging.getLogger(__name__).warning('Tournament club %s skipped card %s: %s',team,card['gameplayer_id']['id'],exc)
                continue
            people.setdefault(person(card),[]).append(card)
        if len(people)<11:raise ValueError(f'球队 {team} 只有 {len(people)} 名本队/同国籍真实不同球员，无法组成11人首发；请补充该队DIY，未借用其他球队球员凑首发')
        coaches=self.coaches(conn)if cpu else self.owned_coaches(conn)
        styles=list(STYLES);rng.shuffle(styles);pairs=[]
        for style in styles:
            eligible=[c for c in coaches if c['payload'].get(style,0)>=85];rng.shuffle(eligible)
            pairs.extend((style,c)for c in eligible[:3])
        if not pairs:raise ValueError(f'球队 {team} 没有熟练度至少85的可用教练；未更换真实球员能力')
        candidates=list(self.profiles());back=rng.choices([4,3,5],weights=[70,20,10])[0]
        remaining=[n for n in(4,3,5)if n!=back];rng.shuffle(remaining)
        profiles=[p for n in[back,*remaining]for p in tactics.draw_order(rng,[p for p in candidates if tactics.back_type(p)==n])]
        identities=list(people)
        from tournament_eligibility import inspect_cards
        availability=inspect_cards([c for rows in people.values()for c in rows],profiles)
        def keeper_variants(used,coach,style):
            result=[]
            for pid,rows in people.items():
                if pid in used:continue
                keepers=[c for c in rows if self.prepared(c)['parameters'][APTITUDE_INDEX[0]]==2]
                if keepers:result.append(max(keepers,key=lambda c:self.rating(c,coach,style,0)))
            result.sort(key=lambda c:self.rating(c,coach,style,0),reverse=True)
            return result
        # Random tactical choices, strongest legal XI within each choice.
        for style,coach in pairs[:18]if availability['strict_possible']else():
            pair_rows={}
            for profile in profiles:
                choices=[];cost=[]
                for attack,defence in zip(profile['attack'],profile['defence']):
                    key=(attack,defence)
                    if key not in pair_rows:
                        row=[];weights=[]
                        for pid in identities:
                            legal=[c for c in people[pid]if all(self.prepared(c)['parameters'][APTITUDE_INDEX[r]]==2 for r in key)]
                            chosen=max(legal,key=lambda c:min(self.rating(c,coach,style,attack),self.rating(c,coach,style,defence)))if legal else None
                            row.append(chosen);weights.append(-min(self.rating(chosen,coach,style,attack),self.rating(chosen,coach,style,defence))if chosen else 100000)
                        pair_rows[key]=(row,weights)
                    row,weights=pair_rows[key]
                    choices.append(row);cost.append(weights)
                slots=assignment(cost)
                if slots is None:continue
                selected=[choices[i][j]for i,j in enumerate(slots)];used={person(c)for c in selected}
                bench=[max(rows,key=lambda c:self.rating(c,coach,style))for pid,rows in people.items()if pid not in used]
                bench.sort(key=lambda c:self.rating(c,coach,style),reverse=True)
                # Keep a real reserve goalkeeper, then the strongest remaining
                # distinct players. Tactical preflight reports actual coverage.
                keepers=[c for c in bench if self.prepared(c)['parameters'][APTITUDE_INDEX[0]]==2]
                if not keepers:keepers=keeper_variants(used,coach,style)
                if not keepers:
                    # A highest-score XI may have consumed a multi-position
                    # keeper. Prove strict infeasibility before relaxing any
                    # aptitude: reserve one real GK and retry this same shape.
                    for reserved,pid in enumerate(identities):
                        if not any(self.prepared(c)['parameters'][APTITUDE_INDEX[0]]==2 for c in people[pid]):continue
                        restricted=[list(row)for row in cost]
                        for row in restricted:row[reserved]=100000
                        retry=assignment(restricted)
                        if retry is None:continue
                        selected=[choices[i][j]for i,j in enumerate(retry)];used={person(c)for c in selected}
                        bench=[max(rows,key=lambda c:self.rating(c,coach,style))for pid,rows in people.items()if pid not in used]
                        bench.sort(key=lambda c:self.rating(c,coach,style),reverse=True)
                        keepers=[c for c in bench if self.prepared(c)['parameters'][APTITUDE_INDEX[0]]==2]
                        if not keepers:keepers=keeper_variants(used,coach,style)
                        if keepers:break
                    if not keepers:continue
                reserve=keepers[0];selected += [reserve]+[c for c in bench if person(c)!=person(reserve)][:11]
                return self.assemble(template,selected,coach,style,profile,int(team),cpu,simulation_only=simulation_only)
        return self.fallback_club(conn,template,people,pairs[0],profiles,int(team),cpu,availability,fallback_seed,simulation_only=simulation_only)

    def fallback_club(self,conn,template,people,pair,profiles,team,cpu,availability,seed,*,simulation_only=False):
        """Tournament-only real club XI, then random Standard bench padding."""
        from tournament_eligibility import REVISION
        style,coach=pair;identities=list(people);best=None;seen=set()
        gk_apt=max(self.prepared(c)['parameters'][APTITUDE_INDEX[0]]for rows in people.values()for c in rows)
        for profile in profiles:
            signature=(tuple(profile['attack']),tuple(profile['defence']))
            if signature in seen:continue
            seen.add(signature);choices=[];cost=[]
            for attack,defence in zip(*signature):
                row=[];weights=[]
                for pid in identities:
                    variants=people[pid]
                    if attack==0:
                        variants=[c for c in variants if self.prepared(c)['parameters'][APTITUDE_INDEX[0]]==gk_apt]
                    def value(card):
                        params=self.prepared(card)['parameters'];a=params[APTITUDE_INDEX[attack]];d=params[APTITUDE_INDEX[defence]]
                        # Genuine aptitude dominates ability; never set it to2.
                        return min(a,d)*1000000+(a+d)*10000+min(self.rating(card,coach,style,attack),self.rating(card,coach,style,defence))
                    card=max(variants,key=value)if variants else None
                    row.append(card);weights.append(-value(card)if card else 100000)
                choices.append(row);cost.append(weights)
            mapping=assignment(cost)
            if mapping is None:continue
            score=-sum(cost[i][j]for i,j in enumerate(mapping))
            if best is None or score>best[0]:best=(score,profile,[choices[i][j]for i,j in enumerate(mapping)])
        if best is None:raise ValueError(f'球队 {team} 的真实11人首发分配失败；未借外援凑首发')
        _,profile,selected=best;used={person(c)for c in selected}
        bench=[max(rows,key=lambda c:self.rating(c,coach,style))for pid,rows in people.items()if pid not in used]
        bench.sort(key=lambda c:self.rating(c,coach,style),reverse=True)
        selected+=bench[:12];added=[];rng=random.Random(seed)
        if len(selected)<23:
            standards=standard_bench_cards(conn,self.document(),cpu);rng.shuffle(standards)
            # Exclude EVERY local person, not only the selected variant, so a
            # borrowed Standard can never duplicate a real team footballer.
            excluded=set(people)
            for card in standards:
                pid=person(card)
                if pid in excluded:continue
                card['_studio_fingerprint']=hashlib.sha256(json.dumps(card,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                card=self.fill_booster(card,rng)
                try:self.prepared(card)
                except ValueError:continue
                excluded.add(pid)
                added.append(card);selected.append(card)
                if len(selected)==23:break
            if len(selected)<23:raise ValueError(f'球队 {team} 已有真实11人首发，但当前有效Standard普卡不足以补足23人替补名单；未虚造或复制球员')
        info={'revision':REVISION,'enabled':True,'allow_incomplete_aptitude':True,
              'original_person_count':len(people),'original_full_goalkeepers':availability['full_goalkeepers'],
              'strict_failure_reasons':availability['reasons']or['strict_assignment_unavailable'],
              'standard_bench_only':True,'fallback_seed':seed,
              'original_people':sorted(people),'added_standard_card_ids':[int(c['gameplayer_id']['id'])for c in added],
              'added_standard_people':[person(c)for c in added]}
        return self.assemble(template,selected,coach,style,profile,team,cpu,fallback=info,simulation_only=simulation_only)

    def assemble(self,template,selected,coach,style,profile,team,cpu,fallback=None,*,simulation_only=False):
        from ai_match_manager import prepare_strategies
        out=copy.deepcopy(template);roster=[]
        for i,card in enumerate(selected):
            p=_copy_player(self.prepared(card));p['parameters']+= [0]*(149-len(p['parameters']))
            # Native is-rental (V17 0x7a88330) requires BOTH type RENTAL and
            # serial 0. Nonzero synthetic instances are silently skipped by
            # the rental UI provider, even when the roster has all 23 rows.
            p['gameplayer_id']={'id':int(card['gameplayer_id']['id']),'serial':810000001+i if cpu else 0}
            p.update(uniform_number=i+1,rental_match_left=0 if cpu else 99)
            if not cpu:p['type']='RENTAL'
            p['disp_overall']=p['disp_max_overall']=self.rating(card,coach,style);roster.append(p)
        squad=out['squad_data'];squad['team_id']=team;squad['player_list']=[{'gameplayer_id':p['gameplayer_id'].copy(),'uniform_number':p['uniform_number']}for p in roster]
        payload=copy.deepcopy(coach['payload']);squad['coach']=[{'coach_id':payload['coach_id'].copy()}]
        for plan in squad['squad_gameplan']['formation']:
            plan.update(formation_offensive=tactics.coordinates(profile,'attack',style),formation_defensive=tactics.coordinates(profile,'defence',style),
                        is_position_edited=['YES','YES'],use_multi_formation='YES',team_style=STYLE_WIRE[style])
            for link in plan.get('coach_link_data',[]):link.update(is_link_on='NO',key_member_Id=255,link_member_Id=255)
        duties=tactics.duties(roster,roles={str(i):r for i,r in enumerate(profile['attack'])})if fallback else tactics.duties(roster)
        squad['squad_gameplan']['match_plan_settings'].update(order=list(range(23))+[255]*17,**duties)
        out.update(player_list=roster,coach_data=payload)
        out=self.normalize(out,team_id=team)
        bind_team_identity(out,team,self.document().get('tournament_team_names',{}))
        flag={k:fallback[k]for k in('revision','allow_incomplete_aptitude','original_person_count','standard_bench_only')}if fallback else None
        spec=(prepare_strategies(self,selected,coach,style,profile,0,tournament_fallback=flag)if fallback else
              prepare_strategies(self,selected,coach,style,profile,0))if cpu and not simulation_only else None
        out['_studio_tournament_squad']={'team_id':team,'style':style,'coach_proficiency':payload[style],
            'formation':profile['id'],'all_max_level':all(p['level_info']['level']==p['level_info']['level_limit']for p in roster),
            'person_identity_revision':PERSON_IDENTITY_REVISION,
            'native_person_keys':[person(p)for p in roster],
            'attack_roles':list(profile['attack']),'defence_roles':list(profile['defence']),'tactical_spec':spec,
            'booster_revision':BOOSTER_REVISION if cpu else RENTAL_BOOSTER_REVISION,
            'random_boosters':[{'card_id':int(c['gameplayer_id']['id']),**c['_studio_ai_booster']}
                               for c in selected if c.get('_studio_ai_booster')]}
        if fallback:
            details=copy.deepcopy(fallback);added=set(details['added_standard_card_ids']);positions=[]
            for i,p in enumerate(roster):
                role_a=profile['attack'][i]if i<11 else None;role_d=profile['defence'][i]if i<11 else None
                positions.append({'roster_index':i,'gameplayer_id':p['gameplayer_id'].copy(),'person_id':person(selected[i]),
                    'standard_bench_added':int(p['gameplayer_id']['id'])in added,'main_role':p['parameters'][0],
                    'aptitudes':[p['parameters'][k]for k in APTITUDE_INDEX],
                    'attack_role':role_a,'defence_role':role_d,
                    'attack_aptitude':p['parameters'][APTITUDE_INDEX[role_a]]if i<11 else None,
                    'defence_aptitude':p['parameters'][APTITUDE_INDEX[role_d]]if i<11 else None})
            details['players']=positions
            details['out_of_position_starters']=[r for r in positions[:11]if min(r['attack_aptitude'],r['defence_aptitude'])<2]
            out['_studio_tournament_squad']['fallback']=details
        return out

    def repair_cpu_boosters(self,team,seed,conn):
        """Upgrade an unstarted cached fixture once, without redrawing anyone."""
        return self.repair_boosters(team,seed,conn,cpu=True)

    def repair_rental_boosters(self,team,seed,conn):
        return self.repair_boosters(team,seed,conn,cpu=False)

    def rental_prepared(self,card,seed):
        return self.prepared(self.fill_booster(card,random.Random(seed)))

    def repair_boosters(self,team,seed,conn,cpu):
        meta=team['_studio_tournament_squad']
        revision=BOOSTER_REVISION if cpu else RENTAL_BOOSTER_REVISION
        if meta.get('booster_revision')==revision:return False
        rng=random.Random(seed);added=[]
        coach={'payload':team['coach_data'],'effects':next((c.get('effects',{})for c in self.coaches(conn)
              if c['payload']['coach_id']['id']==team['coach_data']['coach_id']['id']),{})}
        spec=meta.get('tactical_spec');style=meta['style']
        from ai_match_manager import tournament_aptitude_exception
        relaxed=tournament_aptitude_exception(spec or{})
        for i,player in enumerate(team['player_list']):
            extra=self.fill_booster(player,rng).get('_studio_ai_booster')
            if extra:
                player['parameters'][144+extra['slot']]=extra['id']
                player['initial_booster_id_list']=list(player['parameters'][144:147])
                added.append({'card_id':int(player['gameplayer_id']['id']),**extra})
            player['disp_overall']=player['disp_max_overall']=self.payload_rating(player['parameters'][:147],coach,style)
            if spec and i<len(spec['players']):
                row=spec['players'][i];params=list(player['parameters'][:147]);row['parameters']=params
                row['ratings']=[self.payload_rating(params,coach,style,r)if relaxed or params[APTITUDE_INDEX[r]]==2 else 0 for r in range(13)]
                row['bench_rating']=player['disp_overall']
        meta.update(booster_revision=revision,random_boosters=added)
        logging.getLogger(__name__).info('Tournament %s booster migration: team=%s added=%s','CPU'if cpu else'rental',meta['team_id'],added)
        return True
