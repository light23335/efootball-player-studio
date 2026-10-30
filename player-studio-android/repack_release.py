"""Update Python/web assets in our existing APK; retain its native binaries.

Retains the base Java/resources/codecs. An explicitly compiled InstalledGames
helper may be added in a separate DEX, alongside its package visibility queries.
Signing uses the operator's existing private release key.
"""
from pathlib import Path
import argparse,hashlib,io,json,re,struct,sys,zipfile
ROOT=Path(__file__).resolve().parent
VERSION='2.1-android.2'
VERSION_CODE=201001
RETIRED_CORE_MODULES={'team_workshop.py','team_cpk.py','team_workshop.pyc','team_cpk.pyc','draw_policy.py','draw_journal.py','draw_policy.pyc','draw_journal.pyc'}

def compact_editor_apk(source,output,changes,removed=()):
    """Write one copy of each editor asset and retain 16-KiB .so alignment."""
    import copy
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for entry in old.infolist():
            if entry.filename in removed:continue
            if re.fullmatch(r'META-INF/[^/]+\.(?:SF|RSA|DSA|EC)',entry.filename,re.I) or entry.filename=='META-INF/MANIFEST.MF':continue
            item=copy.copy(entry);item.extra=b'';item.flag_bits&=~8
            raw=changes.get(item.filename)
            if raw is None:raw=old.read(entry)
            if item.compress_type==zipfile.ZIP_STORED:
                alignment=16384 if item.filename.endswith('.so') else 4
                gap=(-(z.fp.tell()+30+len(item.filename.encode('utf8'))))%alignment
                if gap:
                    if gap<4:gap+=alignment
                    item.extra=struct.pack('<HH',0xd935,gap-4)+bytes(gap-4)
            z.writestr(item,raw)

def manifest_version(raw,code,name):
    data=bytearray(raw);strings=[];locations=[];at=8;changed=False;version_index=None;pool=None
    while at<len(data):
        kind,header,size=struct.unpack_from('<HHI',data,at)
        if size<header or at+size>len(data):raise ValueError('Invalid Android manifest chunk')
        if kind==1:
            pool=(at,header,size)
            count,styles,flags,start,style_start=struct.unpack_from('<5I',data,at+8)
            def length(pos,utf8):
                if utf8:
                    n=data[pos];return (((n&127)<<8)|data[pos+1],pos+2) if n&128 else (n,pos+1)
                n=struct.unpack_from('<H',data,pos)[0];return (((n&32767)<<16)|struct.unpack_from('<H',data,pos+2)[0],pos+4) if n&32768 else (n,pos+2)
            for i in range(count):
                pos=at+start+struct.unpack_from('<I',data,at+header+4*i)[0]
                n,pos=length(pos,bool(flags&256))
                if flags&256:byte_count,pos=length(pos,True);codec='utf8'
                else:byte_count=n*2;codec='utf-16le'
                strings.append(bytes(data[pos:pos+byte_count]).decode(codec));locations.append((pos,byte_count,codec))
        elif kind==0x102:
            ns,element,attribute_start,attribute_size,count=struct.unpack_from('<IIHHH',data,at+16)
            if strings[element]=='manifest':
                for i in range(count):
                    pos=at+16+attribute_start+i*attribute_size
                    attr_ns,key,raw_index=struct.unpack_from('<3I',data,pos)
                    if strings[key]=='versionCode':struct.pack_into('<I',data,pos+16,code);changed=True
                    elif strings[key]=='versionName':
                        index=raw_index if raw_index!=0xffffffff else struct.unpack_from('<I',data,pos+16)[0]
                        version_index=index
        at+=size
    if not changed:raise ValueError('Manifest has no versionCode')
    if version_index is None or pool is None:raise ValueError('Manifest has no versionName string')
    strings[version_index]=name
    at,header,size=pool
    count,styles,flags,start,style_start=struct.unpack_from('<5I',data,at+8)
    style_offsets=bytes(data[at+header+count*4:at+header+(count+styles)*4])
    style_data=bytes(data[at+style_start:at+size]) if style_start else b''
    def length(n,utf8):
        if utf8:return bytes([n]) if n<128 else bytes([128|(n>>8),n&255])
        return struct.pack('<H',n) if n<32768 else struct.pack('<HH',0x8000|(n>>16),n&65535)
    encoded=bytearray();offsets=[]
    for value in strings:
        offsets.append(len(encoded));units=len(value.encode('utf-16le'))//2
        if flags&256:
            b=value.encode('utf8');encoded.extend(length(units,True)+length(len(b),True)+b+b'\0')
        else:encoded.extend(length(units,False)+value.encode('utf-16le')+b'\0\0')
    encoded.extend(bytes((-len(encoded))%4))
    start=header+4*(count+styles);rebuilt=bytearray(data[at:at+header])
    struct.pack_into('<I',rebuilt,4,start+len(encoded)+len(style_data))
    struct.pack_into('<III',rebuilt,16,flags&~1,start,start+len(encoded) if style_data else 0)
    rebuilt.extend(struct.pack('<'+'I'*count,*offsets)+style_offsets+encoded+style_data)
    data[at:at+size]=rebuilt;struct.pack_into('<I',data,4,len(data))
    return bytes(data)

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--output',required=True);p.add_argument('--key',required=True);p.add_argument('--password-file',required=True);p.add_argument('--work',required=True);p.add_argument('--installed-games-dex');p.add_argument('--controller-dex');p.add_argument('--runtime-dex-dir');a=p.parse_args()
    core=ROOT/'core' if (ROOT/'core').is_dir() else ROOT.parent/'player-studio-v15';sys.path.insert(0,str(core))
    from compile_cache import write_source_manifest
    write_source_manifest(core)
    from apk_format import replace_entries,sign_v2,verify_v2
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
    work=Path(a.work);work.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.base) as source:
        app=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(source.read('assets/chaquopy/app.imy'))) as old,zipfile.ZipFile(app,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            replacements={p.name:p.read_bytes() for p in core.glob('*.py') if not p.name.startswith(('build_','prepare_','annotate_','package_release','enrich_'))}
            replacements.update({p.name:p.read_bytes() for p in (ROOT/'app/src/main/python').glob('*.py')})
            # Pure Python movie muxer dependencies; native VP9 encoding uses
            # Android MediaCodec, never a Windows ffmpeg executable.
            deps=ROOT.parent/'.work/studio-build-deps'
            for package in ('wannacri','ffmpeg','pythonjsonlogger','tqdm','future','past','libfuturize','libpasteurize','colorama'):
                folder=deps/package
                if not folder.is_dir():raise ValueError('Missing bundled movie dependency: '+package)
                for item in folder.rglob('*.py'):replacements[item.relative_to(deps).as_posix()]=item.read_bytes()
            for entry in old.infolist():
                if entry.filename not in replacements and entry.filename not in RETIRED_CORE_MODULES:z.writestr(entry,old.read(entry))
            for name,raw in replacements.items():compile(raw,name,'exec');z.writestr(name,raw)
        bundle=io.BytesIO()
        with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
            for folder in ('web','resources'):
                for item in (core/folder).rglob('*'):
                    if not item.is_file() or item.suffix in ('.pyc','.log'):continue
                    raw=item.read_bytes()
                    if item.name=='index.html':raw=raw.replace(b'</head>',b'<link rel="stylesheet" href="/android.css"><script defer src="/android-ui.js"></script></head>')
                    z.writestr(item.relative_to(core).as_posix(),raw)
            for name in ('personal_runtime.py','personal_binding.py','division_squads.py','native_overall.py',
                         'ai_tactical_profiles.py','ai_division_sessions.py','ai_match_manager.py',
                         'ai_match_channel.py','ai_match_runtime.py','ai_match_state.py','action_trace.py','league_rules.py','art_registry.py','native_diy_binding.py'):z.write(core/name,name)
            for item in (ROOT/'licenses').glob('*'):
                if item.is_file():z.write(item,'licenses/'+item.name)
            z.write(ROOT/'THIRD_PARTY_NOTICES.md','licenses/THIRD_PARTY_NOTICES.md')
            for rel in ('cityhash/COPYING','texture/LICENSE'):
                item=ROOT/'app/src/main/cpp/vendor'/rel
                if item.is_file():z.write(item,'licenses/'+rel.replace('/','-'))
            for item in (ROOT/'web').glob('*'):
                if item.is_file():z.write(item,'web/'+item.name)
        build=json.loads(source.read('assets/chaquopy/build.json'));build['assets']['app.imy']=hashlib.sha1(app.getvalue()).hexdigest()
        changes={'assets/chaquopy/app.imy':app.getvalue(),'assets/chaquopy/build.json':json.dumps(build,separators=(',',':')).encode(),
                 'assets/studio-bundle.zip':bundle.getvalue(),'assets/studio-bundle.sha256':hashlib.sha256(bundle.getvalue()).hexdigest().encode(),
                 'AndroidManifest.xml':manifest_version(source.read('AndroidManifest.xml'),VERSION_CODE,VERSION)}
        from android_manifest import Manifest
        manifest=Manifest(changes['AndroidManifest.xml'])
        if not any(name=='queries' for _,name,_ in manifest.nodes()):manifest.add_queries(['com.efootball.revival.local','com.efootball.revival.resources','com.efootball.revival.diyer','com.efootball.revival.diyassets'],launcher=True)
        controller_marker='assets/studio-controller-dex.txt'
        removed=set()
        if a.runtime_dex_dir:
            if a.controller_dex or a.installed_games_dex:raise ValueError('Full runtime DEX cannot be combined with partial helper replacements')
            runtime={p.name:p.read_bytes() for p in Path(a.runtime_dex_dir).glob('classes*.dex') if re.fullmatch(r'classes\d*\.dex',p.name)}
            if 'classes.dex' not in runtime:raise ValueError('Compiled runtime must contain classes.dex')
            changes.update(runtime)
            removed={n for n in source.namelist() if re.fullmatch(r'classes\d*\.dex',n)}-runtime.keys()
            changes[controller_marker]=b'classes.dex'
            changes['assets/studio-installed-games-dex.txt']=b'classes.dex'
        if a.controller_dex:
            if controller_marker not in source.namelist():raise ValueError('Compile BaseActivity and MainActivity with D8 and provide --runtime-dex-dir; binary class renaming is invalid')
            name=source.read(controller_marker).decode().strip()
            if name=='classes.dex':raise ValueError('A merged runtime requires --runtime-dex-dir, not a partial controller DEX')
            changes[name]=Path(a.controller_dex).read_bytes();changes[controller_marker]=name.encode()
            manifest.add_activity_alias('com.playerstudio.editor.BaseActivity','com.playerstudio.editor.MainActivity')
        elif not a.runtime_dex_dir and controller_marker not in source.namelist():raise ValueError('This release requires the compiled physical-controller Java helper')
        changes['AndroidManifest.xml']=manifest.bytes()
        marker='assets/studio-installed-games-dex.txt'
        if a.installed_games_dex:
            name=source.read(marker).decode().strip() if marker in source.namelist() else 'classes'+str(max([1]+[int(m.group(1) or 1) for n in source.namelist() if (m:=re.fullmatch(r'classes(\d*)\.dex',n))])+1)+'.dex'
            if name=='classes.dex':raise ValueError('A merged runtime requires --runtime-dex-dir, not a partial InstalledGames DEX')
            changes[name]=Path(a.installed_games_dex).read_bytes();changes[marker]=name.encode()
        elif not a.runtime_dex_dir and marker not in source.namelist():raise ValueError('This release requires the compiled InstalledGames Java helper')
        from dex_checks import inspect_runtime
        dex_names={n for n in source.namelist() if re.fullmatch(r'classes\d*\.dex',n)}|{n for n in changes if re.fullmatch(r'classes\d*\.dex',n)}
        dex_preflight=inspect_runtime({n:changes[n] if n in changes else source.read(n) for n in dex_names-removed})
        from launcher_icon import prepare_launcher
        icon_changes,icon_removed,icon_report=prepare_launcher(source,(ROOT/'app/src/main/res/drawable-nodpi/studio_launcher.png').read_bytes())
        changes.update(icon_changes);removed.update(icon_removed)
        # Added DEX and marker entries must also be written, not only replacements.
        missing={k:v for k,v in changes.items() if k not in source.namelist()}
    compact_editor_apk(a.base,work/'unsigned-android.apk',changes,removed)
    if missing:
        with zipfile.ZipFile(work/'unsigned-android.apk','a',zipfile.ZIP_DEFLATED) as z:
            for name,raw in missing.items():z.writestr(name,raw)
    password=Path(a.password_file).read_text(encoding='utf8').strip().encode()
    key,cert,_=load_key_and_certificates(Path(a.key).read_bytes(),password)
    sign_v2(work/'unsigned-android.apk',a.output,key,cert);verification=verify_v2(a.output)
    with zipfile.ZipFile(a.output) as check:
        assert all(check.read(name)==value for name,value in changes.items())
        if check.testzip():raise ValueError('APK ZIP CRC failure')
        with open(a.output,'rb') as raw:
            for entry in check.infolist():
                if entry.compress_type!=zipfile.ZIP_STORED:continue
                raw.seek(entry.header_offset+26);length,extra=struct.unpack('<HH',raw.read(4))
                alignment=16384 if entry.filename.endswith('.so') else 4
                if (entry.header_offset+30+length+extra)%alignment:raise ValueError('APK alignment failure: '+entry.filename)
    report={'version':VERSION,'version_code':VERSION_CODE,'path':str(Path(a.output).resolve()),'bytes':Path(a.output).stat().st_size,'sha256':hashlib.sha256(Path(a.output).read_bytes()).hexdigest(),'signature':verification,'launcher_icon':icon_report,'base_activity_lifecycle_preserved':True,'physical_controller_helper_added':bool(a.controller_dex),'native_codecs_unchanged':True,'installed_games_helper_added':True,'dex_preflight':dex_preflight,'compiled_runtime_replaced':bool(a.runtime_dex_dir)}
    Path(a.output).with_suffix('.build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
