"""Append replacement movies to the inspected UE4 v11 PAK, retaining indexes.

Only existing USM entries can be replaced. Original payloads, directory index,
path hashes and all unrelated encoded entries remain byte-for-byte unchanged.
Format reference: CUE4Parse FPakEntry.cs and PakFileReader.cs (Apache-2.0).
"""
from pathlib import Path
import hashlib
import shutil
import struct

from native_iostore import aes, read_string

MAGIC = 0x5a6f12e1


class MoviePak:
    def __init__(self, path, key):
        self.path = Path(path)
        self.key = key
        with self.path.open('rb') as f:
            f.seek(-221, 2)
            tail = f.read()
            at = tail.find(struct.pack('<I', MAGIC))
            if at != 17:
                raise ValueError('不是已适配的 221 字节 PAK 尾部')
            self.footer = tail
            _, version, offset, size = struct.unpack_from('<IIQQ', tail, at)
            if version != 11 or tail[16] not in (0, 1):
                raise ValueError('仅支持已检查的 PAK v11')
            self.encrypted = bool(tail[16])
            f.seek(offset)
            index = f.read(size)
            self.index = aes(index, key) if self.encrypted else index
            if hashlib.sha1(self.index).digest() != tail[41:61]:
                raise ValueError('PAK 主索引哈希错误')
            self.mount, pos = read_string(self.index, 0)
            self.count, seed, has_hash = struct.unpack_from('<IQI', self.index, pos)
            if has_hash != 1:
                raise ValueError('PAK 缺少路径哈希索引')
            pos += 16
            # Existing indexes remain in the untouched prefix of the new PAK.
            pos += 36
            if struct.unpack_from('<I', self.index, pos)[0] != 1:
                raise ValueError('PAK 缺少完整目录索引')
            pos += 4
            directory_offset, directory_size = struct.unpack_from('<QQ', self.index, pos)
            directory_hash = self.index[pos + 16:pos + 36]
            pos += 36
            encoded_size = struct.unpack_from('<I', self.index, pos)[0]
            self.encoded_start = pos + 4
            self.encoded = self.index[pos + 4:pos + 4 + encoded_size]
            f.seek(directory_offset)
            directory = f.read(directory_size)
            if self.encrypted:
                directory = aes(directory, key)
            if hashlib.sha1(directory).digest() != directory_hash:
                raise ValueError('PAK 目录索引哈希错误')
        self.entries = {}
        pos = 4
        for _ in range(struct.unpack_from('<I', directory)[0]):
            folder, pos = read_string(directory, pos)
            count = struct.unpack_from('<I', directory, pos)[0]
            pos += 4
            for _ in range(count):
                name, pos = read_string(directory, pos)
                location = struct.unpack_from('<i', directory, pos)[0]
                pos += 4
                self.entries[folder + name] = location
        if len(self.entries) != self.count:
            raise ValueError('PAK 目录数量不匹配')

    def read_replacement(self, name):
        """Read and verify an uncompressed movie written by this adapter."""
        loc = self.entries[name]
        flags, offset, size = struct.unpack_from('<III', self.encoded, loc)
        if flags != 0xe0000000:
            raise ValueError('此接口仅回读本工具生成的未压缩条目')
        with self.path.open('rb') as f:
            f.seek(offset)
            header = f.read(53)
            _, compressed, original, method = struct.unpack_from('<QQQI', header)
            raw = f.read(size)
        if (compressed, original, method) != (size, size, 0) or hashlib.sha1(raw).digest() != header[28:48]:
            raise ValueError('替换视频文件头或哈希无效')
        return raw

    def replace(self, destination, replacements):
        if not replacements:
            raise ValueError('没有选择动画')
        index = bytearray(self.index)
        for name, raw in replacements.items():
            if name not in self.entries or not name.startswith('PlayerCard/') or not name.endswith('.usm') or raw[:4] != b'CRID':
                raise ValueError('仅允许替换当前 PAK 已有的球员卡 USM')
            loc = self.entries[name]
            if loc < 0 or loc + 12 > len(self.encoded):
                raise ValueError('未适配的 PAK 条目位置')
            flags = struct.unpack_from('<I', self.encoded, loc)[0]
            # Both 32-bit offset and uncompressed length must already be present.
            if flags & 0xc0000000 != 0xc0000000 or flags & 0x3f == 0x3f:
                raise ValueError('原条目编码布局未适配')
        destination = Path(destination)
        with self.path.open('rb') as src, destination.open('xb') as out:
            shutil.copyfileobj(src, out, 4 * 1024 * 1024)
            for name, raw in replacements.items():
                offset = out.tell()
                if offset + len(raw) >= 2**32:
                    raise ValueError('测试 PAK 超过 32 位条目范围')
                header = struct.pack('<QQQI', 0, len(raw), len(raw), 0) + hashlib.sha1(raw).digest() + struct.pack('<BI', 0, 0)
                out.write(header)
                out.write(raw)
                struct.pack_into('<III', index, self.encoded_start + self.entries[name], 0xe0000000, offset, len(raw))
            index_offset = out.tell()
            index_bytes = bytes(index)
            stored = aes(index_bytes, self.key, encrypt=True) if self.encrypted else index_bytes
            out.write(stored)
            footer = bytearray(self.footer)
            struct.pack_into('<QQ', footer, 25, index_offset, len(stored))
            footer[41:61] = hashlib.sha1(index_bytes).digest()
            out.write(footer)
        check = MoviePak(destination, self.key)
        if check.entries != self.entries:
            raise ValueError('替换后目录发生变化')
        touched = set()
        for name, raw in replacements.items():
            if check.read_replacement(name) != raw:
                raise ValueError('PAK 动画回读失败')
            start = self.encoded_start + self.entries[name]
            touched.update(range(start, start + 12))
        if any(a != b and i not in touched for i, (a, b) in enumerate(zip(self.index, check.index))):
            raise ValueError('非目标索引被改动')
        return {'entries': self.count, 'replaced': sorted(replacements), 'unrelated_index_bytes_preserved': True}
