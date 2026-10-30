import {exportStep} from './export-errors.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);

export class CoachModelEditor {
  constructor(context){
    Object.assign(this,context);this.sequence=0;this.scope=null;
    document.addEventListener('click',e=>{const b=e.target.closest('[data-personal-coach-model]');if(b&&!this.busy){const run=()=>this.action(b.dataset.personalCoachModel);(b.dataset.personalCoachModel==='export-template'?exportStep(this.row()?.name,'导出教练 GLB 模板',run):run()).catch(error=>{this.message=error.message;this.paint();this.toast(error.message,true);});}});
    document.addEventListener('change',e=>{if(e.target.dataset.personalCoachOption)this.viewer?.setOption(e.target.dataset.personalCoachOption,e.target.checked);});
  }
  render(){return '<section class="personal-coach-model"><h3>这名自建教练的独立三维头模</h3><div id="personal-coach-model-body"><p class="note">正在读取原版头模模板…</p></div></section>';}
  reset(){this.scope=null;this.sequence++;this.data=null;this.result=null;this.message='';this.busy=false;this.viewer?.update({model:{asset:null}});}
  async activate(page){
    const row=this.row();if(page!=='coaches'||!row)return;
    const scope=row.uuid+':'+(this.resourceKey?.()||'');
    if(this.scope!==scope){
      this.scope=scope;this.sequence++;this.result=null;this.data=null;this.message='';
      try{
        this.data=await this.api('coaches/model/template',{source_id:row.native_source_id});
        if(this.row()!==row||this.scope!==scope)return;
        if(!row.head_model&&this.data.available)row.head_model={template_path:this.data.template_path};
        this.paint();
        if(row.head_model)await this.load();
      }catch(error){this.message=error.message;this.paint();}
    }else{this.paint();}
  }
  paint(){
    const body=$('#personal-coach-model-body'),row=this.row();if(!body||!row)return;
    const head=row.head_model,disabled=this.busy?'disabled':'';
    if(!head){body.innerHTML=`<p class="note">${esc(this.message||this.data?.message||'正在读取默认教练头模…')}</p><p class="note">准备好游戏资源后会自动分配默认头模，即可导入自己的 GLB。</p>`;return;}
    body.innerHTML=`<p class="note">此头模只绑定当前自建教练；生成 APK 时随这名教练一起写入。原版教练和其他复制教练各自保留自己的脸。</p><p class="note coach-head-path">原版骨架模板：${esc(head.template_path.split('/').at(-1))}</p>
      <div class="coach-head-layout"><div><div class="model-stage coach-head-stage" id="personal-coach-model-stage"></div><div class="model-hint">左键旋转 · 滚轮缩放 · 右键平移</div><div class="portrait-actions"><label><input type="checkbox" data-personal-coach-option="wireframe" ${this.viewer?.options.wireframe?'checked':''}>线框</label><label><input type="checkbox" data-personal-coach-option="skeleton" ${this.viewer?.options.skeleton?'checked':''}>骨架</label></div></div>
      <div><h3>${head.asset_id?'已导入自制 GLB':'沿用原版头模'}</h3><p class="note">建议先导出此教练的原版 GLB，在原坐标和骨架上修改后导入。兼容的骨骼权重可以继续驱动原版表情；不同骨架只能使用头颈中性绑定，不能自动获得眨眼、张嘴等表情。</p>
      <div class="portrait-actions"><button class="button secondary" data-personal-coach-model="export-template" ${disabled}>导出原版 GLB 模板</button><button class="button primary" data-personal-coach-model="upload" ${disabled}>导入我的 GLB 脸模</button></div>
      <div class="portrait-actions"><button class="button secondary" data-personal-coach-model="preview" ${disabled}>预览当前头模</button><button class="button subtle" data-personal-coach-model="reset" ${disabled}>恢复原版头模</button></div>
      <p class="note">导入后点击本页底部“保存教练”，再去“APK 实装”勾选这名教练，头模会随教练一起写入。</p></div></div>
      <p class="migration-status" role="status">${esc(this.busy?'正在解码、绑定并检查教练头模…':this.message||'头模将独立绑定到当前自建教练。')}</p>`;
    this.attach().catch(error=>this.toast(error.message,true));
  }
  async attach(){
    const stage=$('#personal-coach-model-stage');if(!stage)return;
    if(!this.module)this.module=import('./model-viewer.js');const {ModelViewer}=await this.module;
    if(!stage.isConnected||stage!==$('#personal-coach-model-stage'))return;
    if(!this.viewer){this.viewer=new ModelViewer(meta=>{if(meta.error)this.toast(meta.error,true);});this.viewer.scene.traverse(light=>{if(light.isDirectionalLight&&light.shadow){light.shadow.bias=-.0005;light.shadow.normalBias=.02;}});}
    this.viewer.attach(stage);
    if(this.result)await this.viewer.update({model:{asset:this.result.asset_id,native_source:this.result.report?.mode==='custom'?null:{path:this.result.path},scale:1,rotation:0,morphs:{}}});
  }
  async load(){
    const row=this.row();if(!row?.head_model)return;const seq=++this.sequence;
    this.busy=true;this.paint();
    try{
      const result=await this.api('coaches/model/preview',{head_model:row.head_model});
      if(this.row()!==row||seq!==this.sequence)return;
      this.result=result;const info=result.face_source||result.report?.face;
      this.message='独立头模预览已载入'+(info?` · ${info.bones} 骨骼 · ${info.lods} 个精度档位`:'')+'。'+(result.report?.rig?.warning||'保存并导出 APK 后，在游戏中选择这名自建教练验收。');
    }finally{if(seq===this.sequence){this.busy=false;this.paint();}}
  }
  async action(action){
    const row=this.row();if(!row?.head_model)return;
    if(action==='preview'){await this.load();return;}
    if(action==='reset'){row.head_model={template_path:row.head_model.template_path};await this.load();return;}
    if(action==='upload'){
      const f=await this.api('dialog',{category:'model'});if(!f.path||this.row()!==row)return;
      const a=await this.api('assets/import',{path:f.path,category:'model'});if(!a.id.endsWith('.glb'))throw Error('请使用内嵌贴图的 GLB 文件');
      if(this.row()!==row)return;const old=structuredClone(row.head_model);row.head_model={template_path:old.template_path,asset_id:a.id};
      try{await this.load();}catch(error){row.head_model=old;this.paint();throw error;}return;
    }
    if(action==='export-template'){
      const result=await this.api('coaches/model/preview',{head_model:{template_path:row.head_model.template_path}});
      const response=await fetch(result.url);if(!response.ok)throw Error('原版 GLB 模板导出失败');
      const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=(row.name||'我的教练')+'-原版骨架模板.glb';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
    }
  }
}
