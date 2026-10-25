"""Keep native unique arm/leg textures with the exact selected face family.

The game formats T_<face key>_ArmLeg_D separately from the head mesh. A cloned
head's bHasUniqueArm flag is insufficient without the corresponding texture
and its external IoStore bulk chunks. Pixel blocks and mip levels stay native.
"""
import hashlib
import re
import struct
from native_iostore import package_names,rename_package,package_id

PREFIX='/Game/Assets/character/RealFace/'
REVISION='native-armleg-family-and-bulk-v1'


def face_body_source(assets,project):
    """Keep a copied player's body even when their head is replaced by a GLB."""
    from native_models import person_keys,resolve_face
    source=(project.get('model') or {}).get('appearance_source_id') or (project.get('source_player') or {}).get('id')
    if not source:return None
    keys=set(person_keys(source));rows=[]
    for path in assets.files:
        name=path.rsplit('/',1)[-1].removesuffix('.uasset')
        match=re.fullmatch(r'SK_(\d+)(?:(?:ep|lg|hi|sp)\d+v\d+)?_Face',name)
        if path.endswith('.uasset') and match and match[1] in keys:
            rows.append({'name':name,'path':path})
    selected,proof=resolve_face(rows,source)
    if selected is None:return None
    raw,_,_=assets.face(selected['path'])
    return raw,selected['path'],proof


def _body_properties(raw):
    names=package_names(raw);h=struct.unpack_from('<16I',raw)
    base=h[13]+h[14];first=struct.unpack_from('<Q',raw,h[11])[0];delta=first-base
    matches=[]
    for at in range(h[11],h[12],72):
        if names[struct.unpack_from('<I',raw,at+16)[0]&0x3fffffff]=='PesFaceAssetDataMobile':matches.append(at)
    if len(matches)!=1:raise ValueError('脸模身体外观数据对象不唯一')
    export=matches[0];cooked,size=struct.unpack_from('<QQ',raw,export);start=cooked-delta;end=start+size
    if not base<=start<end<=len(raw):raise ValueError('脸模身体外观数据范围无效')
    fields=[];pos=start
    for _ in range(1024):
        begin=pos;ident,number=struct.unpack_from('<2I',raw,pos);pos+=8
        if ident>=len(names) or number:raise ValueError('脸模身体属性名称未适配')
        name=names[ident]
        if name=='None':return names,export,start,end,fields,begin
        kind_id,number,length,index=struct.unpack_from('<4I',raw,pos);pos+=16
        if kind_id>=len(names) or number or index>100000:raise ValueError('脸模身体属性布局未适配')
        kind=names[kind_id];value=None
        if kind=='StructProperty':pos+=24
        elif kind=='BoolProperty':value=bool(raw[pos]);pos+=1
        elif kind in ('ByteProperty','EnumProperty','ArrayProperty','SetProperty'):pos+=8
        elif kind=='MapProperty':pos+=16
        guid=raw[pos];pos+=1
        if guid==1:pos+=16
        elif guid!=0:raise ValueError('脸模身体属性 GUID 未适配')
        if kind=='IntProperty' and length==4:value=struct.unpack_from('<i',raw,pos)[0]
        pos+=length
        if pos>end:raise ValueError('脸模身体属性数据不完整')
        fields.append((name,kind,value,begin,pos))
    raise ValueError('脸模身体属性过多')


def transfer_body_settings(target,source,model,resources,source_id):
    """Transfer only native skin/unique-arm settings, preserving custom geometry."""
    from native_appearance import profile
    source_fields=_body_properties(source)[4]
    values={name:(kind,value) for name,kind,value,_,_ in source_fields if name in ('SkinColor','bHasUniqueArm')}
    baseline=profile(resources,source_id) if source_id is not None else None
    tone=model.get('skin_tone')
    if tone is not None and (baseline is None or tone!=(baseline['skin_tone'] or 1)
            or model.get('skin_tone_edited') and baseline['skin_tone']==0):values['SkinColor']=('IntProperty',tone)
    missing={n for n in values if n not in package_names(target)}
    if missing:
        names=package_names(target);h=struct.unpack_from('<16I',target)
        target,_=rename_package(target,names[h[0]&0x3fffffff],extra_names=sorted(missing))
    names,export,start,end,fields,terminator=_body_properties(target);parts=[];written=set()
    def encode(name):
        if name not in values:return b''
        kind,value=values[name]
        if name not in names or kind not in names:raise ValueError('自制头模载体缺少原生身体属性名称')
        if kind=='BoolProperty':return struct.pack('<6I2B',names.index(name),0,names.index(kind),0,0,0,int(value),0)
        if kind=='IntProperty' and type(value) is int and 0<=value<=6:
            return struct.pack('<6IBi',names.index(name),0,names.index(kind),0,4,0,0,value)
        raise ValueError('原生身体属性值未适配')
    for name,kind,value,a,b in fields:
        if name in ('SkinColor','bHasUniqueArm'):parts.append(encode(name));written.add(name)
        else:parts.append(target[a:b])
    for name in ('SkinColor','bHasUniqueArm'):
        if name not in written:parts.append(encode(name))
    parts.append(target[terminator:end]);body=b''.join(parts);delta=len(body)-(end-start)
    out=bytearray(target[:start]+body+target[end:]);h=struct.unpack_from('<16I',out)
    for at in range(h[11],h[12],72):
        if at==export:struct.pack_into('<Q',out,at+8,len(body))
        elif struct.unpack_from('<Q',out,at)[0]>struct.unpack_from('<Q',out,export)[0]:
            struct.pack_into('<Q',out,at,struct.unpack_from('<Q',out,at)[0]+delta)
    result=bytes(out)
    check={name:(kind,value) for name,kind,value,_,_ in _body_properties(result)[4] if name in ('SkinColor','bHasUniqueArm')}
    if check!=values:raise ValueError('自制头模身体属性写入后校验失败')
    return result


def unique_arm(raw):
    names=package_names(raw)
    if 'bHasUniqueArm' not in names or 'BoolProperty' not in names:return False
    h=struct.unpack_from('<16I',raw)
    tag=struct.pack('<6I',names.index('bHasUniqueArm'),0,names.index('BoolProperty'),0,0,0)
    at=raw.find(tag,h[13]+h[14])
    if at<0:return False
    if raw.find(tag,at+1)>=0 or at+26>len(raw) or raw[at+24] not in (0,1) or raw[at+25]!=0:
        raise ValueError('原版脸模的独立手臂属性布局未适配')
    return bool(raw[at+24])


def texture_mips(raw,bulk=None):
    """Bounded parse of every native 2-D mip, including optional bulk data."""
    bulk=bulk or {};h=struct.unpack_from('<16I',raw);names=package_names(raw)
    formats=[n for n in names if n.startswith('PF_')]
    if len(formats)!=1:raise ValueError('纹身纹理的像素格式不唯一')
    fmt=formats[0];at=raw.find(fmt.encode()+b'\0',h[13]+h[14])
    if at<24 or raw.find(fmt.encode()+b'\0',at+1)>=0:raise ValueError('纹身纹理的平台数据未适配')
    width,height,slices,length=struct.unpack_from('<4I',raw,at-16)
    if not 1<=width<=8192 or not 1<=height<=8192 or slices!=1 or length!=len(fmt)+1:
        raise ValueError('纹身纹理的尺寸未适配')
    pos=at+length;first,count=struct.unpack_from('<2I',raw,pos);pos+=8
    if not 1<=count<=16 or first>=count:raise ValueError('纹身纹理的 mip 数量未适配')
    mips=[]
    for _ in range(count):
        cooked,flags=struct.unpack_from('<2I',raw,pos);pos+=8
        if cooked!=1:raise ValueError('纹身纹理包含未烘焙 mip')
        wide=bool(flags&0x2000);size,stored,offset=struct.unpack_from('<QQq' if wide else '<IIq',raw,pos)
        offset_at=pos+(16 if wide else 8);pos+=24 if wide else 16
        if not 0<size<=128*1024*1024 or size!=stored:raise ValueError('纹身纹理 bulk 长度未适配')
        if flags&0x40:
            pixels=raw[pos:pos+size];pos+=size;suffix='inline'
        elif flags&0x100:
            suffix='.uptnl' if flags&0x800 else '.ubulk';data=bulk.get(suffix)
            if data is None or offset<0 or offset+size>len(data):
                raise ValueError('纹身纹理缺少完整的 '+suffix+' 数据')
            pixels=data[offset:offset+size]
        else:raise ValueError('纹身纹理的 bulk 存储方式未适配')
        if len(pixels)!=size:raise ValueError('纹身纹理 mip 数据不完整')
        w,hh,depth=struct.unpack_from('<3I',raw,pos);pos+=12
        if not 1<=w<=width or not 1<=hh<=height or depth!=1:raise ValueError('纹身纹理 mip 尺寸无效')
        mips.append({'width':w,'height':hh,'bytes':size,'storage':suffix,
                     'sha256':hashlib.sha256(pixels).hexdigest(),'offset_at':offset_at,'offset':offset})
    return {'format':fmt,'width':width,'height':height,'mips':mips,'skip_offset_at':at-24}


def compile_body(assets,head,head_path,asset_key):
    report={'revision':REVISION,'unique_arm':unique_arm(head),'source':None,'mips_preserved':False}
    if not report['unique_arm']:return [],report
    base=head_path.rsplit('/',1)[-1].removesuffix('.uasset')
    match=re.fullmatch(r'SK_(\d+(?:(?:ep|lg|hi|sp)\d+v\d+)?)_Face',base)
    if not match:raise ValueError('无法确认原生纹身对应的脸模版本')
    family=match[1]
    def exists(f):return '../../../PesMobile/Content/Assets/character/RealFace/T_'+f+'_ArmLeg_D.uasset' in assets.files
    if not exists(family):
        # Older DIY exports renamed only the head; its original material refs
        # still identify the exact family. Never substitute a different age.
        references={m[1] for n in package_names(head)
                    if (m:=re.fullmatch(r'(?:.*/)?MI_(\d+(?:(?:ep|lg|hi|sp)\d+v\d+)?)_Head_.+',n))}
        available={f for f in references if exists(f)}
        if len(available)!=1:raise ValueError('此脸模需要独立纹身纹理，但当前资源缺少对应版本：'+family)
        family=available.pop()
    source=PREFIX+'T_'+family+'_ArmLeg_D';target=PREFIX+'T_'+str(asset_key)+'_ArmLeg_D'
    raw,meta=assets.get(source);bulk={};external=[]
    for suffix,kind in (('.ubulk',3),('.uptnl',4)):
        path='../../../PesMobile/Content/'+source[6:]+suffix
        if path not in assets.files:continue
        container,index=assets.files[path];cid=container.chunk_ids[index]
        if cid[:8]!=struct.pack('<Q',package_id(source)) or cid[11]!=kind:
            raise ValueError('纹身纹理的外部 chunk 身份不一致')
        data=container.read_chunk(index);bulk[suffix]=data
        external.append({'suffix':suffix,'chunk_id':struct.pack('<Q',package_id(target))+cid[8:],'data':data})
    before=texture_mips(raw,bulk)
    encoded,newmeta=rename_package(raw,target);delta=len(encoded)-len(raw)
    encoded=bytearray(encoded)
    for mip in before['mips']:
        if mip['storage']=='inline':struct.pack_into('<q',encoded,mip['offset_at']+delta,mip['offset']+delta)
    skip=before['skip_offset_at'];value=struct.unpack_from('<q',raw,skip)[0]
    struct.pack_into('<q',encoded,skip+delta,value+delta)
    encoded=bytes(encoded);after=texture_mips(encoded,bulk)
    signature=lambda p:[{k:m[k] for k in ('width','height','bytes','storage','sha256')} for m in p['mips']]
    if before['format']!=after['format'] or signature(before)!=signature(after):
        raise ValueError('纹身纹理克隆后像素或 mip 发生变化')
    newmeta.update(imports=meta['imports'],bundles=meta['bundles'],external_chunks=external)
    report.update(source=source,target=target,source_family=family,mips_preserved=True,
                  format=before['format'],mips=signature(before),external_chunks=len(external))
    return [(target,encoded,newmeta)],report


def container_parts(art):
    """Keep package-store entries separate from their external bulk chunks."""
    additions=[];paths={};packages=[]
    for name,raw,meta in art:
        paths['PesMobile/Content/'+name[6:]+'.uasset']=len(additions)
        additions.append((struct.pack('<QHBB',meta['id'],0,0,2),raw))
        packages.append({k:v for k,v in meta.items() if k!='external_chunks'})
        for chunk in meta.get('external_chunks',[]):
            paths['PesMobile/Content/'+name[6:]+chunk['suffix']]=len(additions)
            additions.append((chunk['chunk_id'],chunk['data']))
    return additions,paths,packages
