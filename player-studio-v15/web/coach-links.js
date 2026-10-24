const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roleLabels={source:'核心球员',target:'关键球员'};
const positionLabels=['门将','中后卫','左后卫','右后卫','后腰','中前卫','左前卫','右前卫','前腰','左边锋','右边锋','影锋','中锋'];

export function renderLinkups(row,catalog){
  const types=catalog.COACH_LINK_TYPES||[],schema=catalog.COACH_LINK_SCHEMA||{};
  const styles=schema.style_labels||{...catalog.PLAY_STYLES.attack,...catalog.PLAY_STYLES.defense};
  return `<h3>心有灵犀</h3><p class="note">从原游戏已有组合选择效果，可分别修改核心球员与关键球员的位置、比赛风格。每名教练最多两项，条件分别保存。</p>${[0,1].map(slot=>{
    const config=row.linkups?.[slot];
    return `<section class="coach-link-slot"><label class="field"><span>心有灵犀 ${slot+1}</span><select data-link-slot="${slot}" data-link-field="template_id"><option value="">不使用</option>${types.map(t=>`<option value="${t.template_id}" ${config?.template_id===t.template_id?'selected':''}>${esc(t.label)}${t.coaches?.length?' · '+esc(t.coaches.slice(0,2).join(' / ')):''}</option>`).join('')}</select></label>${config?`<div class="field-grid">${Object.entries(roleLabels).map(([role,label])=>`<div><strong>${label}</strong><fieldset class="coach-link-positions"><legend>可触发的位置（可多选）</legend>${catalog.POSITIONS.map((pos,index)=>`<label><input type="checkbox" data-link-slot="${slot}" data-link-role="${role}" data-link-field="position" value="${index}" ${config[role+'_positions']?.includes(index)?'checked':''}>${esc(positionLabels[index])} (${pos})</label>`).join('')}</fieldset><label class="field"><span>比赛风格</span><select data-link-slot="${slot}" data-link-role="${role}" data-link-field="style">${Array.from({length:36},(_,index)=>`<option value="${index}" ${config[role+'_style']===index?'selected':''}>${esc(styles[index]||'原生风格 '+index)}</option>`).join('')}</select></label></div>`).join('')}</div>`:''}</section>`;
  }).join('')}`;
}

export function updateLinkup(row,el,types){
  if(el.dataset.linkSlot===undefined)return null;
  const slot=Number(el.dataset.linkSlot),field=el.dataset.linkField;
  if(![0,1].includes(slot))return null;
  row.linkups??=[null,null];
  if(field==='template_id'){
    const source=types.find(t=>t.template_id===Number(el.value));
    row.linkups[slot]=el.value&&source?structuredClone(Object.fromEntries(Object.entries(source).filter(([key])=>['template_id','source_positions','target_positions','source_style','target_style'].includes(key)))):null;
    return 'render';
  }
  const config=row.linkups[slot],role=el.dataset.linkRole;if(!config||!['source','target'].includes(role))return null;
  if(field==='style')config[role+'_style']=Number(el.value);
  if(field==='position'){
    const key=role+'_positions',position=Number(el.value);
    config[key]=[...new Set(config[key].filter(p=>p!==position).concat(el.checked?[position]:[]))].sort((a,b)=>a-b);
  }
  return 'changed';
}

export function linkupText(row,catalog){
  return (row.linkups||[]).map((config,slot)=>{
    if(!config)return '';
    const type=(catalog.COACH_LINK_TYPES||[]).find(t=>t.template_id===config.template_id);
    const positions=role=>(config[role+'_positions']||[]).map(p=>catalog.POSITIONS[p]).join('/');
    const styles=catalog.COACH_LINK_SCHEMA?.style_labels||{...catalog.PLAY_STYLES.attack,...catalog.PLAY_STYLES.defense};
    const style=role=>styles[config[role+'_style']]||'原生风格 '+config[role+'_style'];
    return `心有灵犀 ${slot+1}：${type?.label||'原生组合 '+config.template_id} · ${positions('source')}（${style('source')}） → ${positions('target')}（${style('target')}）`;
  }).filter(Boolean).join('；');
}
