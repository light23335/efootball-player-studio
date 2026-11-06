"""Build a signed V14 APK with native personal resources and a progress hook."""
from export_errors import call as _export_data
from pathlib import Path
from export_errors import export_context, exported, call as export_call, failure
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import marshal
import shutil
import sqlite3
import struct
import sys
import threading
import time
import uuid
import zipfile

from native_cpk import Cpk,unwrap,cached_export,decode_statistics
from native_tables import PLAYER,rows,compile_tables
from native_player import reserve_identity,compile_player
from native_art import compile_art
from native_iostore import Container,append_container
from apk_format import replace_entries,local_signer,sign_v2,verify_v2
from export_payload import FilePayload,measure,metadata as payload_metadata,verified_engine,verify_replacements
from export_timing import ExportTimings
from packs import load as load_packs,compile_packs
from native_live import reserve_shared,compile_template,verify_template
from personal_binding import reserve_asset_key,compose,fingerprint
from coaches import CoachStore
from native_coaches import compile_coaches
from overall import maximum_development
from native_v14_repairs import card_series
from native_models import person_keys
import personal_source
from custom_boosters import issues as booster_issues,validate_projects as validate_boosters,canonical as booster_definition,context as booster_context,reserve_booster

PREFIX='assets/gateway-release/'
NATIVE='custom-resources/legends-v10/'
COMPILER_REVISION='v17-source-aware-selection-2.1.6'


def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8')


def _reserve_live_version(library,store,release,template,fingerprint):
    """One real export observes its selected source and current library APK."""
    from native_live import library_version
    observed=library_version(library,store)
    shared=library.home.parent/'.player-studio-shared/native-live-versions.json'
    local=store.root/'native-live-versions.json'
    seeds=[library.home.parent/name/'data/native-live-versions.json'for name in('球员工坊','球员工坊-V14','球员工坊-V15')]
    return reserve_shared(shared,local,release,template,fingerprint,seeds,observed_versions=(observed,))


def bytecode(source,filename):
    code=compile(source,filename,'exec',dont_inherit=True)
    return importlib.util.MAGIC_NUMBER+struct.pack('<III',0,0,len(source.encode('utf8')))+marshal.dumps(code)


WORLD_HELPERS=('stadium_runtime','tournament_rules','tournament_identity','tournament_squads','tournament_eligibility','tournament_runtime','tournament_sim_strength','tournament_simulation','coach_formula','tournament_promotion','tournament_promotion_ui','tournament_rewards','tournament_agents','tournament_schedule_ui','native_tournament_schedule_ui','tournament_home','tournament_reward_ui','league_availability')


def competition_menu_hooks(engine,resources,menu_sha256,tournaments):
    """The original League cache bridge is needed even without custom events."""
    from native_tournament_home import hooks as home_hooks
    result=home_hooks(engine,resources,menu_sha256=menu_sha256)
    if tournaments:
        from native_tournament_schedule_ui_entry import hooks as schedule_entry_hooks
        from native_tournament_contract_ui import hooks as contract_hooks
        result=schedule_entry_hooks(engine,[t['event_id']for t in tournaments],resources,menu_sha256=menu_sha256)+result
        result+=contract_hooks(engine,resources)
    return result

def hook_archive(raw,runtime_source,binding_source=None,division_source=None,rating_source=None,helper_sources=None):
    src=zipfile.ZipFile(io.BytesIO(raw));stub=src.read('embedded_gateway.pyc')
    if stub[:4]!=importlib.util.MAGIC_NUMBER:raise ValueError('游戏 Python 字节码版本不同，未修改 APK')
    # Keep the original protected loader and all its modules unchanged.
    source='import _protected_runtime\n_protected_runtime.exec_into(__name__, globals())\nimport personal_runtime\npersonal_runtime.install(globals())\n'
    dest=io.BytesIO()
    with zipfile.ZipFile(dest,'w') as out:
        for entry in src.infolist():
            if entry.filename in tuple(name+'.pyc'for name in WORLD_HELPERS)+('embedded_gateway.pyc','personal_runtime.pyc','personal_binding.pyc','division_squads.pyc','native_overall.pyc','ai_tactical_profiles.pyc','ai_division_sessions.pyc','ai_match_manager.pyc','ai_match_channel.pyc','ai_match_runtime.pyc','ai_match_state.pyc','action_trace.pyc','league_rules.pyc','art_registry.pyc','native_diy_binding.pyc','draw_policy.pyc','draw_journal.pyc','draw_v22.pyc'):continue
            out.writestr(entry,src.read(entry))
        out.writestr('embedded_gateway.pyc',bytecode(source,'embedded_gateway.py'),compress_type=zipfile.ZIP_DEFLATED)
        out.writestr('personal_runtime.pyc',bytecode(runtime_source,'personal_runtime.py'),compress_type=zipfile.ZIP_DEFLATED)
        if binding_source is not None:out.writestr('personal_binding.pyc',bytecode(binding_source,'personal_binding.py'),compress_type=zipfile.ZIP_DEFLATED)
        if division_source is not None:out.writestr('division_squads.pyc',bytecode(division_source,'division_squads.py'),compress_type=zipfile.ZIP_DEFLATED)
        if rating_source is not None:out.writestr('native_overall.pyc',bytecode(rating_source,'native_overall.py'),compress_type=zipfile.ZIP_DEFLATED)
        for name,content in (helper_sources or {}).items():
            if name not in WORLD_HELPERS+('ai_tactical_profiles','ai_division_sessions','ai_match_manager','ai_match_channel','ai_match_runtime','ai_match_state','action_trace','league_rules','art_registry','native_diy_binding','draw_v22'):raise ValueError('Unknown game helper module')
            out.writestr(name+'.pyc',bytecode(content,name+'.py'),compress_type=zipfile.ZIP_DEFLATED)
    return dest.getvalue()


class NativePackage:
    def __init__(self,library,resources,runtime_source,profile_resources=None):
        self.library=library;self.resources=Path(resources);self.store=library.store;self.runtime_source=runtime_source
        self.profile_resources=Path(profile_resources or resources)
        self.lock=threading.Lock();self.state={'phase':'idle'}

    def status(self):
        with self.lock:return copy.deepcopy(self.state)

    def reference_model(self):
        # A custom mesh is compiled into the pc3600 carrier. Its bind poses
        # must come from that same carrier, independently of preview quality.
        path='PesMobile/Content/Assets/character/RealFace/SK_133543_Face.uasset'
        target=self.library.converted/Path(path).with_name('SK_133543_Face-bind-template-native.glb')
        if not target.is_file():
            self.update(message='自动准备原版脸模骨架与接合模板')
            from native_skeletal import mesh_glb
            assets=self.library.face_assets()
            container=next((c for c in assets.containers if c.path.stem=='pc3600_mobile_and'),None)
            if container is None:raise ValueError('离线资源包缺少原版脸模骨架模板')
            class Carrier:
                def raw(self,name):return container.read('../../../'+path)
            source=target.with_name('SK_133543_Face-bind-template.glb')
            source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(mesh_glb(Carrier(),path))
            self.library.texture_model(source,{'path':path})
            if not target.is_file():raise ValueError('原版骨架模板自动读取失败')
        return target

    def update(self,**values):
        with self.lock:self.state.update(values)

    def cleanup_work(self,work,prefix):
        if work is None or not work.exists():return
        parent=(self.store.root/'tmp').resolve();resolved=work.resolve()
        if resolved.parent!=parent or resolved.name!=work.name or not work.name.startswith(prefix) or work.is_symlink() or work.is_junction():
            self.update(cleanup_warning='构建临时目录不在预期位置，未自动清理');return
        try:shutil.rmtree(resolved)
        except OSError:self.update(cleanup_warning='部分构建临时文件仍被占用，可稍后清理')

    def model_binding(self,p):
        model=p.get('model',{});asset=model.get('asset')
        if not asset:raise ValueError('未选择脸模')
        if (model.get('native_source') or {}).get('path'):return None
        from native_glb import Glb,prove_binding
        static=Glb((self.store.root/'assets'/asset).read_bytes())
        if static.doc.get('skins'):return None
        options=[]
        if model.get('rigged_asset'):options.append(self.store.root/'assets'/model['rigged_asset'])
        folder=self.library.home.parent/'我的脸模'
        if folder.is_dir():options.extend(sorted(folder.glob('*.glb'))[:50])
        for path in options:
            try:
                bound=Glb(path.read_bytes())
                if bound.doc.get('skins'):
                    prove_binding(static,bound);return str(path)
            except (ValueError,KeyError,OSError):continue
        return None  # Export attaches foreign/static heads to a neutral native rig with a warning.

    def candidates(self,current):
        saved=self.store.list_players();projects={r['package_id']:self.store.saved_player(r['package_id'])['project'] for r in saved['rows']}
        projects[current['package_id']]=current;rows=[]
        catalog=_export_data("资料文件",self.resources / 'catalog.json',"读取并解析 JSON",lambda: json.loads((self.resources/'catalog.json').read_text(encoding='utf8')))
        from skill_localization import apply_labels
        apply_labels(catalog,self.resources)
        for uid,p in projects.items():
            error=''
            try:self.model_binding(p)
            except (ValueError,OSError) as exc:error=str(exc)
            warning=''
            if p.get('model',{}).get('asset') and not (p['model'].get('native_source') or {}).get('path'):
                warning='自制头模将检查骨架；非原生骨架会提示，并使用原生头骨中性绑定继续生成。原模型文件保留。'
            rows.append({'package_id':uid,'name':p['display_name'] or p['identity']['name'],'card_type':p['card_type'],
                         'current':uid==current['package_id'],'model_error':error,'model_warning':warning,
                         'booster_error':'；'.join(booster_issues(p,catalog['ABILITIES'])),
                         'maximum_overall':maximum_development(p,catalog)['overall'],'max_level':p['max_level']})
        from coach_models import prepare as prepare_coach_model
        coach_rows=[prepare_coach_model(c,self.library) for c in self.coach_candidates(current)]
        return {'rows':rows,'errors':saved['errors'],'coaches':[{'uuid':c['uuid'],'name':c['name'],'has_model':bool(c.get('head_model'))} for c in coach_rows],
                'packs':[{'uuid':p['uuid'],'name':p['name'],'enabled':p['enabled'],'member_count':len(p['members'])} for p in load_packs(self.store)]}

    def coach_candidates(self,current):
        abilities=_export_data("资料文件",self.resources / 'catalog.json',"读取并解析 JSON",lambda: json.loads((self.resources/'catalog.json').read_text(encoding='utf8')))['ABILITIES']
        rows={c['uuid']:c for c in CoachStore(self.store.root,abilities).list()['rows']}
        for c in current.get('custom_coaches',[]):rows[c['uuid']]=c
        return list(rows.values())

    def write_candidates(self,current,writing='full',apk=None):
        from write_modes import mode,source,statuses,design,requirements
        mode(writing);doc,summary=source(apk,requirements(self.library))if apk else({},None)
        result=self.candidates(current)
        projects={r['package_id']:self.store.saved_player(r['package_id'])['project']for r in self.store.list_players()['rows']}
        projects[current['package_id']]=current
        local={'players':list(projects.values()),'coaches':self.coach_candidates(current),'packs':load_packs(self.store)}
        fields={'players':'package_id','coaches':'uuid','packs':'uuid'};positive={}
        for kind,field in fields.items():
            states=statuses(kind,local[kind],doc,self.store)
            positive[kind]={v[field]:design(kind,v,self.store)for v in local[kind]if states[v[field]]=='unchanged'}
            rows=result['rows'if kind=='players'else kind]
            for row in rows:
                row['write_state']=states.get(row[field],'new')
                if kind=='players'and row['write_state']=='unchanged':
                    row['model_error']='';row['model_warning']='未修改，直接复用来源包现有卡面与脸模'
            if writing=='full':
                seen={r[field]for r in rows}
                for old in doc.get(kind,[]):
                    uid=old['identity']['package_id']if kind=='players'else old['uuid']
                    if uid in seen:continue
                    if kind=='players':
                        payload=old['owned'];rows.append({'package_id':uid,'name':payload.get('name','来源包球员'),'card_type':old['card_type'],
                            'current':False,'max_level':payload.get('level_info',{}).get('level_limit',1),
                            'maximum_overall':old.get('maximum_development',{}).get('overall',0),'model_warning':'来自来源包，保留其现有卡面与脸模',
                            'source_only':True,'write_state':'source_only'})
                    elif kind=='coaches':rows.append({'uuid':uid,'name':old['payload']['name'],'has_model':any(m['uuid']==uid for m in doc.get('coach_models',[])),'source_only':True,'write_state':'source_only'})
                    else:rows.append({'uuid':uid,'name':old['name'],'enabled':old['enabled'],'member_count':len(old['members']),'source_only':True,'write_state':'source_only'})
        result['hidden_unchanged']=0
        if writing=='incremental':
            result['hidden_unchanged']=sum(r['write_state']=='unchanged'for r in result['rows'])
            result['rows']=[r for r in result['rows']if r['write_state']!='unchanged']
        result['write_source']=summary
        from world_workspace import load as load_world
        from tournament_runtime import export_rows
        result['tournaments']=export_rows(load_world(self.store)['tournaments'],doc.get('tournaments',[]))
        if summary:
            with self.lock:self._write_positive=(summary['token'],positive)
        return result

    @exported('APK','实装前检查',lambda self,body: body.get('apk') or body.get('companion') or '生成所选内容')
    def start(self,body):
        with self.lock:
            if self.state['phase']=='working':raise ValueError('已有 APK 实装任务正在进行')
            if body.get('installation_mode','update') not in ('update','coexist'):raise ValueError('安装方式无效')
            if body.get('operation')=='companion':
                self.state={'phase':'working','message':'为离线资源 APK 生成同一本机签名'}
                threading.Thread(target=self._companion,args=(body['companion'],body.get('installation_mode','update')),daemon=True).start()
                return copy.deepcopy(self.state)
            from coach_models import CoachModelStore
            # Old clients may still send include_coach_heads / coach_heads. Neither
            # can activate the retired global store or inject arbitrary targets.
            head_rows=CoachModelStore(self.store.root).list()
            current=body['project'];ids=body.get('selected_ids',[current['package_id']])
            if type(body.get('force_fps160',False)) is not bool:raise ValueError('160 帧开关无效')
            if not isinstance(ids,list) or len(ids)!=len(set(ids)) or len(ids)>10000:raise ValueError('球员选择无效')
            from write_modes import mode,source,statuses,designs,requirements
            writing=mode(body.get('write_mode','full'))
            source_doc,source_summary=source(body.get('apk'),requirements(self.library))
            if body.get('write_source_token')and body['write_source_token']!=source_summary['token']:raise ValueError('来源 APK 已发生变化，请重新读取写入列表后生成')
            old_ids={p['identity']['package_id']for p in source_doc.get('players',[])}
            source_only=set(body.get('source_only_ids',[]))
            if not source_only<=old_ids or not source_only<=set(ids):raise ValueError('来源包球员选择无效，请重新读取列表')
            selected_projects=[copy.deepcopy(current) if uid==current['package_id'] else export_call('球员',uid,'读取已保存工程',self.store.saved_player,uid)['project'] for uid in ids if uid not in source_only]
            player_states=statuses('players',selected_projects,source_doc,self.store)
            projects=[p for p in selected_projects if player_states[p['package_id']]!='unchanged']
            from project_resource_migration import prepare as prepare_project
            projects=[export_call('球员',p,'迁移原版卡面与脸模引用',prepare_project,p,self.resources,self.library.face_assets())[0] for p in projects]
            pack_ids=body.get('pack_ids',[]);selected_packs=[p for p in load_packs(self.store) if p['uuid'] in pack_ids]
            coach_ids=body.get('coach_ids',[]);selected_coaches=[c for c in self.coach_candidates(current) if c['uuid'] in coach_ids]
            if not set(coach_ids)<={c['uuid']for c in selected_coaches}|{c['uuid']for c in source_doc.get('coaches',[])}:raise ValueError('所选教练不存在')
            if not set(pack_ids)<={p['uuid']for p in selected_packs}|{p['uuid']for p in source_doc.get('packs',[])}:raise ValueError('所选卡包不存在')
            if len(pack_ids)!=len(set(pack_ids))or len(coach_ids)!=len(set(coach_ids)):raise ValueError('教练或卡包选择重复')
            if writing=='full':
                existing_members={str(cid):p['identity']['package_id']for p in source_doc.get('players',[])for cid in {p['identity']['card_id'],*p['identity'].get('previous_card_ids',[])}}
                local_pack_ids={p['uuid']for p in selected_packs}
                inspect_packs=selected_packs+[p for p in source_doc.get('packs',[])if p['uuid']in pack_ids and p['uuid']not in local_pack_ids]
                for pack in inspect_packs:
                    for member in pack['members']:
                        uid=member.get('id')if member.get('kind')=='custom'else existing_members.get(str(member.get('card_id')))
                        if uid and uid not in ids:raise ValueError(pack['name']+'：全量模式请同时勾选卡包引用的自建球员')
            coach_states=statuses('coaches',selected_coaches,source_doc,self.store);pack_states=statuses('packs',selected_packs,source_doc,self.store)
            coaches=[c for c in selected_coaches if coach_states[c['uuid']]!='unchanged']
            packs=[p for p in selected_packs if pack_states[p['uuid']]!='unchanged']
            design_rows=designs(selected_projects,selected_coaches,selected_packs,self.store)
            if getattr(self,'_write_positive',(None,))[0]==source_summary['token']:
                for kind,values in self._write_positive[1].items():design_rows[kind]={**values,**design_rows[kind]}
            body=dict(body,write_mode=writing,write_source_token=source_summary['token'],write_designs=design_rows,
                write_selected={'players':ids,'coaches':coach_ids,'packs':pack_ids})
            for pack in packs:
                if not pack['members']:raise ValueError(pack['name']+'：卡包是空草稿，请先添加球员后再生成 APK')
            from workspace_tools import game_options
            from game_settings import settings as read_game_settings
            option_settings=read_game_settings(self.store)
            from game_settings import normalize as normalize_game_settings
            if body.get('force_fps160'):option_settings['frame_rate']={'enabled':True,'target':160}
            if 'frame_rate' in body:option_settings['frame_rate']=body['frame_rate']
            option_settings=normalize_game_settings(option_settings)
            body=dict(body,export_settings=option_settings)
            from world_workspace import load as load_world,normalize as normalize_world
            world=normalize_world(load_world(self.store),self.store.root/'assets')
            from tournament_runtime import export_selection
            tournament_ids=body.get('tournament_ids',[t['uuid']for t in world['tournaments']if t.get('enabled')])
            body['tournament_config']=export_selection(world['tournaments'],source_doc.get('tournaments',[]),tournament_ids,writing)
            if body['tournament_config'] and source_doc and not ids and not coach_ids and not pack_ids:
                # A tournament-only update must retain the user's other content,
                # including tournaments they did not select for replacement.
                writing='incremental'
                body.update(write_mode=writing,tournament_only_update=True)
                body['tournament_config']=export_selection(world['tournaments'],source_doc.get('tournaments',[]),tournament_ids,writing)
            from world_workspace import selection_warnings
            body['tournament_selection_warnings']=selection_warnings(self.library,self.store,body['tournament_config'])
            # Stadium compilation does not validate unrelated, unselected drafts.
            world['tournaments']=[]
            body['world_workspace']=world if(self.store.root/'world-workspace.json').is_file()else None
            if not projects and not packs and not coaches and not head_rows and not source_doc and not world['stadium']['enabled'] and not world['stadium']['unlock_all'] and not body['tournament_config'] and not game_options(self.store).get('enabled') and not body.get('force_fps160') and not any(v['enabled'] for v in option_settings.values()):raise ValueError('请选择球员、教练、头模或卡包，或启用球场、赛事或游戏设置')
            validate_boosters(projects,self._booster_labels())
            self.state={'phase':'working','message':'核对当前游戏原包与所选球员','players':len(projects)}
        threading.Thread(target=self._worker,args=(dict(body,projects=projects,packs=packs,coaches=coaches,stock_coach_models=head_rows),),daemon=True).start()
        return self.status()

    def _companion(self,path,installation_mode='update'):
        work=None
        try:
            source=Path(path).absolute()
            from apk_installation import coexist_entries
            with zipfile.ZipFile(source) as z:
                if 'assets/resource-bootstrap/resources.zip' not in z.namelist():raise ValueError('请选择原版离线资源 APK')
                changes,installation=coexist_entries(z,installation_mode)
            work=self.store.root/'tmp'/('resource-signer-'+uuid.uuid4().hex);work.mkdir()
            unsigned=work/'unsigned.apk';apk_build=replace_entries(source,unsigned,changes,prepare_signing=True)
            key,cert=local_signer(self.store.root/'signing')
            output=self.store.root/'exports'/(('73efootball-工坊共存资源-' if installation_mode=='coexist' else '73efootball-离线资源-个人签名-')+time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:4]+'.apk')
            sign_v2(unsigned,output,key,cert,prepared=apk_build,consume=True);verified=verify_v2(output)
            from apk_installation import identity,remember_resource
            remember_resource(self.store,installation_mode,identity(output)['package'],verified['signer_sha256'])
            self.remember_installation_mode(source,installation_mode)
            self.update(phase='done',message='同签名资源 APK 已生成；首次安装请与个人球员 APK 配套使用',
                        result={'kind':'companion','path':str(output),'url':'/exports/'+output.name,'size':output.stat().st_size,'signature':verified,'installation':installation})
        except Exception as exc:
            import logging
            logging.exception('Native APK compilation failed')
            error=failure(exc,'离线资源 APK',path,'读取、重签名和校验资源包')
            self.update(phase='error',message=str(error),error_context=error.contexts,error_type=error.original_type)
        finally:self.cleanup_work(work,'resource-signer-')

    @cached_export
    def _worker(self,body):
        work=None;compile_cache=None;timings=ExportTimings()
        try:
            work=self.store.root/'tmp'/('native-'+uuid.uuid4().hex);work.mkdir()
            projects=body['projects'];apk=Path(body['apk']).absolute()
            validate_boosters(projects,self._booster_labels())
            rigs=[]
            for p in projects:
                with export_context('球员',p,'校验脸模绑定'):
                    try:rigs.append(self.model_binding(p))
                    except (ValueError,OSError) as exc:raise ValueError(p['identity']['name']+'：'+str(exc)) from exc
            timings.mark('input_and_rig_validation')
            registry_path=self.store.root/'native-player-registry.json'
            registry=_export_data("资料文件",registry_path,"读取并解析 JSON",lambda: json.loads(registry_path.read_text(encoding='utf8'))) if registry_path.exists() else {}
            booster_path=self.store.root/'native-booster-registry.json'
            booster_registry=_export_data("资料文件",booster_path,"读取并解析 JSON",lambda: json.loads(booster_path.read_text(encoding='utf8'))) if booster_path.exists() else {}
            asset_path=self.store.root/'native-asset-registry.json'
            asset_registry=_export_data("资料文件",asset_path,"读取并解析 JSON",lambda: json.loads(asset_path.read_text(encoding='utf8'))) if asset_path.exists() else {}
            coach_path=self.store.root/'native-coach-registry.json'
            coach_registry=_export_data("资料文件",coach_path,"读取并解析 JSON",lambda: json.loads(coach_path.read_text(encoding='utf8'))) if coach_path.exists() else {}
            with zipfile.ZipFile(apk) as source:
                if body.get('write_source_token'):
                    from write_modes import source as inspect_write_source,requirements
                    if inspect_write_source(apk,requirements(self.library))[1]['token']!=body['write_source_token']:raise ValueError('生成前来源 APK 已变化，请重新读取列表')
                from apk_installation import coexist_entries
                install_replacements,installation=coexist_entries(source,body.get('installation_mode','update'))
                release=_export_data("资料文件",PREFIX + 'release-manifest.json',"读取并解析 JSON",lambda: json.loads(source.read(PREFIX+'release-manifest.json')))
                from write_modes import compatible,requirements
                compatible(source,release,requirements(self.library))
                from content_autofill import synchronize
                source,content_replacements,content_sync_report=synchronize(source,self.library,work,self.update)
                release=json.loads(source.read(PREFIX+'release-manifest.json'))
                from native_tables import BOOSTERS
                source_cpk=source.read(PREFIX+NATIVE+'dt870_mobile_and.cpk')
                booster_data=unwrap(Cpk(source_cpk).read(BOOSTERS))
                if len(booster_data)%40:raise ValueError('原生增能表结构改变')
                occupied_boosters={int.from_bytes(booster_data[i+14:i+16],'little')&1023 for i in range(0,len(booster_data),40)}
                inherited=personal_source.read(source,release)
                from write_modes import mode,retained,removals,refresh_packs,prune_tables,source_container,final_designs
                writing=mode(body.get('write_mode','full'))
                compiled={'players':{p['package_id']for p in projects},'coaches':{c['uuid']for c in body.get('coaches',[])},'packs':{p['uuid']for p in body.get('packs',[])}}
                selected={k:set(v)for k,v in body.get('write_selected',compiled).items()}
                kept=retained(inherited,writing,selected,compiled)
                from content_delta import read_catalogue
                content_catalogue=read_catalogue(source)
                owners=personal_source.seed(inherited,registry,asset_registry)
                kept_owner_ids={p['identity']['package_id']for p in kept.get('players',[])}-compiled['players']
                selected_owners=[owner for uid,owner in owners.items()if uid in compiled['players']or writing=='full'and uid not in kept_owner_ids]
                replace_ids=set().union(*(p['aliases'] for p in selected_owners)) if selected_owners else set()
                inherited_boosters={b for p in owners.values() for b in p['boosters']}
                replace_boosters=set().union(*(p['boosters'] for p in selected_owners)) if selected_owners else set()
                seen_boosters={};selected_uuids={p['package_id'] for p in projects}
                for p in projects:
                    with export_context('球员',p,'分配和编译自定义增能'):
                        remap={};active=[b for b in p.get('custom_boosters',[]) if b['id'] in p['booster_ids']]
                        for booster in active:
                            with export_context('自定义增能',booster,'分配和编译自定义增能'):
                                uid=booster['uuid'];design=booster_definition(booster)
                                if uid in seen_boosters and seen_boosters[uid]!=design:raise ValueError(booster_context(p,booster)+'：同一永久增能的定义不同')
                                seen_boosters[uid]=design
                                try:
                                    prior=(inherited.get('editor_registries',{}).get('boosters',{})).get(uid)
                                    prior_alias=(inherited.get('editor_registries',{}).get('boosters',{})).get(uid+':slot0')
                                    assigned=reserve_booster(uid,booster_registry,occupied_boosters|inherited_boosters,prior,first_slot=booster['id']==p['booster_ids'][0],prior_alias=prior_alias)
                                except ValueError as exc:raise ValueError(booster_context(p,booster)+'：'+str(exc)) from exc
                                # A shared source booster cannot change an unselected player.
                                shared=[row for row in kept.get('players',[]) if row['identity']['package_id'] not in selected_uuids and assigned in row['base_parameters'][144:147]]
                                if shared:
                                    before=inherited.get('preview_boosters',{}).get(str(assigned))
                                    effects={str(k):v for k,v in booster['effects'].items() if v}
                                    if not before or {str(k):v for k,v in before['effects'].items() if v}!=effects:raise ValueError(booster_context(p,booster)+'：个人包内未选中的其他球员仍使用此增能；请同时选择相关球员，或新建独立增能')
                                remap[booster['id']]=assigned;booster['id']=assigned
                    p['booster_ids']=[remap.get(v,v) for v in p['booster_ids']];p['custom_boosters']=active
                self.update(message='一次解压并完整校验引擎，供所有接口检查复用')
                timings.mark('source_registry_and_booster_setup')
                engine_file=verified_engine(source,work,self.library.profile['native_engine_sha256'])
                with engine_file.open() as lib:
                    lib.seek(self.library.profile['resource_key_offset']);engine_key=lib.read(32)
                if hashlib.sha256(engine_key).hexdigest()!=self.library.profile['resource_key_sha256']:
                    raise ValueError('此 APK 的原生引擎与 V14 模板不同')
                timings.mark('engine_extract_hash_and_key')
                original=source_cpk
                from catalogue_trash import patch_tables as recycle_tables,active as recycle_items,policy as recycle_policy,patch_seed as recycle_seed
                original=recycle_tables(original,self.store,restore_only=True)
                recycled=recycle_items(self.store)
                original_cpk=Cpk(original)
                records=rows(unwrap(original_cpk.read(PLAYER)),400,8)
                occupied=set(records)|{k&0xfffffff for k in records}
                catalog=_export_data("资料文件",self.resources / 'catalog.json',"读取并解析 JSON",lambda: json.loads((self.resources/'catalog.json').read_text(encoding='utf8')))
                from skill_localization import apply_labels
                apply_labels(catalog,self.resources)
                costs=_export_data("资料文件",self.resources / 'native-progression.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-progression.json').read_text(encoding='utf8')))['costs']
                definitions=[];identities=[]
                with sqlite3.connect(self.resources/'library.sqlite3') as db:
                    template=json.loads(db.execute('select payload from players where id=?',('7511',)).fetchone()[0])
                    for p in projects:
                        with export_context('球员',p,'编译永久编号与球员属性'):
                            own=owners.get(p['package_id'],{}).get('aliases',set())
                            identity=reserve_identity(p,occupied-own,registry);identities.append(identity)
                            from player_identity_binding import owned_person_aliases
                            occupied.update((identity['card_id'],*owned_person_aliases(identity)))
                            nation=p['identity'].get('nation_id')
                            if not nation:
                                row=db.execute('select id from identities where kind=? and name=?',('nation',p['identity']['nationality'])).fetchone()
                                if not row:raise ValueError(p['identity']['name']+'：请选择原版国家/地区后再实装')
                                nation=row[0]
                            team=p['identity'].get('team_id')
                            if not team:raise ValueError(p['identity']['name']+'：请选择原版球队后再实装')
                            source_id=(p.get('source_player') or {}).get('id') or (p.get('native_card') or {}).get('source_id')
                            source_record=records.get(int(source_id)) if source_id else None
                            definitions.append(compile_player(p,catalog,costs,identity,template,int(nation),int(team),source_record,game_version=self.library.profile.get('game_version','V14')))
                from pack_covers import compile_covers
                cover_files,cover_bindings,cover_routes=compile_covers(body['packs'],self.store)
                all_definitions={d['identity']['package_id']:d for d in kept.get('players',[])}
                all_definitions.update({d['identity']['package_id']:d for d in definitions})
                from pack_catalogue import from_archive
                blocked={**from_archive(source),**{cid:{'name':row['name'],'reason':'回收站'}for cid,row in recycled.items()}}
                packs=compile_packs(body['packs'],list(all_definitions.values()),self.resources,cover_bindings,blocked)
                self.update(message='编译个人卡图、脸模网格与原生材质')
                timings.mark('player_and_pack_definitions')
                reference=self.reference_model() if any(not (p.get('model',{}).get('native_source') or {}).get('path') for p in projects) else None
                metadata=_export_data("资料文件",self.resources / 'native-face-template.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-face-template.json').read_text(encoding='utf8')))
                art=[];bindings=[];art_reports=[];private_movie_files={};compile_cache=None;cache_warning=None
                try:
                    from compile_cache import CompileCache,source_context
                    compile_cache=CompileCache(self.store.root/'compiler-cache',source_context(self.library,self.resources))
                except (OSError,ValueError,TypeError,ImportError,AttributeError)as exc:
                    cache_warning='编译缓存不可用，本次正常重新编译：'+str(exc)
                for p,identity,rig in zip(projects,identities,rigs):
                    with export_context('球员',p,'编译卡图、脸模和自制动态背景'):
                        self.update(message='编译卡图与脸模：'+p['identity']['name'])
                        own=owners.get(p['package_id'],{}).get('aliases',set())
                        asset_key=reserve_asset_key(p['package_id'],{v&0xfffffff for v in records}-own,asset_registry)
                        packages,binding,report=compile_art(p,identity,self.library,rig,reference,metadata,asset_key,cache=compile_cache)
                        from private_card_motion import prepare as private_motion
                        if compile_cache and(p.get('native_card')or{}).get('custom_motion'):
                            from compile_cache import assets_in
                            motion_inputs={'uuid':p['package_id'],'custom_motion':p['native_card']['custom_motion'],
                                           'thumbnail_animation':p['appearance'].get('thumbnail_animation',True),'binding':binding}
                            def movie_build():
                                value=private_motion(p,binding,self.library)
                                return(*value,copy.deepcopy(binding))
                            value,movie_cache=compile_cache.run('animation',motion_inputs,movie_build,
                                files=[self.store.root/'assets'/name for name in assets_in(motion_inputs)],encoded=True)
                            private_art,private_files,private_report,binding=value;report['compile_cache']['animation']=movie_cache
                        else:private_art,private_files,private_report=private_motion(p,binding,self.library)
                        packages.extend(private_art);private_movie_files.update(private_files)
                        if private_report:report['custom_motion']=private_report
                        art.extend(packages);bindings.append(binding);art_reports.append(report)
                timings.mark('player_art_and_private_animation')
                self.update(message='写入原生球员表、卡面索引及增能效果')
                coach_catalog=_export_data("资料文件",self.resources / 'coaches.json',"读取并解析 JSON",lambda: json.loads((self.resources/'coaches.json').read_text(encoding='utf8')))['coaches']
                selected_coach_ids={c['uuid'] for c in body.get('coaches',[])}
                old_coaches=[c for c in inherited.get('coaches',[]) if c['uuid'] in selected_coach_ids]
                retired_coaches=[c for c in inherited.get('coaches',[])if writing=='full'and c['uuid']not in selected['coaches']]
                coach_registry.setdefault('coaches',{}).update({c['uuid']:c['id'] for c in old_coaches})
                coach_registry.setdefault('boosters',{}).update(inherited.get('editor_registries',{}).get('coach_boosters',{}))
                coach_registry.setdefault('links',{}).update(inherited.get('editor_registries',{}).get('coach_links',{}))
                from native_coach_links import compile_links,schema as link_schema
                selected_coaches=copy.deepcopy(body.get('coaches',[]))
                link_resources,link_ids,new_link_routes=compile_links(original_cpk,selected_coaches,coach_registry,link_schema(self.profile_resources))
                for coach in selected_coaches:coach['_compiled_link_ids']=link_ids[coach['uuid']]
                coach_resources,coaches=compile_coaches(original_cpk,selected_coaches,coach_catalog,coach_registry,
                    {c['id'] for c in old_coaches},{b for c in old_coaches for b in c['payload'].get('ability_id',[])[:2] if b})
                coach_resources.update(link_resources)
                from coach_models import compile_models as compile_coach_models,verify_loader as verify_coach_model_loader
                coach_model_art,coach_model_report=compile_coach_models(self.library,selected_coaches,coaches,{c['id'] for c in old_coaches})
                coach_model_loader=None
                if coach_model_art or kept.get('coach_models'):
                    with engine_file.open() as engine:coach_model_loader=verify_coach_model_loader(engine,self.profile_resources)
                from coach_portraits import compile_portraits,owned_paths
                coach_art,coach_portrait_report=compile_portraits(body.get('coaches',[]),coaches,self.library)
                art.extend(coach_art)
                from coach_heads import replacement_indices as head_replacements
                from coach_models import compile_stock_models,collect_head_resources
                self.update(message='编译教练三维头模')
                head_art,coach_head_report=compile_stock_models(self.library,body.get('stock_coach_models',[]),coach_catalog)
                art.extend(collect_head_resources(coach_model_art,coach_model_report,head_art,coach_head_report))
                from world_workspace import compile_stadium
                from tournament_runtime import configuration as tournament_configuration
                world=body.get('world_workspace');stadium_art=[];stadium_report={'enabled':False};stadium_config=inherited.get('stadium',{'enabled':False});tournament_config=body['tournament_config']
                if world is not None:
                    if self.library.profile.get('game_version')!='V17'and(world['stadium']['enabled']or tournament_config):raise ValueError('球场与赛事仅适用于已核对的 V17 接口')
                    self.update(message='编译球场 TIFO、场边装置与赛事规则')
                    stadium_art,stadium_config,stadium_report=compile_stadium(self.store,self.library,world)
                    art.extend(stadium_art)
                stadium_stock=[{'target':'PesMobile/Content/'+p[6:]+'.uasset','private_packages':[a[0]for a in stadium_art if '/PlayerStudio/Stadium/'in a[0]]}for p in stadium_report.get('native_table_paths',[])]
                from native_draw_v22 import compile_assets as compile_draw_assets
                draw_art,draw_replacements,draw_stock_groups,draw_report=export_call('抽卡演出','V22 音效蓝图与音效库','编译并校验 V22 抽卡资源',compile_draw_assets,self.library,self.profile_resources,source,content_replacements)
                art.extend(draw_art)
                from card_presentation import repair_routes
                carried_aliases=set().union(*(owners[p['identity']['package_id']]['aliases']for p in kept.get('players',[])))if kept.get('players')else set()
                carried_routes=[r for r in inherited.get('native_binding',{}).get('routes',[])if int(r['cardId'])in carried_aliases]
                prior_card_routes=repair_routes(copy.deepcopy(carried_routes),kept.get('players',[]),records)
                from card_motion import prepare as prepare_card_motion,replacement_indices as motion_replacements
                self.update(message='编译大小头像的动态背景与材质')
                motion=prepare_card_motion(self.library,bindings,prior_card_routes,
                    records,body['export_settings']['card_motion']['enabled'],self.profile_resources)
                bindings=motion['bindings'];inherited_card_routes=motion['routes']
                card_motion_report=motion['reports'];art.extend(motion['packages'])
                for name,raw in motion.get('movie_files',{}).items():
                    if name in private_movie_files and private_movie_files[name]!=raw:raise ValueError('小头像兼容视频与自制视频资源名冲突：'+name)
                    private_movie_files[name]=raw
                self.update(message='合并原生球员、外观、技能与增能资料表')
                timings.mark('coach_and_card_motion')
                entry_art=[];entry_stock=[]
                if tournament_config:
                    from tournament_entry import artwork,image_files
                    entry_art=artwork(self.library);art.extend(entry_art);entry_files,entry_routes=image_files(tournament_config,self.store)
                    entry_stock=[{'target':'PesMobile/Content/'+p[6:]+'.uasset','private_packages':[]}for p,_,_ in entry_art]
                    cover_files.update(entry_files);cover_routes.update(entry_routes)
                cpk,table_report=compile_tables(original,projects,definitions,self.resources,bindings,coach_resources,replace_ids,replace_boosters,source_cpk=original_cpk,tournaments=bool(tournament_config))
                removed_aliases=set().union(*(p['aliases']for uid,p in owners.items()if writing=='full'and uid not in selected['players']))if owners else set()
                cpk=prune_tables(cpk,removed_aliases,{c['id']for c in retired_coaches})
                cpk=recycle_tables(cpk,self.store)
                timings.mark('cpk_tables_and_text')
                src=source_container(source,work,engine_key)
                out=work/'pc3700_mobile_and.utoc'
                from native_body import container_parts
                additions,paths,packages=container_parts(art)
                removed_coach_ids={c['id']for c in retired_coaches}
                retired_prefixes=tuple(prefix+str(cid)+'_'for cid in removed_coach_ids for prefix in ('SK_','MI_','T_'))
                retired_model_paths={index for path,index in src.paths.items()if retired_prefixes and '/character/RealFace/'in path and path.rsplit('/',1)[-1].startswith(retired_prefixes)}
                owned_replacements=personal_source.owned_art_paths(src,selected_owners)|owned_paths(src,[c['id'] for c in old_coaches+retired_coaches])|retired_model_paths
                resource_build=append_container(src,out,additions,paths,packages,owned_replacements|motion_replacements(src,motion['packages'])|head_replacements(src,head_art+coach_model_art+draw_art+stadium_art+entry_art),cache=compile_cache,remove_indices=owned_replacements)
                timings.mark('iostore_build')
                replacements={**content_replacements,PREFIX+NATIVE+'dt870_mobile_and.cpk':cpk,
                              PREFIX+'livedata/dt870_mobile_and.cpk':cpk}
                replacements.update(draw_replacements)
                replacements.update(recycle_seed(source,self.store))
                from coach_heads import patch_stock_containers
                self.update(message='替换教练头模与抽卡音效原始容器，核对加载路径')
                stock_head_replacements,stock_head_report=patch_stock_containers(source,self.library,head_art+draw_art+stadium_art+entry_art,coach_head_report+draw_stock_groups+stadium_stock+entry_stock,work)
                replacements.update(stock_head_replacements)
                timings.mark('coach_stock_containers')
                native_movie_files=motion.get('native_movie_files',{})
                movie_package_report=None
                if private_movie_files or native_movie_files:
                    from movie_package import merge,MEMBER
                    self.update(message='核对动态卡面视频包缓存并合并新增视频')
                    replacements[MEMBER],movie_package_report=merge(source,replacements.get(MEMBER),private_movie_files,native_movie_files,work,compile_cache)
                timings.mark('movie_package')
                for suffix in ('.utoc','.ucas'):replacements[PREFIX+NATIVE+'pc3700_mobile_and'+suffix]=FilePayload.from_path(out.with_suffix(suffix))
                # Original activation verifies all four files, including its empty PAK.
                resource_files={};original_resource_files={}
                for name in ('dt870_mobile_and.cpk','pc3700_mobile_and.pak','pc3700_mobile_and.utoc','pc3700_mobile_and.ucas'):
                    if name=='dt870_mobile_and.cpk':original_resource_files[name]=payload_metadata(original)
                    else:
                        with source.open(PREFIX+NATIVE+name)as stream:info=measure(stream)
                        original_resource_files[name]={k:info[k]for k in('bytes','sha256')}
                    value=replacements.get(PREFIX+NATIVE+name)
                    resource_files[name]=original_resource_files[name]if value is None else payload_metadata(value)
                timings.mark('resource_hashes_and_payloads')
                template_path=PREFIX+'work/templates/CMD_LOGIN_LIVEDATA.json'
                live_template=_export_data("资料文件",template_path,"读取并解析 JSON",lambda: json.loads(source.read(template_path)))
                live_registry_path=self.store.root/'native-live-versions.json'
                from native_live import container_metadata,content_fingerprint
                live_containers=container_metadata(source,replacements,live_template)
                live_fingerprint=content_fingerprint(resource_files['dt870_mobile_and.cpk']['sha256'],live_containers)
                live_version,live_registry=_reserve_live_version(self.library,self.store,release['release_id'],live_template,live_fingerprint)
                live_template=compile_template(live_template,cpk,live_version,live_containers)
                live_report=verify_template(live_template,cpk)
                replacements[template_path]=compact(live_template)
                binding_source=(Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/'personal_binding.py').read_text(encoding='utf8')
                division_source=(Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/'division_squads.py').read_text(encoding='utf8')
                rating_source=(Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/'native_overall.py').read_text(encoding='utf8')
                helper_sources={name:(Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/(name+'.py')).read_text(encoding='utf8')
                                for name in WORLD_HELPERS+('ai_tactical_profiles','ai_division_sessions','ai_match_manager','ai_match_channel','ai_match_runtime','ai_match_state','action_trace','league_rules','art_registry','native_diy_binding','draw_v22')}
                from tournament_schedule_ui import runtime_source as schedule_runtime_source
                helper_sources['tournament_schedule_ui']=schedule_runtime_source(helper_sources['tournament_schedule_ui'],self.profile_resources/'tournament_schedule_ui')
                from tournament_rewards import runtime_source as rewards_runtime_source
                helper_sources['tournament_rewards']=rewards_runtime_source(helper_sources['tournament_rewards'],self.profile_resources)
                coaching_fingerprint=hashlib.sha256((self.profile_resources/'native-ai-match-adapter.json').read_bytes()).hexdigest()
                from studio_resources import bundled_resources
                trace_fingerprint=hashlib.sha256((bundled_resources()/'native-action-trace.json').read_bytes()).hexdigest()
                if tournament_config:
                    trace_fingerprint+=hashlib.sha256((self.profile_resources/'tournament_schedule_ui/native-entry.json').read_bytes()).hexdigest()
                    trace_fingerprint+=hashlib.sha256((self.profile_resources/'tournament_schedule_ui/native-home.json').read_bytes()).hexdigest()
                    trace_fingerprint+=hashlib.sha256((self.profile_resources/'tournament_schedule_ui/native-contract.json').read_bytes()).hexdigest()
                compiler_fingerprint=hashlib.sha256((self.runtime_source+'\0'+binding_source+'\0'+division_source+'\0'+rating_source+'\0'+'\0'.join(helper_sources.values())+'\0'+coaching_fingerprint+'\0'+trace_fingerprint+'\0'+COMPILER_REVISION).encode('utf8')).hexdigest()
                document={'compiler_fingerprint':compiler_fingerprint,'game_version':self.library.profile.get('game_version','V14'),'adapter_family':self.library.profile.get('family','V14'),'draw_profiles':_export_data("资料文件",self.profile_resources / 'native-draw-profiles.json',"读取并解析 JSON",lambda: json.loads((self.profile_resources/'native-draw-profiles.json').read_text(encoding='utf8'))),'format':'personal-player-native-v1','version':1,'players':definitions,'packs':packs,'coaches':coaches,
                          'training_groups':catalog['training_groups'],'resource_files':resource_files,
                          'original_resource_files':inherited.get('original_resource_files',original_resource_files),'live_data':live_report,
                          'card_series_by_id':card_series(cpk),
                          'preview_boosters':{str(b['id']):{'effects':b['effects'],'conditional':bool(b.get('conditional'))} for b in catalog['boosters']}}
                document['players']=list(all_definitions.values())
                document.update(stadium=stadium_config,stadium_preflight=stadium_report,tournaments=tournament_config)
                if tournament_config:document['tournament_entry_image']=next(iter(entry_routes))
                if tournament_config:
                    document['tournament_entry_images']={shape:next(path for path,entry in entry_routes.items()if entry['path'].endswith('-'+shape+'.jpg'))for shape in('portrait','landscape')}
                    from team_names import display as team_display
                    document['tournament_team_names']={str(r['id']):team_display(r)['name']for r in self.library.identities()['team']}
                    from world_workspace import national_teams
                    document['tournament_national_team_nations']=national_teams(self.library)
                    from tournament_schedule_ui_emblems import extract as extract_schedule_emblems
                    emblems=extract_schedule_emblems(self.library.containers,
                        sorted({team for t in tournament_config for team in t['team_ids']}),self.library.native,
                        nation_ids=document['tournament_national_team_nations'])
                    document['tournament_emblems']=emblems['teams']
                    document['tournament_emblem_report']={k:v for k,v in emblems.items()if k!='teams'}
                from world_workspace import unlock_catalogue
                document['stadium'].setdefault('unlock_all',True)
                unlock=unlock_catalogue()
                document['stadium']['unlock_catalogue']=unlock
                # Tournament rules use the scoped native match channel even
                # when the optional automatic coach is switched off.
                needs_coaching=bool(tournament_config)
                document['draw_presentation_revision']=draw_report.get('revision')if draw_report['enabled']else None
                document['draw_presentation_assets']=draw_report
                native_players=unwrap(Cpk(cpk).read(PLAYER),fresh=True)
                document['native_player_catalogue']={'version':1,'table_sha256':hashlib.sha256(native_players).hexdigest(),
                    'card_ids':sorted(rows(native_players,400,8))}
                document['content_catalogue']=content_catalogue
                document['catalogue_recycle_bin']=recycle_policy(self.store)
                document['catalogue_recycle_policy']='remove-owned-exact-cards; backup-save-before-removal; shared-art-retained'
                if tournament_config:
                    from tournament_rewards import export_catalogue as reward_catalogue
                    document['tournament_reinforcement_cards']=reward_catalogue(self.library,document,inherited.get('tournament_reinforcement_cards'))
                    from tournament_squads import export_standard_cards,export_fallback_standard_cards
                    document['tournament_standard_cards']=export_standard_cards(self.library,document)
                    document['tournament_fallback_standard_cards']=export_fallback_standard_cards(self.library,document)
                    document['tournament_standard_card_policy']={'unknown_level_limit':35,'scope':'private-tournament-squads','source':'selected-native-library; final Player.bin IDs only'}
                document['coach_heads']=coach_head_report
                document['coach_head_containers']=stock_head_report
                document['coach_models']=personal_source.merge(kept.get('coach_models',[]),coach_model_report,'uuid')
                document['coach_model_loader']=coach_model_loader
                document['pack_policy']={'allow_china_edition':True}
                from workspace_tools import game_options
                document['game_options']=game_options(self.store)
                export_settings=body['export_settings']
                document['game_settings']=export_settings
                document['card_motion_preflight']=card_motion_report
                document['frame_rate']={**export_settings['frame_rate'],'force_160':export_settings['frame_rate']['enabled'] and export_settings['frame_rate']['target']==160}
                document['installation']=installation
                if export_settings['display']['enabled'] or export_settings['frame_rate']['enabled']:
                    from native_display import verify_display
                    with engine_file.open() as render_engine:
                        document['render_preflight']=verify_display(render_engine,self.profile_resources)
                if document['frame_rate']['enabled']:
                    from native_fps import verify_fps160
                    with engine_file.open() as fps_engine:
                        document['frame_rate']['preflight']=verify_fps160(apk,fps_engine,document['frame_rate']['target'])
                from pack_catalogue import REFERENCE
                excluded=_export_data("资料文件",REFERENCE,"读取并解析 JSON",lambda: json.loads(source.read(REFERENCE))) if REFERENCE in source.namelist() else {}
                excluded={cid:row for cid,row in excluded.items() if row.get('type')not in ('China edition','Workshop recycle bin')}
                excluded.update({cid:{'name':row['name'],'type':'Workshop recycle bin'}for cid,row in recycled.items()})
                replacements[REFERENCE]=compact(excluded)
                document['packs']=refresh_packs(personal_source.merge(kept.get('packs',[]),packs,'uuid'),inherited.get('players',[]),document['players'])
                document['coaches']=personal_source.merge(kept.get('coaches',[]),coaches,'uuid')
                document['write_selection']={'mode':writing,'removed':removals(inherited,document),'source_players':len(inherited.get('players',[])),
                    'selected_players':len(selected['players']),'compiled_players':len(projects),'retained_players':len(document['players'])-len(projects),
                    'final_players':len(document['players']),'final_coaches':len(document['coaches']),'final_packs':len(document['packs'])}
                fallback=next((c for c in coach_catalog if c.get('raw_payload')and c.get('raw_payload_verified',True)),None)
                if fallback:document['write_selection']['fallback_coach']=copy.deepcopy(fallback['raw_payload'])
                document['write_designs']=final_designs(inherited.get('write_designs',{}),body.get('write_designs',{}),document)
                if document['game_version']=='V17':
                    from division_squads import configuration
                    from pack_catalogue import exclusions
                    document['division_squads']=configuration(catalog,exclusions(self.resources),export_settings['ai_division_squads'])
                    from division_squads import random_booster_pool
                    custom_ids=set(booster_registry.values())|set(inherited.get('editor_registries',{}).get('boosters',{}).values())
                    document['division_squads']['random_boosters']=random_booster_pool(catalog,cpk,custom_ids)
                    from division_squads import empty_booster_ids
                    document['division_squads']['empty_booster_ids']=empty_booster_ids(cpk,custom_ids)
                    from division_squads import booster_catalogue
                    document['native_booster_catalogue']=booster_catalogue(cpk)
                    document['division_squads']['excluded_ids']=list(set(document['division_squads']['excluded_ids'])|set(recycled))
                    document['division_squads']['style_mode']=document['game_options'].get('style_mode','shuffle_bag')
                    if tournament_config:
                        from world_workspace import selection_warnings
                        document['tournament_selection_warnings']=selection_warnings(self.library,self.store,tournament_config,document=document)
                    if document['division_squads']['enabled'] or needs_coaching:
                        from native_overall import verify_engine as verify_rating_engine
                        with engine_file.open() as rating_engine:
                            document['division_squads']['native_rating_preflight']=verify_rating_engine(rating_engine)
                document['preview_boosters']={**kept.get('preview_boosters',{}),**document['preview_boosters']}
                for p in projects:
                    with export_context('球员',p,'分配和编译自定义增能'):
                        for b in p.get('custom_boosters',[]):document['preview_boosters'][str(b['id'])]={'effects':b['effects'],'conditional':bool(b.get('conditional'))}
                from tournament_entry import merge_image_routes
                document['pack_covers']=merge_image_routes(kept.get('pack_covers',{}),cover_routes)
                document['editor_registries']={'boosters':booster_registry,'coach_boosters':coach_registry.get('boosters',{}),'coach_links':coach_registry.get('links',{})}
                document['coach_links']=list({r['id']:r for r in [*kept.get('coach_links',[]),*new_link_routes]}.values())
                for relative,content in cover_files.items():replacements[PREFIX+relative]=content
                if document['game_version']=='V17' or identities or inherited.get('native_binding') or content_catalogue['routes'] or document['coach_links'] or tournament_config or export_settings['controller']['enabled'] or export_settings['card_motion']['enabled']:
                    profile=_export_data("资料文件",self.resources / 'native-route-templates.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-route-templates.json').read_text(encoding='utf8')))
                    profile['club_emblems']=True
                    profile['external_routes']=True
                    profile['position_hook']=_export_data("资料文件",self.resources / 'native-position-hook.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-position-hook.json').read_text(encoding='utf8')))
                    profile['acquisition_hook']=_export_data("资料文件",self.resources / 'native-acquisition-hook.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-acquisition-hook.json').read_text(encoding='utf8')))
                    profile['overall_hook']=_export_data("资料文件",self.resources / 'native-overall-hook.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-overall-hook.json').read_text(encoding='utf8')))
                    mini_profile=self.resources/'native-thumbnail-hook.json'
                    if not mini_profile.is_file():mini_profile=self.profile_resources/'native-thumbnail-hook.json'
                    profile['thumbnail_hook']=_export_data("资料文件",mini_profile,"读取并解析 JSON",lambda: json.loads(mini_profile.read_text(encoding='utf8')))
                    # Imported databases may carry an older copy of this
                    # interface. Upgrade only an identical native entry point.
                    current_mini=_export_data("资料文件",self.profile_resources / 'native-thumbnail-hook.json',"读取并解析 JSON",lambda: json.loads((self.profile_resources/'native-thumbnail-hook.json').read_text(encoding='utf8')))
                    if current_mini.get('front_date_offset') is not None:
                        if any(profile['thumbnail_hook'].get(k)!=current_mini.get(k) for k in ('address','original_call','assign','mini_offset','expected_hex')):raise ValueError('此版本的大卡日期接口不同，未套用其他版本的图层位置')
                        for k in ('front_date_offset','front_date_evidence'):profile['thumbnail_hook'][k]=current_mini[k]
                    profile['thumbnail_hook']['stock_routes']=motion['stock_routes']
                    self.update(message='核对并写入技能、手柄与 AI 游戏适配资料')
                    from native_extensions import link_hooks
                    with engine_file.open() as engine:
                        profile['native_hooks']=export_call('游戏资料','native-coach-links.json','编译教练心有灵犀适配',lambda:link_hooks(document['coach_links'],engine,link_schema(self.profile_resources)))
                        from game_settings import controller_hooks
                        profile['native_hooks']+=export_call('游戏资料','native-controller.json','编译手柄键位',controller_hooks,export_settings['controller'],engine,self.profile_resources)
                        from native_skill_effects import hooks as skill_hooks,required as skill_effects_required
                        if skill_effects_required(document['players'],catalog):profile['native_hooks']+=export_call('游戏资料',self.profile_resources/'native-skill-effects.json','核对并写入比赛技能效果',skill_hooks,engine,self.profile_resources,definitions=document['players'])
                        from native_ai_style_ui import preflight as ai_style_preflight
                        document['ai_style_display']=ai_style_preflight(document['players'],profile['native_hooks'])
                        if document['game_version']=='V17':
                            from native_action_trace import hooks as action_trace_hooks,REVISION as ACTION_TRACE_REVISION
                            document['action_trace']={'enabled':export_settings['action_trace']['enabled'],'revision':ACTION_TRACE_REVISION,
                                                      'coverage':'native states, motion attempts and movement samples; candidate pass/dribble/shot before/after; request/power and native control flags; full-match acceptance pending'}
                            if document.get('division_squads',{}).get('enabled') or needs_coaching:
                                from native_ai_match import hooks as match_hooks
                                profile['native_hooks']+=export_call('游戏资料','native-ai-match-adapter.json','编译 AI 组队与临场调整适配',match_hooks,engine,self.profile_resources)
                                document['division_squads']['native_coaching_phase']='verified native execution; situational policy v5; local scenario validation; gameplay acceptance pending'
                            from native_ai_cut_in_shots import hooks as ai_cut_in_hooks,REVISION as AI_CUT_IN_REVISION
                            from game_settings import ai_decision_options
                            ai_options=ai_decision_options(export_settings,document['players'])
                            if export_settings['action_trace']['enabled']:
                                # One combined bundle owns each entry exactly once. Logging
                                # never replaces an enabled AI policy with native behavior.
                                if ai_options['enabled']:ai_cut_in_hooks(engine,ordinary_enabled=True)
                                profile['native_hooks']+=action_trace_hooks(engine,ai_enabled=ai_options['enabled'])
                            elif ai_options['enabled']:profile['native_hooks']+=export_call('游戏资料','native-ai-cut-in-shots.json','编译 AI 射门决策',ai_cut_in_hooks,engine,ordinary_enabled=True)
                            document['ai_cut_in_shots']={**ai_options,'experimental':True,'revision':AI_CUT_IN_REVISION,
                                                         'ordinary_choice':'possession-locked forced native style actions' if ai_options['enabled'] else 'native',
                                                         'possession_probability':0.7,'possession_end':'any holder change, including teammates',
                                                         'priority':['blitz_curler_setup','long_range_curler','long_range_shooting']}
                            from native_skill_capacity import hooks as capacity_hooks,REVISION as SKILL_CAPACITY_REVISION
                            profile['native_hooks']+=export_call('游戏资料','native-skill-capacity.json','编译技能数量与显示扩展',capacity_hooks,engine)
                            document['skill_capacity']={'innate':100,'additional':100,'display':'native-lists',
                                                        'revision':SKILL_CAPACITY_REVISION}
                    with engine_file.open() as engine:
                        for name in ('position_hook','acquisition_hook','overall_hook','thumbnail_hook'):
                            h=profile[name];engine.seek(h['file_offset'])
                            if engine.read(64).hex()!=h['expected_hex']:raise ValueError('此版本的小头像动画接口不同' if name=='thumbnail_hook' else '此版本的抽卡显示接口不同')
                        for evidence in profile['thumbnail_hook'].get('front_date_evidence',[]):
                            engine.seek(evidence['file_offset']);expected=bytes.fromhex(evidence['expected_hex'])
                            if engine.read(len(expected))!=expected:raise ValueError('此版本的 F09 日期图层布局不同，未生成错误的卡面绑定')
                    booster_routes={r['id']:r for r in inherited.get('native_binding',{}).get('profile',{}).get('boosters',[])}
                    booster_routes.update({r['id']:r for r in table_report['personal_booster_text_routes']})
                    if booster_routes:
                        profile['boosters']=list(booster_routes.values())
                        profile['text_hooks']=_export_data("资料文件",self.resources / 'native-text-hooks.json',"读取并解析 JSON",lambda: json.loads((self.resources/'native-text-hooks.json').read_text(encoding='utf8')))
                        with engine_file.open() as engine:
                            for kind in ('name','description'):
                                hook=profile['text_hooks'][kind];engine.seek(hook['file_offset'])
                                if engine.read(64).hex()!=hook['expected_hex']:raise ValueError('此版本的增能文字接口不同')
                    from native_binding_source import read_installer
                    original_binding,installer_code=read_installer(apk,content_catalogue=content_catalogue)
                    routes=[r for r in inherited_card_routes if int(r['cardId']) not in replace_ids]
                    for identity,binding,definition in zip(identities,bindings,definitions):
                        for cid in sorted({identity['card_id'],*owned_person_aliases(identity),int(binding['asset_key']),*identity['previous_card_ids']}):
                            routes.append({'cardId':cid,'suiteDonorId':identity['card_id'],
                                           'portraitKey':binding['asset_key'],'modelFaceKey':binding['asset_key'],
                                           'thumbnail_names':binding['thumbnail_names'],
                                           **({'front_names':binding['front_names'],'private_movie_textures':True} if binding.get('front_names') else {}),
                                           'club_id':definition['owned']['initial_base_team_id'],
                                           'position':definition['base_parameters'][0],
                                           'maximum_overall':definition['maximum_development']['overall'],
                                           'presentation_rarity':10 if definition['card_type'] in ('BigTime','Epic','Legendary') else 0})
                    from card_presentation import repair_routes
                    routes=repair_routes(routes,document['players'],records)
                    if document['game_version']=='V17' or tournament_config:
                        menu=self.library.face_assets().get('PesMobile/Content/Assets/menu/online/evCompe/MainMenu/BP_MenuEvCompeEventMainMenu.uasset')[0]
                        with engine_file.open()as schedule_engine:
                            profile.setdefault('native_hooks',[]).extend(competition_menu_hooks(schedule_engine,self.profile_resources,
                                hashlib.sha256(menu).hexdigest(),tournament_config))
                    compose(original_binding,routes,profile)
                    document['native_binding']={'routes':routes,'profile':profile,'original_fingerprint':fingerprint(original_binding)}
                    from native_binding_source import installer_metadata
                    if installer_metadata(installer_code):
                        document['native_binding']['source']=installer_metadata(installer_code)
                        if installer_metadata(installer_code).get('registry'):
                            document['native_binding']['original_fingerprint']=installer_metadata(installer_code)['raw_fingerprint']
                            document['native_binding']['prepared_fingerprint']=fingerprint(original_binding)
                    # Run the same closure/fingerprint verification performed
                    # on Android before signing, so a startup mismatch cannot
                    # leave the desktop compiler as a successful APK.
                    from native_binding_source import verify_installer
                    document['native_binding_preflight']=verify_installer(installer_code,document['native_binding'])
                from art_registry import verify_content
                document['content_binding_preflight']=verify_content(document)
                document['revision']=hashlib.sha256(compact(document)).hexdigest()
                from write_modes import patch_seed as patch_write_seed
                patch_write_seed(source,replacements,document)
                replacements[PREFIX+'custom-resources/personal-player-studio/players.json']=compact(document)
                replacements['assets/chaquopy/app.imy']=hook_archive(source.read('assets/chaquopy/app.imy'),self.runtime_source,
                    binding_source,division_source,rating_source,helper_sources)
                build=_export_data("资料文件",'assets/chaquopy/build.json',"读取并解析 JSON",lambda: json.loads(source.read('assets/chaquopy/build.json')))
                if build['assets']['app.imy']!=hashlib.sha1(source.read('assets/chaquopy/app.imy')).hexdigest():
                    raise ValueError('原版 Python 缓存标识不同，未生成安装包')
                build['assets']['app.imy']=hashlib.sha1(replacements['assets/chaquopy/app.imy']).hexdigest()
                replacements['assets/chaquopy/build.json']=compact(build)
                release['personal_player_revision']=document['revision']
                release['base_release_id']=release.get('base_release_id',release['release_id'])
                release['release_id']=release['base_release_id']+'-studio-'+document['revision'][:16]
                listed={row['path']:row for row in release['files']}
                for name,value in replacements.items():
                    if not name.startswith(PREFIX):continue
                    rel=name[len(PREFIX):];row={'path':rel,**payload_metadata(value)}
                    if rel in listed:listed[rel].update(row)
                    else:release['files'].append(row)
                replacements[PREFIX+'release-manifest.json']=compact(release)
                replacements.update(install_replacements)
                timings.mark('runtime_hooks_and_manifests')
            self.update(message='整理有效资源、回收旧导出数据并签名')
            unsigned=work/'unsigned.apk';apk_build=replace_entries(apk,unsigned,replacements,store_ucas=True,prepare_signing=True)
            timings.mark('apk_write_and_compress')
            output=self.store.root/'exports'/('73efootball-'+self.library.profile.get('game_version','V14')+('-工坊共存-' if body.get('installation_mode')=='coexist' else '-个人球员-')+time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:4]+'.apk')
            key,cert=local_signer(self.store.root/'signing')
            signing_performance=sign_v2(unsigned,output,key,cert,prepared=apk_build,consume=True)
            timings.mark('signing')
            verified=verify_v2(output)
            timings.mark('independent_signature_verification')
            self.update(message='核对成品实时更新清单与两份球员资料')
            from native_live import verify_apk as verify_live_apk
            try:live_apk_report=verify_live_apk(output,replacements)
            except Exception:
                output.unlink(missing_ok=True)
                raise
            timings.mark('readback_and_live_verification')
            self.update(message='保存永久编号注册表和导出报告')
            temp=registry_path.with_suffix('.tmp');temp.write_bytes(compact(registry));temp.replace(registry_path)
            temp=booster_path.with_suffix('.tmp');temp.write_bytes(compact(booster_registry));temp.replace(booster_path)
            temp=live_registry_path.with_suffix('.tmp');temp.write_bytes(compact(live_registry));temp.replace(live_registry_path)
            temp=asset_path.with_suffix('.tmp');temp.write_bytes(compact(asset_registry));temp.replace(asset_path)
            temp=coach_path.with_suffix('.tmp');temp.write_bytes(compact(coach_registry));temp.replace(coach_path)
            timings.mark('registry_saving')
            report={'identities':identities,'native_art':art_reports,'packs':[{'uuid':p['uuid'],'agent_id':p['agent_id'],'name':p['name'],'members':len(p['members']),'skipped_members':p.get('skipped_members',[])} for p in packs],
                    'native_tables':table_report,'signature':verified,'live_data':live_report,'live_apk_preflight':live_apk_report,'content_binding_preflight':document['content_binding_preflight'],
                    'apk_compaction':apk_build['compaction'],'resource_compaction':resource_build.compaction_report,
                    'compiler_cache':compile_cache.report()if compile_cache else{'enabled':False,'warning':cache_warning},
                    'signing_performance':signing_performance,
                    'export_io':{'revision':'2.1.3','engine_full_hash_verified':True,'engine_extractions':1,
                                 'engine_bytes':engine_file.bytes,'engine_sha256':engine_file.sha256,
                                 'file_payloads':sum(isinstance(v,FilePayload)for v in replacements.values()),
                                 'file_payload_bytes':sum(v.bytes for v in replacements.values()if isinstance(v,FilePayload)),
                                 'movie_package':movie_package_report,'replacement_verification':'streamed-sha256-size-and-zip-crc'},
                    'timings':timings.snapshot(),'cpk_decode':decode_statistics(),
                    'native_binding_routes':len(document.get('native_binding',{}).get('routes',[])),'frame_rate':document['frame_rate'],'game_settings':export_settings,'render_preflight':document.get('render_preflight'),'card_motion_preflight':card_motion_report,'installation':installation,
                    'coaches':[{'uuid':c['uuid'],'id':c['id'],'name':c['payload']['name']} for c in coaches],'coach_portraits':coach_portrait_report,'coach_heads':coach_head_report,'coach_head_containers':stock_head_report,'coach_models':coach_model_report,'coach_model_loader':coach_model_loader,
                    'write_selection':document['write_selection'],'content_autofill':content_sync_report,'source_apk':str(apk),'output':str(output),'engine_profile':release['base_release_id'],'resource_release':release['release_id'],
                    'in_game_tested':False,'progress_policy':'first grant only; existing instance retains live XP, training and statistics'}
            report_path=output.with_suffix('.report.json');report_path.write_bytes(compact(report))
            self.remember_installation_mode(apk,body.get('installation_mode','update'))
            self.update(phase='done',message='APK 已生成并通过签名与资源读回校验；待游戏内验收',
                        result={'path':str(output),'url':'/exports/'+output.name,'size':output.stat().st_size,
                                'report':report,'report_path':str(report_path)})
        except Exception as exc:
            import logging
            logging.exception('Native APK compilation failed')
            error=failure(exc,'游戏 APK',body.get('apk'),self.state.get('message') or '生成游戏 APK')
            self.update(phase='error',message=str(error),error_context=error.contexts,error_type=error.original_type)
        finally:
            if compile_cache is not None:compile_cache.close()
            self.cleanup_work(work,'native-')

    def remember_installation_mode(self,source,mode):
        from apk_sources import remember_mode
        try:remember_mode(self.store,source,mode)
        except OSError:
            import logging
            logging.exception('APK exported, but installation mode could not be remembered')

    def _booster_labels(self):
        path=self.resources/'catalog.json'
        return _export_data("资料文件",path,"读取并解析 JSON",lambda: json.loads(path.read_text(encoding='utf8')))['ABILITIES'] if path.is_file() else {}
