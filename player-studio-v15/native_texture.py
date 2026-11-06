"""Read the cooked platform stream, independently of stale UE name-map entries."""
import ctypes
import io
from pathlib import Path
import re
import struct

TEXTURE_DECODER_REVISION = 'cooked-platform-textures-v1'
_FORMAT = re.compile(rb'PF_[A-Za-z0-9_]+\x00')
_MAX_BULK = 128 * 1024 * 1024


def cooked_mip(raw, bulk_loader=None):
    """Return the first serialized cooked mip; never infer its format from names.

    bulk_loader receives .ubulk or .uptnl only. A candidate must have matching
    dimensions, string length, mip header and bounded bulk metadata before it
    can be selected. Pixel bytes are never scanned for another format marker.
    """
    if len(raw) < 64:
        raise ValueError('原版纹理包头不完整')
    header = struct.unpack_from('<16I', raw)
    start = header[13] + header[14]
    if start > len(raw):
        raise ValueError('原版纹理导出范围无效')
    candidates = []
    for match in _FORMAT.finditer(raw, start, min(len(raw), start + 8192)):
        at = match.start()
        if at < start + 16:
            continue
        width, height, slices, length = struct.unpack_from('<4I', raw, at - 16)
        if not (1 <= width <= 8192 and 1 <= height <= 8192
                and slices == 1 and length == len(match.group())):
            continue
        pos = match.end()
        if pos + 16 > len(raw):
            continue
        first, count, cooked, flags = struct.unpack_from('<4I', raw, pos)
        if not (1 <= count <= 16 and cooked == 1):
            continue
        pos += 16
        wide = bool(flags & 0x2000)
        descriptor_size = 24 if wide else 16
        if pos + descriptor_size > len(raw):
            continue
        size, stored, offset = struct.unpack_from('<QQq' if wide else '<IIq', raw, pos)
        pos += descriptor_size
        if not (0 < size <= _MAX_BULK and size == stored):
            continue
        if flags & 0x40:
            dimensions_at = pos + size
            suffix = None
        elif flags & 0x100:
            dimensions_at = pos
            suffix = '.uptnl' if flags & 0x800 else '.ubulk'
        else:
            continue
        if dimensions_at + 12 > len(raw):
            continue
        mip_width, mip_height, depth = struct.unpack_from('<3I', raw, dimensions_at)
        if not (1 <= mip_width <= width and 1 <= mip_height <= height and depth == 1):
            continue
        fmt = match.group()[:-1].decode('ascii')
        # The V18/V19 hair streams are 16-byte ETC2 RGBA blocks, despite an
        # obsolete PF_ETC2_RGB name-map entry. Check the byte count as well.
        block_bytes = {'PF_ETC2_RGB': 8, 'PF_ETC2_RGBA': 16,
                       'PF_ETC2_RGBA1': 8, 'PF_DXT1': 8,
                       'PF_DXT5': 16, 'PF_BC5': 16, 'PF_BC7': 16}.get(fmt)
        if block_bytes and size != ((mip_width + 3) // 4) * ((mip_height + 3) // 4) * block_bytes:
            continue
        candidates.append(dict(format=fmt, width=mip_width, height=mip_height,
                               size=size, offset=offset, position=pos, suffix=suffix))
        # Bulk bytes can contain arbitrary strings; only inspect the header.
        if suffix is None:
            break
    if len(candidates) != 1:
        raise ValueError('无法唯一识别原版纹理的实际平台数据')
    result = candidates[0]
    if result['suffix'] is None:
        data = raw[result['position']:result['position'] + result['size']]
    else:
        if bulk_loader is None:
            raise ValueError('原版纹理需要外部 bulk 数据：' + result['suffix'])
        bulk = bulk_loader(result['suffix'])
        offset, size = result['offset'], result['size']
        if offset < 0 or offset + size > len(bulk):
            raise ValueError('原版纹理 bulk 数据不完整：' + result['suffix'])
        data = bulk[offset:offset + size]
    if len(data) != result['size']:
        raise ValueError('原版纹理 bulk 数据不完整')
    return dict(format=result['format'], width=result['width'],
                height=result['height'], data=data, storage=result['suffix'] or 'inline')


def desktop_etc2_png(mip, native_folder):
    """Use the shipped Detex codec with the verified cooked pixel format."""
    from PIL import Image

    class Texture(ctypes.Structure):
        _fields_ = [('format', ctypes.c_uint32), ('data', ctypes.c_void_p),
                    ('width', ctypes.c_int), ('height', ctypes.c_int),
                    ('width_in_blocks', ctypes.c_int), ('height_in_blocks', ctypes.c_int)]

    fmt = mip['format']
    if fmt not in ('PF_ETC2_RGB', 'PF_ETC2_RGBA'):
        raise ValueError('桌面原生纹理解码格式不受支持：' + fmt)
    width, height = mip['width'], mip['height']
    lib = ctypes.CDLL(str(Path(native_folder) / 'Detex.dll'))
    fn = lib.detexDecompressTextureLinear
    fn.argtypes = [ctypes.POINTER(Texture), ctypes.c_void_p, ctypes.c_uint32]
    fn.restype = ctypes.c_bool
    rgba = fmt == 'PF_ETC2_RGBA'
    source = ctypes.create_string_buffer(mip['data'])
    output = ctypes.create_string_buffer(width * height * 4)
    codec = ((15 if rgba else 13) << 24) | (0x800000 if rgba else 0) | (0x334 if rgba else 0x320)
    texture = Texture(codec, ctypes.addressof(source), width, height,
                      (width + 3) // 4, (height + 3) // 4)
    if not fn(ctypes.byref(texture), output, 0x334):
        raise ValueError('原版 ETC2 纹理解码失败')
    png = io.BytesIO()
    Image.frombytes('RGBA', (width, height), output.raw).save(png, format='PNG')
    return png.getvalue()
