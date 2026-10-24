"""The V13 editor's position regression, shared by saved player summaries."""
import copy
from coach_formula import factor, displayed


def calculate(project, catalog):
    base = dict(project['base_abilities'])
    trained = dict(base)
    for group in catalog['training_groups']:
        for index in group['indices']:
            key = str(index)
            trained[key] = min(105, trained[key] + project['training'].get(group['id'], 0))
    boosted = dict(trained)
    boosters = {b['id']: b for b in catalog['boosters'] + project.get('custom_boosters', [])}
    player_boosts={}
    for ident in project.get('booster_ids', []):
        booster = boosters.get(ident)
        if not booster or (booster.get('conditional') and not project.get('conditional_boosters')):
            continue
        for key, delta in booster['effects'].items():
            boosted[str(key)] = max(1, min(127, boosted[str(key)] + delta))
            player_boosts[str(key)]=player_boosts.get(str(key),0)+delta
    selected=project.get('preview',{}).get('coach_id')
    coach=next((row for row in project.get('custom_coaches',[])+catalog.get('coaches',[]) if row['id']==selected),None)
    final=dict(boosted)
    if coach:
        tactics=coach.get('tactics') or {}
        style=project.get('preview',{}).get('team_style') or (max(tactics,key=tactics.get) if tactics else None)
        multiplier=factor(tactics.get(style))
        for key in base:
            final[key]=displayed(trained[key],player_boosts.get(key,0),coach['effects'].get(key,0),multiplier)

    def rating(stats, position):
        weights = catalog['ovr_weights'].get(position)
        if not weights:
            return 0
        def score(values):
            value=weights['intercept']
            for key,stat in zip(catalog['ABILITIES'],catalog['stat_keys']):
                value+=weights['abilities'].get(stat,0)*(values[int(key)] if isinstance(values,list) else values[key])
            return value
        value=score(stats)
        source=project.get('source_player',{}).get('original_payload',{})
        params=source.get('parameters') or []
        if type(source.get('_overall')) is int and len(params)>=41 and 0<=params[0]<len(catalog['POSITIONS']) and catalog['POSITIONS'][params[0]]==position:
            value=source['_overall']+value-score(params)
        return max(1,min(127,round(value)))

    pos = project['identity']['position']
    return {'base': rating(base, pos), 'trained': rating(trained, pos), 'before_coach':rating(boosted,pos), 'current': rating(final, pos),
            'positions': {position: rating(final, position) for position in catalog['POSITIONS']},
            'method': 'v13-position-regression-with-native-baseline',
            'coach_id':selected if coach else None, 'includes_condition_arrow': False}


def maximum_development(project,catalog):
    """Find the maximum position score within the cap's real training budget.

    Groups contain disjoint ability sets, so a multiple-choice knapsack gives
    the maximum of the same linear position formula used by the editor.
    Coach preview settings never become part of a card's advertised rating.
    """
    p=copy.deepcopy(project);p.setdefault('preview',{})['coach_id']=None
    p['initial_level']=p['max_level'];budget=0 if p['card_type']=='Trending' else 2*(p['max_level']-1)
    model=catalog['ovr_weights'][p['identity']['position']]
    weights={str(i):model['abilities'].get(stat,0) for i,stat in zip(catalog['ABILITIES'],catalog['stat_keys'])}
    boosts={}
    for bid in p.get('booster_ids',[]):
        b=next((b for b in catalog['boosters']+p.get('custom_boosters',[]) if b['id']==bid),None)
        if b and (not b.get('conditional') or p.get('conditional_boosters')):
            for i,n in b['effects'].items():boosts[str(i)]=boosts.get(str(i),0)+n
    states={0:(0.,{})}
    def cost(n):return sum(1+i//4 for i in range(n))
    for group in catalog['training_groups']:
        choices=[]
        for n in range(41):
            spent=cost(n)
            if spent>budget:break
            gain=sum(weights[str(i)]*(max(1,min(127,min(105,p['base_abilities'][str(i)]+n)+boosts.get(str(i),0)))-max(1,min(127,p['base_abilities'][str(i)]+boosts.get(str(i),0)))) for i in group['indices'])
            choices.append((spent,n,gain))
        next_states={}
        for used,(value,training) in states.items():
            for spent,n,gain in choices:
                total=used+spent
                if total>budget:continue
                if total not in next_states or value+gain>next_states[total][0]+1e-12:
                    next_states[total]=(value+gain,{**training,group['id']:n})
        states=next_states
    used,(_,p['training'])=max(states.items(),key=lambda row:(row[1][0],-row[0]))
    trained=dict(p['base_abilities'])
    for group in catalog['training_groups']:
        for i in group['indices']:trained[str(i)]=min(105,trained[str(i)]+p['training'][group['id']])
    return {'overall':calculate(p,catalog)['before_coach'],'level':p['max_level'],'training':p['training'],
            'spent':used,'budget':budget,'parameters':trained,'includes_player_boosters':True,'includes_coach':False}
