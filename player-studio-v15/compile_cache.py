"""Bounded, verified local compiler artifacts. No pickle or executable cache."""
from pathlib import Path
import contextlib,copy,hashlib,importlib,json,marshal,os,re,sys,threading,types,uuid,zipfile

REVISION='v17-artifacts-and-blocks-2.0.6-v1'
_LOCK=threading.RLock()
_CODE={}
MODULES=('native_art','native_mesh','native_skeletal','native_glb','native_appearance','native_body',
         'native_models','native_iostore','native_thumbnail','thumbnail_background','thumbnail_motion',
         'card_front','private_card_motion','rig_compatibility','glb_import','native_movie',
         'native_library','player_identity_binding')

def digest_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb')as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def _normalized(code):
    return code.replace(co_filename='',co_consts=tuple(_normalized(v)if isinstance(v,types.CodeType)else v for v in code.co_consts))

def code_fingerprint():
    if not _CODE:
        h=hashlib.sha256()
        try:
            for name in MODULES:
                module=importlib.import_module(name);loader=module.__loader__
                code=loader.get_code(name)
                if not isinstance(code,types.CodeType):raise ValueError('Cannot fingerprint compiler '+name)
                h.update(name.encode());h.update(marshal.dumps(_normalized(code)))
        except (AttributeError,ImportError,OSError,ValueError):
            # Some Android AssetFinder versions don't expose get_code. The
            # signed editor bundles this manifest from its exact Python files;
            # it is never taken from an imported game/database/project.
            from studio_resources import bundled_resources
            data=json.loads((bundled_resources()/'compiler-source-hashes.json').read_text('utf8'))
            if data.get('revision')!=REVISION or set(data.get('files',{}))!=set(MODULES):raise ValueError('Compiler source manifest differs')
            if any(not re.fullmatch('[a-f0-9]{64}',v)for v in data['files'].values()):raise ValueError('Compiler source manifest is invalid')
            h=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode())
        _CODE['digest']=h.hexdigest()
    return _CODE['digest']

def write_source_manifest(core):
    core=Path(core);data={'revision':REVISION,'files':{name:digest_file(core/(name+'.py'))for name in MODULES}}
    (core/'resources/compiler-source-hashes.json').write_text(json.dumps(data,sort_keys=True,indent=2),'utf8')

def source_context(library,resources):
    """TOC chunk hashes, source identities, compiler code and adapter data."""
    container_folder=Path(library.containers);sources=[]
    for path in sorted(container_folder.glob('*.utoc')):
        data=path.with_suffix('.ucas');stat=data.stat()
        sources.append([path.name,digest_file(path),stat.st_size,stat.st_mtime_ns])
    adapters=[]
    for folder in dict.fromkeys((Path(library.resources),Path(resources))):
        for path in sorted(folder.iterdir()):
            if path.is_file()and path.suffix in('.json','.bin'):
                adapters.append([path.name,digest_file(path)])
    import PIL,numpy,zlib
    return {'revision':REVISION,'code':code_fingerprint(),'profile':library.profile,
            'runtime':{'python':sys.implementation.cache_tag,'pillow':PIL.__version__,'numpy':numpy.__version__,'zlib':zlib.ZLIB_RUNTIME_VERSION},
            'source_tocs':sources,'source_key':digest_file(container_folder/'resource-key.bin'),
            'adapters':adapters}

def assets_in(value):
    result=set()
    def visit(v):
        if isinstance(v,str)and re.fullmatch(r'[a-f0-9]{64}\.[a-z0-9]+',v):result.add(v)
        elif isinstance(v,dict):
            for child in v.values():visit(child)
        elif isinstance(v,(tuple,list)):
            for child in v:visit(child)
    visit(value);return sorted(result)

class CompileCache:
    def __init__(self,root,context,limit=None):
        self.root=Path(root);self.context=context
        self.limit=limit if limit is not None else(4 if sys.platform=='win32'else 1)*1024**3
        self.stats={'hits':{},'misses':{},'corrupt':0,'write_failures':0,'evicted_bytes':0}
        if self.root.is_symlink()or self.root.is_junction():raise ValueError('编译缓存目录不能是外部链接')
        self.root.mkdir(parents=True,exist_ok=True)

    def key(self,kind,inputs,files=()):
        values=[]
        for path in sorted(set(map(Path,files))):
            values.append([str(path),digest_file(path)if path.is_file()else'MISSING'])
        data={'kind':kind,'context':self.context,'inputs':inputs,'files':values}
        return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def _read(self,path,key):
        with zipfile.ZipFile(path)as archive:
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('schema')!=1 or manifest.get('key')!=key:raise ValueError('Compiler cache identity differs')
            def decode(node):
                kind=node['t'];value=node.get('v')
                if kind=='value':
                    if value is not None and type(value)not in(bool,int,float,str):raise ValueError('Invalid cache scalar')
                    return value
                if kind=='list':return[decode(v)for v in value]
                if kind=='tuple':return tuple(decode(v)for v in value)
                if kind=='dict':return{decode(k):decode(v)for k,v in value}
                if kind=='blob':
                    name=node['entry']
                    if not re.fullmatch(r'b[0-9]{6}',name):raise ValueError('Invalid cache blob name')
                    raw=archive.read(name)
                    if len(raw)!=node['bytes']or hashlib.sha256(raw).hexdigest()!=node['sha256']:raise ValueError('Compiler cache checksum differs')
                    return raw
                raise ValueError('Invalid cache node')
            return decode(manifest['result'])

    def _write(self,path,key,result,encoded):
        temporary=self.root/('writing-'+uuid.uuid4().hex+'.tmp')
        try:
            with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_STORED)as archive:
                count=0
                def encode(value):
                    nonlocal count
                    if value is None or type(value)in(bool,int,float,str):return{'t':'value','v':value}
                    if isinstance(value,(bytes,bytearray,memoryview)):
                        raw=bytes(value);name=f'b{count:06d}';count+=1
                        # Encoded/encrypted blocks and USM files do not benefit
                        # from another DEFLATE pass. Raw native artifacts do.
                        method=zipfile.ZIP_STORED if encoded or raw.startswith(b'CRID')else zipfile.ZIP_DEFLATED
                        archive.writestr(name,raw,compress_type=method,compresslevel=1)
                        return{'t':'blob','entry':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                    if isinstance(value,dict):return{'t':'dict','v':[[encode(k),encode(v)]for k,v in value.items()]}
                    if isinstance(value,(list,tuple)):return{'t':'tuple'if isinstance(value,tuple)else'list','v':[encode(v)for v in value]}
                    raise TypeError('Unsupported compiler cache value')
                archive.writestr('manifest.json',json.dumps({'schema':1,'key':key,'result':encode(result)},ensure_ascii=False,separators=(',',':'),allow_nan=False))
            if temporary.stat().st_size>self.limit:return
            temporary.replace(path)
            self.prune()
        finally:temporary.unlink(missing_ok=True)

    def run(self,kind,inputs,producer,files=(),encoded=False):
        if not re.fullmatch(r'[a-z-]+',kind):raise ValueError('Invalid compiler cache category')
        key=self.key(kind,inputs,files);path=self.root/(kind+'-'+key+'.zip')
        if path.is_file()and not path.is_symlink():
            try:
                result=self._read(path,key);os.utime(path,None)
                self.stats['hits'][kind]=self.stats['hits'].get(kind,0)+1
                return result,{'hit':True,'key':key,'kind':kind}
            except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError):
                self.stats['corrupt']+=1
                with contextlib.suppress(OSError):path.unlink()
        self.stats['misses'][kind]=self.stats['misses'].get(kind,0)+1
        result=producer()
        try:self._write(path,key,result,encoded)
        except (OSError,ValueError,TypeError,RuntimeError):self.stats['write_failures']+=1
        return result,{'hit':False,'key':key,'kind':kind}

    def prune(self):
        with _LOCK:
            files=[]
            for path in self.root.glob('*.zip'):
                if path.is_symlink()or not re.fullmatch(r'[a-z-]+-[a-f0-9]{64}\.zip',path.name):continue
                try:stat=path.stat();files.append((stat.st_mtime_ns,path,stat.st_size))
                except OSError:pass
            total=sum(size for _,_,size in files)
            for _,path,size in sorted(files):
                if total<=self.limit:break
                try:path.unlink();total-=size;self.stats['evicted_bytes']+=size
                except OSError:pass

    def report(self):return{**copy.deepcopy(self.stats),'limit_bytes':self.limit,'directory':str(self.root)}

def clear(root):
    root=Path(root)
    if not root.exists():return{'files':0,'bytes':0}
    if root.is_symlink()or root.is_junction():raise ValueError('编译缓存目录不能是外部链接')
    count=size=0
    for path in root.glob('*.zip'):
        if path.is_symlink()or not re.fullmatch(r'[a-z-]+-[a-f0-9]{64}\.zip',path.name):continue
        length=path.stat().st_size;path.unlink();count+=1;size+=length
    return{'files':count,'bytes':size}

def summary(root):
    root=Path(root);size=count=0
    if root.is_symlink()or root.is_junction():return{'files':0,'bytes':0,'unavailable':True}
    if root.is_dir():
        for path in root.glob('*.zip'):
            if path.is_symlink()or not re.fullmatch(r'[a-z-]+-[a-f0-9]{64}\.zip',path.name):continue
            try:size+=path.stat().st_size;count+=1
            except OSError:pass
    return{'files':count,'bytes':size}
