"""Read compatible APK data into a new catalogue without executing APK code."""
from pathlib import Path
import collections,contextlib,copy,csv,gzip,hashlib,io,json,os,re,shutil,sqlite3,struct,subprocess,threading,uuid,zipfile
from native_cpk import Cpk,unwrap
from native_tables import PLAYER,APPEARANCE,VARIATION,ALIASES
from card_types import editor_card_type

PREFIX='assets/gateway-release/'
IMPORT_REVISION='apk-catalogue-compatible-v7'

def active_resources(base,store):
    path=Path(store)/'active-game.json'
    if not path.is_file():return Path(base)
    selected=json.loads(path.read_text(encoding='utf8'));key=selected.get('database')
    if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{24}',key):raise ValueError('当前游戏数据库记录无效，原文件已保留')
    target=Path(store)/'game-databases'/key
    if not (target/'import-report.json').is_file():raise ValueError('当前游戏数据库缺少导入校验记录')
    return target

def read_tables(archive):
    sources=[]
    for path in (PREFIX+'livedata/dt870_mobile_and.cpk',PREFIX+'custom-resources/legends-v10/dt870_mobile_and.cpk'):
        if path in archive.namelist():sources.append(Cpk(archive.read(path)))
    if not sources:raise ValueError('APK 不含当前支持的离线球员数据库')
    result={}
    for name,size in ((PLAYER,400),(APPEARANCE,64),(VARIATION,168)):
        merged={}
        for source in sources:
            if name not in source.files:continue
            data=unwrap(source.read(name))
            if not data or len(data)%size:raise ValueError('新版数据表布局不兼容：'+name)
            offset=8 if name==PLAYER else 0
            for at in range(0,len(data),size):
                row=data[at:at+size];key=int.from_bytes(row[offset:offset+8],'little');merged[key]=row
        if not merged:raise ValueError('新版 APK 缺少必要数据表：'+name)
        result[name]=merged
    for source in reversed(sources):
        if ALIASES in source.files:result[ALIASES]=unwrap(source.read(ALIASES));break
    return result

def build_catalogue(apk,resources):
    """Use declared bit fields plus the APK's own complete card payloads."""
    resources=Path(resources);catalog=json.loads((resources/'catalog.json').read_text(encoding='utf8'))
    fields=json.loads((resources/'native-player-fields.json').read_text(encoding='utf8'));ability=json.loads((resources/'native-ability-bits.json').read_text(encoding='utf8'));skills=json.loads((resources/'native-skill-bits.json').read_text(encoding='utf8'))
    with zipfile.ZipFile(apk) as z:
        from pack_catalogue import catalogue_from_archive
        (resources/'pack-exclusions.json').write_text(json.dumps(catalogue_from_archive(z),ensure_ascii=False),encoding='utf8')
        tables=read_tables(z);names={};classes={};verified={}
        name_path=PREFIX+'outputs/reference/player_editor_names.json.gz'
        if name_path in z.namelist():names=json.loads(gzip.decompress(z.read(name_path)))
        class_path=PREFIX+'outputs/reference/card-class-table.csv'
        if class_path in z.namelist():classes={r['player_id']:r['card_class'] for r in csv.DictReader(io.StringIO(z.read(class_path).decode('utf8')))}
        verify_path=PREFIX+'outputs/reference/verified-card-update.json.gz'
        if verify_path in z.namelist():
            for row in json.loads(gzip.decompress(z.read(verify_path))).get('cards',[]):
                p=row.get('payload') or {};cid=str((p.get('gameplayer_id') or {}).get('id',''))
                if row.get('level_limit_verified'):verified[cid]=p
        seed=sqlite3.connect(':memory:')
        try:
            seed.deserialize(z.read(PREFIX+'outputs/efootball/local-club.sqlite3'))
            if seed.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('APK 自带数据库校验失败')
            managed={str(cid):(json.loads(raw),kind) for cid,raw,kind in seed.execute('select card_id,payload,card_type from managed_cards')}
        finally:seed.close()
        labels={str(cid):b[12:140].split(b'\0')[0].decode('utf8','strict') for cid,b in tables[VARIATION].items()}
        records=[]
        for ident,b in sorted(tables[PLAYER].items()):
            pid=str(ident);bits=int.from_bytes(b,'little')
            def get(key):f=fields[key];return (bits>>f['bit'])&((1<<f['width'])-1)
            strings=[b[88+i*61:149+i*61].split(b'\0')[0].decode('utf8','strict').strip() for i in range(5)]
            en=next((s for s in strings[::-1] if s),pid);name,english=(names.get(pid) or [en,en])[:2]
            params=[0]*147;params[0]=get('position')
            if params[0]>=len(catalog['POSITIONS']):raise ValueError('新版球员位置编号不兼容：'+pid)
            for i,m in ability.items():params[int(i)]=((bits>>m['bit'])&63)+40
            for i,pos in enumerate(catalog['APTITUDES'],1):params[i]=get('aptitude.'+pos)
            for i,key in ((33,'weak_foot_accuracy'),(41,'form'),(42,'injury_resistance'),(43,'foot'),(45,'weak_foot_usage')):params[i]=get(key)
            params[46:49]=[get('age')+10,get('height_cm')+100,get('weight_kg')+30]
            if not 140<=params[47]<=220:params[47]=0
            selected=[]
            for i,m in skills.items():
                if (bits>>m['bit'])&1:selected.append(int(i));params[int(catalog['PARAMETER_BY_SKILL'][i])]=1
            attack,defense=get('style.in_possession'),get('style.out_of_possession');params[61:63]=[attack,defense]
            p={'gameplayer_id':{'id':ident,'serial':0},'parameters':params,'level_info':{'level':1,'level_limit':None},'play_style':[attack,defense],
               'initial_base_team_id':get('club'),'_nation_id':get('nationality'),'_studio_unknown_level_limit':True,'_studio_partial_skill_mapping':True,'_studio_skill_ids':selected}
            kind=classes.get(pid,'UNKNOWN');source='导入 APK · Player.bin/400'
            if pid in managed:
                complete,kind=managed[pid]
                if len(complete.get('parameters',[]))!=147:raise ValueError('新版完整球员参数布局改变')
                p.update(copy.deepcopy(complete));source+=' + 原包完整卡池'
                p.pop('_studio_unknown_level_limit',None);p.pop('_studio_partial_skill_mapping',None)
            elif pid in verified:
                complete=verified[pid];limit=complete.get('level_info',{}).get('level_limit')
                if len(complete.get('parameters',[]))==147 and type(limit) is int and 1<=limit<=100:
                    p.update(copy.deepcopy(complete));p.pop('_studio_unknown_level_limit',None);p.pop('_studio_partial_skill_mapping',None);source+=' + 原包已校验资料'
            p.update(_studio_client_record=b.hex(),_studio_names=strings,_studio_card_label=labels.get(pid,''),_studio_native_card_class=kind)
            from native_celebration import restore_payload
            restore_payload(p)
            from ai_playing_styles import restore_payload as restore_ai_styles
            restore_ai_styles(p)
            kind=editor_card_type(kind,labels.get(pid,''));position=p['parameters'][0]
            if type(position) is not int or not 0<=position<len(catalog['POSITIONS']):raise ValueError('完整卡池位置格式改变')
            level=p.get('level_info',{}).get('level_limit')
            if level is not None and (type(level) is not int or not 1<=level<=100):raise ValueError('新版等级上限超出当前布局')
            records.append((pid,name or en,english or en,' '.join([pid,name or en,english or en,*strings]).casefold(),catalog['POSITIONS'][position],kind,p.get('_overall'),level,str(ident&0xfffffff),json.dumps(p,ensure_ascii=False,separators=(',',':')),source))
        path=resources/'library.sqlite3';db=sqlite3.connect(path)
        try:
            with db:
                db.execute('delete from players');db.executemany('insert into players values(?,?,?,?,?,?,?,?,?,?,?)',records)
                db.execute('delete from card_aliases')
                if ALIASES in tables:db.executemany('insert or replace into card_aliases values(:before,:after)',csv.DictReader(io.StringIO(tables[ALIASES].decode('utf8'))))
                # Team names are version-local, while the stable IDs in saved
                # projects are deliberately not rewritten.
                live=Cpk(z.read(PREFIX+'livedata/dt870_mobile_and.cpk'))
                if 'common/etc/pesdb/Team.bin' in live.files:
                    teams=unwrap(live.read('common/etc/pesdb/Team.bin'))
                    if len(teams)%1600:raise ValueError('球队表布局改变')
                    db.execute('delete from identities where kind="team"')
                    for at in range(0,len(teams),1600):
                        row=teams[at:at+1600];tid=int.from_bytes(row[12:16],'little')&131071;en=row[396:466].split(b'\0')[0].decode('utf8');zh=row[1036:1106].split(b'\0')[0].decode('utf8')
                        if en or zh:db.execute('insert or replace into identities values(?,?,?,?)',('team',tid,zh or en,en))
                summary=json.loads(db.execute('select value from meta where key="summary"').fetchone()[0]);summary.update(players=len(records),client_player_records=len(records),source=Path(apk).name,by_card_type=dict(collections.Counter(row[5] for row in records)))
                db.execute('update meta set value=? where key="summary"',(json.dumps(summary,ensure_ascii=False),))
            if db.execute('pragma quick_check').fetchone()[0]!='ok':raise ValueError('生成后的数据库校验失败')
        finally:db.close()
        from native_appearance import compact_table
        (resources/'native-appearance.bin').write_bytes(compact_table(tables[APPEARANCE]))
        coaches=read_coaches(z,resources)
        from native_equipment import write_catalogue
        equipment=write_catalogue(Cpk(z.read(PREFIX+'custom-resources/legends-v10/dt870_mobile_and.cpk')),resources)
        from apk_literals import update_options
        options=update_options(apk,catalog)
        (resources/'native-progression.json').write_text(json.dumps({'version':1,'source':'导入 APK · pes_tables.EXPERIENCE_LIST','costs':options['costs']}),encoding='utf8')
        catalog['release_id']=json.loads(z.read(PREFIX+'release-manifest.json'))['release_id'];(resources/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
        return {'players':len(records),'managed_cards':len(managed),'coaches':coaches,'boosters':options['boosters'],'skills':options['skills'],'verified_level_cards':sum(row[7] is not None for row in records),'tables':{k:len(v) for k,v in tables.items() if isinstance(v,dict)}}

def read_coaches(archive,resources):
    from native_coaches import COACH,BOOSTER,TACTICS,ATTRIBUTES
    sources=[Cpk(archive.read(n)) for n in (PREFIX+'livedata/dt870_mobile_and.cpk',PREFIX+'custom-resources/legends-v10/dt870_mobile_and.cpk') if n in archive.namelist()]
    raw=bonus=None
    for source in sources:
        if COACH in source.files:raw=unwrap(source.read(COACH))
        if BOOSTER in source.files:bonus=unwrap(source.read(BOOSTER))
    previous=json.loads((resources/'coaches.json').read_text(encoding='utf8'));old={str(c['id']):c for c in previous['coaches']}
    if raw is None:return len(old)
    if len(raw)%176 or bonus is None or len(bonus)%4:raise ValueError('新版教练数据库布局改变')
    boosts={};attribute={v:k for k,v in ATTRIBUTES.items()};attribute.update({2:'34',6:'17'})
    for at in range(0,len(bonus),4):
        value=int.from_bytes(bonus[at:at+4],'little');boosts[value&1023]=((value>>15)&31,(value>>10)&31)
    coaches=[]
    for at in range(0,len(raw),176):
        row=raw[at:at+176];value=int.from_bytes(row,'little');cid=str(value&((1<<64)-1))
        local=row[32:78].split(b'\0')[0].decode('utf8','strict');english=row[78:124].split(b'\0')[0].decode('utf8','strict')
        if not cid or not (local or english):continue
        prior=copy.deepcopy(old.get(cid) or next(iter(old.values())));prior.update(id=cid,type='native',name=english or local,name_en=english or local,name_local=local,age=((value>>231)&63)+15)
        if cid not in old:prior['pack_title']=''
        prior['raw_payload_verified']=cid in old
        prior['tactics']={name:(value>>bit)&127 for name,bit in TACTICS.items()}
        ids=[(value>>bit)&511 for bit in (160,148,128,137)];effects={};unmapped=[]
        for bid in ids:
            if not bid:continue
            attr,amount=boosts.get(bid,(None,0))
            if attr in attribute:effects[attribute[attr]]=effects.get(attribute[attr],0)+amount
            else:unmapped.append(bid)
        prior.update(effects=effects,unmapped_abilities=unmapped,ability_ids=ids,source='导入 APK · 原生教练表')
        prior['raw_payload'].update(coach_id={'id':int(cid),'serial':0},name=prior['name'],name_en=prior['name_en'],age=prior['age'],ability_id=ids,**prior['tactics'])
        coaches.append(prior)
    if not coaches:raise ValueError('新版教练目录为空，未启用数据库')
    previous['coaches']=coaches;(resources/'coaches.json').write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf8');return len(coaches)

def index_assets(library):
    key=(library.containers/'resource-key.bin').read_bytes().hex();env=os.environ.copy();env['TEMP']=str(library.native);env['TMP']=str(library.native)
    command=[str(library.tool),'-i',str(library.containers),'-g','GAME_eFootball','-k','0x'+key,'-p','*','-l']
    completed=subprocess.run(command,capture_output=True,env=env,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (library.root/'last-index.log').write_bytes(completed.stderr)
    if completed.returncode:raise ValueError('新版资源索引读取失败')
    listed={p.strip() for p in completed.stdout.decode('utf8','replace').splitlines()};paths=sorted(p for p in listed if p.endswith('.uasset'));rows=[]
    for asset in paths:
        name=asset.rsplit('/',1)[-1][:-7]
        if '/Thumbnail/Player/' in asset or ('/RealFace/' in asset and re.fullmatch(r'\d+(?:_|f)',name)):
            kind='portrait' if re.fullmatch(r'\d+_(?:l)?',name) else 'card';match=re.match(r'(\d+)',name) if kind=='portrait' or re.fullmatch(r'\d+f',name) else re.search(r'(\d{6,})',name)
        elif '/character/' in asset.casefold() and name.startswith('SK_'):kind='model';match=re.match(r'SK_(\d+)',name)
        else:continue
        rows.append((hashlib.sha256(asset.encode()).hexdigest()[:24],asset,name,kind,match.group(1) if match else ''))
    if len(rows)<1000:raise ValueError('新版美术索引数量异常，未替换旧数据库')
    with contextlib.closing(sqlite3.connect(library.resources/'library.sqlite3')) as db,db:
        db.execute('delete from assets');db.executemany('insert into assets values(?,?,?,?,?)',rows)
        summary=json.loads(db.execute('select value from meta where key="summary"').fetchone()[0]);summary.update(assets=len(rows),by_asset_kind=dict(collections.Counter(row[3] for row in rows)))
        db.execute('update meta set value=? where key="summary"',(json.dumps(summary,ensure_ascii=False),))
    media=json.loads((library.resources/'native-card-media.json').read_text(encoding='utf8'))
    media['movies']=sorted({p for p in listed if p.lower().endswith(('.usm','.webm','.mp4','.m2v')) and '/playercard/' in p.lower()})
    (library.resources/'native-card-media.json').write_text(json.dumps(media,ensure_ascii=False),encoding='utf8')
    return len(rows)

class GameImport:
    def __init__(self,server,base):self.server=server;self.base=Path(base);self.state={'phase':'idle'};self.lock=threading.Lock()
    def status(self):
        with self.lock:return copy.deepcopy(self.state)
    def update(self,**kw):
        with self.lock:self.state.update(kw)
    def install_adapter(self,path):
        source=Path(path)
        if not source.is_file() or source.suffix.lower()!='.json' or source.stat().st_size>65536:raise ValueError('请选择不超过 64 KB 的兼容适配 JSON')
        document=json.loads(source.read_text(encoding='utf8'))
        if document.get('format')!='player-studio-game-adapters-v1' or not isinstance(document.get('engines'),dict) or not 1<=len(document['engines'])<=128:raise ValueError('适配资料格式无效')
        base=json.loads((self.base/'game-adapters.json').read_text(encoding='utf8'));family=json.loads((self.base/'native-resource-profile.json').read_text(encoding='utf8')).get('adapter_family','V14')
        for digest,item in document['engines'].items():
            if not re.fullmatch('[a-f0-9]{64}',digest) or not isinstance(item,dict) or set(item)-{'family','game_version','validation','resource_key_offset','resource_key_sha256'}:raise ValueError('适配引擎资料字段无效')
            if item.get('family')!=family or not re.fullmatch('V[0-9]{1,3}',str(item.get('game_version',''))):raise ValueError('适配资料与当前原生系列不兼容')
            if digest in base['engines'] and item!=base['engines'][digest]:raise ValueError('不能覆盖随软件已核对的引擎适配资料')
            if 'resource_key_offset' in item and (type(item['resource_key_offset']) is not int or not 0<=item['resource_key_offset']<1<<31):raise ValueError('资源密钥位置无效')
            if 'resource_key_sha256' in item and not re.fullmatch('[a-f0-9]{64}',str(item['resource_key_sha256'])):raise ValueError('资源密钥校验值无效')
        folder=self.server.store.root/'compatibility';folder.mkdir(exist_ok=True);target=folder/'game-adapters.json'
        prior=json.loads(target.read_text(encoding='utf8')) if target.is_file() else {'format':'player-studio-game-adapters-v1','engines':{}}
        prior['engines'].update(document['engines']);temp=target.with_suffix('.tmp');temp.write_text(json.dumps(prior,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,target)
        return {'installed':len(document['engines']),'message':'已安装适配资料；仍会检查数据库、骨架和写入接口。'}
    def start(self,body):
        if self.status()['phase']=='working':raise ValueError('正在导入游戏数据，请稍候')
        if self.server.native_package.status()['phase']=='working' or self.server.library.state['phase']=='preparing':raise ValueError('请等待当前实装或资源准备结束')
        apk=Path(body.get('apk','')).absolute();companion=Path(body.get('companion','')).absolute()
        if not apk.is_file() or apk.suffix.lower()!='.apk' or not companion.is_file():raise ValueError('请选择新版主 APK 和已有离线资源 APK')
        with self.lock:
            if self.state['phase']=='working':raise ValueError('正在导入游戏数据，请稍候')
            self.state={'phase':'working','message':'核对新版 APK 与兼容性','result':None}
        threading.Thread(target=self._work,args=(apk,companion),daemon=True).start();return self.status()
    def _work(self,apk,companion):
        from native_library import NativeLibrary
        staging=None;previous_resources=self.server.library.resources
        try:
            with zipfile.ZipFile(apk) as archive:
                manifest=json.loads(archive.read(PREFIX+'release-manifest.json'));release=manifest['release_id']
                from personal_source import read as read_personal
                personal=read_personal(archive,manifest)
                with archive.open('lib/arm64-v8a/libUE4.so') as f:engine=hashlib.file_digest(f,'sha256').hexdigest()
            adapters=json.loads((self.base/'game-adapters.json').read_text(encoding='utf8'))['engines'];adapter=adapters.get(engine)
            external=self.server.store.root/'compatibility/game-adapters.json'
            if not adapter and external.is_file():adapter=json.loads(external.read_text(encoding='utf8')).get('engines',{}).get(engine)
            from engine_compatibility import detect
            self.update(message='自动核对原生接口；引擎指纹变化不影响兼容版本导入')
            adapter=detect(apk,self.base,release,adapter)
            base_profile=json.loads((self.base/'native-resource-profile.json').read_text(encoding='utf8'))
            if adapter['family']!=base_profile.get('adapter_family','V14'):raise ValueError('此 APK 属于另一原生适配系列，请用对应的软件版本导入')
            self.update(message='计算主包校验值，避免同版本文件被误复用')
            with apk.open('rb') as source:apk_hash=hashlib.file_digest(source,'sha256').hexdigest()
            key=hashlib.sha256((release+engine+apk_hash+IMPORT_REVISION).encode()).hexdigest()[:24];root=self.server.store.root/'game-databases';root.mkdir(exist_ok=True);destination=root/key
            if destination.exists():
                if not (destination/'import-report.json').is_file():raise ValueError('存在未完成的同版本导入，请保留日志后重试')
            else:
                staging=root/('stage-'+uuid.uuid4().hex);shutil.copytree(self.base,staging)
                namespace=adapter['game_version']+'-'+key[:8]
                previous_report=previous_resources/'import-report.json'
                if previous_report.is_file():
                    prior=json.loads(previous_report.read_text(encoding='utf8'))
                    if prior.get('apk_sha256')==apk_hash and prior.get('engine_sha256')==engine:
                        namespace=json.loads((previous_resources/'native-resource-profile.json').read_text(encoding='utf8'))['cache_namespace']
                profile={**base_profile,**adapter,'release_id':release,'native_engine_sha256':engine,'cache_namespace':namespace}
                (staging/'native-resource-profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf8')
                self.update(message='重建新版球员、等级、国家与球队数据库')
                counts=build_catalogue(apk,staging);library=NativeLibrary(staging,self.server.library.home,self.server.store)
                if library.state['phase']!='ready':library.state={'phase':'preparing','message':'准备新版美术资源','files':0,'bytes':0};library._setup(apk,companion)
                if library.state['phase']!='ready':raise ValueError(library.state.get('message') or '新版美术资源准备失败')
                self.update(message='读取新版卡面、脸模与小头像索引')
                counts['assets']=index_assets(library)
                report={'format':'player-studio-apk-database-v1','import_revision':IMPORT_REVISION,'apk':str(apk),'apk_sha256':apk_hash,'companion':str(companion),'release_id':release,'engine_sha256':engine,'counts':counts,'personal_data_preserved':True,'in_game_tested':False}
                (staging/'import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');staging.rename(destination);staging=None
            self.server.use_resources(destination)
            pointer=self.server.store.root/'active-game.json';temp=pointer.with_suffix('.tmp');temp.write_text(json.dumps({'database':key,'apk':str(apk),'companion':str(companion)},ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,pointer)
            from library_cleanup import cleanup_old_libraries
            try:cleanup=cleanup_old_libraries(self.server.store,self.server.library.home,destination)
            except (OSError,ValueError) as exc:cleanup={'warnings':[str(exc)]}
            result=json.loads((destination/'import-report.json').read_text(encoding='utf8'));result['old_library_cleanup']=cleanup
            self.update(phase='done',message='新版数据库已启用，旧库已清理，自建工程与签名已保留' if not cleanup.get('warnings') else '新版数据库已启用，部分旧缓存待清理；自建工程与签名已保留',result=result)
        except Exception as exc:
            if self.server.library.resources!=previous_resources:self.server.use_resources(previous_resources)
            if staging and staging.is_dir():
                parent=self.server.store.root/'game-databases'
                if staging.resolve().parent==parent.resolve() and staging.name.startswith('stage-') and not staging.is_symlink() and not staging.is_junction():
                    try:shutil.rmtree(staging);staging=None
                    except OSError:pass
            self.update(phase='error',message=str(exc),staging=str(staging) if staging else None)
