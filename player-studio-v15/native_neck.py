"""Fit a cut-off custom neck into the verified game's collar volume.

Only the lower neck is extended. The face, UVs, triangles and skeleton stay;
the extended area receives weights sampled from the original neck/chest.
"""


def fit(glb,reference,vertical_cm=0,binding=None):
    """Fit only cut-off necks; complete imported collars stay unchanged.

    Editor handles deform the mesh around fixed native joints. They never
    change the game's skeleton or inverse bind matrices.
    """
    import numpy as np
    changes,report=_fit_collar(glb,reference)
    a=glb.head()['attributes'];source=glb.read(a['POSITION']).astype(float)
    positions=changes.get('positions',source).copy()
    names=[reference.doc['nodes'][j]['name'] for j in reference.doc['skins'][0]['joints']]
    ibm=reference.read(reference.doc['skins'][0]['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
    head=np.linalg.inv(ibm[names.index('sk_head')])[:3,3]
    bottom=float(source[:,1].min());top=float(head[1]-.035)
    t=np.clip((source[:,1]-bottom)/max(top-bottom,.015),0,1);h=t*t*(3-2*t)
    binding=binding or {};head_offset=np.asarray(binding.get('head',[0,0,0]),dtype=float)/100
    head_offset[1]+=float(vertical_cm)/100
    root_offset=np.asarray(binding.get('neck_root',[0,0,0]),dtype=float)/100
    movement=h[:,None]*head_offset+(1-h[:,None])*root_offset
    if np.any(movement):
        positions+=movement;changes['positions']=positions
        report['placement_handles_cm']={'head':(head_offset*100).tolist(),'neck_root':(root_offset*100).tolist()}
        report['collar_endpoint_preserved_by_head_offset']=True
    report['native_skeleton_unchanged']=True
    if report.get('maximum_extension_m',0)>.08:
        report['warning']='头模在颈部高处截断，自动接合需要延伸超过 8 厘米。建议导入包含锁骨和胸口的模型，再关闭自动延伸。'
    return changes,report

def _fit_collar(glb,reference):
    import numpy as np
    attrs=glb.head()['attributes'];positions=glb.read(attrs['POSITION']).astype(float)
    normals=glb.read(attrs['NORMAL']).astype(float)
    joints=glb.read(attrs['JOINTS_0']).astype(int);weights=glb.read(attrs['WEIGHTS_0']).astype(float)
    primitive=reference.doc['meshes'][0]['primitives'][0];a=primitive['attributes']
    native=reference.read(a['POSITION']).astype(float)
    names=[reference.doc['nodes'][j]['name'] for j in reference.doc['skins'][0]['joints']]
    ibm=reference.read(reference.doc['skins'][0]['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
    head=np.linalg.inv(ibm[names.index('sk_head')])[:3,3]
    top=float(head[1]-.035);bottom=float(positions[:,1].min());target=float(native[:,1].min()+.015)
    if bottom<=target+.07:
        return {},{'status':'already-reaches-collar','changed_vertices':0,'complete_import_preserved':True}
    if bottom>=top-.015:raise ValueError('头模没有足够的颈部网格，请使用带颈部并绑定 V13 骨架的模型')
    t=np.clip((top-positions[:,1])/(top-bottom),0,1)
    # Preserve the front of the chin while the neck below it reaches the shirt.
    t*=np.clip((head[2]+.105-positions[:,2])/.04,0,1)
    strength=t*t*(3-2*t);mask=strength>1e-8
    # A high cut neck also leaves the jaw above the native collar. Bring the
    # entire head down modestly before extending the hidden part into the shirt.
    offset=-min(.04,max(0,bottom-target-.10))
    fitted=positions.copy();fitted[:,1]+=offset;fitted[:,1]-=strength*(bottom+offset-target)
    source_joints=reference.read(a['JOINTS_0']).astype(int)
    source_weights=reference.read(a['WEIGHTS_0']).astype(float)
    selected=np.flatnonzero(mask);bone_count=len(names)
    for start in range(0,len(selected),256):
        ix=selected[start:start+256];distance=((fitted[ix,None,:]-native[None,:,:])**2).sum(2)
        near=np.argpartition(distance,7,axis=1)[:,:8]
        blend=1/(np.take_along_axis(distance,near,axis=1)+1e-7);blend/=blend.sum(1,keepdims=True)
        dense=np.zeros((len(ix),bone_count));rows=np.broadcast_to(np.arange(len(ix))[:,None,None],(len(ix),8,4))
        np.add.at(dense,(rows.ravel(),source_joints[near].ravel()),(source_weights[near]*blend[:,:,None]).ravel())
        dense*=strength[ix,None]
        np.add.at(dense,(np.repeat(np.arange(len(ix)),4),joints[ix].ravel()),(weights[ix]*(1-strength[ix,None])).ravel())
        js=np.argsort(dense,axis=1)[:,-4:][:,::-1];ws=np.take_along_axis(dense,js,axis=1);ws/=ws.sum(1,keepdims=True)
        joints[ix]=js;weights[ix]=ws
    faces=glb.read(glb.head()['indices']).reshape(-1,3)
    def vertex_normals(points):
        cross=np.cross(points[faces[:,1]]-points[faces[:,0]],points[faces[:,2]]-points[faces[:,0]])
        result=np.zeros_like(points)
        for k in range(3):np.add.at(result,faces[:,k],cross)
        return result/np.maximum(np.linalg.norm(result,axis=1,keepdims=True),1e-12)
    sign=1 if np.einsum('ij,ij->i',vertex_normals(positions),normals).mean()>=0 else -1
    corrected=vertex_normals(fitted)*sign;normals[mask]=corrected[mask]
    return {'positions':fitted,'normals':normals,'joints':joints,'weights':weights},{
        'status':'extended-and-bound-to-native-collar','changed_vertices':int(mask.sum()),
        'source_bottom_m':bottom,'export_bottom_m':float(fitted[:,1].min()),
        'face_above_m_shape_unchanged':top,'vertical_offset_m':offset,
        'maximum_extension_m':float((positions[:,1]-fitted[:,1]).max())}
