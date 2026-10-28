import {renderLinkups,updateLinkup,linkupText} from './coach-links.js';
import {CoachHeads} from './coach-heads.js';
import {CoachModelEditor} from './coach-model.js';
import {coachIdentity,identityField,identityLabel,identityMatches} from './coach-identities.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);
export const tactics=[['possession','控球游戏'],['short_counter','快速反击'],['long_counter','长传反击'],['side_attack','外侧进攻'],['long_ball','长传战术'],['overload','压上进攻']];

export class CoachUI {
  constructor(context){
    this.heads=new CoachHeads(context);
    this.modelEditor=new CoachModelEditor({...context,row:()=>this.editing});
    Object.assign(this,context);this.query='';this.editing=null;this.custom=this.custom||[];this.previewOpen=false;this.previewQuery='';this.page=0;this.pageSize=24;this.originalPortraits=new Map();this.pendingPortraits=new Set();this.identityOpen=null;this.identityQueries={nation:'',team:''};
    document.addEventListener('input',e=>{
      const el=e.target;
      if(el.dataset.coachIdentityQuery&&this.editing){const kind=el.dataset.coachIdentityQuery;this.identityQueries[kind]=el.value;this.renderIdentityResults(kind);}
      if(this.editing&&updateLinkup(this.editing,el,this.catalog.COACH_LINK_TYPES||[])==='render')$('#coach-link-editor').innerHTML=renderLinkups(this.editing,this.catalog);
      if(el.id==='coach-query'){this.query=el.value;this.page=0;this.renderResults();}
      if(el.id==='coach-custom-only'){this.customOnly=el.checked;this.page=0;this.renderResults();}
      if(el.id==='coach-model-only'){this.modelOnly=el.checked;this.page=0;this.renderResults();}
      if(el.id==='preview-coach-query'){this.previewQuery=el.value;this.renderPreviewResults();}
      if(el.dataset.coachPortrait&&this.editing?.portrait){this.editing.portrait[el.dataset.coachPortrait]=Number(el.value);this.portraitPreview();}
      if(el.dataset.coachField&&this.editing){
        const [group,key]=el.dataset.coachField.split('.');
        const value=el.type==='number'?Math.max(Number(el.min),Math.min(Number(el.max),Math.round(Number(el.value)))):el.value;
        if(group==='tactics'||group==='effects')this.editing[group][key]=value;
        else this.editing[group]=value;
      }
    });
    document.addEventListener('change',e=>{if(e.target.id==='preview-coach'){this.choose(e.target.value);}if(e.target.id==='preview-team-style'){this.commit(()=>this.project().preview.team_style=e.target.value,'preview-team-style');this.rerender();}});
    document.addEventListener('click',e=>{
      const toggle=e.target.closest('[data-coach-identity-toggle]');if(toggle&&this.editing){const kind=toggle.dataset.coachIdentityToggle;this.identityOpen=this.identityOpen===kind?null:kind;this.updateIdentityPickers();if(this.identityOpen)$('#coach-identity-query-'+kind)?.focus();return;}
      const option=e.target.closest('[data-coach-identity-option]');if(option&&this.editing){const kind=option.dataset.coachIdentityKind;this.editing[identityField(kind)]=Number(option.dataset.coachIdentityOption);if(kind==='team')this.editing.team_source='custom';this.identityOpen=null;this.identityQueries[kind]='';this.updateIdentityPickers();$('#coach-identity-toggle-'+kind)?.focus();return;}
      const page=e.target.closest('[data-coach-page]');if(page&&!page.disabled){this.page+=Number(page.dataset.coachPage);this.renderResults();$('#coach-results')?.scrollIntoView({block:'start'});return;}
      if(e.target.closest('[data-coach-picker]')){this.previewOpen=!this.previewOpen;this.renderPreview();if(this.previewOpen)$('#preview-coach-query')?.focus();return;}
      const preview=e.target.closest('[data-preview-coach]');if(preview){this.previewOpen=false;this.previewQuery='';this.choose(preview.dataset.previewCoach);return;}
      if(e.target.closest('[data-new-coach]'))this.edit();
      if(e.target.closest('[data-cancel-coach]')){this.editing=null;this.rerender();}
      if(e.target.closest('[data-save-coach]'))this.save().catch(e=>this.toast(e.message,true));
      const remove=e.target.closest('[data-delete-coach]');if(remove){this.deletePending=remove.dataset.deleteCoach;this.renderResults();}
      if(e.target.closest('[data-cancel-delete-coach]')){this.deletePending=null;this.renderResults();}
      if(e.target.closest('[data-confirm-delete-coach]'))this.remove(this.deletePending).catch(e=>this.toast(e.message,true));
      if(e.target.closest('[data-upload-coach-portrait]'))this.uploadPortrait().catch(e=>this.toast(e.message,true));
      if(e.target.closest('[data-clear-coach-portrait]')&&this.editing){this.editing.portrait=null;this.rerender();}
      const use=e.target.closest('[data-use-coach]');if(use)this.choose(use.dataset.useCoach);
      const edit=e.target.closest('[data-edit-coach]');if(edit)this.edit(edit.dataset.editCoach);
    });
    document.addEventListener('keydown',e=>{if(e.target.dataset.coachIdentityQuery){const kind=e.target.dataset.coachIdentityQuery;if(e.key==='Escape'){this.identityOpen=null;this.updateIdentityPickers();$('#coach-identity-toggle-'+kind)?.focus();}if(e.key==='Enter'){e.preventDefault();$('#coach-identity-results-'+kind+' [data-coach-identity-option]')?.click();}return;}if(e.target.id!=='preview-coach-query')return;if(e.key==='Escape'){this.previewOpen=false;this.renderPreview();$('#preview-coach-picker')?.focus();}if(e.key==='Enter'){e.preventDefault();$('#preview-coach-results [data-preview-coach]')?.click();}});
  }
  rows(){const rows=new Map([...(this.catalog.coaches||[]),...this.custom,...(this.project().custom_coaches||[])].map(c=>[c.id,c]));return [...rows.values()];}
  effectText(row){return Object.entries(row.effects||{}).filter(([,v])=>v).map(([index,value])=>`${this.catalog.ABILITIES[index]} ${value>0?'+':''}${value}`).join(' · ')||'无已映射的能力加成';}
  identityText(row){const options=this.identities?.()||{};return `国籍：${identityLabel(row,'nation',options)} · 俱乐部：${identityLabel(row,'team',options)}`;}
  identityControls(row){const options=this.identities?.()||{};return `<h3 style="margin-top:22px">国籍与俱乐部</h3><div class="field-grid">${[['nation','国籍 / 地区'],['team','俱乐部']].map(([kind,label])=>`<div class="coach-identity-picker"><span>${label}</span><button type="button" class="coach-picker-toggle" id="coach-identity-toggle-${kind}" data-coach-identity-toggle="${kind}" aria-expanded="${this.identityOpen===kind}" aria-controls="coach-identity-search-${kind}"><span>${esc(identityLabel(row,kind,options))}</span><span aria-hidden="true">⌕</span></button><div id="coach-identity-search-${kind}" ${this.identityOpen===kind?'':'hidden'}><input class="input" type="search" id="coach-identity-query-${kind}" data-coach-identity-query="${kind}" value="${esc(this.identityQueries[kind])}" placeholder="搜索中文名、英文名或编号" aria-label="搜索${label}" autocomplete="off"><div class="coach-identity-results" id="coach-identity-results-${kind}" role="listbox" aria-label="${label}搜索结果">${this.identityResults(kind)}</div></div></div>`).join('')}</div><p class="note">复制原版教练会读取其国籍与可用俱乐部资料；原包没有提供俱乐部时会标明。选择后随教练保存，并写入生成的游戏 APK。</p>`;}
  identityResults(kind){const query=this.identityQueries[kind],rows=identityMatches(this.identities?.()||{},kind,query),selected=this.editing?.[identityField(kind)]??0;return `${!query.trim()?`<button type="button" role="option" aria-selected="${!selected}" data-coach-identity-option="0" data-coach-identity-kind="${kind}">${kind==='nation'?'不设置国籍':'无俱乐部'}</button>`:''}${rows.slice(0,12).map(r=>`<button type="button" role="option" aria-selected="${r.id===selected}" data-coach-identity-option="${r.id}" data-coach-identity-kind="${kind}"><strong>${esc(r.name||r.name_en)}</strong><small>${esc(r.name_en)} · #${r.id}</small></button>`).join('')}<p class="note">${rows.length?'找到 '+rows.length+' 项'+(rows.length>12?'，显示前 12 项，请输入名称缩小范围':''):'没有匹配项，请更换关键词'}</p>`;}
  renderIdentityResults(kind){const el=$('#coach-identity-results-'+kind);if(el)el.innerHTML=this.identityResults(kind);}
  updateIdentityPickers(){for(const kind of ['nation','team']){const button=$('#coach-identity-toggle-'+kind),search=$('#coach-identity-search-'+kind),input=$('#coach-identity-query-'+kind);if(button){button.firstElementChild.textContent=identityLabel(this.editing,kind,this.identities?.()||{});button.setAttribute('aria-expanded',String(this.identityOpen===kind));}if(search)search.hidden=this.identityOpen!==kind;if(input)input.value=this.identityQueries[kind];this.renderIdentityResults(kind);}}
  portraitImage(row,editor=false){const c=row.portrait||this.originalPortraits.get(String(row.id));return c?.asset_id?`<div class="coach-portrait ${editor?'editor':''}"><img ${editor?'id="coach-portrait-image"':''} src="/assets/${esc(c.asset_id)}" alt="${editor?'教练头像取景预览':esc(row.name)+'的游戏头像'}" style="object-position:${50+c.x/2}% ${50+c.y/2}%;transform-origin:${50+c.x/2}% ${50+c.y/2}%;transform:scale(${c.zoom})"></div>`:editor?'':`<div class="coach-avatar-placeholder" title="${esc(c?.message||(row.type==='custom'?'可以编辑教练并上传头像':'正在读取原版头像'))}">${row.type==='custom'?'未上传头像':c?.missing?'无独立头像':c?.unavailable?'头像暂未就绪':'头像读取中'}</div>`;}
  syncPortraitScope(){const key=this.resourceKey?.()||'';if(key!==this.portraitScope){this.portraitScope=key;this.originalPortraits.clear();}}
  async loadPortraits(rows){
    this.syncPortraitScope();const scope=this.portraitScope;
    const ids=rows.filter(r=>{const cached=this.originalPortraits.get(String(r.id));return r.type!=='custom'&&(!cached||cached.retryAt<Date.now())&&!this.pendingPortraits.has(String(r.id));}).slice(0,24).map(r=>String(r.id));if(!ids.length)return;
    ids.forEach(id=>this.pendingPortraits.add(id));
    try{const result=await this.api('coaches/portraits',{ids});if(scope!==this.portraitScope)return;for(const id of ids){const portrait=result.portraits[id]||{unavailable:true,message:result.message||'原版头像未能读取'};if(portrait.unavailable)portrait.retryAt=Date.now()+30000;this.originalPortraits.set(id,portrait);}this.updatePortraitElements();}
    catch(error){if(scope===this.portraitScope){for(const id of ids)this.originalPortraits.set(id,{unavailable:true,message:error.message,retryAt:Date.now()+30000});this.updatePortraitElements();}}
    finally{ids.forEach(id=>this.pendingPortraits.delete(id));}
  }
  updatePortraitElements(){for(const el of document.querySelectorAll('[data-native-coach-portrait]')){const row=this.rows().find(r=>String(r.id)===el.dataset.nativeCoachPortrait);if(row)el.innerHTML=this.portraitImage(row);}}
  resultPage(){const query=this.query.trim().toLocaleLowerCase(),rows=this.rows().filter(r=>(!this.customOnly||r.type==='custom')&&(!this.modelOnly||this.hasHead(r))&&[r.name,r.name_en,r.pack_title,r.id].join(' ').toLocaleLowerCase().includes(query)),pages=Math.max(1,Math.ceil(rows.length/this.pageSize));this.page=Math.max(0,Math.min(this.page,pages-1));return {total:rows.length,pages,rows:rows.slice(this.page*this.pageSize,(this.page+1)*this.pageSize)};}
  pagination(result){return `<div class="coach-pagination"><p class="note">共 ${result.total} 名教练 · 第 ${this.page+1} / ${result.pages} 页 · 每页 ${this.pageSize} 名</p><div class="welcome-actions"><button class="button secondary" data-coach-page="-1" ${this.page?'':'disabled'}>上一页</button><button class="button secondary" data-coach-page="1" ${this.page+1<result.pages?'':'disabled'}>下一页</button></div></div>`;}
  portraitControls(row){return `<div class="coach-portrait-editor"><h3>教练头像</h3><div class="portrait-actions"><button class="button secondary" data-upload-coach-portrait>${row.portrait?'更换头像':'上传头像'}</button>${row.portrait?'<button class="button subtle" data-clear-coach-portrait>移除头像</button>':''}</div>${this.portraitImage(row,true)}${row.portrait?`<div class="field-grid three">${[['zoom','缩放',1,4,.01],['x','水平取景',-100,100,1],['y','垂直取景',-100,100,1]].map(([k,label,min,max,step])=>`<label class="field"><span>${label}</span><input type="range" min="${min}" max="${max}" step="${step}" value="${row.portrait[k]}" data-coach-portrait="${k}"></label>`).join('')}</div>`:''}<p class="note">支持 PNG、JPG 和 WebP。头像与教练一起保存、随工程分享；生成 APK 时勾选此教练即可写入游戏。</p></div>`;}
  portraitPreview(){const c=this.editing?.portrait,img=$('#coach-portrait-image');if(!c||!img)return;img.style.objectPosition=`${50+c.x/2}% ${50+c.y/2}%`;img.style.transformOrigin=img.style.objectPosition;img.style.transform=`scale(${c.zoom})`;}
  async uploadPortrait(){const row=this.editing,file=await this.api('dialog',{category:'image'});if(!row||!file.path||this.editing!==row)return;const asset=await this.api('assets/import',{path:file.path,category:'image'});if(this.editing!==row)return;row.portrait={asset_id:asset.id,zoom:1,x:0,y:0};this.rerender();this.toast('头像已载入，调整取景后保存教练');}
  renderPreview(){
    this.syncPortraitScope();
    const selected=this.project().preview?.coach_id||'',rows=this.rows(),coach=rows.find(r=>r.id===selected),style=this.project().preview?.team_style||Object.entries(coach?.tactics||{}).sort((a,b)=>b[1]-a[1])[0]?.[0];
    const focused=document.activeElement?.id==='preview-coach-query',selection=focused?document.activeElement.selectionStart:null;
    $('#coach-selection').innerHTML=`<div class="coach-picker"><span>教练预览</span><button type="button" id="preview-coach-picker" class="coach-picker-toggle" data-coach-picker aria-expanded="${this.previewOpen}" aria-controls="preview-coach-search"><span>${esc(coach?.name||(selected?'工程教练未在当前资料中':'不使用教练'))}</span><span aria-hidden="true">⌕</span></button><div id="preview-coach-search" ${this.previewOpen?'':'hidden'}><label class="field"><span class="sr-only">搜索预览教练</span><input class="input" id="preview-coach-query" type="search" placeholder="搜索中文名、英文名或卡包" value="${esc(this.previewQuery)}" autocomplete="off" aria-controls="preview-coach-results"></label><div id="preview-coach-results" role="listbox" aria-label="教练搜索结果"></div></div></div><div id="preview-coach-details"></div><button class="text-link" data-page="coaches">浏览 / 新建教练</button>`;
    this.renderPreviewResults();
    if(focused&&this.previewOpen){$('#preview-coach-query').focus();if(selection!==null)try{$('#preview-coach-query').setSelectionRange(selection,selection);}catch{}}
    this.updatePreview();
    if(coach){const label=document.createElement('label');label.className='field coach-style-field';label.innerHTML=`<span>战术体系</span><select id="preview-team-style">${tactics.map(([k,v])=>`<option value="${k}" ${k===style?'selected':''}>${v} · 熟练度 ${coach.tactics[k]}</option>`).join('')}</select>`;$('#coach-selection').insertBefore(label,$('#preview-coach-details'));}
    if(coach)this.loadPortraits([coach]);
  }
  updatePreview(){
    const row=this.rows().find(c=>c.id===this.project().preview?.coach_id),el=$('#preview-coach-details');if(!el)return;
    el.innerHTML=row?`<div class="preview-coach-face" data-native-coach-portrait="${esc(row.id)}">${this.portraitImage(row)}</div><p class="note">${esc(this.identityText(row))}</p><p>${esc(this.effectText(row))}</p><p class="note">${esc(linkupText(row,this.catalog))}</p>${row.unmapped_abilities?.length?'<small>部分原版特征尚未映射，不计入当前总评。</small>':''}`:'<p>当前显示球员自身与增能效果</p>';
  }
  previewMatches(){const query=this.previewQuery.trim().toLocaleLowerCase();return this.rows().filter(row=>[row.name,row.name_en,row.pack_title,row.id].join(' ').toLocaleLowerCase().includes(query));}
  renderPreviewResults(){
    const el=$('#preview-coach-results');if(!el||!this.previewOpen)return;
    const rows=this.previewMatches(),selected=this.project().preview?.coach_id||'';
    el.innerHTML=`<button type="button" role="option" aria-selected="${!selected}" data-preview-coach="">不使用教练</button>${rows.slice(0,40).map(row=>`<button type="button" role="option" aria-selected="${row.id===selected}" data-preview-coach="${esc(row.id)}"><strong>${esc(row.name)}</strong><small>${row.type==='custom'?'自建 · ':''}${esc(row.name_en||row.pack_title||'')}</small></button>`).join('')}<p class="note">${rows.length?'找到 '+rows.length+' 名'+(rows.length>40?'，显示前 40 名，请输入关键词缩小范围':''):'没有匹配的教练，请更换关键词'}</p>`;
  }
  choose(id){
    const row=this.rows().find(c=>c.id===id);
    this.commit(()=>{const p=this.project();p.preview??={};p.preview.coach_id=id||null;
      if(row&&!p.preview.team_style)p.preview.team_style=Object.entries(row.tactics||{}).sort((a,b)=>b[1]-a[1])[0]?.[0];
      if(row?.type==='custom'){p.custom_coaches??=[];p.custom_coaches=p.custom_coaches.filter(c=>c.id!==id);p.custom_coaches.push(structuredClone(row));}
    },'preview-coach');this.rerender();
  }
  edit(id){
    this.modelEditor.reset();
    const row=id&&this.rows().find(c=>c.id===id),uuid=row?.type==='custom'?row.uuid:crypto.randomUUID();
    this.editing={...(row?structuredClone(row):{}),id:'custom:'+uuid,uuid,type:'custom',name:row?(row.type==='custom'?row.name:row.name+' · 自建'):'',name_en:row?.name_en||'',tactics:structuredClone(row?.tactics||Object.fromEntries(tactics.map(([k])=>[k,70]))),effects:structuredClone(row?.effects||{})};
    Object.assign(this.editing,coachIdentity(row));this.identityOpen=null;this.identityQueries={nation:'',team:''};
    if(!this.editing.portrait&&this.originalPortraits.get(String(id))?.asset_id)this.editing.portrait=structuredClone(this.originalPortraits.get(String(id)));
    delete this.editing.raw_payload;delete this.editing.unmapped_abilities;delete this.editing.ability_ids;
    this.navigate('coaches');
  }
  render(){return this.heads.render()+this.renderCoach();}
  renderCoach(){
    if(this.editing){const row=this.editing;return `<section class="panel"><div class="panel-title"><h2>${this.custom.some(c=>c.id===row.id)?'编辑自建教练':'新建教练'}</h2><span class="tag">永久身份 ${esc(row.uuid.slice(0,8))}</span></div><div class="panel-body"><div class="field-grid"><label class="field"><span>教练姓名</span><input class="input" data-coach-field="name" value="${esc(row.name)}" maxlength="80" placeholder="输入教练姓名"></label><label class="field"><span>英文名（可选）</span><input class="input" data-coach-field="name_en" value="${esc(row.name_en)}" maxlength="80"></label></div>${this.identityControls(row)}${this.portraitControls(row)}${this.modelEditor.render()}<div id="coach-link-editor">${renderLinkups(row,this.catalog)}</div><h3 style="margin-top:22px">战术熟练度</h3><div class="field-grid three">${tactics.map(([key,label])=>`<label class="field"><span>${label}</span><input class="input" type="number" min="0" max="100" data-coach-field="tactics.${key}" value="${row.tactics[key]||0}"></label>`).join('')}</div><h3 style="margin-top:22px">能力加成</h3><p class="note" style="margin:0 0 14px">每项可填 -20 到 +20；选择这名教练后即时应用到能力与总评预览。战术熟练度采用原包公式，能力加成另外叠加。</p><div class="field-grid three">${Object.entries(this.catalog.ABILITIES).map(([index,label])=>`<label class="field"><span>${esc(label)}</span><input class="input" type="number" min="-20" max="20" data-coach-field="effects.${index}" value="${row.effects[index]||0}"></label>`).join('')}</div><div class="personal-actions"><button class="button primary" data-save-coach>保存并用于预览</button><button class="button secondary" data-cancel-coach>取消</button></div><p class="note">自建教练保存于本机，也随使用它的球员工程携带。保存后可在“APK 球员实装”勾选写入游戏。实装支持全部 26 项能力中最多 2 项原生增能，每项 +1 至 +20，另有 2 项心有灵犀；负数仅用于软件预览。</p></div></section>`;}
    return `<section class="panel"><div class="panel-title"><h2>教练资料与自建教练</h2><button class="button primary" data-new-coach>＋ 新建教练</button></div><div class="panel-body"><p class="panel-description">当前数据库提供 ${this.catalog.coaches.length.toLocaleString()} 条原版教练资料。按所选战术熟练度计算能力变化，再叠加已映射的能力加成。可以复制原版资料建立自己的教练。头像从已准备的游戏资源按需读取；没有独立头像的教练会标明。</p><div class="search-box">⌕<input id="coach-query" value="${esc(this.query)}" placeholder="搜索教练中文名、英文名、卡包或编号"></div><label class="switch-label"><input type="checkbox" id="coach-custom-only" ${this.customOnly?'checked':''}>只看自建教练（${this.rows().filter(c=>c.type==='custom').length}）</label><label class="switch-label"><input type="checkbox" id="coach-model-only" ${this.modelOnly?'checked':''}>只看有三维头模的教练</label><div id="coach-results"></div></div></section>`;
  }
  activate(page){if(page==='coaches'&&!this.editing)this.renderResults();this.heads.activate(page).then(()=>{if(page==='coaches'&&!this.editing)this.renderResults();});this.modelEditor.activate(page);}
  hasHead(row){return !!row.head_model||this.heads.rows.some(r=>r.coach_ids.includes(String(row.type==='custom'?row.native_source_id:row.id)));}
  renderResults(){
    const el=$('#coach-results');if(!el)return;
    this.syncPortraitScope();
    const result=this.resultPage(),rows=result.rows;
    el.innerHTML=`${this.pagination(result)}<div class="coach-grid">${rows.map(row=>`<article class="coach-card"><div data-native-coach-portrait="${esc(row.id)}">${this.portraitImage(row)}</div><div class="row-between"><h3>${esc(row.name)}</h3><span class="inline-badge">${row.type==='custom'?'自建':'原版'}${this.hasHead(row)?' · 三维头模':''}</span></div><small>${esc(row.name_en||'')}${row.pack_title?' · '+esc(row.pack_title):''}</small><p class="note">${esc(this.identityText(row))}</p><div class="coach-tactics">${tactics.map(([key,label])=>`<span>${label}<strong>${row.tactics[key]}</strong></span>`).join('')}</div><p>${esc(this.effectText(row))}</p><p class="note">${esc(linkupText(row,this.catalog))}</p>${row.unmapped_abilities?.length?'<small>未映射的原版特征未计入</small>':''}<div class="personal-actions"><button class="button secondary" data-use-coach="${esc(row.id)}">${this.project().preview?.coach_id===row.id?'当前预览教练':'用于预览'}</button><button class="button subtle" data-coach-head-view="${esc(row.type==='custom'?row.native_source_id||'custom':row.id)}">查看三维头模</button><button class="button subtle" data-edit-coach="${esc(row.id)}">${row.type==='custom'?'编辑教练':'复制为自建'}</button>${this.deleteControls(row)}</div></article>`).join('')||'<p class="no-matches">没有匹配的教练，请更换关键词。</p>'}</div>${result.pages>1?this.pagination(result):''}`;
    this.loadPortraits(rows);
  }
  async save(){
    if(this.saving)return;this.saving=true;
    try{const {coach}=await this.api('coaches/save',{coach:this.editing});this.custom=this.custom.filter(c=>c.id!==coach.id);this.custom.push(coach);
      this.commit(()=>{const p=this.project();p.custom_coaches??=[];p.custom_coaches=p.custom_coaches.filter(c=>c.id!==coach.id);p.custom_coaches.push(coach);p.preview??={};p.preview.coach_id=coach.id;if(!p.preview.team_style)p.preview.team_style=Object.entries(coach.tactics).sort((a,b)=>b[1]-a[1])[0][0];},'save-coach');
      this.editing=null;await this.flushSave(true);this.rerender();this.toast('教练已保存，并已用于当前球员预览');
    }finally{this.saving=false;}
  }
  deleteControls(row){
    if(row.type!=='custom')return '';
    if(this.deletePending!==row.id)return `<button class="button subtle" data-delete-coach="${esc(row.id)}">删除教练</button>`;
    return `<div class="coach-delete-confirm"><p>删除“${esc(row.name)}”及本机球员工程中的对应引用？将先备份。已导出的 APK 和游戏内教练保持原状。</p><button class="button danger" data-confirm-delete-coach ${this.deleting?'disabled':''}>确认删除</button><button class="button secondary" data-cancel-delete-coach ${this.deleting?'disabled':''}>取消</button></div>`;
  }
  async remove(id){
    const row=this.rows().find(c=>c.id===id&&c.type==='custom');if(!row||this.deleting)return;
    this.deleting=true;this.renderResults();
    try{
      await this.flushSave(true);
      const result=await this.api('coaches/delete',{uuid:row.uuid,confirmed:true});
      this.custom=this.custom.filter(c=>c.id!==id);this.editing=null;this.deletePending=null;
      this.onCoachDeleted?.(row.uuid);
      this.replaceProject(result.project);
      this.rerender();this.toast(`已删除教练，并清理 ${result.affected_projects} 份已保存球员工程中的引用。原资料已备份。`);
      if(result.unreadable_projects.length)this.toast(`另有 ${result.unreadable_projects.length} 份无法读取的工程未处理，可在“我的球员”查看。`,true);
    }finally{this.deleting=false;this.renderResults();}
  }
}
