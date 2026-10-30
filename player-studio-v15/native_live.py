"""Publish the actual personal CPK hash/size in the client's live-data contract."""
import copy,hashlib,json,os,threading,time,uuid
from pathlib import Path
from contextlib import contextmanager

_RESERVATION_LOCK=threading.Lock()

def version_info(template):
    value=template['version_file']
    return json.loads(value) if isinstance(value,str) else copy.deepcopy(value)

def reserve_version(path,release,template,fingerprint):
    registry=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    return _reserve(registry,release,template,fingerprint)


def _reserve(registry,release,template,fingerprint):
    base=version_info(template)['version']
    if type(base) is not int:raise ValueError('原版实时更新版本号无效')
    group=registry.setdefault(release,{'last':base,'hashes':{}})
    latest=max([base,*[v['last'] for v in registry.values()]])
    version=group['hashes'].get(fingerprint)
    if version is None or version<=base or version<latest:
        version=latest+1
        if version>=2147483647:raise ValueError('实时更新版本号范围已用完，未生成安装包')
        group['last']=version;group['hashes'][fingerprint]=version
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


def reserve_shared(path,local,release,template,fingerprint,seeds=()):
    """One monotonic counter for V13/V14, including concurrent app builds."""
    path=Path(path)
    with _RESERVATION_LOCK,_file_lock(path.with_suffix('.lock')):
        combined={}
        for candidate in (path,Path(local),*map(Path,seeds)):
            if not candidate.is_file():continue
            for key,value in json.loads(candidate.read_text(encoding='utf8')).items():
                entry=combined.setdefault(key,{'last':0,'hashes':{}})
                entry['last']=max(entry['last'],value['last'])
                for digest,version in value['hashes'].items():entry['hashes'][digest]=max(entry['hashes'].get(digest,0),version)
        version,combined=_reserve(combined,release,template,fingerprint)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(combined,separators=(',',':')),encoding='utf8');os.replace(temporary,path)
        return version,combined

def compile_template(template,cpk,version):
    out=copy.deepcopy(template);info=version_info(out)
    if not {'version','dt870Hash','dt870FileSize'}<=info.keys():raise ValueError('此版本的实时更新清单尚未适配')
    if type(version) is not int or not info['version']<version<2147483647:raise ValueError('个人实时更新版本号必须高于原版')
    info.update(version=version,dt870Hash=hashlib.sha256(cpk).hexdigest(),dt870FileSize=len(cpk))
    rows=[r for r in out['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
    if len(rows)!=1:raise ValueError('实时更新清单中的球员 CPK 不唯一，未生成安装包')
    rows[0]['size']=len(cpk)
    out['version_file']=json.dumps(info,ensure_ascii=False,separators=(',',':')) if isinstance(template['version_file'],str) else info
    return out

def verify_template(template,cpk):
    info=version_info(template)
    rows=[r for r in template['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
    if len(rows)!=1 or rows[0]['size']!=len(cpk) or info['dt870FileSize']!=len(cpk) or info['dt870Hash']!=hashlib.sha256(cpk).hexdigest():
        raise ValueError('实时更新清单与实际球员 CPK 不一致，未发布安装包')
    return {'version':info['version'],'bytes':len(cpk),'sha256':info['dt870Hash'],'verified':True}

def verify_apk(path):
    """Check the signed APK's actual download/active copies and live contract."""
    import zipfile
    prefix='assets/gateway-release/'
    active='custom-resources/legends-v10/dt870_mobile_and.cpk'
    download='livedata/dt870_mobile_and.cpk'
    template_path='work/templates/CMD_LOGIN_LIVEDATA.json'
    document_path='custom-resources/personal-player-studio/players.json'
    with zipfile.ZipFile(path) as archive:
        def digest(name):
            h=hashlib.sha256();size=0
            with archive.open(prefix+name) as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk);size+=len(chunk)
            return {'bytes':size,'sha256':h.hexdigest()}
        actual=digest(active)
        if digest(download)!=actual:raise ValueError('实时更新校验失败：下载用与游戏激活用的球员 CPK 副本不同')
        template=json.loads(archive.read(prefix+template_path));info=version_info(template)
        rows=[r for r in template['livedata_list'] if r.get('name')=='dt870_mobile_and.cpk']
        if len(rows)!=1 or rows[0]['size']!=actual['bytes'] or info['dt870FileSize']!=actual['bytes'] or info['dt870Hash']!=actual['sha256']:
            raise ValueError('实时更新校验失败：版本清单与 APK 内实际球员 CPK 不一致')
        document=json.loads(archive.read(prefix+document_path));report=document.get('live_data',{})
        if report.get('version')!=info['version'] or any(report.get(k)!=v for k,v in actual.items()):
            raise ValueError('实时更新校验失败：个人球员配置中的版本、大小或哈希未同步')
        if document.get('resource_files',{}).get('dt870_mobile_and.cpk')!=actual:
            raise ValueError('实时更新校验失败：激活资源校验记录未同步')
        manifest=json.loads(archive.read(prefix+'release-manifest.json'))
        listed={r['path']:r for r in manifest['files']}
        for name in (active,download,template_path,document_path):
            meta=actual if name in(active,download) else digest(name)
            row=listed.get(name,{})
            if any(row.get(k)!=v for k,v in meta.items()):raise ValueError('实时更新校验失败：发布清单未同步 '+name)
    return {'version':info['version'],**actual,'verified':True,'active_download_copies_match':True,'manifest_matches':True}
