"""Extract the supplied APK's offline coach definitions and mapped effects."""
from pathlib import Path
import json
import sqlite3
import zipfile

ROOT = Path(__file__).absolute().parent
TACTICS = ('possession', 'short_counter', 'long_counter', 'side_attack', 'long_ball')


def main():
    with zipfile.ZipFile(ROOT.parent / '73efootball-V13.apk') as z:
        prefix = 'assets/gateway-release/outputs/reference/'
        effects = json.loads(z.read(prefix + 'coach_boost_map.json'))
        rows = {}
        for source in ('SPECIAL_BOOSTER_COACHES.json', 'REQUESTED_COACHES.json'):
            for row in json.loads(z.read(prefix + source))['coaches']:
                prior = rows.get(str(row['coach_id']), {})
                rows[str(row['coach_id'])] = {**prior, **row}
        conn = sqlite3.connect(':memory:')
        conn.deserialize(z.read('assets/gateway-release/outputs/efootball/local-club.sqlite3'))
        for ident, payload in conn.execute('SELECT coach_id,json FROM coaches'):
            rows.setdefault(str(ident), {})['raw_payload'] = json.loads(payload)
        conn.close()
    result = []
    for ident, row in rows.items():
        raw = row['raw_payload']
        profile = row.get('provenance', {}).get('profile', {})
        name = row.get('display_name') or '初始教练'
        mapped, unknown = {}, []
        for ability in raw.get('ability_id', []):
            indices = effects.get(str(ability), [])
            for index in indices:
                mapped[str(index)] = mapped.get(str(index), 0) + 1
            if ability and not indices:
                unknown.append(ability)
        result.append({'id': ident, 'type': 'native', 'name': profile.get('chineseName') or name,
                       'name_en': profile.get('accentedName') or profile.get('name') or name,
                       'pack_title': row.get('pack_title', ''), 'age': raw.get('age'),
                       'tactics': {k: raw.get(k, 0) for k in TACTICS}, 'effects': mapped,
                       'unmapped_abilities': unknown, 'ability_ids': raw.get('ability_id', []),
                       'source': 'provided V13 offline coach catalogue', 'raw_payload': raw})
    result.sort(key=lambda row: (row['name'], row['id']))
    data = {'version': 1, 'coaches': result, 'effect_map': effects,
            'effect_basis': 'V13 developed_preview.coach_boosts: +1 for each mapped ability_id; no invented tactic multiplier'}
    (ROOT / 'resources/coaches.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'coaches': len(result), 'mapped_ability_ids': len(effects)}))


if __name__ == '__main__':
    main()
