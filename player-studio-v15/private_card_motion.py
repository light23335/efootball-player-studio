"""Private movie assets and complete front-layer routes for one project card."""
import hashlib
import struct
from pathlib import Path

from native_art import clone_group
from native_iostore import package_names, fstring
from native_movie import remux_usm


def movie_packages(assets, name, raw):
    """Clone the inspected 30fps F02 source, including its private YUV textures."""
    _, info = remux_usm(raw)
    return movie_metadata_packages(assets,name,info)


def movie_metadata_packages(assets,name,info):
    """Rebuild inspected movie metadata without transcoding the source video."""
    if not __import__('re').fullmatch(r'[0-9a-z_]{14}',name):
        raise ValueError('独立视频资源名称无效')
    if any(type(info.get(key))is not int for key in('width','height','frames'))or not(1<=info['width']<=4096 and 1<=info['height']<=4096 and 1<=info['frames']<=1800):
        raise ValueError('独立视频元数据无效')
    if info['duration'] != info['frames'] / 30:
        raise ValueError('独立卡面实验目前要求30fps')
    template = '0501_256_f02_v'
    movie = '/Game/Movies/PlayerCard/'
    tex = '/Game/Assets/ui/Data/Thumbnail/Player/'
    source = movie + template
    data, meta = assets.get(source)
    # FilePath is serialized as FString, outside the package name map.
    old = b'PlayerCard/' + template.encode() + b'.usm\0'
    new = b'PlayerCard/' + name.encode() + b'.usm\0'
    if len(old) != len(new) or data.count(old) != 1:
        raise ValueError('独立视频路径模板发生变化')
    data = data.replace(old, new)
    data = data.replace(struct.pack('<II', 182, 256), struct.pack('<II', info['width'], info['height']))
    names = package_names(data)
    for key in ('TotalFrames',):
        marker = struct.pack('<II', names.index(key), 0)
        positions = [i for i in range(len(data)) if data.startswith(marker, i)
                     and data[i + 8:i + 16] == struct.pack('<II', names.index('IntProperty'), 0)]
        if len(positions) != 1:
            raise ValueError('视频总帧数属性不唯一')
        updated = bytearray(data)
        struct.pack_into('<I', updated, positions[0] + 25, info['frames'])
        data = bytes(updated)
    group = {source: (data, meta)}
    renames = {source: movie + name}
    texture_path = tex + 'Variation2022/' + template
    texture, metadata = assets.get(texture_path)
    texture_names=package_names(texture)
    resized=bytearray(texture)
    for prop,full,half in [('SizeX',info['width'],(info['width']+1)//2),
                           ('SizeY',info['height'],(info['height']+1)//2)]:
        marker=struct.pack('<II',texture_names.index(prop),0)
        found=[]
        for at in range(len(texture)-29):
            if texture.startswith(marker,at) and texture[at+8:at+16]==struct.pack('<II',texture_names.index('IntProperty'),0):
                found.append(at+25)
        if len(found)!=3:raise ValueError('独立视频YUV纹理尺寸布局不同')
        for i,at in enumerate(found):struct.pack_into('<I',resized,at,half if i<2 else full)
    texture=bytes(resized)
    # Clone the movie and all component textures in one dependency group.
    group[texture_path] = (texture, metadata)
    renames[texture_path] = tex + 'Variation2022/' + name
    output = clone_group(group, renames)
    # Native details and acquisition UI request separate root/Variation2022 paths.
    root_group = {source: (data, meta), texture_path: (texture, metadata)}
    root_names = {source: movie + name, texture_path: tex + name}
    output.extend(x for x in clone_group(root_group, root_names) if x[0] != movie + name)
    return output


def prepare(project, binding, library):
    config = (project.get('native_card') or {}).get('custom_motion')
    if not config:
        return [], {}, None
    assets = library.face_assets()
    uid = project['package_id']
    files, packages, names = {}, [], []
    for role, dimensions in [('large', (182, 256)), ('mini', (128, 128))]:
        asset = config[role]['asset_id']
        if not __import__('re').fullmatch(r'[a-f0-9]{64}\.usm', asset):
            raise ValueError('独立动画资源编号无效')
        raw = (library.store.root / 'assets' / asset).read_bytes()
        if hashlib.sha256(raw).hexdigest() + '.usm' != asset:
            raise ValueError('独立动画文件校验失败')
        _, info = remux_usm(raw)
        if (info['width'], info['height']) != dimensions:
            raise ValueError('独立大小卡动画尺寸不匹配')
        # 14 chars matches the source's serialized FilePath length.
        name = 'c' + hashlib.sha256((uid + role + asset).encode()).hexdigest()[:11] + '_v'
        names.append(name[:-2])
        files['PlayerCard/' + name + '.usm'] = raw
        packages.extend(movie_packages(assets, name, raw))
    front = [''] * 10
    front[1] = names[0]
    front[6] = binding['asset_key'] + 'f'
    binding['front_names'] = front
    binding['private_movie_textures'] = True
    binding['thumbnail_names'] = [binding['asset_key'] + '_b', names[1] if project['appearance'].get('thumbnail_animation',True) else '', '', binding['asset_key'] + '_m', '', '']
    return packages, files, {'private': True, 'background_slot': 'M02', 'front_slots': front,
                              'original_decorations_removed': True, 'project': uid}


def write_movie_pak(path, movies):
    """A small uncompressed legacy PAK, accepted by UE4's existing PAK loader."""
    entries = []
    with Path(path).open('xb') as out:
        for name, raw in sorted(movies.items()):
            offset = out.tell()
            entry = struct.pack('<QQQI', offset, len(raw), len(raw), 0) + hashlib.sha1(raw).digest() + struct.pack('<BI', 0, 0)
            out.write(bytes(8) + entry[8:])
            out.write(raw)
            entries.append((name, entry))
        index = fstring('../../../PesMobile/Content/Movies/') + struct.pack('<I', len(entries))
        index += b''.join(fstring(name) + entry for name, entry in entries)
        offset = out.tell()
        out.write(index)
        out.write(struct.pack('<IIQQ', 0x5a6f12e1, 3, offset, len(index)) + hashlib.sha1(index).digest())


def read_movie_pak(raw,allow_native=False):
    from native_iostore import read_string
    if len(raw)<44:raise ValueError('独立动画包不完整')
    magic,version,offset,size=struct.unpack_from('<IIQQ',raw,len(raw)-44)
    if magic!=0x5a6f12e1 or version!=3 or offset+size!=len(raw)-44:raise ValueError('独立动画包格式不同')
    index=raw[offset:offset+size]
    if hashlib.sha1(index).digest()!=raw[-20:]:raise ValueError('独立动画包索引校验失败')
    mount,pos=read_string(index,0)
    if mount!='../../../PesMobile/Content/Movies/':raise ValueError('独立动画包路径不同')
    count=struct.unpack_from('<I',index,pos)[0];pos+=4
    if count>20000:raise ValueError('独立动画包数量过多')
    movies={}
    for _ in range(count):
        name,pos=read_string(index,pos)
        private=__import__('re').fullmatch(r'PlayerCard/c[0-9a-f]{11}_v\.usm',name)
        native=allow_native and __import__('re').fullmatch(r'PlayerCard/[0-9]{4}_[0-9]{1,4}_[fm][0-9]{2}_v\.usm',name)
        if not(private or native)or name in movies:raise ValueError('独立动画包文件名无效')
        off,size,unpacked,method=struct.unpack_from('<QQQI',index,pos)
        digest=index[pos+28:pos+48];flags,block=struct.unpack_from('<BI',index,pos+48);pos+=53
        if method or flags or block or size!=unpacked or off+53+size>offset:raise ValueError('独立动画包条目无效')
        payload=raw[off+53:off+53+size]
        if hashlib.sha1(payload).digest()!=digest or payload[:4]!=b'CRID':raise ValueError('独立动画文件校验失败')
        movies[name]=payload
    if pos!=len(index):raise ValueError('独立动画包索引尾部异常')
    return movies
