"""Match-local CPU coaching policy. No save/ability edits and no native calls.

The native adapter supplies one coherent snapshot and owns legal execution.
This policy returns a proposal; a proposal is never an acknowledgement.
"""
import copy
import math
import time

REVISION = 'v17-situational-coach-v5-continuous-planning'
APTITUDE_INDEX = (13, 10, 11, 12, 6, 7, 8, 9, 5, 3, 4, 2, 1)
ATTACK_ROLES = frozenset((8, 9, 10, 11, 12))


def strategy(minute, difference, must_win=False, period_end=90):
    if not math.isfinite(minute) or not -20 <= difference <= 20:
        raise ValueError('Invalid match situation')
    if period_end not in (90,120) or minute > period_end+20:
        raise ValueError('Unknown match period')
    if difference < 0 and minute >= period_end-5 or difference <= -2 and minute >= period_end-20:
        return 'last_push'
    if difference < 0 and minute >= 60 or difference <= -2 and minute >= 30:
        return 'chase'
    if difference > 0 and minute >= 75:
        return 'protect'
    if difference == 0 and minute >= period_end-5 and must_win:
        return 'chase'
    return 'base'


def tactical_profile(profile, kind, style):
    import ai_tactical_profiles as templates
    result=copy.deepcopy(profile);result['strategy']=kind
    if kind=='protect':
        result['support']='restrained'
        parts=result['id'].split(':');parts[2]='restrained';result['id']=':'.join(parts)
    result['attack_coords']=templates.coordinates(result,'attack',style)
    result['defence_coords']=templates.coordinates(result,'defence',style)
    return result


def resolve_profile(spec,ident,mode):
    import ai_tactical_profiles as templates
    kind=mode
    rows=[p for p in spec['profiles']if p['id']==ident]
    value=next((p for p in rows if p.get('strategy')==kind),None)
    if value is None:value=next((p for p in rows+templates.profiles()if p['id']==ident),None)
    if value is None:raise ValueError('Unknown coaching formation')
    return tactical_profile(value,kind,spec.get('style'))


def tactical_value(profile, mode):
    """Workshop task units, independent of the native overall rating scale."""
    a,d=profile['attack'],profile['defence']
    if mode in ('chase','last_push'):
        front=sum({8:1.1,9:1.5,10:1.5,11:1.4,12:1.8}.get(r,0) for r in a)
        cover=d.count(1)+d.count(4)*.8
        connection=min(sum(r in (4,5,8,11)for r in a),4)*.35
        width=min(sum(r in (2,3,6,7,9,10)for r in a),4)*.3
        return front*(1.35 if mode=='last_push' else 1)+connection+width-max(0,(2.1 if mode=='last_push' else 2.8)-cover)*(.6 if mode=='last_push' else 1.5)
    if mode=='protect':
        # A defensive shape still needs an outlet. A second striker is not a
        # substitute for central cover, nor are five CBs intrinsically best.
        return (min(d.count(1),3)*.7+min(d.count(4),2)*1.2+
                min(d.count(5),2)*.35+sum(r in (2,3) for r in d)*.45+
                min(sum(r in (11,12) for r in a),1)*.7-
                max(0,sum(r in ATTACK_ROLES for r in a)-2)*.5)
    return 0.


def shape_signature(profile):
    """Actual two-phase shape, independent of labels and duty identities."""
    return {phase:{'roles':list(profile[phase]),
                   'grid':[[r['position_x'],r['position_y']]for r in profile[phase+'_coords']]}
            for phase in ('attack','defence')}


def tactical_catalogue(base, kind, style):
    """Round-robin distinct families, not the first eight base variants."""
    import ai_tactical_profiles as templates
    groups={};seen=set()
    for p in templates.profiles():
        signature=(p['attack'],p['defence'])
        if signature in seen:continue
        seen.add(signature)
        p=tactical_profile(p,kind,style)
        distance=sum(a!=b or c!=d for a,b,c,d in zip(p['attack'],base['attack'],p['defence'],base['defence']))
        p['_task_order']=(-tactical_value(p,kind),distance,p['id'])
        groups.setdefault(p['family'],[]).append(p)
    for values in groups.values():values.sort(key=lambda p:p['_task_order'])
    families=sorted(groups,key=lambda f:groups[f][0]['_task_order'])
    result=[]
    for turn in range(max(map(len,groups.values()))):
        for family in families:
            if turn<len(groups[family]):
                p=groups[family][turn];p.pop('_task_order',None);result.append(p)
    return result


def substitution_budget(snapshot, mode, severe, urgent=False):
    left=snapshot['substitutions_left'];windows=snapshot['windows_left'];minute=snapshot['minute']
    if left<=0 or windows<=0 and snapshot['phase']!='halftime':return 0
    emergency=mode=='last_push' or mode=='chase' and snapshot['score'][1]-snapshot['score'][0]>=2
    if emergency:return min(2,left)
    # A single severely tired player does not authorize an unrelated second
    # early change. Preserve two later choices in the middle of the match.
    reserve=2 if minute<70 else 1 if minute<80 else 0
    ordinary=0 if minute<55 else min(2,max(0,left-reserve))
    if mode in ('chase','protect'):ordinary=max(ordinary,min(1,left))
    return min(2,left,max(ordinary,len(severe)))


def pool_can_fill(spec, indices, profile):
    """Cheap simultaneous aptitude coverage, not a forecast of native events."""
    slots=list(zip(profile['attack'],profile['defence']));assigned={}
    def place(slot,seen):
        a,d=slots[slot]
        for index in indices:
            if index in seen:continue
            p=spec['players'][index]['parameters']
            if p[APTITUDE_INDEX[a]]!=2 or p[APTITUDE_INDEX[d]]!=2:continue
            seen.add(index)
            if index not in assigned or place(assigned[index],seen):
                assigned[index]=slot;return True
        return False
    return all(place(slot,set()) for slot in range(11))


def task_value(parameters,role,mode,style):
    """Small workshop role utility; never written into native abilities/OVR."""
    fields = {
        'possession':(18,19,21), 'short_counter':(34,38,14),
        'long_counter':(22,35,23), 'side_attack':(22,28,40),
        'long_ball':(23,35,22), 'overload':(14,26,40)}.get(style,(18,21,40))
    score=(sum(parameters[k] for k in fields)/len(fields)-70)*.04
    if mode in ('chase','last_push') and role in ATTACK_ROLES:
        score+=(parameters[14]+parameters[20]+parameters[38]-210)*.025
    if mode=='protect' and role in (1,2,3,4,5):
        score+=(parameters[15]+parameters[24]+parameters[26]-210)*.025
    return score


def assignment(spec, snapshot, profile, maximum_changes=0, mode='base', excluded=()):
    """Min-cost flow: jointly place live players and permitted substitutes.

    Position aptitude is a hard condition for both phases. The source's bench
    gate enforces the change budget globally, rather than per position.
    """
    on = snapshot['on_field']
    if not 7 <= len(on) <= 11 or len(set(on)) != len(on):
        return None
    players = spec['players']; blocked = set(excluded) | set(snapshot.get('unavailable', []))
    available = [i for i in range(len(players)) if i not in blocked and (i in on or i in snapshot['bench'])]
    roles = list(zip(profile['attack'], profile['defence']))
    # Native dismissals stay dismissals: remove attacking slots from this
    # proposal, never invent an eleventh player or replace a sent-off player.
    slots = list(range(11))
    for _ in range(11-len(on)):
        choices = [s for s in slots if roles[s][0] in (9, 10, 11, 12)]
        if not choices:
            choices = [s for s in slots if roles[s][0] not in (0, 1)]
        if not choices:
            return None
        slots.remove(choices[-1])
    source, bench_gate, player_at = 0, 1, 2
    slot_at = player_at + len(available); sink = slot_at + len(slots)
    graph = [[] for _ in range(sink+1)]
    def edge(a, b, cap, cost):
        forward = [b, len(graph[b]), cap, cost]
        backward = [a, len(graph[a]), 0, -cost]
        graph[a].append(forward); graph[b].append(backward)
        return forward
    edge(source, bench_gate, maximum_changes, 0)
    selected_edges = []
    current_gk = next((i for i in on if players[i]['parameters'][APTITUDE_INDEX[0]] == 2 and snapshot.get('roles', {}).get(str(i)) == 0), on[0])
    for n, index in enumerate(available):
        current = index in on; p = players[index]; node = player_at+n
        stamina = snapshot.get('stamina', {}).get(str(index))
        if type(stamina) not in (int, float) or not math.isfinite(stamina) or not 0 <= stamina <= 100:
            if current:return None
            continue
        edge(source if current else bench_gate, node, 1, 0)
        for k, slot in enumerate(slots):
            attack, defence = roles[slot]
            if p['parameters'][APTITUDE_INDEX[attack]] != 2 or p['parameters'][APTITUDE_INDEX[defence]] != 2:
                continue
            if profile.get('requires_central_cover') and attack == 5 and (p['parameters'][15]+p['parameters'][26] < 140 or p['parameters'][40] < 65):
                continue
            if attack == 0 and index != current_gk or index == current_gk and attack != 0:
                continue
            native = min(p['ratings'][attack], p['ratings'][defence])
            # Workshop decision cost, not a native rating or an ability bonus.
            effective = native - max(0, 80-stamina)*.22
            if not current:
                effective -= 1.0 if mode=='last_push' else 3.0 if mode=='chase' else 5.0
            effective += task_value(p['parameters'],attack,mode,spec.get('style'))
            e = edge(node, slot_at+k, 1, -round(effective*100))
            selected_edges.append((index, slot, e))
    for k in range(len(slots)):
        edge(slot_at+k, sink, 1, 0)
    total_cost = 0
    for _ in slots:
        distance = [float('inf')]*len(graph); distance[source] = 0
        previous = [None]*len(graph); queue = [source]; queued = {source}; at = 0
        while at < len(queue):
            node = queue[at]; at += 1; queued.discard(node)
            for k, e in enumerate(graph[node]):
                to, reverse, capacity, cost = e
                if capacity and distance[to] > distance[node]+cost:
                    distance[to] = distance[node]+cost; previous[to] = (node, k)
                    if to not in queued:
                        queue.append(to); queued.add(to)
        if previous[sink] is None:
            return None
        total_cost += distance[sink]; node = sink
        while node != source:
            parent, k = previous[node]; e = graph[parent][k]
            e[2] -= 1; graph[node][e[1]][2] += 1; node = parent
    mapping = {slot:index for index,slot,e in selected_edges if e[2] == 0}
    if len(mapping) != len(on):
        return None
    incoming = sorted(set(mapping.values())-set(on)); outgoing = sorted(set(on)-set(mapping.values()))
    if len(incoming) != len(outgoing) or len(incoming) > maximum_changes:
        return None
    from division_squads import strength
    ratings = [p.get('bench_rating', p['ratings'][p['parameters'][0]]) for p in players]
    for slot,index in mapping.items():
        a,d = roles[slot]; ratings[index] = min(players[index]['ratings'][a],players[index]['ratings'][d])
    native_lower_bound = strength(ratings) if len(on)==11 and len(ratings)==23 else None
    if len(on) == 11 and native_lower_bound < spec.get('minimum', 0):
        return None
    return {'mapping': mapping, 'incoming': incoming, 'outgoing': outgoing,
            'utility': -total_cost/100, 'profile': profile, 'mode': mode,
            'native_lower_bound_strength': native_lower_bound}


def prepare_strategies(generator,selected,coach,style,base,minimum,game_id=None,entry_id=None):
    """Bounded preflight using this actual 23, with zero/two-change variants.

    Save feasibility rather than asserting that an arbitrary chase/protect
    shape can be used by every player. Live planning rechecks the real lineup.
    """
    import ai_tactical_profiles as templates
    players=[]
    for i,c in enumerate(selected):
        params=list(generator.prepared(c)['parameters'])
        ratings=[generator.rating(c,coach,style,r) if params[APTITUDE_INDEX[r]]==2 else 0 for r in range(13)]
        players.append({'id':int(c['gameplayer_id']['id']),'serial':810000001+i,'parameters':params,
                        'ratings':ratings,'bench_rating':generator.rating(c,coach,style)})
    basis=tactical_profile(base,'base',style)
    spec={'revision':REVISION,'game_id':game_id,'entry_id':entry_id,'players':players,'style':style,
          'coach_id':coach['payload']['coach_id'],'minimum':minimum,'base_profile':basis,
          'profiles':[basis],'prepared':{},'must_win':False}
    snapshot={'on_field':list(range(11)),'bench':list(range(11,23)),
              'stamina':{str(i):100 for i in range(23)},'roles':{str(i):r for i,r in enumerate(base['attack'])},
              'defence_roles':{str(i):r for i,r in enumerate(base['defence'])}}
    for kind in ('chase','last_push','protect'):
        ordered=tactical_catalogue(base,kind,style)
        trials=0;options=[];family_counts={}
        for p in ordered:
            if family_counts.get(p['family'],0)>=2:continue
            trials+=1
            for budget in (0,1,2):
                found=legal_assignment(spec,snapshot,p,budget,kind,allow_staging=True)
                if found:
                    options.append({'profile_id':p['id'],'required_changes':len(found['incoming']),
                                    'mapping':found['mapping'],'incoming':found['incoming'],'outgoing':found['outgoing'],
                                    'native_lower_bound_strength':found['native_lower_bound_strength'],
                                    'execution_path':'formation_then_substitution_then_final' if found.get('pre_formation') else 'substitution_then_formation' if found['incoming'] else 'formation_only',
                                    'pre_formation':found.get('pre_formation')})
                    spec['profiles'].append(p);family_counts[p['family']]=family_counts.get(p['family'],0)+1
                    break
            if len(options)>=4 or trials>=32:break
        spec['prepared'][kind]={'available':bool(options),'options':options,'evaluated_shapes':trials,
                               'families':sorted(family_counts),'recomputed_after_lineup_changes':True,
                               'unavailable_reason':None if options else 'This 23 cannot fill a legal two-phase shape within two substitutions and the rating floor'}
    return spec


def staged_formation(spec,snapshot,found,mode,deadline=None):
    """Prove every intermediate role before proposing a formation-first path.

    This never submits a joint native command. The manager waits for each ACK
    and fresh roles before it submits the separate member change.
    """
    if not found['incoming'] or len(snapshot['on_field'])!=11:return None
    # Undo only the proposed member identities in the final legal mapping.
    # An unconstrained best zero-sub assignment can place the outgoing player
    # in an unrelated role and conceal this perfectly legal intermediate.
    import itertools
    from division_squads import strength
    target=found['profile']
    for outgoing in itertools.permutations(found['outgoing']):
        replacement=dict(zip(found['incoming'],outgoing))
        mapping={s:replacement.get(i,i)for s,i in found['mapping'].items()}
        if set(mapping.values())!=set(snapshot['on_field']):continue
        if any(spec['players'][i]['parameters'][APTITUDE_INDEX[r]]!=2
               for s,i in mapping.items() for r in (target['attack'][s],target['defence'][s])):continue
        ratings=[p.get('bench_rating',p['ratings'][p['parameters'][0]])for p in spec['players']]
        for s,i in mapping.items():ratings[i]=min(spec['players'][i]['ratings'][target['attack'][s]],spec['players'][i]['ratings'][target['defence'][s]])
        if strength(ratings)<spec.get('minimum',0):continue
        return {'profile_id':target['id'],'mapping':mapping,'pairs':list(zip(found['incoming'],outgoing)),
                'native_lower_bound_strength':strength(ratings)}
    candidates=[found['profile'],*spec.get('profiles',[])];seen=set()
    for profile in candidates:
        if profile['id'] in seen:continue
        if deadline is not None and time.perf_counter()>=deadline:break
        seen.add(profile['id'])
        before=assignment(spec,snapshot,profile,0,mode)
        if before is None:continue
        intermediate=dict(snapshot,roles={str(i):profile['attack'][s]for s,i in before['mapping'].items()},
                          defence_roles={str(i):profile['defence'][s]for s,i in before['mapping'].items()})
        pairs=substitution_pairs(spec,intermediate,found['incoming'],found['outgoing'])
        if pairs is None:continue
        # Also prove the post-member-change intermediate still clears the
        # native strength floor; the final target can improve it later.
        mapping={s:dict((out,inc)for inc,out in pairs).get(i,i)for s,i in before['mapping'].items()}
        from division_squads import strength
        ratings=[p.get('bench_rating',p['ratings'][p['parameters'][0]])for p in spec['players']]
        for s,i in mapping.items():ratings[i]=min(spec['players'][i]['ratings'][profile['attack'][s]],spec['players'][i]['ratings'][profile['defence'][s]])
        if strength(ratings)<spec.get('minimum',0):continue
        return {'profile_id':profile['id'],'mapping':before['mapping'],'pairs':pairs,
                'native_lower_bound_strength':before['native_lower_bound_strength']}
    return None


def valid_snapshot(spec, snapshot):
    try:
        if snapshot['game_id'] != spec['game_id'] or snapshot.get('human_controlled') is not False:
            return False
        if spec.get('entry_id') is not None and snapshot.get('entry_id') != spec['entry_id']:
            return False
        if not snapshot.get('coherent') or snapshot.get('paused') or snapshot.get('replay'):
            return False
        if snapshot['phase'] not in ('play', 'stoppage', 'halftime'):
            return False
        if not math.isfinite(snapshot['minute']) or not 0 <= snapshot['minute'] <= 150:
            return False
        if len(snapshot['score']) != 2 or any(type(n) is not int or not 0 <= n <= 50 for n in snapshot['score']):
            return False
        ids = snapshot['on_field']+snapshot['bench']
        if len(ids) != len(set(ids)) or any(type(i) is not int or not 0 <= i < len(spec['players']) for i in ids):
            return False
        return 7 <= len(snapshot['on_field']) <= 11
    except (KeyError, TypeError, ValueError):
        return False


def substitution_pairs(spec, snapshot, incoming, outgoing):
    """Find a legal intermediate lineup while waiting for the joint shape.

    Native member changes and native formation updates are separate events.
    Each incoming player must also fully cover the outgoing player's CURRENT
    two-phase role. Never temporarily put a new striker in an untrained AMF
    slot and hope the later formation update will repair it.
    """
    if len(incoming) != len(outgoing) or len(incoming) > 2:
        return None
    roles = snapshot.get('roles', {})
    defensive = snapshot.get('defence_roles', roles)
    def visit(todo, remaining):
        if not todo:return []
        out = todo[0]; attack = roles.get(str(out)); defence = defensive.get(str(out))
        if type(attack) is not int or type(defence) is not int or not 0 <= attack < 13 or not 0 <= defence < 13:
            return None
        for inc in remaining:
            p = spec['players'][inc]['parameters']
            if p[APTITUDE_INDEX[attack]] != 2 or p[APTITUDE_INDEX[defence]] != 2:
                continue
            result = visit(todo[1:], [i for i in remaining if i != inc])
            if result is not None:return [(inc, out)]+result
        return None
    return visit(list(outgoing), list(incoming))


def lineup_utility(spec,snapshot,mode):
    """Counterfactual for leaving the actual native lineup exactly as it is."""
    roles=snapshot.get('roles',{});defence=snapshot.get('defence_roles',roles);result=0.
    for index in snapshot['on_field']:
        a=roles.get(str(index));d=defence.get(str(index))
        if type(a)is not int or type(d)is not int or not 0<=a<13 or not 0<=d<13:return None
        energy=snapshot.get('stamina',{}).get(str(index))
        if type(energy)not in (int,float) or not math.isfinite(energy) or not 0<=energy<=100:return None
        p=spec['players'][index]
        effective=min(p['ratings'][a],p['ratings'][d])-max(0,80-energy)*.22
        result+=round((effective+task_value(p['parameters'],a,mode,spec.get('style')))*100)/100
    return result


def legal_assignment(spec,snapshot,profile,maximum_changes=0,mode='base',excluded=(),required_outgoing=(),deadline=None,mandatory_outgoing=(),allow_staging=False):
    """Keep searching when the best final shape has an unsafe intermediate.

    Native substitutions are confirmed before the target shape is committed.
    A globally optimal reassignment can therefore be illegal in that brief
    intermediate lineup. Evaluate bounded alternatives with fixed legal
    member pairs instead of silently abandoning every substitution.
    """
    mandatory=set(mandatory_outgoing)
    if len(mandatory)>maximum_changes or not mandatory<=set(snapshot['on_field']):return None
    excluded=tuple(set(excluded)|mandatory)
    best=assignment(spec,snapshot,profile,maximum_changes,mode,excluded)
    if best is not None:
        pairs=substitution_pairs(spec,snapshot,best['incoming'],best['outgoing'])
        if pairs is not None and mandatory<=set(best['outgoing']) and (not required_outgoing or set(best['outgoing'])&set(required_outgoing)):
            best['pairs']=pairs
            return best
        if allow_staging and mandatory<=set(best['outgoing']) and (not required_outgoing or set(best['outgoing'])&set(required_outgoing)):
            pre=staged_formation(spec,snapshot,best,mode,deadline)
            if pre:
                best['pairs']=pre['pairs'];best['pre_formation']=pre;return best
    unchanged=None if mandatory else assignment(spec,snapshot,profile,0,mode,excluded)
    if unchanged is not None:unchanged['pairs']=[]
    if maximum_changes<=0:return unchanged
    blocked=set(excluded)|set(snapshot.get('unavailable',[]))
    roles=snapshot.get('roles',{});defence=snapshot.get('defence_roles',roles)
    players=spec['players'];choices=[]
    # Compare with the ACTUAL native lineup. The unconstrained zero-sub
    # solution may itself permute many roles and has not been executed.
    actual_utility=lineup_utility(spec,snapshot,mode)
    if actual_utility is None:return unchanged
    best=None
    for out in snapshot['on_field']:
        a=roles.get(str(out));d=defence.get(str(out))
        if a==0 or type(a)is not int or type(d)is not int or not 0<=a<13 or not 0<=d<13:continue
        old=players[out]
        old_value=min(old['ratings'][a],old['ratings'][d])-max(0,80-snapshot['stamina'][str(out)])*.22
        for inc in snapshot['bench']:
            if inc in blocked:continue
            p=players[inc]
            if p['parameters'][APTITUDE_INDEX[a]]!=2 or p['parameters'][APTITUDE_INDEX[d]]!=2:continue
            energy=snapshot.get('stamina',{}).get(str(inc))
            if type(energy)not in (int,float) or not math.isfinite(energy) or not 0<=energy<=100:continue
            value=min(p['ratings'][a],p['ratings'][d])-max(0,80-energy)*.22
            choices.append((value-old_value,inc,out))
    choices.sort(reverse=True)
    # This is a decision-search budget, not a restriction on the card pool.
    # Keep the best pair for each outgoing player before filling remaining
    # slots, so a single versatile substitute cannot crowd everyone else out.
    selected=[];seen_out=set()
    for row in choices:
        if row[2] not in seen_out:selected.append(row);seen_out.add(row[2])
    selected.extend(row for row in choices if row not in selected)
    selected=sorted(selected[:24],reverse=True)
    combinations=[[(inc,out)] for _,inc,out in selected]
    if maximum_changes>=2:
        joint=[]
        for i,(value,inc,out) in enumerate(selected):
            for other,inc2,out2 in selected[i+1:]:
                if inc!=inc2 and out!=out2:joint.append((value+other,[(inc,out),(inc2,out2)]))
        joint.sort(key=lambda row:row[0],reverse=True)
        combinations.extend(pairs for _,pairs in joint[:32])
    for pairs in combinations:
        if deadline is not None and time.perf_counter()>=deadline:break
        incoming=[p[0] for p in pairs];outgoing=[p[1] for p in pairs]
        if not mandatory<=set(outgoing):continue
        if required_outgoing and not set(outgoing)&set(required_outgoing):continue
        constrained=dict(snapshot,bench=incoming)
        found=assignment(spec,constrained,profile,len(pairs),mode,(*excluded,*outgoing))
        if found is None or set(found['incoming'])!=set(incoming) or set(found['outgoing'])!=set(outgoing):continue
        if best is None or found['utility']>best['utility']:
            found['pairs']=pairs;best=found
    return best if best is not None and (mandatory or best['utility']>actual_utility+2) else unchanged


def decision_context(snapshot, mode):
    # Stamina changes continuously and is deliberately absent. A rejected
    # native request is retried only after a meaningful legal-context change.
    return [list(snapshot['score']), sorted(snapshot['on_field']),
            sorted(snapshot.get('unavailable', [])), snapshot.get('substitutions_left'),
            snapshot.get('windows_left'), snapshot.get('native_pending_count', 0), mode,
            snapshot.get('period'),snapshot['phase']]


class Manager:
    def __init__(self, spec, state=None):
        self.spec = copy.deepcopy(spec)
        self.state = copy.deepcopy(state) if state and state.get('game_id') == spec['game_id'] and state.get('entry_id') == spec.get('entry_id') else {
            'game_id': spec['game_id'], 'mode': 'base', 'last_tactic_minute': -100,
            'last_sub_minute': -100, 'used_out': [], 'previous_on_field': [],
            'last_score': None, 'last_active_count': 11, 'pending': None, 'next_id': 1,
            'entry_id': spec.get('entry_id'),
            'after_sub_plan': None, 'last_evaluation_minute':-100,'rejected_context':None}
        self.state.setdefault('journal', [])
        self.state.setdefault('last_clock', None)
        self.state.setdefault('elapsed_minute', 0.)
        self.state.setdefault('profile_id',spec['base_profile']['id'])
        self.state.setdefault('rebuild_due',False)
        self.state.setdefault('last_full_evaluation',-100.)
        self.state.setdefault('staged_plan',None)
        self.state.setdefault('last_emergency_signature',None)
        self._candidates={}
        self._coverage_cache={}
        self._coverage_groups=None

    def profile(self,ident,mode=None):
        return resolve_profile(self.spec,ident,mode or self.state['mode'])

    def candidates(self,snapshot,mode):
        current=self.profile(self.state['profile_id'])
        kind=mode
        blocked=set(self.state['used_out'])|set(snapshot.get('unavailable',[]))
        available=tuple(i for i in snapshot['on_field']+snapshot['bench'] if i not in blocked)
        key=(kind,available,self.state['profile_id'])
        if key not in self._candidates:
            rows=tactical_catalogue(current,kind,self.spec.get('style'))
            rows.insert(0,tactical_profile(current,kind,self.spec.get('style')))
            result=[];seen=set();families={}
            for p in rows:
                if p['id'] in seen or families.get(p['family'],0)>=2:continue
                seen.add(p['id'])
                if len(snapshot['on_field'])==11 and not pool_can_fill(self.spec,available,p):continue
                result.append(p);families[p['family']]=families.get(p['family'],0)+1
                if len(result)>=24:break
            self._candidates={key:result}
        return self._candidates[key]

    def explain(self,snapshot,reason,**values):
        value={'reason':reason,'minute':snapshot['minute'],'score':list(snapshot['score']),**values}
        key={k:v for k,v in value.items() if k!='minute'}
        if key!=self.state.get('decision_key'):
            self.state['decision_key']=key;self.state['last_decision']=value
            self.record('decision',**value)

    def future_coverage_cost(self,snapshot,found,profiles=None):
        if not found['outgoing'] or len(snapshot['on_field'])!=11:return 0.
        blocked=set(self.state['used_out'])|set(snapshot.get('unavailable',[]))
        before=[i for i in snapshot['on_field']+snapshot['bench'] if i not in blocked]
        after=[i for i in before if i not in found['outgoing']]
        # Preserve tasks that this match may still need, not every formation
        # family in the global catalogue. Several legal shapes for the same
        # chase/protect task provide alternatives, not cumulative penalties.
        mode=found.get('mode',self.state['mode'])
        if mode=='last_push':return 0.
        needed=('chase','protect')if mode=='base' or snapshot['minute']<70 else (mode,)
        if self._coverage_groups is None:
            groups={}
            for kind in ('chase','protect'):
                declared=self.spec.get('prepared',{}).get(kind,{}).get('options')
                values=([self.profile(row['profile_id'],kind)for row in declared] if declared is not None else
                        [tactical_profile(p,kind,self.spec.get('style'))for p in self.spec['profiles']])
                groups[kind]=values
            self._coverage_groups=groups
        key=(tuple(before),needed)
        if key not in self._coverage_cache:
            self._coverage_cache={key:{kind:[p for p in self._coverage_groups.get(kind,[]) if pool_can_fill(self.spec,before,p)]
                                      for kind in needed}}
        possible=self._coverage_cache[key]
        after_key=(key,tuple(sorted(found['outgoing'])))
        if after_key not in self._coverage_cache:
            self._coverage_cache[after_key]=sum(bool(values) and not any(pool_can_fill(self.spec,after,p) for p in values)
                                                 for values in possible.values())
        lost=self._coverage_cache[after_key]
        return lost*(1.5 if snapshot['minute']<70 else .5)

    def record(self, event, **payload):
        self.state['journal'].append({'event': event, **payload})
        del self.state['journal'][:-128]

    def clock(self, snapshot):
        """Monotonic decision/cooldown time, separate from displayed minute.

        A verified native continuous counter wins. With stage-local clocks,
        only observed forward deltas are counted across a stage transition;
        break duration and an assumed 45/90-minute offset are never invented.
        """
        tick = snapshot.get('elapsed_seconds')
        if type(tick) in (int, float) and math.isfinite(tick) and tick >= 0:
            elapsed = tick/60.
            if elapsed < self.state['elapsed_minute']:return None
            self.state['elapsed_minute'] = elapsed
        else:
            current = [snapshot.get('period'), snapshot['minute']]
            previous = self.state['last_clock']
            if previous is None:
                self.state['elapsed_minute'] = snapshot['minute']
            elif current[0] == previous[0] and current[1] < previous[1]:
                return None  # Out-of-order/replay clock: do not age cooldowns.
            else:
                self.state['elapsed_minute'] += max(0., current[1]-previous[1])
            self.state['last_clock'] = current
        return self.state['elapsed_minute']

    def cancel(self, pending, snapshot, reason):
        if pending.get('cancel_requested'):return
        pending['cancel_requested'] = True
        pending['cancel_reason'] = reason
        self.record('cancel_requested', plan_id=pending['id'], sequence=snapshot['sequence'], reason=reason)

    def cancellation(self):
        pending = self.state['pending']
        if pending and pending.get('cancel_requested'):
            return {'kind':'cancel', 'id':pending['id'], 'game_id':self.spec['game_id'],
                    'entry_id':self.spec.get('entry_id'), 'reason':pending['cancel_reason']}
        return None

    def observe(self, snapshot):
        if not valid_snapshot(self.spec, snapshot):
            return False
        elapsed = self.clock(snapshot)
        if elapsed is None:return False
        current = set(snapshot['on_field']); before = set(self.state['previous_on_field'])
        if before and current!=before:self.state['rebuild_due']=True
        self.state['used_out'] = sorted(set(self.state['used_out']) | (before-current))
        self.state['previous_on_field'] = list(snapshot['on_field'])
        pending = self.state['pending']
        if pending and snapshot.get('ack_id') == pending['id']:
            # Native request acceptance and an actual lineup change are distinct.
            if snapshot.get('ack_status') == 'applied':
                completed = True
                if pending['kind'] == 'substitution':
                    if not set(pending['incoming']).issubset(current) or set(pending['outgoing']) & current:
                        completed = False
                    if completed:
                        self.state['last_sub_minute'] = elapsed
                        # Refresh shape and duties after EVERY confirmed
                        # substitution, including an ordinary fatigue change.
                        self.state['after_sub_plan'] = pending
                        self.state['rebuild_due'] = True
                else:
                    self.state['mode'] = pending['mode']
                    self.state['profile_id'] = pending['profile_id']
                    self.state['attack_level'] = pending['attack_level']
                    if pending.get('changes_shape',True):self.state['last_tactic_minute'] = elapsed
                    self.state['rebuild_due'] = False
                    if pending.get('continuation'):
                        self.state['staged_plan']=pending['continuation']
                        self.record('intermediate_formation_confirmed',plan_id=pending['id'])
                if completed:
                    self.record('applied', plan_id=pending['id'], sequence=snapshot['sequence'])
                    self.state['pending'] = None
            elif snapshot.get('ack_status') in ('rejected', 'stale', 'cancelled', 'partial'):
                self.state['rejected_context']=pending.get('context')
                self.state['after_sub_plan'] = None
                self.state['staged_plan'] = None
                self.record(snapshot['ack_status'], plan_id=pending['id'], sequence=snapshot['sequence'])
                self.state['pending'] = None
        pending = self.state['pending']
        if pending:
            if 'initial_on_field' not in pending:
                self.cancel(pending, snapshot, 'old plan has no verified initial lineup')
                return True
            mode = strategy(snapshot['minute'], snapshot['score'][0]-snapshot['score'][1],
                            self.spec.get('must_win', False), snapshot.get('period_end',90))
            expected = set(pending['initial_on_field'])
            result = (expected-set(pending['outgoing'])) | set(pending['incoming'])
            # An expected partial replacement is permitted while the native
            # window is processing. Other entrants/removals invalidate it.
            partial = current <= (expected | set(pending['incoming'])) and (expected & result) <= current
            reason = None
            if list(snapshot['score']) != pending['score']:reason = 'score changed'
            elif len(current) != pending['active_count'] or not partial:reason = 'native lineup changed'
            elif set(pending['incoming']) & set(snapshot.get('unavailable', [])):reason = 'substitute unavailable'
            elif mode != pending['mode']:reason = 'strategy changed'
            elif elapsed-pending.get('created_elapsed', elapsed) > 3:reason = 'native confirmation timed out'
            if reason:self.cancel(pending, snapshot, reason)
        return True

    def propose(self, snapshot):
        if not self.observe(snapshot) or self.state['pending']:
            return None
        minute = snapshot['minute']; elapsed = self.state['elapsed_minute']; score = tuple(snapshot['score'])
        mode = strategy(minute, score[0]-score[1], self.spec.get('must_win', False),snapshot.get('period_end',90))
        count = len(snapshot['on_field'])
        count_changed=count != self.state['last_active_count']
        if count_changed:self.state['rebuild_due']=True
        emergency_signature=[sorted(snapshot.get('unavailable',[])),sorted(i for i in snapshot['on_field'] if snapshot.get('stamina',{}).get(str(i),100)<35)]
        new_emergency=emergency_signature!=self.state['last_emergency_signature'] and any(emergency_signature)
        self.state['last_emergency_signature']=emergency_signature
        urgent = score != self.state['last_score'] or count_changed or new_emergency
        if self.state['last_score'] is None:
            urgent = False
        self.state['last_score'] = score; self.state['last_active_count'] = count
        if not urgent and elapsed-self.state.get('last_evaluation_minute',-100)<.5:
            return None
        # Do not consume the evaluation opportunity while awaiting a legal
        # native window. A stoppage arriving shortly afterward must still work.
        can_change = (snapshot.get('safe_to_change') is True and snapshot['phase'] in ('stoppage','halftime') or
                      snapshot.get('native_formation_window') is True and snapshot['phase']=='play')
        can_queue = snapshot.get('safe_to_queue') is True or (can_change and snapshot['phase'] != 'play')
        if not can_change and not can_queue:return None
        if snapshot.get('native_pending_count', 0):
            self.explain(snapshot,'native_queue_busy',mode=mode);return None
        self.state['last_evaluation_minute']=elapsed
        context=decision_context(snapshot,mode)
        if context==self.state.get('rejected_context'):
            self.explain(snapshot,'same_rejected_context',mode=mode);return None
        level={'base':2,'protect':1 if score[0]-score[1]==1 else 2,'chase':3,'last_push':4}[mode]
        changed=mode!=self.state['mode'] or level!=self.state.get('attack_level',2)
        interval={'base':5,'protect':5,'chase':3,'last_push':2}[mode]
        periodic=elapsed-self.state['last_full_evaluation']>=interval
        cooldown=3 if mode=='last_push' else 5
        can_reform=urgent or elapsed-self.state['last_tactic_minute']>=cooldown
        # Evaluation cadence and actual formation cooldown are independent.
        tactic_due = self.state['rebuild_due'] or changed or periodic or urgent
        staged=self.state.get('staged_plan')
        if staged and (staged['score']!=list(score) or staged['mode']!=mode or
                       set(staged['initial_on_field'])!=set(snapshot['on_field']) or
                       elapsed-staged['created_elapsed']>3):
            self.record('staged_plan_cancelled',reason='live situation changed before next step')
            self.state['staged_plan']=None;staged=None;self.state['rebuild_due']=True;tactic_due=True
        if staged:tactic_due=True
        follow=self.state.get('after_sub_plan')
        if follow:
            expected=(set(follow.get('initial_on_field',snapshot['on_field']))-set(follow.get('outgoing',[])))|set(follow.get('incoming',[]))
            if follow.get('score',list(score))!=list(score) or follow['mode']!=mode or expected!=set(snapshot['on_field']):
                self.record('after_sub_plan_cancelled',reason='live situation changed; confirmed member changes retained')
                self.state['after_sub_plan']=None;follow=None;self.state['rebuild_due']=True;tactic_due=True
        if follow and follow['mode']==mode:tactic_due=True
        stamina = snapshot.get('stamina', {})
        tired = [i for i in snapshot['on_field'] if snapshot.get('roles', {}).get(str(i)) != 0 and
                 type(stamina.get(str(i))) in (int,float) and (stamina[str(i)] < 35 or minute >= 55 and stamina[str(i)] < 55)]
        # Card risk is supplied only when decoded by the adapter; unknown is not
        # treated as a yellow card and one yellow never suffices on its own.
        risk = [i for i in snapshot['on_field'] if snapshot.get('yellow_risk', {}).get(str(i)) == 'high']
        sub_due = (tired or risk or tactic_due) and (urgent or elapsed-self.state['last_sub_minute'] >= 5)
        if not tactic_due and not sub_due:
            self.explain(snapshot,'current_plan_still_matches_situation',mode=mode,
                         family=self.profile(self.state['profile_id'])['family'])
            return None
        left = snapshot.get('substitutions_left'); windows = snapshot.get('windows_left')
        if type(left) is not int or type(windows) is not int or left < 0 or windows < 0:
            return None
        severe=sorted((i for i in tired if stamina.get(str(i),100)<35),key=lambda i:(stamina[str(i)],i))
        budget=substitution_budget(snapshot,mode,severe,urgent) if sub_due and can_queue else 0
        if not tactic_due and budget==0:
            self.explain(snapshot,'substitution_budget_reserved_or_unavailable',mode=mode,
                         remaining=left,windows=windows,severe=len(severe));return None
        # A fatigue change must retain the confirmed protect/chase structure;
        # using the original base here would silently undo a previous change.
        current_profile=self.profile(self.state['profile_id'])
        profiles=[current_profile] if not tactic_due else self.candidates(snapshot,mode)
        if tactic_due:self.state['last_full_evaluation']=elapsed
        if staged:profiles=[self.profile(staged['profile_id'],mode)]
        follow = self.state.get('after_sub_plan')
        if follow and follow['mode'] == mode:
            profiles = [self.profile(follow['profile_id'],mode)]
            budget = 0
        candidates = [];rejected=0;cooldown_rejected=set();deadline=time.perf_counter()+.2
        current_shape=shape_signature(current_profile)
        roles=snapshot.get('roles',{});defensive=snapshot.get('defence_roles',roles)
        invalid_current=any(type(role)is int and 0<=role<13 and self.spec['players'][i]['parameters'][APTITUDE_INDEX[role]]!=2
                            for i in snapshot['on_field']for role in (roles.get(str(i)),defensive.get(str(i))))
        may_start_change=can_reform or bool(severe) or count_changed or invalid_current
        parent=staged or follow or {}
        authorization=parent.get('cooldown_authorized',{})
        def shape_allowed(target,pre=None):
            target_shape=shape_signature(target)
            if target_shape==current_shape and pre is None:return True
            if may_start_change:return True
            # Only finish an explicitly authorized multi-step plan through
            # its own confirmed intermediate shape. An old after-sub refresh
            # is never a blanket exception to formation cooldown.
            return (authorization.get('target')==target_shape and authorization.get('intermediate')==current_shape
                    and elapsed<=authorization.get('expires_elapsed',-1) and pre is None)
        keep=lineup_utility(self.spec,snapshot,mode)
        if keep is None:return None
        if not self.state['rebuild_due'] and not changed and not follow and not staged:
            candidates.append({'incoming':[],'outgoing':[],'profile':current_profile,'hold':True,
                               'decision_value':keep/count+3*tactical_value(current_profile,mode)+.15})
        def consider(profile,allowance,mandatory=()):
            nonlocal rejected
            found=legal_assignment(self.spec,snapshot,profile,allowance,mode,self.state['used_out'],
                                   () if tactic_due else tired+risk,deadline,mandatory,
                                   allow_staging=can_change and tactic_due and not staged)
            if not found:rejected+=1;return
            if not found['incoming'] and (not can_change or not tactic_due):return
            if not tactic_due and found['incoming'] and not set(found['outgoing'])&set(tired+risk):return
            if not shape_allowed(found['profile'],found.get('pre_formation')):
                rejected+=1;cooldown_rejected.add(found['profile']['family']);return
            switch=.6 if profile['family']!=current_profile['family'] else .12 if profile['id']!=current_profile['id'] else 0.
            cost=len(found['incoming'])*(.25 if mode=='last_push' else 1.4 if minute<70 else .7)
            if found.get('pre_formation'):cost+=.35
            if found['incoming'] and windows<=1 and snapshot['phase']!='halftime' and minute<70:cost+=1.5
            if mode!='last_push':cost+=self.future_coverage_cost(snapshot,found)
            found['decision_value']=found['utility']/count+3*tactical_value(profile,mode)-switch-cost
            candidates.append(found)
        # Inspect no-sub alternatives across families before spending the
        # bounded search time on expensive multi-substitution combinations.
        if tactic_due:
            for profile in profiles:
                if time.perf_counter()>=deadline:break
                consider(profile,0)
        # Search constrained severe-fatigue replacements before voluntary
        # upgrades. They retain every aptitude/intermediate/floor condition.
        if budget and severe:
            import itertools
            targets=[group for n in range(min(budget,len(severe)),0,-1) for group in itertools.combinations(severe,n)]
            targets.sort(key=lambda group:tuple(i in group for i in severe),reverse=True)
            for group in targets:
                if time.perf_counter()>=deadline:break
                for profile in profiles:
                    if time.perf_counter()>=deadline:break
                    consider(profile,len(group),group)
        for allowance in range(1,budget+1):
            for profile in profiles:
                if time.perf_counter()>=deadline:break
                consider(profile,allowance)
        if not candidates:
            self.explain(snapshot,'no_legal_plan',mode=mode,budget=budget,remaining=left,
                         families=sorted({p['family']for p in profiles}),rejected=rejected,cooldown_rejected=sorted(cooldown_rejected))
            return None
        chosen=max(candidates,key=lambda c:(tuple(i in c['outgoing']for i in severe),c['decision_value']))
        if chosen.get('hold'):
            self.explain(snapshot,'hold_lineup_better_after_change_costs',mode=mode,budget=budget,
                         severe=severe,candidates=len(candidates),cooldown_rejected=sorted(cooldown_rejected))
            return None
        if not tactic_due and not set(chosen['outgoing']) & set(tired+risk):
            return None
        proposal = {'id':self.state['next_id'],'game_id':self.spec['game_id'],
                    'policy_revision':REVISION,
                    'based_on_sequence':snapshot['sequence'],'minute':minute,'mode':mode,
                    'entry_id':self.spec.get('entry_id'),'context':context,
                    'score':list(score),'active_count':count,
                    'kind':'substitution' if chosen['incoming'] else 'formation',
                    'mapping':chosen['mapping'],'incoming':chosen['incoming'],'outgoing':chosen['outgoing'],
                    'profile_id':chosen['profile']['id'],
                    'pairs': chosen['pairs'], 'initial_on_field':list(snapshot['on_field']),
                    'created_elapsed':elapsed,
                    'attack_level':level,
                    'native_lower_bound_strength':chosen['native_lower_bound_strength'],
                    'reason':'fatigue or disciplinary risk' if chosen['incoming'] and set(chosen['outgoing'])&set(tired+risk) and not changed else 'score-time strategy'}
        pre=chosen.get('pre_formation')
        if pre:
            proposal['continuation']={'profile_id':proposal['profile_id'],'score':list(score),'mode':mode,
                                      'initial_on_field':list(snapshot['on_field']),'created_elapsed':elapsed,
                                      'cooldown_authorized':{'target':shape_signature(chosen['profile']),
                                          'intermediate':shape_signature(self.profile(pre['profile_id'],mode)),
                                          'expires_elapsed':elapsed+3}}
            proposal.update(kind='formation',mapping=pre['mapping'],incoming=[],outgoing=[],pairs=[],
                            profile_id=pre['profile_id'],native_lower_bound_strength=pre['native_lower_bound_strength'],
                            reason='confirmed formation-first execution path')
        elif authorization:
            proposal['cooldown_authorized']=copy.deepcopy(authorization)
            if staged:self.state['staged_plan']=None
        elif staged:self.state['staged_plan']=None
        from ai_tactical_profiles import duties
        actual_profile=self.profile(proposal['profile_id'],mode)
        proposal['changes_shape']=shape_signature(actual_profile)!=current_shape or count_changed
        live_roles={str(index):actual_profile['attack'][slot]for slot,index in proposal['mapping'].items()}
        proposal['duties']=duties(self.spec['players'],list(proposal['mapping'].values()),live_roles)
        self.state['after_sub_plan'] = None
        self.state['next_id'] += 1; self.state['pending'] = proposal
        structural=chosen['profile']['family']!=current_profile['family']
        self.explain(snapshot,'selected',mode=mode,budget=budget,remaining=left,
                     current_family=current_profile['family'],target_family=chosen['profile']['family'],
                     structural_change=structural,profile=proposal['profile_id'],
                     action=('structural_formation' if structural else 'substitution' if chosen['incoming']
                             else 'duty_refresh' if follow else 'shape_or_attack_level'),
                     candidates=len(candidates),families=sorted({p['profile']['family']for p in candidates}))
        self.record('proposed', plan_id=proposal['id'], sequence=snapshot['sequence'],
                    mode=mode, incoming=proposal['incoming'], outgoing=proposal['outgoing'])
        return copy.deepcopy(proposal)
