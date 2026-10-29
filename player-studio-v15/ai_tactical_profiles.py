"""V17 whole-team tactical templates, using verified native role/grid enums.

Draw families, midfield groups and variants separately. Template multiplicity
must never make one midfield group more likely than another. Coordinates are
paired phase layouts; changing a label alone does not create a new formation.
"""
import copy

ROLE_NAMES = ('GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF')
BASES = (
    ('433', '4-3-3', 'GK CB CB LB RB DMF CMF CMF LWF RWF CF', 'GK CB CB LB RB DMF CMF CMF LMF RMF CF'),
    ('4213', '4-2-1-3', 'GK CB CB LB RB DMF CMF AMF LWF RWF CF', 'GK CB CB LB RB DMF CMF CMF LMF RMF CF'),
    ('4231', '4-2-3-1', 'GK CB CB LB RB DMF CMF LMF RMF AMF CF', 'GK CB CB LB RB DMF CMF LMF RMF AMF CF'),
    ('442', '4-4-2', 'GK CB CB LB RB DMF CMF LMF RMF CF CF', 'GK CB CB LB RB DMF CMF LMF RMF CF CF'),
    ('4411', '4-4-1-1', 'GK CB CB LB RB DMF CMF LMF RMF SS CF', 'GK CB CB LB RB DMF CMF LMF RMF SS CF'),
    ('4312', '4-3-1-2', 'GK CB CB LB RB DMF CMF CMF AMF CF CF', 'GK CB CB LB RB DMF CMF CMF CMF CF CF'),
    ('4222', '4-2-2-2', 'GK CB CB LB RB DMF CMF AMF AMF CF CF', 'GK CB CB LB RB DMF CMF LMF RMF CF CF'),
    ('451', '4-5-1', 'GK CB CB LB RB DMF CMF CMF LMF RMF CF', 'GK CB CB LB RB DMF CMF CMF LMF RMF CF'),
    ('4321', '4-3-2-1', 'GK CB CB LB RB DMF CMF CMF SS SS CF', 'GK CB CB LB RB DMF CMF CMF AMF AMF CF'),
    ('4132', '4-1-3-2', 'GK CB CB LB RB DMF LMF RMF AMF CF CF', 'GK CB CB LB RB DMF LMF RMF CMF CF CF'),
    ('424', '4-2-4', 'GK CB CB LB RB CMF CMF LWF RWF CF CF', 'GK CB CB LB RB CMF CMF LMF RMF CF CF'),
    ('343', '3-4-3', 'GK CB CB CB LMF RMF DMF CMF LWF RWF CF', 'GK CB CB CB LB RB DMF CMF LMF RMF CF'),
    ('3421', '3-4-2-1', 'GK CB CB CB LMF RMF DMF CMF AMF AMF CF', 'GK CB CB CB LB RB DMF CMF LMF RMF CF'),
    ('352', '3-5-2', 'GK CB CB CB LMF RMF DMF CMF AMF CF CF', 'GK CB CB CB LB RB DMF CMF CMF CF CF'),
    ('3142', '3-1-4-2', 'GK CB CB CB LMF RMF DMF CMF CMF CF CF', 'GK CB CB CB LB RB DMF CMF CMF CF CF'),
    ('523', '5-2-3', 'GK CB CB CB LB RB DMF CMF LWF RWF CF', 'GK CB CB CB LB RB DMF CMF LMF RMF CF'),
    ('532', '5-3-2', 'GK CB CB CB LB RB DMF CMF AMF CF CF', 'GK CB CB CB LB RB DMF CMF CMF CF CF'),
    ('541', '5-4-1', 'GK CB CB CB LB RB DMF CMF LMF RMF CF', 'GK CB CB CB LB RB DMF CMF LMF RMF CF'),
)
SUPPORTS = ('balanced', 'left_support', 'right_support', 'restrained')


def back_type(profile,phase='base'):
    if phase=='base':return int(profile['family'][0])
    return sum(r in (1,2,3) for r in profile[phase])


def _midfields(attack, defence, family):
    middle = [i for i, r in enumerate(attack) if r in (4, 5)]
    if len(middle) == 2:
        groups = (('double_anchor', (4, 4)), ('anchor_link', (4, 5)), ('double_link', (5, 5)))
    elif len(middle) == 3:
        groups = (('anchor_two_links', (4, 5, 5)), ('double_anchor_link', (4, 4, 5)), ('three_links', (5, 5, 5)))
    else:
        groups = (('single_anchor', tuple(attack[i] for i in middle)),)
    for name, roles in groups:
        a, d = list(attack), list(defence)
        for i, role in zip(middle, roles):
            a[i] = d[i] = role
        # A 3-5-2 / 5-3-2 also has a true flat-middle option, not another label
        # for the existing advanced playmaker arrangement.
        yield name, a, d
    if family in ('352', '532'):
        a, d = list(attack), list(defence)
        advanced = a.index(8); a[advanced] = d[advanced] = 5
        yield 'flat_middle', a, d


def profiles():
    result = []
    for family, name, astr, dstr in BASES:
        original_a = tuple(ROLE_NAMES.index(r) for r in astr.split())
        original_d = tuple(ROLE_NAMES.index(r) for r in dstr.split())
        for group, attack, defence in _midfields(original_a, original_d, family):
            for support in SUPPORTS:
                fronts = ('parallel', 'staggered', 'link_striker') if attack.count(12) == 2 else ('parallel',)
                for front in fronts:
                    a, d = list(attack), list(defence)
                    if front == 'link_striker':
                        slot = max(i for i, r in enumerate(a) if r == 12)
                        a[slot] = d[slot] = 11
                    ident = ':'.join((family, group, support, front))
                    result.append({'id': ident, 'family': family, 'name': name,
                                   'midfield_group': group, 'support': support, 'front': front,
                                   'attack': tuple(a), 'defence': tuple(d),
                                   'requires_central_cover': 4 not in a})
    return result


def draw_order(rng, candidates=None, previous=None):
    """Family -> midfield group -> whole variant, all with equal group odds."""
    candidates = profiles() if candidates is None else list(candidates)
    families = sorted({p['family'] for p in candidates}); rng.shuffle(families)
    result = []
    for family in families:
        rows = [p for p in candidates if p['family'] == family]
        groups = sorted({p['midfield_group'] for p in rows}); rng.shuffle(groups)
        for group in groups:
            variants = [p for p in rows if p['midfield_group'] == group]
            rng.shuffle(variants)
            variants.sort(key=lambda p: p['id'] == previous)
            result.extend(variants)
    # Avoid exactly repeating the preceding family+variant when alternatives
    # exist; overlapping individual player draws remain natural.
    result.sort(key=lambda p: p['id'] == previous)
    return result


def coordinates(profile, phase, style):
    roles = profile[phase]; groups = {}
    rows = [{'role': role, 'position_x': 0, 'position_y': 52} for role in roles]
    for i, role in enumerate(roles):
        groups.setdefault(role, []).append(i)
    depths = {0:3, 1:11, 2:16, 3:16, 4:20, 5:28, 6:31, 7:31, 8:36, 9:42, 10:42, 11:44, 12:46}
    for role, indices in groups.items():
        count = len(indices)
        if role in (2, 6, 9): lanes = [12] * count
        elif role in (3, 7, 10): lanes = [92] * count
        elif count == 1: lanes = [52]
        elif count == 2: lanes = [36, 68]
        elif count == 3: lanes = [30, 52, 74]
        elif count == 4 and role == 5: lanes = [30, 74, 30, 74]
        else: raise ValueError('Unsupported tactical role multiplicity')
        for i, lane in zip(indices, lanes):
            rows[i].update(position_x=depths[role], position_y=lane)
    central = [i for i,r in enumerate(roles) if r in (4, 5, 8)]
    if len(central) == 2 and abs(depths[roles[central[0]]]-depths[roles[central[1]]]) <= 8:
        for i,y in zip(central,(30,74)): rows[i]['position_y'] = y
    elif len(central) == 3 and len({roles[i] for i in central}) == 3:
        rows[groups[4][0]]['position_y'] = 30
        rows[groups[5][0]]['position_y'] = 74
    elif len(central) == 4 and len(groups.get(4,[])) == len(groups.get(8,[])) == 1:
        rows[groups[4][0]]['position_x'] = 19
        rows[groups[8][0]]['position_x'] = 36
    # Phase-dependent actual lines and width. A low wing-back becomes LB/RB;
    # wingers and advanced playmakers use their paired defensive role, so this
    # is not a uniform whole-team depth multiplier.
    if phase == 'defence':
        for row in rows:
            role = row['role']
            row['position_x'] = {0:3,1:10,2:12,3:12,4:19,5:27,6:26,7:26,8:35,9:39,10:39,11:37,12:44}[role]
            if role in (2,3,6,7): row['position_y'] = 10 if role in (2,6) else 94
    else:
        for row in rows:
            r = row['role']; left = r in (2,6); right = r in (3,7)
            if left or right:
                wingback = profile['family'] in ('343','3421','352','3142') and r in (6,7)
                base = 28 if wingback else row['position_x']
                support = profile.get('support','balanced')
                shift = -3 if support == 'restrained' else 4 if support == ('left_support' if left else 'right_support') else 0
                if support in ('left_support','right_support') and shift == 0: shift = -2
                row['position_x'] = base + shift + (2 if style in ('side_attack','overload') else 0)
        if profile.get('front') == 'staggered':
            forwards = groups.get(12,[])
            if len(forwards) == 2: rows[forwards[1]]['position_x'] = 43
        if profile.get('front') == 'link_striker':
            rows[groups[11][-1]]['position_y'] = 72
            rows[groups[12][0]]['position_y'] = 38
    strategy=profile.get('strategy')
    if phase=='attack' and strategy in ('chase','last_push','protect'):
        for row in rows:
            role=row['role']
            shift=({2:4,3:4,5:2,6:5,7:5,8:3}.get(role,0) if strategy=='last_push' else
                   {2:3,3:3,5:1,6:4,7:4,8:2}.get(role,0) if strategy=='chase'
                   else {2:-3,3:-3,5:-2,6:-4,7:-4,8:-2}.get(role,0))
            target=max(3,min(48,row['position_x']+shift))
            if all(other is row or abs(target-other['position_x'])>=7 or
                   abs(row['position_y']-other['position_y'])>=16 for other in rows):
                row['position_x']=target
    if len(groups.get(5,[])) == 4:
        for index,depth in zip(groups[5],(22,22,32,32)):
            rows[index]['position_x'] = depth
    if roles.count(11) == roles.count(12) == 1 and profile.get('front') != 'link_striker':
        rows[groups[11][0]]['position_x'] = 37
    validate(rows)
    return rows


def validate(rows):
    if len(rows) != 11 or sum(r['role'] == 0 for r in rows) != 1:
        raise ValueError('AI formation needs eleven players and one goalkeeper')
    for row in rows:
        if not 0 <= row['role'] < 13 or not 0 <= row['position_x'] <= 48 or not 0 <= row['position_y'] <= 104:
            raise ValueError('Invalid native formation grid')
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            # The grid's depth covers a much shorter range than its width.
            # This prevents the known mixed DMF/CMF collision and near stacks.
            if abs(a['position_x']-b['position_x']) < 7 and abs(a['position_y']-b['position_y']) < 16:
                raise ValueError('AI formation positions overlap')


def bench_roles(profile):
    """Twelve bench duties matched to the structure, not a fixed 12-role list."""
    a, d = profile['attack'], profile['defence']
    if a.count(1) == 3:
        roles = [0,1,1,2,3,4,5,6,7,8,12,12]
    elif a.count(12) + a.count(11) >= 2:
        roles = [0,1,1,2,3,4,5,6,7,8,12,12]
    else:
        roles = [0,1,1,2,3,4,5,6,7,8,9,10]
    if 8 not in a and 4 not in a:
        roles[5] = 5
    return tuple(roles)


def duties(players, on_field=None, roles=None):
    """Return workshop player indices, restricted to the proposed on-field set.

    Native duties refer to physical roster indices (0..39), not lineup slots.
    They happen to match these indices at initial team creation; dispatch after
    substitutions must resolve them against the observed native identity map.
    """
    indices = list(range(11)) if on_field is None else list(on_field)
    if not indices or len(set(indices))!=len(indices):raise ValueError('Invalid on-field duty identities')
    outfield = [i for i in indices if (roles.get(str(i)) if roles is not None else players[i]['parameters'][0]) != 0]
    if not outfield: outfield = indices
    def ranked(fields,foot=None,exclude=()):
        pool=[i for i in outfield if i not in exclude] or outfield
        def value(i):
            p=players[i]['parameters']
            return (sum(p[k]*weight for k,weight in fields)+
                    (16 if foot is not None and len(p)>43 and p[43]==foot else 0),-i)
        return sorted(pool,key=value,reverse=True)
    short=((27,3),(28,2),(20,1));first=ranked(short)[0]
    # Native six-duty order: longFK, shortFK, secondFK, leftCK, rightCK, PK.
    # Prefer an inswinging strong foot, with a small tie-break bonus. Ability
    # remains dominant; never turn an unskilled player into the best kicker.
    return {'captain':ranked(((40,1),(26,1),(35,1)))[0],
            'set_piece_taker':[ranked(((27,3),(22,2),(38,1),(28,1)))[0],first,
                ranked(short,exclude=(first,))[0],
                ranked(((22,3),(28,2),(27,1)),foot=0)[0],
                ranked(((22,3),(28,2),(27,1)),foot=1)[0],
                ranked(((20,3),(27,2),(28,1)))[0]],
            'df_overlap_setplay':ranked(((23,1),(39,1),(35,1)))[:3]}
