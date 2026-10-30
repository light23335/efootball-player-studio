import {exportStep} from './export-errors.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);

export class CoachHeads {
  constructor(context){
    Object.assign(this,context);this.rows=[];this.saved=[];this.open=false;this.query='';this.sequence=0;
    document.addEventListener('click',e=>{
      const b=e.target.closest('[data-head-action],[data-coach-head-view]');if(!b)return;
      if(b.dataset.coachHeadView){this.openFor(b.dataset.coachHeadView).catch(e=>this.toast(e.message,true));return;}
      if(this.busy&&b.dataset.headAction!=='close')return;
      const run=()=>this.action(b.dataset.headAction);
      (b.dataset.headAction==='export'?exportStep(this.currentCoach?.name,'导出教练头模 GLB',run):run()).catch(error=>{this.message=error.message;this.toast(error.message,true);this.paint();});
    });
    document.addEventListener('change',e=>{
      if(e.target.id==='coach-head-target'&&!this.busy)this.select(e.target.value).catch(error=>this.toast(error.message,true));
      if(e.target.dataset.headOption)this.viewer?.setOption(e.target.dataset.headOption,e.target.checked);
    });
    document.addEventListener('input',e=>{if(e.target.id==='coach-head-query'){this.query=e.target.value;this.options();}});
  }
  render(){return !this.open?'':`<section class="panel coach-head-panel"><div class="panel-title"><h2>${esc(this.currentCoach?.name||'教练')} · 当前三维头模</h2><button class="button secondary" data-head-action="close">关闭预览</button></div><div class="panel-body" id="coach-head-body"></div></section>`;}
  async activate(page){
    this.active=page==='coaches';if(!this.active)return;
    try{const data=await this.api('coaches/heads/list',{});if(!this.active)return;
      this.rows=data.rows;this.saved=data.saved;this.ready=data.ready;
      if(this.target&&!this.rows.some(r=>r.path===this.target)){this.target=null;this.draft=null;this.previewData=null;this.sequence++;}
      this.paint();
    }catch(e){this.message=e.message;this.paint();}
  }
  label(row){return `${row.label} · 版本 ${row.variant} · ${row.name}`;}
  options(){
    const select=$('#coach-head-target');if(!select)return;
    const q=this.query.trim().toLocaleLowerCase();const rows=this.rows.filter(r=>r.path===this.target||[r.label,r.name,...r.coach_ids].join(' ').toLocaleLowerCase().includes(q));
    select.innerHTML='<option value="">选择要查看 / 替换的原版教练头模</option>'+rows.map(r=>`<option value="${esc(r.path)}" ${r.path===this.target?'selected':''}>${esc(this.label(r))}</option>`).join('');
  }
  paint(){
    const body=$('#coach-head-body');if(!body)return;body.hidden=!this.open;if(!this.open)return;
    if(this.currentCoach?.type==='custom'){
      body.innerHTML=`<p class="note">当前自建教练正在使用的头模。导入自己的 GLB 后，这里直接显示导入的模型。</p><div class="model-stage coach-head-stage" id="coach-head-stage"></div><div class="model-hint">拖动旋转 · 滚轮或双指缩放</div><div class="portrait-actions"><button class="button secondary" data-edit-coach="${esc(this.currentCoach.id)}">编辑教练 / 更换头模</button></div><p class="migration-status" role="status">${esc(this.busy?'正在读取当前头模…':this.message||'')}</p>`;
      this.attach().catch(error=>this.toast(error.message,true));return;
    }
    const selected=this.rows.find(r=>r.path===this.target);const saved=this.saved.find(r=>r.target===this.target);
    const disabled=this.busy?'disabled':'';
    body.innerHTML=`<p class="panel-description">直接查看这名教练当前使用的头模。保存过替换时显示替换结果；可在这里导出或更换模型。</p>
      ${!this.ready?'<p class="migration-status">请先在“游戏来源与更新”准备游戏和离线资源。</p>':''}
      ${selected?`<p class="note coach-head-path">目标：${esc(selected.path)}</p><p class="note">按资源路径替换，使用同一路径的所有教练都会受影响。姓名来自编号匹配，具体比赛加载效果需游戏内验收。恢复原版时请使用未含本次替换的来源 APK。</p>
      <div class="coach-head-layout"><div><div class="model-stage coach-head-stage" id="coach-head-stage"></div><div class="model-hint">左键旋转 · 滚轮缩放 · 右键平移</div><div class="portrait-actions"><label><input type="checkbox" data-head-option="wireframe" ${this.viewer?.options.wireframe?'checked':''}>线框</label><label><input type="checkbox" data-head-option="skeleton" ${this.viewer?.options.skeleton?'checked':''}>骨架</label><label><input type="checkbox" data-head-option="rotate" ${this.viewer?.options.rotate?'checked':''}>旋转</label></div></div>
      <div><h3>替换方式</h3><label class="field"><span>换用原版教练头模</span><select id="coach-head-source" ${disabled}>${this.rows.map(r=>`<option value="${esc(r.path)}" ${(this.draft?.source||this.target)===r.path?'selected':''}>${esc(this.label(r))}</option>`).join('')}</select></label><div class="portrait-actions"><button class="button secondary" data-head-action="native" ${disabled}>预览所选原版头模</button><button class="button secondary" data-head-action="upload" ${disabled}>导入自制 GLB 并验证</button></div><p class="note">GLB 使用米制游戏坐标并内嵌贴图。推荐先导出本教练的原版 GLB，在原坐标中编辑后导入。兼容骨架保留可用权重；非兼容骨架采用原生头骨中性绑定，无法保留其面部表情。</p>
      <p class="note">当前方案：${this.draft?.mode==='custom'?'自制 GLB':this.draft?.mode==='native'?esc(this.rows.find(r=>r.path===this.draft.source)?.label||'原版头模'):'尚未选择替换'}${saved?' · 已保存的替换会列入 APK 导出':''}</p>
      <div class="portrait-actions"><button class="button secondary" data-head-action="original" ${disabled}>查看原版目标</button><button class="button secondary" data-head-action="draft" ${disabled||!this.draft?'disabled':''}>查看替换效果</button><button class="button secondary" data-head-action="export" ${disabled||!this.previewData?'disabled':''}>导出当前预览 GLB</button></div>
      <div class="portrait-actions"><button class="button primary" data-head-action="save" ${disabled||!this.draft?'disabled':''}>保存替换用于 APK</button><button class="button subtle" data-head-action="delete" ${disabled||!saved?'disabled':''}>取消已保存的替换</button></div>
      <p class="note">保存后到“APK 实装”勾选教练头模写入；取消替换后，下次生成恢复原版。</p></div></div>`:''}
      <p class="migration-status ${this.message?.includes('失败')?'error':''}" id="coach-head-status" role="status">${esc(this.busy?'正在解码与验证，请稍候…':this.message||'选择一个原版教练头模开始。')}</p>`;
    this.options();this.attach().catch(error=>{this.message=error.message;const status=$('#coach-head-status');if(status)status.textContent='三维预览未能启动：'+error.message;});
  }
  async attach(){
    const stage=$('#coach-head-stage');if(!stage)return;
    if(!this.modelModule)this.modelModule=import('./model-viewer.js');
    const {ModelViewer}=await this.modelModule;
    if(!stage.isConnected||stage!==$('#coach-head-stage'))return;
    if(!this.viewer){
      this.viewer=new ModelViewer(meta=>{if(meta.error)this.toast(meta.error,true);});
      this.viewer.scene.traverse(light=>{if(light.isDirectionalLight&&light.shadow){light.shadow.bias=-.0005;light.shadow.normalBias=.02;}});
    }
    this.viewer.attach(stage);
    if(this.previewData)this.viewer.update({model:{asset:this.previewData.asset_id,native_source:this.previewData.report?.mode==='custom'?null:{path:this.previewData.path||this.target},scale:1,rotation:0,morphs:{}}});
  }
  async select(path){
    this.target=path||null;this.draft=structuredClone(this.saved.find(r=>r.target===path)||null);this.previewData=null;this.sequence++;this.message='';this.paint();
    if(path)await this.load(false);
  }
  async load(draft){
    if(!this.target)return;const seq=++this.sequence;this.busy=true;this.paint();
    try{const r=await this.api(draft?'coaches/heads/preview':'coaches/heads/original',draft?{head:this.draft}:{path:this.target});
      if(seq!==this.sequence)return;this.previewData=r;
      const info=r.face_source||r.report?.face;
      this.message=(draft?'替换效果':'原版目标')+'已载入'+(info?` · ${info.highest_vertices} 顶点 · ${info.bones} 骨骼 · ${info.lods} 个精度档位`:'')+(r.report?.rig?.warning?'。'+r.report.rig.warning:'')+'。软件已解码，比赛效果待游戏内验收。';
    }finally{if(seq===this.sequence){this.busy=false;this.paint();}}
  }
  async openFor(id){
    const coach=this.lookupCoach?.(id);if(!coach)throw Error('未找到这名教练，请刷新列表');
    const seq=++this.sequence;this.currentCoach=structuredClone(coach);this.open=true;this.busy=true;
    this.target=null;this.draft=null;this.previewData=null;this.message='';this.rerender();
    try{
      const result=await this.api('coaches/model/current',{coach:this.currentCoach});
      if(seq!==this.sequence)return;
      this.target=result.template_path;this.draft=structuredClone(result.replacement||null);this.previewData=result;
      this.message=result.personal?(result.head_model?.asset_id?'已显示你上传的教练头模。':'已显示这名教练的默认 / 继承头模。'):(result.replacement?'已显示当前保存的替换头模。':'已显示原版教练当前头模。');
    }catch(error){if(seq===this.sequence)this.message=error.message;}
    finally{if(seq===this.sequence){this.busy=false;this.paint();}}
    if(seq===this.sequence)$('.coach-head-panel')?.scrollIntoView({block:'start',behavior:'smooth'});
  }
  async action(action){
    if(action==='close'){this.open=false;this.sequence++;this.busy=false;this.viewer?.update({model:{asset:null}});this.rerender();return;}
    if(action==='toggle'){this.open=!this.open;this.rerender();return;}
    if(action==='original'){await this.load(false);return;}
    if(action==='draft'){if(this.draft)await this.load(true);return;}
    if(action==='native'){const source=$('#coach-head-source')?.value;if(!source)return;this.draft={target:this.target,mode:'native',source};await this.load(true);return;}
    if(action==='upload'){
      const target=this.target;const f=await this.api('dialog',{category:'model'});if(!f.path||target!==this.target)return;
      const a=await this.api('assets/import',{path:f.path,category:'model'});if(!a.id.endsWith('.glb'))throw Error('教练头模请使用内嵌贴图的 GLB 文件');
      if(target!==this.target)return;this.draft={target,mode:'custom',asset_id:a.id};await this.load(true);return;
    }
    if(action==='export'){
      const r=await fetch(this.previewData.url);if(!r.ok)throw Error('GLB 下载失败');const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=this.target.split('/').at(-1).replace('.uasset',this.draft&&this.previewData.report?'-replacement.glb':'.glb');a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);return;
    }
    if(action==='save'){
      this.busy=true;this.paint();try{const r=await this.api('coaches/heads/save',{head:this.draft});this.saved=this.saved.filter(v=>v.target!==r.head.target);this.saved.push(r.head);this.previewData=r;this.message='替换已保存。请到“APK 实装”生成游戏 APK，再验收比赛中的教练头模。';this.toast('教练头模替换已保存');}finally{this.busy=false;this.paint();}return;
    }
    if(action==='delete'){await this.api('coaches/heads/delete',{target:this.target});this.saved=this.saved.filter(v=>v.target!==this.target);this.draft=null;await this.load(false);this.message='已取消替换。下次使用原版来源生成 APK 时不再写入此头模。';this.paint();}
  }
}
