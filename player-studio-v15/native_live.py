"""Publish the actual personal CPK hash/size in the client's live-data contract."""
import copy,hashlib,json,os,threading,time,uuid
from pathlib import Path
from contextlib import contextmanager

_RESERVATION_LOCK=threading.Lock()
# Highest publicly delivered V17 live version. Ship this monotonic floor in
# both workshop distributions; an empty/restored user registry must not make
# an old selected source roll an installed client's live version backwards.
PUBLISHED_VERSION_FLOOR=2026102493
VERSION_LIMIT=2147483647

def version_info(template):
    value=template['version_file']
    return json.loads(value) if isinstance(value,str) else copy.deepcopy(value)

def _version(value,source):
    if type(value)is not int or not 0<=value<VERSION_LIMIT:
        raise ValueError(source+'实时更新版本号无效或超出范围')
    return value


def _registry_versions(registry):
    if not isinstance(registry,dict):raise ValueError('实时更新版本记录格式无效')
    result=[]
    for row in registry.values():
        if not isinstance(row,dict)or not isinstance(row.get('hashes'),dict):raise ValueError('实时更新版本记录格式无效')
        result.append(_version(row.get('last'),'已保存的'))
        result.extend(_version(v,'已保存指纹的')for v in row['hashes'].values())
    return result


def library_version(library,store):
    """Read the current imported-library APK, independently of write source."""
    import zipfile
    from apk_sources import recorded
    path=recorded(library,store).get('apk')
    if not path or not Path(path).is_file():raise ValueError('当前资料库主 APK 不可读取，无法核对实时更新版本；请重新选择导入来源')
    try:
        with zipfile.ZipFile(path)as archive:
            name='assets/gateway-release/work/templates/CMD_LOGIN_LIVEDATA.json'
            if archive.getinfo(name).file_size>2*1024*1024:raise ValueError('资料库实时更新清单过大')
            template=json.loads(archive.read(name))
        return _version(version_info(template)['version'],'当前资料库的')
    except (OSError,KeyError,TypeError,UnicodeDecodeError,zipfile.BadZipFile)as exc:
        raise ValueError('当前资料库主 APK 的实时更新版本无法读取')from exc


def reserve_version(path,release,template,fingerprint,*,observed_versions=()):
    registry=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    return _reserve(registry,release,template,fingerprint,observed_versions=observed_versions)


def _reserve(registry,release,template,fingerprint,*,observed_versions=()):
    base=_version(version_info(template)['version'],'来源的')
    latest=max(base,_version(PUBLISHED_VERSION_FLOOR,'已发行的'),
               *[_version(v,'已观察的')for v in observed_versions],*_registry_versions(registry))
    group=registry.get(release,{'last':base,'hashes':{}})
    version=group['hashes'].get(fingerprint)
    if version is None or version<=base or version<latest:
        version=latest+1
        if version>=VERSION_LIMIT:raise ValueError('实时更新版本号范围已用完，未生成安装包')
    group['last']=max(group['last'],version);group['hashes'][fingerprint]=version
    registry[release]=group
    return version,registry


@contextmanager
def _file_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if handle.seek(0,2)==0:handle.write(b'\0');handle.flush()
        if os.name=='nt':
            import msvcrt
            for _ in range(300):
                try:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:time.sleep(.1)
            else:raise ValueError('另一版本正在分配资源版本号，请稍后重试')
            try:yield
            finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def reserve_shared(path,local,release,template,fingerprint,seeds=(),*,observed_versions=()):
    """One monotonic counter for V13/V14, including concurrent app builds."""
    path=Path(path)
    with _RESERVATION_LOCK,_file_lock(path.with_suffix('.lock')):
        combined={}
        for candidate in (path,Path(local),*map(Path,seeds)):
            if not candidate.is_file():continue
            loaded=json.loads(candidate.read_text(encoding='utf8'));_registry_versions(loaded)
            for key,value in loaded.items():
                entry=combined.setdefault(key,{'last':0,'hashes':{}})
                entry['last']=max(entry['last'],value['last'])
                for digest,version in value['hashes'].items():entry['hashes'][digest]=max(entry['hashes'].get(digest,0),version)
        version,combined=_reserve(combined,release,template,fingerprint,observed_versions=observed_versions)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(combined,separators=(',',':')),encoding='utf8');os.replace(temporary,path)
        return version,combined

def container_metadata(source,replacements,template):
    """Measure every native container advertised by this live-data contract."""
    import re
    from export_payload import metadata,measure
    result={}
    for row in version_info(template).get('dt880',[]):
        if not re.fullmatch(r'pc[0-9]+',row.get('name','')):raise ValueError('实时更新容器名称格式改变')
        for suffix in ('.pak','.ucas','.utoc'):
            name=row['name']+'_mobile_and'+suffix
            member='assets/gateway-release/livedata/'+name
            if member in replacements:result[name]=metadata(replacements[member])
            else:
                with source.open(member)as stream:actual=measure(stream)
                result[name]={k:actual[k]for k in('bytes','sha256')}
    return result


def content_fingerprint(cpk_digest,containers):
    return hashlib.sha256(json.dumps({'cpk':cpk_digest,'containers':containers},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def compile_template(template,cpk,version,containers=None):
    out=copy.deepcopy(template);info=version_info(out)
    if not {'version','dt870Hash','dt870FileSize'}<=info.keys():raise ValueError('此版本的实时更新清单尚未适配')
    if type(version) is not int or not info['version']<version<2147483647:raise ValueError('个人实时更新版本号必须高于原版')
    info.update(version=version,dt870Hash=hashlib.sha256(cpk).hexdigest(),dt870FileSize=len(cpk))
    rows=[r for r in out['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
    if len(rows)!=1:raise ValueError('实时更新清单中的球员 CPK 不唯一，未生成安装包')
    rows[0]['size']=len(cpk)
    if containers is not None:
        listed={row['name']:row for row in out['livedata_list']}
        for container in info.get('dt880',[]):
            for field,suffix,size_field in (('hash','.pak','hashFileSize'),('ucas','.ucas','ucasFileSize'),('utoc','.utoc','utocFileSize')):
                name=container['name']+'_mobile_and'+suffix
                actual=containers[name]
                container[field]=actual['sha256'];container[size_field]=actual['bytes']
                if name not in listed:raise ValueError('实时更新下载清单缺少容器 '+name)
                listed[name]['size']=actual['bytes']
    out['version_file']=json.dumps(info,ensure_ascii=False,separators=(',',':')) if isinstance(template['version_file'],str) else info
    return out

def verify_template(template,cpk):
    info=version_info(template)
    rows=[r for r in template['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
    if len(rows)!=1 or rows[0]['size']!=len(cpk) or info['dt870FileSize']!=len(cpk) or info['dt870Hash']!=hashlib.sha256(cpk).hexdigest():
        raise ValueError('实时更新清单与实际球员 CPK 不一致，未发布安装包')
    return {'version':info['version'],'bytes':len(cpk),'sha256':info['dt870Hash'],'verified':True}

def verify_apk(path,replacements=None):
    """Check the signed APK's actual download/active copies and live contract."""
    import zipfile
    prefix='assets/gateway-release/'
    active='custom-resources/legends-v10/dt870_mobile_and.cpk'
    download='livedata/dt870_mobile_and.cpk'
    template_path='work/templates/CMD_LOGIN_LIVEDATA.json'
    document_path='custom-resources/personal-player-studio/players.json'
    with zipfile.ZipFile(path) as archive:
        # Both checks consume the same actual post-signing reads. Expected
        # input metadata never stands in for an observed output digest.
        from export_payload import verify_replacements
        control=(template_path,document_path,'release-manifest.json')
        observed=verify_replacements(archive,replacements,capture={prefix+n for n in control})if replacements is not None else{'digests':{},'captured':{}}
        cache=observed['digests'];captured=observed['captured'];reads=0;hits=0
        def digest(name):
            nonlocal reads,hits
            full=prefix+name
            if full in cache:hits+=1;return cache[full]
            h=hashlib.sha256();size=0
            with archive.open(full) as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk);size+=len(chunk)
            reads+=1;cache[full]={'bytes':size,'sha256':h.hexdigest()};return cache[full]
        def read_json(name):
            full=prefix+name
            return json.loads(captured[full]if full in captured else archive.read(full))
        actual=digest(active)
        if digest(download)!=actual:raise ValueError('实时更新校验失败：下载用与游戏激活用的球员 CPK 副本不同')
        template=read_json(template_path);info=version_info(template)
        rows=[r for r in template['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
        if len(rows)!=1 or rows[0]['size']!=actual['bytes'] or info['dt870FileSize']!=actual['bytes'] or info['dt870Hash']!=actual['sha256']:
            raise ValueError('实时更新校验失败：版本清单与 APK 内实际球员 CPK 不一致')
        document=read_json(document_path);report=document.get('live_data',{})
        from art_registry import verify_content
        content_bindings=verify_content(document)
        if report.get('version')!=info['version'] or any(report.get(k)!=v for k,v in actual.items()):
            raise ValueError('实时更新校验失败：个人球员配置中的版本、大小或哈希未同步')
        if document.get('resource_files',{}).get('dt870_mobile_and.cpk')!=actual:
            raise ValueError('实时更新校验失败：激活资源校验记录未同步')
        manifest=read_json('release-manifest.json')
        listed={r['path']:r for r in manifest['files']}
        download_rows={r['name']:r for r in template['livedata_list']}
        checked_containers=0
        for container in info.get('dt880',[]):
            for field,suffix,size_field in (('hash','.pak','hashFileSize'),('ucas','.ucas','ucasFileSize'),('utoc','.utoc','utocFileSize')):
                name=container['name']+'_mobile_and'+suffix;member='livedata/'+name
                meta=digest(member)
                if container.get(field)!=meta['sha256'] or container.get(size_field)!=meta['bytes'] or download_rows.get(name,{}).get('size')!=meta['bytes']:
                    raise ValueError('实时更新校验失败：原生容器版本清单与实际文件不一致 '+name)
                if any(listed.get(member,{}).get(k)!=v for k,v in meta.items()):
                    raise ValueError('实时更新校验失败：原生容器发布清单未同步 '+name)
                checked_containers+=1
        for name in (active,download,template_path,document_path):
            meta=actual if name in(active,download) else digest(name)
            row=listed.get(name,{})
            if any(row.get(k)!=v for k,v in meta.items()):raise ValueError('实时更新校验失败：发布清单未同步 '+name)
    return {'version':info['version'],**actual,'verified':True,'active_download_copies_match':True,'manifest_matches':True,
            'shared_actual_digests':hits,'additional_digest_reads':reads,'content_bindings':content_bindings,
            'replacement_entries_verified':len(observed['digests'])if replacements is not None else 0,
            'native_container_entries_checked':checked_containers}
