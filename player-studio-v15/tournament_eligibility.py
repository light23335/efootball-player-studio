"""Read-only tournament roster inspection; warnings never block manual picks.

Random selection requires eleven real, distinct club/country people. The
strict 23/two-keeper/two-phase aptitude result is diagnostic only: an eligible
short or position-incomplete pool uses the tournament-only fallback builder.
Pending local projects are inspection identities, never fabricated game cards.
"""
import copy
import json
from contextlib import closing

import ai_tactical_profiles as tactics
from division_squads import (APTITUDE_INDEX, ROLE_NAMES, native_card_ids,
                             STOCK_AI_EXCLUDED_CARD_IDS, STOCK_TEST_PERSON_IDS as _STOCK_TEST_PERSON_IDS)
from tournament_identity import native_person_key, person, personal_identities

STOCK_TEST_PERSON_IDS=frozenset(map(native_person_key,_STOCK_TEST_PERSON_IDS))

REVISION = 'tournament-real-xi-fallback-v1'
MIN_REAL_STARTERS = 11


def _aptitudes(card):
    params = card.get('parameters', [])
    if (not isinstance(params,list) or len(params) not in (147,149) or
        any(type(n) is not int for n in params[:147]) or not 0<=params[0]<13 or
        any(params[i] not in (0,1,2) for i in APTITUDE_INDEX)):
        return None
    return tuple(params[i] for i in APTITUDE_INDEX)


def _strict(people, profiles):
    if len(people) < 23 or sum(any(a[0] == 2 for a in rows) for rows in people.values()) < 2:
        return False
    signatures = set()
    for profile in profiles:
        slots = tuple(zip(profile['attack'], profile['defence'])) + ((0, 0),)
        if slots in signatures:
            continue
        signatures.add(slots)
        pools = [[pid for pid, rows in people.items() if any(a[r] == a[d] == 2 for a in rows)] for r, d in slots]
        if any(not pool for pool in pools):
            continue
        assigned = {}
        def place(slot, seen):
            for pid in pools[slot]:
                if pid in seen:
                    continue
                seen.add(pid)
                if pid not in assigned or place(assigned[pid], seen):
                    assigned[pid] = slot
                    return True
            return False
        if all(place(slot, set()) for slot in sorted(range(12), key=lambda i: len(pools[i]))):
            return True
    return False


def _status(people, profiles=None):
    profiles = tactics.profiles() if profiles is None else profiles
    count = len(people)
    keepers = sum(any(a[0] == 2 for a in rows) for rows in people.values())
    strict = _strict(people, profiles)
    reasons = []
    if count < 11:
        reasons.append('fewer_than_11_real_people')
    if count < 23:
        reasons.append('fewer_than_23_real_people')
    if keepers < 2:
        reasons.append('fewer_than_two_full_goalkeepers')
    if count >= 23 and keepers >= 2 and not strict:
        reasons.append('no_strict_two_phase_formation')
    mode = 'strict' if strict else 'fallback' if count >= 11 else 'insufficient'
    warning = ('只有 '+str(count)+' 名真实不同球员，无法组成11人首发；可补充本队/同国籍DIY。' if count < 11 else
               '原队 '+str(count)+' 人；严格23人组队失败时保留真实熟练度排首发，缺额仅以随机满级普卡补替补。' if not strict else '')
    return {'revision': REVISION, 'eligible': count >= 11, 'random_eligible': count >= 11,
            'manual_allowed': True, 'export_allowed': True, 'real_people': count,
            'current_people': count, 'full_goalkeepers': keepers, 'strict_possible': strict,
            'fallback_required': count >= 11 and not strict, 'mode': mode,
            'reason': reasons[0] if reasons else None, 'reasons': reasons, 'warning': warning,
            'standard_bench_needed': max(0, 23-count) if count >= 11 else 0}


def inspect_cards(cards, profiles=None):
    people = {}
    for card in cards:
        apt = _aptitudes(card)
        if apt is not None:
            people.setdefault(person(card), []).append(apt)
    return _status(people, profiles)


def load_eligibility_index(library, document):
    """Parse the library once; pass the returned index to all four UI modes."""
    with closing(library.db()) as conn:
        source = [(str(cid), json.loads(raw), kind) for cid, raw, kind in
                  conn.execute('select id,payload,card_type from players')]
    valid = native_card_ids(document)
    if valid is None:
        valid = {int(cid) for cid, _, _ in source}
        valid.update(int(row.get('identity', {}).get('card_id') or 0) for row in document.get('players', []))
    rows = {cid: (card, kind, False) for cid, card, kind in source}
    custom = {int(row.get('identity', {}).get('card_id') or 0) for row in document.get('players', [])}
    packages = {int(row.get('identity', {}).get('card_id') or 0): row.get('identity', {}).get('package_id')
                for row in document.get('players', [])}
    for row in document.get('players', []):
        card = row.get('owned')
        if isinstance(card, dict) and isinstance(card.get('gameplayer_id'), dict):
            rows[str(card['gameplayer_id']['id'])] = (copy.deepcopy(card), 'DIY', True)
    bindings = personal_identities(document)
    blocked = {str(row['id']) for row in document.get('catalogue_recycle_bin', [])}
    blocked.update(map(str, document.get('division_squads', {}).get('excluded_ids', [])))
    records = []
    for cid, (card, kind, diy) in rows.items():
        try:
            ident = int(cid)
            if ident not in valid or cid in blocked or int(card['gameplayer_id']['id']) != ident:
                continue
            apt = _aptitudes(card)
            if apt is None:
                continue
            diy = diy or ident in custom or bool(card.get('_personal_player_uuid'))
            pid = bindings.get(ident, person(card))
            if pid in STOCK_TEST_PERSON_IDS and not diy:
                continue
            records.append({'id': ident, 'person': pid, 'apt': apt, 'diy': diy,
                            'stock_excluded': ident in STOCK_AI_EXCLUDED_CARD_IDS and not diy,
                            'club': int(card.get('initial_base_team_id') or 0),
                            'native_national': int(card.get('initial_base_national_team_id') or 0),
                            'nation': int(card.get('_nation_id') or 0), 'kind': kind, 'pending': False,
                            'package': packages.get(ident) or card.get('_personal_player_uuid')})
        except (KeyError, TypeError, ValueError):
            continue
    local = {}
    identities = library.identities() if document.get('tournament_local_projects') else {}
    nations = {}
    for row in identities.get('nation', []):
        nations.setdefault(row.get('name'), set()).add(int(row['id']))
    for project in document.get('tournament_local_projects', []):
        package = project.get('package_id')
        identity = project.get('identity') or {}
        if not package:
            continue
        team = identity.get('team_id')
        nation = identity.get('nation_id')
        if not nation:
            matches = nations.get(identity.get('nationality'), set())
            nation = next(iter(matches)) if len(matches) == 1 else 0
        if type(team) is not int or team <= 0:
            continue
        apt = tuple(project.get('position_aptitudes', {}).get(role, 0) for role in ROLE_NAMES)
        if any(type(n) is not int or n not in (0, 1, 2) for n in apt):
            continue
        bound = identity.get('bound_original_player_id')
        if not bound and identity.get('bind_original_player') is True:
            bound = identity.get('original_player_id') or (project.get('source_player') or {}).get('id')
            if not bound:
                continue
        try:
            if bound and (isinstance(bound,bool) or not str(bound).isascii() or not str(bound).isdigit() or not 0<int(bound)<2**63):
                continue
            pid = native_person_key(bound) if bound else ('local-project', str(package))
            if not pid:continue
        except (ValueError, TypeError):
            continue
        local[str(package)] = {'id': None, 'person': pid, 'apt': apt, 'diy': True,
                               'stock_excluded': False, 'club': team, 'native_national': 0,
                               'nation': int(nation or 0), 'kind': 'DIY', 'pending': True, 'package': str(package)}
    # A local edit supersedes an imported DIY of the same package only for
    # inspection. It never reserves a card ID or edits the imported record.
    records = [row for row in records if str(row.get('package')) not in local]
    records.extend(local.values())
    clubs, nation_rows, native_rows = {}, {}, {}
    for row in records:
        clubs.setdefault(row['club'], []).append(row)
        if row['nation']:
            nation_rows.setdefault(row['nation'], []).append(row)
        if row['native_national']:
            native_rows.setdefault(row['native_national'], []).append(row)
    return {'records': records, 'clubs': clubs, 'nations': nation_rows, 'native_national': native_rows,
            'team_nations': copy.deepcopy(document.get('tournament_national_team_nations', {})),
            'teams': [int(t['id']) for t in library.identities().get('team', [])] if hasattr(library, 'identities') else [],
            'profiles': tactics.profiles(), 'cache': {}}


def eligible_teams(library, document, team_ids=None, *, include_diy=True, cpu=True, index=None):
    index = load_eligibility_index(library, document) if index is None else index
    teams = index['teams'] if team_ids is None else list(map(int, team_ids))
    result = {}
    for team in teams:
        key = (team, bool(include_diy), bool(cpu))
        if key in index['cache']:
            result[str(team)] = copy.deepcopy(index['cache'][key])
            continue
        nation = index['team_nations'].get(str(team))
        family = [int(t) for t, n in index['team_nations'].items() if n == nation] if nation is not None else []
        if nation is None:
            rows = index['clubs'].get(team, [])
        else:
            combined = index['nations'].get(int(nation), [])[:]
            for alias in family:
                combined.extend(index['clubs'].get(alias, []))
                combined.extend(index['native_national'].get(alias, []))
            rows = combined
        people, baseline, pending = {}, {}, set()
        for row in rows:
            if nation is not None and row['nation']>0 and row['nation']!=int(nation):
                continue
            if cpu and row['stock_excluded']:
                continue
            if not row['diy']:
                baseline.setdefault(row['person'], []).append(row['apt'])
            if row['diy'] and not include_diy:
                continue
            people.setdefault(row['person'], []).append(row['apt'])
            if row['pending']:
                pending.add(row['person'])
        status = _status(people, index['profiles'])
        status.update(source_people=len(baseline), current_people=len(people),
                      diy_people_added=len(set(people)-set(baseline)),
                      local_pending_export=len(pending), include_diy=bool(include_diy), cpu=bool(cpu))
        index['cache'][key] = status
        result[str(team)] = copy.deepcopy(status)
    return result
