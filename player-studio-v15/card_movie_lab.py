"""Command-line prototype for converting and importing custom card movies."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
DEPS = ROOT.parent / '.work/movie-lab-deps'
if DEPS.is_dir():
    sys.path.insert(0, str(DEPS))

from card_movie_import import encode, mux_ivf
from card_movie_pak import MoviePak
from apk_format import replace_entries, local_signer, sign_v2, verify_v2


def build(args):
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    key = Path(args.resource_key).read_bytes()
    movies = {'PlayerCard/0501_256_f02_v.usm': Path(args.large).read_bytes(),
              'PlayerCard/0501_m06_v.usm': Path(args.mini).read_bytes()}
    # Accept only the tested opaque contract for each original playback resource.
    from native_movie import remux_usm
    expected = [(182, 256, 300), (128, 128, 150)]
    reports = []
    for (name, raw), (w, h, count) in zip(movies.items(), expected):
        _, meta = remux_usm(raw)
        if (meta['width'], meta['height'], meta['frames']) != (w, h, count) or meta['duration'] != count / 30:
            raise ValueError('测试槽位要求大卡 182×256/30fps/10秒，小卡 128×128/30fps/5秒')
        reports.append({'path': name, **meta})
    source = Path(args.apk).resolve()
    original_signature = verify_v2(source)
    signing = Path(args.signing)
    if not (signing / 'personal-apk-signing-key.pem').is_file():
        raise ValueError('必须指定已有本机签名目录')
    signer, cert = local_signer(signing)
    from cryptography.hazmat.primitives import serialization
    cert_hash = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    same_signer = cert_hash == original_signature['signer_sha256']
    if not same_signer and not args.allow_new_signature:
        raise ValueError('所选签名与源 APK 不同；未生成可能无法覆盖安装的包')
    pak_reports = []
    changes = {}
    member = 'assets/pc0000_mobile_and.pak'
    with zipfile.ZipFile(source) as apk, apk.open(member) as stream, zipfile.ZipFile(stream) as nested:
        for entry in nested.infolist():
            if Path(entry.filename).name not in ('Idsphone.pak', 'pc7000_mobile_and.pak'):
                continue
            original = folder / ('original-' + Path(entry.filename).name)
            with nested.open(entry) as inp, original.open('xb') as out:
                shutil.copyfileobj(inp, out, 4 * 1024 * 1024)
            patched = folder / Path(entry.filename).name
            pak = MoviePak(original, key)
            report = pak.replace(patched, movies)
            pak_reports.append({'archive': entry.filename, **report})
            changes[entry.filename] = patched
            # Independent CUE4Parse extraction of the actual new archive.
            verify = folder / ('readback-' + patched.stem)
            cmd = [str(ROOT / 'tools/asset-decoder/cue4parse.exe'), '--pak', str(patched),
                   '-o', str(verify), '-g', 'GAME_eFootball', '-k', '0x' + key.hex(), '-f', 'raw', '-y']
            for name in movies:
                cmd += ['-p', 'PesMobile/Content/Movies/' + name]
            env = os.environ.copy()
            env['TEMP'] = env['TMP'] = str(ROOT / 'tools/asset-decoder/native')
            result = subprocess.run(cmd, capture_output=True, timeout=120, env=env,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            # Do not copy decoder command lines or key-bearing logs to reports.
            if result.returncode:
                raise ValueError('独立 CUE4Parse 解码器执行失败')
            for name, raw in movies.items():
                matches = list(verify.rglob(Path(name).name))
                if len(matches) != 1 or matches[0].read_bytes() != raw:
                    raise ValueError('独立资源解码器回读不匹配：' + name)
        if len(changes) != 2:
            raise ValueError('未找到预期的两个电影 PAK')
        new_nested = folder / 'pc0000_mobile_and.pak'
        with zipfile.ZipFile(new_nested, 'x', allowZip64=True) as out:
            out.comment = nested.comment
            for entry in nested.infolist():
                with (changes[entry.filename].open('rb') if entry.filename in changes else nested.open(entry)) as inp:
                    with out.open(copy.copy(entry), 'w') as dst:
                        shutil.copyfileobj(inp, dst, 4 * 1024 * 1024)
    print('PAK independent readback passed; building signed APK', flush=True)
    unsigned = folder / 'unsigned.apk'
    target = folder / '73efootball-V17-自制动态卡面测试.apk'
    replace_entries(source, unsigned, {member: new_nested.read_bytes()})
    sign_v2(unsigned, target, signer, cert)
    signature = verify_v2(target)
    # Check the final APK, including every unchanged ZIP entry's directory CRC/size.
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target) as after:
        a = {i.filename: (i.CRC, i.file_size) for i in before.infolist() if i.filename != member}
        b = {i.filename: (i.CRC, i.file_size) for i in after.infolist() if i.filename != member}
        if a != b:
            raise ValueError('APK 非目标条目发生改变')
        with after.open(member) as stream, zipfile.ZipFile(stream) as nested:
            for name, path in changes.items():
                with nested.open(name) as inp, path.open('rb') as expected:
                    if hashlib.file_digest(inp, 'sha256').digest() != hashlib.file_digest(expected, 'sha256').digest():
                        raise ValueError('最终 APK 内嵌电影 PAK 不匹配')
    report = {'apk': str(target), 'source': str(source), 'signature': signature,
              'same_signer': same_signer, 'unchanged_other_apk_entries': True,
              'installation': 'same-signer update' if same_signer else 'different signer: use an isolated test device/emulator; cannot update source installation',
              'independent_cue4parse_readback': True, 'movies': reports,
              'paks': pak_reports, 'in_game_tested': False,
              'scope': '共享原槽位替换；大卡0501/256背景，小卡0501系列M06前景特效；未新增独立球员绑定'}
    (folder / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=True), flush=True)
    # Only this run's verified, disposable intermediates are removed. Originals
    # and all installed/user files are outside these paths and remain untouched.
    unsigned.unlink()
    new_nested.unlink()
    for p in folder.glob('original-*.pak'):
        p.unlink()


def main():
    parser = argparse.ArgumentParser(description='自制动态卡面实验工具（尚需手机实测）')
    sub = parser.add_subparsers(dest='command', required=True)
    convert = sub.add_parser('convert', help='普通视频转大卡背景和小卡实验动画')
    convert.add_argument('video')
    convert.add_argument('--output', required=True)
    convert.add_argument('--mini-video', help='可单独提供方形小卡测试源')
    patch = sub.add_parser('build', help='替换固定测试槽位并生成同签名 APK')
    for name in ('apk', 'resource-key', 'signing', 'large', 'mini', 'output'):
        patch.add_argument('--' + name, required=True)
    patch.add_argument('--allow-new-signature', action='store_true', help='允许生成不同签名的隔离测试包，不能覆盖原签名安装')
    args = parser.parse_args()
    if args.command == 'build':
        return build(args)
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    reports = {}
    for name, w, h, seconds, source in [('large-background', 182, 256, 10, args.video),
                                        ('mini-effect', 128, 128, 5, args.mini_video or args.video)]:
        encode(source, folder / (name + '.ivf'), ROOT / 'tools/video/ffmpeg.exe', w, h, 30, seconds)
        reports[name] = mux_ivf(folder / (name + '.ivf'), folder / (name + '.usm'))
    (folder / 'conversion.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(reports, ensure_ascii=True))


if __name__ == '__main__':
    main()
