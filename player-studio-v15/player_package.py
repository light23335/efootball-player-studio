"""Portable single-player snapshots for 73efootball V13. Python 3.10+, stdlib only.

This edits exported saves, never a running game's database or an APK.
Client assets and new native player definitions require a separate adapter.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

FORMAT = "73efootball-personal-player"
VERSION = 1
MAX_DB = 512 * 1024 * 1024
MAX_JSON = 8 * 1024 * 1024
REGISTRY_KEY = "personal_player_packages_v1"
REQUIRED = {
    "meta": {"key", "value"},
    "gameplayers": {"id", "serial", "json", "source", "acquired_at"},
    "careerplan": {"id", "serial", "category", "points", "at"},
    "squads": {"squad_id", "json"},
    "warehouse": {"id", "serial"},
    "managed_cards": {"card_id", "fingerprint", "payload", "card_type", "subtype", "evidence"},
    "managed_serials": {"card_id", "next_serial"},
    "owned_identity_aliases": {"id", "old_serial", "new_serial"},
}
PROFILE = "73efootball-v13-147-v1"
KNOWN_TRIGGERS = {
    "owned_serial_positive_insert": "CREATE TRIGGER owned_serial_positive_insert before insert on gameplayers when NEW.serial<=0 begin select raise(ABORT,'owned serial must be positive'); end",
    "owned_serial_positive_update": "CREATE TRIGGER owned_serial_positive_update before update of serial on gameplayers when NEW.serial<=0 begin select raise(ABORT,'owned serial must be positive'); end",
}
for _table in ("managed_members", "managed_cards"):
    for _operation in ("insert", "update"):
        _name = f"excluded_{_table}_{_operation}"
        KNOWN_TRIGGERS[_name] = (f"CREATE TRIGGER {_name} BEFORE {_operation} ON {_table} "
            "WHEN CAST(NEW.card_id AS TEXT) IN (SELECT card_id FROM excluded_catalog_ids) BEGIN SELECT RAISE(IGNORE); END")


class PackageError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PackageError(message)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def value_hash(value):
    return digest(compact(value).encode("utf-8"))


def integer(value, label, low=0):
    require(type(value) is int and low <= value <= 2**63 - 1, f"{label} 必须是有效整数")
    return value


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "JSON 含重复字段")
            result[key] = value
        return result
    require(len(data) <= MAX_JSON, "JSON 过大")
    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda s: (_ for _ in ()).throw(PackageError("JSON 非有限数")))


def atomic_new(path, data):
    path = Path(path).resolve()
    require(not path.exists(), f"输出已存在，拒绝覆盖：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    try:
        with part.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # Windows rename refuses an existing destination. POSIX link provides
        # the same atomic, no-overwrite publication semantics on local disks.
        if os.name == "nt":
            os.rename(part, path)
        else:
            os.link(part, path)
    finally:
        part.unlink(missing_ok=True)
    return path


def archive_bytes(members):
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(members.items()):
            z.writestr(name, data)
    return buffer.getvalue()


def checked_zip(path, max_total=1024 * 1024 * 1024):
    z = zipfile.ZipFile(path)
    try:
        entries = z.infolist()
        require(len(entries) <= 4096, "压缩包文件数量过多")
        names = [e.filename for e in entries]
        require(len(set(names)) == len(names), "压缩包含重复文件名")
        total = 0
        for e in entries:
            p = PurePosixPath(e.filename)
            require(not p.is_absolute() and ".." not in p.parts and "\\" not in e.filename and ":" not in e.filename,
                    "压缩包路径无效")
            require(not e.is_dir() and not e.flag_bits & 1, "不接受目录项或加密 ZIP")
            require(e.file_size <= MAX_DB, "压缩包单文件过大")
            total += e.file_size
        require(total <= max_total, "压缩包展开后过大")
        return z
    except BaseException:
        z.close()
        raise


def connect(path, readonly=False):
    c = sqlite3.connect(Path(path).resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA trusted_schema=OFF")
    return c


def schema(c):
    result = {}
    for table, columns in REQUIRED.items():
        kind = c.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
        require(kind is not None and kind[0] == "table", f"不兼容的存档表：{table}")
        description = [dict(r) for r in c.execute(f'PRAGMA table_info("{table}")')]
        require(columns <= {r["name"] for r in description}, f"缺少存档列：{table}")
        result[table] = description
    return result


def check_player(p, cid, serial,allow_partial_original=False):
    integer(cid, "card_id", 1)
    integer(serial, "serial", 1)
    require(isinstance(p, dict), "球员数据必须是对象")
    require(p.get("gameplayer_id") == {"id": cid, "serial": serial}, "球员身份与记录不一致")
    parameters = p.get("parameters")
    require(isinstance(parameters, list) and len(parameters) == 147 and all(type(x) is int for x in parameters),
            "只支持已核对的 V13 147 项参数布局；新布局需要适配")
    info = p.get("level_info")
    require(isinstance(info, dict), "缺少等级与培养数据")
    partial=allow_partial_original and not p.get('_personal_player_uuid')
    for key in ("level", "level_limit", "exp_total", "customize_point"):
        if partial and key!='level' and info.get(key) is None:continue
        integer(info.get(key), key, 1 if key in ("level", "level_limit") else 0)
    if info.get('level_limit') is not None:require(info["level"] <= info["level_limit"], "等级高于等级上限")
    for key in ("games", "goal", "assist"):
        if key in p:
            integer(p[key], key)
    for key in ("_careerplan_base_parameters",):
        if key in p:
            require(isinstance(p[key], list) and len(p[key]) == 147, f"{key} 布局不兼容")


def check_db(path):
    with contextlib.closing(connect(path, True)) as c:
        require([tuple(r) for r in c.execute("PRAGMA integrity_check")] == [("ok",)], "SQLite 完整性检查失败")
        desc = schema(c)
        for row in c.execute("SELECT id,serial,json FROM gameplayers"):
            # Unselected stock cards can have an unknown cap and incomplete
            # progression in the supplied game. Preserve them byte for byte;
            # snapshot()/load_package() still strictly validate selected data.
            check_player(read_json(row["json"]), row["id"], row["serial"],True)
        for row in c.execute("SELECT json FROM squads"):
            read_json(row[0])
        return {"user_version": c.execute("PRAGMA user_version").fetchone()[0], "schema": desc}


@contextlib.contextmanager
def save_input(path):
    path = Path(path).absolute()
    require(path.is_file(), f"存档不存在：{path}")
    with tempfile.TemporaryDirectory(prefix="efplayer-") as temp:
        db = Path(temp) / "club.sqlite3"
        if path.suffix.lower() == ".efsave":
            with checked_zip(path, MAX_DB + MAX_JSON) as z:
                require(set(z.namelist()) == {"manifest.json", "club.sqlite3"}, "不是兼容的 .efsave")
                require(z.getinfo("manifest.json").file_size <= 16384, "存档清单过大")
                meta = read_json(z.read("manifest.json"))
                require(meta.get("format") == "73efootball-save" and type(meta.get("version")) is int and meta["version"] == 1,
                        "存档格式不兼容")
                integer(meta.get("offline_id"), "offline_id", 1)
                integer(meta.get("source_id"), "source_id", 1)
                require(meta["offline_id"] != meta["source_id"], "存档身份冲突")
                with z.open("club.sqlite3") as src, db.open("wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                require(digest(db.read_bytes()) == meta.get("db_sha256"), "存档 SHA256 校验失败")
        else:
            require(path.suffix.lower() in (".sqlite3", ".sqlite", ".db"), "请使用游戏导出的 .efsave 或关闭后的 SQLite 快照")
            require(path.stat().st_size <= MAX_DB, "数据库过大")
            with contextlib.closing(connect(path, True)) as src, contextlib.closing(sqlite3.connect(db)) as out:
                src.backup(out)
                out.execute("PRAGMA journal_mode=DELETE")
            meta = None
        info = check_db(db)
        if meta:
            with contextlib.closing(connect(db, True)) as c:
                user = c.execute("SELECT value FROM meta WHERE key='user_id'").fetchone()
                require(user is not None and int(user[0]) == meta["source_id"], "存档身份不匹配")
        yield db, meta, info


def native_fingerprint(apk):
    with zipfile.ZipFile(apk) as z:
        name = "lib/arm64-v8a/libUE4.so"
        require(name in z.namelist(), "不是支持的 Android ARM64 游戏 APK")
        h = hashlib.sha256()
        with z.open(name) as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        try:
            release = json.loads(z.read("assets/gateway-release/release-manifest.json"))["release_id"]
        except (KeyError, ValueError):
            release = "unknown"
        return {"native_engine_sha256": h.hexdigest(), "release_id": release}


def compatible_engine(source,target,profile,target_apk=None):
    if source==target:return True
    path=Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/'resources/migration-compatibility.json'
    pairs=json.loads(path.read_text(encoding='utf8')).get('verified_upgrades',[]) if path.is_file() else []
    if any(row.get('source_engine')==source and row.get('target_engine')==target and row.get('profile')==profile for row in pairs):return True
    if target_apk is not None and profile==PROFILE:
        try:
            from engine_compatibility import detect
            detect(target_apk,path.parent,native_fingerprint(target_apk)['release_id'])
            return True
        except (OSError,ValueError,KeyError):return False
    return False


def registry(c):
    row = c.execute("SELECT value FROM meta WHERE key=?", (REGISTRY_KEY,)).fetchone()
    result = read_json(row[0]) if row else {}
    require(isinstance(result, dict), "个人球员登记损坏")
    return result


def instance_binding(entry,cid,serial):
    if not entry:return None
    if (entry.get('card_id'),entry.get('serial'))==(cid,serial):return entry
    return (entry.get('instances') or {}).get(f'{cid}:{serial}')


def instance_pairs(entry):
    yield entry.get('card_id'),entry.get('serial')
    for value in (entry.get('instances') or {}).values():
        yield value.get('card_id'),value.get('serial')


def rows_for(c, table, cid, serial):
    return [dict(r) for r in c.execute(f'SELECT * FROM "{table}" WHERE id=? AND serial=? ORDER BY rowid', (cid, serial))]


def snapshot(c, cid, serial):
    row = c.execute("SELECT * FROM gameplayers WHERE id=? AND serial=?", (cid, serial)).fetchone()
    require(row is not None, "找不到指定的持有球员实例，请同时核对 ID 和 serial")
    row = dict(row)
    player = read_json(row.pop("json"))
    check_player(player, cid, serial)
    career = rows_for(c, "careerplan", cid, serial)
    for item in career:
        integer(item["points"], "培养记录 points")
    card = c.execute("SELECT * FROM managed_cards WHERE card_id=?", (str(cid),)).fetchone()
    aliases = [dict(r) for r in c.execute(
        "SELECT * FROM owned_identity_aliases WHERE id=? AND (old_serial=? OR new_serial=?) ORDER BY old_serial", (cid, serial, serial))]
    return {"row": row, "player": player, "careerplan": career,
            "warehouse": bool(rows_for(c, "warehouse", cid, serial)),
            "catalog": dict(card) if card else None, "aliases": aliases}


def progress(s):
    p = s["player"]
    return {"level": p["level_info"]["level"], "exp_total": p["level_info"]["exp_total"],
            "games": p.get("games", 0), "goal": p.get("goal", 0), "assist": p.get("assist", 0)}


def training_hash(s):
    p = s["player"]
    return value_hash({"level_info": p["level_info"], "careerplan": s["careerplan"],
                       "additional_skill_id": p.get("additional_skill_id"),
                       "additional_position": p.get("additional_position")})


def load_package(path):
    with checked_zip(path) as z:
        require("manifest.json" in z.namelist() and "player.json" in z.namelist(), "球员包缺少文件")
        manifest = read_json(z.read("manifest.json"))
        require(manifest.get("format") == FORMAT and type(manifest.get("version")) is int and manifest["version"] == VERSION,
                "球员包版本不兼容")
        require(str(uuid.UUID(manifest["package_id"])) == manifest["package_id"], "球员包永久标识无效")
        require(manifest.get("profile") == PROFILE, "未知球员参数适配器")
        hashes = manifest.get("sha256")
        require(isinstance(hashes, dict) and set(z.namelist()) == set(hashes) | {"manifest.json"}, "球员包清单不完整")
        data = {}
        for name, expected in hashes.items():
            require(name == "player.json" or name.startswith("assets/"), "球员包含未知文件")
            payload = z.read(name)
            require(digest(payload) == expected, f"球员包校验失败：{name}")
            data[name] = payload
        state = read_json(data["player.json"])
        cid = integer(manifest.get("card_id"), "card_id", 1)
        serial = integer(manifest.get("serial"), "serial", 1)
        check_player(state["player"], cid, serial)
        require(state["row"]["id"] == cid and state["row"]["serial"] == serial, "球员包身份损坏")
        require(type(state.get("warehouse")) is bool, "储备状态损坏")
        for r in state["careerplan"]:
            require(r["id"] == cid and r["serial"] == serial, "培养记录身份损坏")
            integer(r["points"], "培养记录 points")
        if state.get("catalog"):
            require(state["catalog"]["card_id"] == str(cid), "卡池定义身份损坏")
        for r in state["aliases"]:
            require(r["id"] == cid and (r["old_serial"] == serial or r["new_serial"] == serial), "身份别名损坏")
        return manifest, state, data


def export_player(save, apk, cid, serial, output, project=None, previous=None, assets=None):
    old_manifest, old_state, members = load_package(previous) if previous else ({}, {}, {})
    project_data = read_json(Path(project).read_bytes()) if project else {}
    package_id = old_manifest.get("package_id") or project_data.get("package_id") or str(uuid.uuid4())
    require(not old_manifest or (old_manifest["card_id"], old_manifest["serial"]) == (cid, serial), "不能用其他球员刷新该独立包")
    require(not project_data or project_data.get("package_id") == package_id, "工程与旧球员包的永久标识不同")
    fp = native_fingerprint(apk)
    if old_manifest:
        require(compatible_engine(old_manifest["native"]["native_engine_sha256"],fp["native_engine_sha256"],old_manifest['profile'],apk), "目标 APK 的关键接口不兼容，未刷新独立包")
    with save_input(save) as (db, meta, info), contextlib.closing(connect(db, True)) as c:
        reg = registry(c)
        state = snapshot(c, cid, serial)
        native_uid=state['player'].get('_personal_player_uuid')
        if native_uid:
            if old_manifest:
                require(old_state['player'].get('_personal_player_uuid')==native_uid,'旧快照不属于这个球员实例')
            elif project_data:
                require(project_data.get('package_id')==native_uid,'所选工程不属于这个球员实例')
                package_id=native_uid
            else:
                package_id=next((uid for uid,r in reg.items() if (cid,serial) in instance_pairs(r)),native_uid)
        for uid, r in reg.items():
            if (cid,serial) in instance_pairs(r):
                require(uid == package_id, "此实例已属于另一个独立包，请使用原工程或 --previous")
        require(state["catalog"] is not None, "此球员没有可核对的本地卡池定义，需要专用适配")
        members["player.json"] = compact(state).encode("utf-8")
        if assets:
            root = Path(assets).absolute()
            require(root.is_dir() and not root.is_symlink(), "资源目录不存在或是符号链接")
            for f in sorted(root.rglob("*")):
                require(not f.is_symlink(), "资源目录不能含符号链接")
                if f.is_file():
                    require(f.stat().st_size <= MAX_DB, "单个资源过大")
                    members["assets/" + f.relative_to(root).as_posix()] = f.read_bytes()
        manifest = {"format": FORMAT, "version": VERSION, "profile": PROFILE,
                    "package_id": package_id, "label": project_data.get("display_name") or old_manifest.get("label") or "个人球员",
                    "card_id": cid, "serial": serial, "created_at": old_manifest.get("created_at", stamp()),
                    "snapshot_at": stamp(), "native": fp, "db": info,
                    "source_save_sha256": digest(Path(save).read_bytes()),
                    "previous_snapshot_sha256": digest(Path(previous).read_bytes()) if previous else None,
                    "progress": progress(state), "asset_installation": "separate-client-adapter-required",
                    "sha256": {n: digest(b) for n, b in members.items()}}
        members["manifest.json"] = compact(manifest).encode("utf-8")
        result = atomic_new(output, archive_bytes(members))
    load_package(result)
    return {"output": str(result), "package_id": package_id, "progress": manifest["progress"]}


def insert_row(c, table, row):
    require(set(row) <= {r["name"] for r in c.execute(f'PRAGMA table_info("{table}")')}, f"{table} 含未知列")
    keys = list(row)
    require(all(k.replace("_", "").isalnum() for k in keys), "无效列名")
    c.execute(f'INSERT INTO "{table}" (' + ",".join('"' + k + '"' for k in keys) + ") VALUES (" + ",".join("?" for _ in keys) + ")", [row[k] for k in keys])


def migration(save, package, apk, output=None, prefer="stop"):
    m, incoming, members = load_package(package)
    fp = native_fingerprint(apk)
    require(compatible_engine(m["native"]["native_engine_sha256"],fp["native_engine_sha256"],m['profile'],apk),
            "目标 APK 的引擎发生变化，尚未验证参数含义；拒绝写入，原存档和球员包均保留")
    cid, serial, uid = m["card_id"], m["serial"], m["package_id"]
    with save_input(save) as (db, save_meta, info):
        require(info == m["db"], "存档表结构或 user_version 已变化，需要增加迁移适配器")
        with contextlib.closing(connect(db)) as c:
            for trigger in c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"):
                normalize = lambda sql: "".join(sql.split()).lower()
                require(trigger["name"] in KNOWN_TRIGGERS and normalize(trigger["sql"]) == normalize(KNOWN_TRIGGERS[trigger["name"]]),
                        "目标存档含未核对触发器，拒绝写入")
            reg = registry(c)
            owned = reg.get(uid)
            binding=instance_binding(owned,cid,serial)
            if owned:
                # A native project owns a card definition and can have many
                # independently trained draw copies. Keep the original grant
                # serial (including its released tombstone), registering each
                # additional snapshot under its exact card ID and serial.
                native_copy=(owned.get('card_id')==cid and incoming['player'].get('_personal_player_uuid')==uid)
                require(binding or native_copy, "永久标识指向其他实例")
            for other_uid, r in reg.items():
                require(other_uid == uid or (cid,serial) not in instance_pairs(r), "球员编号已被其他独立包占用")
            current_row = c.execute("SELECT 1 FROM gameplayers WHERE id=? AND serial=?", (cid, serial)).fetchone()
            current = snapshot(c, cid, serial) if current_row else None
            if owned and not binding and current:
                require(current['player'].get('_personal_player_uuid')==uid,'目标副本不属于这个自建球员')
            preserved_zero_aliases=[]
            if owned and incoming['player'].get('_personal_player_uuid')==uid:
                aliases=[]
                for alias in incoming['aliases']:
                    existing=c.execute('select new_serial from owned_identity_aliases where id=? and old_serial=?',(cid,alias['old_serial'])).fetchone()
                    if alias['old_serial']==0 and existing and existing[0]!=alias['new_serial']:
                        # Zero is a version-local default-grant alias, never
                        # an owned instance. Keep the target's default/tombstone
                        # while restoring the explicitly identified draw copy.
                        preserved_zero_aliases.append(dict(alias,target_new_serial=existing[0]));continue
                    aliases.append(alias)
                incoming=copy.deepcopy(incoming);incoming['aliases']=aliases
            catalog = c.execute("SELECT * FROM managed_cards WHERE card_id=?", (str(cid),)).fetchone()
            require(catalog is not None, "新版缺少该球员的卡池定义；先完成客户端球员资源适配，不能只插入存档")
            catalog_changed = dict(catalog) != incoming["catalog"]
            require(not catalog_changed or owned, "新版同一 ID 的卡池定义不同且无个人包登记，可能发生 ID 冲突；拒绝覆盖")
            action = "insert" if current is None else "unchanged"
            if current is not None and value_hash(current) != value_hash(incoming):
                require(owned, "目标同一 ID 和 serial 已有不同球员数据，且未登记为此独立包；拒绝覆盖")
                if prefer == "target":
                    action = "keep-target"
                else:
                    newer = [k for k, v in progress(current).items() if v > progress(incoming)[k]]
                    require(not newer, "目标存档有更新的进度（" + ", ".join(newer) + "），请先从目标导出最新独立包，拒绝回退")
                    same_stage = all(progress(current)[k] == progress(incoming)[k] for k in ("level", "exp_total"))
                    if same_stage and training_hash(current) != training_hash(incoming):
                        require(training_hash(current) == (binding or {}).get("training_sha256"),
                                "目标在相同等级经验下有新的加点、追加技能或位置记录，请先导出最新独立包，拒绝回退培养")
                    require(prefer == "package", "球员状态不同；核对计划后用 --prefer package 恢复更新前最新快照，或 --prefer target 保留目标状态")
                    action = "replace-registered"
            selected = current if action == "keep-target" else incoming
            report = {"package_id": uid, "card_id": cid, "serial": serial, "action": action,
                      "progress_before": progress(current) if current else None, "progress_after": progress(selected),
                      "careerplan_rows": len(selected["careerplan"]), "target_release": fp["release_id"],
                      "assets_in_package": len([n for n in members if n.startswith("assets/")]),
                      "assets_installed": False, "note": "只合并单名球员；不替换阵容、货币或其他球员。客户端卡面和脸模需另行适配。"}
            report['preserved_target_zero_serial_aliases']=preserved_zero_aliases
            if output is None:
                report["dry_run"] = True
                return report
            output = Path(output).resolve()
            require(not output.exists(), "输出已存在，拒绝覆盖")
            require(output != Path(save).resolve(), "输出必须与原存档不同")
            require(output.suffix.lower() == (".efsave" if save_meta else ".sqlite3"), "输出扩展名与输入存档类型不一致")
            report_path = output.with_name(output.name + ".migration.json")
            require(not report_path.exists(), "迁移报告已存在，拒绝覆盖")
            backup = output.parent / "backups" / (Path(save).stem + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + Path(save).suffix)
            atomic_new(backup, Path(save).read_bytes())
            require(digest(backup.read_bytes()) == digest(Path(save).read_bytes()), "备份校验失败")
            report["backup"] = str(backup)
            c.execute("BEGIN IMMEDIATE")
            try:
                if action in ("insert", "replace-registered"):
                    for table in ("gameplayers", "careerplan", "warehouse"):
                        c.execute(f'DELETE FROM "{table}" WHERE id=? AND serial=?', (cid, serial))
                    row = dict(incoming["row"], json=compact(incoming["player"]))
                    insert_row(c, "gameplayers", row)
                    for r in incoming["careerplan"]:
                        insert_row(c, "careerplan", r)
                    if incoming["warehouse"]:
                        insert_row(c, "warehouse", {"id": cid, "serial": serial})
                if catalog_changed and action != "keep-target":
                    c.execute("DELETE FROM managed_cards WHERE card_id=?", (str(cid),))
                    insert_row(c, "managed_cards", incoming["catalog"])
                if action != "keep-target":
                    for r in incoming["aliases"]:
                        existing = c.execute("SELECT new_serial FROM owned_identity_aliases WHERE id=? AND old_serial=?", (r["id"], r["old_serial"])).fetchone()
                        require(existing is None or existing[0] == r["new_serial"], "身份别名冲突，未发布迁移存档")
                        if existing is None:
                            insert_row(c, "owned_identity_aliases", r)
                high = c.execute("SELECT max(serial) FROM gameplayers WHERE id=?", (cid,)).fetchone()[0]
                next_row = c.execute("SELECT next_serial FROM managed_serials WHERE card_id=?", (str(cid),)).fetchone()
                following = max(serial + 1, (high or 0) + 1, next_row[0] if next_row else 0)
                c.execute("INSERT INTO managed_serials(card_id,next_serial) VALUES(?,?) ON CONFLICT(card_id) DO UPDATE SET next_serial=excluded.next_serial", (str(cid), following))
                record={"card_id":cid,"serial":serial,"snapshot_sha256":value_hash(selected),
                        "training_sha256":training_hash(selected),"imported_at":stamp(),
                        "source_package_sha256":digest(Path(package).read_bytes())}
                entry=copy.deepcopy(owned or {})
                if not owned or (owned.get('card_id'),owned.get('serial'))==(cid,serial):entry.update(record)
                else:entry.setdefault('instances',{})[f'{cid}:{serial}']=record
                reg[uid]=entry
                c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (REGISTRY_KEY, compact(reg)))
                c.commit()
            except BaseException:
                c.rollback()
                raise
        check_db(db)
        with contextlib.closing(connect(db, True)) as verify:
            require(snapshot(verify, cid, serial) == selected, "迁移后球员或培养记录不一致，未发布存档")
        db_bytes = db.read_bytes()
        if save_meta:
            updated_meta = dict(save_meta, db_sha256=digest(db_bytes))
            result = archive_bytes({"club.sqlite3": db_bytes, "manifest.json": compact(updated_meta).encode("utf8")})
        else:
            result = db_bytes
        atomic_new(output, result)
        report["output"] = str(output)
        report["output_sha256"] = digest(result)
        report["dry_run"] = False
        atomic_new(report_path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf8"))
        return report


def init_project(output):
    project = {"format": "73efootball-personal-player-project", "version": 1, "package_id": str(uuid.uuid4()),
               "display_name": "", "card_id": None, "serial": None, "status": "awaiting-user-profile-and-client-assets",
               "identity": {"name": None, "height_cm": None, "weight_kg": None, "preferred_foot": None, "position": None},
               "card_type": None, "card_series": None, "base_abilities": {}, "innate_skills": [], "additional_skills": [],
               "initial_level": None, "max_level": None, "booster_ids": [],
               "migration": {"preserve_full_player_payload": True, "preserve_careerplan": True, "reject_newer_progress_rollback": True}}
    atomic_new(output, json.dumps(project, ensure_ascii=False, indent=2).encode("utf8"))
    return {"project": str(Path(output).resolve()), "package_id": project["package_id"], "note": "尚未创建游戏球员，等待填写数据和客户端资源适配"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="73efootball 独立球员包与更新迁移工具")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="建立永久身份工程，能力和资源保持空白")
    p.add_argument("--out", required=True)
    p = sub.add_parser("list", help="列出导出存档内的球员实例")
    p.add_argument("--save", required=True)
    p = sub.add_parser("inspect", help="校验并查看球员包")
    p.add_argument("--package", required=True)
    p = sub.add_parser("export", help="导出或刷新单名球员最新状态")
    for name in ("save", "apk", "out"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--serial", type=int, required=True)
    p.add_argument("--project")
    p.add_argument("--previous")
    p.add_argument("--assets")
    for command in ("plan", "import"):
        p = sub.add_parser(command, help="只检查迁移计划" if command == "plan" else "生成新存档与备份，保留原文件")
        p.add_argument("--save", required=True)
        p.add_argument("--package", required=True)
        p.add_argument("--target-apk", required=True)
        p.add_argument("--prefer", choices=("stop", "package", "target"), default="stop")
        if command == "import":
            p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_project(args.out)
        elif args.command == "list":
            with save_input(args.save) as (db, meta, info), contextlib.closing(connect(db, True)) as c:
                result = [{"id": r["id"], "serial": r["serial"], **progress({"player": read_json(r["json"])})} for r in c.execute("SELECT id,serial,json FROM gameplayers ORDER BY id,serial")]
        elif args.command == "inspect":
            m, s, data = load_package(args.package)
            result = {k: v for k, v in m.items() if k not in ("sha256", "db")}
            result["careerplan_rows"] = len(s["careerplan"])
            result["checked"] = True
        elif args.command == "export":
            result = export_player(args.save, args.apk, args.id, args.serial, args.out, args.project, args.previous, args.assets)
        else:
            result = migration(args.save, args.package, args.target_apk, getattr(args, "out", None), args.prefer)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PackageError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, sqlite3.Error) as exc:
        print("未完成操作：" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
