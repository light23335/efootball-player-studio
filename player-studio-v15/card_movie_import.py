"""Experimental opaque VP9 card movies; no changes to live projects or resources.

Muxing uses separately installed WannaCRI 0.3.3 (MIT). This adapter supplies
validated IVF packets directly, so an external ffprobe is not required.
"""
from pathlib import Path
import struct
import subprocess

from native_movie import ivf_packets, extract_ivf, remux_usm
from native_cpk import Utf


def _fix_mux_headers(data):
    """Correct WannaCRI 0.3.3's byte-count fields to match original USMs.

    Its metadata_size is a keyframe count and root filesize includes an extra
    0x800. Numeric in-place edits leave all stream and seek offsets intact.
    """
    raw = bytearray(data)
    chunks = []
    pos = 0
    while pos < len(raw):
        size = 8 + struct.unpack_from('>I', raw, pos + 4)[0]
        chunks.append((pos, size, raw[pos:pos + 4], raw[pos + 15]))
        pos += size
    if pos != len(raw):
        raise ValueError('USM 块范围无效')
    metadata_size = sum(size for _, size, tag, kind in chunks if tag == b'@SFV' and kind == 3)
    ixsize = max(size - 8 for _, size, tag, kind in chunks if tag == b'@SFV' and kind == 0)
    for pos, size, tag, kind in chunks:
        if kind != 1:
            continue
        start = pos + 8 + raw[pos + 9]
        length = 8 + struct.unpack_from('>I', raw, start + 4)[0]
        table = Utf(bytes(raw[start:start + length]))
        if tag == b'CRID':
            table.set(0, 'filesize', len(raw))
        elif tag == b'@SFV':
            table.set(0, 'metadata_size', metadata_size)
            table.set(0, 'ixsize', ixsize)
        raw[start:start + length] = table.bytes()
    return bytes(raw)


def encode(source, destination, ffmpeg, width, height, fps, seconds, crop_x=0, crop_y=0):
    """Center crop an input to a template's opaque, silent video contract."""
    if (width, height) not in ((182, 256), (128, 128)):
        raise ValueError('实验版仅支持 182×256 大卡、128×128 小卡')
    if fps not in (24, 30, 60) or not 0 < seconds <= 30:
        raise ValueError('帧率或时长超出实验范围')
    dest = Path(destination)
    if dest.exists():
        raise ValueError('输出已存在，请选择新路径')
    frames = round(seconds * fps)
    if type(crop_x) not in (int,float) or type(crop_y) not in (int,float) or not -100<=crop_x<=100 or not -100<=crop_y<=100:
        raise ValueError('视频裁切位置应在 -100 至 100 之间')
    x=(crop_x+100)/200; y=(crop_y+100)/200
    crop = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:(iw-ow)*{x}:(ih-oh)*{y},setsar=1,fps={fps}'
    # Loop short input clips; an explicit frame count bounds both decoding and output.
    cmd = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin',
           '-stream_loop', '-1', '-i', str(source), '-an', '-vf', crop,
           '-frames:v', str(frames), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p',
           '-b:v', '0', '-crf', '28', '-g', str(fps), '-lag-in-frames', '0',
           '-auto-alt-ref', '0', '-deadline', 'good', '-cpu-used', '4', '-f', 'ivf', '-n', str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    video = ivf_packets(dest.read_bytes())
    if len(video['packets']) != frames or (video['width'], video['height']) != (width, height):
        raise ValueError('编码结果的帧数或尺寸不匹配')
    return video


def mux_ivf(source, destination):
    from wannacri.usm import Usm
    from wannacri.usm.media.video import GenericVideo
    from wannacri.usm.media.tools import create_video_crid_page, create_video_header_page
    from wannacri.usm.types import ElementType
    dest = Path(destination)
    if dest.exists() or dest.with_suffix('.webm').exists():
        raise ValueError('USM 或预览视频已存在，请选择新路径')
    raw = Path(source).read_bytes()
    info = ivf_packets(raw)
    packets = info['packets']
    if any(t != i for i, (t, _, _) in enumerate(packets)):
        raise ValueError('仅支持连续等间隔 IVF 帧')
    fps = info['rate'] / info['scale']
    duration = len(packets) / fps
    sizes = [len(frame) + 12 + (32 if i == 0 else 0) for i, (_, frame, _) in enumerate(packets)]
    maximum = max(sizes)
    crid = create_video_crid_page(Path(source).name, len(raw), maximum, 0,
                                  round(len(raw) * 8 / duration), 16777984)
    header = create_video_header_page(len(packets), sum(k for _, _, k in packets),
                                     fps, 24 + (maximum + 31) // 32 * 32, 9, 0, info)
    # These fields are also present in the game's original VP9 headers.
    for name in ('mpeg_profile', 'mpeg_level'):
        header.update(name, ElementType.I8, 0)

    def stream():
        pos = 0
        for size, (_, _, key) in zip(sizes, packets):
            yield raw[pos:pos + size], key
            pos += size
        if pos != len(raw):
            raise ValueError('IVF 分包不完整')

    video = GenericVideo(stream, crid, header, len(packets))
    with dest.open('xb') as out:
        for chunk in Usm([video], version=16777984).stream():
            out.write(chunk)
    encoded = _fix_mux_headers(dest.read_bytes())
    dest.write_bytes(encoded)
    if extract_ivf(encoded) != raw:
        raise ValueError('USM 回读与原 IVF 视频帧不同')
    webm, report = remux_usm(encoded)
    dest.with_suffix('.webm').write_bytes(webm)
    report['fps'] = fps
    report['in_game_tested'] = False
    return report
