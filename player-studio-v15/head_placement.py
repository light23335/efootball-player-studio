"""Per-player placement around fixed game joints, shared by preview/export."""
def place_without_extension(glb,reference,vertical_cm=0,binding=None):
    import numpy as np
    a=glb.head()['attributes'];positions=glb.read(a['POSITION']).astype(float)
    names=[reference.doc['nodes'][j]['name'] for j in reference.doc['skins'][0]['joints']]
    ibm=reference.read(reference.doc['skins'][0]['inverseBindMatrices']).reshape(-1,4,4).transpose(0,2,1)
    head=np.linalg.inv(ibm[names.index('sk_head')])[:3,3];bottom=float(positions[:,1].min())
    t=np.clip((positions[:,1]-bottom)/max(float(head[1]-.035)-bottom,.015),0,1);h=t*t*(3-2*t)
    binding=binding or {};offset=np.asarray(binding.get('head',[0,0,0]),dtype=float)/100;offset[1]+=float(vertical_cm)/100
    root=np.asarray(binding.get('neck_root',[0,0,0]),dtype=float)/100
    positions+=h[:,None]*offset+(1-h[:,None])*root
    return {'positions':positions},{'status':'placement-without-neck-extension','native_skeleton_unchanged':True,'collar_endpoint_preserved_by_head_offset':True}
