"""Join the APK's verified definitions, localized identities and card aliases.

Development command; it only updates the editor catalogue, never either APK.
"""
from pathlib import Path
import csv
import gzip
import io
import json
import sqlite3
import sys
import zipfile
from card_types import editor_card_type

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT.parent / '.work/asset-tools/pes-tools'))
import cpk
import wesys


def main():
    c = sqlite3.connect(ROOT / 'resources/library.sqlite3')
    c.executescript('''CREATE TABLE IF NOT EXISTS card_aliases(before TEXT PRIMARY KEY,after TEXT);
        CREATE TABLE IF NOT EXISTS identities(kind TEXT,id INTEGER,name TEXT,name_en TEXT,
        PRIMARY KEY(kind,id));''')
    with zipfile.ZipFile(ROOT.parent / '73efootball-V13.apk') as z:
        live = cpk.Cpk(z.read('assets/gateway-release/livedata/dt870_mobile_and.cpk'))
        base = cpk.Cpk(z.read('assets/dt200_mobile_all.cpk'))
        def extract(container, name):
            f = next(f for f in container.files if f.name == name)
            return wesys.unpack_wesys_payload(container.read(f.path))
        aliases = list(csv.DictReader(io.StringIO(extract(live, 'filenameConvTable.csv').decode('utf8'))))
        c.executemany('INSERT OR REPLACE INTO card_aliases VALUES(:before,:after)', aliases)
        variations = extract(live, 'PlayerVariationDetail.bin')
        assert len(variations) % 168 == 0
        labels = {str(int.from_bytes(variations[i:i+8], 'little')):
                  variations[i+12:i+140].split(b'\0', 1)[0].decode('utf8')
                  for i in range(0, len(variations), 168)}
        # Mobile Country.bin: 1488 bytes, id bits 10..18, native localized strings.
        countries = extract(base, 'Country.bin')
        assert len(countries) % 1488 == 0
        ids = set()
        for off in range(0, len(countries), 1488):
            row = countries[off:off+1488]
            ident = (int.from_bytes(row[:8], 'little') >> 10) & 511
            en = row[288:358].split(b'\0')[0].decode('utf8')
            zh = row[858:928].split(b'\0')[0].decode('utf8')
            assert ident not in ids
            ids.add(ident)
            c.execute('INSERT OR REPLACE INTO identities VALUES(?,?,?,?)', ('nation', ident, zh or en, en))
        # Team.bin uses the published 1600-byte layout, including Chinese names.
        teams = extract(live, 'Team.bin')
        assert len(teams) % 1600 == 0
        for off in range(0, len(teams), 1600):
            row = teams[off:off+1600]
            ident = int.from_bytes(row[12:16], 'little') & 131071
            en = row[396:466].split(b'\0')[0].decode('utf8')
            zh = row[1036:1106].split(b'\0')[0].decode('utf8')
            if en or zh:
                c.execute('INSERT OR REPLACE INTO identities VALUES(?,?,?,?)', ('team', ident, zh or en, en))
        verified = json.loads(gzip.decompress(z.read('assets/gateway-release/outputs/reference/verified-card-update.json.gz')))
        count = 0
        for card in verified['cards']:
            payload = card.get('payload') or {}
            pid = str((payload.get('gameplayer_id') or {}).get('id', ''))
            row = c.execute('SELECT payload,source FROM players WHERE id=?', (pid,)).fetchone()
            if not row:
                continue
            old = json.loads(row[0])
            # Keep byte-level provenance and never replace an already complete local definition.
            if not old.get('_studio_unknown_level_limit'):
                continue
            limit = (payload.get('level_info') or {}).get('level_limit')
            if not card.get('level_limit_verified') or type(limit) is not int or not 1 <= limit <= 100:
                continue
            merged = {**old, **payload}
            merged.pop('_studio_unknown_level_limit', None)
            merged.pop('_studio_skill_ids', None)
            merged.pop('_studio_partial_skill_mapping', None)
            merged['_studio_level_evidence'] = card.get('level_evidence')
            c.execute('UPDATE players SET payload=?,level_limit=?,overall=COALESCE(?,overall),source=? WHERE id=?',
                      (json.dumps(merged, ensure_ascii=False, separators=(',', ':')), limit,
                       payload.get('_overall'), row[1]+' + 原包已校验资料', pid))
            count += 1
        reclassified = 0
        for pid, kind, raw in c.execute('SELECT id,card_type,payload FROM players').fetchall():
            payload = json.loads(raw)
            label = labels.get(pid, payload.get('_studio_card_label', ''))
            native = payload.get('_studio_native_card_class') or ('Epic' if kind == 'BigTime' else kind)
            display = editor_card_type(native, label)
            payload['_studio_card_label'] = label
            payload['_studio_native_card_class'] = native
            reclassified += display != kind
            c.execute('UPDATE players SET card_type=?,payload=? WHERE id=?',
                      (display, json.dumps(payload, ensure_ascii=False, separators=(',', ':')), pid))
        summary = json.loads(c.execute("SELECT value FROM meta WHERE key='summary'").fetchone()[0])
        summary['by_card_type'] = dict(c.execute('SELECT card_type,count(*) FROM players GROUP BY card_type'))
        c.execute("UPDATE meta SET value=? WHERE key='summary'", (json.dumps(summary, ensure_ascii=False),))
    c.commit()
    print(json.dumps({'verified_levels_added': count, 'card_aliases': len(aliases),
                      'reclassified_big_time': reclassified,
                      'identities': c.execute('SELECT count(*) FROM identities').fetchone()[0]}))
    c.close()


if __name__ == '__main__':
    main()
