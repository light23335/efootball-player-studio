"""Bounded conversion of the supplied UE4.26 texture, material and head assets.

Reads documented CUE4Parse serializers, then validates counts and references.
Unsupported asset layouts fail explicitly rather than substituting artwork.
"""
from pathlib import Path
import ctypes,io,json,os,re,struct
import numpy as np
from PIL import Image
from native_iostore import package_names
from native_mesh import read_lod
from native_skeletal import object_imports,skeleton,local_matrix,mesh_glb


class Properties:
    def __init__(self,raw):
        self.raw=raw;self.names=package_names(raw);self.imports=object_imports(raw,self.names)
    def fname(self,at):
        ident,number=struct.unpack_from('<II',self.raw,at)
        if ident>=len(self.names) or number>100000:raise ValueError('原版属性名称无效')
        return self.names[ident]+('_'+str(number-1) if number else '')
    def tag(self,at):
        name=self.fname(at);at+=8
        if name=='None':return name,'',at,at,{}
        kind=self.fname(at);at+=8;size,index=struct.unpack_from('<II',self.raw,at);at+=8;extra={}
        if size>len(self.raw):raise ValueError('原版属性长度无效')
        if kind=='StructProperty':extra['struct']=self.fname(at);at+=24
        elif kind=='BoolProperty':extra['bool']=bool(self.raw[at]);at+=1
        elif kind in ('ByteProperty','EnumProperty'):extra['enum']=self.fname(at);at+=8
        elif kind in ('ArrayProperty','SetProperty'):extra['inner']=self.fname(at);at+=8
        elif kind=='MapProperty':at+=16
        guid=self.raw[at];at+=1
        if guid==1:at+=16
        elif guid!=0:raise ValueError('原版属性 GUID 格式改变')
        if at+size>len(self.raw):raise ValueError('原版属性数据不完整')
        return name,kind,at,at+size,extra
    def object(self,at):
        index=struct.unpack_from('<i',self.raw,at)[0]
        path=self.imports[-index-1] if index<0 and -index-1<len(self.imports) else ''
        return {'ObjectPath':path,'ObjectName':path.rsplit('/',1)[-1]}
    def read(self,at,depth=0):
        if depth>12:raise ValueError('原版属性嵌套过深')
        result={}
        for _ in range(1024):
            name,kind,start,end,extra=self.tag(at)
            if name=='None':return result,end
            value=None
            if kind=='NameProperty':value=self.fname(start)
            elif kind=='ObjectProperty':value=self.object(start)
            elif kind=='IntProperty':value=struct.unpack_from('<i',self.raw,start)[0]
            elif kind=='FloatProperty':value=struct.unpack_from('<f',self.raw,start)[0]
            elif kind=='BoolProperty':value=extra['bool']
            elif kind=='StructProperty':
                if extra['struct'] not in ('Guid','LinearColor','Color','Vector','Vector2D','PerPlatformFloat','PerPlatformInt','PerPlatformBool'):
                    value,_=self.read(start,depth+1)
            elif kind=='ArrayProperty':
                count=struct.unpack_from('<I',self.raw,start)[0];pos=start+4
                if count>100000:raise ValueError('原版属性数组过大')
                if count==0:value=[]
                elif extra['inner']=='StructProperty':
                    _,_,pos,_,_=self.tag(pos);value=[]
                    for _ in range(count):item,pos=self.read(pos,depth+1);value.append(item)
                elif extra['inner']=='ObjectProperty':value=[self.object(pos+i*4) for i in range(count)]
                elif extra['inner']=='IntProperty':
                    if pos+count*4!=end:raise ValueError('原版整数数组长度无效')
                    value=list(struct.unpack_from('<'+'i'*count,self.raw,pos))
            if value is not None:result[name]=value
            at=end
        raise ValueError('原版属性数量异常')

def material_json(assets,path,depth=0):
    if depth>8:raise ValueError('原版材质继承过深')
    raw=assets.raw(path);h=struct.unpack_from('<16I',raw);props,_=Properties(raw).read(h[13]+h[14])
    parent=(props.get('Parent') or {}).get('ObjectPath')
    if parent:
        try:base=material_json(assets,parent,depth+1)[0]['Properties'].get('TextureParameterValues',[])
        except (ValueError,KeyError):base=[]
        inherited={p.get('ParameterInfo',{}).get('Name'):p for p in base}
        inherited.update({p.get('ParameterInfo',{}).get('Name'):p for p in props.get('TextureParameterValues',[])})
        props['TextureParameterValues']=list(inherited.values())
    return [{'Name':path.rsplit('/',1)[-1].removesuffix('.uasset'),'Properties':props}]


def skeletal_json(assets,path):
    """Read the coach compiler's exact bounds and per-LOD material remapping."""
    from native_skeletal import skeleton
    raw=assets.raw(path);names=package_names(raw);start,_,_=skeleton(raw,names)
    materials_at=None
    imports=object_imports(raw,names)
    for count in range(1,33):
        at=start-4-count*40
        if at<28 or struct.unpack_from('<I',raw,at)[0]!=count:continue
        refs=[struct.unpack_from('<i',raw,at+4+i*40)[0]for i in range(count)]
        if all(v<0 and -v-1<len(imports)and imports[-v-1]for v in refs):materials_at=at;break
    if materials_at is None:raise ValueError('教练头模材质表尚未适配')
    bounds=struct.unpack_from('<7f',raw,materials_at-28)
    if not all(np.isfinite(bounds))or any(v<0 for v in bounds[3:]):raise ValueError('教练头模边界无效')
    parser=Properties(raw)
    if 'LODInfo'not in names:raise ValueError('教练头模没有精度档位资料')
    marker=struct.pack('<II',names.index('LODInfo'),0);at=raw.find(marker,struct.unpack_from('<16I',raw)[13])
    found=[]
    while at>=0 and at<materials_at:
        try:
            name,kind,pos,end,extra=parser.tag(at)
            if name=='LODInfo'and kind=='ArrayProperty'and extra.get('inner')=='StructProperty':found.append((pos,end))
        except (ValueError,struct.error):pass
        at=raw.find(marker,at+1,materials_at)
    if len(found)!=1:raise ValueError('无法唯一识别教练精度档位属性')
    pos,end=found[0];count=struct.unpack_from('<I',raw,pos)[0]
    if not 1<=count<=16:raise ValueError('教练精度档位数量无效')
    _,kind,pos,_,extra=parser.tag(pos+4)
    if kind!='StructProperty':raise ValueError('教练精度档位结构无效')
    rows=[]
    for _ in range(count):row,pos=parser.read(pos);rows.append(row)
    if pos!=end:raise ValueError('教练精度档位数据范围不同')
    return [{'Type':'SkeletalMesh','Name':Path(path).stem,'ImportedBounds':{
        'Origin':dict(zip(('X','Y','Z'),bounds[:3])),'BoxExtent':dict(zip(('X','Y','Z'),bounds[3:6])),'SphereRadius':bounds[6]},'Properties':{'LODInfo':rows}}]

def block_image(data,width,height,fmt):
    if fmt=='PF_B8G8R8A8':return Image.frombytes('RGBA',(width,height),data,'raw','BGRA')
    if fmt=='PF_R8G8B8A8':return Image.frombytes('RGBA',(width,height),data)
    if fmt in ('PF_G8','PF_R8'):return Image.frombytes('L',(width,height),data).convert('RGBA')
    astc=re.fullmatch(r'PF_ASTC_(\d+)x(\d+)',fmt)
    formats={'PF_ETC2_RGB':(1,'decode_etc2'),'PF_ETC2_RGBA':(2,'decode_etc2a8'),
             'PF_ETC2_RGBA1':(3,'decode_etc2a1'),'PF_DXT1':(4,'decode_bc1'),'PF_DXT5':(5,'decode_bc3'),
             'PF_BC5':(6,'decode_bc5'),'PF_BC7':(7,'decode_bc7')}
    if not astc and fmt not in formats:raise ValueError('此原版纹理格式未适配：'+fmt)
    if os.environ.get('STUDIO_CODECS'):
        from cityhash import library
        lib=library();out=(ctypes.c_uint32*(width*height))()
        if astc:
            fn=lib.studio_astc;fn.argtypes=[ctypes.c_char_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
            success=fn(data,len(data),width,height,*map(int,astc.groups()),out)
        else:
            fn=lib.studio_blocks;fn.argtypes=[ctypes.c_char_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
            success=fn(data,len(data),width,height,formats[fmt][0],out)
        if not success:raise ValueError('原版纹理块长度或内容校验失败')
        pixels=bytes(out)
    else:
        # Host-only comparison dependency, never bundled as an Android wheel.
        import texture2ddecoder
        fn=getattr(texture2ddecoder,'decode_astc' if astc else formats[fmt][1])
        pixels=fn(data,width,height,*map(int,astc.groups())) if astc else fn(data,width,height)
    return Image.frombytes('RGBA',(width,height),pixels,'raw','BGRA')

def texture_image(assets,path):
    raw=assets.raw(path);h=struct.unpack_from('<16I',raw);names=package_names(raw)
    formats=[n for n in names if n.startswith('PF_')]
    if len(formats)!=1:raise ValueError('原版纹理像素格式不唯一')
    fmt=formats[0];at=raw.find(fmt.encode()+b'\0',h[13]+h[14])
    if at<16:raise ValueError('未找到原版纹理平台数据')
    width,height,slices,length=struct.unpack_from('<4I',raw,at-16)
    if not 1<=width<=8192 or not 1<=height<=8192 or slices!=1 or length!=len(fmt)+1:raise ValueError('原版纹理尺寸或切片数未适配')
    pos=at+length;first,count,cooked,flags=struct.unpack_from('<4I',raw,pos);pos+=16
    if not 1<=count<=16 or cooked!=1:raise ValueError('原版纹理 mip 格式未适配')
    wide=bool(flags&0x2000);size,stored,offset=struct.unpack_from('<QQq' if wide else '<IIq',raw,pos);pos+=24 if wide else 16
    if not 0<size<=128*1024*1024 or size!=stored:raise ValueError('原版纹理 bulk 长度未适配')
    if flags&0x40:data=raw[pos:pos+size];dimensions_at=pos+size
    elif flags&0x100:
        # Optional high-resolution mips are a different IoStore chunk (4),
        # exposed as .uptnl. The .ubulk chunk (3) contains lower mips only.
        suffix='.uptnl' if flags&0x800 else '.ubulk'
        bulk=assets.raw(path.removesuffix('.uasset')+suffix)
        if offset<0 or offset+size>len(bulk):raise ValueError(f'原版纹理 bulk 数据不完整：{path}{suffix}，偏移 {offset}，需要 {size} 字节，实际 {len(bulk)} 字节')
        data=bulk[offset:offset+size]
        dimensions_at=pos
    else:raise ValueError('此原版纹理 bulk 存储方式未适配')
    if len(data)!=size:raise ValueError('原版纹理 bulk 数据不完整')
    mip_width,mip_height,depth=struct.unpack_from('<3I',raw,dimensions_at)
    if not 1<=mip_width<=width or not 1<=mip_height<=height or depth!=1:raise ValueError('原版纹理 mip 尺寸不受支持')
    width,height=mip_width,mip_height
    return block_image(data,width,height,fmt)




def convert(assets,path,output,mode='auto'):
    path=path.removeprefix('../../../');relative=Path(path)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('原版资源输出路径越界')
    destination=Path(output)/relative;destination.parent.mkdir(parents=True,exist_ok=True)
    if mode=='raw':destination.write_bytes(assets.raw(path));return
    if mode=='json':destination.with_suffix('.json').write_text(json.dumps(skeletal_json(assets,path)if relative.stem.startswith('SK_')else material_json(assets,path),ensure_ascii=False),encoding='utf8');return
    name=relative.stem
    if name.startswith('SK_'):destination.with_suffix('.glb').write_bytes(mesh_glb(assets,path))
    else:texture_image(assets,path).save(destination.with_suffix('.png'))
