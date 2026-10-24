"""Embedded GLB access and proof that a rigged head matches its design mesh."""
import json
import struct


class Glb:
    def __init__(self,raw):
        if raw[:4]!=b'glTF' or struct.unpack_from('<I',raw,4)[0]!=2 or struct.unpack_from('<I',raw,8)[0]!=len(raw):
            raise ValueError('请选择完整的 GLB 2.0 模型')
        at=12;self.binary=b'';self.doc=None
        while at<len(raw):
            size,kind=struct.unpack_from('<II',raw,at);at+=8
            if at+size>len(raw):raise ValueError('GLB 数据不完整')
            if kind==0x4e4f534a:self.doc=json.loads(raw[at:at+size])
            elif kind==0x004e4942:self.binary=raw[at:at+size]
            at+=size
        if self.doc is None or any(b.get('uri') for b in self.doc.get('buffers',[])):
            raise ValueError('实装模型需要使用内嵌数据的 GLB')

    def read(self,index):
        import numpy as np
        a=self.doc['accessors'][index];v=self.doc['bufferViews'][a['bufferView']]
        dtype=np.dtype({5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']])
        width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
        step=v.get('byteStride',dtype.itemsize*width);offset=v.get('byteOffset',0)+a.get('byteOffset',0)
        values=np.ndarray((a['count'],width),dtype=dtype,buffer=self.binary,offset=offset,strides=(step,dtype.itemsize)).copy()
        if a.get('normalized'):values=np.maximum(values.astype(float)/np.iinfo(dtype).max,-1)
        return values

    def head(self):
        primitives=[p for m in self.doc.get('meshes',[]) for p in m['primitives']]
        if len(primitives)!=1:raise ValueError('自制脸模暂需合并为一个带内嵌贴图的网格')
        p=primitives[0]
        if p.get('mode',4)!=4:raise ValueError('脸模需要使用三角形网格')
        return p

    def image(self,primitive=None):
        p=primitive or self.head();material=self.doc['materials'][p.get('material',0)]
        texture=material.get('pbrMetallicRoughness',{}).get('baseColorTexture')
        if not texture:raise ValueError('脸模缺少内嵌的 BaseColor 贴图')
        image=self.doc['images'][self.doc['textures'][texture['index']]['source']]
        view=self.doc['bufferViews'][image['bufferView']];at=view.get('byteOffset',0)
        return self.binary[at:at+view['byteLength']]


def prove_binding(static,rigged):
    import numpy as np
    a,b=static.head(),rigged.head()
    x=static.read(a['attributes']['POSITION']);y=rigged.read(b['attributes']['POSITION'])
    if x.shape!=y.shape or len(x)>500000:raise ValueError('骨架版本与当前头模顶点数量不同')
    if not np.array_equal(static.read(a['indices']),rigged.read(b['indices'])):raise ValueError('骨架版本改变了当前头模的三角形')
    if not np.array_equal(static.read(a['attributes']['TEXCOORD_0']),rigged.read(b['attributes']['TEXCOORD_0'])):raise ValueError('骨架版本与当前头模 UV 不同')
    if static.image(a)!=rigged.image(b):
        from PIL import Image
        import io
        left=Image.open(io.BytesIO(static.image(a))).convert('RGBA')
        right=Image.open(io.BytesIO(rigged.image(b))).convert('RGBA')
        if left.size!=right.size or left.tobytes()!=right.tobytes():
            raise ValueError('骨架版本与当前头模贴图像素不同')
    coords=np.column_stack((x,np.ones(len(x))))
    transform=np.linalg.lstsq(coords,y,rcond=None)[0]
    error=float(np.linalg.norm(coords@transform-y,axis=1).max())
    if error>2e-6:raise ValueError('骨架版本的形状与当前头模不符')
    if not rigged.doc.get('skins') or not {'JOINTS_0','WEIGHTS_0'}<=b['attributes'].keys():
        raise ValueError('此 GLB 尚未绑定游戏骨架')
    return {'geometry_unchanged':True,'triangles_unchanged':True,'uv_unchanged':True,'texture_unchanged':True,'maximum_alignment_error_m':error}


def verify_skeleton(rigged,reference):
    import numpy as np
    if len(rigged.doc.get('skins',[]))!=1 or len(reference.doc.get('skins',[]))!=1:raise ValueError('仅支持一套已核对的原版游戏骨架')
    own,game=rigged.doc['skins'][0],reference.doc['skins'][0]
    if len(own['joints'])!=len(game['joints']):raise ValueError('脸模骨骼数量与原版模板不同')
    for a,b in zip(own['joints'],game['joints']):
        left,right=rigged.doc['nodes'][a],reference.doc['nodes'][b]
        for key in ('name','translation','rotation','scale','matrix'):
            if left.get(key)!=right.get(key):raise ValueError('脸模骨骼名称、顺序或绑定姿态与游戏模板不同')
    ibm_own=rigged.read(own['inverseBindMatrices']);ibm_game=reference.read(game['inverseBindMatrices'])
    if not np.allclose(ibm_own,ibm_game,atol=1e-6,rtol=0):raise ValueError('脸模逆绑定矩阵与原版模板不同')
    return len(own['joints'])
