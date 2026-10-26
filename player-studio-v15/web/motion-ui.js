const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const panel=(title,body)=>`<section class="panel"><div class="panel-title"><h2>${title}</h2></div><div class="panel-body">${body}</div></section>`;

export class MotionUI {
  constructor(context){
    Object.assign(this,context);this.rows=[];this.presets=[];this.query='';this.page=0;this.total=0;this.pages=1;this.request=0;this.view=null;this.message='';
    document.addEventListener('input',e=>{if(e.target.id==='motion-query'){this.query=e.target.value;this.page=0;clearTimeout(this.timer);this.timer=setTimeout(()=>this.search(),250);}});
    document.addEventListener('change',e=>{
      if(e.target.id==='motion-mode'){
        this.view=e.target.value;
        if(this.view==='legacy')this.commit(()=>this.project().motion_style={version:1,mode:'legacy'},'motion-mode');
        this.rerender();
      }
    });
    document.addEventListener('click',e=>{
      const button=e.target.closest('[data-motion-action]');if(!button)return;
      this.action(button).catch(error=>this.feedback(error.message,true));
    });
  }
  selected(){return this.project().motion_style;}
  feedback(message,error=false){this.message=message;const el=document.querySelector('#motion-message');if(el){el.textContent=message;el.classList.toggle('motion-error',error);}this.toast(message,error);}
  render(){
    const p=this.project(),s=this.selected(),mode=this.view||(s?.mode||'legacy'),enabled=s&&s.mode!=='legacy';
    return `<div class="motion-editor">${panel('这张卡的动作风格',`
      <p class="panel-description">为不同时期的卡分别选择动作。游戏里没有的球员，也可以参考原版球员，再保存成自己的预设。</p>
      <label class="field"><span>配置方式</span><select id="motion-mode"><option value="legacy" ${mode==='legacy'?'selected':''}>保持现有配置</option><option value="source" ${mode==='source'?'selected':''}>参考原版球员</option><option value="custom" ${mode==='custom'?'selected':''}>使用我的动作预设</option></select></label>
      <div class="motion-current"><span class="motion-caption">当前已应用</span><strong>${enabled?esc(s.label||s.source_name||'我的动作组合'):'现有配置'}</strong><p>${enabled?`动作参考：${esc(s.source_name||'通用组合')}${s.period?' · '+esc(s.period):''}`:'尚未指定独立动作来源；原有导出行为保持不变。'}</p></div>
      <div class="motion-scope"><strong>本版支持：四项比赛姿态参数继承与导出</strong><p>人物专属动作尚未接入。页面中的球员模型仍是外观预览，不能预览带球动作；手感需在比赛中核对。</p></div>
      <p id="motion-message" class="note" role="status" aria-live="polite">${esc(this.message)}</p>`)}
      ${mode==='source'?panel('选择动作参考',`
        <p class="panel-description">选择具体卡片作为参考。应用时只更新动作配置，能力、技能、模型和卡面分别保留。</p>
        ${p.source_player?.id?'<button class="button secondary" data-motion-action="current-source">使用当前资料来源球员的动作</button>':''}
        <label class="field motion-search"><span>搜索原版球员</span><div class="input-row"><input class="input" id="motion-query" value="${esc(this.query)}" placeholder="输入中文名、英文名或卡片编号"><button class="button secondary" data-motion-action="search">搜索</button></div></label>
        <div id="motion-results" aria-live="polite"><p class="note">正在读取参考球员…</p></div>
        <div class="motion-pagination"><button class="button subtle" data-motion-action="previous">上一页</button><span id="motion-total"></span><button class="button subtle" data-motion-action="next">下一页</button></div>`):''}
      ${mode==='custom'?panel('我的动作预设',`<p class="panel-description">预设可用于任意球员。先从原版选择动作，再用下方名称保存；不同年份可以各存一份。</p><div id="motion-presets"><p class="note">正在读取预设…</p></div>`):''}
      ${enabled?panel('为这套动作命名',`
        <div class="field-grid"><label class="field"><span>这张卡的动作名称</span><input class="input" data-bind="motion_style.label" maxlength="60" value="${esc(s.label||s.source_name)}" placeholder="例如：我的青年边锋"></label><label class="field"><span>时期备注（可选）</span><input class="input" data-bind="motion_style.period" maxlength="60" value="${esc(s.period)}" placeholder="例如：2006–2007"></label></div>
        <div class="motion-actions"><button class="button primary" data-motion-action="save-preset">保存为可复用预设</button><button class="button secondary" data-motion-action="restore">还原参考球员的姿态</button></div>
        <p class="note">当前配置随顶部“保存球员”保存到这张卡。保存为预设后，打开另一张卡即可在“使用我的动作预设”中选用。</p>`):''}
      </div>`;
  }
  activate(page){
    this.active=page==='motion';if(!this.active){this.request++;return;}
    const id=this.project().package_id;
    if(this.cardId!==id){this.cardId=id;this.view=this.selected()?.mode||'legacy';this.message='';this.rows=[];this.query='';this.page=0;this.rerender();return;}
    const mode=this.view||this.selected()?.mode||'legacy';
    if(mode==='source')this.search();
    if(mode==='custom')this.loadPresets();
  }
  async search(){
    if(!this.active)return;
    const request=++this.request,id=this.project().package_id,box=document.querySelector('#motion-results');if(!box)return;
    box.innerHTML='<p class="note">正在读取参考球员…</p>';
    try{
      const result=await this.api('library/search',{query:this.query,page:this.page});
      if(request!==this.request||!this.active||id!==this.project().package_id||!document.querySelector('#motion-results'))return;
      this.rows=result.rows;this.total=result.total;this.pages=result.pages;this.page=result.page;
      box.innerHTML=this.rows.length?`<div class="motion-source-list">${this.rows.map(r=>`<div class="motion-source-row"><div><strong>${esc(r.name)}</strong><small>${esc(r.name_en)} · ${esc(r.position)} · ${esc(r.card_type)}${r.overall?' · 总评 '+esc(r.overall):''}</small><small>卡片 ${esc(r.id)}</small></div><button class="button secondary" data-motion-action="source" data-source-id="${esc(r.id)}">应用动作</button></div>`).join('')}</div>`:'<p class="note">没有找到球员，请换一个姓名或编号。自创球员可以选择任意原版球员作为参考。</p>';
      document.querySelector('#motion-total').textContent=`${this.total.toLocaleString()} 张卡 · ${this.page+1} / ${Math.max(1,this.pages)} 页`;
      document.querySelector('[data-motion-action="previous"]').disabled=this.page===0;
      document.querySelector('[data-motion-action="next"]').disabled=this.page+1>=this.pages;
    }catch(error){if(request!==this.request||!this.active)return;box.textContent='参考资料读取失败：'+error.message;}
  }
  async loadPresets(){
    const id=this.project().package_id;
    try{const result=await this.api('motion/presets',{});if(!this.active||id!==this.project().package_id)return;this.presets=result.rows;this.renderPresets();}
    catch(error){const el=document.querySelector('#motion-presets');if(el)el.textContent='预设读取失败：'+error.message;}
  }
  renderPresets(){
    const el=document.querySelector('#motion-presets');if(!el)return;
    el.innerHTML=this.presets.length?this.presets.map(r=>`<div class="motion-source-row"><div><strong>${esc(r.label)}</strong><small>参考：${esc(r.style.source_name||'通用组合')}${r.style.period?' · '+esc(r.style.period):''}</small></div><button class="button secondary" data-motion-action="preset" data-preset-id="${esc(r.id)}">应用预设</button></div>`).join(''):'<p class="note">还没有动作预设。先选择“参考原版球员”，应用动作后保存自己的预设。</p>';
  }
  async action(button){
    const action=button.dataset.motionAction;
    if(action==='search'){clearTimeout(this.timer);this.page=0;return this.search();}
    if(action==='previous'||action==='next'){this.page=Math.max(0,this.page+(action==='next'?1:-1));return this.search();}
    if(action==='source'||action==='current-source'){
      const id=action==='source'?button.dataset.sourceId:this.project().source_player?.id;
      const cardId=this.project().package_id;button.disabled=true;
      try{
        const selected=await this.api('motion/source',{id});
        if(cardId!==this.project().package_id)return;
        this.commit(()=>this.project().motion_style=selected,'motion-source');this.view='source';this.message='已应用参考姿态。可修改名称，区分不同年份的卡。';this.rerender();
      }finally{button.disabled=false;}
    }
    if(action==='restore'){
      const s=this.selected();if(!s?.original_parameters)return this.feedback('当前预设没有原始参考值，请重新选择参考球员。',true);
      this.commit(()=>{this.project().motion_style.parameters=structuredClone(s.original_parameters);},'motion-restore');this.feedback('已还原参考球员的姿态参数。');
    }
    if(action==='save-preset'){
      const selected=structuredClone(this.selected()),label=(selected?.label||'').trim();
      if(!label)return this.feedback('请先填写动作名称。',true);
      button.disabled=true;
      try{const result=await this.api('motion/presets/save',{style:selected,label});this.presets=result.rows;this.feedback('动作预设已保存，其他卡也可以选用。');this.renderPresets();}finally{button.disabled=false;}
    }
    if(action==='preset'){
      const row=this.presets.find(r=>r.id===button.dataset.presetId);if(!row)return;
      this.commit(()=>{this.project().motion_style={...structuredClone(row.style),mode:'custom',label:row.label,preset_id:row.id};},'motion-preset');this.view='custom';this.message='已应用预设；只改变当前这张卡的动作配置。';this.rerender();
    }
  }
}
