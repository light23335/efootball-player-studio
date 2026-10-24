"""Integrity-checked, offline, non-destructive APK delta generation/apply.

VCDIFF is handled by the bundled unmodified Apache-2.0 xdelta executable.
No signing keys, game saves or full source APKs are put in an update packet.
"""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import threading
import uuid
import zipfile


def digest(path, callback=None):
    h = hashlib.sha256()
    done = 0
    size = Path(path).stat().st_size
    with open(path, 'rb') as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
            done += len(block)
            if callback:
                callback(done, size)
    return h.hexdigest()


def _lp(data, at=0):
    if at + 4 > len(data):
        raise ValueError('APK 签名块被截断')
    size = struct.unpack_from('<I', data, at)[0]
    if at + 4 + size > len(data):
        raise ValueError('APK 签名块长度无效')
    return data[at+4:at+4+size], at+4+size


def signer_fingerprints(path):
    """Read certificates from APK v2/v3 signing blocks without claiming verification."""
    with open(path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size-65557))
        tail = f.read()
        end = tail.rfind(b'PK\x05\x06')
        if end < 0 or end+22 > len(tail):
            raise ValueError('APK ZIP 目录无效')
        comment_size = struct.unpack_from('<H', tail, end+20)[0]
        if end+22+comment_size != len(tail):
            raise ValueError('APK ZIP 尾部无效')
        central = struct.unpack_from('<I', tail, end+16)[0]
        if central < 24:
            return []
        f.seek(central-24)
        footer = f.read(24)
        if footer[8:] != b'APK Sig Block 42':
            return []
        length = struct.unpack_from('<Q', footer)[0]
        if not 24 <= length <= min(32*1024*1024, central-8):
            raise ValueError('APK 签名块大小无效')
        f.seek(central-length-8)
        block = f.read(length+8)
        if struct.unpack_from('<Q', block)[0] != length:
            raise ValueError('APK 签名块不完整')
    at = 8
    certificates = []
    while at < len(block)-24:
        record_size = struct.unpack_from('<Q', block, at)[0]
        if record_size < 4 or at+8+record_size > len(block)-24:
            raise ValueError('APK 签名条目无效')
        kind = struct.unpack_from('<I', block, at+8)[0]
        if kind in (0x7109871a, 0xf05368c0, 0x1b93ad61):
            signers, _ = _lp(block[at+12:at+8+record_size])
            pos = 0
            while pos < len(signers):
                signer, pos = _lp(signers, pos)
                signed, _ = _lp(signer)
                _, p = _lp(signed)
                certs, _ = _lp(signed, p)
                cert, _ = _lp(certs)
                certificates.append(hashlib.sha256(cert).hexdigest())
        at += 8+record_size
    return sorted(set(certificates))


def apk_info(path, callback=None):
    path = Path(path).absolute()
    if not path.is_file() or path.suffix.lower() != '.apk':
        raise ValueError('请选择现有 APK 文件')
    with zipfile.ZipFile(path) as z:
        if 'AndroidManifest.xml' not in z.namelist():
            raise ValueError('文件不是 Android 安装包')
        release = None
        try:
            release = json.loads(z.read('assets/gateway-release/release-manifest.json')).get('release_id')
        except (KeyError, ValueError):
            pass
    return {'name': path.name, 'size': path.stat().st_size, 'sha256': digest(path, callback),
            'signer_sha256': signer_fingerprints(path), 'release_id': release}


class ApkDelta:
    def __init__(self, home, store):
        self.tool = Path(home)/'tools/apk-delta/xdelta3.exe'
        self.store = store
        self.lock = threading.Lock()
        self.state = {'phase': 'idle', 'message': ''}

    def status(self):
        with self.lock:
            return dict(self.state)

    def update(self, **values):
        with self.lock:
            self.state = {**self.state, **values}

    def start(self, body):
        with self.lock:
            if self.state['phase'] == 'working':
                raise ValueError('已有 APK 任务正在处理，请等待完成')
            if not self.tool.is_file():
                raise ValueError('缺少 tools/apk-delta/xdelta3.exe，请解压完整软件包')
            operation = body.get('operation')
            if operation not in ('create', 'apply', 'inspect'):
                raise ValueError('未知增量操作')
            self.state = {'phase': 'working', 'operation': operation, 'message': '准备校验文件', 'id': uuid.uuid4().hex}
        threading.Thread(target=self._worker, args=(dict(body),), daemon=True).start()
        return self.status()

    def _hash_progress(self, label):
        return lambda done, total: self.update(message=label, done=done, total=total)

    def _run(self, args, temp):
        env = os.environ.copy()
        env.pop('XDELTA', None)
        result = subprocess.run([str(self.tool.absolute()), *map(str, args)], cwd=temp, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('增量处理失败：'+result.stdout.decode('utf8', 'replace')[-1800:])

    def _worker(self, body):
        try:
            with tempfile.TemporaryDirectory(prefix='apk-delta-', dir=self.store.root/'tmp') as work:
                work = Path(work)
                operation = body['operation']
                if operation == 'inspect':
                    info = apk_info(body['source'], self._hash_progress('读取 APK 哈希与签名证书'))
                    self.update(phase='done', message='APK 信息已读取', result=info)
                    return
                if operation == 'create':
                    source = Path(body['source']).absolute()
                    target = Path(body['target']).absolute()
                    before = apk_info(source, self._hash_progress('校验原 APK'))
                    after = apk_info(target, self._hash_progress('校验新版 APK'))
                    if before['sha256'] == after['sha256']:
                        raise ValueError('两个 APK 完全相同，无需增量更新')
                    patch = work/'payload.vcdiff'
                    self.update(message='计算 APK 二进制差异', done=0, total=0)
                    self._run(['-e', '-D', '-S', 'none', '-B', '67108864', '-W', '8388608', '-s', source, target, patch], work)
                    manifest = {'format': '73efootball-apk-delta', 'version': 1, 'algorithm': 'VCDIFF/xdelta3',
                                'source': before, 'target': after,
                                'payload': {'file': 'payload.vcdiff', 'size': patch.stat().st_size, 'sha256': digest(patch)},
                                'same_signer': bool(before['signer_sha256']) and before['signer_sha256'] == after['signer_sha256']}
                    output = self.store.root/'exports'/('APK增量更新-'+self.status()['id'][:8]+'.efupdate')
                    temporary_packet=work/'update.efupdate'
                    with zipfile.ZipFile(temporary_packet, 'x', compression=zipfile.ZIP_STORED) as z:
                        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                        z.write(patch, 'payload.vcdiff')
                    temporary_packet.rename(output)
                    result = {'path': str(output), 'url': '/exports/'+output.name, 'size': output.stat().st_size,
                              'saving_percent': round(100*(1-output.stat().st_size/after['size']), 2), 'manifest': manifest}
                    self.update(phase='done', message='增量包已生成', result=result)
                else:
                    source = Path(body['source']).absolute()
                    packet = Path(body['patch']).absolute()
                    if not packet.is_file():
                        raise ValueError('请选择增量更新包')
                    with zipfile.ZipFile(packet) as z:
                        if z.namelist().count('manifest.json') != 1 or z.namelist().count('payload.vcdiff') != 1:
                            raise ValueError('增量包条目无效')
                        if z.getinfo('manifest.json').file_size > 65536:
                            raise ValueError('增量清单过大')
                        manifest = json.loads(z.read('manifest.json'))
                        if manifest.get('format') != '73efootball-apk-delta' or manifest.get('version') != 1 or manifest.get('algorithm') != 'VCDIFF/xdelta3':
                            raise ValueError('不支持的增量包格式')
                        before = apk_info(source, self._hash_progress('确认增量包适用于所选 APK'))
                        if before['sha256'] != manifest['source']['sha256'] or before['size'] != manifest['source']['size']:
                            raise ValueError('原 APK 不匹配：此增量包只适用于清单指定的确切版本，原文件没有修改')
                        info = z.getinfo('payload.vcdiff')
                        if info.file_size != manifest['payload']['size'] or info.file_size > 8*1024**3:
                            raise ValueError('增量数据大小不匹配')
                        patch = work/'payload.vcdiff'
                        with z.open(info) as src, patch.open('xb') as dst:
                            while chunk := src.read(4*1024*1024):
                                dst.write(chunk)
                        if digest(patch) != manifest['payload']['sha256']:
                            raise ValueError('增量包损坏，校验未通过')
                    target = work/'merged.apk'
                    self.update(message='离线合成新版 APK', done=0, total=0)
                    self._run(['-d', '-D', '-s', source, patch, target], work)
                    after = apk_info(target, self._hash_progress('校验合成结果，确认与完整新版逐字节一致'))
                    for key in ('size', 'sha256', 'signer_sha256'):
                        if after[key] != manifest['target'][key]:
                            raise ValueError('合成结果校验失败，未输出 APK')
                    manifest['same_signer']=bool(before['signer_sha256']) and before['signer_sha256']==after['signer_sha256']
                    output = self.store.root/'exports'/('增量合成新版-'+self.status()['id'][:8]+'.apk')
                    target.rename(output)
                    self.update(phase='done', message='新版 APK 已生成，原包保持原样',
                                result={'path': str(output), 'url': '/exports/'+output.name,
                                        'size': output.stat().st_size, 'manifest': manifest})
        except Exception as exc:
            self.update(phase='error', message=str(exc))
