"""Inspected UE4.26 inline static meshes for stadium decorations, not stadiums.

The byte contract follows CUE4Parse's FStaticMeshLODResources serializers.
Only complete, bounded inline buffers are accepted; no skeletal conversion.
"""
import struct
from native_mesh import Reader


def read_index(r):
    wide=r.read('I')
    if wide not in(0,1):raise ValueError('静态模型索引类型无效')
    data,count=r.bulk(1);expand=r.read('I');width=4 if wide else 2
    if count%width or expand not in(0,1):raise ValueError('静态模型索引流不完整')
    return {'width':width,'data':data,'expand':expand}


def read_lod(raw,offset):
    r=Reader(raw,offset);flags=r.bytes(2)
    if flags!=b'\x01\x09':raise ValueError('仅支持已核对的移动端静态模型档位')
    count=r.read('I')
    if not 1<=count<=32:raise ValueError('静态模型材质分段数量无效')
    sections=[r.read('9I')for _ in range(count)]
    if any(s[5]not in(0,1)or s[6]not in(0,1)or s[7]not in(0,1)or s[8]not in(0,1)for s in sections):raise ValueError('静态模型分段布局改变')
    deviation=r.read('f');cooked,inline=r.read('II')
    if cooked or inline!=1:raise ValueError('静态模型不是完整内联档位')
    stream_start=r.at
    if r.bytes(2)!=b'\x01\x09':raise ValueError('静态模型缓冲布局改变')
    position_at=r.at;stride,n=r.read('II');positions,np=r.bulk(12)
    if stride!=12 or n!=np or not 1<=n<=500000:raise ValueError('静态模型顶点流无效')
    if r.bytes(2)!=b'\x01\x00':raise ValueError('静态模型 UV 布局改变')
    nuv,nv,full,high=r.read('4I')
    if not 1<=nuv<=8 or nv!=n or full not in(0,1)or high not in(0,1):raise ValueError('静态模型 UV/法线规格无效')
    tangents,nt=r.bulk(16 if high else 8);uv,ntuv=r.bulk(8 if full else 4)
    if nt!=n or ntuv!=n*nuv:raise ValueError('静态模型 UV/法线数量不一致')
    if r.bytes(2)!=b'\x01\x00':raise ValueError('静态模型顶点颜色布局改变')
    cs,cn=r.read('II');colors=b''
    if cn:
        colors,nc=r.bulk(4)
        if cs!=4 or cn!=n or nc!=n:raise ValueError('静态模型颜色流无效')
    elif cs not in(0,4):raise ValueError('静态模型颜色步长无效')
    indices=[read_index(r)for _ in range(4)]
    for _ in range(count+1):
        r.array(4);r.array(4);r.read('f') # area-weighted sampling, not gameplay collision
    stream_end=r.at;sizes=r.read('3I')
    gpu=sum(map(len,(positions,tangents,uv,colors)))+sum(len(i['data'])for i in indices)
    if tuple(sizes)!=(gpu,len(indices[2]['data']),len(indices[1]['data'])+len(indices[3]['data'])):raise ValueError('静态模型缓冲长度不一致')
    idx=indices[0];values=struct.unpack('<'+('I'if idx['width']==4 else'H')*(len(idx['data'])//idx['width']),idx['data'])
    if not values or max(values)>=n or any(s[1]+s[2]*3>len(values)or s[3]>s[4]or s[4]>=n for s in sections):raise ValueError('静态模型分段引用无效')
    return dict(start=offset,end=r.at,flags=flags,sections=sections,deviation=deviation,vertices=n,positions=positions,
                position_at=position_at,nuv=nuv,full_uv=full,high_tangent=high,tangents=tangents,uv=uv,colors=colors,indices=indices,sizes=sizes)


def find_lods(raw):
    marker=b'\x01\x09';at=0;sets=[]
    while(at:=raw.find(marker,at))>=0:
        start=at;at+=1
        if start<4:continue
        count=struct.unpack_from('<I',raw,start-4)[0]
        if not 1<=count<=8:continue
        try:
            lods=[];pos=start
            for _ in range(count):
                lod=read_lod(raw,pos);lods.append(lod);pos=lod['end']
            if raw[pos]!=count:continue # native NumInlinedLODs byte
            sets.append(lods)
        except (ValueError,struct.error,IndexError):continue
    if len(sets)!=1:raise ValueError('无法唯一读取原生静态模型档位')
    return sets[0]


def make_lod(template,positions,normals,uv,faces):
    import numpy as np
    p=np.asarray(positions,dtype='<f4');n=np.asarray(normals,dtype=float);t=np.asarray(uv,dtype='<f4');f=np.asarray(faces,dtype=int)
    count=len(p)
    if p.shape!=(count,3)or n.shape!=(count,3)or t.shape!=(count,2)or f.ndim!=2 or f.shape[1]!=3 or not 3<=count<=200000 or not 1<=len(f)<=300000:
        raise ValueError('场景模型需要完整的顶点、法线、UV 和三角形；上限 20 万顶点、30 万三角形')
    if not all(np.isfinite(x).all()for x in(p,n,t))or f.min()<0 or f.max()>=count:raise ValueError('场景模型含无效数据')
    length=np.linalg.norm(n,axis=1)
    if(length<1e-6).any():raise ValueError('场景模型法线不能为空')
    n/=length[:,None];axis=np.zeros_like(n);axis[:,2]=1;axis[np.abs(n[:,2])>.9]=[0,1,0]
    tangent=np.cross(axis,n);tangent/=np.linalg.norm(tangent,axis=1)[:,None]
    packed=np.concatenate((np.column_stack((tangent,np.zeros(count))),np.column_stack((n,np.ones(count)))),axis=1)
    packed=(np.rint((packed+1)*127.5).clip(0,255).astype(np.uint8)^128).tobytes()
    def bulk(data,width):return struct.pack('<II',width,len(data)//width)+data
    width=2 if count<=65535 else 4
    def index(values):return struct.pack('<I',width==4)+bulk(np.asarray(values,dtype='<u2'if width==2 else'<u4').tobytes(),1)+struct.pack('<I',0)
    forward=f.reshape(-1);reverse=f[:,::-1].reshape(-1)
    idx=[forward,reverse,forward,reverse]
    coords=np.repeat(t[:,None,:],template['nuv'],axis=1).astype('<f4').tobytes()
    stream=(b'\x01\x09'+struct.pack('<II',12,count)+bulk(p.tobytes(),12)+
            b'\x01\x00'+struct.pack('<4I',template['nuv'],count,1,0)+bulk(packed,8)+bulk(coords,8)+
            b'\x01\x00'+struct.pack('<II',0,0)+b''.join(index(x)for x in idx)+bytes(24))
    gpu=len(p.tobytes())+len(packed)+len(coords)+sum(len(x)*width for x in idx)
    section=struct.pack('<9I',0,0,len(f),0,count-1,0,1,0,1)
    encoded=(b'\x01\x09'+struct.pack('<I',1)+section+struct.pack('<fII',0,0,1)+stream+
             struct.pack('<3I',gpu,len(forward)*width,2*len(forward)*width))
    check=read_lod(encoded,0)
    if check['vertices']!=count or check['end']!=len(encoded)or check['positions']!=p.tobytes():raise ValueError('静态模型写回校验失败')
    return encoded


def replace(raw,positions,normals,uv,faces):
    import numpy as np
    from native_iostore import package_names
    lods=find_lods(raw);p=np.asarray(positions,dtype='<f4');origin=(p.max(axis=0)+p.min(axis=0))/2;extent=(p.max(axis=0)-p.min(axis=0))/2
    radius=float(np.linalg.norm(p-origin,axis=1).max());bounds=struct.pack('<7f',*origin,*extent,radius)
    result=bytearray(raw);names=package_names(raw);h=struct.unpack_from('<16I',raw)
    # ExtendedBounds is a tagged struct, with one FGuid and an optional property GUID.
    tag=struct.pack('<II',names.index('ExtendedBounds'),0);locations=[];at=h[13]+h[14]
    while(at:=raw.find(tag,at,lods[0]['start']))>=0:
        if struct.unpack_from('<I',raw,at+8)[0]==names.index('StructProperty')and struct.unpack_from('<I',raw,at+16)[0]in(28,159):locations.append(at)
        at+=8
    if len(locations)!=1:raise ValueError('无法核对场景模型包围盒')
    prop=locations[0];start=prop+49+(16 if raw[prop+48]else 0)
    size=struct.unpack_from('<I',raw,prop+16)[0]
    if size==28:
        old_bounds=raw[start:start+28];result[start:start+28]=bounds
    else:
        parts=[]
        for key,value,width,header in(('Origin',bounds[:12],12,49),('BoxExtent',bounds[12:24],12,49),('SphereRadius',bounds[24:],4,25)):
            field=raw.find(struct.pack('<II',names.index(key),0),start,start+size)
            if field<0 or struct.unpack_from('<I',raw,field+16)[0]!=width:raise ValueError('静态模型包围盒字段改变')
            at=field+header+(16 if raw[field+header-1]else 0)
            parts.append(raw[at:at+width]);result[at:at+width]=value
        old_bounds=b''.join(parts)
    render_at=raw.find(old_bounds,lods[-1]['end'])
    if render_at<0 or raw.find(old_bounds,render_at+1)>=0:raise ValueError('无法唯一核对场景渲染包围盒')
    result[render_at:render_at+28]=bounds
    blocks=b''.join(make_lod(l,p,normals,uv,faces)for l in lods)
    result=bytearray(result[:lods[0]['start']]+blocks+result[lods[-1]['end']:]);delta=len(result)-len(raw)
    mesh_name=names[h[0]&0x3fffffff].rsplit('/',1)[-1]
    rows=[at for at in range(h[11],h[12],72)if names[struct.unpack_from('<I',raw,at+16)[0]&0x3fffffff]==mesh_name]
    if len(rows)!=1:raise ValueError('无法唯一核对静态模型导出项')
    target=rows[0];size=struct.unpack_from('<Q',result,target+8)[0]
    if size<lods[-1]['end']-lods[0]['start']:raise ValueError('静态模型导出范围不完整')
    struct.pack_into('<Q',result,target+8,size+delta)
    # These carriers place the StaticMesh last; other exports must stay before it.
    serial=struct.unpack_from('<Q',raw,target)[0]
    if any(struct.unpack_from('<Q',raw,at)[0]>serial for at in range(h[11],h[12],72)):raise ValueError('静态模型载体导出顺序改变')
    check=find_lods(result)
    if len(check)!=len(lods)or any(l['positions']!=p.tobytes()for l in check):raise ValueError('场景模型最终回读失败')
    return bytes(result),{'vertices':len(p),'triangles':len(faces),'lods':len(lods),'bounds_cm':[*origin.tolist(),*extent.tolist(),radius],
                          'collision':'disabled in generated sections; native decoration component has NoCollision','in_game_tested':False}
