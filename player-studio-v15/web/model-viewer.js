import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OBJLoader} from 'three/addons/loaders/OBJLoader.js';
import {GLTFExporter} from 'three/addons/exporters/GLTFExporter.js';
import {HeadTools} from './head-tools.js';

function disposeObject(root) {
  if (!root) return;
  const geometry = new Set(), materials = new Set(), textures = new Set();
  root.traverse(node => {
    if (node.geometry) geometry.add(node.geometry);
    for (const material of (Array.isArray(node.material) ? node.material : [node.material])) {
      if (!material) continue;
      materials.add(material);
      for (const val of Object.values(material)) if (val?.isTexture) textures.add(val);
    }
  });
  geometry.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); textures.forEach(t => t.dispose());
}

export class ModelViewer {
  constructor(onStatus) {
    this.onStatus = onStatus;
    this.wrapper = document.createElement('div');
    this.wrapper.style.cssText = 'width:100%;height:100%;position:relative';
    this.container = null;
    this.animations = [];
    this.mixer = null;
    this.clock = new THREE.Clock();
    this.loadSequence = 0;
    this.framesRendered = 0;
    this.options = {wireframe:false, skeleton:false, rotate:false};
    this.scene = new THREE.Scene();
    try {
      this.renderer = new THREE.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true});
    } catch (e) {
      this.wrapper.innerHTML = '<div class="model-empty model-failure">当前环境无法创建 3D 画面。请在 Edge 设置中开启图形加速后重新打开。</div>';
      this.failed = true;
      return;
    }
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.wrapper.append(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(32,1,.01,100);
    this.camera.position.set(2.55,1.8,3.6);
    this.controls = new OrbitControls(this.camera,this.renderer.domElement);
    this.controls.target.set(0,.95,0);
    this.controls.enableDamping = true;
    this.controls.minDistance = .45;
    this.controls.maxDistance = 10;
    this.controls.maxPolarAngle = Math.PI*.56;
    this.scene.add(new THREE.HemisphereLight(0xc7e8ff,0x53606d,2));
    const key = new THREE.DirectionalLight(0xffe0ba,3.2);
    key.position.set(2.5,5,4);key.castShadow=true;
    key.shadow.mapSize.set(1024,1024);key.shadow.camera.left=-2;key.shadow.camera.right=2;key.shadow.camera.top=3;key.shadow.camera.bottom=-2;
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x91c8ff,2.6);fill.position.set(-3,2,-1);this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xa5ffd9,2);rim.position.set(0,3,-3);this.scene.add(rim);
    const floor = new THREE.Mesh(new THREE.CylinderGeometry(.82,.89,.055,80),new THREE.MeshStandardMaterial({color:0x202e3a,roughness:.65,metalness:.35}));
    floor.position.y=-.055;floor.receiveShadow=true;this.scene.add(floor);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(.83,.005,8,100),new THREE.MeshBasicMaterial({color:0x609f8b}));
    ring.rotation.x=Math.PI/2;ring.position.y=-.024;this.scene.add(ring);
    const grid = new THREE.GridHelper(10,40,0x283b47,0x1c2d38);grid.position.y=-.085;grid.material.transparent=true;grid.material.opacity=.36;this.scene.add(grid);
    this.readout=document.createElement('div');this.readout.className='model-readout';this.wrapper.append(this.readout);
    this.observer = new ResizeObserver(()=>this.resize());this.observer.observe(this.wrapper);
    const animate = () => {
      requestAnimationFrame(animate);
      const delta = Math.min(this.clock.getDelta(),.1);
      if (!this.wrapper.isConnected || !this.wrapper.offsetWidth || !this.wrapper.offsetHeight) return;
      this.controls.autoRotate=this.options.rotate;this.controls.autoRotateSpeed=.7;
      this.controls.update();this.mixer?.update(delta);
      this.renderer.render(this.scene,this.camera);
      this.framesRendered++;
    };
    animate();
  }

  attach(container) {
    if (!container) return;
    if(this.container !== container || !this.wrapper.isConnected)container.append(this.wrapper);
    this.container=container;this.resize();
    requestAnimationFrame(()=>this.resize());
  }

  resize() {
    if(this.failed)return;
    const w=this.wrapper.clientWidth,h=this.wrapper.clientHeight;
    if(w<2||h<2)return;
    this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();
    this.controls.update();this.renderer.render(this.scene,this.camera);this.framesRendered++;
  }

  async update(project) {
    if(this.failed)return;
    this.project=project;
    const asset=project.model.asset||null;
    const custom=asset?.endsWith('.glb')&&!project.model.native_source?.path;
    const loadKey=JSON.stringify([asset,custom,project.model.native_source?.path,custom&&project.model.rigged_asset,custom&&project.model.neck_seam,custom&&project.model.preserve_expression]);
    if(asset){
      if(this.loadedKey!==loadKey){
        this.asset=asset;this.loadedKey=loadKey;const seq=++this.loadSequence;
        this.readout.innerHTML='<strong>正在载入模型…</strong>';
        try{
          let object,animations=[],headTools=null,spec=null;
          if(custom&&this.previewApi){
            try{spec=await this.previewApi(project);headTools=await HeadTools.load(this,spec);object=headTools.root;}
            catch(error){this.onStatus?.({error:'导出接合预览暂不可用：'+error.message+'。当前只显示导入原网格。'});}
          }
          if(!custom&&project.model.native_source?.path&&this.previewApi){
            spec=await this.previewApi(project);
            headTools=await HeadTools.load(this,spec);object=headTools.root;
          }
          if(!object){
            if(asset.endsWith('.glb')){const gltf=await new GLTFLoader().loadAsync('/assets/'+asset);object=gltf.scene;animations=custom?[]:gltf.animations;}
            else object=new OBJLoader().parse(await (await fetch('/assets/'+asset)).text());
          }
          if(seq!==this.loadSequence){disposeObject(object);return;}
          object.updateMatrixWorld(true);
          const box=new THREE.Box3().setFromObject(object),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
          const factor=1.8/Math.max(size.y,size.x*.65,size.z*.65,.001);
          const wrapper=new THREE.Group();wrapper.name='ImportedPlayerPreview';wrapper.userData.asset=asset;wrapper.add(object);
          object.position.sub(new THREE.Vector3(center.x,box.min.y,center.z));wrapper.scale.setScalar(factor);
          wrapper.userData.normalizedScale=factor;
          object.traverse(node=>{if(node.isMesh){node.castShadow=true;node.receiveShadow=true;}});
          this.replace(wrapper,animations);
          this.headTools=headTools;if(headTools){headTools.activate();this.metadata.headPreview=spec;this.onStatus?.(this.metadata);}
          this.signature='';
        }catch(error){
          this.asset=asset;if(this.subject){this.scene.remove(this.subject);disposeObject(this.subject);this.subject=null;}this.readout.textContent='原版模型载入失败，未使用替代模型';this.onStatus?.({error:'模型无法解析。支持自包含 GLB 和普通 OBJ；Draco 压缩模型请先解压网格。'+error.message});
        }
      }
      if(this.subject){
        const scale=(this.subject.userData.normalizedScale||1)*Number(project.model.scale||1);
        this.subject.scale.setScalar(scale);this.subject.rotation.y=THREE.MathUtils.degToRad(Number(project.model.rotation||0));
        this.headTools?.setProject(project);
      }
    }else{
      this.asset=null;this.loadedKey=null;this.loadSequence++;this.headTools?.dispose();this.headTools=null;
      if(this.subject){this.scene.remove(this.subject);disposeObject(this.subject);this.subject=null;}
      if(this.skeletonHelper){this.scene.remove(this.skeletonHelper);this.skeletonHelper.dispose();this.skeletonHelper=null;}
      this.metadata={meshes:0,triangles:0,bones:0,animations:[],morphs:[]};
      this.readout.innerHTML='<strong>尚未选择游戏原版模型</strong>从球员库的“原版模型”中选择；这里只显示已有网格。';
    }
    for(const morph of this.metadata?.morphs||[]){const value=project.model.morphs?.[morph.key];if(value!==undefined)this.setMorph(morph.mesh,morph.index,value);}
    if(this.headTools)this.readout.textContent=(this.headTools.testing?'面部权重检查 · 仅预览，不改变导出':this.headTools.test.raw?'原始绑定检查 · 不改变导出':this.headTools.spec.original_game_face?'游戏原版头模':'APK 导出接合预览 · '+(project.model.preserve_expression!==false?'保持导入表情':'使用导入面部权重'))+' · '+this.metadata.triangles.toLocaleString()+' 三角面';
    this.applyOptions();
  }

  replace(root,animations){
    this.headTools?.dispose();this.headTools=null;
    if(this.subject){this.scene.remove(this.subject);disposeObject(this.subject);}
    if(this.skeletonHelper){this.scene.remove(this.skeletonHelper);this.skeletonHelper.dispose();this.skeletonHelper=null;}
    this.subject=root;this.animations=animations;this.scene.add(root);
    this.mixer=animations.length?new THREE.AnimationMixer(root):null;
    let meshes=0,triangles=0,bones=0;const morphs=[];
    root.traverse(n=>{for(let p=n;p;p=p.parent)if(p.userData.previewOnly)return;
      if(n.isMesh){meshes++;triangles+=(n.geometry.index?n.geometry.index.count:n.geometry.attributes.position?.count||0)/3;
      if(n.morphTargetDictionary)for(const [name,index]of Object.entries(n.morphTargetDictionary))if(!name.startsWith('Studio'))morphs.push({name,index,mesh:n.uuid,key:`${meshes}:${name}`,value:n.morphTargetInfluences?.[index]||0});}
      if(n.isBone)bones++;});
    this.metadata={meshes,triangles:Math.round(triangles),bones,animations:animations.map(a=>a.name||'未命名动画'),morphs};
    this.readout.innerHTML=`<strong>${this.project?.model.native_source?'游戏原版模型':'已导入模型'}</strong>${meshes} 网格 · ${Math.round(triangles).toLocaleString()} 三角面${bones?' · '+bones+' 骨骼':''}`;
    this.resize();
    this.onStatus?.(this.metadata);
  }

  applyOptions(){
    if(!this.subject)return;
    this.subject.traverse(n=>{if(n.isMesh&&!n.userData.referenceMesh)for(const m of(Array.isArray(n.material)?n.material:[n.material]))if(m)m.wireframe=this.options.wireframe;});
    if(this.options.skeleton&&!this.skeletonHelper&&this.metadata.bones){this.skeletonHelper=new THREE.SkeletonHelper(this.subject);this.scene.add(this.skeletonHelper);}
    if(this.skeletonHelper)this.skeletonHelper.visible=this.options.skeleton;
  }

  setOption(key,value){this.options[key]=value;this.applyOptions();}
  setHeadTest(values){this.headTools?.setTest(values);this.update(this.project);}
  play(index){if(!this.mixer)return;this.mixer.stopAllAction();if(index>=0&&this.animations[index])this.mixer.clipAction(this.animations[index]).play();}
  setMorph(mesh,index,value){const n=this.subject?.getObjectByProperty('uuid',mesh);if(n?.morphTargetInfluences)n.morphTargetInfluences[index]=value;}
  view(mode){
    if(this.failed)return;
    if(mode==='head'){const box=new THREE.Box3().setFromObject(this.subject),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());const y=box.max.y-size.y*.09;this.camera.position.set(center.x+.22,y+.04,center.z+1.05);this.controls.target.set(center.x,y,center.z);}
    else if(mode==='front'){this.camera.position.set(0,1.05,4.6);this.controls.target.set(0,.96,0);}
    else{this.camera.position.set(2.55,1.8,3.6);this.controls.target.set(0,.95,0);}
    this.controls.update();
  }
  snapshot(){
    if(this.failed||!this.subject)throw Error('模型尚未准备完成');
    this.renderer.render(this.scene,this.camera);return this.renderer.domElement.toDataURL('image/png');
  }
  async exportGLB(){
    if(this.failed||!this.subject)throw Error('模型尚未准备完成');
    // Original heads must not acquire preview scale, centering, or test poses.
    if(this.project.model.native_source?.path){
      const response=await fetch(this.headTools?.spec.url||('/assets/'+this.asset));
      if(!response.ok)throw Error('原版头模导出失败，请重新载入模型');
      return response.arrayBuffer();
    }
    const helpers=[];this.subject.traverse(n=>{if(n.userData.previewOnly){helpers.push([n,n.visible]);n.visible=false;}});
    const actual=this.headTools?.actual,shown=actual?.visible;if(actual)actual.visible=true;
    const exportRoot=this.headTools?.raw||this.subject.children[0],exportVisible=exportRoot.visible;
    const tests=this.headTools?{...this.headTools.test}:null;
    if(tests)this.headTools.setTest({jaw:0,blink:0,raw:false,reference:false,handles:false});
    const previewOnly=exportRoot.userData.previewOnly;delete exportRoot.userData.previewOnly;
    exportRoot.visible=true;
    try{return await new GLTFExporter().parseAsync(exportRoot,{binary:true,animations:[],onlyVisible:true});}
    finally{if(previewOnly!==undefined)exportRoot.userData.previewOnly=previewOnly;exportRoot.visible=exportVisible;if(tests)this.headTools.setTest(tests);for(const [n,visible]of helpers)n.visible=visible;if(actual)actual.visible=shown;}
  }
}
