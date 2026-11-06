"""A verified prepared companion cache can supply later content imports.

The main APK remains necessary for executable code and database records. The
original companion APK is not necessary once its container cache is complete.
"""
import contextlib,hashlib,json,struct,zipfile
from pathlib import Path
from types import SimpleNamespace


class CachedCompanion:
    def __init__(self,library,label=''):
        self.folder=Path(library.containers);self.label=str(label or '')
        profile=library.profile
        if library.state.get('phase')!='ready':raise ValueError('当前库的离线资源尚未准备完整')
        ready=Path(library.root)/'ready.json'
        try:receipt=json.loads(ready.read_text('utf8'))
        except (OSError,ValueError)as e:raise ValueError('当前库缺少资源准备记录，请重新准备离线资源')from e
        if receipt.get('release_id')!=profile.get('release_id'):raise ValueError('当前库的离线资源准备记录版本不一致')
        key=(self.folder/'resource-key.bin').read_bytes()
        if hashlib.sha256(key).hexdigest()!=profile.get('resource_key_sha256'):raise ValueError('当前库的离线资源密钥与已核对版本不一致')
        self.files={p.name:p for p in self.folder.iterdir()if p.is_file()and not p.is_symlink()
                    and p.suffix in('.pak','.utoc','.ucas')and not p.stem.endswith('_10_P')}
        if 'global.utoc'not in self.files or not any(k!='global.utoc'and k.endswith('.utoc')for k in self.files):
            raise ValueError('当前库缺少完整的原版离线资源容器，仍需选择离线资源 APK')
        from native_iostore import Container
        for name,path in self.files.items():
            if path.suffix!='.utoc':continue
            container=Container(path,key);data=path.with_suffix('.ucas')
            if not data.is_file():raise ValueError('离线资源缓存缺少配套文件：'+data.name)
            size=data.stat().st_size
            for block in container.blocks:
                if len(block)!=12:raise ValueError('离线资源缓存块索引不完整：'+name)
                start=int.from_bytes(block[:5],'little');length=int.from_bytes(block[5:8],'little')
                if container.flags&2:length=(length+15)//16*16
                if start+length>size:raise ValueError('离线资源缓存已截断：'+data.name)
        self.sizes={k:p.stat().st_size for k,p in self.files.items()}

    def __str__(self):return self.label
    def namelist(self):return list(self.files)
    def getinfo(self,name):return SimpleNamespace(file_size=self.sizes[name])
    def open(self,name):return self.files[name].open('rb')


@contextlib.contextmanager
def companion_archive(source):
    if isinstance(source,CachedCompanion):yield source
    else:
        with zipfile.ZipFile(source)as z,z.open('assets/resource-bootstrap/resources.zip')as raw,zipfile.ZipFile(raw)as nested:
            yield nested


def select_delta_sources(library,store,body):
    from apk_sources import resolve,kind_matches,recorded
    chosen=resolve(library,store);record=recorded(library,store)
    def find(key):
        # Current library inputs take precedence over stale form values. The
        # form is an explicit fallback when its recorded source has moved.
        values=[chosen.get(key),record.get(key),body.get(key)]
        for value in dict.fromkeys(str(v)for v in values if v):
            path=Path(value).absolute()
            if path.is_file()and kind_matches(path,key):return path
        return None
    apk=find('apk')
    if apk is None:raise ValueError('当前库对应的主程序 APK 已移动或不可读取；请在上方重新选择主程序 APK。离线资源完整时无需重新选择资源包')
    companion=find('companion')
    if companion is None:
        try:companion=CachedCompanion(library,chosen.get('companion')or body.get('companion'))
        except (OSError,ValueError,KeyError,IndexError,struct.error)as e:
            raise ValueError('无法复用当前库的离线资源：'+str(e)+'。请重新选择配套离线资源 APK')from e
    return apk,companion
