"""Build a signed V14 APK with native personal resources and a progress hook."""
from pathlib import Path
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

from native_cpk import Cpk,unwrap
from native_tables import PLAYER,rows,compile_tables
from native_player import reserve_identity,compile_player
from native_art import compile_art
from native_iostore import Container,append_container
from apk_format import replace_entries,local_signer,sign_v2,verify_v2
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
COMPILER_REVISION='v17-additional-design-sync-and-zidane-text-1.9.15.4'


def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8')


def bytecode(source,filename):
    code=compile(source,filename,'exec',dont_inherit=True)
    return importlib.util.MAGIC_NUMBER+struct.pack('<III',0,0,len(source.encode('utf8')))+marshal.dumps(code)


def hook_archive(raw,runtime_source,binding_source=None):
    src=zipfile.ZipFile(io.BytesIO(raw));stub=src.read('embedded_gateway.pyc')
    if stub[:4]!=importlib.util.MAGIC_NUMBER:raise ValueError('游戏 Python 字节码版本不同，未修改 APK')
    # Keep the original protected loader and all its modules unchanged.
    source='import _protected_runtime\n_protected_runtime.exec_into(__name__, globals())\nimport personal_runtime\npersonal_runtime.install(globals())\n'
    dest=io.BytesIO()
    with zipfile.ZipFile(dest,'w') as out:
        for entry in src.infolist():
            if entry.filename in ('embedded_gateway.pyc','personal_runtime.pyc','personal_binding.pyc'):continue
            out.writestr(entry,src.read(entry))
        out.writestr('embedded_gateway.pyc',bytecode(source,'embedded_gateway.py'),compress_type=zipfile.ZIP_DEFLATED)
        out.writestr('personal_runtime.pyc',bytecode(runtime_source,'personal_runtime.py'),compress_type=zipfile.ZIP_DEFLATED)
        if binding_source is not None:out.writestr('personal_binding.pyc',bytecode(binding_source,'personal_binding.py'),compress_type=zipfile.ZIP_DEFLATED)
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
        catalog=json.loads((self.resources/'catalog.json').read_text(encoding='utf8'))
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
        return {'rows':rows,'errors':saved['errors'],'coaches':[{'uuid':c['uuid'],'name':c['name']} for c in self.coach_candidates(current)],
                'packs':[{'uuid':p['uuid'],'name':p['name'],'enabled':p['enabled'],'member_count':len(p['members'])} for p in load_packs(self.store)]}

    def coach_candidates(self,current):
        abilities=json.loads((self.resources/'catalog.json').read_text(encoding='utf8'))['ABILITIES']
        rows={c['uuid']:c for c in CoachStore(self.store.root,abilities).list()['rows']}
        for c in current.get('custom_coaches',[]):rows[c['uuid']]=c
        return list(rows.values())

    def start(self,body):
        with self.lock:
            if self.state['phase']=='working':raise ValueError('已有 APK 实装任务正在进行')
            if body.get('installation_mode','update') not in ('update','coexist'):raise ValueError('安装方式无效')
            if body.get('operation')=='companion':
                self.state={'phase':'working','message':'为离线资源 APK 生成同一本机签名'}
                threading.Thread(target=self._companion,args=(body['companion'],body.get('installation_mode','update')),daemon=True).start()
                return copy.deepcopy(self.state)
            current=body['project'];ids=body.get('selected_ids',[current['package_id']])
            if type(body.get('force_fps160',False)) is not bool:raise ValueError('160 帧开关无效')
            if not isinstance(ids,list) or len(ids)!=len(set(ids)) or len(ids)>10000:raise ValueError('球员选择无效')
            projects=[copy.deepcopy(current) if uid==current['package_id'] else self.store.saved_player(uid)['project'] for uid in ids]
            from project_resource_migration import prepare as prepare_project
            projects=[prepare_project(p,self.resources,self.library.face_assets())[0] for p in projects]
            pack_ids=body.get('pack_ids',[]);packs=[p for p in load_packs(self.store) if p['uuid'] in pack_ids]
            coach_ids=body.get('coach_ids',[]);coaches=[c for c in self.coach_candidates(current) if c['uuid'] in coach_ids]
            if len(coaches)!=len(set(coach_ids)):raise ValueError('所选教练不存在')
            if len(packs)!=len(set(pack_ids)):raise ValueError('所选卡包不存在')
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
            if not projects and not packs and not coaches and not game_options(self.store).get('enabled') and not body.get('force_fps160') and not any(v['enabled'] for v in option_settings.values()):raise ValueError('请选择球员、教练或卡包，或启用游戏设置')
            validate_boosters(projects,self._booster_labels())
            self.state={'phase':'working','message':'核对当前游戏原包与所选球员','players':len(projects)}
        threading.Thread(target=self._worker,args=(dict(body,projects=projects,packs=packs,coaches=coaches),),daemon=True).start()
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
            unsigned=work/'unsigned.apk';replace_entries(source,unsigned,changes)
            key,cert=local_signer(self.store.root/'signing')
            output=self.store.root/'exports'/(('73efootball-工坊共存资源-' if installation_mode=='coexist' else '73efootball-离线资源-个人签名-')+time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:4]+'.apk')
            sign_v2(unsigned,output,key,cert);verified=verify_v2(output)
            from apk_installation import identity,remember_resource
            remember_resource(self.store,installation_mode,identity(output)['package'],verified['signer_sha256'])
            self.update(phase='done',message='同签名资源 APK 已生成；首次安装请与个人球员 APK 配套使用',
                        result={'kind':'companion','path':str(output),'url':'/exports/'+output.name,'size':output.stat().st_size,'signature':verified,'installation':installation})
        except Exception as exc:
            import logging
            logging.exception('Native APK compilation failed')
            self.update(phase='error',message=str(exc) or ('APK 编译失败：'+type(exc).__name__+'，详情见运行日志'))
        finally:self.cleanup_work(work,'resource-signer-')

    def _worker(self,body):
        work=None
        try:
            work=self.store.root/'tmp'/('native-'+uuid.uuid4().hex);work.mkdir()
            projects=body['projects'];apk=Path(body['apk']).absolute()
            validate_boosters(projects,self._booster_labels())
            rigs=[]
            for p in projects:
                try:rigs.append(self.model_binding(p))
                except (ValueError,OSError) as exc:raise ValueError(p['identity']['name']+'：'+str(exc)) from exc
            registry_path=self.store.root/'native-player-registry.json'
            registry=json.loads(registry_path.read_text(encoding='utf8')) if registry_path.exists() else {}
            booster_path=self.store.root/'native-booster-registry.json'
            booster_registry=json.loads(booster_path.read_text(encoding='utf8')) if booster_path.exists() else {}
            asset_path=self.store.root/'native-asset-registry.json'
            asset_registry=json.loads(asset_path.read_text(encoding='utf8')) if asset_path.exists() else {}
            coach_path=self.store.root/'native-coach-registry.json'
            coach_registry=json.loads(coach_path.read_text(encoding='utf8')) if coach_path.exists() else {}
            with zipfile.ZipFile(apk) as source:
                from apk_installation import coexist_entries
                install_replacements,installation=coexist_entries(source,body.get('installation_mode','update'))
                release=json.loads(source.read(PREFIX+'release-manifest.json'))
                if release['release_id']!=self.library.profile['release_id']:
                    raise ValueError('请选择当前数据库对应的 APK；更换主包请先在 APK 数据更新页导入')
                from native_tables import BOOSTERS
                booster_data=unwrap(Cpk(source.read(PREFIX+NATIVE+'dt870_mobile_and.cpk')).read(BOOSTERS))
                if len(booster_data)%40:raise ValueError('原生增能表结构改变')
                occupied_boosters={int.from_bytes(booster_data[i+14:i+16],'little')&1023 for i in range(0,len(booster_data),40)}
                inherited=personal_source.read(source,release)
                owners=personal_source.seed(inherited,registry,asset_registry)
                selected_owners=[owners[p['package_id']] for p in projects if p['package_id'] in owners]
                replace_ids=set().union(*(p['aliases'] for p in selected_owners)) if selected_owners else set()
                inherited_boosters={b for p in owners.values() for b in p['boosters']}
                replace_boosters=set().union(*(p['boosters'] for p in selected_owners)) if selected_owners else set()
                seen_boosters={};selected_uuids={p['package_id'] for p in projects}
                for p in projects:
                    remap={};active=[b for b in p.get('custom_boosters',[]) if b['id'] in p['booster_ids']]
                    for booster in active:
                        uid=booster['uuid'];design=booster_definition(booster)
                        if uid in seen_boosters and seen_boosters[uid]!=design:raise ValueError(booster_context(p,booster)+'：同一永久增能的定义不同')
                        seen_boosters[uid]=design
                        try:
                            prior=(inherited.get('editor_registries',{}).get('boosters',{})).get(uid)
                            prior_alias=(inherited.get('editor_registries',{}).get('boosters',{})).get(uid+':slot0')
                            assigned=reserve_booster(uid,booster_registry,occupied_boosters|inherited_boosters,prior,first_slot=booster['id']==p['booster_ids'][0],prior_alias=prior_alias)
                        except ValueError as exc:raise ValueError(booster_context(p,booster)+'：'+str(exc)) from exc
                        # A shared source booster cannot change an unselected player.
                        shared=[row for row in inherited.get('players',[]) if row['identity']['package_id'] not in selected_uuids and assigned in row['base_parameters'][144:147]]
                        if shared:
                            before=inherited.get('preview_boosters',{}).get(str(assigned))
                            effects={str(k):v for k,v in booster['effects'].items() if v}
                            if not before or {str(k):v for k,v in before['effects'].items() if v}!=effects:raise ValueError(booster_context(p,booster)+'：个人包内未选中的其他球员仍使用此增能；请同时选择相关球员，或新建独立增能')
                        remap[booster['id']]=assigned;booster['id']=assigned
                    p['booster_ids']=[remap.get(v,v) for v in p['booster_ids']];p['custom_boosters']=active
                with source.open('lib/arm64-v8a/libUE4.so') as lib:
                    lib.seek(self.library.profile['resource_key_offset']);engine_key=lib.read(32)
                if hashlib.sha256(engine_key).hexdigest()!=self.library.profile['resource_key_sha256']:
                    raise ValueError('此 APK 的原生引擎与 V14 模板不同')
                with source.open('lib/arm64-v8a/libUE4.so') as lib:
                    digest=hashlib.file_digest(lib,'sha256').hexdigest()
                if digest!=self.library.profile['native_engine_sha256']:
                    raise ValueError('此 APK 的完整引擎指纹与已验证 V14 不同，未生成安装包')
                original=source.read(PREFIX+NATIVE+'dt870_mobile_and.cpk')
                records=rows(unwrap(Cpk(original).read(PLAYER)),400,8)
                occupied=set(records)|{k&0xfffffff for k in records}
                catalog=json.loads((self.resources/'catalog.json').read_text(encoding='utf8'))
                from skill_localization import apply_labels
                apply_labels(catalog,self.resources)
                costs=json.loads((self.resources/'native-progression.json').read_text(encoding='utf8'))['costs']
                definitions=[];identities=[]
                with sqlite3.connect(self.resources/'library.sqlite3') as db:
                    template=json.loads(db.execute('select payload from players where id=?',('7511',)).fetchone()[0])
                    for p in projects:
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
                        definitions.append(compile_player(p,catalog,costs,identity,template,int(nation),int(team),source_record))
                from pack_covers import compile_covers
                cover_files,cover_bindings,cover_routes=compile_covers(body['packs'],self.store)
                all_definitions={d['identity']['package_id']:d for d in inherited.get('players',[])}
                all_definitions.update({d['identity']['package_id']:d for d in definitions})
                from pack_catalogue import from_archive
                packs=compile_packs(body['packs'],list(all_definitions.values()),self.resources,cover_bindings,from_archive(source))
                self.update(message='编译个人卡图、脸模网格与原生材质')
                reference=self.reference_model() if any(not (p.get('model',{}).get('native_source') or {}).get('path') for p in projects) else None
                metadata=json.loads((self.resources/'native-face-template.json').read_text(encoding='utf8'))
                art=[];bindings=[];art_reports=[]
                for p,identity,rig in zip(projects,identities,rigs):
                    self.update(message='编译卡图与脸模：'+p['identity']['name'])
                    own=owners.get(p['package_id'],{}).get('aliases',set())
                    asset_key=reserve_asset_key(p['package_id'],{v&0xfffffff for v in records}-own,asset_registry)
                    packages,binding,report=compile_art(p,identity,self.library,rig,reference,metadata,asset_key)
                    art.extend(packages);bindings.append(binding);art_reports.append(report)
                self.update(message='写入原生球员表、卡面索引及增能效果')
                coach_catalog=json.loads((self.resources/'coaches.json').read_text(encoding='utf8'))['coaches']
                selected_coach_ids={c['uuid'] for c in body.get('coaches',[])}
                old_coaches=[c for c in inherited.get('coaches',[]) if c['uuid'] in selected_coach_ids]
                coach_registry.setdefault('coaches',{}).update({c['uuid']:c['id'] for c in old_coaches})
                coach_registry.setdefault('boosters',{}).update(inherited.get('editor_registries',{}).get('coach_boosters',{}))
                coach_registry.setdefault('links',{}).update(inherited.get('editor_registries',{}).get('coach_links',{}))
                from native_coach_links import compile_links,schema as link_schema
                selected_coaches=copy.deepcopy(body.get('coaches',[]))
                link_resources,link_ids,new_link_routes=compile_links(Cpk(original),selected_coaches,coach_registry,link_schema(self.profile_resources))
                for coach in selected_coaches:coach['_compiled_link_ids']=link_ids[coach['uuid']]
                coach_resources,coaches=compile_coaches(Cpk(original),selected_coaches,coach_catalog,coach_registry,
                    {c['id'] for c in old_coaches},{b for c in old_coaches for b in c['payload'].get('ability_id',[])[:2] if b})
                coach_resources.update(link_resources)
                from coach_portraits import compile_portraits,owned_paths
                coach_art,coach_portrait_report=compile_portraits(body.get('coaches',[]),coaches,self.library)
                art.extend(coach_art)
                from card_presentation import repair_routes
                prior_card_routes=repair_routes(copy.deepcopy(inherited.get('native_binding',{}).get('routes',[])),inherited.get('players',[]),records)
                from card_motion import prepare as prepare_card_motion,replacement_indices as motion_replacements
                motion=prepare_card_motion(self.library,bindings,prior_card_routes,
                    records,body['export_settings']['card_motion']['enabled'],self.profile_resources)
                bindings=motion['bindings'];inherited_card_routes=motion['routes']
                card_motion_report=motion['reports'];art.extend(motion['packages'])
                cpk,table_report=compile_tables(original,projects,definitions,self.resources,bindings,coach_resources,replace_ids,replace_boosters)
                src=Container(self.library.containers/'pc3700_mobile_and_10_P.utoc',engine_key)
                out=work/'pc3700_mobile_and.utoc'
                from native_body import container_parts
                additions,paths,packages=container_parts(art)
                resource_build=append_container(src,out,additions,paths,packages,personal_source.owned_art_paths(src,selected_owners)|owned_paths(src,[c['id'] for c in old_coaches])|motion_replacements(src,motion['packages']))
                replacements={PREFIX+NATIVE+'dt870_mobile_and.cpk':cpk,
                              PREFIX+'livedata/dt870_mobile_and.cpk':cpk}
                for suffix in ('.utoc','.ucas'):replacements[PREFIX+NATIVE+'pc3700_mobile_and'+suffix]=out.with_suffix(suffix).read_bytes()
                # Original activation verifies all four files, including its empty PAK.
                resource_files={};original_resource_files={}
                for name in ('dt870_mobile_and.cpk','pc3700_mobile_and.pak','pc3700_mobile_and.utoc','pc3700_mobile_and.ucas'):
                    baseline=original if name=='dt870_mobile_and.cpk' else source.read(PREFIX+NATIVE+name)
                    original_resource_files[name]={'bytes':len(baseline),'sha256':hashlib.sha256(baseline).hexdigest()}
                    value=replacements.get(PREFIX+NATIVE+name)
                    if value is None:value=baseline
                    resource_files[name]={'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
                template_path=PREFIX+'work/templates/CMD_LOGIN_LIVEDATA.json'
                live_template=json.loads(source.read(template_path))
                live_registry_path=self.store.root/'native-live-versions.json'
                shared=self.library.home.parent/'.player-studio-shared/native-live-versions.json'
                seeds=[self.library.home.parent/name/'data/native-live-versions.json' for name in ('球员工坊','球员工坊-V14','球员工坊-V15')]
                live_version,live_registry=reserve_shared(shared,live_registry_path,release['release_id'],live_template,resource_files['dt870_mobile_and.cpk']['sha256'],seeds)
                live_template=compile_template(live_template,cpk,live_version)
                live_report=verify_template(live_template,cpk)
                replacements[template_path]=compact(live_template)
                binding_source=(Path(getattr(sys,'_MEIPASS',Path(__file__).absolute().parent))/'personal_binding.py').read_text(encoding='utf8')
                compiler_fingerprint=hashlib.sha256((self.runtime_source+'\0'+binding_source+'\0'+COMPILER_REVISION).encode('utf8')).hexdigest()
                document={'compiler_fingerprint':compiler_fingerprint,'game_version':self.library.profile.get('game_version','V14'),'adapter_family':self.library.profile.get('family','V14'),'draw_profiles':json.loads((self.resources/'native-draw-profiles.json').read_text(encoding='utf8')),'format':'personal-player-native-v1','version':1,'players':definitions,'packs':packs,'coaches':coaches,
                          'training_groups':catalog['training_groups'],'resource_files':resource_files,
                          'original_resource_files':inherited.get('original_resource_files',original_resource_files),'live_data':live_report,
                          'card_series_by_id':card_series(cpk),
                          'preview_boosters':{str(b['id']):{'effects':b['effects'],'conditional':bool(b.get('conditional'))} for b in catalog['boosters']}}
                document['players']=list(all_definitions.values())
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
                    with source.open('lib/arm64-v8a/libUE4.so') as render_engine:
                        document['render_preflight']=verify_display(render_engine,self.profile_resources)
                if document['frame_rate']['enabled']:
                    from native_fps import verify_fps160
                    with source.open('lib/arm64-v8a/libUE4.so') as fps_engine:
                        document['frame_rate']['preflight']=verify_fps160(apk,fps_engine,document['frame_rate']['target'])
                from pack_catalogue import REFERENCE
                if REFERENCE in source.namelist():
                    excluded=json.loads(source.read(REFERENCE))
                    replacements[REFERENCE]=compact({cid:row for cid,row in excluded.items() if row.get('type')!='China edition'})
                document['packs']=personal_source.merge(inherited.get('packs',[]),packs,'uuid')
                document['coaches']=personal_source.merge(inherited.get('coaches',[]),coaches,'uuid')
                document['preview_boosters']={**inherited.get('preview_boosters',{}),**document['preview_boosters']}
                for p in projects:
                    for b in p.get('custom_boosters',[]):document['preview_boosters'][str(b['id'])]={'effects':b['effects'],'conditional':bool(b.get('conditional'))}
                document['pack_covers']={**inherited.get('pack_covers',{}),**cover_routes}
                document['editor_registries']={'boosters':booster_registry,'coach_boosters':coach_registry.get('boosters',{}),'coach_links':coach_registry.get('links',{})}
                document['coach_links']=list({r['id']:r for r in [*inherited.get('coach_links',[]),*new_link_routes]}.values())
                for relative,content in cover_files.items():replacements[PREFIX+relative]=content
                if identities or inherited.get('native_binding') or document['coach_links'] or export_settings['controller']['enabled'] or export_settings['card_motion']['enabled']:
                    profile=json.loads((self.resources/'native-route-templates.json').read_text(encoding='utf8'))
                    profile['club_emblems']=True
                    profile['external_routes']=True
                    profile['position_hook']=json.loads((self.resources/'native-position-hook.json').read_text(encoding='utf8'))
                    profile['acquisition_hook']=json.loads((self.resources/'native-acquisition-hook.json').read_text(encoding='utf8'))
                    profile['overall_hook']=json.loads((self.resources/'native-overall-hook.json').read_text(encoding='utf8'))
                    mini_profile=self.resources/'native-thumbnail-hook.json'
                    if not mini_profile.is_file():mini_profile=self.profile_resources/'native-thumbnail-hook.json'
                    profile['thumbnail_hook']=json.loads(mini_profile.read_text(encoding='utf8'))
                    # Imported databases may carry an older copy of this
                    # interface. Upgrade only an identical native entry point.
                    current_mini=json.loads((self.profile_resources/'native-thumbnail-hook.json').read_text(encoding='utf8'))
                    if current_mini.get('front_date_offset') is not None:
                        if any(profile['thumbnail_hook'].get(k)!=current_mini.get(k) for k in ('address','original_call','assign','mini_offset','expected_hex')):raise ValueError('此版本的大卡日期接口不同，未套用其他版本的图层位置')
                        for k in ('front_date_offset','front_date_evidence'):profile['thumbnail_hook'][k]=current_mini[k]
                    profile['thumbnail_hook']['stock_routes']=motion['stock_routes']
                    from native_extensions import link_hooks
                    with source.open('lib/arm64-v8a/libUE4.so') as engine:
                        profile['native_hooks']=link_hooks(document['coach_links'],engine,link_schema(self.profile_resources))
                        from game_settings import controller_hooks
                        profile['native_hooks']+=controller_hooks(export_settings['controller'],engine,self.profile_resources)
                        from native_skill_effects import hooks as skill_hooks,required as skill_effects_required
                        if skill_effects_required(document['players'],catalog):profile['native_hooks']+=skill_hooks(engine,self.profile_resources)
                        if document['game_version']=='V17':
                            from native_skill_capacity import hooks as capacity_hooks,REVISION as SKILL_CAPACITY_REVISION
                            profile['native_hooks']+=capacity_hooks(engine)
                            document['skill_capacity']={'innate':20,'additional':10,'display':'native-lists',
                                                        'revision':SKILL_CAPACITY_REVISION}
                    with source.open('lib/arm64-v8a/libUE4.so') as engine:
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
                        profile['text_hooks']=json.loads((self.resources/'native-text-hooks.json').read_text(encoding='utf8'))
                        with source.open('lib/arm64-v8a/libUE4.so') as engine:
                            for kind in ('name','description'):
                                hook=profile['text_hooks'][kind];engine.seek(hook['file_offset'])
                                if engine.read(64).hex()!=hook['expected_hex']:raise ValueError('此版本的增能文字接口不同')
                    from native_binding_source import read_installer
                    original_binding,installer_code=read_installer(apk)
                    routes=[r for r in inherited_card_routes if int(r['cardId']) not in replace_ids]
                    for identity,binding,definition in zip(identities,bindings,definitions):
                        for cid in sorted({identity['card_id'],*owned_person_aliases(identity),int(binding['asset_key']),*identity['previous_card_ids']}):
                            routes.append({'cardId':cid,'suiteDonorId':identity['card_id'],
                                           'portraitKey':binding['asset_key'],'modelFaceKey':binding['asset_key'],
                                           'thumbnail_names':binding['thumbnail_names'],
                                           'club_id':definition['owned']['initial_base_team_id'],
                                           'position':definition['base_parameters'][0],
                                           'maximum_overall':definition['maximum_development']['overall'],
                                           'presentation_rarity':10 if definition['card_type'] in ('BigTime','Epic','Legendary') else 0})
                    from card_presentation import repair_routes
                    routes=repair_routes(routes,document['players'],records)
                    compose(original_binding,routes,profile)
                    document['native_binding']={'routes':routes,'profile':profile,'original_fingerprint':fingerprint(original_binding)}
                    from native_binding_source import installer_metadata
                    if installer_metadata(installer_code):document['native_binding']['source']=installer_metadata(installer_code)
                    # Run the same closure/fingerprint verification performed
                    # on Android before signing, so a startup mismatch cannot
                    # leave the desktop compiler as a successful APK.
                    from native_binding_source import verify_installer
                    document['native_binding_preflight']=verify_installer(installer_code,document['native_binding'])
                document['revision']=hashlib.sha256(compact(document)).hexdigest()
                replacements[PREFIX+'custom-resources/personal-player-studio/players.json']=compact(document)
                replacements['assets/chaquopy/app.imy']=hook_archive(source.read('assets/chaquopy/app.imy'),self.runtime_source,
                    binding_source)
                build=json.loads(source.read('assets/chaquopy/build.json'))
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
                    rel=name[len(PREFIX):];row={'path':rel,'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
                    if rel in listed:listed[rel].update(row)
                    else:release['files'].append(row)
                replacements[PREFIX+'release-manifest.json']=compact(release)
                replacements.update(install_replacements)
            self.update(message='整理有效资源、回收旧导出数据并签名')
            unsigned=work/'unsigned.apk';apk_build=replace_entries(apk,unsigned,replacements)
            output=self.store.root/'exports'/('73efootball-'+self.library.profile.get('game_version','V14')+('-工坊共存-' if body.get('installation_mode')=='coexist' else '-个人球员-')+time.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:4]+'.apk')
            key,cert=local_signer(self.store.root/'signing')
            sign_v2(unsigned,output,key,cert)
            verified=verify_v2(output)
            with zipfile.ZipFile(output) as check:
                for name,value in replacements.items():
                    if check.read(name)!=value:raise ValueError('生成的 APK 文件校验失败：'+name)
            temp=registry_path.with_suffix('.tmp');temp.write_bytes(compact(registry));temp.replace(registry_path)
            temp=booster_path.with_suffix('.tmp');temp.write_bytes(compact(booster_registry));temp.replace(booster_path)
            temp=live_registry_path.with_suffix('.tmp');temp.write_bytes(compact(live_registry));temp.replace(live_registry_path)
            temp=asset_path.with_suffix('.tmp');temp.write_bytes(compact(asset_registry));temp.replace(asset_path)
            temp=coach_path.with_suffix('.tmp');temp.write_bytes(compact(coach_registry));temp.replace(coach_path)
            report={'identities':identities,'native_art':art_reports,'packs':[{'uuid':p['uuid'],'agent_id':p['agent_id'],'name':p['name'],'members':len(p['members']),'skipped_members':p.get('skipped_members',[])} for p in packs],
                    'native_tables':table_report,'signature':verified,'live_data':live_report,
                    'apk_compaction':apk_build['compaction'],'resource_compaction':resource_build.compaction_report,
                    'native_binding_routes':len(document.get('native_binding',{}).get('routes',[])),'frame_rate':document['frame_rate'],'game_settings':export_settings,'render_preflight':document.get('render_preflight'),'card_motion_preflight':card_motion_report,'installation':installation,
                    'coaches':[{'uuid':c['uuid'],'id':c['id'],'name':c['payload']['name']} for c in coaches],'coach_portraits':coach_portrait_report,
                    'source_apk':str(apk),'output':str(output),'engine_profile':release['base_release_id'],'resource_release':release['release_id'],
                    'in_game_tested':False,'progress_policy':'first grant only; existing instance retains live XP, training and statistics'}
            report_path=output.with_suffix('.report.json');report_path.write_bytes(compact(report))
            self.update(phase='done',message='APK 已生成并通过签名与资源读回校验；待游戏内验收',
                        result={'path':str(output),'url':'/exports/'+output.name,'size':output.stat().st_size,
                                'report':report,'report_path':str(report_path)})
        except Exception as exc:
            import logging
            logging.exception('Native APK compilation failed')
            self.update(phase='error',message=str(exc))
        finally:self.cleanup_work(work,'native-')

    def _booster_labels(self):
        path=self.resources/'catalog.json'
        return json.loads(path.read_text(encoding='utf8'))['ABILITIES'] if path.is_file() else {}
