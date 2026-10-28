"""Local custom coaches. Native game records are never edited by preview selection."""
from pathlib import Path
import copy
import json
import os
import threading
import uuid

TACTICS = ('possession', 'short_counter', 'long_counter', 'side_attack', 'long_ball', 'overload')


def normalize_coach(value, abilities):
    if not isinstance(value, dict):
        raise ValueError('教练资料需要是对象')
    row = copy.deepcopy(value)
    row['uuid'] = str(uuid.UUID(row.get('uuid') or str(uuid.uuid4())))
    row['id'] = 'custom:' + row['uuid']
    row['type'] = 'custom'
    row['name'] = str(row.get('name') or '').strip()[:80]
    if not row['name']:
        raise ValueError('请填写教练姓名')
    row['name_en'] = str(row.get('name_en') or '')[:80]
    from coach_identity import normalize as normalize_identity
    row.update(normalize_identity(row))
    row['tactics'] = row.get('tactics') or {}
    if not isinstance(row['tactics'], dict):
        raise ValueError('教练战术资料格式不正确')
    for key in TACTICS:
        value = row['tactics'].get(key, 0 if key=='overload' else 70)
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError('战术熟练度请填写 0–100 的整数')
        row['tactics'][key] = value
    effects = row.get('effects') or {}
    if not isinstance(effects, dict) or any(str(k) not in abilities or type(v) is not int or not -20 <= v <= 20 for k, v in effects.items()):
        raise ValueError('教练能力加成请使用 26 项能力，范围为 -20 到 +20')
    row['effects'] = {str(k): v for k, v in effects.items() if v}
    from coach_portraits import normalize
    row['portrait'] = normalize(row.get('portrait'))
    from native_coach_links import normalize_slots
    row['linkups'] = normalize_slots(row.get('linkups'))
    from coach_models import normalize as normalize_model
    row['head_model'] = normalize_model(row.get('head_model'))
    return row


class CoachStore:
    def __init__(self, root, abilities):
        self.root = Path(root) / 'coaches'
        self.root.mkdir(exist_ok=True)
        self.abilities = abilities
        self.lock = threading.RLock()

    def list(self):
        rows, errors = [], []
        with self.lock:
            for path in self.root.glob('*.json'):
                try:
                    if path.stat().st_size > 256 * 1024:
                        raise ValueError('文件过大')
                    data = normalize_coach(json.loads(path.read_text(encoding='utf8')), self.abilities)
                    if data['uuid'] != path.stem:
                        raise ValueError('教练身份不一致')
                    rows.append(data)
                except (ValueError, OSError) as exc:
                    errors.append({'file': path.name, 'message': str(exc)})
        return {'rows': rows, 'errors': errors}

    def save(self, value):
        data = normalize_coach(value, self.abilities)
        if (data.get('head_model') or {}).get('asset_id'):
            from native_glb import Glb
            asset=self.root.parent/'assets'/data['head_model']['asset_id']
            if not asset.is_file():raise ValueError('教练 GLB 文件缺失，请重新导入')
            Glb(asset.read_bytes())
        if data.get('portrait'):
            from coach_portraits import pixels
            from types import SimpleNamespace
            pixels(data['portrait'],SimpleNamespace(root=self.root.parent))
        path = self.root / (data['uuid'] + '.json')
        with self.lock:
            if path.is_file():
                previous = path.read_bytes()
                backup = self.root.parent / 'backups' / ('coach-' + data['uuid'] + '-' + uuid.uuid4().hex[:8] + '.json')
                backup.write_bytes(previous)
            temp = path.with_name('.coach-' + uuid.uuid4().hex)
            with temp.open('w', encoding='utf8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        return {'coach': data, 'path': str(path)}
