"""Random AI Division opponents. Game-side code uses only the standard library.

Opponents are private copies of current catalogue cards, never owned players.
The original prepare/start/finish transaction owns the per-match snapshot.
"""
import copy
import hashlib
import bisect
import json
import math
import random
import sqlite3
import struct
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from native_overall import rating as native_rating
import ai_tactical_profiles as tactics

REVISION = 'v17-division-library-v7-quality-and-type-bag'
MARKER = '_studio_division_squad_v1'
STYLES = ('possession', 'short_counter', 'long_counter', 'side_attack', 'long_ball', 'overload')
# Native UI switch 0x35099f8 / table0xc3d935: the wire enum places
# Long Ball at3 and Out Wide at4. The editor's display/bag order differs.
STYLE_WIRE = {'possession':0, 'short_counter':1, 'long_counter':2,
              'side_attack':4, 'long_ball':3, 'overload':5}
ROLE_NAMES = ('GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF')
# The aptitude array has its own native order, unlike the main-position enum.
APTITUDE_INDEX = (13, 10, 11, 12, 6, 7, 8, 9, 5, 3, 4, 2, 1)
STARTERS = (0, 1, 1, 2, 3, 4, 5, 8, 9, 10, 12)
BENCH = (0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 11, 12)
FORMATIONS = tactics.BASES
LAST_FORMATION = 'personal_ai_division_last_formation_v1'
MIX_STEPS = 5120
MIN_COACH_PROFICIENCY = 85
MAX_GENERATION_TRIALS = 48
TRAINING_REVISION = 'v17-native-max-training-v1'
# Stock V17 placeholders with flat 95 attributes and no original portrait.
# Identify these records, rather than excluding legitimate high-stat DIY cards.
STOCK_TEST_PERSON_IDS = frozenset((8554053, 8554076, 25331269))
# AI-only exact-card exclusions. Do not exclude an entire footballer, a name,
# a copied DIY card or the player's own usable catalogue/owned collection.
STOCK_AI_EXCLUDED_CARD_IDS = frozenset((
    89136418985304,8554053,8554076,25331269,89136418985305,
    89136418985307,89136418985314,89136418985306,89136418985308,
    89136418985311,89136418985310,89136418985313,89136418985302,
    89136418985303,89136418985312,89136418985315,88046312750111,
    88046292734664,89136418985301))
_LOCK = threading.RLock()


def quality_limits(minimum):
    return ((104,109,102,106) if minimum>=3400 else
            (102,106,100,103) if minimum>=3300 else (99,103,97,101))


def quality_report(scores,minimum):
    floor,mean,bench_floor,bench_mean=quality_limits(max(minimum,_strength_known(scores)))
    start,bench=scores[:11],scores[11:]
    return {'starter_min':min(start),'starter_mean':sum(start)/11,
            'bench_min':min(bench),'bench_mean':sum(bench)/12,
            'weakest_three_mean':sum(sorted(start)[:3])/3,
            'limits':dict(starter_min=floor,starter_mean=mean,bench_min=bench_floor,bench_mean=bench_mean),
            'passed':min(start)>=floor and sum(start)>=11*mean and min(bench)>=bench_floor and sum(bench)>=12*bench_mean}


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


# Native aggregation multiplies integer sums by three fixed float32 weights.
# Exact lookup tables avoid repeating float32 packing in every Gibbs probe.
_WEIGHTED_SUMS=tuple(tuple(f32(n*f32(weight)) for n in range(count*255+1))
                     for count,weight in ((11,1.8),(3,1.4),(5,.6)))


def strength(ratings):
    """V17 0x70a6324: descending 23, weights 1.8/1.4/1/.6, truncate.

    Individual inputs use the separately verified native integer rating kernel.
    A conservative stat/bonus lower bound keeps conditional effects optional.
    """
    if len(ratings) != 23 or any(type(n) is not int or not 0 <= n <= 255 for n in ratings):
        raise ValueError('AI 阵容必须包含 23 个有效的球员评分')
    return _strength_known(ratings)


def _strength_known(ratings):
    """Internal 23 native integer ratings; callers already established bounds."""
    r = sorted(ratings, reverse=True)
    a = _WEIGHTED_SUMS[0][sum(r[:11])]
    b = _WEIGHTED_SUMS[1][sum(r[11:14])]
    c = sum(r[14:18])
    d = _WEIGHTED_SUMS[2][sum(r[18:])]
    return min(9999, int(f32(f32(f32(a + b) + c) + d)))


def _required_rating_known(scores,index,minimum):
    values=list(scores);low,high=0,255
    while low<high:
        middle=(low+high)//2;values[index]=middle
        if _strength_known(values)>=minimum:high=middle
        else:low=middle+1
    return low


def proficiency_factor(value):
    value = f32(value)
    if value < 90:
        x = f32(value - 99)
        value = f32(f32(f32(f32(x * f32(x * -38)) / 99) / 99) + 104)
    else:
        slope = struct.unpack('<f', struct.pack('<I', 0x3d46a7f0))[0]
        offset = struct.unpack('<f', struct.pack('<I', 0x42c68189))[0]
        value = f32(f32(value * slope) + offset)
    return f32(value / 100)


def configuration(catalog, excluded, options=None):
    """Export only real coach payloads; no workstation files at game runtime."""
    enabled=(options or {}).get('enabled',True)
    if type(enabled) is not bool:raise ValueError('AI 随机组队开关无效')
    coaches = []
    for row in catalog.get('coaches', []):
        payload = row.get('raw_payload')
        if not isinstance(payload, dict) or not any(row.get('tactics', {}).get(k, 0) >= MIN_COACH_PROFICIENCY for k in STYLES):
            continue
        p = copy.deepcopy(payload)
        p.update(row.get('tactics', {}))
        coaches.append({'payload': p, 'effects': row.get('effects', {})})
    return {'enabled': enabled, 'revision': REVISION, 'minimum': 3200, 'top_minimum': 3300,
            'minimum_stars': 5, 'rating_method': 'v17-native-integer-lower-bound',
            'coach_minimum': MIN_COACH_PROFICIENCY, 'style_mode': 'shuffle_bag',
            'coaches': coaches, 'excluded_ids': sorted(map(str, excluded))}


def person(card):
    # All variants of an original footballer share the low 28-bit identity.
    identity=card.get('_studio_squad_person_id')
    if type(identity)is int and 0<identity<2**28:return identity
    return int(card['gameplayer_id']['id']) & 0xfffffff


def personal_identities(document):
    """Respect opt-in original-person links without merging independent DIYs."""
    result={}
    for row in document.get('players',[]):
        identity=row.get('identity')or{}
        bound=identity.get('bound_original_player_id')
        try:canonical=(int(bound)&0xfffffff)if bound else identity.get('independent_person_id',identity.get('person_id'))
        except (ValueError,TypeError):continue
        if type(canonical)is not int or not 0<canonical<2**28:continue
        owned=(row.get('owned')or{}).get('gameplayer_id')or{}
        aliases=[identity.get('card_id'),owned.get('id'),*identity.get('previous_card_ids',[])]
        for value in aliases:
            if type(value)is int and value>0:result[value]=canonical
    return result


class Generator:
    def __init__(self, document, developed, wire, caps, formation, teams, normalize, root=None):
        self.document = document
        self.developed = developed
        self.wire = wire
        self.caps = caps
        self.formation = formation
        self.teams = teams
        self.normalize = normalize
        self._trained = {}
        self._ratings = OrderedDict()
        self._prepared = {}
        self._pool_cache = {}
        self.sampling = {}
        self.root = Path(root) if root is not None else None
        self._load_cache()

    def _load_cache(self):
        if self.root is None:
            return
        try:
            data = json.loads((self.root / 'outputs/efootball/personal-ai-division-cache.json').read_text(encoding='utf8'))
            if data.get('training_revision') != TRAINING_REVISION and data.get('revision') not in (REVISION,'v17-division-library-v3-five-star-diversity'):
                return
            for key, value in data['rows'][:20000]:
                params = value.get('parameters', [])
                if len(key) == 2 and len(params) == 147 and all(type(n) is int for n in params) and 0 <= params[0] < 13:
                    self._trained[tuple(key)] = value
        except (OSError, ValueError, KeyError, TypeError):
            return

    def warm_pools(self, cards):
        pools = {role: [] for role in set(STARTERS + BENCH)}
        for card in cards:
            pools[card['parameters'][0]].append(card)
        return pools

    def warm(self):
        if self.root is None:
            return
        try:
            db = self.root / 'outputs/efootball/local-club.sqlite3'
            with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
                cards = self.cards(conn)
            pools = self.warm_pools(cards)
            for pool in pools.values():
                for card in pool:
                    self.trained(card)
            valid = {(int(c['gameplayer_id']['id']), c['_studio_fingerprint']) for c in cards}
            rows = [(k, v) for k, v in tuple(self._trained.items()) if k in valid][:20000]
            destination = db.with_name('personal-ai-division-cache.json')
            temporary = destination.with_suffix('.tmp')
            temporary.write_text(json.dumps({'revision': REVISION,'training_revision':TRAINING_REVISION,'rows':rows},separators=(',',':')),encoding='utf8')
            temporary.replace(destination)
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            return  # A cache miss can always be rebuilt by the request path.

    def cards(self, conn):
        document = self.document()
        bindings=personal_identities(document)
        custom_ids={int(r['identity']['card_id'])for r in document.get('players',[])if isinstance(r.get('identity',{}).get('card_id'),int)}
        blocked = set(document['division_squads'].get('excluded_ids', []))
        if conn.execute("select 1 from sqlite_master where name='excluded_catalog_ids'").fetchone():
            blocked.update(str(r[0]) for r in conn.execute("select card_id from excluded_catalog_ids where reason != 'China edition'"))
        rows = []
        for cid, fingerprint, raw in conn.execute('select card_id,fingerprint,payload from managed_cards order by card_id'):
            if str(cid) in blocked:
                continue
            if int(cid) in STOCK_AI_EXCLUDED_CARD_IDS and int(cid) not in custom_ids:
                continue
            try:
                p = json.loads(raw)
                if not isinstance(p,dict):continue
                p.pop('_studio_squad_person_id',None)
                if int(cid) in bindings:p['_studio_squad_person_id']=bindings[int(cid)]
                if not isinstance(p, dict) or type(p.get('default_rarity')) is not int or not 4 <= p['default_rarity'] <= 255:
                    continue
                params = p.get('parameters', [])
                if len(params) != 147 or type(params[0]) is not int or not 0 <= params[0] <= 12:
                    continue
                if int(p['gameplayer_id']['id']) != int(cid) or not person(p):
                    continue
                if int(cid) not in custom_ids and person(p) in STOCK_TEST_PERSON_IDS:
                    continue
                if any(type(n) is not int for n in params[:41]):
                    continue
                p['_studio_fingerprint'] = fingerprint or hashlib.sha256(raw.encode()).hexdigest()
                rows.append(p)
            except (ValueError, TypeError, KeyError):
                continue
        return rows

    def trained(self, card):
        key = (int(card['gameplayer_id']['id']), card['_studio_fingerprint'])
        cap = self.caps().get(key[0])
        required_level=max(cap or 1,card.get('level_info',{}).get('level_limit') or 1)
        cached=self._trained.get(key)
        if cached and cached.get('level_info',{}).get('level_limit',1)!=required_level:
            self._trained.pop(key,None)
        if key not in self._trained:
            p = copy.deepcopy(card)
            if cap and cap > (p.get('level_info', {}).get('level_limit') or 1):
                p.setdefault('level_info', {})['level_limit'] = cap
            self._trained[key] = self.developed.developed(p, {})
            level = self._trained[key].get('level_info', {})
            if level.get('level', 1) != level.get('level_limit', 1):
                raise ValueError('AI 球员满级培养失败，未下发未完成培养的球员')
        return self._trained[key]

    def prepared(self, card):
        key = (int(card['gameplayer_id']['id']), card['_studio_fingerprint'], self.document().get('revision'))
        if key not in self._prepared:
            self._prepared[key] = self.wire(copy.deepcopy(self.trained(card)), 'list')
        return self._prepared[key]

    def rating(self, card, coach, style, position=None):
        """Native lower bound: actual wire stats, native integer kernel, no fit loss.

        Require full position aptitude in the slot pool. Use the native 99 stat
        cap before boosters even where the client permits higher stats. Ignore
        positive conditional/link bonuses; include negative conditional effects.
        All native rating weights are non-negative, so this is a lower bound,
        not a regression estimate or an override of the client's displayed score.
        """
        p = self.prepared(card)
        position = p['parameters'][0] if position is None else position
        effects = coach.get('effects', {})
        proficiency = coach['payload'][style]
        key = (card['gameplayer_id']['id'], card['_studio_fingerprint'], proficiency,
               json.dumps(effects, sort_keys=True), self.document().get('revision'), position)
        if key not in self._ratings:
            params = list(p['parameters'][:147])
            boosts = {}
            for bid in set(params[144:147]):
                bonus = self.document().get('preview_boosters', {}).get(str(bid), {})
                for i, n in bonus.get('effects', {}).items():
                    amount = min(0, n) if bonus.get('conditional') else n
                    boosts[int(i)] = boosts.get(int(i), 0) + amount
            for i, amount in effects.items():
                boosts[int(i)] = boosts.get(int(i), 0) + amount
            factor = proficiency_factor(proficiency)
            for i in range(14, 41):
                if i == 33:
                    continue
                value = params[i]
                params[i] = max(40, min(99, value + int(f32(f32(factor * f32(value)) - f32(value)))))
            self._ratings[key] = native_rating(params, position, boosts)
            if len(self._ratings)>80000:self._ratings.popitem(last=False)
        else:self._ratings.move_to_end(key)
        return self._ratings[key]

    def coaches(self, conn):
        config = self.document()['division_squads']
        rows = {int(c['payload']['coach_id']['id']): copy.deepcopy(c) for c in config['coaches']}
        for definition in self.document().get('coaches', []):
            cid = int(definition['id'])
            rows[cid] = {'payload': copy.deepcopy(definition['payload']),
                         'effects': definition.get('effects', {})}
        for raw, in conn.execute('select json from coaches'):
            p = json.loads(raw)
            cid = int(p['coach_id']['id'])
            rows.setdefault(cid, {'effects': {}})['payload'] = p
        return list(rows.values())

    def positions(self, roster, role_codes=None, phase=None, style=None):
        roles = [ROLE_NAMES[r] for r in role_codes] if role_codes is not None else [ROLE_NAMES[p['parameters'][0]] for p in roster[:11]]
        result = self.formation(roles)
        # Native opponent_squad.formation_for_roles returns (roles, coords).
        # Reject a changed interface before sending a nested array to the client.
        if not isinstance(result, tuple) or len(result) != 2:
            raise ValueError('AI 原版阵型接口返回格式改变，未下发异常站位')
        chosen, coords = result
        if list(chosen) != roles or not isinstance(coords, list) or len(coords) != 11:
            raise ValueError('AI 原版阵型必须包含完整的 11 人位置')
        for role, row in zip(roles, coords):
            if not isinstance(row, dict) or row.get('role') != ROLE_NAMES.index(role):
                raise ValueError('AI 阵型位置编号与球员不一致')
            if any(type(row.get(k)) is not int or not 0 <= row[k] <= 100 for k in ('position_x', 'position_y')):
                raise ValueError('AI 阵型坐标无效，未下发异常站位')
        coords = copy.deepcopy(coords)
        if phase is not None:
            groups = {}
            for row in coords:
                groups.setdefault(row['role'], []).append(row)
            # The stock helper independently starts DMF/CMF at y=64/65.
            # Mixed central roles therefore collide even though neither role
            # is duplicated. Allocate lanes jointly across the midfield unit.
            central = [row for row in coords if row['role'] in (4, 5, 8)]
            if len(central) == 2:
                for row, y in zip(central, (30, 74)):
                    row['position_y'] = y
            elif len(central) >= 3:
                for role in (4, 5, 8):
                    rows = groups.get(role, [])
                    if len(rows) == 1:
                        rows[0]['position_y'] = 52
                    else:
                        for row, y in zip(rows, (30, 74)):
                            row['position_y'] = y
                # Three different single roles still need separate lanes.
                if len(central) == 3 and all(len(groups.get(r, [])) == 1 for r in (4, 5, 8)):
                    groups[4][0]['position_y'] = 30
                    groups[5][0]['position_y'] = 74
                # A diamond keeps its central anchor and tip far enough apart.
                if len(central) == 4 and len(groups.get(4, [])) == len(groups.get(8, [])) == 1:
                    groups[4][0]['position_x'] = 19
                    groups[8][0]['position_x'] = 36
            for role in (11, 12):
                rows = groups.get(role, [])
                if len(rows) == 2:
                    for row, y in zip(rows, (35, 69)):
                        row['position_y'] = y
            for row in coords:
                if row['role'] == 0:
                    continue
                if phase == 'defence':
                    row['position_x'] = max(8, round(row['position_x'] * .82))
                    row['position_y'] = round(52 + (row['position_y'] - 52) * .85)
                elif style in ('side_attack', 'overload') and row['role'] in (2, 3, 6, 7):
                    row['position_x'] = min(47, row['position_x'] + 3)
                elif style in ('short_counter', 'long_counter', 'long_ball') and row['role'] in (9, 10, 11, 12):
                    row['position_x'] = min(47, row['position_x'] + 2)
        return coords

    def repair_snapshot(self, conn, response):
        """Repair only workshop v1 opponent snapshots, keeping match identity."""
        marker = response.get(MARKER)
        if not isinstance(marker, dict) or marker.get('revision') != 'v17-division-library-v1':
            return False
        roster = response.get('player_list', [])
        if len(roster) != 23:
            raise ValueError('旧 AI 对手快照人数异常，已保留原数据')
        for player in roster:
            params = list(player['parameters'])
            cid = str(player['gameplayer_id']['id'])
            raw = conn.execute('select payload from managed_cards where card_id=?', (cid,)).fetchone()
            if raw:
                original = json.loads(raw[0]).get('parameters', [])
                if len(original) >= 14:
                    params[1:14] = original[1:14]
            params[APTITUDE_INDEX[params[0]]] = 2
            player['parameters'] = params
        coords = self.positions(roster)
        for plan in response['squad_data']['squad_gameplan']['formation']:
            plan['formation_offensive'] = copy.deepcopy(coords)
            plan['formation_defensive'] = copy.deepcopy(coords)
        marker.update(revision=REVISION, formation_repaired_from='v17-division-library-v1')
        return True

    @staticmethod
    def profiles():
        return tactics.profiles()

    def slot_pools(self, cards, coach, style, profile):
        requirements = list(zip(profile['attack'], profile['defence'])) + [(r, r) for r in tactics.bench_roles(profile)]
        signature = (tuple((c['gameplayer_id']['id'], c['_studio_fingerprint']) for c in cards),
                     json.dumps(coach, sort_keys=True), style, self.document().get('revision'))
        if self._pool_cache.get('signature') != signature:
            self._pool_cache = {'signature': signature, 'rows': {}, 'initializers': {}}
        stored = self._pool_cache['rows']
        cache = {}; pools = []
        for index, (attack, defence) in enumerate(requirements):
            key = (attack, defence, index >= 11)
            if key not in stored:
                rows = []
                for card in cards:
                    params = self.prepared(card)['parameters']
                    if params[APTITUDE_INDEX[attack]] != 2 or params[APTITUDE_INDEX[defence]] != 2:
                        continue
                    if profile.get('requires_central_cover') and attack == 5 and (params[15]+params[26] < 140 or params[40] < 65):
                        continue
                    if index >= 11:
                        score = self.rating(card, coach, style)
                    else:
                        score = min(self.rating(card, coach, style, attack), self.rating(card, coach, style, defence))
                    rows.append((card, score))
                stored[key] = sorted(rows, key=lambda row: (row[1], int(row[0]['gameplayer_id']['id'])))
            pools.append(stored[key])
        return pools

    @staticmethod
    def required_rating(scores, index, minimum):
        strength(scores)
        return _required_rating_known(scores,index,minimum)

    def select(self, cards, coach, style, minimum, rng, profile=None, maximum=3500):
        """Equal-weight target over feasible ordered squads, with finite mixing.

        Initialization is exponentially tilted solely to find a feasible state.
        The result is then mixed using uniform feasible single-slot Gibbs moves
        and symmetric uniform two-slot proposals. No top-N cut, strongest-card
        repair or DIY quota is used. Finite-chain mixing is not an assertion of
        independent, mathematically exact uniform output over every legal squad.
        """
        aggregate = _strength_known
        profile = profile or self.profiles()[1]
        source_pools = self.slot_pools(cards, coach, style, profile)
        limits=quality_limits(minimum)
        quality_pools=self._pool_cache.setdefault('quality_rows',{})
        pools=[]
        for i,pool in enumerate(source_pools):
            key=(id(pool),limits[i>=11 and 2 or 0])
            if key not in quality_pools:quality_pools[key]=[row for row in pool if row[1]>=key[1]]
            pools.append(quality_pools[key])
        def acceptable(values):
            total=aggregate(values)
            floor,mean,bench_floor,bench_mean=quality_limits(max(minimum,total))
            return (minimum<=total<=maximum and min(values[:11])>=floor and min(values[11:])>=bench_floor
                    and sum(values[:11])>=mean*11 and sum(values[11:])>=bench_mean*12)
        if any(not pool for pool in pools):
            return None
        if aggregate([pool[-1][1] for pool in pools]) < minimum:
            return None
        if aggregate([pool[0][1] for pool in pools]) > maximum:
            return None
        selected = None
        beta = 0.0
        # Scores have at most 256 values. Grouping them avoids recomputing
        # exp() for thousands of card variants on every initialization attempt.
        # Counts by footballer preserve the exact eligible-card weights after
        # excluding identities already used elsewhere in the squad.
        initializers=self._pool_cache.setdefault('initializers',{})
        bins=[]
        for pool in pools:
            key=id(pool)
            if key not in initializers:
                groups={};by_person={}
                for c,score in pool:
                    groups.setdefault(score,[]).append(c)
                    person_rows=by_person.setdefault(person(c),{})
                    person_rows[score]=person_rows.get(score,0)+1
                initializers[key]=(sorted(groups),groups,by_person)
            bins.append(initializers[key])
        for attempt in range(96):
            rows = []; used = set()
            derivative=0.0
            for levels,groups,by_person in bins:
                counts={score:len(groups[score]) for score in levels}
                for identity in used:
                    for score,count in by_person.get(identity,{}).items():counts[score]-=count
                eligible=[score for score in levels if counts[score]]
                if not eligible:
                    break
                anchor=eligible[-1] if beta>=0 else eligible[0]
                weights=[counts[score]*math.exp(beta*(score-anchor)) for score in eligible]
                total=sum(weights);mean=sum(s*w for s,w in zip(eligible,weights))/total
                derivative+=sum(w*(s-mean)**2 for s,w in zip(eligible,weights))/total
                score=rng.choices(eligible,weights=weights,k=1)[0]
                group=groups[score];c=None
                for _ in range(32):
                    candidate=rng.choice(group)
                    if person(candidate) not in used:c=candidate;break
                if c is None:c=rng.choice([c for c in group if person(c) not in used])
                chosen=(c,score)
                rows.append(chosen); used.add(person(chosen[0]))
            if len(rows) == 23 and acceptable([row[1] for row in rows]):
                selected = [row[0] for row in rows]
                scores = [row[1] for row in rows]
                break
            if len(rows) == 23:
                # Both tails matter when sampling a band: positive-only
                # initialization could never find a lower-strength squad from
                # a naturally very strong catalogue. This tilt only finds a
                # starting state; subsequent feasible mixing is unweighted.
                values=[row[1] for row in rows]
                error = max((minimum+maximum)/2-aggregate(values),
                            (limits[1]*11-sum(values[:11]))*2,(limits[3]*12-sum(values[11:]))*2)
                if aggregate(values)>maximum:error=(minimum+maximum)/2-aggregate(values)
                step=max(-.4,min(.4,error/max(50.,1.35*derivative)))
                beta = max(-4.,min(4.,beta+step))
        if selected is None:
            return None
        score_lists = [[row[1] for row in pool] for pool in pools]
        used = {person(c) for c in selected}
        changed = paired = 0
        for step in range(MIX_STEPS):
            if step % 5 == 4:
                left, right = rng.sample(range(23), 2)
                incoming_a, score_a = rng.choice(pools[left])
                incoming_b, score_b = rng.choice(pools[right])
                a, b = person(incoming_a), person(incoming_b)
                outside = used - {person(selected[left]), person(selected[right])}
                if a == b or a in outside or b in outside:
                    continue
                candidate = list(scores); candidate[left] = score_a; candidate[right] = score_b
                if not acceptable(candidate):
                    continue
                if incoming_a is not selected[left] or incoming_b is not selected[right]:
                    paired += 1
                selected[left], selected[right] = incoming_a, incoming_b
                scores = candidate; used = outside | {a, b}
                continue
            index = rng.randrange(23)
            required = _required_rating_known(scores, index, minimum)
            start = bisect.bisect_left(score_lists[index], required)
            # The native aggregation is monotonic in a single rating. Find
            # the upper conditional boundary, preserving the whole-team band.
            lo, hi = required, 256
            candidate = list(scores)
            while lo < hi:
                mid = (lo+hi)//2; candidate[index] = mid
                if mid == 256 or aggregate(candidate) > maximum: hi = mid
                else: lo = mid+1
            stop = bisect.bisect_left(score_lists[index], lo)
            group=scores[:11] if index<11 else scores[11:]
            needed=(limits[1]*11 if index<11 else limits[3]*12)-(sum(group)-scores[index])
            start=max(start,bisect.bisect_left(score_lists[index],needed))
            outside = used - {person(selected[index])}
            pool = pools[index]; chosen = None
            for _ in range(64):
                if start >= stop: break
                row = pool[rng.randrange(start, stop)]
                if person(row[0]) not in outside:
                    chosen = row; break
            if chosen is None:
                available = [row for row in pool[start:stop] if person(row[0]) not in outside]
                if not available:
                    continue
                chosen = rng.choice(available)
            card, score = chosen
            proposed=list(scores);proposed[index]=score
            if not acceptable(proposed):continue
            if card is not selected[index]:
                changed += 1
            selected[index], scores[index] = card, score
            used = outside | {person(card)}
        self.sampling = {'method': 'uniform-feasible-gibbs-and-symmetric-pairs',
                         'initialization_attempts': attempt + 1, 'proposals': MIX_STEPS,
                         'single_changes': changed, 'pair_changes': paired,
                         'fixed_top_card_repair': False, 'top_n_pool_limit': False,
                         'exact_independent_uniform_claimed': False}
        # Reorder the SAME sampled 23 when a materially stronger bench player
        # covers the starter's two-phase job and the outgoing player covers
        # the bench duty. Never inject a fixed strong core or alter abilities.
        lookup=[{int(c['gameplayer_id']['id']):s for c,s in pool}for pool in pools]
        swaps=0
        from ai_match_manager import task_value
        starts=list(range(1,11));rng.shuffle(starts)
        for left in starts:
            options=list(range(12,23));rng.shuffle(options)
            for right in options:
                inc,old=selected[right],selected[left]
                a=lookup[left].get(int(inc['gameplayer_id']['id']));b=lookup[right].get(int(old['gameplayer_id']['id']))
                if a is None or b is None or a<=scores[left]+6:continue
                role=profile['attack'][left]
                if task_value(self.prepared(old)['parameters'],role,'base',style)>task_value(self.prepared(inc)['parameters'],role,'base',style)+2:continue
                values=list(scores);values[left],values[right]=a,b
                if not acceptable(values):continue
                selected[left],selected[right]=inc,old;scores=values;swaps+=1;break
        self.sampling['same_roster_role_balance_swaps']=swaps
        self.sampling['accepted_strength_range'] = [minimum, maximum]
        self.sampling['quality']=quality_report(scores,minimum)
        return selected, scores

    def repair_plan_bench(self,cards,selected,ratings,coach,style,profile,minimum,maximum,rng,spec):
        """Try at most two bench-only repairs, preserving all eleven starters.

        Sample the eligible role pools, never insert a predetermined star or
        require the entire squad to be versatile. Full preflight still wins.
        """
        from ai_match_manager import pool_can_fill,tactical_catalogue,prepare_strategies
        missing=[kind for kind in ('chase','protect')if not spec['prepared'][kind]['available']]
        targets={kind:tactical_catalogue(profile,kind,style)[:18]for kind in missing}
        pools=self.slot_pools(cards,coach,style,profile);selected=list(selected);ratings=list(ratings)
        def coverage(players):
            return sum(any(pool_can_fill({'players':players},range(23),p)for p in rows)for rows in targets.values())
        value=coverage(spec['players']);changes=[]
        for _ in range(2):
            best=None;indices=list(range(12,23));rng.shuffle(indices)
            used={person(c)for c in selected}
            for i in indices:
                pool=pools[i]
                for card,score in rng.sample(pool,min(16,len(pool))):
                    if person(card) in used-{person(selected[i])}:continue
                    scores=list(ratings);scores[i]=score
                    if not minimum<=strength(scores)<=maximum or not quality_report(scores,minimum)['passed']:continue
                    players=list(spec['players']);players[i]={'parameters':self.prepared(card)['parameters']}
                    covered=coverage(players)
                    if covered>value:best=(i,card,scores,covered);break
                if best:break
            if best is None:break
            i,card,ratings,value=best;selected[i]=card;changes.append(i)
            spec=prepare_strategies(self,selected,coach,style,profile,spec['minimum'])
            if all(spec['prepared'][k]['available']for k in ('chase','protect')):break
        spec['bench_plan_repairs']=changes
        return selected,ratings,spec

    def build(self, conn, template, division, rng=None, style=None, previous_profile=None,formation_type=None):
        rng = rng or random.SystemRandom()
        document = self.document()
        cards = self.cards(conn)
        minimum = 3300 if division <= 3 else 3200
        style = rng.choice(STYLES) if style is None else style
        if style not in STYLES: raise ValueError('Invalid AI team style')
        coaches = [c for c in self.coaches(conn) if MIN_COACH_PROFICIENCY <= c['payload'].get(style, 0) <= 99]
        rng.shuffle(coaches)
        # Hundreds of visually different coaches may share the same rating
        # inputs. Probe each distinct effect/proficiency group before spending
        # the bounded budget testing another identical numeric setup.
        signatures=set();distinct_coaches=[]
        for c in coaches:
            signature=(c['payload'][style],json.dumps(c.get('effects',{}),sort_keys=True))
            if signature not in signatures:distinct_coaches.append(c);signatures.add(signature)
        coaches=distinct_coaches
        profiles = self.profiles()
        previous = conn.execute('select value from meta where key=?', (LAST_FORMATION,)).fetchone()
        try:
            previous_id = json.loads(previous[0]).get('id') if previous else None
        except (ValueError, TypeError, AttributeError):
            previous_id = None
        if previous_profile is not None:previous_id=previous_profile
        profiles = tactics.draw_order(rng, profiles, previous_id)
        if formation_type is None:
            from ai_division_sessions import preview_formation
            saved=conn.execute("select value from meta where key='personal_ai_division_draw_v2'").fetchone()
            state=json.loads(saved[0]) if saved else {}
            formation_type,_=preview_formation(state,rng)
        previous_family=previous_id.split(':',1)[0] if isinstance(previous_id,str)else None
        profiles.sort(key=lambda p:(tactics.back_type(p)!=formation_type,p['family']==previous_family))
        seen_requirements=set();search_profiles=[]
        for candidate in profiles:
            requirements=(candidate['attack'],candidate['defence'],tactics.bench_roles(candidate))
            if requirements not in seen_requirements:
                search_profiles.append(candidate);seen_requirements.add(requirements)
        result = None; profile = None
        preferred = (3400,3500) if rng.random() < .2 else (3300,3399)
        trials = 0
        # Limit expensive searches; randomize whole families/groups rather than
        # giving a family more weight because it contains more templates.
        from ai_match_manager import prepare_strategies
        spec=None;failures=[]
        # Exhaust the chosen defensive type before permitting a type fallback.
        searches=((True,preferred,16),(True,(minimum,3500),32),
                  (False,preferred,40),(False,(minimum,3500),MAX_GENERATION_TRIALS))
        for same_type,band,limit in searches:
            for candidate_profile in search_profiles:
                if (tactics.back_type(candidate_profile)==formation_type)!=same_type:continue
                if trials>=limit:break
                coach = coaches[(trials // 2) % len(coaches)] if coaches else None
                if coach is None: break
                trials += 1
                result = self.select(cards, coach, style, band[0], rng, candidate_profile, band[1])
                if result:
                    chosen,values=result
                    possible=prepare_strategies(self,chosen,coach,style,candidate_profile,minimum)
                    if not all(possible['prepared'][kind]['available'] for kind in ('chase','protect')):
                        chosen,values,possible=self.repair_plan_bench(cards,chosen,values,coach,style,candidate_profile,band[0],band[1],rng,possible)
                    if all(possible['prepared'][kind]['available'] for kind in ('chase','protect')):
                        result=(chosen,values);profile=candidate_profile;spec=possible;break
                    failures.append({'family':candidate_profile['family'],'reason':'No executable chase/protect plan for sampled 23'})
                    result=None
            if result: break
        if not result:
            raise ValueError('当前五星及以上可用卡与教练无法组成达到 ' + str(minimum) + ' 的 ' + style + ' AI 阵容')
        selected, ratings = result
        out = copy.deepcopy(template)
        roster = []
        for i, card in enumerate(selected):
            p = copy.deepcopy(self.prepared(card))
            params = list(p['parameters'])
            p['parameters'] = params + [0] * (149 - len(params))
            p['gameplayer_id'] = {'id': int(card['gameplayer_id']['id']), 'serial': 810000001 + i}
            p.update(uniform_number=i + 1, rental_match_left=0)
            roster.append(p)
        squad = out['squad_data']
        squad['player_list'] = [{'gameplayer_id': copy.deepcopy(p['gameplayer_id']), 'uniform_number': p['uniform_number']} for p in roster]
        coach_payload = copy.deepcopy(coach['payload'])
        squad['coach'] = [{'coach_id': copy.deepcopy(coach_payload['coach_id'])}]
        attack_coords = tactics.coordinates(profile, 'attack', style)
        defence_coords = tactics.coordinates(profile, 'defence', style)
        for plan in squad['squad_gameplan']['formation']:
            plan['formation_offensive'] = copy.deepcopy(attack_coords)
            plan['formation_defensive'] = copy.deepcopy(defence_coords)
            plan['is_position_edited'] = ['YES', 'YES']
            plan['use_multi_formation'] = 'YES'
            plan['team_style'] = STYLE_WIRE[style]
            for link in plan.get('coach_link_data', []):
                link.update(is_link_on='NO', key_member_Id=255, link_member_Id=255)
        settings = squad['squad_gameplan']['match_plan_settings']
        settings.update(order=list(range(23)) + [255] * 17, **tactics.duties(roster))
        out['player_list'] = roster
        out['coach_data'] = coach_payload
        teams = self.teams()
        team_id = int(rng.choice(list(teams)))
        out = self.normalize(out, team_id=team_id)
        attack_ratings = [self.rating(c, coach, style, profile['attack'][i]) if i < 11 else self.rating(c, coach, style) for i, c in enumerate(selected)]
        defence_ratings = [self.rating(c, coach, style, profile['defence'][i]) if i < 11 else self.rating(c, coach, style) for i, c in enumerate(selected)]
        out[MARKER] = {'revision': REVISION, 'division': division, 'minimum': minimum,
                       'native_lower_bound_strength': strength(ratings), 'conservative_strength': strength(ratings),
                       'native_attack_strength': strength(attack_ratings), 'native_defence_strength': strength(defence_ratings),
                       'individual_rating_method': 'v17-native-integer-lower-bound', 'native_aggregation_verified': True,
                       'actual_client_strength_measured': False, 'style': style, 'proficiency': coach_payload[style],
                       'minimum_stars': 5, 'eligible_cards': len(cards), 'formation_id': profile['id'], 'formation_name': profile['name'],
                       'ai_only_excluded_card_ids':sorted(STOCK_AI_EXCLUDED_CARD_IDS),
                       'formation_family': profile['family'], 'variant': {k:profile[k] for k in ('midfield_group','support','front')},
                       'preferred_strength_range': list(preferred), 'preferred_strength_met': preferred[0] <= strength(ratings) <= preferred[1],
                       'target_strength_range':list(preferred),'preferred_target_met':preferred[0]<=strength(ratings)<=preferred[1],
                       'strength_fallback_reason':None if preferred[0]<=strength(ratings)<=preferred[1] else 'Preferred band had no quality-qualified executable squad within the bounded search',
                       'quality':quality_report(ratings,band[0]),'requested_back_type':formation_type,
                       'base_back_type':tactics.back_type(profile),'attack_back_type':tactics.back_type(profile,'attack'),
                       'defence_back_type':tactics.back_type(profile,'defence'),
                       'formation_type_fallback':None if tactics.back_type(profile)==formation_type else {'requested':formation_type,'actual':tactics.back_type(profile),'reason':'Chosen type exhausted its bounded aptitude/quality/executable-plan search; proportions not guaranteed for this entry'},
                       'preflight_failures':failures,
                       'generation_trials': trials, 'all_players_max_level': all(p['level_info']['level'] == p['level_info']['level_limit'] for p in roster),
                       'attack_roles': list(profile['attack']), 'defence_roles': list(profile['defence']),
                       'secondary_position_starters': sum(c['parameters'][0] != profile['attack'][i] for i, c in enumerate(selected[:11])),
                       'sampling': dict(self.sampling), 'coach_id': coach_payload['coach_id'], 'base_team_id': team_id,
                       'card_ids': [p['gameplayer_id']['id'] for p in roster], 'ratings': ratings}
        out[MARKER]['tactical_spec']=spec
        out[MARKER]['prepared_strategies']=copy.deepcopy(spec['prepared'])
        # Legacy catalogue copies can retain a display cache from before
        # training (including values such as 13). Recompute this declared
        # card cache from the actual trained parameters and native kernel.
        # These are private opponent copies; owned cards and stats stay intact.
        for player,card in zip(out['player_list'],selected):
            score=self.rating(card,coach,style)
            player['disp_overall']=player['disp_max_overall']=score
        return out


def release_cached_opponent(conn):
    """Disable only the workshop opponent cache, retaining an exact backup.

    Original opponents, owned cards and division progress are untouched. A
    previous generated APK must not make the first native match reuse a DIY
    opponent after the user has disabled this feature in a new APK.
    """
    row=conn.execute("select value from meta where key='ai_division_active_match'").fetchone()
    if not row:return False
    active=json.loads(row[0])
    if not isinstance(active,dict) or not isinstance(active.get('opponent'),dict) or not active['opponent'].get(MARKER):
        return False
    if conn.in_transaction:raise ValueError('AI opponent restore requires a transaction boundary')
    with conn:
        conn.execute('begin immediate')
        conn.execute('insert or ignore into meta values(?,?)',
                     ('personal_ai_disabled_snapshot_v1:'+str(active.get('game_id','unknown')),row[0]))
        conn.execute("delete from meta where key='ai_division_active_match'")
    return True


def install(document, root, logic=None):
    import ai_division, developed_preview, club_store, opponent_squad, ziru_data, owned_coaches
    from ai_division_sessions import Entries, bridge
    import ai_match_runtime as coaching
    if getattr(ai_division.prepare, '_studio_division', False):
        return
    generator = Generator(document, developed_preview, club_store.wire_player,
                          opponent_squad.external_caps, opponent_squad.formation_for_roles,
                          ziru_data.teams, ziru_data.normalize_opponent_team, root)
    entries = Entries()
    enabled=lambda:document().get('division_squads',{}).get('enabled') is True
    if logic is not None: bridge(logic,entries,_LOCK,lambda:coaching.deactivate('accepted native entry exit'),enabled=enabled)
    previous = ai_division.prepare
    old_sync = owned_coaches.sync_opponent
    def sync(conn, response):
        if enabled() and response.get(MARKER) and response.get('coach_data', {}).get('coach_id') == response['squad_data']['coach'][0]['coach_id']:
            return
        return old_sync(conn, response)
    def prepare(conn, response, request):
        with _LOCK:
            if not enabled():
                coaching.deactivate('AI opponent feature disabled')
                release_cached_opponent(conn)
                return previous(conn,response,request)
            if conn.in_transaction:
                raise ValueError('AI division requires a transaction boundary')
            active_row = conn.execute("select value from meta where key='ai_division_active_match'").fetchone()
            active = json.loads(active_row[0]) if active_row else None
            entries.recover_committed_entry(conn,active)
            reusable = entries.reusable(conn,active)
            if active and reusable:
                snapshot = active
                opponent = copy.deepcopy(snapshot.get('opponent', {}))
                if generator.repair_snapshot(conn, opponent):
                    # The original prepare requires a clean transaction boundary.
                    # Repair only its opponent payload; save an exact backup first.
                    with conn:
                        conn.execute('insert or ignore into meta values(?,?)',
                                     ('personal_ai_formation_backup_v1:' + str(snapshot.get('game_id', 'unknown')), active_row[0]))
                        snapshot['opponent'] = opponent
                        conn.execute("update meta set value=? where key='ai_division_active_match'",
                                     (json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')),))
            entry = None
            if not reusable:
                division = int(ai_division.state(conn)['division'])
                rng = random.SystemRandom()
                entry = entries.draw(conn,active,rng,document()['division_squads'].get('style_mode','shuffle_bag'))
                response = generator.build(conn,response,division,rng,style=entry['style'],previous_profile=entry['previous_formation'],formation_type=entry['formation_type'])
                first=response[MARKER]['card_ids'][:11]
                previous_starters=entry.pop('previous_starters')
                response[MARKER]['previous_starting_card_overlap']=len(set(first)&set(previous_starters))
                response[MARKER]['previous_starting_identity_overlap']=len({c&0xfffffff for c in first}&{c&0xfffffff for c in previous_starters})
                entry['draw_state_after'].update(last_starters=first,last_formation=response[MARKER]['formation_id'],last_entry=entry['entry_id'])
                response[MARKER].update(entry_id=entry['entry_id'],process_id=entry['process_id'],
                                        draw_state_after=entry['draw_state_after'],style_mode=entry['draw_state_after']['style_mode'],base_game_id=entry['base_game_id'])
                response[MARKER]['tactical_spec']['entry_id']=entry['entry_id']
                if active:
                    with conn:
                        conn.execute('begin immediate')
                        active = entries.replace_active(conn,active,response,entry)
            result = previous(conn, response, request)
            report = result.pop(MARKER, None)
            if report:
                report = dict(report, game_id=result.get('game_id'))
                tactical_spec=report.pop('tactical_spec',None)
                if tactical_spec is not None:
                    tactical_spec.update(game_id=result['game_id'],entry_id=report.get('entry_id'))
                    tactical_spec['debug_external_status']=document().get('division_squads',{}).get('debug_external_status') is True
                    # V17 live CPU roster IDs use a32-bit foreign serial-2,
                    # padding, then the64-bit card ID. Wire serials remain
                    # unchanged. Original ABI probes and MuMu tests7/9/10
                    # verified full-roster scope plus actual plan/sub ACKs.
                    # Overall automatic-coaching capabilities remain separate.
                    tactical_spec['native_identity']={'layout':'serial32-padding32-card64','cpu_serial':-2,
                                                     'execution_verified':True,'source':'V17 native ABI probes; MuMu scoped plan and substitution ACK tests7/9/10'}
                    try:report['coaching']=coaching.activate(tactical_spec,root)
                    except Exception as error:
                        # Match preparation has already committed. A diagnostic
                        # bridge failure must not undo the native match/save.
                        coaching.deactivate('configuration failed')
                        report['coaching']={'status':'unavailable','error':str(error),'execution_enabled':False}
                if entry is not None:
                    entry['game_id']=result['game_id']
                    with conn:
                        conn.execute('begin immediate')
                        entries.commit(conn,entry,report)
                        entries.event(conn,entry['entry_id'],'opponent_prepared',{
                            k:report[k] for k in ('style','style_mode','proficiency','formation_id','native_lower_bound_strength')})
                report['runtime_revision'] = REVISION
                report['selection_rules_current'] = bool(report.get('formation_id') and report.get('individual_rating_method') == 'v17-native-integer-lower-bound')
                if report.get('formation_id'):
                    try:
                        with conn:
                            conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',
                                         (LAST_FORMATION, json.dumps({'id': report['formation_id'], 'game_id': result.get('game_id')})))
                    except sqlite3.Error:
                        pass  # Rotation history must not invalidate a committed match.
                destination = Path(root) / 'outputs/efootball/personal-ai-division-status.json'
                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                    if document().get('division_squads', {}).get('debug_external_status'):
                        import re
                        owner = re.match(r'^/data/(?:data|user/\d+)/([a-zA-Z0-9_.]+)/files(?:/|$)', Path(root).as_posix())
                        if owner:
                            external = Path('/storage/emulated/0/Android/data') / owner[1] / 'files/personal-ai-division-status.json'
                            external.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                except OSError:
                    pass  # A diagnostic file must not roll back a committed match.
            return result
    prepare._studio_division = True
    owned_coaches.sync_opponent = sync
    ai_division.prepare = prepare
    for module in tuple(sys.modules.values()):
        if not isinstance(module, type(sys)):
            continue
        for key, value in tuple(vars(module).items()):
            if value is previous:
                setattr(module, key, prepare)
    if enabled():threading.Thread(target=generator.warm, name='AI division card cache', daemon=True).start()
