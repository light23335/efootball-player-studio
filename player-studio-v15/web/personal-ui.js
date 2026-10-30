import {cardTypeName} from './domain.js';
import {choosePlayerAction} from './player-prompts.js';
import {PlayerFoldersUI} from './player-folders.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);

export class PersonalUI {
  constructor(context){
    Object.assign(this,context);this.query='';this.request=0;this.offset=0;this.pageSize=60;
    this.folders=new PlayerFoldersUI({api:this.api,toast:this.toast,changed:()=>{this.offset=0;return this.refresh().catch(error=>this.toast(error.message,true));}});
    document.addEventListener('input',e=>{if(e.target.id==='personal-query'){this.query=e.target.value;this.offset=0;clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),200);}});
    document.addEventListener('click',e=>{
      const page=e.target.closest('[data-personal-page]');if(page&&!page.disabled){this.offset=Math.max(0,this.offset+Number(page.dataset.personalPage)*this.pageSize);this.refresh().catch(e=>this.toast(e.message,true));return;}
      const open=e.target.closest('[data-personal-open]'),exported=e.target.closest('[data-personal-export]');
      if(open)this.open(open.dataset.personalOpen).catch(e=>this.toast(e.message,true));
      if(exported)this.export(exported.dataset.personalExport).catch(e=>this.toast(e.message,true));
      const removed=e.target.closest('[data-personal-delete]');if(removed)this.remove(removed.dataset.personalDelete).catch(e=>this.toast(e.message,true));
    });
  }
  render(){return `<section class="panel"><div class="panel-title"><h2>我的球员</h2><span class="tag">本机球员库</span></div><div class="panel-body"><p class="panel-description">点击顶部“保存球员”，将当前设计保存到这里。同一身份再次保存会更新原条目；新建球员会分配新的永久身份。每名球员分别保留能力、培养方案、技能、卡面、模型和自定义增能。</p><div class="copy-player-entry"><button class="button primary" data-page="library">从已有球员复制</button><p class="note">复制到独立自建球员槽位，修改和保存不会影响原球员数据。</p></div>${this.folders.render()}<div class="search-box">⌕<input id="personal-query" value="${esc(this.query)}" placeholder="搜索我的球员姓名或永久身份"></div><p id="personal-total" class="note">正在读取…</p><details id="personal-read-errors" hidden><summary>查看未读出文件的原因</summary><ul id="personal-error-list"></ul></details><div id="personal-results"></div><div id="personal-pagination" class="welcome-actions"></div><p class="note">这里保存编辑器设计与培养方案。游戏中的实际经验、战绩和培养进度由游戏存档保存。</p></div></section>`;}
  activate(page){this.active=page==='personal';if(this.active)this.refresh().catch(e=>this.toast(e.message,true));}
  async refresh(){
    const request=++this.request;await this.folders.load();
    if(!this.active||request!==this.request)return;
    const data=await this.api('players/list',{query:this.query,offset:this.offset,limit:this.pageSize,folder_id:this.folders.selected||null});
    if(!this.active||request!==this.request||!$('#personal-results'))return;
    if(this.offset&&this.offset>=data.total){this.offset=Math.max(0,Math.ceil(data.total/this.pageSize)*this.pageSize-this.pageSize);return this.refresh();}
    this.rows=data.rows;
    $('#personal-pagination').innerHTML=`<button class="button secondary" data-personal-page="-1" ${this.offset?'':'disabled'}>上一页</button><span>第 ${Math.floor(this.offset/this.pageSize)+1} / ${Math.max(1,Math.ceil(data.total/this.pageSize))} 页</span><button class="button secondary" data-personal-page="1" ${this.offset+this.pageSize<data.total?'':'disabled'}>下一页</button>`;
    $('#personal-total').textContent=`已保存 ${data.saved_total??data.total} / ${data.capacity??10000} 名球员${this.folders.selected?' · 当前分类 '+data.total+' 名':this.query?' · 搜索匹配 '+data.total+' 名':''}${data.errors.length?' · '+data.errors.length+' 份文件需核对，原文件已保留':''}`;
    $('#personal-read-errors').hidden=!data.errors.length;
    $('#personal-error-list').innerHTML=data.errors.map(row=>`<li><code>${esc(row.file)}</code>：${esc(row.message)}</li>`).join('');
    $('#personal-results').innerHTML=data.rows.length?`<div class="personal-player-grid">${data.rows.map(r=>`<article class="personal-player"><div class="personal-avatar">${r.portrait?`<img src="/assets/${esc(r.portrait)}" alt="${esc(r.name)}的原版球员图">`:'<span>未选择卡面</span>'}<strong>${r.overall.current}<small>${esc(r.position)}</small></strong></div><div class="personal-player-body"><h3>${esc(r.display_name||r.name)}</h3><div class="native-tags"><span>${esc(cardTypeName(r.card_type))}</span><span>Lv.${r.level} / ${r.max_level}</span>${r.folder_name?`<span class="personal-folder-tag" title="${esc(r.folder_name)}">▱ ${esc(r.folder_name)}</span>`:''}${r.package_id===this.project().package_id?'<span>正在编辑</span>':''}</div><p>基础 ${r.overall.base} · 培养后 ${r.overall.trained} · 含增能 ${r.overall.before_coach}${r.overall.coach_id?' · 教练 '+r.overall.current:''}</p><small class="muted">${esc(r.package_id)}<br>保存于 ${esc(r.saved_at)}</small><div class="personal-actions"><button class="button secondary" data-personal-open="${r.package_id}">打开编辑</button><button class="button subtle" data-personal-export="${r.package_id}">导出工程</button>${this.folders.selected&&this.folders.selected!=='unfiled'?`<button class="button subtle" data-folder-remove-player="${r.package_id}">移出文件夹</button>`:''}<button class="button danger" data-personal-delete="${r.package_id}">删除球员</button></div></div></article>`).join('')}</div>`:'<div class="loading-state">'+(this.query?'没有符合条件的自建球员':this.folders.selected==='unfiled'?'所有已保存球员都已分类':this.folders.selected?'文件夹中还没有球员，点击“添加已有球员”继续添加。':'还没有保存的球员。编辑完成后点击顶部“保存球员”。')+'</div>';
  }
  async save(){await this.flushSave(true);const data=await this.api('players/save',{project:this.project()});this.toast(`已保存到我的球员 · 计算总评 ${data.overall.current}`);if(this.active)await this.refresh();return data;}
  async remove(id){
    if(this.deleting)return;
    const row=this.rows?.find(r=>r.package_id===id);if(!row)return;
    this.deleting=true;
    try{
      const confirm=this.confirmDelete||choosePlayerAction;
      if(await confirm('确认删除自建球员？',`将删除“${row.display_name||row.name}”（${id}）的本机球员记录，并从已保存卡包移除。${id===this.project().package_id?'当前编辑内容也会清空。':''}已导出的文件和游戏内球员不受影响；素材与删除前备份保留。`,[{id:'delete',label:'确认删除这名球员',danger:true}])!=='delete')return;
      await this.flushSave(true);
      const data=await this.api('players/delete',{package_id:id,confirmed:true});
      this.replaceProject(data.project);this.onPlayerDeleted?.(id);this.rerender();
      this.toast(`已删除 ${row.display_name||row.name}${data.removed_pack_members?'，已从 '+data.removed_pack_members+' 个卡包位置移除':''}`);
      if(data.folder_warning)this.toast(data.folder_warning,true);
    }finally{this.deleting=false;}
  }
  async open(id){if(this.beforeOpenPlayer&&!await this.beforeOpenPlayer(id))return;await this.flushSave(true);const data=await this.api('players/open',{package_id:id});this.replaceProject(data.project);this.navigate('profile');this.toast('已打开自建球员，永久身份和编辑内容已恢复');}
  async export(id){const data=await this.api('players/export',{package_id:id});const a=document.createElement('a');a.href=data.url;a.download=data.filename;a.click();this.toast('已导出球员工程，包含所选资源');}
}
