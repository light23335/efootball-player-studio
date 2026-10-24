import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';

export class HeadTools{
  static async load(viewer,spec){
    const tools=new HeadTools(viewer,spec),loader=new GLTFLoader();
    const [actual,raw,reference]=await Promise.all([loader.loadAsync(spec.export_url),loader.loadAsync(spec.raw_url),loader.loadAsync(spec.reference_url)]);
    tools.actual=actual.scene;tools.raw=raw.scene;tools.reference=reference.scene;
    for(const [role,root] of [['export',tools.actual],['raw',tools.raw],['reference',tools.reference]]){
      root.name='HeadPreview-'+role;root.userData.previewOnly=role!=='export';tools.root.add(root);
      root.traverse(n=>{if(n.isSkinnedMesh)tools.base.set(n.uuid,n.skeleton.bones.map(b=>({bone:b,quaternion:b.quaternion.clone()})));
        if(n.isMesh&&role==='reference'){n.userData.referenceMesh=true;n.material=new THREE.MeshBasicMaterial({color:0x80dcca,wireframe:true,transparent:true,opacity:.32,depthWrite:false});n.renderOrder=2;}
      });
    }
    tools.raw.visible=false;tools.reference.visible=false;
    for(const [key,position] of Object.entries(spec.anchors)){
      const marker=new THREE.Mesh(new THREE.SphereGeometry(.007,16,12),new THREE.MeshBasicMaterial({color:key==='head'?0xffce72:0x80ddc5,depthTest:false}));
      marker.position.fromArray(position);marker.name=key==='head'?'头部定位点':'颈根定位点';marker.renderOrder=20;marker.userData.previewOnly=true;marker.userData.handle=key;tools.markers.set(key,marker);tools.root.add(marker);
    }
    return tools;
  }
  constructor(viewer,spec){this.viewer=viewer;this.spec=spec;this.root=new THREE.Group();this.root.name='ExportEquivalentHead';this.markers=new Map();this.base=new Map();this.test={jaw:0,blink:0,raw:false,reference:false,handles:false,selected:'head'};}
  activate(){
    const v=this.viewer;this.control=new TransformControls(v.camera,v.renderer.domElement);this.control.setMode('translate');this.control.setSize(.7);this.control.setTranslationSnap(.001);
    this.gizmo=this.control.getHelper();v.scene.add(this.gizmo);this.gizmo.visible=false;
    this.control.addEventListener('dragging-changed',e=>{v.controls.enabled=!e.value;});
    this.control.addEventListener('objectChange',()=>{
      const key=this.test.selected,marker=this.markers.get(key);if(!marker)return;
      const offset=marker.position.clone().sub(new THREE.Vector3().fromArray(this.spec.anchors[key])).multiplyScalar(100);
      const values=offset.toArray().map(x=>Math.round(THREE.MathUtils.clamp(x,-10,10)*100)/100);
      // The head marker includes the existing vertical-placement slider.
      if(key==='head')values[1]=Math.round(THREE.MathUtils.clamp(values[1]-(Number(this.project?.model.head_vertical_cm)||0),-10,10)*100)/100;
      v.onBindingChange?.(key,values);
    });
    this.pointer=e=>{
      if(!this.test.handles||this.control.dragging)return;
      const rect=v.renderer.domElement.getBoundingClientRect(),pointer=new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),ray=new THREE.Raycaster();ray.setFromCamera(pointer,v.camera);
      const hit=ray.intersectObjects([...this.markers.values()])[0];if(hit){this.setTest({selected:hit.object.userData.handle});v.onHeadSelection?.(this.test.selected);}
    };
    v.renderer.domElement.addEventListener('pointerdown',this.pointer);this.setProject(v.project);
    const values={};document.querySelectorAll('[data-head-option],[data-head-test]').forEach(el=>{const key=el.dataset.headOption||el.dataset.headTest;values[key]=el.type==='checkbox'?el.checked:el.tagName==='SELECT'?el.value:Number(el.value);});this.setTest(values);
  }
  dispose(){this.viewer.controls.enabled=true;this.viewer.renderer.domElement.removeEventListener('pointerdown',this.pointer);this.control?.detach();if(this.gizmo)this.viewer.scene.remove(this.gizmo);this.control?.dispose();}
  setProject(project){this.project=project;const m=project.model,handles=m.binding_handles||{};
    for(const [key,label] of [['head','Head'],['neck_root','Root']]){
      const values=[...(handles[key]||[0,0,0])];if(key==='head')values[1]+=Number(m.head_vertical_cm)||0;
      for(const root of [this.actual,this.raw])root.traverse(mesh=>{if(!mesh.morphTargetDictionary)return;for(let i=0;i<3;i++){const index=mesh.morphTargetDictionary['Studio'+label+'XYZ'[i]];if(index!==undefined)mesh.morphTargetInfluences[index]=values[i];}});
      this.markers.get(key).position.fromArray(this.spec.anchors[key]).add(new THREE.Vector3().fromArray(values).multiplyScalar(.01));
    }
    this.applyTest();
  }
  setTest(values){Object.assign(this.test,values);this.actual.visible=!this.test.raw;this.raw.visible=this.test.raw;this.reference.visible=this.test.reference;
    for(const marker of this.markers.values())marker.visible=this.test.handles;
    if(this.control){this.control.detach();if(this.test.handles)this.control.attach(this.markers.get(this.test.selected));this.gizmo.visible=this.test.handles;}
    this.applyTest();
  }
  applyTest(){
    for(const poses of this.base.values())for(const {bone,quaternion}of poses){bone.quaternion.copy(quaternion);
      const angle=bone.name==='skf_jaw'?this.test.jaw*28:bone.name.startsWith('skf_eyelid_t_')?this.test.blink*18:bone.name.startsWith('skf_eyelid_b_')?this.test.blink*-8:0;
      if(angle)bone.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),THREE.MathUtils.degToRad(angle)));
    }
    this.root.updateMatrixWorld(true);this.root.traverse(mesh=>{if(mesh.isSkinnedMesh)mesh.skeleton.update();});
  }
}

export function headPanel(project,viewer){
 const m=project.model,custom=!!m.asset&&!m.native_source?.path;
 const coordinate=(key,label)=>`<fieldset class="field"><legend>${label}（厘米）</legend><div class="field-grid">${['X','Y','Z'].map((axis,i)=>`<label class="field"><span>${axis} · ${['左右','上下','前后'][i]}</span><input type="number" step="0.1" min="-10" max="10" data-bind="model.binding_handles.${key}.${i}" value="${m.binding_handles?.[key]?.[i]||0}"></label>`).join('')}</div></fieldset>`;
 return `<section class="panel"><div class="panel-title"><h2>头模接合与表情设置</h2><span class="tag">每名球员独立保存</span></div><div class="panel-body"><label class="switch-label"><input type="checkbox" data-bind="model.preserve_expression" ${m.preserve_expression!==false?'checked':''}>导入游戏时保持导入表情（自制头模）</label><p class="note">开启后保护下颌和眼睑，头颈仍随游戏动作运动；关闭后使用导入的面部蒙皮，需自行核对游戏中的大幅表情。游戏原版脸模沿用原版表情。</p>${custom?`<div class="model-view-options"><label class="switch-label"><input type="checkbox" data-head-option="reference">叠加原版头模对照</label><label class="switch-label"><input type="checkbox" data-head-option="handles">显示可拖动定位点</label><label class="switch-label"><input type="checkbox" data-head-option="raw">原始绑定检查（不改变导出设置）</label></div><label class="field"><span>选择定位点，也可点击画面中的圆点</span><select data-head-option="selected"><option value="head">头部定位 · 暖黄色</option><option value="neck_root">颈根定位 · 绿色</option></select></label><p class="note">拖动坐标箭头调整；定位点修改网格接合，原生骨骼结构保持不变。对照使用相同游戏坐标和缩放。较完整的锁骨、胸口模型会保留原有颈部形状。</p>${coordinate('head','头部定位')}${coordinate('neck_root','颈根定位')}<button class="button secondary" data-action="head-handles-reset">重置这名球员的定位点</button><div class="field-grid"><label class="field"><span>张嘴检查</span><input type="range" min="0" max="1" step=".01" value="0" data-head-test="jaw"></label><label class="field"><span>闭眼检查</span><input type="range" min="0" max="1" step=".01" value="0" data-head-test="blink"></label></div><p class="note">默认显示 APK 导出效果。保持表情开启时，张嘴与闭眼不会拉动面部；勾选原始绑定检查可查看原来的面部权重。检查动作是本地测试，不是原游戏动作。</p><p class="note" id="head-fit-notice"></p>`:'<p class="note">选择已绑定游戏骨架的自制头模后，可使用原版对照、定位点和面部检查。</p>'}</div></section>`;
}
