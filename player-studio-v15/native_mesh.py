"""Strict reader/writer for V13's inline cooked skeletal mesh render data.

The format is matched against CUE4Parse's UE4.26 serializers. Unsupported
cloth, skin formats and streamed bulk data are rejected before modification.
"""
import struct


class Reader:
    def __init__(self,data,at=0):self.data=data;self.at=at
    def read(self,fmt):
        values=struct.unpack_from('<'+fmt,self.data,self.at);self.at+=struct.calcsize('<'+fmt)
        return values[0] if len(values)==1 else values
    def bytes(self,size):
        if size<0 or self.at+size>len(self.data):raise ValueError('Truncated cooked mesh')
        value=self.data[self.at:self.at+size];self.at+=size;return value
    def array(self,width):
        count=self.read('I')
        if count>2000000:raise ValueError('Cooked mesh array is too large')
        return self.bytes(count*width),count
    def bulk(self,width):
        size,count=self.read('II')
        if size!=width or count>2000000:raise ValueError(f'Unexpected cooked mesh bulk array at {self.at-8}: item {size}, count {count}, expected item {width}')
        return self.bytes(width*count),count


def read_lod(raw,offset):
    r=Reader(raw,offset)
    flags=r.bytes(2);cooked_out,inlined=r.read('II')
    if flags!=b'\x01\x01' or cooked_out or inlined!=1:raise ValueError('Only inspected inline V13 LODs are supported')
    required,nrequired=r.array(2)
    section_count=r.read('I')
    if not 1<=section_count<=32:raise ValueError('Unexpected skeletal mesh section count')
    sections=[]
    for _ in range(section_count):
        begin=r.at;strip=r.bytes(2)
        material,base_index,triangles,recompute,mask,shadow,base_vertex=r.read('hiiiBII')
        cloth,ncloth=r.array(64)
        if ncloth:raise ValueError('Cloth sections require a separate native adapter')
        bones,nbones=r.array(2);nvertices,max_influences=r.read('II')
        cloth_asset=r.read('h');clothing=r.bytes(20)
        if strip!=b'\x01\x01' or cloth_asset!=-1 or not 1<=max_influences<=8:raise ValueError('Unsupported skeletal mesh section format')
        disabled=r.read('I')
        sections.append({'start':begin,'end':r.at,'material':material,'base_index':base_index,'triangles':triangles,
                         'base_vertex':base_vertex,'vertices':nvertices,'bones':list(struct.unpack('<'+'H'*nbones,bones)),
                         'influences':max_influences,'raw':raw[begin:r.at]})
    active,nactive=r.array(2)
    buffers_size=r.read('I');buffer_start=r.at
    stream_flags=r.bytes(2)
    if stream_flags!=b'\x01\x01':raise ValueError('Unsupported mesh stream flags')
    index_width=r.read('B')
    if index_width not in (2,4):raise ValueError('Unsupported mesh index format')
    indices,index_count=r.bulk(index_width)
    position_start=r.at
    stride,nvertices=r.read('II')
    if stride!=12:raise ValueError('Only full-precision native mesh positions are supported')
    positions,position_count=r.bulk(12)
    if position_count!=nvertices:raise ValueError('Mesh vertex count mismatch')
    static_start=r.at
    static_flags=r.bytes(2);nuv,static_n,full_uv,high_tangent=r.read('IIII')
    if static_flags!=b'\x01\x00' or static_n!=nvertices or nuv>8:raise ValueError('Unsupported static mesh vertex layout')
    tangents,ntangent=r.bulk(16 if high_tangent else 8)
    uv_data,nuvdata=r.bulk(8 if full_uv else 4)
    if ntangent!=nvertices or nuvdata!=nvertices*nuv:raise ValueError('Mesh tangent/UV count mismatch')
    skin_start=r.at
    skin_flags=r.bytes(2);variable,max_influences,nbone_values,skin_n,use16=r.read('IIIII')
    if skin_flags!=b'\x01\x00' or variable or max_influences!=4 or use16 or skin_n!=nvertices or nbone_values!=skin_n*4:
        raise ValueError('Unsupported native skin-weight layout')
    skin,nskin=r.bulk(1)
    if nskin!=nvertices*8:raise ValueError('Native skin-weight size mismatch')
    lookup_flags=r.bytes(2);nlookup=r.read('I');lookup,nlookup_data=r.bulk(4)
    if lookup_flags!=b'\x01\x00' or nlookup or nlookup_data:raise ValueError('Unsupported skin lookup table')
    color_start=r.at
    # bHasVertexColors is false on e.g. the original Fabinho head: UE omits
    # the entire colour buffer, leaving just the profile-count word. Validate
    # the enclosing stream length before deciding, rather than reading the
    # next LOD's header as vertex colours.
    if buffer_start+buffers_size-r.at==4:colors=b''
    else:
        color_flags=r.bytes(2);color_stride,color_n=r.read('II');colors,ncolors=r.bulk(4)
        if color_flags!=b'\x01\x00' or color_stride!=4 or color_n!=nvertices or ncolors!=nvertices:raise ValueError('Unsupported native mesh colors')
    profiles=r.read('I')
    if profiles:raise ValueError('Native skin-weight profiles require a separate adapter')
    if buffers_size!=r.at-buffer_start:raise ValueError('Skeletal render buffer size mismatch')
    for section in sections:
        if section['base_index']+section['triangles']*3>index_count or section['base_vertex']+section['vertices']>nvertices:
            raise ValueError('Native section references invalid render data')
    return {'start':offset,'end':r.at,'required':required,'nrequired':nrequired,'sections':sections,'active':active,'nactive':nactive,
            'vertices':nvertices,'indices':indices,'index_width':index_width,'positions':positions,'tangents':tangents,
            'uv_data':uv_data,'nuv':nuv,'full_uv':bool(full_uv),'high_tangent':bool(high_tangent),'skin':skin,'colors':colors,
            'position_start':position_start,'static_start':static_start,'skin_start':skin_start,'color_start':color_start,
            'buffer_start':buffer_start,'buffers_size':buffers_size}


def find_lods(raw):
    marker=b'\x01\x01\x00\x00\x00\x00\x01\x00\x00\x00'
    offset=0;candidates=[]
    while (start:=raw.find(marker,offset))>=0:
        offset=start+1
        if start<4:continue
        count=struct.unpack_from('<I',raw,start-4)[0]
        if not 1<=count<=8:continue
        try:
            lods=[];at=start
            for _ in range(count):
                lod=read_lod(raw,at);lods.append(lod);at=lod['end']
            candidates.append(lods)
        except (ValueError,struct.error):pass
    if len(candidates)!=1:raise ValueError('Could not uniquely identify inspected native skeletal LODs')
    return candidates[0]


def head_arrays(glb,bone_count,adjustments=None,bone_remap=None):
    import numpy as np
    primitive=glb.head();attrs=primitive['attributes']
    positions=glb.read(attrs['POSITION']).astype(float)
    normals=glb.read(attrs['NORMAL']).astype(float)
    uv=glb.read(attrs['TEXCOORD_0']).astype(float)
    joints=glb.read(attrs['JOINTS_0']).astype(int)
    weights=glb.read(attrs['WEIGHTS_0']).astype(float)
    changes=adjustments or {}
    positions=changes.get('positions',positions);normals=changes.get('normals',normals)
    joints=changes.get('joints',joints).copy();weights=changes.get('weights',weights).copy()
    faces=glb.read(primitive['indices']).reshape(-1,3).astype(int)
    count=len(positions)
    if not 100<=count<=500000 or faces.size>3000000 or faces.min()<0 or faces.max()>=count:
        raise ValueError('自制头模顶点或三角形数量不受支持')
    if any(not np.isfinite(a).all() for a in (positions,normals,uv,weights)) or (weights<0).any():
        raise ValueError('头模含无效坐标或蒙皮权重')
    if joints.shape!=(count,4) or weights.shape!=(count,4) or joints.min()<0 or joints.max()>=bone_count:
        raise ValueError('头模需要每顶点最多 4 项有效骨骼权重')
    if bone_remap is not None:
        joints=np.asarray(bone_remap,dtype=int)[joints]
        # Several facial influences can collapse to the same head bone in a
        # match LOD. Merge them before quantising the four skin influences.
        for column in range(1,4):
            for previous in range(column):
                same=joints[:,column]==joints[:,previous]
                weights[same,previous]+=weights[same,column];weights[same,column]=0
    totals=weights.sum(axis=1)
    if (totals<.99).any() or (totals>1.01).any():raise ValueError('脸模蒙皮权重未归一化')
    weights/=totals[:,None]
    used=sorted(set(joints[weights>1e-7].tolist()))
    if len(used)>75:raise ValueError('头模使用超过 75 个骨骼，需要分割为多个移动端网格分段')
    remap={bone:i for i,bone in enumerate(used)}
    skin=glb.doc['skins'][0];node_to_bone={node:i for i,node in enumerate(skin['joints'])}
    parents={child:i for i,node in enumerate(glb.doc['nodes']) for child in node.get('children',[])}
    required=set(used)
    for bone in used:
        node=skin['joints'][bone];visited=set()
        while node in parents and node not in visited:
            visited.add(node);node=parents[node]
            if node in node_to_bone:required.add(node_to_bone[node])
    mapped=np.zeros_like(joints,dtype=np.uint8)
    for bone,index in remap.items():mapped[joints==bone]=index
    packed_weights=np.rint(weights*255).astype(np.int16)
    packed_weights[np.arange(count),weights.argmax(axis=1)]+=255-packed_weights.sum(axis=1)
    skin=np.concatenate((mapped,packed_weights.astype(np.uint8)),axis=1)
    # CUE4Parse maps X,Z,Y in metres and keeps triangle order. Swapping the
    # indices again would invert every surface and make faces render inside out.
    positions=(positions[:,[0,2,1]]*100).astype('<f4')
    normal=normals[:,[0,2,1]]
    normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
    axis=np.zeros_like(normal);axis[:,2]=1;axis[np.abs(normal[:,2])>.9]=[0,1,0]
    tangent=np.cross(axis,normal);tangent/=np.maximum(np.linalg.norm(tangent,axis=1,keepdims=True),1e-12)
    packed=np.concatenate((np.column_stack((tangent,np.zeros(count))),np.column_stack((normal,np.ones(count)))),axis=1)
    # UE4.26 IncreaseNormalPrecision stores signed bytes (CUE applies XOR).
    packed=(np.rint((packed+1)*127.5).clip(0,255).astype(np.uint8)^128)
    return {'positions':positions,'normals':normal,'uv':uv.astype('<f4'),'faces':faces,
            'tangents':packed,'skin':skin,'bones':used,'required_bones':sorted(required),'vertices':count,'triangles':len(faces)}


def make_lod(template,head):
    import numpy as np
    count=head['vertices'];indices=head['faces']
    width=2 if count<=65535 else 4
    index_data=indices.astype('<u2' if width==2 else '<u4').tobytes()
    def array(data,width):return struct.pack('<I',len(data)//width)+data
    def bulk(data,width):return struct.pack('<II',width,len(data)//width)+data
    # Preserve the carrier's active-bone contract. replace_head has already
    # folded influences on stripped facial bones onto retained ancestors.
    required=sorted(set(np.frombuffer(template['required'],dtype='<u2').tolist())|set(head['required_bones']))
    active=sorted(set(np.frombuffer(template['active'],dtype='<u2').tolist())|set(head['required_bones']))
    required_data=np.asarray(required,dtype='<u2').tobytes();active_data=np.asarray(active,dtype='<u2').tobytes()
    bone_map=b''.join(struct.pack('<H',b) for b in head['bones'])
    section=(b'\x01\x01'+struct.pack('<hiiiBII',0,0,head['triangles'],0,1,1,0)
             +struct.pack('<I',0)+array(bone_map,2)+struct.pack('<IIh',count,4,-1)
             +b'\0'*16+struct.pack('<iI',-1,0))
    uv_count=max(1,template['nuv'])
    uv=np.repeat(head['uv'][:,None,:],uv_count,axis=1).astype('<f4').tobytes()
    stream=(b'\x01\x01'+bytes([width])+bulk(index_data,width)
            +struct.pack('<II',12,count)+bulk(head['positions'].tobytes(),12)
            +b'\x01\x00'+struct.pack('<IIII',uv_count,count,1,0)
            +bulk(head['tangents'].tobytes(),8)+bulk(uv,8)
            +b'\x01\x00'+struct.pack('<IIIII',0,4,count*4,count,0)
            +bulk(head['skin'].tobytes(),1)+b'\x01\x00'+struct.pack('<III',0,4,0)
            +b'\x01\x00'+struct.pack('<II',4,count)+bulk(b'\xff'*count*4,4)
            +struct.pack('<I',0))
    result=(b'\x01\x01'+struct.pack('<II',0,1)+array(required_data,2)
            +struct.pack('<I',1)+section+array(active_data,2)+struct.pack('<I',len(stream))+stream)
    parsed=read_lod(result,0)
    if parsed['end']!=len(result) or parsed['vertices']!=count or parsed['skin']!=head['skin'].tobytes():
        raise ValueError('Generated skeletal mesh failed structural read-back')
    if not set(head['required_bones'])<=set(required)&set(active):
        raise ValueError('导出模型的骨骼依赖未完整写入精度档位')
    return result


def retained_bone_map(glb,active):
    """Fold stripped influences onto the nearest retained skeleton ancestor.

    V13's match animation only supplies the carrier LOD's original active
    bones. Adding names to render data cannot create missing facial matrices.
    """
    skin=glb.doc['skins'][0];nodes=skin['joints'];index={node:i for i,node in enumerate(nodes)}
    parents={child:i for i,node in enumerate(glb.doc['nodes']) for child in node.get('children',[])}
    active=set(active);result=[]
    for bone,node in enumerate(nodes):
        seen=set()
        while bone not in active:
            if node not in parents or node in seen:
                raise ValueError('原版模型精度档位缺少可用的父骨骼')
            seen.add(node);node=parents[node];bone=index.get(node,-1)
        result.append(bone)
    return result


def custom_face_bone_map(reference,active):
    """Keep custom geometry neutral under the carrier's facial performance.

    Matching skeleton names/bind matrices does not prove that a replacement
    mouth, eyelid or eyeball follows the carrier's anatomical weighting. These
    skf_ influences must follow the head until such per-face work is verified.
    Head/neck/spine animation and each native LOD's retained-bone contract stay.
    This adapter is only called for custom heads, never original game faces.
    """
    names=[reference.doc['nodes'][n].get('name','') for n in reference.doc['skins'][0]['joints']]
    if names.count('sk_head')!=1:raise ValueError('自制头模缺少唯一的原版头部骨骼')
    retained=retained_bone_map(reference,active);head=retained[names.index('sk_head')]
    return [head if name.startswith('skf_') else retained[i] for i,name in enumerate(names)]


def replace_head(raw,glb,reference,metadata,neck_seam=True,head_vertical_cm=0,preserve_expression=True,binding=None):
    import numpy as np
    from native_glb import verify_skeleton
    bones=verify_skeleton(glb,reference)
    adjustments={};neck_report={'status':'disabled'}
    if neck_seam:
        from native_neck import fit
        adjustments,neck_report=fit(glb,reference,head_vertical_cm,binding)
    elif head_vertical_cm or any(any(v) for v in (binding or {}).values()):
        from head_placement import place_without_extension
        adjustments,neck_report=place_without_extension(glb,reference,head_vertical_cm,binding)
    lods=find_lods(raw);head=head_arrays(glb,bones,adjustments)
    original_bounds=metadata['ImportedBounds']
    original_values=[original_bounds[group][axis] for group in ('Origin','BoxExtent') for axis in ('X','Y','Z')]+[original_bounds['SphereRadius']]
    bounds_bytes=struct.pack('<7f',*original_values)
    bounds_at=raw.find(bounds_bytes,0,lods[0]['start'])
    if bounds_at<0 or raw.find(bounds_bytes,bounds_at+1,lods[0]['start'])>=0:
        raise ValueError('Could not uniquely locate original mesh bounds')
    lo=head['positions'].min(axis=0)-1;hi=head['positions'].max(axis=0)+1
    center=(lo+hi)/2;extent=(hi-lo)/2
    updated=bytearray(raw)
    struct.pack_into('<7f',updated,bounds_at,*center,*extent,float(np.linalg.norm(extent)))
    blocks=[];bone_reports=[]
    for level,lod in enumerate(lods):
        active=np.frombuffer(lod['active'],dtype='<u2').tolist()
        mapping=custom_face_bone_map(reference,active) if preserve_expression else retained_bone_map(reference,active)
        lod_head=head_arrays(glb,bones,adjustments,mapping)
        if not set(lod_head['bones'])<=set(active):raise ValueError('比赛档位仍引用了已裁去的骨骼')
        blocks.append(make_lod(lod,lod_head))
        bone_reports.append({'lod':level,'used_bones':len(lod_head['bones']),
                             'folded_influences':[b for b in head['bones'] if mapping[b]!=b],
                             'uses_original_active_bones_only':True})
    result=bytearray(updated[:lods[0]['start']]+b''.join(blocks)+updated[lods[-1]['end']:])
    delta=len(result)-len(raw)
    h=struct.unpack_from('<16I',result)
    # The cooked render buffers are inside the final SkeletalMesh export.
    # Earlier user-data exports and every byte of the original skeleton stay.
    export_count=(h[12]-h[11])//72
    containing=[]
    for i in range(export_count):
        at=h[11]+i*72;size=struct.unpack_from('<Q',result,at+8)[0]
        if size>=lods[-1]['end']-lods[0]['start']:containing.append(at)
    if len(containing)!=1:raise ValueError('Cannot uniquely identify skeletal mesh export size')
    at=containing[0]+8
    struct.pack_into('<Q',result,at,struct.unpack_from('<Q',result,at)[0]+delta)
    check=find_lods(result)
    if len(check)!=len(lods) or any(lod['vertices']!=head['vertices'] for lod in check):
        raise ValueError('Native mesh LOD verification failed')
    return bytes(result),{'vertices':head['vertices'],'triangles':head['triangles'],'lods':len(lods),
                          'bones':bones,'used_bones':len(head['bones']),'native_skin_weights':True,
                          'original_skeleton_preserved':True,'lod_geometry':'same mesh at both original LOD slots',
                          'all_lods_include_used_bones_and_parents':True,
                          'facial_animation':'custom-neutral-face; head-neck-spine motion preserved' if preserve_expression else 'imported facial weights; native LOD retention applies',
                          'carrier_facial_weights_removed':bool(preserve_expression),
                          'lod_skinning':bone_reports,
                          'neck_seam':neck_report,'in_game_tested':False}
