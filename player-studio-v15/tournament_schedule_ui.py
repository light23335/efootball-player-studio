"""Read-only, saved-state tournament presentation. No draw/advance/write calls.

The HTML is self contained so the existing local content service and native
in-game WebView can use the same bytes without a second resource server.
"""
import copy
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

import tournament_rules as rules

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'resources' / 'tournament_schedule_ui'
_EMBEDDED_ASSETS = None
PREFIX = 'player_studio_tournament_v1:'


def _emblem(entry):
    if not isinstance(entry,dict):
        return None
    uri=entry.get('uri','')
    if not isinstance(uri,str) or not uri.startswith('data:image/png;base64,') or len(uri)>100000:
        return None
    try:raw=base64.b64decode(uri.split(',',1)[1],validate=True)
    except ValueError:return None
    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(raw).hexdigest()!=entry.get('sha256'):
        return None
    return {k:entry[k] for k in ('uri','sha256','source','source_sha256','kind') if k in entry}


def _team(team, names, player, emblems):
    return {'id': team, 'name': str(names.get(str(team), names.get(team, '球队 ' + str(team)))),
            'own': team == player, 'emblem':_emblem(emblems.get(str(team),emblems.get(team)))} if team is not None else None


def _bracket(stage, fixtures, stage_index):
    """Include ungenerated rounds, but never predict a team or a result.

    The runtime sorts tie IDs as strings and pairs opposite ends. Preserve that
    exact graph (also at 128 teams); adjacent-card assumptions give wrong links.
    """
    size = 1 << (stage['input_count'] - 1).bit_length()
    rounds, previous = [], []
    r = 0
    while size > stage['output_count']:
        actual = {}
        for f in fixtures:
            if f['round'] == r:
                actual.setdefault(f['tie'], []).append(f)
        nodes = []
        ordered = sorted(previous, key=lambda n: n['id'])
        for pair in range(size // 2):
            key = f'{stage_index}:{r}:{pair}'
            legs = sorted(actual.get(key, []), key=lambda f: f['leg'])
            first = legs[0] if legs else None
            sources = [ordered[pair]['id'], ordered[-1-pair]['id']] if ordered else []
            nodes.append({'id': key, 'round': r, 'sources': sources,
                          'teams': [first['home'], first['away']] if first else [None, None],
                          'fixtures': [f['id'] for f in legs],
                          'winner': rules.tie_winner(legs) if legs else None,
                          'bye': bool(first and first.get('bye')),
                          'generated': bool(legs),
                          'rules': rules.round_rules(stage, size)})
        rounds.append({'index': r, 'size': size, 'name': {2: '决赛', 4: '半决赛', 8: '四分之一决赛'}.get(size, str(size) + ' 强'),
                       'generated': bool(actual), 'nodes': nodes})
        previous = nodes
        size //= 2
        r += 1
    return rounds


def presentation(current, names=None, emblems=None):
    """Return JSON-compatible display data without mutating the save or indexes."""
    names = names or {}
    emblems = emblems or {}
    definition = current['definition']
    player = definition['player_team_id']
    fixtures = copy.deepcopy(current['fixtures'])
    by_stage = {}
    for f in fixtures:
        # The runtime overloads "penalties": True means rule enabled before
        # play; [h,a] means an actual shootout after settlement. Separate them.
        f['penalties_allowed'] = definition['stages'][f['stage']]['type'] in ('knockout', 'playoff')
        if not isinstance(f.get('penalties'), list):
            f['penalties'] = None
        by_stage.setdefault(f['stage'], []).append(f)
    stages = []
    history = {h['stage']: h['tables'] for h in current.get('stage_history', [])}
    for i, s in enumerate(definition['stages']):
        rows = by_stage.get(i, [])
        status = 'complete' if current.get('completed') or i < current['stage_index'] else 'current' if i == current['stage_index'] else 'pending'
        tables = copy.deepcopy(history.get(i, []))
        if i == current['stage_index'] and s['type'] in ('groups', 'league') and not tables:
            tables = [rules.standings(current, g) for g in range(len(current.get('groups', [])))]
        groups = []
        for g, table in enumerate(tables):
            groups.append({'index': g, 'name': '联赛积分榜' if s['type'] == 'league' else (chr(65 + g) if g < 26 else str(g + 1)) + ' 组',
                           'teams': [row['team'] for row in table], 'table': table})
        # Original group order matters for the seed tiebreaker. Historical tables
        # already contain the original seed; no inferred draw is needed.
        byes = []
        if s['type'] in ('groups', 'league') and rows:
            for group in groups:
                roster = set(group['teams'])
                for r in range(s['rounds']):
                    active = {f[k] for f in rows if f.get('group') == group['index'] and f['round'] == r for k in ('home', 'away')}
                    byes.extend({'round': r, 'group': group['index'], 'team': t} for t in sorted(roster - active))
        stages.append({'index': i, 'name': s['name'], 'type': s['type'], 'status': status,
                       'rules': copy.deepcopy(s), 'groups': groups, 'byes': byes,
                       'fixture_ids': [f['id'] for f in rows],
                       'bracket': _bracket(s, rows, i) if s['type'] in ('knockout', 'playoff') and rows else []})
    pending = sorted((f for f in fixtures if f['stage'] == current['stage_index'] and not f['played']),
                     key=lambda f: (f['round'], f.get('leg', 1), f['id']))
    next_own = next((f for f in pending if player in (f['home'], f['away'])), None)
    own_played = sum(f['played'] and not f.get('bye') and player in (f['home'], f['away']) for f in fixtures)
    own_pending = any(player in (f['home'], f['away']) for f in pending)
    # State.entrants is the active stage's saved roster, including direct
    # qualifiers who bypass its playoff. Do not call next_fixture/due/advance.
    active = set(current.get('entrants', [])) | set(current.get('bypass', []))
    own_ties = [f for f in fixtures if f['stage'] == current['stage_index'] and 'tie' in f and player in (f['home'], f['away'])]
    eliminated = False
    if own_ties:
        last = max(own_ties, key=lambda f: (f['round'], f['leg']))
        same = [f for f in own_ties if f['tie'] == last['tie']]
        winner = rules.tie_winner(same)
        eliminated = winner is not None and winner != player
    own_status = 'champion' if current.get('champion') == player else 'complete' if current.get('completed') else 'eliminated' if eliminated else 'playing' if own_pending else 'waiting' if player in active else 'eliminated'
    difficulty = rules.difficulty(current)
    fingerprint = hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'version': 1, 'uuid': definition['uuid'], 'run_id': current['run_id'], 'save_sha256': fingerprint,
            'name': definition['name'], 'difficulty': difficulty, 'difficulty_name': rules.DIFFICULTIES[difficulty],
            'completed': current.get('completed', False),
            'champion': current.get('champion'), 'player_team_id': player, 'player_status': own_status,
            'player_played': own_played, 'stage_index': current['stage_index'],
            'current_round': pending[0]['round'] if pending else current.get('round', 0),
            'next_fixture_id': next_own['id'] if next_own else None,
            'teams': [_team(t, names, player, emblems) for t in definition['team_ids']], 'stages': stages, 'fixtures': fixtures}


def overview_html(current, names=None, emblems=None):
    data = json.dumps(presentation(current, names, emblems), ensure_ascii=False, separators=(',', ':'))
    # JSON lives in an inert script element. Escape HTML delimiters before
    # embedding even when a user names a team </script><script>… .
    data = data.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    def asset(name):
        return _EMBEDDED_ASSETS[name] if _EMBEDDED_ASSETS is not None else (ASSETS / name).read_text('utf8')
    return asset('index.html').replace('/*SCHEDULE_CSS*/', asset('schedule.css')).replace('/*SCHEDULE_JS*/', asset('schedule.js')).replace('SCHEDULE_DATA', data).encode('utf8')


def runtime_source(source=None, assets=None):
    """Build-time only: embed assets in the helper's pyc for Chaquopy.

    No virtual __file__ lookup and no extra Android static routes are required.
    Source/asset overrides also support the desktop compiler's extracted bundle.
    """
    source = source if source is not None else Path(__file__).read_text('utf8')
    folder = Path(assets) if assets is not None else ASSETS
    embedded = {name: (folder / name).read_text('utf8') for name in ('index.html', 'schedule.css', 'schedule.js')}
    marker = '_EMBEDDED_ASSETS = None'
    if source.count(marker + '\n') != 1:
        raise ValueError('赛程界面资源嵌入点改变')
    return source.replace(marker + '\n', '_EMBEDDED_ASSETS = ' + repr(embedded) + '\n', 1)


def read_saved(root, uid):
    """Read exactly one existing save. Missing saves stay missing."""
    uid = str(uuid.UUID(uid))
    path = (Path(root) / 'outputs/efootball/local-club.sqlite3').resolve()
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        row = conn.execute('SELECT value FROM meta WHERE key=?', (PREFIX + uid,)).fetchone()
    return json.loads(row[0]) if row else None


def saved_overview(root, uid, names=None, emblems=None):
    current = read_saved(root, uid)
    return overview_html(current, names, emblems) if current else None
