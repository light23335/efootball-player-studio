"""Validate the artifact produced by migration-ui.cjs against the real seed."""
import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.request

root = Path(__file__).absolute().parents[2]
sys.path.insert(0, str(root / 'player-studio'))
import player_package as pp

qa = root / '.work' / 'studio-qa'
r = json.loads((qa / 'migration-ui-result.json').read_text(encoding='utf8'))
expected = json.loads((qa / 'seed-expectation.json').read_text(encoding='utf8'))
cid, serial = expected['id'], expected['serial']
with pp.save_input(r['output']) as (db, meta, info), contextlib.closing(pp.connect(db, True)) as c, contextlib.closing(pp.connect(qa / 'seed.sqlite3', True)) as before:
    assert pp.snapshot(c, cid, serial) == expected['state']
    for table in ('gameplayers', 'careerplan', 'squads', 'coaches', 'warehouse', 'agents'):
        query = 'SELECT * FROM ' + table
        args = ()
        if table == 'gameplayers':
            query += ' WHERE NOT (id=? AND serial=?)'
            args = (cid, serial)
        assert sorted((tuple(v) for v in c.execute(query, args)), key=repr) == sorted((tuple(v) for v in before.execute(query, args)), key=repr), table
    assert r['package_id'] in pp.registry(c)
    newer = qa / 'newer.sqlite3'
    newer.write_bytes(db.read_bytes())
    save_meta = dict(meta)
with contextlib.closing(sqlite3.connect(newer)) as c, c:
    p = json.loads(c.execute('SELECT json FROM gameplayers WHERE id=? AND serial=?', (cid, serial)).fetchone()[0])
    p['level_info']['exp_total'] += 1
    c.execute('UPDATE gameplayers SET json=? WHERE id=? AND serial=?', (pp.compact(p), cid, serial))
data = newer.read_bytes()
save_meta['db_sha256'] = pp.digest(data)
newer_save = qa / 'newer.efsave'
newer_save.write_bytes(pp.archive_bytes({'manifest.json': pp.compact(save_meta).encode(), 'club.sqlite3': data}))
original_hash = pp.digest(newer_save.read_bytes())
import os
runtime = json.loads(Path(os.environ.get('STUDIO_RUNTIME', root / '.work/studio-final-test/runtime.json')).read_text(encoding='utf8'))
url = runtime['url'].split('/?')[0] + '/api/migration/plan'
token = runtime['url'].split('token=')[1]
request = urllib.request.Request(url, data=json.dumps({'save': str(newer_save), 'apk': str(root / '73efootball-V13.apk'), 'package': r['snapshot'], 'prefer': 'package'}).encode(), headers={'X-Studio-Token': token, 'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(request)
    raise AssertionError('old snapshot must be rejected')
except urllib.error.HTTPError as e:
    assert e.code == 400
    error = json.load(e)['error']
assert original_hash == pp.digest(newer_save.read_bytes())
r.update(complete_player_and_journal_equal=True, unrelated_tables_equal=True, source_backup_equal=Path(r['target']).read_bytes() == Path(r['backup']).read_bytes(), old_snapshot_rejected=True, old_snapshot_message=error)
(qa / 'migration-ui-result.json').write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps({k: r[k] for k in ('complete_player_and_journal_equal', 'unrelated_tables_equal', 'source_backup_equal', 'old_snapshot_rejected')}, ensure_ascii=False))
