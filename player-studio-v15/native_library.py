"""Local player catalogue and conversion of existing game artwork only."""
from pathlib import Path
import contextlib
from collections import OrderedDict
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import uuid
import zipfile
from native_movie import convert_movie
from native_models import resolve_face,person_keys
from native_skeletal import FACE_DECODER_REVISION
from native_presets import NativePresets


def glb_textures(path, materials, output):
    data=path.read_bytes();chunks=[];offset=12
    while offset<len(data):
        length,kind=struct.unpack_from('<II',data,offset);chunks.append((kind,data[offset+8:offset+8+length]));offset+=8+length
    doc=json.loads(next(b for k,b in chunks if k==0x4E4F534A));binary=bytearray(next((b for k,b in chunks if k==0x004E4942),b''));bound=0
    for material in doc.get('materials',[]):
        item=materials.get(material.get('name'))
        if not item:continue
        png,properties=item
        while len(binary)%4:binary.append(0)
        view=len(doc.setdefault('bufferViews',[]));doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':len(png)})
        binary.extend(png);image=len(doc.setdefault('images',[]));doc['images'].append({'bufferView':view,'mimeType':'image/png'})
        texture=len(doc.setdefault('textures',[]));doc['textures'].append({'source':image})
        pbr=material.setdefault('pbrMetallicRoughness',{});pbr['baseColorTexture']={'index':texture};pbr['metallicFactor']=0
        if any(k in material.get('name','').lower() for k in ('hair','eyelash')):
            material['alphaMode']='MASK';material['alphaCutoff']=properties.get('BasePropertyOverrides',{}).get('OpacityMaskClipValue',.3333);material['doubleSided']=True
        bound+=1
    doc.setdefault('buffers',[{}])[0]['byteLength']=len(binary)
    raw=json.dumps(doc,separators=(',',':')).encode();raw+=b' '*((-len(raw))%4);binary+=b'\0'*((-len(binary))%4)
    payload=struct.pack('<II',len(raw),0x4E4F534A)+raw+struct.pack('<II',len(binary),0x004E4942)+binary
    output.write_bytes(struct.pack('<4sII',b'glTF',2,len(payload)+12)+payload)
    return {'materials':len(doc.get('materials',[])),'textured_materials':bound}


class NativeLibrary:
    def __init__(self, resources, home, store):
        self.resources=Path(resources);self.home=Path(home);self.store=store
        self.profile=json.loads((self.resources/'native-resource-profile.json').read_text(encoding='utf8'))
        namespace=self.profile.get('cache_namespace')
        if namespace is not None and (not isinstance(namespace,str) or not namespace or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in namespace)):raise ValueError('资源缓存版本标识无效')
        self.root=self.home/'library'/'versions'/namespace if namespace else self.home/'library'
        self.containers=self.root/'containers';self.converted=self.root/'converted'
        self.tool=self.home/'tools/asset-decoder/cue4parse.exe';self.native=self.tool.parent/'native'
        self.ffmpeg=self.home/'tools/video/ffmpeg.exe'
        self.card_media=json.loads((self.resources/'native-card-media.json').read_text(encoding='utf8'))
        self.card_widgets=json.loads((self.resources/'native-card-widgets.json').read_text(encoding='utf8'))
        self.presets=NativePresets(self)
        self.convert_lock=threading.Lock();self.setup_lock=threading.Lock()
        self.thumbnail_lock=threading.Lock();self.thumbnail_frames=OrderedDict()
        self._face_assets=None
        try:ready=json.loads((self.root/'ready.json').read_text(encoding='utf8')).get('release_id')==self.profile['release_id'] and self.containers.is_dir()
        except (OSError,ValueError):ready=False
        self.state={'phase':'ready' if ready else 'missing','message':''}
        self.cache_path=store.root/('native-cache-'+namespace+'.json' if namespace else 'native-cache.json')
        try:self.cache=json.loads(self.cache_path.read_text(encoding='utf8'))
        except (OSError,ValueError):self.cache={}

    def db(self):
        c=sqlite3.connect('file:'+str(self.resources/'library.sqlite3').replace('\\','/')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c

    def thumbnail_video_frame(self,path,seconds):
        from thumbnail_background import desktop_frame
        return desktop_frame(self,path,seconds)

    def thumbnail_movie(self,path):
        if path not in self.card_media['movies']:raise ValueError('小头像动画不在当前资源库中')
        with self.convert_lock:
            source=self.converted/path
            if not source.is_file():self.run([path],'raw')
            movie=source.with_suffix('.webm');meta=convert_movie(source,movie,self.ffmpeg)
            asset=self.store.import_asset(movie,'video')
            return {'asset_id':asset['id'],'url':asset['url'],'kind':'video',**meta}

    def summary(self):
        with contextlib.closing(self.db()) as c:s=json.loads(c.execute("SELECT value FROM meta WHERE key='summary'").fetchone()[0])
        return {**s,**self.state,'tools_ready':self.tool.is_file(),'cache_directory':str(self.root),'game_version':self.profile.get('game_version','V14')}

    def search(self, body):
        q=str(body.get('query','')).strip().casefold()[:120];kind=body.get('kind','');page=max(0,int(body.get('page',0)));limit=24
        where=[];values=[]
        if q:
            where.append('search LIKE ?');values.append('%'+q.replace('%','').replace('_','')+'%')
        if body.get('position'):
            where.append('position=?');values.append(body['position'])
        if kind:where.append('card_type=?');values.append(kind)
        if body.get('for_pack'):
            from pack_catalogue import exclusions
            blocked=exclusions(self.resources)
            if blocked:
                where.append('id NOT IN ('+','.join('?' for _ in blocked)+')');values.extend(blocked)
        clause=' WHERE '+' AND '.join(where) if where else ''
        with contextlib.closing(self.db()) as c:
            count=c.execute('SELECT count(*) FROM players'+clause,values).fetchone()[0]
            rows=[dict(r) for r in c.execute('SELECT id,name,name_en,position,card_type,overall,level_limit,base_id,source FROM players'+clause+' ORDER BY CASE WHEN card_type="BigTime" THEN 0 WHEN card_type="Epic" THEN 1 WHEN card_type="Legendary" THEN 2 ELSE 3 END, CAST(id AS INTEGER) DESC LIMIT ? OFFSET ?',values+[limit,page*limit])]
            for row in rows:
                row['portrait']=self._portrait(c,row['id'],row['base_id'])
        return {'rows':rows,'total':count,'page':page,'pages':max(1,(count+limit-1)//limit)}

    def _portrait(self,c,pid,base):
        for candidate in (pid+'_l',pid+'_',base+'_l',base+'_'):
            candidate=self._alias(c,candidate)
            r=c.execute('SELECT id FROM assets WHERE kind="portrait" AND name=? ORDER BY CASE WHEN path LIKE "PesMobile/%" THEN 0 ELSE 1 END LIMIT 1',(candidate,)).fetchone()
            if r:return r[0]
        return None

    def _thumbnail(self,c,pid,base):
        # '_' is the native squad/roster image; '_l' belongs to the larger
        # artwork. Resolve the game's aliases before choosing the package.
        for key in dict.fromkeys((str(pid),str(base),str(int(pid)&0xfffffff))):
            name=self._alias(c,key+'_')
            row=c.execute('SELECT id FROM assets WHERE kind="portrait" AND name=? ORDER BY CASE WHEN path LIKE "PesMobile/%" THEN 0 ELSE 1 END LIMIT 1',(name,)).fetchone()
            if row:return row[0]
        return None

    def _alias(self,c,name):
        visited=set()
        while name not in visited:
            visited.add(name)
            try:row=c.execute('SELECT after FROM card_aliases WHERE before=?',(name,)).fetchone()
            except sqlite3.OperationalError:return name
            if not row or row[0]==name:break
            name=row[0]
        return name

    def identities(self):
        with contextlib.closing(self.db()) as c:
            try:rows=[dict(r) for r in c.execute('SELECT * FROM identities ORDER BY name')]
            except sqlite3.OperationalError:rows=[]
        return {kind:[r for r in rows if r['kind']==kind] for kind in ('nation','team')}

    def player(self,pid):
        with contextlib.closing(self.db()) as c:
            row=c.execute('SELECT * FROM players WHERE id=?',(str(pid),)).fetchone()
            if not row:raise ValueError('球员编号不在当前数据库中')
            from native_celebration import restore_payload
            r=dict(row);r['payload']=restore_payload(json.loads(r['payload']));r['portrait']=self._portrait(c,r['id'],r['base_id'])
            from ai_playing_styles import restore_payload as restore_ai_styles
            restore_ai_styles(r['payload'])
            r['thumbnail']=self._thumbnail(c,r['id'],r['base_id'])
            from native_appearance import profile
            r['appearance_profile']=profile(self.resources,r['id'])
            if r['payload']['parameters'][47]==0:
                raise ValueError('原数据库此条是体型、能力为零的空占位记录，无法作为真实球员模板')
            alias=self._alias(c,r['id']+'_').split('_')[0]
            # Native legend IDs retain their person ID in the low 28 bits.
            # An exact name join cannot find retired players with no base row.
            person=str(int(r['id'])&0xfffffff)
            model_keys=list(dict.fromkeys([r['id'],r['base_id'],alias,person,*person_keys(r['id']),*person_keys(r['base_id'])]))
            matches=[dict(v) for v in c.execute('SELECT * FROM assets WHERE kind="model" AND player_key IN ('+','.join('?' for _ in model_keys)+') ORDER BY CASE WHEN name LIKE "%_Face" THEN 0 ELSE 1 END,name LIMIT 40',model_keys)]
            r['models']=matches
            selected,r['model_resolution']=resolve_face(matches,r['id'])
            r['auto_model']=selected['id'] if selected else None
            r['face_variants']=[m for m in matches if m['name'].endswith('_Face')]
            r['card_layers']=[dict(v) for v in c.execute('SELECT * FROM assets WHERE kind="card" AND player_key=? ORDER BY name',(r['id'],))]
            r['identity_names']={}
            for kind,value in [('nation',r['payload'].get('_nation_id')),('team',r['payload'].get('initial_base_team_id') or r['payload'].get('initial_base_national_team_id'))]:
                try:name=c.execute('SELECT name,name_en FROM identities WHERE kind=? AND id=?',(kind,value)).fetchone()
                except sqlite3.OperationalError:name=None
                r['identity_names'][kind]={'id':value,'name':name['name'] if name else '', 'name_en':name['name_en'] if name else ''}
            return r

    def assets(self, body):
        kind=body.get('kind','portrait');q=str(body.get('query','')).strip()[:120];page=max(0,int(body.get('page',0)));limit=18
        if kind not in ('portrait','thumbnail','card','model'):raise ValueError('未知资源类别')
        where=' WHERE kind=?';params=['portrait' if kind=='thumbnail' else kind]
        if kind=='thumbnail':
            where+=" AND substr(name,-1)='_' AND (path LIKE 'PesMobile/%' OR NOT EXISTS (SELECT 1 FROM assets preferred WHERE preferred.kind=assets.kind AND preferred.name=assets.name AND preferred.path LIKE 'PesMobile/%'))"
        with contextlib.closing(self.db()) as c:
            if q:
                text='%'+q.replace('%','')+'%'
                owners=list(c.execute('SELECT id,base_id FROM players WHERE search LIKE ? LIMIT 80',(text,)))
                keys={str(v) for row in owners for v in row}
                if kind=='thumbnail':
                    for row in owners:
                        keys.update((str(int(row['id'])&0xfffffff),self._alias(c,str(row['id'])+'_').split('_')[0]))
                keys=list(keys)
                where+=' AND (name LIKE ? OR path LIKE ?'
                params+=[text,text]
                if keys:where+=' OR player_key IN ('+','.join('?' for _ in keys)+')';params+=keys
                where+=')'
            count=c.execute('SELECT count(*) FROM assets'+where,params).fetchone()[0]
            rows=[dict(r) for r in c.execute('SELECT * FROM assets'+where+' ORDER BY name LIMIT ? OFFSET ?',params+[limit,page*limit])]
        for row in rows:
            hit=self.cache.get(row['id'])
            if row['kind']=='model' and row['name'].endswith('_Face') and hit and hit.get('decoder_revision')!=FACE_DECODER_REVISION:hit=None
            row['converted']=hit if hit and (self.store.root/'assets'/hit['asset_id']).is_file() else None
        if kind=='thumbnail':
            with contextlib.closing(self.db()) as c:
                for row in rows:
                    owner=c.execute('SELECT name,name_en FROM players WHERE id=? OR base_id=? ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END LIMIT 1',(row['player_key'],row['player_key'],row['player_key'])).fetchone()
                    row['player_name']=owner['name'] if owner else ''
        return {'rows':rows,'total':count,'page':page,'pages':max(1,(count+limit-1)//limit)}

    def card(self,pid):
        if self.state['phase']!='ready':raise ValueError('请先准备原版资源缓存')
        player=self.player(pid)
        ident=int(pid);style=(ident>>40)&255;style=f'{style>>4:02d}{style&15:02d}';agent=(ident>>28)&4095
        limited=bool(ident&(1<<48))
        layers=[];movies=[];missing=[]
        native_movies={Path(path).stem:path for path in self.card_media['movies']}
        with contextlib.closing(self.db()) as c:
            portrait_row=c.execute('SELECT name FROM assets WHERE id=?',(player['portrait'],)).fetchone() if player['portrait'] else None
            portrait_pid=portrait_row[0].split('_')[0] if portrait_row else str(pid)
            art_ids=list(dict.fromkeys([str(pid),portrait_pid]))
            def common_names(slot):
                names=[f'{style}_{agent}_{slot}_lim',f'{style}_{slot}_lim'] if limited else []
                return names+[f'{style}_{agent}_{slot}',f'{style}_{slot}']
            def texture(names):
                for name in names:
                    resolved=self._alias(c,name)
                    row=c.execute('SELECT * FROM assets WHERE name=? AND kind IN ("portrait","card") ORDER BY CASE WHEN path LIKE "PesMobile/%" THEN 0 ELSE 1 END LIMIT 1',(resolved,)).fetchone()
                    if row:return dict(row)
            def movie(names):
                for name in names:
                    for candidate in (name+'_v',self._alias(c,name+'_v'),self._alias(c,name)+'_v'):
                        if candidate in native_movies:return native_movies[candidate]
            for slot in ('f01','f02','f03','f04','f05','f06','f07','f09','f10'):
                names=[f'{style}_{slot}_{key}_' for key in art_ids]+common_names(slot)
                row=texture(names)
                if row:layers.append({**row,'slot':slot,'blend':'screen' if slot in ('f03','f05','f06','f07','f10') else 'source-over'})
            if player['portrait']:
                row=c.execute('SELECT * FROM assets WHERE id=?',(player['portrait'],)).fetchone()
                layers.append({**dict(row),'slot':'portrait','blend':'source-over'})
            # The native ST_PlayerCardFrontTexture contains f01..f10. bXX are
            # card-back layers; mXX are MobileIcon layers, never front layers.
            for slot in ('f02','f03','f05','f10'):
                path=movie(common_names(slot))
                if path:movies.append({'slot':slot,'path':path,'kind':'video','blend':'source-over' if slot=='f02' else 'screen'})
        converted=self.convert({'ids':list(dict.fromkeys(row['id'] for row in layers))})['results'] if layers else {}
        output=[]
        for row in layers:
            hit=converted.get(row['id'],{})
            if hit.get('asset_id'):output.append({**hit,'slot':row['slot'],'blend':row['blend']})
            else:missing.append({'path':row['path'],'reason':hit.get('error','原版图层无法读取')})
        font_paths={name:'PesMobile/Content/Platforms/_Android/Assets/ui/Font/'+path+'.ufont' for name,path in [('sans','eFootballSans-Regular'),('headline','eFootballStencil-Regular'),('chinese','NotoSansSC-SemiBold')]}
        with self.convert_lock:
            raw_paths=[row['path'] for row in movies]+list(font_paths.values())
            requests=[path for path in raw_paths if not (self.converted/path).is_file()]
            if requests:self.run(requests,'raw')
            for row in movies:
                path=self.converted/row['path']
                try:
                    webm=path.with_suffix('.webm');meta=convert_movie(path,webm,self.ffmpeg)
                    imported=self.store.import_asset(webm,'video')
                    output.append({**row,**meta,'name':path.stem,'asset_id':imported['id'],'url':imported['url']})
                except (ValueError,OSError) as exc:missing.append({'path':row['path'],'reason':str(exc)})
            fonts={}
            for name,ref in font_paths.items():
                path=self.converted/ref
                if not path.is_file():missing.append({'path':ref,'reason':'原版字体未读取'});continue
                raw=path.read_bytes();font=path.with_suffix('.otf' if raw[:4]==b'OTTO' else '.ttf');font.write_bytes(raw)
                asset=self.store.import_asset(font,'font');fonts[name]={'asset_id':asset['id'],'path':ref}
        animated_slots={row['slot'] for row in output if row['kind']=='video'}
        output=[row for row in output if row['kind']=='video' or row['slot'] not in animated_slots]
        order={'f01':0,'f02':1,'portrait':2,'f04':3,'f03':4,'f05':5,'f06':6,'f07':7,'f10':8,'f09':9}
        output.sort(key=lambda row:order[row['slot']])
        return {'version':1,'composition_revision':3,'source_id':str(pid),'native_style':style,'native_agent':agent,
                'card_type':player['card_type'],'source_label':player['payload'].get('_studio_card_label',''),
                'layers':output,'fonts':fonts,'layout':self.card_media['layout'],'missing':missing,
                'ui':{key:self.card_widgets[key] for key in ('widgets','states','native_dispatch')},'info':self.card_info(pid),
                'video_frames_unchanged':True,'renderer':'native-assets-browser-composite',
                'material_verified_in_game':False}

    def card_info(self,pid,team_id=None,nation_id=None):
        player=self.player(pid);payload=player['payload']
        team=payload.get('initial_base_team_id') or payload.get('initial_base_national_team_id') or 0
        nation=payload.get('_nation_id') or 0
        team=int(team_id) if team_id is not None else int(team)
        nation=int(nation_id) if nation_id is not None else int(nation)
        if not 0<=team<=131071 or not 0<=nation<=511:raise ValueError('球队或国家编号超出原表范围')
        graphics=self.card_widgets['graphics'];symbols=self.card_widgets['symbols'];paths={}
        for i in range(6):
            key=f'UiPlayerCardInfo_RarityStar_{i}'
            if key in graphics:paths[f'stars{i}']=graphics[key]
        for key,name in [('logo','UiPlayerCardInfo_eFootballLogo'),('combi','UiPlayerCardInfo_Combi'),
                         ('celebration','UiPlayerCardInfo_Celebration'),('boosterEffect','UiPlayerCardBoosterEffect')]:
            if name in graphics:paths[key]=graphics[name]
        for i in range(6):
            name='CmnIconBoosterTiny_'+(str(i) if i else 'Empty')
            if name in graphics:paths[f'booster{i}']=graphics[name]
        for key,names in [('club',[f'e_{team:06d}_r_l',f'e_{team:06d}_r',f'e_{team:06d}_f_l',f'e_{team:06d}_f']),('nation',[f'{nation:03d}_l',f'{nation:03d}'])]:
            path=next((symbols[n] for n in names if n in symbols),None)
            if path:paths[key]=path
        imported={};missing=[]
        with self.convert_lock:
            needed=[v for v in paths.values() if not (self.converted/Path(v).with_suffix('.png')).is_file()]
            if needed:self.run(needed)
            for key,ref in paths.items():
                image=self.converted/Path(ref).with_suffix('.png')
                if not image.is_file():missing.append(ref);continue
                asset=self.store.import_asset(image,'image')
                imported[key]={'asset_id':asset['id'],'kind':'image','path':ref}
        return {'source_id':str(pid),'team_id':team,'nation_id':nation,'symbol_revision':2,
                'national_team':not bool(payload.get('initial_base_team_id')),
                'rarity':max(0,min(5,int(payload.get('default_rarity',0))+1)),
                'assets':imported,'missing':missing}

    def setup(self,body):
        if self.state['phase']=='preparing':return self.summary()
        if self.state['phase']=='ready' and self.containers.is_dir():return self.summary()
        main=Path(body.get('apk') or self.home/'原始APK'/('73efootball-'+self.profile.get('game_version','V16')+'.apk')).absolute()
        companion=Path(body.get('companion') or self.home/'原始APK'/'73efootball-离线资源包-V9+.apk').absolute()
        if not main.is_file() or not companion.is_file():raise ValueError('请选择主 APK 和离线资源包 APK')
        if not self.tool.is_file():raise ValueError('缺少随软件提供的 tools/asset-decoder 工具目录')
        self.state={'phase':'preparing','message':'正在检查两个 APK','files':0,'bytes':0}
        threading.Thread(target=self._setup,args=(main,companion),daemon=True).start();return self.summary()

    def _setup(self,main,companion):
        with self.setup_lock:
            staging=self.root/('prepare-'+uuid.uuid4().hex)
            try:
                staging.mkdir(parents=True)
                def copy(z,member,priority=0):
                    item=z.getinfo(member);name=Path(member).name
                    if priority and not name.startswith('global.'):
                        p=Path(name);name=p.stem+'_10_P'+p.suffix
                    dest=staging/name
                    self.state['message']='准备原版资源：'+name
                    with z.open(member) as src,dest.open('wb') as dst:
                        while chunk:=src.read(4*1024*1024):dst.write(chunk);self.state['bytes']+=len(chunk)
                    self.state['files']+=1
                with zipfile.ZipFile(main) as z:
                    release=json.loads(z.read('assets/gateway-release/release-manifest.json'))['release_id']
                    if release!=self.profile['release_id']:raise ValueError('APK 与当前数据库不是同一版，请先在“APK 数据更新”中导入新版主包')
                    with z.open('lib/arm64-v8a/libUE4.so') as lib:
                        lib.seek(self.profile['resource_key_offset']);key=lib.read(32)
                    if hashlib.sha256(key).hexdigest()!=self.profile['resource_key_sha256']:raise ValueError('资源引擎与 V14 不同，需要适配')
                    with z.open('lib/arm64-v8a/libUE4.so') as lib:
                        if hashlib.file_digest(lib,'sha256').hexdigest()!=self.profile['native_engine_sha256']:
                            raise ValueError('APK 引擎指纹与已核对 V14 不同')
                    (staging/'resource-key.bin').write_bytes(key)
                    with z.open('assets/pc0000_mobile_and.pak') as raw,zipfile.ZipFile(raw) as nested:
                        for n in nested.namelist():
                            if n.endswith(('.pak','.ucas','.utoc')):copy(nested,n,10)
                    for n in z.namelist():
                        if n.startswith(('assets/pc0010_mobile_and.','assets/gateway-release/livedata/','assets/gateway-release/custom-resources/')) and n.endswith(('.pak','.ucas','.utoc')):copy(z,n,10)
                with zipfile.ZipFile(companion) as z,z.open('assets/resource-bootstrap/resources.zip') as raw,zipfile.ZipFile(raw) as nested:
                    for n in nested.namelist():
                        if n.endswith(('.pak','.ucas','.utoc')):copy(nested,n)
                if self.containers.exists():raise ValueError('资源目录已存在，请重新启动检查，不覆盖已有缓存')
                staging.rename(self.containers)
                (self.root/'ready.json').write_text(json.dumps({'apk':str(main),'companion':str(companion),'release_id':release,'files':self.state['files']}),encoding='utf8')
                self.state={'phase':'ready','message':'原版资源已就绪','files':self.state['files']}
            except Exception as exc:self.state={'phase':'error','message':str(exc)}

    def run(self,paths,mode='auto'):
        if any(not (self.native/name).is_file() for name in ('Detex.dll','zlib-ng2.dll','oodle-data-shared.dll')):
            raise ValueError('随软件提供的离线解码库缺失，请重新解压完整软件包')
        self.converted.mkdir(parents=True,exist_ok=True)
        config=self.converted/('batch-'+uuid.uuid4().hex+'.txt');config.write_text('\n'.join(paths),encoding='utf8')
        env=os.environ.copy();env['TEMP']=str(self.native);env['TMP']=str(self.native)
        key=(self.containers/'resource-key.bin').read_bytes().hex()
        args=[str(self.tool),'-i',str(self.containers),'-g','GAME_eFootball','-k','0x'+key,'-c',str(config),'-o',str(self.converted),'-y','--mesh-format','Gltf2']
        if mode!='auto':args+=['-f',mode]
        result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        config.unlink(missing_ok=True)
        (self.root/'last-conversion.log').write_bytes(result.stdout)
        if result.returncode:raise ValueError('原版资源转换失败，请查看 library/last-conversion.log')

    def convert(self,body):
        identifiers=list(dict.fromkeys(body.get('ids') or []))
        if not identifiers or len(identifiers)>24:raise ValueError('每次请选择 1–24 项资源')
        if self.state['phase']!='ready':raise ValueError('请先准备原版资源缓存')
        with self.convert_lock,contextlib.closing(self.db()) as c:
            rows=[];results={}
            for identifier in identifiers:
                row=c.execute('SELECT * FROM assets WHERE id=?',(identifier,)).fetchone()
                if not row:raise ValueError('资源编号不在游戏索引中')
                hit=self.cache.get(identifier)
                current_face=row['kind']=='model' and row['name'].endswith('_Face')
                if hit and (not current_face or hit.get('decoder_revision')==FACE_DECODER_REVISION) and (self.store.root/'assets'/hit['asset_id']).is_file():results[identifier]=hit
                else:rows.append(dict(row))
            ordinary=[r['path'] for r in rows if r['kind']!='model' or not r['name'].endswith('_Face')]
            if ordinary:self.run(ordinary)
            for r in rows:
                suffix='.glb' if r['kind']=='model' else '.png';p=self.converted/Path(r['path']).with_suffix(suffix)
                face_metadata={}
                if r['kind']=='model' and r['name'].endswith('_Face'):
                    p,face_metadata=self.convert_face(r)
                if not p.is_file():
                    results[r['id']]={'error':'这个游戏资源尚不能转换，未使用替代图像','path':r['path']};continue
                metadata={}
                if suffix=='.glb':p,metadata=self.texture_model(p,r)
                asset=self.store.import_asset(p,'model' if suffix=='.glb' else 'image')
                hit={'asset_id':asset['id'],'url':asset['url'],'path':r['path'],'name':r['name'],'kind':r['kind'],**metadata,**face_metadata}
                results[r['id']]=hit;self.cache[r['id']]=hit
            self.cache_path.write_text(json.dumps(self.cache,ensure_ascii=False,indent=2),encoding='utf8')
            return {'results':results}

    def face_assets(self):
        if self._face_assets is None:
            from native_art import Assets
            self._face_assets=Assets(self.containers)
        return self._face_assets

    def convert_face(self,row):
        from native_skeletal import mesh_glb
        assets=self.face_assets();raw,_,details=assets.face(row['path'])
        class SelectedFace:
            def raw(self,path):return raw
        target=self.converted/Path(row['path']).with_suffix('.glb')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(mesh_glb(SelectedFace(),row['path']))
        return target,{'decoder_revision':FACE_DECODER_REVISION,'face_source':details}

    def texture_model(self,path,row):
        b=path.read_bytes();length=struct.unpack_from('<I',b,12)[0];doc=json.loads(b[20:20+length]);names=[m['name'] for m in doc.get('materials',[]) if m.get('name')]
        folder=row['path'].rsplit('/',1)[0]
        # Original UE material parameters supply the exact texture links.
        sources={m['name']:m.get('extras',{}).get('studio_material_path') for m in doc.get('materials',[]) if m.get('name')}
        candidates={name:('PesMobile/Content/'+sources[name][6:]+'.uasset' if sources.get(name,'') and sources[name].startswith('/Game/') else folder+'/'+name+'.uasset') for name in names}
        if candidates:self.run(list(candidates.values()),'json')
        materials={};requests=[];bindings=[]
        for name in names:
            file=self.converted/Path(candidates[name]).with_suffix('.json')
            if not file.is_file():continue
            data=json.loads(file.read_text(encoding='utf-8-sig'))
            for export in data:
                props=export.get('Properties',{})
                for param in props.get('TextureParameterValues',[]):
                    label=param.get('ParameterInfo',{}).get('Name','').casefold()
                    if label not in ('basecolormap','basecolor','diffuse','diffusemap'):continue
                    ref=param.get('ParameterValue',{}).get('ObjectPath','')
                    if not ref.startswith('/Game/'):continue
                    texture=row['path'].split('/Content/')[0]+'/Content/'+ref[6:].split('.')[0]+'.uasset'
                    requests.append(texture);bindings.append((name,texture,props));break
        missing=[v for v in requests if not (self.converted/Path(v).with_suffix('.png')).is_file()]
        if missing:self.run(missing)
        for name,ref,props in bindings:
            png=self.converted/Path(ref).with_suffix('.png')
            if png.is_file():materials[name]=(png.read_bytes(),props)
        target=path.with_name(path.stem+'-native.glb');metadata=glb_textures(path,materials,target)
        return target,metadata
