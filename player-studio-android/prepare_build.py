"""Stage only public v1.8.4 code and resources; build the Android codecs."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--sdk',required=True);p.add_argument('--reuse-codecs',help='Our previous editor APK with byte-identical codec sources');p.add_argument('--core',default=str(ROOT/'core' if (ROOT/'core').is_dir() else ROOT.parent/'player-studio-v15'));args=p.parse_args()
    sdk=Path(args.sdk);core=Path(args.core);generated=ROOT/'app/build/generated';generated.mkdir(parents=True,exist_ok=True)
    python=generated/'studioPython'
    if python.exists():shutil.rmtree(python)
    python.mkdir()
    for source in core.glob('*.py'):
        if not source.name.startswith(('build_','prepare_','annotate_','package_release','enrich_')):shutil.copy2(source,python/source.name)
    assets=generated/'studioAssets';assets.mkdir(exist_ok=True)
    with zipfile.ZipFile(assets/'studio-bundle.zip','w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for folder in ('resources','web'):
            for source in (core/folder).rglob('*'):
                if not source.is_file() or source.suffix in ('.pyc','.log'):continue
                data=source.read_bytes()
                if source.name=='index.html':
                    data=re.sub(rb'V16 \xc2\xb7 [^<]+',b'V16 \xc2\xb7 1.9.5.1 Android',data).replace(b'</head>',b'<link rel="stylesheet" href="/android.css"><script defer src="/android-ui.js"></script></head>')
                z.writestr(source.relative_to(core).as_posix(),data)
        for name in ('personal_runtime.py','personal_binding.py'):z.write(core/name,name)
        for source in (ROOT/'licenses').glob('*'):
            if source.is_file():z.write(source,'licenses/'+source.name)
        for source in (ROOT/'THIRD_PARTY_NOTICES.md',):z.write(source,'licenses/'+source.name)
        for relative in ('cityhash/COPYING','texture/LICENSE'):
            source=ROOT/'app/src/main/cpp/vendor'/relative
            if source.is_file():z.write(source,'licenses/'+relative.replace('/','-'))
        overlay=ROOT/'web'
        for source in overlay.glob('*'):z.write(source,'web/'+source.name)
    (assets/'studio-bundle.sha256').write_text(hashlib.sha256((assets/'studio-bundle.zip').read_bytes()).hexdigest(),encoding='ascii')
    (ROOT/'local.properties').write_text('sdk.dir='+str(sdk).replace('\\','/')+'\n',encoding='utf8')
    if args.reuse_codecs:
        with zipfile.ZipFile(args.reuse_codecs) as archive:
            for abi in ('arm64-v8a','x86_64'):
                dest=ROOT/'app/src/main/jniLibs'/abi;dest.mkdir(parents=True,exist_ok=True)
                (dest/'libstudio_codecs.so').write_bytes(archive.read('lib/'+abi+'/libstudio_codecs.so'))
        print('Public core staged; existing identical ARM64 and x86_64 codec binaries retained.');return
    ndk=sorted((sdk/'ndk').glob('*'))[-1];compiler=ndk/'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    cpp=ROOT/'app/src/main/cpp'
    for abi,target in (('arm64-v8a','aarch64-linux-android26'),('x86_64','x86_64-linux-android26')):
        dest=ROOT/'app/src/main/jniLibs'/abi;dest.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(compiler),'--target='+target,'-shared','-fPIC','-O2','-std=c++17','-Wno-c++11-narrowing','-static-libstdc++',
            '-Wl,-z,max-page-size=16384','-I'+str(cpp/'vendor/cityhash'),'-I'+str(cpp/'vendor/texture'),
            str(cpp/'studio_codecs.cpp'),str(cpp/'vendor/cityhash/city.cc'),str(cpp/'vendor/texture/astc.cpp'),
            str(cpp/'vendor/texture/etc.cpp'),str(cpp/'vendor/texture/bcn.cpp'),
            '-o',str(dest/'libstudio_codecs.so')],check=True)
    print('Public core staged; ARM64 and x86_64 codecs built.')
if __name__=='__main__':main()

