import {cardTypeName} from './domain.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);

export class PersonalUI {
  constructor(context){
    Object.assign(this,context);this.query='';this.request=0;
    document.addEventListener('input',e=>{if(e.target.id==='personal-query'){this.query=e.target.value;clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),200);}});
    document.addEventListener('click',e=>{
      const open=e.target.closest('[data-personal-open]'),exported=e.target.closest('[data-personal-export]');
      if(open)this.open(open.dataset.personalOpen).catch(e=>this.toast(e.message,true));
      if(exported)this.export(exported.dataset.personalExport).catch(e=>this.toast(e.message,true));
    });
  }
  render(){return `<section class="panel"><div class="panel-title"><h2>我的球员</h2><span class="tag">本机球员库</span></div><div class="panel-body"><p class="panel-description">点击顶部“保存球员”，将当前设计保存到这里。同一身份再次保存会更新原条目；新建球员会分配新的永久身份。每名球员分别保留能力、培养方案、技能、卡面、模型和自定义增能。</p><div class="search-box">⌕<input id="personal-query" value="${esc(this.query)}" placeholder="搜索我的球员姓名或永久身份"></div><p id="personal-total" class="note">正在读取…</p><div id="personal-results"></div><p class="note">这里保存的是编辑器设计与培养模拟。游戏中实际获得的经验和培养进度，请从最新存档导出 .efplayer。</p></div></section>`;}
  activate(page){this.active=page==='personal';if(this.active)this.refresh().catch(e=>this.toast(e.message,true));}
  async refresh(){
    const request=++this.request,data=await this.api('players/list',{query:this.query});
    if(!this.active||request!==this.request||!$('#personal-results'))return;
    $('#personal-total').textContent=`已保存 ${data.total} 名球员${data.errors.length?' · '+data.errors.length+' 份文件需核对，原文件已保留':''}`;
    $('#personal-results').innerHTML=data.rows.length?`<div class="personal-player-grid">${data.rows.map(r=>`<article class="personal-player"><div class="personal-avatar">${r.portrait?`<img src="/assets/${esc(r.portrait)}" alt="${esc(r.name)}的原版球员图">`:'<span>未选择卡面</span>'}<strong>${r.overall.current}<small>${esc(r.position)}</small></strong></div><div class="personal-player-body"><h3>${esc(r.display_name||r.name)}</h3><div class="native-tags"><span>${esc(cardTypeName(r.card_type))}</span><span>Lv.${r.level} / ${r.max_level}</span>${r.package_id===this.project().package_id?'<span>正在编辑</span>':''}</div><p>基础 ${r.overall.base} · 培养后 ${r.overall.trained} · 含增能 ${r.overall.before_coach}${r.overall.coach_id?' · 教练 '+r.overall.current:''}</p><small class="muted">${esc(r.package_id)}<br>保存于 ${esc(r.saved_at)}</small><div class="personal-actions"><button class="button secondary" data-personal-open="${r.package_id}">打开编辑</button><button class="button subtle" data-personal-export="${r.package_id}">导出工程</button></div></div></article>`).join('')}</div>`:'<div class="loading-state">'+(this.query?'没有符合条件的自建球员':'还没有保存的球员。编辑完成后点击顶部“保存球员”。')+'</div>';
  }
  async save(){await this.flushSave(true);const data=await this.api('players/save',{project:this.project()});this.toast(`已保存到我的球员 · 计算总评 ${data.overall.current}`);if(this.active)await this.refresh();return data;}
  async open(id){if(this.beforeOpenPlayer&&!await this.beforeOpenPlayer(id))return;await this.flushSave(true);const data=await this.api('players/open',{package_id:id});this.replaceProject(data.project);this.navigate('profile');this.toast('已打开自建球员，永久身份和编辑内容已恢复');}
  async export(id){const data=await this.api('players/export',{package_id:id});const a=document.createElement('a');a.href=data.url;a.download=data.filename;a.click();this.toast('已导出球员工程，包含所选资源');}
}
