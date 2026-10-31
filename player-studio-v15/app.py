"""Offline Windows player design studio. All traffic stays on 127.0.0.1."""
from __future__ import annotations
from export_errors import export_context, exported

import argparse
import base64
import contextlib
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
import uuid
import urllib.request
import webbrowser
import zipfile

import player_package as migration
from native_library import NativeLibrary
from apk_database import GameImport,active_resources
from native_package import NativePackage
from card_types import CARD_TYPES
from overall import calculate as calculate_overall
from coaches import CoachStore, normalize_coach, TACTICS
from player_folders import PlayerFolders
from native_appearance import validate as validate_appearance
from ai_playing_styles import OPTIONS as AI_PLAYING_STYLES,project_value as ai_styles,validate as validate_ai_styles
import packs
import editor_drafts
from window_sessions import WindowSessions
from booster_library import BoosterLibrary

APP_VERSION = "2.1.1"
GAME_PLATFORM = "android"
MAX_PERSONAL_PLAYERS = 10000
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).absolute().parent))
RESOURCE = BUNDLE / "resources"
WEB = BUNDLE / "web"
ASSET_ID = re.compile(r"^[a-f0-9]{64}\.(png|jpg|jpeg|webp|glb|obj|webm|usm|otf|ttf)$")
MAX_ASSET = 128 * 1024 * 1024
CATALOG = json.loads((RESOURCE / "catalog.json").read_text(encoding="utf-8"))
from playing_styles import apply_catalogue as apply_playing_styles
apply_playing_styles(CATALOG)
from skill_localization import apply_labels as apply_skill_labels
apply_skill_labels(CATALOG,RESOURCE)
from native_coach_links import schema as coach_link_schema,repair_legacy as repair_coach_options
_coach_options=repair_coach_options(json.loads((RESOURCE / 'coaches.json').read_text(encoding='utf8')),coach_link_schema(RESOURCE),RESOURCE)
from coach_tactics import repair_catalogue as repair_coach_tactics
_coach_options=repair_coach_tactics(_coach_options,RESOURCE)
CATALOG['coaches'] = _coach_options['coaches']
CATALOG['COACH_LINK_TYPES'] = _coach_options.get('linkup_types',[])
CATALOG['COACH_LINK_SCHEMA']=coach_link_schema(RESOURCE)
CATALOG['AI_PLAYING_STYLES']=AI_PLAYING_STYLES


def number(value, low, high, default):
    if type(value) not in (int, float) or not (low <= value <= high):
        return default
    return value


def default_project():
    p = json.loads((RESOURCE / "initial-project.json").read_text(encoding="utf-8"))
    p['ai_playing_styles']=[]
    return normalize_project(p)


def normalize_project(value):
    if not isinstance(value, dict):
        raise ValueError("工程需要是 JSON 对象")
    p = copy.deepcopy(value)
    # Preserve the original permanent identity and every unrecognized field.
    p["package_id"] = str(uuid.UUID(p.get("package_id") or str(uuid.uuid4())))
    if p.get("format", "73efootball-personal-player-project") != "73efootball-personal-player-project":
        raise ValueError("请选择 .efproject 或个人球员工程 JSON；不支持旧版 .efplayer 快照")
    if p.get("version", 1) != 1:
        raise ValueError("工程版本较新，需要升级软件后打开")
    p["format"] = "73efootball-personal-player-project"
    p["version"] = 1
    p["studio_version"] = APP_VERSION
    p["game_platform"] = GAME_PLATFORM
    p["display_name"] = str(p.get("display_name") or "")[:40]
    identity = p.setdefault("identity", {})
    if not isinstance(identity, dict):
        raise ValueError("个人资料格式不正确")
    for k, v in {"name": "", "height_cm": 180, "weight_kg": 75, "preferred_foot": "右脚", "position": "CF",
                 "nationality": "中国", "age": 22, "number": 10, "team": "PERSONAL CLUB"}.items():
        if identity.get(k) is None:
            identity[k] = v
    identity["height_cm"] = number(identity.get("height_cm"), 140, 220, 180)
    identity["weight_kg"] = number(identity.get("weight_kg"), 40, 140, 75)
    identity["age"] = number(identity.get("age"), 15, 60, 22)
    identity["number"] = int(number(identity.get("number"), 1, 999, 10))
    if identity["position"] not in CATALOG["POSITIONS"]:
        identity["position"] = "CF"
    for key in ("name", "nationality", "team", "preferred_foot"):
        identity[key] = str(identity.get(key) or "")[:60]
    identity['shirt_name']=str(identity.get('shirt_name') or identity['name'])[:60]
    from player_identity_binding import normalize as normalize_original_binding
    normalize_original_binding(identity,p.get('source_player'))
    celebration=p.get('celebration')
    if celebration is not None:
        from native_celebration import validate as validate_celebration
        validate_celebration(celebration)
    if p.get('ai_playing_styles') is not None:p['ai_playing_styles']=validate_ai_styles(p['ai_playing_styles'])
    elif (p.get('source_player') or {}).get('original_payload'):p['ai_playing_styles']=ai_styles(p)
    if p.get('motion_style') is not None:
        from native_motion import normalize as normalize_motion
        p['motion_style']=normalize_motion(p['motion_style'])
    p["card_type"] = p.get("card_type") or "Epic"
    if p["card_type"] not in CARD_TYPES:
        raise ValueError("未知的基础卡种")
    p["card_series"] = p.get("card_series") or p["card_type"]
    if p['card_type'] == 'Epic' and p['card_series'] == 'BigTime':
        p['card_type'] = 'BigTime'  # Migrate the old combined Epic/Big Time UI.
    if p['card_type'] == 'BigTime':
        p['card_series'] = 'BigTime'
    abilities = p.setdefault("base_abilities", {})
    if not isinstance(abilities, dict):
        raise ValueError("基础能力格式不正确")
    for key in CATALOG["ABILITIES"]:
        abilities[key] = int(number(abilities.get(key), 1, 105, 65))
    for key in ("innate_skills", "additional_skills"):
        values = p.get(key) or []
        if not isinstance(values, list):
            raise ValueError("技能列表格式不正确")
        for v in values:
            if type(v) is not int or str(v) not in CATALOG["PARAMETER_BY_SKILL"] or "预留" in CATALOG["SKILL_LABELS"].get(str(v), ""):
                raise ValueError("工程包含未适配的技能编号，已保留原文件；请先核对技能目录")
        p[key] = list(dict.fromkeys(values))
    # Project storage must preserve valid designs beyond the game's display
    # capacity. Native APK compilation checks its own supported capacities.
    p["additional_skills"] = [v for v in p["additional_skills"] if v not in p["innate_skills"]]
    p["initial_level"] = int(number(p.get("initial_level"), 1, 100, 1))
    p["max_level"] = int(number(p.get("max_level"), 1, 100, 35))
    p["initial_level"] = min(p["initial_level"], p["max_level"])
    training = p.setdefault("training", {})
    if not isinstance(training, dict):
        raise ValueError("培养分配格式不正确")
    for group in CATALOG["training_groups"]:
        training[group["id"]] = int(number(training.get(group["id"]), 0, 40, 0))
    custom = p.setdefault('custom_boosters', [])
    if not isinstance(custom, list) or len(custom)>10000:
        raise ValueError('一个工程最多保存 10000 项自定义增能')
    seen=set()
    for booster in custom:
        if not isinstance(booster,dict) or type(booster.get('id')) is not int or not 1<=booster['id']<11000 or booster['id'] in seen:
            raise ValueError('自定义增能身份冲突')
        seen.add(booster['id'])
        booster['uuid']=str(uuid.UUID(booster.get('uuid') or str(uuid.uuid4())))
        booster['label']=str(booster.get('label') or '自定义增能')[:40]
        booster['conditional']=bool(booster.get('conditional',False))
        effects=booster.get('effects',{})
        if not isinstance(effects,dict) or any(str(k) not in CATALOG['ABILITIES'] or type(v) is not int or not -20<=v<=20 for k,v in effects.items()):
            raise ValueError('自定义增能请使用 26 项能力，效果范围为 -20 到 +20')
        booster['effects']={str(k):v for k,v in effects.items()}
    ids = {0} | {b["id"] for b in CATALOG["boosters"]} | seen
    boosters = p.get("booster_ids") or []
    if not isinstance(boosters, list) or len(boosters) > 2 or any(type(v) is not int or v not in ids for v in boosters):
        raise ValueError("增能编号尚未适配，已保留原文件")
    p["booster_ids"] = (boosters + [0, 0])[:2]
    if p['booster_ids'][0]>255 and p['booster_ids'][0] not in seen:
        raise ValueError('第一增能槽的原版编号范围为 0–255，请在第二槽选择此增能')
    if p["booster_ids"][0] and p["booster_ids"][0] == p["booster_ids"][1]:
        raise ValueError("两个增能槽请选择不同项目")
    p.setdefault("conditional_boosters", False)
    custom_coaches=p.setdefault('custom_coaches',[])
    if not isinstance(custom_coaches,list) or len(custom_coaches)>50:
        raise ValueError('一个工程最多携带 50 项自建教练资料')
    p['custom_coaches']=[normalize_coach(row,CATALOG['ABILITIES']) for row in custom_coaches]
    if len({row['id'] for row in p['custom_coaches']})!=len(custom_coaches):
        raise ValueError('自建教练身份重复')
    settings=p.setdefault('preview',{})
    if not isinstance(settings,dict):raise ValueError('预览设置格式不正确')
    if settings.get('training_position') and settings['training_position'] not in CATALOG['POSITIONS']:
        raise ValueError('自动加点位置无效')
    selected=str(settings.get('coach_id') or '')
    if selected and not (re.fullmatch(r'\d{1,20}',selected) or selected.startswith('custom:') and str(uuid.UUID(selected[7:]))==selected[7:]):
        raise ValueError('教练身份格式不正确')
    settings['coach_id']=selected or None
    if settings.get('team_style') and settings['team_style'] not in TACTICS:raise ValueError('未知的教练战术体系')
    p.setdefault("position_aptitudes", {pos: (2 if pos == identity["position"] else 0) for pos in CATALOG["POSITIONS"]})
    p.setdefault("play_style", {"attack": 1, "defense": 0})
    p.setdefault("traits", {"weak_foot_usage": "普通", "weak_foot_accuracy": "普通", "form": "稳定", "injury": "普通"})
    if not isinstance(p['traits'],dict) or p['traits'].get('weak_foot_usage','普通') not in ('低','普通','高','极高'):
        raise ValueError('逆足使用频率请选择低、普通、高或极高')
    appearance = p.setdefault("appearance", {})
    if 'card_date' in appearance:
        value=appearance['card_date']
        if not isinstance(value,str) or len(value)>10:raise ValueError('BT 日期格式应为 YYYY-MM-DD')
        if value:
            try:
                if datetime.strptime(value,'%Y-%m-%d').strftime('%Y-%m-%d')!=value:raise ValueError()
            except ValueError:raise ValueError('BT 日期无效，请选择真实日期') from None
    if 'card_rarity' in appearance and (type(appearance['card_rarity']) is not int or not 1<=appearance['card_rarity']<=5):
        raise ValueError('卡面星级应为 1–5')
    for key, val in {"accent": "#cbb06b", "jersey": "#202b42", "background": "#101a2c", "portrait": None,
                     "background_image": None, "photo_zoom": 1, "photo_x": 0, "photo_y": 0, "card_title": "PERSONAL EDITION"}.items():
        appearance.setdefault(key, val)
    for key,val in {'thumbnail_image':None,'thumbnail_mode':'card','thumbnail_zoom':1,'thumbnail_x':0,'thumbnail_y':0,'thumbnail_animation':True}.items():appearance.setdefault(key,val)
    if appearance['thumbnail_mode'] not in ('card','portrait','image'):raise ValueError('小头像来源无效')
    if type(appearance['thumbnail_animation']) is not bool:raise ValueError('小头像动态背景必须为开关值')
    for key,lo,hi in (('thumbnail_zoom',.5,8),('thumbnail_x',-100,100),('thumbnail_y',-100,100)):
        value=appearance[key]
        if type(value) not in (int,float) or not lo<=value<=hi:raise ValueError('小头像裁切参数超出范围')
    model = p.setdefault("model", {})
    p.setdefault('weekly_condition','auto')
    from native_equipment import validate as validate_equipment
    validate_equipment(p.setdefault('equipment',{'boots_id':None,'sleeves':'keep'}))
    if p['weekly_condition'] not in ('auto','A','B','C','D','E'):raise ValueError('实时更新状态请选择跟随规则或 A–E')
    model.setdefault('preserve_expression',True)
    if type(model['preserve_expression']) is not bool:raise ValueError('保持导入表情必须为开关值')
    handles=model.setdefault('binding_handles',{'head':[0,0,0],'neck_root':[0,0,0]})
    if not isinstance(handles,dict) or set(handles)-{'head','neck_root'}:raise ValueError('头颈定位点无效')
    for key in ('head','neck_root'):
        values=handles.setdefault(key,[0,0,0])
        if not isinstance(values,list) or len(values)!=3 or any(type(v) not in (int,float) or not -10<=v<=10 for v in values):raise ValueError('头颈定位点各轴范围为 -10 至 +10 厘米')
    model.setdefault('head_vertical_cm',0)
    offset=model['head_vertical_cm']
    if type(offset) not in (int,float) or not -10<=offset<=10:raise ValueError('头模垂直位置范围为 -10 至 +10 厘米')
    validate_appearance(model)
    if 'leg_length' in (model.get('physique') or {}):model['torso_length']=14-model['physique']['leg_length']
    for key, val in {"asset": None, "texture": None, "skin": "#bb8968", "hair": "#251e1c", "head_width": 1,
                     "head_height": 1, "shoulders": 1, "hair_style": "short", "scale": 1, "rotation": 0}.items():
        model.setdefault(key, val)
    for group, fields in ((appearance, ("portrait", "background_image", "thumbnail_image")), (model, ("asset", "texture", "rigged_asset"))):
        for field in fields:
            if group.get(field) and not ASSET_ID.fullmatch(str(group[field])):
                raise ValueError("工程含无效的本地资源路径")
    for group, fields in ((appearance, ("accent", "jersey", "background")), (model, ("skin", "hair"))):
        for field in fields:
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(group.get(field, ""))):
                raise ValueError("颜色格式需要是 #RRGGBB")
    card=p.get('native_card')
    if card:
        if not isinstance(card,dict) or card.get('version')!=1 or not isinstance(card.get('layers'),list) or len(card['layers'])>32 or not isinstance(card.get('fonts'),dict):
            raise ValueError('原版卡面预览资料格式或版本不兼容')
        layout=card.get('layout') or {}
        if any(type(layout.get(k)) not in (int,float) or not 1<=layout[k]<=4096 for k in ('width','height')):
            raise ValueError('原版卡面尺寸无效')
        for key in ('overall','position','name'):
            box=layout.get(key) or {}
            if any(type(box.get(k)) not in (int,float) or not -4096<=box[k]<=4096 for k in ('x','y','w','h','size')) or box['w']<=0 or box['h']<=0 or box['size']<=0:
                raise ValueError('原版资料层位置无效')
        if any(not isinstance(row,dict) or not row.get('asset_id') or row.get('blend','source-over') not in ('source-over','screen','multiply','lighter') for row in card['layers']):
            raise ValueError('原版卡面图层无效')
        custom=card.get('custom_motion')
        if custom is not None:
            if not isinstance(custom,dict) or any(not isinstance(custom.get(k),dict) or not re.fullmatch(r'[a-f0-9]{64}\.usm',str(custom[k].get('asset_id',''))) or not isinstance(custom[k].get('preview'),dict) or not re.fullmatch(r'[a-f0-9]{64}\.webm',str(custom[k]['preview'].get('asset_id',''))) for k in ('large','mini')):
                raise ValueError('自制动态背景素材无效，请重新导入视频')
    referenced_assets(p)
    if p.get('status')=='new-player-slot' and p['identity']['name'].strip() and (p.get('native_card') or p['model'].get('asset') or p['appearance'].get('portrait')):
        # Older versions kept the empty-slot marker after a custom model or
        # card was authored. Loading that saved design must enable editing.
        p['status']='draft';p['editor_ready']=True
    return p


def referenced_assets(p):
    images=[p["appearance"].get("portrait"),p["appearance"].get("thumbnail_image"), p["appearance"].get("background_image"),p["model"].get("asset"), p["model"].get("texture"),p['model'].get('rigged_asset')]
    images.extend(v.get('asset_id') for v in (p.get('native_art') or {}).values() if isinstance(v,dict))
    result={v for v in images if v}
    def collect(value):
        if isinstance(value,dict):
            if value.get('asset_id'):result.add(value['asset_id'])
            for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    collect(p.get('native_card'))
    collect([c.get('portrait') for c in p.get('custom_coaches',[])])
    collect([c.get('head_model') for c in p.get('custom_coaches',[])])
    if any(not isinstance(v,str) or not ASSET_ID.fullmatch(v) for v in result):
        raise ValueError('原版资源引用无效')
    return result


def dialog(kind="open", category="project", initial=""):
    if os.name != "nt":
        raise ValueError("文件选择器目前支持 Windows，也可以在输入框中粘贴路径")
    filters = {"project": "球员工程\0*.efproject;*.json\0所有文件\0*.*\0",
               "image": "图片\0*.png;*.jpg;*.jpeg;*.webp\0所有文件\0*.*\0",
               "motion-video": "视频\0*.mp4;*.mov;*.webm\0所有文件\0*.*\0",
               "model": "三维模型\0*.glb;*.obj\0所有文件\0*.*\0",
               "save": "游戏存档\0*.efsave;*.sqlite3\0所有文件\0*.*\0",
               "package": "独立球员包\0*.efplayer\0所有文件\0*.*\0",
               "apk": "安卓游戏 APK\0*.apk\0所有文件\0*.*\0",
               "content-delta": "内容增量包 ZIP\0*.zip\0所有文件\0*.*\0",
               "update": "APK 增量包\0*.efupdate\0所有文件\0*.*\0"}
    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD), ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR), ("pvReserved", ctypes.c_void_p),
                    ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]
    buffer = ctypes.create_unicode_buffer(32768)
    if initial and kind == "save":
        buffer.value = initial
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(ofn)
    ofn.lpstrFilter = filters.get(category, filters["project"]) + "\0"
    ofn.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    ofn.nMaxFile = len(buffer)
    ofn.nFilterIndex = 1
    ofn.lpstrTitle = "选择文件" if kind == "open" else "保存文件"
    ofn.Flags = 0x00080000 | 0x00000008 | (0x00001000 if kind == "open" else 0x00000002)
    fn = ctypes.windll.comdlg32.GetOpenFileNameW if kind == "open" else ctypes.windll.comdlg32.GetSaveFileNameW
    return buffer.value if fn(ctypes.byref(ofn)) else None


class Store:
    def __init__(self, data):
        self.root = Path(data).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("assets", "exports", "backups", "tmp", "players"):
            (self.root / folder).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.player_folders = PlayerFolders(self)
        self.coaches = CoachStore(self.root, CATALOG['ABILITIES'])
        self.boosters = BoosterLibrary(self.root)
        self.project_path = self.root / "current-project.json"
        self.last_backup = 0
        if self.project_path.exists():
            try:
                self.project = normalize_project(json.loads(self.project_path.read_text(encoding="utf8")))
            except Exception:
                # Never silently overwrite a damaged autosave.
                shutil.copy2(self.project_path, self.root / "backups" / ("unreadable-" + uuid.uuid4().hex + ".json"))
                self.project = default_project()
        else:
            self.project = default_project()
        self.save(self.project)

    def save(self, project, manual=False):
        p = normalize_project(project)
        self.boosters.sync(p,getattr(self,'project',None))
        data = json.dumps(p, ensure_ascii=False, indent=2).encode("utf8")
        with self.lock:
            if self.project_path.exists() and (manual or time.monotonic() - self.last_backup > 120):
                backup = self.root / "backups" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ".json")
                shutil.copy2(self.project_path, backup)
                self.last_backup = time.monotonic()
            temp = self.root / (".project-" + uuid.uuid4().hex)
            with temp.open("wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.project_path)
            self.project = p
        return {"saved": True, "at": datetime.now().strftime("%H:%M:%S"), "project": p}

    def _player_path(self, package_id):
        return self.root / 'players' / (str(uuid.UUID(package_id)) + '.json')

    def new_player_slot(self):
        """Checkpoint the old identity and immediately register a fresh slot."""
        with self.lock:
            previous=copy.deepcopy(self.project)
            if previous['identity']['name'].strip():self.save_player(previous)
            elif self._player_path(previous['package_id']).is_file() or previous.get('source_player') or previous.get('model',{}).get('asset') or previous.get('appearance',{}).get('portrait'):
                previous['identity']['name']='未命名球员';self.save_player(previous)
            project=default_project();project['package_id']=str(uuid.uuid4())
            names={r['name'] for r in self.list_players()['rows']};index=1
            while '新建球员 '+str(index) in names:index+=1
            project['identity']['name']='新建球员 '+str(index)
            project['status']='new-player-slot'
            self.save_player(project)
            result=self.save(project,True)
            return {**result,'new_slot':True,'previous_package_id':previous['package_id']}

    def saved_player(self, package_id):
        path = self._player_path(package_id)
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('未找到已保存的自建球员')
        entry = migration.read_json(path.read_bytes())
        if entry.get('format') != '73efootball-saved-player' or entry.get('version') != 1:
            raise ValueError('已保存球员的格式或版本不兼容，原文件已保留')
        project = normalize_project(entry['project'])
        if project['package_id'] != str(uuid.UUID(package_id)):
            raise ValueError('球员永久身份与文件名不一致')
        return {**entry, 'project': project}

    def save_player(self, project):
        p = normalize_project(project)
        if not p['identity']['name'].strip():
            raise ValueError('请先填写球员姓名，再保存到我的球员')
        for name in referenced_assets(p):
            if not (self.root / 'assets' / name).is_file():
                raise ValueError('球员引用的资源缺失，请先重新载入对应资源')
        entry = {'format': '73efootball-saved-player', 'version': 1,
                 'saved_at': migration.stamp(), 'overall': calculate_overall(p, CATALOG), 'project': p}
        path = self._player_path(p['package_id'])
        self.boosters.sync(p)
        data = json.dumps(entry, ensure_ascii=False, indent=2).encode('utf8')
        with self.lock:
            if not path.exists() and sum(1 for _ in (self.root/'players').glob('*.json'))>=MAX_PERSONAL_PLAYERS:
                raise ValueError('自建球员已达到 10000 名上限，请删除不需要的球员后再新建')
            if path.is_file():
                backup = self.root / 'backups' / ('saved-player-' + path.stem + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.json')
                shutil.copy2(path, backup)
            temp = path.with_name('.player-' + uuid.uuid4().hex)
            with temp.open('wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        return {'saved': True, 'package_id': p['package_id'], 'saved_at': entry['saved_at'],
                'overall': entry['overall'], 'path': str(path)}

    def delete_player(self, package_id, confirmed=False):
        if confirmed is not True:
            raise ValueError('请先确认删除这名自建球员')
        with self.lock:
            entry = self.saved_player(package_id)
            path = self._player_path(package_id)
            if path.is_symlink():
                raise ValueError('球员文件不能是外部链接')
            package_id = entry['project']['package_id']
            pack_path = self.root / 'packs.json'
            old_packs = pack_path.read_bytes() if pack_path.exists() else None
            rows = packs.load(self)
            removed = 0
            for row in rows:
                members = row['members']
                row['members'] = [m for m in members if not (m['kind']=='custom' and m['id']==package_id)]
                removed += len(members)-len(row['members'])
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
            backup = self.root / 'backups' / ('deleted-player-'+package_id+'-'+stamp+'.json')
            previous = copy.deepcopy(self.project)
            current = previous['package_id'] == package_id
            if removed:
                (self.root/'backups'/('packs-before-delete-'+stamp+'.json')).write_bytes(old_packs)
            path.replace(backup)
            try:
                if removed:
                    temp=pack_path.with_suffix('.tmp')
                    temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
                    os.replace(temp,pack_path)
                if current:
                    self.save(default_project(), manual=True)
            except Exception:
                shutil.copy2(backup,path)
                if removed:pack_path.write_bytes(old_packs)
                if current:self.save(previous,manual=True)
                raise
            folder_warning=None
            try:self.player_folders.forget(package_id)
            except (ValueError,OSError) as error:folder_warning=str(error)
            return {'deleted':True,'package_id':package_id,'removed_pack_members':removed,
                    'current_cleared':current,'project':self.project,'backup':str(backup),'folder_warning':folder_warning}

    def list_players(self, query='', offset=0, limit=None, folder_id=None):
        if type(offset) is not int or offset<0 or (limit is not None and (type(limit) is not int or not 1<=limit<=100)):
            raise ValueError('球员分页参数无效')
        rows, errors = [], []
        query = str(query).casefold()[:120]
        with self.lock:
            folder_error=None
            try:folders=self.player_folders.read()
            except ValueError as error:
                if folder_id:raise
                folder_error=str(error);folders={'folders':[],'members':{}}
            names={r['id']:r['name'] for r in folders['folders']}
            if folder_id and folder_id!='unfiled' and folder_id not in names:raise ValueError('文件夹已不存在，请刷新列表')
            for path in (self.root / 'players').glob('*.json'):
                try:
                    entry = self.saved_player(path.stem)
                    p = entry['project']
                    group=folders['members'].get(p['package_id'])
                    if folder_id and (group is not None if folder_id=='unfiled' else group!=folder_id):continue
                    if query and query not in ' '.join([p['identity']['name'], p['display_name'], p['package_id']]).casefold():
                        continue
                    rows.append({'package_id': p['package_id'], 'name': p['identity']['name'],
                                 'display_name': p['display_name'], 'card_type': p['card_type'],
                                 'position': p['identity']['position'], 'level': p['initial_level'],
                                 'folder_id':group,'folder_name':names.get(group),
                                 'max_level': p['max_level'], 'overall': calculate_overall(p, CATALOG),
                                 'portrait': p['appearance']['portrait'], 'saved_at': entry['saved_at']})
                except (ValueError, KeyError, OSError) as exc:
                    errors.append({'file': path.name, 'message': str(exc)})
        rows.sort(key=lambda item: item['saved_at'], reverse=True)
        total=len(rows)
        return {'rows':rows[offset:offset+limit] if limit else rows,'total':total,'offset':offset,
                'saved_total':sum(1 for _ in (self.root/'players').glob('*.json'))-len(errors),'capacity':MAX_PERSONAL_PLAYERS,'errors':errors,'folder_error':folder_error}

    def import_asset(self, path, category):
        source = Path(path).absolute()
        if not source.is_file() or source.stat().st_size > MAX_ASSET:
            raise ValueError("文件不存在或超过 128 MB")
        suffix = source.suffix.lower()
        allowed = {'image':('.png','.jpg','.jpeg','.webp'),'model':('.glb','.obj'),'video':('.webm',),'font':('.otf','.ttf')}.get(category,())
        if suffix not in allowed:
            raise ValueError("图片支持 PNG/JPG/WebP；模型支持 GLB/OBJ")
        data = source.read_bytes()
        if category=='video' and not data.startswith(b'\x1aE\xdf\xa3'):
            raise ValueError('原版动画封装无效')
        if category=='font' and data[:4] not in (b'OTTO',b'\x00\x01\x00\x00'):
            raise ValueError('原版字体格式无效')
        if suffix == ".glb" and data[:4] != b"glTF":
            raise ValueError("这不是有效的 GLB 文件")
        if category == "image" and not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8") or data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
            raise ValueError("图片内容与扩展名不符")
        name = hashlib.sha256(data).hexdigest() + suffix
        target = self.root / "assets" / name
        if not target.exists():
            target.write_bytes(data)
        return {"id": name, "name": source.name, "size": len(data), "url": "/assets/" + name}

    def import_screenshot(self, uri):
        if not isinstance(uri, str) or not uri.startswith("data:image/png;base64,"):
            raise ValueError("取景需要是 PNG 图片")
        data = base64.b64decode(uri.split(",", 1)[1], validate=True)
        if len(data) > 6 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("取景图片过大或格式不正确")
        name = hashlib.sha256(data).hexdigest() + ".png"
        (self.root / "assets" / name).write_bytes(data)
        return {"id": name, "url": "/assets/" + name}

    def import_project(self, path):
        source = Path(path).absolute()
        if source.suffix.lower() == ".efproject":
            with migration.checked_zip(source, 512 * 1024 * 1024) as z:
                m = migration.read_json(z.read("manifest.json"))
                if m.get('format')=='73efootball-studio-project' and m.get('version')==2:
                    from project_sharing import import_selected
                    return import_selected(self,z,m)
                if m.get("format") != "73efootball-studio-project" or m.get("version") != 1:
                    raise ValueError("工程包版本不兼容")
                expected = set(m["sha256"]) | {"manifest.json"}
                if set(z.namelist()) != expected or "project.json" not in expected:
                    raise ValueError("工程包清单不完整")
                files = {}
                for name, sha in m["sha256"].items():
                    data = z.read(name)
                    if migration.digest(data) != sha:
                        raise ValueError("工程包校验失败：" + name)
                    if name != "project.json" and (not name.startswith("assets/") or not ASSET_ID.fullmatch(name[7:])):
                        raise ValueError("工程包含未知文件")
                    if name.startswith("assets/") and (len(data) > MAX_ASSET or name[7:71] != migration.digest(data)):
                        raise ValueError("资源内容与永久文件名不一致")
                    files[name] = data
                from project_transfer import prepare as transfer_project
                from custom_motion_import import upgrade_legacy
                p = normalize_project(upgrade_legacy(transfer_project(migration.read_json(files["project.json"]),GAME_PLATFORM,m.get("game_platform")),files))
                for name in referenced_assets(p):
                    if "assets/" + name not in files:
                        raise ValueError("工程包缺少引用的资源")
                needed=referenced_assets(p)
                for name, data in files.items():
                    if name.startswith("assets/") and name[7:] in needed:
                        (self.root / name).write_bytes(data)
        else:
            if source.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("工程 JSON 过大")
            from project_transfer import prepare as transfer_project
            p = normalize_project(transfer_project(migration.read_json(source.read_bytes()),GAME_PLATFORM))
        existing=self._player_path(p['package_id'])
        if existing.is_file() and self.saved_player(p['package_id'])['project']!=p:
            p['package_id']=str(uuid.uuid4());p['card_id']=None;p['serial']=0
        if self.project['package_id']!=p['package_id'] and self.project['identity']['name'].strip():self.save_player(self.project)
        if p['identity']['name'].strip():self.save_player(p)
        self.save(p, manual=True)
        return p

    @exported('球员工程','导出工程',lambda self,project: project)
    def export_project(self, project):
        p = normalize_project(project)
        files = {"project.json": json.dumps(p, ensure_ascii=False, indent=2).encode("utf8")}
        for name in referenced_assets(p):
            source = self.root / "assets" / name
            if not source.is_file():
                raise ValueError("工程引用的资源缺失："+name+"，请重新导入图片或模型")
            with export_context('工程素材',name,'读取图片、模型或动画文件'):
                files["assets/" + name] = source.read_bytes()
        manifest = {"format": "73efootball-studio-project", "version": 1, "package_id": p["package_id"],
                    "game_platform":GAME_PLATFORM, "created_at": migration.stamp(), "sha256": {k: migration.digest(v) for k, v in files.items()}}
        files["manifest.json"] = migration.compact(manifest).encode("utf8")
        filename = "球员工程-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4] + ".efproject"
        (self.root / "exports" / filename).write_bytes(migration.archive_bytes(files))
        return {"url": "/exports/" + quote(filename), "filename": filename, "path": str(self.root / "exports" / filename)}


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, token=None):
        super().__init__(address, Handler)
        self.store = store
        home = Path(sys.executable).absolute().parent if getattr(sys, 'frozen', False) else Path(__file__).absolute().parent.parent / '球员工坊-V15'
        self.home=home
        self.use_resources(active_resources(RESOURCE,store.root))
        self.game_import = GameImport(self,RESOURCE)
        from onboarding import Setup
        self.setup = Setup(self)
        from updates import UpdateChecker
        self.updates = UpdateChecker(store,RESOURCE,APP_VERSION,globals().get('PLATFORM','pc'))
        self.window_sessions = WindowSessions(self.shutdown)
        from native_motion import MotionPresets
        self.motion_presets=MotionPresets(store)
        self.token = token or secrets.token_urlsafe(32)
        self.last_seen = time.monotonic()

    def use_resources(self,resources):
        global CATALOG
        from head_preview import HeadPreview
        library=NativeLibrary(resources,self.home,self.store)
        package=NativePackage(library,resources,(BUNDLE/'personal_runtime.py').read_text(encoding='utf8'),profile_resources=RESOURCE)
        self.catalog=json.loads((Path(resources)/'catalog.json').read_text(encoding='utf8'))
        apply_playing_styles(self.catalog)
        apply_skill_labels(self.catalog,RESOURCE)
        coach_options=repair_coach_options(json.loads((Path(resources)/'coaches.json').read_text(encoding='utf8')),coach_link_schema(RESOURCE),resources)
        from coach_identity import repair_catalogue as repair_coach_identity
        coach_options=repair_coach_identity(coach_options,resources)
        coach_options=repair_coach_tactics(coach_options,resources,RESOURCE)
        self.catalog['coaches']=coach_options['coaches']
        self.catalog['COACH_LINK_TYPES']=coach_options.get('linkup_types',[])
        self.catalog['COACH_LINK_SCHEMA']=coach_link_schema(RESOURCE)
        self.catalog['AI_PLAYING_STYLES']=AI_PLAYING_STYLES
        from native_equipment import read_catalogue
        self.catalog['equipment']=read_catalogue(resources,RESOURCE)
        CATALOG=self.catalog
        self.library=library;self.native_package=package;self.head_preview=HeadPreview(library,package)
        from native_thumbnail import ThumbnailPreview
        self.thumbnail_preview=ThumbnailPreview(library)


class Handler(BaseHTTPRequestHandler):
    server_version = "PlayerStudio/1"

    def log_message(self, fmt, *args):
        logging.info(fmt, *args)

    def authenticated(self):
        cookie = dict(part.strip().split("=", 1) for part in self.headers.get("Cookie", "").split(";") if "=" in part)
        query = parse_qs(urlsplit(self.path).query)
        # A restarted local server issues a new launch token. An old browser
        # cookie must not override the explicit token in the new launch URL.
        supplied = self.headers.get("X-Studio-Token") or query.get("token", [""])[0] or cookie.get("studio_session") or ""
        return secrets.compare_digest(supplied, self.server.token)

    def send(self, data, status=200, content_type="application/json; charset=utf-8", cookie=False, download=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self' blob: data:; worker-src blob:; object-src 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header("Set-Cookie", "studio_session=" + self.server.token + "; HttpOnly; SameSite=Strict; Path=/")
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(download))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/health":
            return self.send({"app": "player-studio", "version": APP_VERSION})
        if path == "/" and self.authenticated():
            return self.send((WEB / "index.html").read_bytes(), content_type="text/html; charset=utf-8", cookie=True)
        if not self.authenticated():
            return self.send({"error": "请从桌面程序启动球员工坊"}, 403)
        self.server.last_seen = time.monotonic()
        if path == "/api/bootstrap":
            self.server.updates.start()
            app_root = self.server.library.home.parent
            from apk_sources import resolve as resolve_sources
            selected=resolve_sources(self.server.library,self.server.store)
            return self.send({"project": self.server.store.project, "catalog": self.server.catalog, "version": APP_VERSION,
                              "platform":globals().get('PLATFORM','pc'),
                              "data_directory": str(self.server.store.root), "default_apk": selected['apk'],
                              "default_companion": selected['companion'], "library": self.server.library.summary(),
                              "migration_profile": migration.PROFILE, "identities": self.server.library.identities(),
                              "custom_coaches": self.server.store.coaches.list(),
                              "default_rigged":str(app_root/'我的脸模/我的头部-接缝修复-V13骨架.glb') if (app_root/'我的脸模/我的头部-接缝修复-V13骨架.glb').is_file() else ''})
        if path == "/api/ping":
            return self.send({"ok": True})
        if path.startswith("/assets/"):
            name = path[8:]
            if not ASSET_ID.fullmatch(name):
                return self.send({"error": "无效资源"}, 404)
            file = self.server.store.root / "assets" / name
        elif path.startswith("/exports/"):
            name = path[9:]
            if "/" in name or "\\" in name or ".." in name:
                return self.send({"error": "无效导出路径"}, 404)
            file = self.server.store.root / "exports" / name
        else:
            file = Path(os.path.abspath(WEB / path.lstrip("/")))
            if not str(file).startswith(str(WEB.absolute()) + os.sep):
                return self.send({"error": "路径不存在"}, 404)
        if not file.is_file():
            return self.send({"error": "文件不存在"}, 404)
        mime = {".js": "text/javascript; charset=utf-8", ".glb": "model/gltf-binary", ".obj": "text/plain; charset=utf-8",'.webm':'video/webm','.otf':'font/otf','.ttf':'font/ttf'}.get(file.suffix.lower(), mimetypes.guess_type(str(file))[0] or "application/octet-stream")
        if file.stat().st_size > 8*1024*1024:
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(file.stat().st_size))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if path.startswith('/exports/'):
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''"+quote(file.name))
            self.end_headers()
            try:
                with file.open('rb') as src:
                    shutil.copyfileobj(src, self.wfile, 1024*1024)
            except (BrokenPipeError, ConnectionResetError):pass
        else:self.send(file.read_bytes(), content_type=mime, download=file.name if path.startswith("/exports/") else None)

    def do_POST(self):
        if not self.authenticated():
            return self.send({"error": "会话无效"}, 403)
        origin = self.headers.get("Origin")
        expected = "http://127.0.0.1:" + str(self.server.server_port)
        if origin and origin != expected:
            return self.send({"error": "来源不匹配"}, 403)
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 8 * 1024 * 1024:
                raise ValueError("请求过大")
            body = migration.read_json(self.rfile.read(size) or b"{}")
            store = self.server.store
            self.server.last_seen = time.monotonic()
            if path == "/api/project/save":
                result = store.save(body["project"], body.get("manual", False))
                if body['project'].get('identity',{}).get('name','').strip():
                    try:store.save_player(body['project'])
                    except ValueError as exc:result['draft_message']=str(exc)
            elif path == '/api/editor/drafts':
                result={'rows':editor_drafts.listing(store)}
            elif path == '/api/editor/drafts/save':
                value=body.get('value')
                if body.get('category')=='coach' and value and str(value.get('name','')).strip():
                    # Persist the raw edit before optional resource preparation.
                    editor_drafts.update(store,'coach',value,commit=False)
                    from coach_models import prepare
                    try:value=prepare(value,self.server.library)
                    except (ValueError,OSError):pass  # An unavailable head must not lose text edits.
                result=editor_drafts.update(store,body['category'],value)
            elif path == '/api/project/checkpoint':
                value=normalize_project(body['project'])
                backup=store.root/'backups'/('before-template-'+datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]+'.json')
                with store.lock:backup.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
                result={'backed_up':True,'backup':str(backup)}
            elif path == '/api/window/open':
                result = self.server.window_sessions.open(body['session'])
            elif path == '/api/window/close':
                def save_window():
                    for draft in body.get('editor_drafts',[]):
                        editor_drafts.update(store,draft['category'],draft.get('value'),commit=False)
                    value=body.get('project')
                    if value is None and body.get('package_id')==store.project['package_id'] and 'patch' in body:
                        from window_sessions import apply_project_delta
                        value=apply_project_delta(store.project,body['patch'])
                    if value and value.get('package_id')==store.project['package_id']:
                        store.save(value, manual=True)
                result = self.server.window_sessions.close(body['session'], save_window)
            elif path == '/api/players/save':
                result = store.save_player(body['project'])
            elif path == '/api/players/list':
                result = store.list_players(body.get('query', ''),body.get('offset',0),body.get('limit'),body.get('folder_id'))
            elif path == '/api/players/folders/list':
                result = store.player_folders.listing()
            elif path == '/api/players/folders/create':
                result = store.player_folders.create(body.get('name'),body.get('player_ids',[]))
            elif path == '/api/players/folders/add':
                result = store.player_folders.add(body.get('folder_id'),body.get('player_ids'))
            elif path == '/api/players/folders/remove':
                result = store.player_folders.remove(body.get('folder_id'),body.get('player_ids'))
            elif path == '/api/players/folders/rename':
                result = store.player_folders.rename(body.get('folder_id'),body.get('name'))
            elif path == '/api/players/folders/delete':
                result = store.player_folders.delete(body.get('folder_id'),body.get('confirmed',False))
            elif path == '/api/boosters/list':
                result = store.boosters.list(body.get('query',''),body.get('offset',0))
            elif path == '/api/players/delete':
                result = store.delete_player(body['package_id'], body.get('confirmed', False))
            elif path == '/api/players/open':
                if store.project['package_id']!=body['package_id'] and store.project['identity']['name'].strip():store.save_player(store.project)
                result = store.save(store.saved_player(body['package_id'])['project'], manual=True)
            elif path == '/api/players/export':
                result = store.export_project(store.saved_player(body['package_id'])['project'])
            elif path == '/api/coaches/save':
                from coach_models import prepare as prepare_coach_model,preview_coach
                coach=prepare_coach_model(body['coach'],self.server.library)
                if (coach.get('head_model') or {}).get('asset_id'):preview_coach(self.server.library,coach['head_model'])
                result = store.coaches.save(coach)
            elif path == '/api/coaches/model/template':
                from coach_models import template
                result = template(self.server.library,body.get('source_id'),allow_default=True)
            elif path == '/api/coaches/model/current':
                from coach_models import current
                result = current(self.server.library,body.get('coach'))
            elif path == '/api/coaches/model/preview':
                from coach_models import preview_coach
                result = preview_coach(self.server.library,body.get('head_model'))
            elif path == '/api/coaches/list':
                result = store.coaches.list()
            elif path == '/api/coaches/delete':
                from coach_deletion import delete_coach
                result = delete_coach(store,body.get('uuid'),body.get('confirmed',False))
                editor_drafts.remove(store,'coach',body['uuid'])
            elif path == '/api/coaches/heads/list':
                from coach_heads import catalogue
                result = catalogue(self.server.library,self.server.catalog['coaches'])
            elif path == '/api/coaches/heads/original':
                from coach_heads import original
                result = original(self.server.library,body.get('path'))
            elif path == '/api/coaches/heads/preview':
                from coach_heads import preview
                result = preview(self.server.library,body.get('head'))
            elif path == '/api/coaches/heads/save':
                from coach_heads import preview,CoachHeadStore
                result = preview(self.server.library,body.get('head'))
                result['head'] = CoachHeadStore(store.root).save(body['head'])
            elif path == '/api/coaches/heads/delete':
                from coach_heads import CoachHeadStore
                CoachHeadStore(store.root).delete(body.get('target'))
                result = {'deleted':True}
            elif path=='/api/motion/source':
                from native_motion import from_player
                result=from_player(self.server.library.player(str(body.get('id',''))))
            elif path=='/api/motion/presets':
                result={'rows':self.server.motion_presets.list()}
            elif path=='/api/motion/presets/save':
                result=self.server.motion_presets.save(body)
            elif path == '/api/coaches/portraits':
                from coach_portraits import original_portraits
                result = original_portraits(self.server.library,self.server.catalog['coaches'],body.get('ids'))
            elif path == "/api/library/search":
                result = self.server.library.search(body)
            elif path == '/api/library/recycle':
                if self.server.native_package.status()['phase']=='working' or self.server.game_import.status()['phase']=='working':raise ValueError('请等待当前生成或导入完成，再调整回收站')
                from catalogue_trash import change as recycle_change
                result=recycle_change(self.server.library,body)
            elif path == "/api/library/player":
                result = self.server.library.player(body["id"])
            elif path == '/api/library/card':
                result = self.server.library.card(body['id'])
            elif path == '/api/library/card-info':
                result = self.server.library.card_info(body['id'],body.get('team_id'),body.get('nation_id'))
            elif path == '/api/library/presets':
                result = self.server.library.presets.search(body)
            elif path == '/api/library/preset-previews':
                result = self.server.library.presets.previews(body['ids'])
            elif path == '/api/library/preset':
                result = self.server.library.presets.apply(body)
            elif path == "/api/library/assets":
                result = self.server.library.assets(body)
            elif path == "/api/library/convert":
                result = self.server.library.convert(body)
            elif path == "/api/library/setup":
                result = self.server.library.setup(body)
            elif path == "/api/library/status":
                result = self.server.library.summary()
            elif path == '/api/game-import/start':
                result = self.server.game_import.start(body)
            elif path == '/api/game-import/inspect-delta':
                result = self.server.game_import.inspect_delta(body['path'])
            elif path == '/api/setup/status':
                result = self.server.setup.status(body.get('refresh',False))
            elif path == '/api/setup/preferences':
                from onboarding import preferences
                result = preferences(store,body)
            elif path == '/api/setup/install-plan':
                result = self.server.setup.install_plan(body)
            elif path == '/api/updates/status':
                result = self.server.updates.status()
            elif path == '/api/updates/check':
                result = self.server.updates.start(manual=True)
            elif path == '/api/updates/settings':
                result = self.server.updates.settings(body)
            elif path == '/api/updates/dismiss':
                result = self.server.updates.dismiss()
            elif path == '/api/updates/open':
                url=self.server.updates.link()
                action=globals().get('open_update_action',lambda value:webbrowser.open(value))
                result={'opened':bool(action(url))}
            elif path == '/api/game-import/status':
                result = self.server.game_import.status()
            elif path == '/api/game-import/install-adapter':
                result = self.server.game_import.install_adapter(body['path'])
            elif path == '/api/native-apk/start':
                if self.server.game_import.status()['phase']=='working':raise ValueError('正在切换游戏数据库，请等待导入完成')
                result = self.server.native_package.start(body if body.get('operation')=='companion' else {**body,'project':normalize_project(body['project'])})
            elif path == '/api/native-apk/candidates':
                result = self.server.native_package.candidates(normalize_project(body['project']))
            elif path == '/api/native-apk/sources':
                from apk_sources import resolve as resolve_sources,installation_guidance
                result = resolve_sources(self.server.library,self.server.store)
                if body.get('apk'):result['installation']=installation_guidance(body['apk'],self.server.store)
            elif path == '/api/packs/list':
                result = {'rows':packs.load(store),'banners':json.loads((RESOURCE/'native-pack-template.json').read_text(encoding='utf8'))['banners']}
            elif path == '/api/packs/save':
                result = packs.save(store,body['pack'])
            elif path == '/api/packs/random-options':
                result = {'rows':packs.random_options(self.server.library.resources,store)}
            elif path == '/api/packs/random':
                result = packs.random_members(self.server.library.resources,body,store)
            elif path == '/api/appearance/profile':
                from native_appearance import profile
                result = profile(self.server.library.resources,body['id']) or {}
            elif path == '/api/model/head-preview':
                result = self.server.head_preview.prepare(normalize_project(body['project']))
            elif path == '/api/thumbnail/preview':
                result = self.server.thumbnail_preview.prepare(normalize_project(body['project']))
            elif path == '/api/card-motion/import':
                from custom_motion_import import convert
                role=body.get('role','both')
                if role not in ('both','mini'):raise ValueError('动画转换目标无效')
                result=convert(store,self.server.library.ffmpeg,body['path'],['large','mini'] if role=='both' else ['mini'],body.get('crop_x',0),body.get('crop_y',0))
            elif path == '/api/native-apk/status':
                result = self.server.native_package.status()
            elif path == "/api/project/new":
                result = store.new_player_slot()
            elif path == '/api/projects/export':
                from project_sharing import export_selected
                result=export_selected(store,body['selected_ids'],normalize_project(body['project']))
            elif path == '/api/tools/status':
                from workspace_tools import export_list,game_options
                result={**export_list(store),'game_options':game_options(store),'platform':globals().get('PLATFORM','pc'),'busy':self.server.native_package.status()['phase']=='working' or self.server.game_import.status()['phase']=='working'}
            elif path == '/api/tools/game-options':
                from workspace_tools import game_options
                result=game_options(store,body)
            elif path == '/api/tools/game-settings':
                from game_settings import settings,schema
                with store.lock:result={'value':settings(store,body.get('value')),'schema':schema()}
            elif path == '/api/exports/clear':
                from workspace_tools import clear_exports
                result=clear_exports(self.server)
            elif path == '/api/compiler-cache/clear':
                from workspace_tools import clear_compiler_cache
                result=clear_compiler_cache(self.server)
            elif path == '/api/exports/open':
                from workspace_tools import open_export
                result=globals().get('open_export_action',open_export)(store,body['name'])
            elif path == "/api/dialog":
                result = {"path": dialog(body.get("kind", "open"), body.get("category", "project"), body.get("initial", ""))}
            elif path == "/api/project/import":
                result = {"project": store.import_project(body["path"])}
            elif path == "/api/project/export":
                result = store.export_project(body["project"])
            elif path == "/api/assets/import":
                result = store.import_asset(body["path"], body.get("category", "image"))
            elif path == "/api/assets/data":
                result = store.import_screenshot(body["data"])
            elif path == "/api/exit":
                result = {"closed": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                return self.send({"error": "未知操作"}, 404)
            self.send(result)
        except Exception as exc:
            logging.exception("Operation failed")
            if '/export' in path:
                from export_errors import failure
                request_body=locals().get('body',{});request_body=request_body if isinstance(request_body,dict) else {}
                item=request_body.get('project') or request_body.get('package_id') or request_body.get('save') or path
                if path=='/api/package/export':item=request_body.get('player_name') or ('球员卡号 '+str(request_body.get('id'))+'／实例 '+str(request_body.get('serial')))
                exc=failure(exc,'导出资料',item,path)
            self.send({"error": str(exc),"error_context":getattr(exc,'contexts',[]),"error_type":getattr(exc,'original_type',type(exc).__name__)}, 400)


def open_window(url, data):
    candidates = [Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
                  Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"]
    for exe in candidates:
        if exe.is_file():
            subprocess.Popen([str(exe), "--app=" + url, "--window-size=1580,1020", "--no-first-run", "--disable-background-mode",
                              "--user-data-dir=" + str(Path(data) / "browser")], close_fds=True)
            return
    webbrowser.open(url)


def source_apk(home, configured, filename):
    """Resolve movable portable inputs without retaining another PC\'s paths."""
    home=Path(home)
    candidates=([Path(configured)] if configured else [])+[home/"原始APK"/filename,home/filename,home.parent/filename]
    return next((str(p) for p in candidates if p.is_file()), "")

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir")
    parser.add_argument("--no-idle-exit", action="store_true")
    args = parser.parse_args(argv)
    home = Path(sys.executable).absolute().parent if getattr(sys, "frozen", False) else Path(__file__).absolute().parent
    data = Path(args.data_dir).absolute() if args.data_dir else home / "data"
    runtime_path = data / "runtime.json"
    if runtime_path.is_file():
        try:
            existing = json.loads(runtime_path.read_text(encoding="utf8"))
            existing_url = urlsplit(existing["url"])
            if existing_url.hostname != "127.0.0.1":
                raise ValueError("无效的本地会话")
            existing_token = parse_qs(existing_url.query)["token"][0]
            request = urllib.request.Request(f"http://127.0.0.1:{existing['port']}/api/ping", headers={"X-Studio-Token": existing_token})
            with urllib.request.urlopen(request, timeout=1) as response:
                if not json.load(response).get("ok"):
                    raise ValueError("会话不可用")
            if not args.no_browser:
                open_window(existing["url"], data)
            if sys.stdout:
                print(json.dumps(existing), flush=True)
            return
        except Exception:
            pass
    store = Store(data)
    logging.basicConfig(filename=store.root / "studio.log", level=logging.INFO, encoding="utf8")
    tempfile.tempdir = str(store.root / "tmp")
    server = StudioServer(("127.0.0.1", args.port), store)
    url = f"http://127.0.0.1:{server.server_port}/?token={server.token}"
    runtime = {"pid": os.getpid(), "port": server.server_port, "url": url, "version": APP_VERSION}
    runtime_path = store.root / "runtime.json"
    runtime_path.write_text(json.dumps(runtime, indent=2), encoding="utf8")
    if sys.stdout:
        print(json.dumps(runtime), flush=True)
    if not args.no_browser:
        open_window(url, store.root)
    def idle_monitor():
        while True:
            time.sleep(15)
            busy=server.game_import.status()['phase']=='working' or server.native_package.status()['phase']=='working' or server.library.state['phase']=='preparing'
            if not args.no_idle_exit and not busy and time.monotonic() - server.last_seen > 180:
                server.shutdown()
                return
    threading.Thread(target=idle_monitor, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        server.server_close()
        runtime_path.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if sys.stderr:
            raise
        ctypes.windll.user32.MessageBoxW(None, str(error), "球员工坊启动失败", 0x10)
