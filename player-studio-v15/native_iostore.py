"""UE4.26 IoStore v2 reader and deterministic writer for the V13 adapter.

Only the format present in the supplied game is accepted. Keys are read from
the user's prepared resource cache; they are never embedded in the software.
The reader follows the public CUE4Parse format definitions (Apache-2.0).
"""
from pathlib import Path
import hashlib
import struct
import zlib
import shutil

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b'-==--==--==--==-'
INV = 0xffffffff


def aes(data, key, encrypt=False):
    if len(data) % 16:
        raise ValueError('IoStore encrypted data is not block aligned')
    context = Cipher(algorithms.AES(key), modes.ECB()).encryptor() if encrypt else Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return context.update(data) + context.finalize()


def fstring(value):
    raw = value.encode('utf8') + b'\0'
    return struct.pack('<i', len(raw)) + raw


def read_string(data, offset):
    count = struct.unpack_from('<i', data, offset)[0]
    offset += 4
    if abs(count) > 1 << 20:
        raise ValueError('Invalid IoStore string')
    size = count if count >= 0 else -count * 2
    raw = data[offset:offset + size]
    if len(raw) != size:
        raise ValueError('Truncated IoStore string')
    value = raw[:-1].decode('utf8') if count > 0 else raw[:-2].decode('utf-16-le') if count < 0 else ''
    return value, offset + size


class Container:
    def __init__(self, path, key=None):
        self.path = Path(path)
        self.key = key
        b = self.path.read_bytes()
        if b[:16] != MAGIC or b[16] != 2:
            raise ValueError('Only the inspected V13 IoStore v2 layout is supported')
        self.header = b[:144]
        hsz, count, blocks, block_size, method_count, method_width, self.block, index_size, partitions = struct.unpack_from('<9I', b, 20)
        self.container_id = struct.unpack_from('<Q', b, 56)[0]
        self.flags = b[80]
        if hsz != 144 or block_size != 12 or self.flags & 4 or partitions > 1:
            raise ValueError('Unsupported IoStore header or signed container')
        if self.flags & 2 and (not key or len(key) != 32):
            raise ValueError('Prepare the original resource cache before reading this container')
        offset = hsz
        self.chunk_ids = [b[offset+i*12:offset+(i+1)*12] for i in range(count)]
        if len(set(self.chunk_ids)) != count:
            raise ValueError('Duplicate IoStore chunk IDs')
        offset += count * 12
        self.ranges = [(int.from_bytes(b[offset+i*10:offset+i*10+5], 'big'), int.from_bytes(b[offset+i*10+5:offset+(i+1)*10], 'big')) for i in range(count)]
        offset += count * 10
        self.blocks = [b[offset+i*12:offset+(i+1)*12] for i in range(blocks)]
        offset += blocks * 12
        self.methods = [b[offset+i*method_width:offset+(i+1)*method_width].rstrip(b'\0').decode() for i in range(method_count)]
        offset += method_count * method_width
        index = b[offset:offset+index_size]
        offset += index_size
        if self.flags & 2:
            index = aes(index, key)
        self.paths = {}
        if self.flags & 8:
            self._index(index)
        self.metas = b[offset:]
        if len(self.metas) != count * 33:
            raise ValueError('Unexpected V13 IoStore chunk metadata layout')
        self.by_id = {v:i for i,v in enumerate(self.chunk_ids)}

    def _index(self, b):
        self.mount, offset = read_string(b, 0)
        nd = struct.unpack_from('<I', b, offset)[0]
        offset += 4
        dirs = [struct.unpack_from('<4I', b, offset+i*16) for i in range(nd)]
        offset += nd * 16
        nf = struct.unpack_from('<I', b, offset)[0]
        offset += 4
        files = [struct.unpack_from('<3I', b, offset+i*12) for i in range(nf)]
        offset += nf * 12
        ns = struct.unpack_from('<I', b, offset)[0]
        offset += 4
        strings = []
        for _ in range(ns):
            value, offset = read_string(b, offset)
            strings.append(value)
        stack = [(0, self.mount)]
        visited = set()
        while stack:
            idx, prefix = stack.pop()
            if idx in visited:
                raise ValueError('Cyclic IoStore directory')
            visited.add(idx)
            _, child, _, item = dirs[idx]
            seen = set()
            while item != INV:
                if item in seen:
                    raise ValueError('Cyclic IoStore file list')
                seen.add(item)
                name, item, chunk = files[item]
                self.paths[prefix + strings[name]] = chunk
            while child != INV:
                stack.append((child, prefix + strings[dirs[child][0]] + '/'))
                child = dirs[child][2]

    def read_chunk(self, index):
        start, size = self.ranges[index]
        first, last = start // self.block, (start+size-1) // self.block
        out = bytearray()
        with self.path.with_suffix('.ucas').open('rb') as f:
            for i in range(first, last+1):
                b = self.blocks[i]
                at = int.from_bytes(b[:5], 'little')
                stored = int.from_bytes(b[5:8], 'little')
                original = int.from_bytes(b[8:11], 'little')
                method = b[11]
                f.seek(at)
                raw = f.read((stored+15)//16*16 if self.flags & 2 else stored)
                if self.flags & 2:
                    raw = aes(raw, self.key)
                raw = raw[:stored]
                if method:
                    if self.methods[method-1] != 'Zlib':
                        raise ValueError('Unsupported IoStore compression')
                    raw = zlib.decompress(raw)
                if len(raw) != original:
                    raise ValueError('IoStore block size mismatch')
                out.extend(raw)
        offset = start-first*self.block
        return bytes(out[offset:offset+size])

    def read(self, path):
        return self.read_chunk(self.paths[path])


def directory_index(paths, mount='../../../'):
    """Build the v2 directory tree. paths maps relative names to chunk indices."""
    strings, indices, dirs, files = [], {}, [[INV, INV, INV, INV]], []
    children = {0:{}}
    def intern(value):
        if value not in indices:
            indices[value] = len(strings)
            strings.append(value)
        return indices[value]
    for path, chunk in sorted(paths.items()):
        if path.startswith('/') or '..' in path.split('/') or '\\' in path:
            raise ValueError('Invalid output resource path')
        parts = path.split('/')
        parent = 0
        for part in parts[:-1]:
            if part not in children[parent]:
                idx = len(dirs)
                children[parent][part] = idx
                children[idx] = {}
                dirs.append([intern(part), INV, dirs[parent][1], INV])
                dirs[parent][1] = idx
            parent = children[parent][part]
        files.append([intern(parts[-1]), dirs[parent][3], chunk])
        dirs[parent][3] = len(files)-1
    return (fstring(mount)+struct.pack('<I', len(dirs))+b''.join(struct.pack('<4I', *d) for d in dirs)
            +struct.pack('<I', len(files))+b''.join(struct.pack('<3I', *f) for f in files)
            +struct.pack('<I', len(strings))+b''.join(fstring(s) for s in strings))


def write_container(path, chunks, paths, container_id, block_size=65536):
    """Write unencrypted UE4 v2 chunks, hashing every uncompressed chunk.

    Every chunk begins on a compression-block boundary. A separate container
    header chunk must be supplied by the caller. Existing containers are never
    modified. This writer deliberately has no signing/encryption bypass mode.
    """
    path = Path(path)
    if path.exists() or path.with_suffix('.ucas').exists():
        raise ValueError('Output container already exists')
    if len({cid for cid, _ in chunks}) != len(chunks) or any(len(cid) != 12 for cid,_ in chunks):
        raise ValueError('Invalid or duplicate output chunk identity')
    if any(not 0 <= n < len(chunks) for n in paths.values()):
        raise ValueError('Directory refers to missing chunk')
    blocks, ranges, metas = [], [], []
    logical = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.ucas').open('xb') as f:
        for _, raw in chunks:
            compressed = False
            ranges.append(logical.to_bytes(5, 'big')+len(raw).to_bytes(5, 'big'))
            for offset in range(0, len(raw), block_size):
                value = raw[offset:offset+block_size]
                encoded = zlib.compress(value, 6)
                method = 1
                if len(encoded) >= len(value):
                    encoded, method = value, 0
                compressed |= bool(method)
                blocks.append(f.tell().to_bytes(5, 'little')+len(encoded).to_bytes(3, 'little')+len(value).to_bytes(3, 'little')+bytes([method]))
                f.write(encoded)
            logical += ((len(raw)+block_size-1)//block_size)*block_size
            # V2 uses FIoChunkHash (32 bytes), followed by a flags byte.
            metas.append(hashlib.sha1(raw).digest()+b'\0'*12+bytes([int(compressed)]))
    index = directory_index(paths)
    header = bytearray(144)
    header[:16] = MAGIC
    header[16] = 2
    struct.pack_into('<9I', header, 20, 144, len(chunks), len(blocks), 12, 1, 32, block_size, len(index), 0)
    struct.pack_into('<Q', header, 56, container_id)
    header[80] = 1 | 8
    path.write_bytes(bytes(header)+b''.join(cid for cid,_ in chunks)+b''.join(ranges)+b''.join(blocks)+b'Zlib'+b'\0'*28+index+b''.join(metas))
    check = Container(path)
    for i, (_, raw) in enumerate(chunks):
        if check.read_chunk(i) != raw:
            raise ValueError('Generated IoStore read-back verification failed')
    return check


def package_id(name):
    from cityhash import CityHash64
    return CityHash64(name.lower().encode('utf-16-le'))


def package_header(container_id, packages):
    """eFootball UE4's 16-byte FFilePackageStoreEntry layout."""
    ids = [p['id'] for p in packages]
    entries = bytearray()
    imported = bytearray()
    for p in packages:
        imports = p.get('imports', [])
        at = len(entries)
        relative = len(packages)*16+len(imported)-(at+8) if imports else 0
        entries.extend(struct.pack('<4I', p.get('exports',1), p.get('bundles',1), len(imports), relative))
        imported.extend(b''.join(struct.pack('<Q', i) for i in imports))
    store = bytes(entries+imported)
    return (struct.pack('<QIIIQ', container_id, len(ids), 0, 8, 0xc1640000)
            +struct.pack('<I',len(ids))+b''.join(struct.pack('<Q',i) for i in ids)
            +struct.pack('<I',len(store))+store+b'\0'*8)


def package_names(raw):
    h=struct.unpack_from('<16I',raw)
    names=[];offset=h[6]
    for _ in range(h[9]//8-1):
        a,b=raw[offset:offset+2];offset+=2
        count,wide=((a&127)<<8)|b,bool(a&128)
        if wide:offset+=offset%2
        size=count*(2 if wide else 1)
        names.append(raw[offset:offset+size].decode('utf-16-le' if wide else 'utf8'));offset+=size
    return names


def export_rebindings(raw,new_name,replacements=None):
    from cityhash import CityHash64
    h=struct.unpack_from('<16I',raw);names=package_names(raw)
    changes=replacements or {};old_name=names[h[0]&0x3fffffff]
    changes={old_name:new_name,old_name.rsplit('/',1)[-1]:new_name.rsplit('/',1)[-1],**changes}
    result={}
    for at in range(h[11],h[12],72):
        old=struct.unpack_from('<Q',raw,at+56)[0]
        if old==0xffffffffffffffff:continue
        obj=names[struct.unpack_from('<I',raw,at+16)[0]&0x3fffffff]
        full=(new_name+'/'+changes.get(obj,obj)).lower()
        result[old]=(CityHash64(full.encode('utf-16-le'))&((1<<62)-1))|(2<<62)
    return result


def rename_package(raw, name, replacements=None, import_hashes=None, package_ids=None):
    """Clone an inspected UE4 IoStore package without changing its exports.

    Name batches and all affected header offsets are rebuilt; package/object
    hashes are recomputed. This is deliberately separate from mesh conversion.
    """
    from cityhash import CityHash64
    h = list(struct.unpack_from('<16I',raw))
    if h[6] != 64 or h[9] % 8 or h[9] < 16 or h[13]+h[14] > len(raw):
        raise ValueError('Unrecognized UE4 package summary')
    names, offset = [], h[6]
    for _ in range(h[9]//8-1):
        a,b = raw[offset:offset+2]
        offset += 2
        count, wide = ((a&127)<<8)|b, bool(a&128)
        if wide:
            offset += offset%2
        size = count*(2 if wide else 1)
        names.append(raw[offset:offset+size].decode('utf-16-le' if wide else 'utf8'))
        offset += size
    old_name = names[h[0]&0x3fffffff]
    basename = name.rsplit('/',1)[-1]
    old_basename = old_name.rsplit('/',1)[-1]
    changes = {old_name:name,old_basename:basename,**(replacements or {})}
    names = [changes.get(n,n) for n in names]
    batch = bytearray()
    for value in names:
        encoded = value.encode('utf8')
        if len(encoded) > 32767:
            raise ValueError('Package name is too long')
        batch.extend(len(encoded).to_bytes(2,'big')+encoded)
    names_size = len(batch)
    batch.extend(b'\0'*((-len(batch))%8))
    hashes = struct.pack('<Q',0xc1640000)+b''.join(struct.pack('<Q',CityHash64(n.lower().encode('utf8'))) for n in names)
    new_names = bytes(batch)+hashes
    old_end = h[10]
    # Preserve padding between hashes and the import map.
    new_names += b'\0'*((-(64+len(new_names)))%8)
    delta = 64+len(new_names)-old_end
    result = bytearray(raw[:64]+new_names+raw[old_end:])
    h[5] += delta
    h[7] = names_size
    h[8] = 64+len(batch)
    for index in (10,11,12,13):
        h[index] += delta
    struct.pack_into('<16I',result,0,*h)
    for at in range(h[10],h[11],8):
        old=struct.unpack_from('<Q',result,at)[0]
        if old in (import_hashes or {}):struct.pack_into('<Q',result,at,import_hashes[old])
    at=h[13];n=struct.unpack_from('<i',result,at)[0];at+=4
    for _ in range(n):
        old,arcs=struct.unpack_from('<Qi',result,at)
        if old in (package_ids or {}):struct.pack_into('<Q',result,at,package_ids[old])
        at+=12+arcs*8
    if at!=h[13]+h[14]:raise ValueError('Unrecognized original import graph')
    count = (h[12]-h[11])//72
    for i in range(count):
        at = h[11]+72*i
        cooked = struct.unpack_from('<Q',result,at)[0]
        struct.pack_into('<Q',result,at,cooked+delta)
        object_index = struct.unpack_from('<I',result,at+16)[0]&0x3fffffff
        object_name = names[object_index]
        full_name = name.lower()+'/'+object_name.lower()
        if struct.unpack_from('<Q',result,at+56)[0]!=0xffffffffffffffff:
            export_hash = (CityHash64(full_name.encode('utf-16-le'))&((1<<62)-1))|(2<<62)
            struct.pack_into('<Q',result,at+56,export_hash)
    return bytes(result), {'id':package_id(name),'exports':count,'bundles':1,'imports':[]}


def read_package_header(raw, strict=True):
    cid,count,names_size,hashes_size=struct.unpack_from('<QIII',raw)
    if names_size or hashes_size!=8 or struct.unpack_from('<Q',raw,20)[0]!=0xc1640000:
        raise ValueError('Only the inspected V13 container package store is supported')
    n=struct.unpack_from('<I',raw,28)[0]
    if count!=n:
        raise ValueError('Package store count mismatch')
    ids=struct.unpack_from('<'+str(n)+'Q',raw,32)
    size=struct.unpack_from('<I',raw,32+n*8)[0]
    start=36+n*8
    result=[]
    for i,pid in enumerate(ids):
        at=start+i*16
        exports,bundles,nimports,relative=struct.unpack_from('<4I',raw,at)
        imports=list(struct.unpack_from('<'+str(nimports)+'Q',raw,at+8+relative)) if nimports else []
        result.append({'id':pid,'exports':exports,'bundles':bundles,'imports':imports})
    if strict and raw[start+size:]!=b'\0'*8:
        raise ValueError('Unsupported package redirects or extra container metadata')
    if strict and package_header(cid,result)!=raw:
        raise ValueError('Original package store did not rebuild byte-for-byte')
    return cid,result


def append_container(source, output, additions, paths, packages, replace_indices=()):
    """Append personal packages while preserving every original resource block.

    Original encrypted/compressed UCAS bytes stay byte-identical. The container
    header is replaced by a new chunk and its old space is left untouched.
    """
    if not isinstance(source,Container):
        raise TypeError('Expected an inspected source container')
    output=Path(output)
    if output.exists() or output.with_suffix('.ucas').exists():
        raise ValueError('Output must be a new container')
    header_index=next(i for i,cid in enumerate(source.chunk_ids) if cid[11]==10)
    cid,old_packages=read_package_header(source.read_chunk(header_index))
    if cid!=source.container_id:
        raise ValueError('Container ID mismatch')
    replace_indices=set(replace_indices)
    allowed_ids={struct.unpack_from('<Q',source.chunk_ids[i])[0] for i in replace_indices}
    ids={p['id'] for p in old_packages}
    if any(p['id'] in ids and p['id'] not in allowed_ids for p in packages):
        raise ValueError('Personal resource package collides with an original package')
    replacements={p['id']:p for p in packages}
    new_header=package_header(cid,[replacements.get(p['id'],p) for p in old_packages]+[p for p in packages if p['id'] not in ids])
    chunks=list(source.chunk_ids)
    ranges=list(source.ranges)
    blocks=list(source.blocks)
    metas=[source.metas[i*33:(i+1)*33] for i in range(len(chunks))]
    if any(c in source.by_id and source.by_id[c] not in replace_indices for c,_ in additions):
        raise ValueError('Personal resource chunk collides with an original chunk')
    indices=[];next_index=len(chunks)
    for chunk_id,_ in additions:
        if chunk_id in source.by_id:indices.append(source.by_id[chunk_id])
        else:indices.append(next_index);next_index+=1
    if len(set(indices))!=len(indices):raise ValueError('Duplicate personal resource chunk')
    all_paths={p.removeprefix('../../../'):i for p,i in source.paths.items()}
    if any(p in all_paths and (all_paths[p] not in replace_indices or all_paths[p]!=indices[i]) for p,i in paths.items()):
        raise ValueError('Personal resource path collides with an original resource')
    all_paths.update({p:indices[i] for p,i in paths.items()})
    encrypted=bool(source.flags&2)
    method=source.methods.index('Zlib')+1
    logical=len(blocks)*source.block
    output.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source.path.with_suffix('.ucas'),output.with_suffix('.ucas'))
    with output.with_suffix('.ucas').open('ab') as f:
        for index,(chunk_id,raw) in [*zip(indices,additions),(header_index,(chunks[header_index],new_header))]:
            compressed=False
            physical=f.tell()
            if encrypted and physical%16:
                raise ValueError('Original encrypted UCAS is not aligned')
            for start in range(0,len(raw),source.block):
                value=raw[start:start+source.block]
                encoded=zlib.compress(value,6)
                compression=method
                if len(encoded)>=len(value):encoded,compression=value,0
                compressed|=bool(compression)
                blocks.append(f.tell().to_bytes(5,'little')+len(encoded).to_bytes(3,'little')+len(value).to_bytes(3,'little')+bytes([compression]))
                f.write(aes(encoded+b'\0'*((-len(encoded))%16),source.key,True) if encrypted else encoded)
            item=(logical,len(raw));meta=hashlib.sha1(raw).digest()+b'\0'*12+bytes([int(compressed)])
            if index==len(chunks):chunks.append(chunk_id);ranges.append(item);metas.append(meta)
            elif index==header_index or index in replace_indices:ranges[index]=item;metas[index]=meta
            else:raise ValueError('Invalid appended chunk index')
            logical+=((len(raw)+source.block-1)//source.block)*source.block
    directory=directory_index(all_paths)
    if encrypted:directory=aes(directory+b'\0'*((-len(directory))%16),source.key,True)
    h=bytearray(source.header)
    struct.pack_into('<I',h,24,len(chunks));struct.pack_into('<I',h,28,len(blocks));struct.pack_into('<I',h,48,len(directory))
    ranges_raw=b''.join(a.to_bytes(5,'big')+b.to_bytes(5,'big') for a,b in ranges)
    methods=b''.join(s.encode()+b'\0'*(32-len(s)) for s in source.methods)
    output.write_bytes(bytes(h)+b''.join(chunks)+ranges_raw+b''.join(blocks)+methods+directory+b''.join(metas))
    check=Container(output,source.key)
    for i,(_,raw) in zip(indices,additions):
        if check.read_chunk(i)!=raw:raise ValueError('Appended native package failed read-back')
    if check.read_chunk(header_index)!=new_header:raise ValueError('New package store failed read-back')
    return check
