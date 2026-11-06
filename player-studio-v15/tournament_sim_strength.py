"""Auditable ratings of the exact private tournament entry snapshot.

The native parameter layout is the one verified in resources/catalog.json
and resources/native-coach-attributes.json.  Trained wire parameters do NOT
contain player or coach booster effects.  Apply coach_formula's existing
float32 ability formula once; never train a wire player again or use its
cached/displayed OVR.  This module neither reads nor writes a player library.

The five category weights, spatial contribution weights and aptitude losses
are simulator policy, not a claim to reproduce the native match engine.
ClubGenerator's legal starters have full aptitude in both phases, so their
aptitude multiplier is exactly one.  Conditional positive boosts are not
assumed active without an explicit condition; this matches the generator's
conservative policy.  All these decisions are included in the returned audit.
"""
import copy
import hashlib
import json
import math

from coach_formula import displayed, factor


REVISION = 'tournament-actual-squad-five-ratings-v1'
CONTEXT = '_studio_sim_strength_context_v1'
TEAM_MARKER = '_studio_tournament_squad'
ROLE_NAMES = ('GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF',
              'AMF', 'LWF', 'RWF', 'SS', 'CF')
APTITUDE_INDEX = (13, 10, 11, 12, 6, 7, 8, 9, 5, 3, 4, 2, 1)
STYLE_WIRE = {'possession': 0, 'short_counter': 1, 'long_counter': 2,
              'side_attack': 4, 'long_ball': 3, 'overload': 5}
# Verified native 147-parameter indices, not catalogue regression indices.
ABILITIES = {
    14: 'attacking_awareness', 15: 'defensive_awareness', 16: 'goalkeeping_awareness',
    17: 'dribbling', 18: 'ball_control', 19: 'tight_possession', 20: 'finishing',
    21: 'low_pass', 22: 'lofted_pass', 23: 'heading', 24: 'tackling',
    25: 'aggression', 26: 'defensive_engagement', 27: 'set_piece', 28: 'curl',
    29: 'gk_catching', 30: 'gk_parrying', 31: 'gk_reflexes', 32: 'gk_reach',
    34: 'speed', 35: 'physical_contact', 36: 'balance', 37: 'kicking_power',
    38: 'acceleration', 39: 'jump', 40: 'stamina'}
METRIC_FIELDS = {
    'attack': {14: .25, 20: .35, 37: .12, 34: .08, 38: .12, 23: .08},
    'creation': {18: .20, 19: .15, 21: .30, 22: .20, 17: .15},
    'defence': {15: .35, 24: .30, 26: .20, 35: .10, 25: .05},
    'goalkeeping': {16: .25, 29: .15, 30: .15, 31: .30, 32: .15}}
# A forward's shooting cannot replace the defenders' actual defensive skills.
ROLE_WEIGHTS = {
    'attack': (0, .04, .18, .18, .12, .30, .65, .65, .85, 1, 1, 1.05, 1.2),
    'creation': (0, .12, .50, .50, .70, 1, .90, .90, 1.1, .65, .65, .65, .35),
    'defence': (0, 1.25, 1, 1, 1.1, .45, .25, .25, .10, .08, .08, .04, .04),
    'goalkeeping': (1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)}
# No native partial-aptitude multiplier has been decoded by this project.
APTITUDE_POLICY = {0: .70, 1: .85, 2: 1.0}
DEPTH_STARTER_WEIGHT = .80
DEPTH_BENCH_WEIGHT = .20
DEPTH_BENCH_CAP_ABOVE_STARTERS = 10.0
MAX_FIELD_REPLACEMENTS = 5


def _identity(player):
    ident = player.get('gameplayer_id', {})
    if any(type(ident.get(k)) is not int or ident[k] < 0 for k in ('id', 'serial')):
        raise ValueError('模拟阵容球员身份不完整')
    return ident['id'], ident['serial']


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _formations(team):
    squad = team.get('squad_data', {})
    plans = squad.get('squad_gameplan', {}).get('formation', [])
    if not isinstance(plans, list) or not plans or not isinstance(plans[0], dict):
        raise ValueError('模拟阵容缺少实际攻防比赛计划')
    plan = plans[0]
    phases = []
    for key in ('formation_offensive', 'formation_defensive'):
        rows = plan.get(key)
        if not isinstance(rows, list) or len(rows) != 11:
            raise ValueError('模拟阵容攻防站位必须各有11人')
        for row in rows:
            if not isinstance(row, dict) or type(row.get('role')) is not int or not 0 <= row['role'] < 13:
                raise ValueError('模拟阵容存在未知原生位置')
            for field, limit in (('position_x', 100), ('position_y', 104)):
                value = row.get(field)
                if type(value) is not int or not 0 <= value <= limit:
                    raise ValueError('模拟阵容实际站位坐标无效')
        if sum(r['role'] == 0 for r in rows) != 1:
            raise ValueError('模拟阵容每个阶段必须恰有一名门将')
        phases.append(rows)
    if next(i for i, r in enumerate(phases[0]) if r['role'] == 0) != next(i for i, r in enumerate(phases[1]) if r['role'] == 0):
        raise ValueError('模拟阵容攻防阶段的门将不是同一人')
    style = next((s for s, wire in STYLE_WIRE.items() if wire == plan.get('team_style')), None)
    if style is None:
        raise ValueError('模拟阵容缺少已核对的原生球队战术')
    return phases[0], phases[1], style


def _ordered_roster(team):
    rows = team.get('player_list')
    refs = team.get('squad_data', {}).get('player_list')
    if not isinstance(rows, list) or not isinstance(refs, list) or len(refs) != 23:
        raise ValueError('模拟赛需要实际入场的完整23人名单')
    pool = {}
    for row in rows:
        ident = _identity(row)
        if ident in pool:
            raise ValueError('模拟阵容包含重复球员实例')
        pool[ident] = row
    ids = [_identity(r) for r in refs]
    if len(set(ids)) != 23 or any(ident not in pool for ident in ids):
        raise ValueError('模拟阵容的入场引用与能力快照不一致')
    roster = [pool[ident] for ident in ids]
    order = team.get('squad_data', {}).get('squad_gameplan', {}).get('match_plan_settings', {}).get('order')
    if not isinstance(order, list) or len(order) < 23 or any(type(i) is not int for i in order[:23]) or set(order[:23]) != set(range(23)):
        raise ValueError('模拟阵容首发替补顺序无效')
    if any(type(i) is not int or i != 255 for i in order[23:]):
        raise ValueError('模拟阵容包含未知顺序占位')
    for player in roster:
        params = player.get('parameters')
        if not isinstance(params, list) or len(params) not in (147, 149) or any(type(i) is not int for i in params):
            raise ValueError('模拟球员必须使用实际147/149字段原生能力')
        if not 0 <= params[0] < 13 or any(params[i] not in (0, 1, 2) for i in APTITUDE_INDEX):
            raise ValueError('模拟球员位置熟练度布局无效')
        if any(not 0 <= params[i] <= 127 for i in ABILITIES):
            raise ValueError('模拟球员能力超出原生范围')
        level = player.get('level_info', {})
        if type(level.get('level')) is not int or type(level.get('level_limit')) is not int or not 1 <= level['level'] <= level['level_limit'] <= 100:
            raise ValueError('模拟赛缺少真实入场球员的培养等级')
    return [roster[i] for i in order[:23]], list(order[:23])


def _selected_coach(team, candidates):
    refs = team.get('squad_data', {}).get('coach', [])
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        raise ValueError('模拟阵容需要实际选择的一名教练')
    ident = refs[0].get('coach_id')
    exact = [c for c in candidates if c.get('payload', {}).get('coach_id') == ident]
    # Catalogue definitions are sometimes serial-zero while an owned copy has
    # its own serial. Effects belong to the same actual native coach ID.
    same = [c for c in candidates if c.get('payload', {}).get('coach_id', {}).get('id') == (ident or {}).get('id')]
    choices = exact or same
    if not choices:
        raise ValueError('模拟阵容所选教练的真实增能资料不完整')
    coach = copy.deepcopy(choices[0])
    payload = team.get('coach_data', {})
    if payload.get('coach_id') == ident:
        coach['payload'] = copy.deepcopy(payload)
    else:
        coach['payload']['coach_id'] = copy.deepcopy(ident)
    return coach


def snapshot_for_ratings(team, generator, conn, *, squad=None, player_pool=None):
    """Freeze the generator/entry's exact team and its real effect definitions.

    Optional ``squad`` and ``player_pool`` describe an already accepted entry
    plan, including its substitutions/reordered XI. No new squad is generated
    here. The caller persists/uses this very roster for simulation and entry.
    """
    out = copy.deepcopy(team)
    if CONTEXT in out and squad is None and player_pool is None:
        _ordered_roster(out)
        _formations(out)
        _context(out, None, None)
        return out
    if squad is not None:
        out['squad_data'] = copy.deepcopy(squad)
    if player_pool is not None:
        values = player_pool.values() if isinstance(player_pool, dict) else player_pool
        pool = {_identity(p): p for p in out.get('player_list', [])}
        pool.update({_identity(p): p for p in values})
        out['player_list'] = [copy.deepcopy(pool[_identity(ref)]) for ref in out['squad_data']['player_list']]
    roster, _ = _ordered_roster(out)
    _formations(out)
    document = generator.document()
    candidates = generator.coaches(conn)
    selected = _selected_coach(out, candidates)
    used = {bid for p in out['player_list'] for bid in p['parameters'][144:147]}
    known = document.get('preview_boosters', {})
    out[CONTEXT] = {
        'revision': REVISION, 'parameters_stage': 'max-trained-wire' if all(
            p['level_info']['level'] == p['level_info']['level_limit'] for p in roster) else 'trained-wire',
        'coach': selected,
        'preview_boosters': {str(b): copy.deepcopy(known[str(b)]) for b in used if str(b) in known},
        'empty_booster_ids': sorted({0, *document.get('division_squads', {}).get('empty_booster_ids', [])}),
        'native_booster_catalogue': copy.deepcopy(document.get('native_booster_catalogue')),
        'conditional_boosters_active': [],
        'ability_formula': 'coach_formula.displayed / float32 / applied once',
        'source': 'ClubGenerator actual private entry snapshot'}
    return out


def _context(team, document, coach):
    frozen = team.get(CONTEXT)
    if frozen is not None:
        if document is not None or coach is not None:
            raise ValueError('冻结的模拟快照不能再覆盖教练或增能上下文')
        if not isinstance(frozen, dict) or frozen.get('revision') != REVISION:
            raise ValueError('模拟评分上下文版本无效')
        context = frozen
    else:
        if not isinstance(team.get(TEAM_MARKER), dict) or document is None:
            raise ValueError('模拟评分缺少ClubGenerator快照及真实增能上下文')
        candidates = [coach] if coach is not None else list(document.get('division_squads', {}).get('coaches', []))
        for row in document.get('coaches', []):
            candidates.append({'payload': row['payload'], 'effects': row.get('effects', {})})
        roster, _ = _ordered_roster(team)
        context = {'revision': REVISION, 'parameters_stage': 'max-trained-wire' if all(
            p['level_info']['level'] == p['level_info']['level_limit'] for p in roster) else 'trained-wire',
                   'coach': _selected_coach(team, candidates),
                   'preview_boosters': document.get('preview_boosters', {}),
                   'empty_booster_ids': [0, *document.get('division_squads', {}).get('empty_booster_ids', [])],
                   'native_booster_catalogue': document.get('native_booster_catalogue'),
                   'conditional_boosters_active': []}
    if context.get('parameters_stage') not in ('trained-wire', 'max-trained-wire', 'effective-abilities'):
        raise ValueError('模拟能力加成阶段不明确，拒绝重复加成')
    selected = _selected_coach(team, [context['coach']])
    return context, selected


def _effects(raw):
    if not isinstance(raw, dict):
        raise ValueError('模拟能力增能资料无效')
    out = {}
    for index, value in raw.items():
        try:
            key = int(index)
        except (TypeError, ValueError):
            raise ValueError('模拟增能包含未知能力索引') from None
        if key not in ABILITIES or type(value) is not int or not -127 <= value <= 127:
            raise ValueError('模拟增能包含未核对能力或数值')
        out[key] = value
    return out


def _native_booster_missing(context,bid):
    catalogue=context.get('native_booster_catalogue')or{}
    ids=catalogue.get('ids')
    return (catalogue.get('revision')=='v17-compiled-booster-presence-v1'
            and catalogue.get('missing_record_policy')=='native-zero-record-0x823dfe4'
            and isinstance(catalogue.get('source_sha256'),str)and len(catalogue['source_sha256'])==64
            and isinstance(ids,list)and ids and all(type(i)is int and 0<=i<1024 for i in ids)
            and type(bid)is int and 0<bid<1024 and bid not in ids)


def _effective(player, context, coach, style):
    params = player['parameters']
    base = {i: params[i] for i in ABILITIES}
    boosts = {}
    details = []
    empty = set(context.get('empty_booster_ids', [0]))
    active = set(context.get('conditional_boosters_active', []))
    for bid in sorted(set(params[144:147]) - empty):
        if _native_booster_missing(context,bid):
            # Native 823dfe4 resolves an absent record to the bank's
            # dedicated zero-effect object. Keep the actual player ID;
            # do not invent a booster definition or rewrite the card.
            details.append({'id':bid,'missing_native_record':True,
                            'lookup_fallback':'native-zero-effect-record',
                            'authored_effects':None,'applied_effects':{}})
            continue
        bonus = context.get('preview_boosters', {}).get(str(bid))
        if bonus is None:
            raise ValueError('模拟球员缺少真实增能定义：' + str(bid))
        effects = _effects(bonus.get('effects', {}))
        conditional = bool(bonus.get('conditional'))
        applied = {i: min(0, n) if conditional and bid not in active else n for i, n in effects.items()}
        for i, amount in applied.items():
            boosts[i] = boosts.get(i, 0) + amount
        details.append({'id': bid, 'conditional': conditional, 'active': not conditional or bid in active,
                        'authored_effects': effects, 'applied_effects': applied})
    coach_boosts = _effects(coach.get('effects', {}))
    proficiency = coach['payload'].get(style)
    if type(proficiency) is not int or not 0 <= proficiency <= 100:
        raise ValueError('模拟阵容缺少当前战术的真实教练熟练度')
    multiplier = factor(proficiency)
    already = context['parameters_stage'] == 'effective-abilities'
    values = base.copy() if already else {
        i: displayed(base[i], boosts.get(i, 0), coach_boosts.get(i, 0), multiplier)
        for i in ABILITIES}
    return values, {'base': base, 'effective': values.copy(),
                    'player_boosters': details, 'coach_effects': coach_boosts,
                    'coach_proficiency': proficiency, 'coach_factor': multiplier,
                    'ability_formula_applications': 0 if already else 1,
                    'parameters_stage': context['parameters_stage']}


def _player_metrics(values):
    return {metric: sum(values[i] * weight for i, weight in fields.items())
            for metric, fields in METRIC_FIELDS.items()}


def _fit(player, role):
    return APTITUDE_POLICY[player['parameters'][APTITUDE_INDEX[role]]]


def _spatial_weight(metric, row):
    # Coordinates are actual native values. These small contribution changes
    # select who performs the task; they are not an extra native stat bonus.
    x = max(0, min(48, row['position_x'])) / 48
    if metric == 'attack':
        return .90 + .20 * x
    if metric == 'defence':
        return 1.10 - .20 * x
    if metric == 'creation':
        return .95 + .05 * (1 - abs(x - .55))
    return 1.0


def _role_quality(metrics, role):
    a, c, d = (metrics[k] for k in ('attack', 'creation', 'defence'))
    if role == 0:
        return metrics['goalkeeping']
    if role == 1:
        return .85 * d + .15 * c
    if role in (2, 3):
        return .55 * d + .30 * c + .15 * a
    if role == 4:
        return .55 * d + .45 * c
    if role == 5:
        return .55 * c + .25 * d + .20 * a
    if role in (6, 7):
        return .55 * c + .35 * a + .10 * d
    if role == 8:
        return .60 * c + .40 * a
    if role in (9, 10):
        return .65 * a + .35 * c
    if role == 11:
        return .75 * a + .25 * c
    return .90 * a + .10 * c


def _depth(roster, values, metrics, attack, defence):
    slots = [i for i, row in enumerate(attack) if row['role'] != 0]
    starter_quality = sum((_role_quality(metrics[i], attack[i]['role']) * _fit(roster[i], attack[i]['role']) +
                           _role_quality(metrics[i], defence[i]['role']) * _fit(roster[i], defence[i]['role'])) / 2
                          for i in slots) / len(slots)
    stamina = sum(values[i][40] for i in slots) / len(slots)
    # Distinct substitutes and distinct slots, at most five actual field
    # replacements. A universal reserve is never counted five times.
    options = []
    for index in range(11, 23):
        row = []
        for slot in slots:
            a, d = attack[slot]['role'], defence[slot]['role']
            if min(roster[index]['parameters'][APTITUDE_INDEX[a]], roster[index]['parameters'][APTITUDE_INDEX[d]]) != 2:
                row.append(None)
                continue
            quality = (_role_quality(metrics[index], a) + _role_quality(metrics[index], d)) / 2
            row.append(.80 * quality + .20 * values[index][40])
        options.append((index, row))
    # DP is bounded by 10 field slots and 12 bench players (638 masks <=5).
    states = {0: (0.0, ())}
    for index, candidates in options:
        updated = dict(states)
        for mask, (score, chosen) in states.items():
            if len(chosen) >= MAX_FIELD_REPLACEMENTS:
                continue
            for local, value in enumerate(candidates):
                bit = 1 << local
                if value is None or mask & bit:
                    continue
                target = mask | bit
                proposed = score + value
                if target not in updated or proposed > updated[target][0]:
                    updated[target] = (proposed, chosen + ((index, slots[local], value),))
        states = updated
    _, (total, chosen) = max(states.items(), key=lambda item: (len(item[1][1]), item[1][0], -item[0]))
    coverage = len(chosen)
    bench_raw = (total + 40 * (MAX_FIELD_REPLACEMENTS - coverage)) / MAX_FIELD_REPLACEMENTS
    cap = starter_quality + DEPTH_BENCH_CAP_ABOVE_STARTERS
    bench = min(bench_raw, cap)
    result = DEPTH_STARTER_WEIGHT * stamina + DEPTH_BENCH_WEIGHT * bench
    return result, {'starter_stamina': stamina, 'starter_role_quality': starter_quality,
                    'bench_raw': bench_raw, 'bench_capped': bench, 'bench_cap': cap,
                    'starter_weight': DEPTH_STARTER_WEIGHT, 'bench_weight': DEPTH_BENCH_WEIGHT,
                    'maximum_field_replacements': MAX_FIELD_REPLACEMENTS,
                    'covered_replacements': coverage,
                    'replacements': [{'bench_order': i, 'slot': slot, 'quality': quality}
                                     for i, slot, quality in chosen]}


def _penalty_plan(team, roster, order):
    settings = team['squad_data']['squad_gameplan'].get('match_plan_settings', {})
    duties = settings.get('set_piece_taker')
    first = duties[5] if isinstance(duties, list) and len(duties) > 5 else None
    if type(first) is not int or not 0 <= first < 23:
        first = None
    slot = order[:11].index(first) if first in order[:11] else None
    return {'native_first_taker_roster_index': first,
            'native_first_taker_starting_order': slot,
            'native_first_taker_on_field': slot is not None,
            'native_first_taker_gameplayer_id': copy.deepcopy(roster[slot]['gameplayer_id']) if slot is not None else None,
            'native_full_order': None, 'full_order_decoded': False,
            'source': 'native six-duty set_piece_taker[5]; physical roster index mapped through actual XI order'}


def ratings(team_snapshot, *, document=None, coach=None):
    """Return attack/creation/defence/goalkeeping/depth and an independent audit.

    Prefer ``ratings(snapshot_for_ratings(...))`` so replay remains independent
    of later catalogue/coach edits. Direct ClubGenerator snapshots can instead
    supply their exact document/coach. Inputs are never modified. Scores use
    the native ability scale (normally 40--120), not 23-player OVR totals.
    """
    roster, order = _ordered_roster(team_snapshot)
    attack, defence, style = _formations(team_snapshot)
    context, selected = _context(team_snapshot, document, coach)
    values, players = [], []
    for index, player in enumerate(roster):
        effective, audit = _effective(player, context, selected, style)
        values.append(effective)
        audit.update(order=index, roster_index=order[index], gameplayer_id=copy.deepcopy(player['gameplayer_id']),
                     is_starter=index < 11)
        players.append(audit)
    metrics = [_player_metrics(value) for value in values]
    result = {}
    raw = {}
    contribution = {}
    for metric in METRIC_FIELDS:
        layout = defence if metric in ('defence', 'goalkeeping') else attack
        denominator = 0.0
        total = 0.0
        unadjusted = 0.0
        rows = []
        for slot, position in enumerate(layout):
            role = position['role']
            weight = ROLE_WEIGHTS[metric][role] * _spatial_weight(metric, position)
            fit = _fit(roster[slot], role)
            value = metrics[slot][metric]
            total += value * fit * weight
            unadjusted += value * weight
            denominator += weight
            rows.append({'slot': slot, 'role': ROLE_NAMES[role], 'coordinates': copy.deepcopy(position),
                         'raw_metric': value, 'aptitude': roster[slot]['parameters'][APTITUDE_INDEX[role]],
                         'fit_multiplier': fit, 'task_weight': weight})
        if denominator <= 0:
            raise ValueError('模拟阵容缺少必要比赛职责')
        result[metric] = total / denominator
        raw[metric] = unadjusted / denominator
        contribution[metric] = rows
    result['depth'], depth = _depth(roster, values, metrics, attack, defence)
    raw['depth'] = depth['starter_stamina'] * DEPTH_STARTER_WEIGHT + depth['bench_raw'] * DEPTH_BENCH_WEIGHT
    if any(not math.isfinite(value) for value in result.values()):
        raise ValueError('模拟评分产生非有限数值')
    penalty_plan = _penalty_plan(team_snapshot, roster, order)
    # Hash the exact input abilities/entry plan and frozen effect definitions;
    # do not include unrelated names, portraits or cached OVR fields.
    source = {'roster': [{'gameplayer_id': p['gameplayer_id'], 'parameters': p['parameters'],
                           'level_info': p['level_info']} for p in roster],
              'order': order, 'attack': attack, 'defence': defence, 'style': style,
              'coach': selected, 'context': context, 'penalty_plan': penalty_plan}
    result['audit'] = {'revision': REVISION, 'snapshot_sha256': _digest(source),
                       'scale': 'native ability units; simulator category aggregation',
                       'source': 'actual 23-player entry roster/order/two-phase layout',
                       'all_max_level': all(p['level_info']['level'] == p['level_info']['level_limit'] for p in roster),
                       'actual_non_max_level': any(p['level_info']['level'] != p['level_info']['level_limit'] for p in roster),
                       'style': style,
                       'coach_id': copy.deepcopy(selected['payload']['coach_id']),
                       'parameter_layout': '147-native; catalog ABILITIES/native-coach-attributes evidence',
                       'metric_fields': copy.deepcopy(METRIC_FIELDS), 'raw_metrics': raw,
                       'players': players, 'contributions': contribution, 'depth': depth,
                       'penalty_plan': penalty_plan,
                       'starting_order': order[:11], 'bench_order': order[11:],
                       'aptitude_policy': dict(APTITUDE_POLICY),
                       'bench_influence': 'only depth; 20% of depth, five distinct legal replacements, starter quality +10 cap',
                       'conditional_policy': 'positive conditional effects inactive unless explicitly frozen active; negative effects retained',
                       'native_game_outcome_claimed': False}
    return result
