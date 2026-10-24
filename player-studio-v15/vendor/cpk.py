#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cpk.py — CRI CPK 容器 读取 / 就地打补丁

eFootball 的 dt*.cpk 用 CRI Middleware 的 CPK 封装。内层每个 .bin 仍是 WESYS 容器,
所以完整链路是:  CPK -> WESYS -> 记录表。

CPK 结构:
    0x00  char[4]  'CPK '
    0x10  @UTF     CpkHeader 表 (被 CRI 的 XOR 混淆)
    各段  @UTF     TOC / ITOC / ETOC / GTOC, 偏移写在 CpkHeader 里
    文件数据段

@UTF 是 CRI 自己的列式表格格式, 大端。混淆用一个乘法同余序列做逐字节 XOR
(m=0x655f, t=0x4115) —— 官方工具写出来就是混淆的, 不是加密。

TOC 每行给出: DirName / FileName / FileSize(存储大小) / ExtractSize(解压后大小)
/ FileOffset。**FileSize != ExtractSize 表示该文件被 CRILAYLA 压缩过** —— 官方的
dt200 一个都没压, 但第三方补丁(ePatch 之类)重打包时会压, 所以读取要能解。

写回一律**存成未压缩**并把两个尺寸字段都改成新长度 —— 游戏的 CRI 库两种都认,
而重新压缩既没必要也容易压出和官方不一样的流。
"""
import struct

try:
    # 原生扩展 (native/, 见 docs/PERF_OPEN_DT200_ZH.md)。缺了也能跑, 只是慢。
    import efootball_native as _native
except ImportError:
    _native = None

MAGIC = b"CPK "
CRILAYLA_MAGIC = b"CRILAYLA"

# @UTF 列存储方式
_ST_ZERO, _ST_CONST, _ST_PERROW = 0x10, 0x30, 0x50
# 类型 -> (struct 格式, 字节数)
_TYPES = {0: (">B",1), 1: (">b",1), 2: (">H",2), 3: (">h",2), 4: (">I",4),
          5: (">i",4), 6: (">Q",8), 7: (">q",8), 8: (">f",4), 9: (">d",8),
          0xA: (">I",4), 0xB: (">Q",8)}


def _deobfuscate_py(buf):
    """参照实现。native 版必须和它逐字节一致 (test_native.py 对着跑)。"""
    out = bytearray(len(buf))
    m, t = 0x655F, 0x4115
    for i, b in enumerate(buf):
        out[i] = b ^ (m & 0xFF)
        m = (m * t) & 0xFFFFFFFF
    return bytes(out)


def deobfuscate(buf):
    """CRI 的 @UTF 混淆 (自反)。"""
    if _native is None:
        return _deobfuscate_py(buf)
    return _native.deobfuscate(bytes(buf))


def _decompress_crilayla_py(buf):
    """CRILAYLA —— CRI 自家的 LZSS 变体。

        b"CRILAYLA" | u32 解压后大小 | u32 压缩块大小 | 压缩块 | 0x100 字节

    最后那 0x100 字节是**原文件开头**, 原样存着不压。压缩块是**从最后一个字节往前**
    按位读的, 输出也从最后一个字节往前填 —— 整个解码是倒着走的, 所以下面所有下标
    看着都像反的。

    token: 1 位标志。0 = 后面 8 位是一个原样字节; 1 = 13 位回溯距离 + 变长长度
    (2/3/5/8 位分级, 每级读满全 1 就继续读下一级, 第四级读满 255 就一直接 8 位)。
    """
    if buf[:8] != CRILAYLA_MAGIC:
        raise ValueError("不是 CRILAYLA 数据")
    usize, csize = struct.unpack_from("<II", buf, 8)
    head = bytes(buf[16 + csize:16 + csize + 0x100])
    if len(head) < 0x100:
        raise ValueError("CRILAYLA 尾部那 0x100 字节文件头不完整")
    out = bytearray(usize + 0x100)
    out[:0x100] = head

    off = 16 + csize - 1                       # 压缩块最后一个字节
    pool = left = 0

    def bits(n):
        nonlocal off, pool, left
        v = 0
        while n:
            if not left:
                pool = buf[off]
                off -= 1
                left = 8
            take = n if n < left else left
            v = (v << take) | ((pool >> (left - take)) & ((1 << take) - 1))
            left -= take
            n -= take
        return v

    end = 0x100 + usize - 1
    done = 0
    while done < usize:
        if bits(1):
            ref = end - done + bits(13) + 3
            ln = 3
            for w in (2, 3, 5, 8):
                v = bits(w)
                ln += v
                if v != (1 << w) - 1:
                    break
            else:
                v = 255
                while v == 255:
                    v = bits(8)
                    ln += v
            for _ in range(ln):
                out[end - done] = out[ref]
                ref -= 1
                done += 1
                if done >= usize:              # 最后一段可能超出, 到量就停
                    break
        else:
            out[end - done] = bits(8)
            done += 1
    return bytes(out)


def decompress_crilayla(buf):
    """CRILAYLA 解压。有原生扩展就用它, 没有就用上面的参照实现。

    两者对**合法**数据逐字节一致。损坏数据上原生版更严格: 参照实现里
    `buf[off]` 的 off 变负会绕到缓冲区末尾接着读(Python 的负下标), 原生版报错。
    两边都是 ValueError, 调用方看不出区别。
    """
    if _native is None:
        return _decompress_crilayla_py(buf)
    return _native.decompress_crilayla(bytes(buf))


class UtfTable:
    """一张已解析的 @UTF 表。保留解混淆后的缓冲区, 支持改写单元格后重新写出。"""

    def __init__(self, buf, obfuscated):
        self.buf = bytearray(buf)
        self.obfuscated = obfuscated
        base = 8
        rows_off, str_off, data_off, name_off = struct.unpack_from(">IIII", buf, 8)
        self.ncol, self.rowlen, self.nrow = struct.unpack_from(">HHI", buf, 24)
        self.base, self.rows_off = base, rows_off
        self._strings = bytes(buf[base + str_off: base + data_off])
        self._data_off = base + data_off

        p = 32
        self.cols = []                       # (名字, storage, type, 常量值, 行内偏移)
        row_cursor = 0
        for _ in range(self.ncol):
            flags = buf[p]; p += 1
            cname = self._s(struct.unpack_from(">I", buf, p)[0]); p += 4
            storage, typ = flags & 0xF0, flags & 0x0F
            const, in_row = None, None
            if storage == _ST_CONST:
                fmt, n = _TYPES[typ]
                const = struct.unpack_from(fmt, buf, p)[0]; p += n
                if typ == 0xA:
                    const = self._s(const)
            elif storage == _ST_PERROW:
                in_row = row_cursor
                row_cursor += _TYPES[typ][1]
            self.cols.append((cname, storage, typ, const, in_row))
        self.name = self._s(name_off)
        self.rows = [self._read_row(i) for i in range(self.nrow)]

    def _s(self, off):
        e = self._strings.index(b"\0", off)
        return self._strings[off:e].decode("utf-8", "replace")

    def _read_row(self, r):
        q = self.base + self.rows_off + r * self.rowlen
        row = {}
        for cname, storage, typ, const, in_row in self.cols:
            if storage == _ST_ZERO:
                row[cname] = 0
            elif storage == _ST_CONST:
                row[cname] = const
            else:
                fmt, n = _TYPES[typ]
                v = struct.unpack_from(fmt, self.buf, q + in_row)[0]
                if typ == 0xA:
                    v = self._s(v)
                elif typ == 0xB:
                    o, ln = v >> 32, v & 0xFFFFFFFF
                    v = bytes(self.buf[self._data_off + o: self._data_off + o + ln])
                row[cname] = v
        return row

    def set(self, r, cname, value):
        """改写第 r 行的某个 per-row 数值列。只支持定长数值类型。"""
        for name, storage, typ, _c, in_row in self.cols:
            if name != cname:
                continue
            if storage != _ST_PERROW:
                raise ValueError(f"列 {cname!r} 不是 per-row 存储, 改不了")
            if typ in (0xA, 0xB):
                raise ValueError(f"列 {cname!r} 是字符串/数据列, 本函数不支持")
            fmt, _n = _TYPES[typ]
            struct.pack_into(fmt, self.buf, self.base + self.rows_off + r * self.rowlen + in_row, value)
            self.rows[r][cname] = value
            return
        raise KeyError(cname)

    def to_bytes(self):
        """写回原始形态 (需要时重新混淆)。"""
        return deobfuscate(bytes(self.buf)) if self.obfuscated else bytes(self.buf)


def parse_utf(buf):
    """兼容旧调用: 返回 (表名, 行列表)。"""
    t = load_utf(buf)
    return t.name, t.rows


def load_utf(buf):
    obf = buf[:4] != b"@UTF"
    if obf:
        buf = deobfuscate(buf)
    if buf[:4] != b"@UTF":
        raise ValueError("不是 @UTF 表 (混淆解不开)")
    return UtfTable(buf, obf)


SECTION_MAGIC = (b"CPK ", b"TOC ", b"ITOC", b"ETOC", b"GTOC", b"HTOC", b"HGTOC")


def _utf_at(data, off):
    """从 off 处读一张 @UTF 表, 返回 (表对象, 表起始偏移, 表字节数)。

    每个段(CPK/TOC/ITOC/...)前面有 16 字节段头, @UTF 表在 +16。"""
    if data[off:off + 4] in SECTION_MAGIC:
        off += 16
    head = data[off:off + 8]
    raw = head if head[:4] == b"@UTF" else deobfuscate(head)
    size = struct.unpack_from(">I", raw, 4)[0]
    total = 8 + size
    return load_utf(data[off:off + total]), off, total


class CpkFile:
    __slots__ = ("dir", "name", "path", "offset", "size", "extract_size", "id")

    def __init__(self, d, n, o, sz, ex, fid):
        self.dir, self.name = d, n
        self.path = f"{d}/{n}" if d else n
        self.offset, self.size, self.extract_size, self.id = o, sz, ex, fid

    @property
    def compressed(self):
        return self.size != self.extract_size

    def __repr__(self):
        c = " [压缩]" if self.compressed else ""
        return f"<{self.path} @{self.offset} {self.size}B{c}>"


class Cpk:
    """一个已解析的 CPK。支持读取内层文件, 以及**不重打包**的就地/挪位补丁。"""

    def __init__(self, data):
        if data[:4] != MAGIC:
            raise ValueError("不是 CPK 容器")
        self.data = bytearray(data)
        self._hdr_tbl, self._hdr_off, self._hdr_len = _utf_at(data, 16)
        self.header = self._hdr_tbl.rows[0]
        toc_off = self.header.get("TocOffset", 0)
        if not toc_off:
            raise ValueError("该 CPK 没有 TOC 段 (可能只有 ITOC)")
        self._toc_tbl, self._toc_off, self._toc_len = _utf_at(data, toc_off)
        # TOC 的 FileOffset 以段起点为基准, 而不是 ContentOffset
        self.base = min(toc_off, self.header.get("ContentOffset", toc_off))
        self.align = self.header.get("Align", 2048) or 2048
        self.files = [CpkFile(r["DirName"], r["FileName"],
                              self.base + r["FileOffset"], r["FileSize"],
                              r["ExtractSize"], r["ID"]) for r in self._toc_tbl.rows]
        self._by_path = {f.path: f for f in self.files}
        self._row_of = {f.path: i for i, f in enumerate(self.files)}

    def __len__(self):
        return len(self.files)

    def get(self, path):
        return self._by_path.get(path)

    def read(self, path):
        """取出一个文件的内容。压缩过的(第三方补丁重打包时常见)在这里解开。"""
        raw = self.read_raw(path)
        if not self._by_path[path].compressed:
            return raw
        if raw[:8] != CRILAYLA_MAGIC:
            # 尺寸对不上又不是 CRILAYLA: 宁可报错也不能把压缩字节当数据交出去,
            # 上层会拿它去按记录长度切, 切出来全是垃圾。
            raise ValueError("%s 是压缩的, 但不是 CRILAYLA (前 8 字节 %r), 解不开"
                             % (path, bytes(raw[:8])))
        out = decompress_crilayla(raw)
        want = self._by_path[path].extract_size
        if len(out) != want:
            raise ValueError("%s 解压后 %d 字节, TOC 说应该是 %d" % (path, len(out), want))
        return out

    def read_raw(self, path):
        """该文件在容器里存着的原始字节 (压缩的话就是压缩后的样子)。"""
        f = self._by_path[path]
        return bytes(self.data[f.offset:f.offset + f.size])

    # ---------- 补丁 ----------

    def slack(self, path):
        """该文件后面到下一个文件之间的空隙字节数 (可安全扩张的余量)。"""
        f = self._by_path[path]
        end = f.offset + f.size
        nxt = min((o.offset for o in self.files if o.offset >= end), default=None)
        if nxt is None:
            nxt = self.base + self.header.get("ContentSize", 0)
        return max(0, nxt - end)

    def _reserved(self):
        """不可覆盖的区域: 文件头 + 各段索引表。"""
        res = [(0, self.base)]
        for k in ("Toc", "Itoc", "Etoc", "Gtoc", "Htoc", "Hgtoc"):
            o = self.header.get(k + "Offset") or 0
            n = self.header.get(k + "Size") or 0
            if o and n:
                res.append((o, o + n))
        return res

    def _find_gap(self, need, exclude_path):
        """在现有布局的空隙里找一段能放下 need 字节的位置。

        没有这一步的话, 每改一次就往末尾追加一次, 文件会无限膨胀 ——
        上一次挪走后腾出来的旧块正好能被下一次复用。"""
        spans = [(f.offset, f.offset + f.size) for f in self.files if f.path != exclude_path]
        spans += self._reserved()
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        limit = len(self.data)
        for i, (_, end) in enumerate(merged):
            start = -(-end // self.align) * self.align
            stop = merged[i + 1][0] if i + 1 < len(merged) else limit
            if stop - start >= need:
                return start
        return None

    def patch(self, path, new_data):
        """把 path 的内容换成 new_data, 返回 (新 CPK 字节, 该文件的新偏移)。

        三级策略, 都**不需要重新打包整个 cpk**, 其余文件逐字节不变:
          1. 原槽位放得下  -> 就地覆盖, 文件总长不变
          2. 别处有空隙    -> 挪进空隙, 文件总长不变 (复用上次挪走腾出的旧块)
          3. 都放不下      -> 追加到末尾
        所有 CRC 字段实测为 0, 无需重算。
        """
        f = self._by_path[path]
        r = self._row_of[path]
        out = bytearray(self.data)
        n = len(new_data)

        if n <= f.size + self.slack(path):
            out[f.offset:f.offset + n] = new_data
            if n < f.size:
                out[f.offset + n:f.offset + f.size] = bytes(f.size - n)
            moved_to = f.offset
        else:
            # 旧块清零必须排在写新数据**之前**: 空隙搜索会把该文件自己原来的位置
            # 算作可用空间, 后清会把刚写进去的数据整片抹掉(实测炸过一次 Player.bin)。
            out[f.offset:f.offset + f.size] = bytes(f.size)
            gap = self._find_gap(n, path)
            if gap is not None:
                out[gap:gap + n] = new_data
                moved_to = gap
            else:
                out += bytes((-len(out)) % self.align)
                moved_to = len(out)
                out += new_data
                out += bytes((-len(out)) % self.align)
            self._toc_tbl.set(r, "FileOffset", moved_to - self.base)

        self._toc_tbl.set(r, "FileSize", n)
        self._toc_tbl.set(r, "ExtractSize", n)                # 未压缩文件两者相等
        toc = self._toc_tbl.to_bytes()
        assert len(toc) == self._toc_len, "TOC 长度变了, 不该发生"
        out[self._toc_off:self._toc_off + self._toc_len] = toc
        return bytes(out), moved_to


def open_cpk(path):
    with open(path, "rb") as fh:
        return Cpk(fh.read())
