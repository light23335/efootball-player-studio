"""Remove the stock portrait UV offset in the private MobileIcon material.

V17 stores GLES shader source as inline LZ4 blocks. Keep every binding, vertex
shader and shader permutation; change only the six verified pixel shaders'
portrait UV transform. The shader hashes remain sorted and frozen resource
indices are remapped with them. Stock packages are never passed to an output.
"""
import hashlib,struct


def lz4_block(data,expected):
    data=memoryview(data);out=bytearray();p=0
    def length(n):
        nonlocal p
        if n==15:
            while True:
                if p>=len(data):raise ValueError('小头像着色器压缩长度无效')
                v=data[p];p+=1;n+=v
                if v!=255:break
        return n
    while p<len(data):
        token=data[p];p+=1;n=length(token>>4)
        if p+n>len(data) or len(out)+n>expected:raise ValueError('小头像着色器文字范围无效')
        out.extend(data[p:p+n]);p+=n
        if p==len(data):break
        if p+2>len(data):raise ValueError('小头像着色器压缩偏移无效')
        offset=struct.unpack_from('<H',data,p)[0];p+=2;n=length(token&15)+4
        if not offset or offset>len(out) or len(out)+n>expected:raise ValueError('小头像着色器压缩引用无效')
        for _ in range(n):out.append(out[-offset])
    if len(out)!=expected:raise ValueError('小头像着色器解压长度不同')
    return bytes(out)


def _compress(data):
    """Small standard LZ4 block encoder; no codec DLL on PC or Android."""
    out=bytearray();table={};anchor=0;p=0;limit=len(data)-12
    def extra(n):
        while n>=255:out.append(255);n-=255
        out.append(n)
    while p<=limit:
        key=data[p:p+4];previous=table.get(key);table[key]=p
        if previous is None or p-previous>65535:
            p+=1;continue
        end=p+4
        while end<len(data)-5 and data[end]==data[previous+end-p]:end+=1
        literals=p-anchor;match=end-p-4
        out.append((min(literals,15)<<4)|min(match,15))
        if literals>=15:extra(literals-15)
        out.extend(data[anchor:p]);out.extend(struct.pack('<H',p-previous))
        if match>=15:extra(match-15)
        old=p;p=end;anchor=p
        for pos in range(old+1,p):table[data[pos:pos+4]]=pos
    literals=len(data)-anchor;out.append(min(literals,15)<<4)
    if literals>=15:extra(literals-15)
    out.extend(data[anchor:]);return bytes(out)


def patch_private_shader(raw,profile):
    from card_motion import _exports
    cfg=profile['inline_shader_uv'];out=bytearray(raw)
    if hashlib.sha256(raw).hexdigest()!=profile['assets_sha256'][cfg['material']]:
        raise ValueError('小头像人物着色器版本不同，未修改原版材质')
    at=cfg['code_offset'];original_hash=bytes.fromhex(cfg['resource_hash'])
    if raw[at:at+20]!=original_hash:raise ValueError('小头像着色器代码入口不同')
    count=struct.unpack_from('<I',raw,at+20)[0];hash_start=at+24
    hashes=[raw[hash_start+i*20:hash_start+(i+1)*20]for i in range(count)]
    if [h.hex()for h in hashes]!=cfg['shader_hashes'] or hashes!=sorted(hashes):
        raise ValueError('小头像着色器排列不同')
    p=hash_start+20*count
    if struct.unpack_from('<I',raw,p)[0]!=count:raise ValueError('小头像着色器条目数量不同')
    entries_start=p+4;p=entries_start;rows=[];changed=[]
    old_offset=b'vec2(2.265625e-01,3.125000e-02)'
    old_scale=b'vec2(9.375000e-01,9.375000e-01)'
    for i,oldhash in enumerate(hashes):
        n=struct.unpack_from('<I',raw,p)[0];packed=raw[p+4:p+4+n]
        size,frequency=struct.unpack_from('<IB',raw,p+4+n);p+=9+n
        code=lz4_block(packed,size)if n!=size else packed
        if hashlib.sha256(code).hexdigest()!=cfg['uncompressed_sha256'][i]:
            raise ValueError('小头像着色器内容不同')
        if frequency==3:
            if code.count(old_offset)!=1 or code.count(old_scale)!=1:
                raise ValueError('小头像人物裁切坐标不同')
            code=code.replace(old_offset,b'vec2(0.000000e+00,0.000000e+00)')
            code=code.replace(old_scale,b'vec2(1.000000e+00,1.000000e+00)')
            packed=_compress(code)
            if len(packed)>=len(code):packed=code
            if (lz4_block(packed,size)if len(packed)!=size else packed)!=code:
                raise ValueError('小头像着色器重编码校验失败')
            newhash=hashlib.sha1(code).digest();changed.append(i)
        elif frequency==0:
            newhash=oldhash
        else:raise ValueError('小头像着色器阶段不同')
        rows.append((newhash,i,struct.pack('<I',len(packed))+packed+struct.pack('<IB',size,frequency)))
    if changed!=cfg['pixel_indices'] or p!=len(raw):raise ValueError('小头像材质资源边界不同')
    rows.sort(key=lambda row:row[0]);newhashes=b''.join(row[0]for row in rows)
    remap={old:new for new,(_,old,_)in enumerate(rows)}
    for offset,old in cfg['frozen_resource_indices']:
        if struct.unpack_from('<I',raw,offset)[0]!=old:raise ValueError('小头像着色器引用不同')
        struct.pack_into('<I',out,offset,remap[old])
    resource_hash=hashlib.sha1(newhashes).digest()
    out[at:at+20]=resource_hash;out[hash_start:hash_start+20*count]=newhashes
    new_entries=b''.join(row[2]for row in rows);out[entries_start:p]=new_entries
    growth=len(out)-len(raw)
    proxy=cfg['proxy_num_bytes_offset'];oldsize=struct.unpack_from('<I',raw,proxy)[0]
    if oldsize!=len(raw)-(proxy+4):raise ValueError('小头像材质代理长度不同')
    struct.pack_into('<I',out,proxy,oldsize+growth)
    for row in _exports(raw):
        if row['actual']<=at<row['actual']+row['size']:
            struct.pack_into('<Q',out,row['at']+8,row['size']+growth)
        elif row['actual']>at:struct.pack_into('<Q',out,row['at'],row['offset']+growth)
    # All caches containing code or uniforms get a deterministic private key.
    for key in ('cooked_shader_map_id_hash','shader_content_hash'):
        old=bytes.fromhex(profile[key]if key in profile else cfg[key])
        if bytes(out).count(old)!=1:raise ValueError('小头像私有着色器标识不同')
        out=bytearray(bytes(out).replace(old,hashlib.sha1(b'PlayerStudio/mini-uv/v5\0'+old+resource_hash).digest()))
    return bytes(out),{'portrait_uv_identity':True,'pixel_shader_variants':len(changed),
                       'vertex_shaders_preserved':count-len(changed),
                       'private_shader_resource_hash':resource_hash.hex(),
                       'shader_resource_indices_remapped':True}
