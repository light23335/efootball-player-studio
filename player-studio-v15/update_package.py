"""Validate and stage the program files from a portable release archive."""
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile
import hashlib
import re
import urllib.request
import os
import subprocess
import ctypes
import json


def _save_journal(path, journal):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf8') as f:
        json.dump(journal, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def cleanup_completed_updates(data_root, current_version):
    """Keep the backup from the newest confirmed update; remove older owned updates."""
    from updates import version
    tmp = Path(data_root) / 'tmp'
    if not tmp.is_dir() or tmp.is_symlink() or tmp.is_junction():
        return {'confirmed': False}
    completed = []
    legacy = []
    for work in tmp.glob('studio-update-*'):
        if not work.is_dir() or work.is_symlink() or work.is_junction():
            continue
        try:
            owned = json.loads((work / 'studio-update-owned.json').read_text(encoding='utf8'))
            installed = json.loads((work / 'studio-update-installed.json').read_text(encoding='utf8'))
            if owned != installed or not version(installed.get('version')):
                continue
            completed.append((work, installed, (work / 'studio-update-installed.json').stat().st_mtime_ns))
        except (OSError, ValueError, TypeError):
            # Old versions predate ownership markers. Only recognize their exact
            # generated layout; leave anything unusual untouched.
            try:
                names = {p.name for p in work.iterdir()}
                if (re.fullmatch(r'studio-update-[a-z0-9_]{8}', work.name)
                    and names == {'backup', 'stage', 'package.zip', 'updater.exe'}
                    and (work/'package.zip').is_file() and (work/'updater.exe').is_file()
                    and (work/'backup'/'球员工坊.exe').is_file()
                    and {p.name for p in (work/'backup').iterdir()} <= {'球员工坊.exe','tools'}
                    and {p.name for p in (work/'stage').iterdir()} <= {'球员工坊.exe','tools'}):
                    legacy.append((work, work.stat().st_mtime_ns))
            except OSError:
                pass
            continue
    matches = [item for item in completed if version(item[1]['version']) == version(current_version)]
    if not matches:
        return {'confirmed': False}
    newest = max(matches, key=lambda item: item[2])
    keep, _, cutoff = newest
    removed = 0
    for work, _, stamp in completed:
        if work == keep or stamp > cutoff:
            continue
        try:
            if any(p.is_symlink() or p.is_junction() for p in work.rglob('*')):
                continue
            shutil.rmtree(work)
            removed += 1
        except OSError:
            pass
    for work, stamp in legacy:
        if stamp > cutoff:
            continue
        try:
            if any(p.is_symlink() or p.is_junction() for p in work.rglob('*')):
                continue
            shutil.rmtree(work)
            removed += 1
        except OSError:
            pass
    # The helper may still be exiting. Failed removals are retried on next launch.
    for name in ('package.zip', 'package.zip.partial', 'updater.exe'):
        item = keep / name
        try:
            if item.is_file() and not item.is_symlink(): item.unlink()
        except OSError:
            pass
    stage = keep / 'stage'
    try:
        if stage.is_dir() and not stage.is_symlink() and not stage.is_junction() and not any(p.is_symlink() or p.is_junction() for p in stage.rglob('*')):
            shutil.rmtree(stage)
    except OSError:
        pass
    return {'confirmed': True, 'removed': removed}


def recover_update(home, journal_path):
    home, journal_path = Path(home), Path(journal_path)
    journal = json.loads(journal_path.read_text(encoding='utf8'))
    backup = Path(journal['backup'])
    for entry in reversed(journal['files']):
        rel = PurePosixPath(entry['path'])
        if not rel.parts or any(p in ('.', '..') or ':' in p or '\\' in p for p in rel.parts) or rel.parts[0].casefold() in ('data', 'library'):
            raise ValueError('恢复记录路径无效')
        target, saved = home.joinpath(*rel.parts), backup.joinpath(*rel.parts)
        if entry['existed']:
            if target.is_file() and target.stat().st_size == saved.stat().st_size:
                def digest(path):
                    value = hashlib.sha256()
                    with path.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
                    return value.digest()
                if digest(target) == digest(saved):
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.studio-restore')
            shutil.copy2(saved, temp)
            os.replace(temp, target)
        elif target.exists():
            target.unlink()
    journal_path.unlink()


def run_update_helper(pid, home, work, parent_pid=0):
    """Wait for the old process, replace files, and relaunch the application."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    open_error = ctypes.get_last_error() if not handle else 0
    parent_handle = None
    if parent_pid:
        query = kernel.OpenProcess(0x100000 | 0x1000, False, parent_pid)
        if query:
            kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
            kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
            buf = ctypes.create_unicode_buffer(32768); length = ctypes.c_uint32(len(buf))
            if kernel.QueryFullProcessImageNameW(query, 0, buf, ctypes.byref(length)) and os.path.normcase(os.path.abspath(buf.value)) == os.path.normcase(os.path.abspath(str(home / '球员工坊.exe'))):
                parent_handle = query
            else:
                kernel.CloseHandle(query)
    if handle:
        result = kernel.WaitForSingleObject(handle, 120000)
        kernel.CloseHandle(handle)
        if result != 0:
            if parent_handle: kernel.CloseHandle(parent_handle)
            ctypes.windll.user32.MessageBoxW(None, '工坊未能退出，更新没有执行。', '更新失败', 0x10)
            return
    elif open_error != 87:
        if parent_handle: kernel.CloseHandle(parent_handle)
        ctypes.windll.user32.MessageBoxW(None, '无法确认工坊是否已退出，更新没有执行。', '更新失败', 0x10)
        return
    if parent_handle:
        result = kernel.WaitForSingleObject(parent_handle, 120000)
        kernel.CloseHandle(parent_handle)
        if result != 0:
            ctypes.windll.user32.MessageBoxW(None, '工坊进程尚未完全退出，更新没有执行。', '更新失败', 0x10)
            return
    try:
        journal = home / '.studio-update-recovery.json'
        if journal.exists():
            recover_update(home, journal)
        else:
            install_staged(work / 'stage', home, work / 'backup')
            owned = work / 'studio-update-owned.json'
            if owned.is_file():
                try:
                    _save_journal(work / 'studio-update-installed.json', json.loads(owned.read_text(encoding='utf8')))
                except (OSError, ValueError):
                    pass  # A missing cleanup marker must not stop the updated application.
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, '更新失败，已尝试恢复旧版：' + str(exc), '更新失败', 0x10)
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    subprocess.Popen([str(home / '球员工坊.exe')], cwd=str(home), env=env)


def download_package(url, destination, expected_sha256, progress=None):
    """Download to a temporary file and publish it only after digest verification."""
    if not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256 or ''):
        raise ValueError('更新包缺少有效的 SHA256 校验值')
    destination = Path(destination)
    partial = destination.with_name(destination.name + '.partial')
    if destination.exists() or partial.exists():
        raise ValueError('更新下载文件已存在')
    digest = hashlib.sha256()
    total = 0
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'PlayerStudio-Updater'})
        with urllib.request.urlopen(request, timeout=30) as response, partial.open('xb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    progress(total)
        if digest.hexdigest() != expected_sha256.lower():
            raise ValueError('更新包校验失败')
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return total


def install_staged(stage, home, backup):
    """Replace staged files, restoring the previous files if replacement fails.

    Run only after all application processes have exited. The backup must be a
    fresh directory on the same filesystem as the application.
    """
    stage, home, backup = map(Path, (stage, home, backup))
    if backup.exists():
        raise ValueError('更新备份目录已存在')
    if not (stage / '球员工坊.exe').is_file():
        raise ValueError('更新暂存目录缺少程序')
    files = [p for p in stage.rglob('*') if p.is_file()]
    if any(p.relative_to(stage).parts[0].casefold() in ('data', 'library') for p in files):
        raise ValueError('更新包包含用户数据目录')
    backup.mkdir(parents=True)
    journal_path = home / '.studio-update-recovery.json'
    if journal_path.exists():
        raise ValueError('存在尚未恢复的更新')
    journal = {'backup': str(backup.absolute()), 'files': []}
    _save_journal(journal_path, journal)
    try:
        for source in files:
            rel = source.relative_to(stage)
            target = home / rel
            old = backup / rel
            for parent in (target, *target.parents):
                if parent == home.parent:
                    break
                if parent.is_symlink() or parent.is_junction():
                    raise ValueError('更新路径包含链接：'+str(parent))
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            if existed:
                old.parent.mkdir(parents=True, exist_ok=True)
                # Keep the running program present until its replacement is ready.
                # A separate recovery journal is still required for interruptions.
                shutil.copy2(target, old)
            journal['files'].append({'path': rel.as_posix(), 'existed': existed})
            _save_journal(journal_path, journal)
            source.replace(target)
    except Exception:
        recover_update(home, journal_path)
        raise
    journal_path.unlink()
    return len(journal['files'])


def stage_package(archive, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('更新暂存目录已存在')
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        files = []
        roots = set()
        seen = set()
        unpacked = 0
        for item in entries:
            name = item.filename
            path = PurePosixPath(name)
            if '\\' in name or name.startswith('/') or any(p in ('.', '..') or ':' in p or p.rstrip(' .') != p for p in name.split('/')):
                raise ValueError('更新包路径无效')
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('更新包不允许包含链接')
            if not path.parts:
                continue
            roots.add(path.parts[0])
            if item.is_dir() or len(path.parts) < 2:
                continue
            relative = path.parts[1:]
            if relative[0].casefold() in ('data', 'library'):
                continue
            unpacked += item.file_size
            if unpacked > 4 * 1024**3 or len(files) >= 50000:
                raise ValueError('更新包解压后过大')
            key = '/'.join(relative).casefold()
            if key in seen:
                raise ValueError('更新包包含重复文件')
            seen.add(key)
            files.append((item, relative))
        if len(roots) != 1 or '球员工坊.exe' not in seen:
            raise ValueError('更新包结构无效或缺少程序')
        try:
            destination.mkdir(parents=True)
            for item, relative in files:
                target = destination.joinpath(*relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(item) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
    return len(files)
