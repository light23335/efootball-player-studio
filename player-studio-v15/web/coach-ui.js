const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);
export const tactics=[['possession','控球游戏'],['short_counter','快速反击'],['long_counter','长传反击'],['side_attack','外侧进攻'],['long_ball','长传战术']];

export class CoachUI {
  constructor(context){
    Object.assign(this,context);this.query='';this.editing=null;this.custom=this.custom||[];
    document.addEventListener('input',e=>{
      const el=e.target;
      if(el.id==='coach-query'){this.query=el.value;this.renderResults();}
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
      if(e.target.closest('[data-new-coach]'))this.edit();
      if(e.target.closest('[data-cancel-coach]')){this.editing=null;this.rerender();}
      if(e.target.closest('[data-save-coach]'))this.save().catch(e=>this.toast(e.message,true));
      if(e.target.closest('[data-upload-coach-portrait]'))this.uploadPortrait().catch(e=>this.toast(e.message,true));
      if(e.target.closest('[data-clear-coach-portrait]')&&this.editing){this.editing.portrait=null;this.rerender();}
      const use=e.target.closest('[data-use-coach]');if(use)this.choose(use.dataset.useCoach);
      const edit=e.target.closest('[data-edit-coach]');if(edit)this.edit(edit.dataset.editCoach);
    });
  }
  rows(){const rows=new Map([...(this.catalog.coaches||[]),...this.custom,...(this.project().custom_coaches||[])].map(c=>[c.id,c]));return [...rows.values()];}
  effectText(row){return Object.entries(row.effects||{}).filter(([,v])=>v).map(([index,value])=>`${this.catalog.ABILITIES[index]} ${value>0?'+':''}${value}`).join(' · ')||'无已映射的能力加成';}
  portraitImage(row,editor=false){const c=row.portrait;return c?`<div class="coach-portrait ${editor?'editor':''}"><img ${editor?'id="coach-portrait-image"':''} src="/assets/${esc(c.asset_id)}" alt="${editor?'教练头像取景预览':esc(row.name)+'的头像'}" style="object-position:${50+c.x/2}% ${50+c.y/2}%;transform-origin:${50+c.x/2}% ${50+c.y/2}%;transform:scale(${c.zoom})"></div>`:'';}
  portraitControls(row){return `<div class="coach-portrait-editor"><h3>教练头像</h3><div class="portrait-actions"><button class="button secondary" data-upload-coach-portrait>${row.portrait?'更换头像':'上传头像'}</button>${row.portrait?'<button class="button subtle" data-clear-coach-portrait>移除头像</button>':''}</div>${this.portraitImage(row,true)}${row.portrait?`<div class="field-grid three">${[['zoom','缩放',1,4,.01],['x','水平取景',-100,100,1],['y','垂直取景',-100,100,1]].map(([k,label,min,max,step])=>`<label class="field"><span>${label}</span><input type="range" min="${min}" max="${max}" step="${step}" value="${row.portrait[k]}" data-coach-portrait="${k}"></label>`).join('')}</div>`:''}<p class="note">支持 PNG、JPG 和 WebP。头像与教练一起保存、随工程分享；生成 APK 时勾选此教练即可写入游戏。</p></div>`;}
  portraitPreview(){const c=this.editing?.portrait,img=$('#coach-portrait-image');if(!c||!img)return;img.style.objectPosition=`${50+c.x/2}% ${50+c.y/2}%`;img.style.transformOrigin=img.style.objectPosition;img.style.transform=`scale(${c.zoom})`;}
  async uploadPortrait(){const row=this.editing,file=await this.api('dialog',{category:'image'});if(!row||!file.path||this.editing!==row)return;const asset=await this.api('assets/import',{path:file.path,category:'image'});if(this.editing!==row)return;row.portrait={asset_id:asset.id,zoom:1,x:0,y:0};this.rerender();this.toast('头像已载入，调整取景后保存教练');}
  renderPreview(){
    const selected=this.project().preview?.coach_id||'',rows=this.rows(),coach=rows.find(r=>r.id===selected),style=this.project().preview?.team_style||Object.entries(coach?.tactics||{}).sort((a,b)=>b[1]-a[1])[0]?.[0];
    $('#coach-selection').innerHTML=`<label class="field"><span>教练预览</span><select id="preview-coach"><option value="">不使用教练</option>${rows.map(c=>`<option value="${esc(c.id)}" ${selected===c.id?'selected':''}>${c.type==='custom'?'自建 · ':''}${esc(c.name)}${c.pack_title?' · '+esc(c.pack_title):''}</option>`).join('')}${selected&&!rows.some(c=>c.id===selected)?`<option selected value="${esc(selected)}">工程教练未在当前资料中</option>`:''}</select></label><div id="preview-coach-details"></div><button class="text-link" data-page="coaches">浏览 / 新建教练</button>`;
    this.updatePreview();
    if(coach){const label=document.createElement('label');label.className='field coach-style-field';label.innerHTML=`<span>战术体系</span><select id="preview-team-style">${tactics.map(([k,v])=>`<option value="${k}" ${k===style?'selected':''}>${v} · 熟练度 ${coach.tactics[k]}</option>`).join('')}</select>`;$('#coach-selection').insertBefore(label,$('#preview-coach-details'));}
  }
  updatePreview(){
    const row=this.rows().find(c=>c.id===this.project().preview?.coach_id),el=$('#preview-coach-details');if(!el)return;
    el.innerHTML=row?`<p>${esc(this.effectText(row))}</p>${row.unmapped_abilities?.length?'<small>部分原版特征尚未映射，不计入当前总评。</small>':''}`:'<p>当前显示球员自身与增能效果</p>';
  }
  choose(id){
    const row=this.rows().find(c=>c.id===id);
    this.commit(()=>{const p=this.project();p.preview??={};p.preview.coach_id=id||null;
      if(row&&!p.preview.team_style)p.preview.team_style=Object.entries(row.tactics||{}).sort((a,b)=>b[1]-a[1])[0]?.[0];
      if(row?.type==='custom'){p.custom_coaches??=[];p.custom_coaches=p.custom_coaches.filter(c=>c.id!==id);p.custom_coaches.push(structuredClone(row));}
    },'preview-coach');this.rerender();
  }
  edit(id){
    const row=id&&this.rows().find(c=>c.id===id),uuid=row?.type==='custom'?row.uuid:crypto.randomUUID();
    this.editing={...(row?structuredClone(row):{}),id:'custom:'+uuid,uuid,type:'custom',name:row?(row.type==='custom'?row.name:row.name+' · 自建'):'',name_en:row?.name_en||'',tactics:structuredClone(row?.tactics||Object.fromEntries(tactics.map(([k])=>[k,70]))),effects:structuredClone(row?.effects||{})};
    delete this.editing.raw_payload;delete this.editing.unmapped_abilities;delete this.editing.ability_ids;
    this.navigate('coaches');
  }
  render(){
    if(this.editing){const row=this.editing;return `<section class="panel"><div class="panel-title"><h2>${this.custom.some(c=>c.id===row.id)?'编辑自建教练':'新建教练'}</h2><span class="tag">永久身份 ${esc(row.uuid.slice(0,8))}</span></div><div class="panel-body"><div class="field-grid"><label class="field"><span>教练姓名</span><input class="input" data-coach-field="name" value="${esc(row.name)}" maxlength="80" placeholder="输入教练姓名"></label><label class="field"><span>英文名（可选）</span><input class="input" data-coach-field="name_en" value="${esc(row.name_en)}" maxlength="80"></label></div>${this.portraitControls(row)}<h3 style="margin-top:22px">战术熟练度</h3><div class="field-grid three">${tactics.map(([key,label])=>`<label class="field"><span>${label}</span><input class="input" type="number" min="0" max="100" data-coach-field="tactics.${key}" value="${row.tactics[key]||0}"></label>`).join('')}</div><h3 style="margin-top:22px">能力加成</h3><p class="note" style="margin:0 0 14px">每项可填 -20 到 +20；选择这名教练后即时应用到能力与总评预览。战术熟练度采用原包公式，能力加成另外叠加。</p><div class="field-grid three">${Object.entries(this.catalog.ABILITIES).map(([index,label])=>`<label class="field"><span>${esc(label)}</span><input class="input" type="number" min="-20" max="20" data-coach-field="effects.${index}" value="${row.effects[index]||0}"></label>`).join('')}</div><div class="personal-actions"><button class="button primary" data-save-coach>保存并用于预览</button><button class="button secondary" data-cancel-coach>取消</button></div><p class="note">自建教练保存于本机，也随使用它的球员工程携带。保存后可在“APK 球员实装”勾选写入游戏。原生教练最多 4 项 +1 至 +15 的增能；未支持的属性会在导出前明确提示。</p></div></section>`;}
    return `<section class="panel"><div class="panel-title"><h2>教练资料与自建教练</h2><button class="button primary" data-new-coach>＋ 新建教练</button></div><div class="panel-body"><p class="panel-description">当前数据库提供 ${this.catalog.coaches.length.toLocaleString()} 条原版教练资料。按所选战术熟练度计算能力变化，再叠加已映射的能力加成。可以复制原版资料建立自己的教练。</p><div class="search-box">⌕<input id="coach-query" value="${esc(this.query)}" placeholder="搜索教练中文名、英文名或卡包"></div><div id="coach-results"></div></div></section>`;
  }
  activate(page){if(page==='coaches'&&!this.editing)this.renderResults();}
  renderResults(){
    const el=$('#coach-results');if(!el)return;
    const query=this.query.toLocaleLowerCase(),rows=this.rows().filter(r=>[r.name,r.name_en,r.pack_title].join(' ').toLocaleLowerCase().includes(query));
    el.innerHTML=`<p class="note">${rows.length} 名教练</p><div class="coach-grid">${rows.map(row=>`<article class="coach-card">${this.portraitImage(row)}<div class="row-between"><h3>${esc(row.name)}</h3><span class="inline-badge">${row.type==='custom'?'自建':'原版'}</span></div><small>${esc(row.name_en||'')}${row.pack_title?' · '+esc(row.pack_title):''}</small><div class="coach-tactics">${tactics.map(([key,label])=>`<span>${label}<strong>${row.tactics[key]}</strong></span>`).join('')}</div><p>${esc(this.effectText(row))}</p>${row.unmapped_abilities?.length?'<small>未映射的原版特征未计入</small>':''}<div class="personal-actions"><button class="button secondary" data-use-coach="${esc(row.id)}">${this.project().preview?.coach_id===row.id?'当前预览教练':'用于预览'}</button><button class="button subtle" data-edit-coach="${esc(row.id)}">${row.type==='custom'?'编辑教练':'复制为自建'}</button></div></article>`).join('')}</div>`;
  }
  async save(){
    if(this.saving)return;this.saving=true;
    try{const {coach}=await this.api('coaches/save',{coach:this.editing});this.custom=this.custom.filter(c=>c.id!==coach.id);this.custom.push(coach);
      this.commit(()=>{const p=this.project();p.custom_coaches??=[];p.custom_coaches=p.custom_coaches.filter(c=>c.id!==coach.id);p.custom_coaches.push(coach);p.preview??={};p.preview.coach_id=coach.id;if(!p.preview.team_style)p.preview.team_style=Object.entries(coach.tactics).sort((a,b)=>b[1]-a[1])[0][0];},'save-coach');
      this.editing=null;await this.flushSave(true);this.rerender();this.toast('教练已保存，并已用于当前球员预览');
    }finally{this.saving=false;}
  }
}
