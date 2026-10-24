"""Rewrap native USM/IVF VP9 packets as WebM without decoding any frame.

Container references: FFmpeg libavformat/usmdec.c and the WebM/Matroska
element specifications. Encrypted, non-VP9 and separate alpha streams stop.
"""
import hashlib
import struct


def convert_movie(source,destination,ffmpeg=None):
    """Preserve VP9 packets; losslessly transcode the original MPEG-2 clip."""
    from pathlib import Path
    import subprocess
    source,destination=Path(source),Path(destination)
    raw=source.read_bytes()
    stream=extract_ivf(raw)
    if stream.startswith(b'DKIF'):
        result,meta=remux_usm(raw);destination.write_bytes(result);return meta
    if not stream.startswith(b'\0\0\x01\xb3'):
        raise ValueError('此原版动画不是已适配的 VP9 或 MPEG-2 视频')
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise ValueError('此原版卡面使用 MPEG-2，需要随软件提供的视频转换工具')
    count=stream.count(b'\0\0\x01\0')
    if not 1<=count<=18000:raise ValueError('原版 MPEG-2 帧数未通过检查')
    source_hash=hashlib.sha256(raw).hexdigest()
    marker=destination.with_suffix('.conversion.json')
    try:
        import json
        cached=json.loads(marker.read_text(encoding='utf8'))
        if cached['original_usm_sha256']==source_hash and destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest()==cached['webm_sha256']:
            return cached
    except (OSError,ValueError,KeyError):pass
    p=subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','mpegvideo','-i','pipe:0','-an',
                      '-c:v','libvpx-vp9','-lossless','1','-pix_fmt','yuv420p','-deadline','good','-cpu-used','4',
                      '-f','webm','-y',str(destination)],input=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode or not destination.is_file():raise ValueError('原版 MPEG-2 动画转换失败')
    meta={'codec':'VP9','source_codec':'MPEG-2','frames':count,'reencoded':True,'lossless':True,
          'original_usm_sha256':source_hash,'webm_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
    marker.write_text(json.dumps(meta),encoding='utf8');return meta


def extract_ivf(data):
    if data[:4] != b'CRID' or len(data) > 128 * 1024 * 1024:
        raise ValueError('不是支持的原版 USM 动画')
    pos, pieces = 0, []
    while pos < len(data):
        if pos + 32 > len(data):
            raise ValueError('原版动画块不完整')
        size = struct.unpack_from('>I', data, pos + 4)[0]
        end = pos + 8 + size
        offset, padding = data[pos+9], struct.unpack_from('>H', data, pos+10)[0]
        if size < 24 or end > len(data) or offset < 24 or offset + padding > size:
            raise ValueError('原版动画块长度无效')
        tag = data[pos:pos+4]
        if tag in (b'@ALP', b'@SFA'):
            raise ValueError('此动画的独立透明或音频轨道尚未适配')
        if tag == b'@SFV' and data[pos+15] == 0:
            if data[pos+12] != 0:
                raise ValueError('此动画有多条视频轨道，尚未适配')
            pieces.append(data[pos+8+offset:end-padding])
        pos = end
    return b''.join(pieces)


def ivf_packets(data):
    if len(data) < 32 or data[:4] != b'DKIF':
        raise ValueError('原版动画不是未加密的 IVF 视频')
    version, header, codec, width, height, rate, scale, count, _ = struct.unpack_from('<HH4sHHIIII', data, 4)
    if version != 0 or header != 32 or codec != b'VP90' or not 0 < width <= 4096 or not 0 < height <= 4096 or not 0 < rate / max(scale, 1) <= 300 or scale == 0:
        raise ValueError('此原版视频编码或尺寸尚未适配')
    pos, packets, previous = 32, [], -1
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError('IVF 帧头不完整')
        size, timestamp = struct.unpack_from('<IQ', data, pos)
        pos += 12
        if not size or pos + size > len(data) or timestamp <= previous:
            raise ValueError('IVF 帧长度或时间戳无效')
        frame = data[pos:pos+size]
        # All supported clips use VP9 profile 0. Inspect the uncompressed frame
        # header only for WebM keyframe flags; the compressed data stays intact.
        if frame[0] >> 6 != 2 or (frame[0] >> 4) & 3:
            raise ValueError('原版 VP9 profile 尚未适配')
        key = not (frame[0] & 12)
        packets.append((timestamp, frame, key))
        previous = timestamp
        pos += size
    if not packets or len(packets) != count or not packets[0][2] or (packets[-1][0]+1)*scale/rate > 60:
        raise ValueError('原版动画帧数或时长未通过核对')
    return {'width': width, 'height': height, 'rate': rate, 'scale': scale, 'packets': packets}


def _uint(value):
    return value.to_bytes(max(1, (value.bit_length()+7)//8), 'big')


def _size(value):
    for count in range(1, 9):
        if value < (1 << (7*count)) - 1:
            return (value | (1 << (7*count))).to_bytes(count, 'big')
    raise ValueError('WebM 元素过大')


def _element(tag, payload):
    return _uint(tag) + _size(len(payload)) + payload


def _number(tag, value):
    return _element(tag, _uint(value))


def remux_usm(data):
    ivf = extract_ivf(data)
    video = ivf_packets(ivf)
    width, height, rate, scale, packets = [video[k] for k in ('width', 'height', 'rate', 'scale', 'packets')]
    duration = (packets[-1][0]+1)*scale/rate
    ebml = _element(0x1A45DFA3, _number(0x4286, 1)+_number(0x42F7, 1)+_number(0x42F2, 4)+_number(0x42F3, 8)+_element(0x4282, b'webm')+_number(0x4287, 4)+_number(0x4285, 2))
    info = _element(0x1549A966, _number(0x2AD7B1, 1000000)+_element(0x4489, struct.pack('>d', duration*1000))+_element(0x4D80, b'Player Studio')+_element(0x5741, b'Native VP9 packet remux'))
    track = _element(0xAE, _number(0xD7, 1)+_number(0x73C5, 1)+_number(0x83, 1)+_number(0x9C, 0)+_element(0x86, b'V_VP9')+_number(0x23E383, round(1e9*scale/rate))+_element(0xE0, _number(0xB0, width)+_number(0xBA, height)))
    tracks = _element(0x1654AE6B, track)
    clusters, cues, blocks, start = [], [], [], 0
    position = len(info) + len(tracks)

    def flush():
        nonlocal blocks, position
        if not blocks:
            return
        cluster = _element(0x1F43B675, _number(0xE7, start)+b''.join(blocks))
        cues.append(_element(0xBB, _number(0xB3, start)+_element(0xB7, _number(0xF7, 1)+_number(0xF1, position))))
        clusters.append(cluster)
        position += len(cluster)
        blocks = []

    for timestamp, frame, key in packets:
        millis = round(timestamp*scale/rate*1000)
        if key and blocks:
            flush()
            start = millis
        if millis-start > 32767:
            raise ValueError('原版动画关键帧间隔未适配')
        blocks.append(_element(0xA3, b'\x81'+struct.pack('>hB', millis-start, 0x80 if key else 0)+frame))
    flush()
    result = ebml + _element(0x18538067, info+tracks+b''.join(clusters)+_element(0x1C53BB6B, b''.join(cues)))
    return result, {'width': width, 'height': height, 'frames': len(packets), 'duration': duration,
                    'codec': 'VP9', 'frame_payload_sha256': hashlib.sha256(b''.join(frame for _, frame, _ in packets)).hexdigest(),
                    'original_usm_sha256': hashlib.sha256(data).hexdigest(), 'reencoded': False}
