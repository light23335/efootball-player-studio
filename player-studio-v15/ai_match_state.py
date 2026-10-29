"""Decode the normal V17 CPU eleven; uncertain/emergency states stay native.

Input must come from the scoped native channel (complete 23 card/serial pairs
and a non-human team). This decoder supplies facts to the policy, not permission
to execute: the runtime's separate capability proofs remain mandatory.
"""
import math
from ai_match_channel import decode_match_clock


def decode_normal(spec, raw, *, allow_reduced=False):
    try:
        if raw['game_id']!=spec['game_id'] or raw.get('entry_id')!=spec.get('entry_id'):
            return None
        if raw['team'] not in (0,1) or raw['phase'] not in (1,2):return None
        period=raw['period'];frames=raw['clock_frames']
        if type(frames) not in (int,float) or not math.isfinite(frames) or frames<0:return None
        clock=decode_match_clock(period,frames)
        phase='play' if raw['phase']==1 else 'stoppage'
        if period in (2,4,6):
            # Original native transitions reset the stage counter. These are
            # breaks at45/90/105; they are not additional playing periods.
            if raw['phase']!=2 or frames>60:return None
            clock={'minute':{2:45,4:90,6:105}[period],
                   'period_end':120 if period in (4,6) else 90}
            phase='halftime'
        if clock is None:return None
        players=raw['live']
        if len(players)!=23 or len(spec['players'])!=23:return None
        if [p['lineup_slot']for p in players]!=list(range(23)):return None
        identities=[p['expected_index']for p in players]
        physical=[p['physical_index']for p in players]
        if set(identities)!=set(range(23)) or len(set(physical))!=23 or any(type(i)is not int or not 0<=i<40 for i in physical):return None
        roles={};defence={};stamina={};unavailable=[];discipline={};yellow_risk={};on_field=[];departures={}
        for i,p in enumerate(players):
            index=p['expected_index'];energy=p['stamina'];key=str(index)
            health=[p.get(k) for k in ('yellow_count','direct_red','injury_state')]
            if any(v is not None for v in health):
                if (any(type(v) is not int for v in health) or
                    not 0<=health[0]<=2 or health[1] not in (0,1) or not 0<=health[2]<2**32):return None
                discipline[key]={'yellow_count':health[0],'direct_red':bool(health[1]),
                                 'dismissed':health[0]>=2 or bool(health[1]),'injury_state':health[2]}
                # A nonzero injury word has no established severity mapping.
                # Let native injury/GK handlers act; do not invent one here.
                if i<11 and (health[0]>=2 or health[1] or health[2]):
                    # A card/injury alone is not proof the actor has left.
                    # Wait for the original active flag to clear and for the
                    # native emergency queue to finish. No eleventh replacement
                    # is invented when the player has actually departed.
                    if not allow_reduced or i==0 or p['native_flag_4202']!=0:return None
                    if p['native_flag_4218'] not in (0,1):return None
                    unavailable.append(index)
                    departures[key]='dismissed' if health[0]>=2 or health[1] else 'native_inactive_injured'
                    continue
            if i<11:
                # Live baseline: active4202=1, secondary4218=0. The native
                # eligible getter is substitution-candidate eligibility:
                # after a normal substitution the active entrant returns0.
                # Do not guess whether a departure means injury, red card,
                # replay or another native state; yield the entire plan.
                if (p['native_flag_4202'],p['native_flag_4218'])!=(1,0):return None
                a,d=p['attack_role'],p['defence_role']
                if any(type(r)is not int or not 0<=r<=12 for r in (a,d)):return None
                if (i==0)!=(a==0 and d==0) or (i and (a==0 or d==0)):return None
                roles[key]=a;defence[key]=d
                on_field.append(index)
                if health[0]==1 and clock['minute']>=60 and a in (1,2,3,4) and energy<55:
                    yellow_risk[key]='high'
            elif not p['eligible'] or discipline.get(key,{}).get('dismissed') or discipline.get(key,{}).get('injury_state',0):
                unavailable.append(index);continue
            if type(energy) not in (int,float) or not math.isfinite(energy) or not 0<=energy<=100:return None
            stamina[key]=energy
        score=raw['score']
        if len(score)!=2 or any(type(v)is not int or not 0<=v<=50 for v in score):return None
        left,windows,pending=(raw[k]for k in ('substitutions_left','windows_left','native_pending'))
        if any(type(v)is not int or not 0<=v<=40 for v in (left,windows,pending)):return None
        out={'entry_id':spec.get('entry_id'),'game_id':spec['game_id'],'sequence':raw['sequence'],
             'human_controlled':False,'coherent':True,'paused':False,'replay':False,
             'phase':phase,'period':period,'minute':clock['minute'],'period_end':clock['period_end'],
             'clock_frames':frames,'score':list(score),'on_field':on_field,
             'bench':[i for i in identities[11:]if i not in unavailable],'unavailable':unavailable,
             'roles':roles,'defence_roles':defence,'stamina':stamina,
             'substitutions_left':left,'windows_left':windows,'native_pending_count':pending,
             'safe_to_change':phase in ('stoppage','halftime'),
             'safe_to_queue':pending==0 and left>0 and (windows>0 or phase=='halftime'),
             # Publication is allowed during play, but native mutation happens
             # ONLY in 6c4ce44's original CPU tactical-update callback. MuMu's
             # actual alternate-shape ACK and held-plan readback confirm this
             # boundary; no worker thread calls engine plan setters directly.
             'native_formation_window':phase=='play' and pending==0,
             'state_source':'v17_scoped_normal_eleven',
             'discipline_source':'v17_original_entry_cards_and_injury_word' if len(discipline)==23 else 'unknown; original emergency handling retained'}
        if discipline:out['discipline']=discipline
        if yellow_risk:out['yellow_risk']=yellow_risk
        if not 7<=len(on_field)<=11:return None
        if departures:
            if len(discipline)!=23 or pending:return None
            out.update(departures=departures,state_source='v17_scoped_confirmed_reduced_lineup')
        for k in ('ack_id','ack_status','rejection_reason'):
            if k in raw:out[k]=raw[k]
        return out
    except (KeyError,TypeError,ValueError,IndexError):
        return None


def decode_match(spec,raw):
    """Admit confirmed departures; unknown injury severity/emergency GK stay native."""
    return decode_normal(spec,raw,allow_reduced=True)
