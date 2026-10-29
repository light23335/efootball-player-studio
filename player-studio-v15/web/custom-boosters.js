const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function boosterProblems(booster,abilities){
  const issues=[];
  if(booster.conditional)issues.push('旧工程启用了自定义条件触发，当前暂不支持实装。');
  for(const [id,value] of Object.entries(booster.effects||{})){
    if(!Number.isInteger(value)||value<0||value>20)issues.push(`${abilities[id]||id}：${value}，可实装范围为 0 至 +20。`);
  }
  return issues;
}
export function renderCustomBoosterBody(project,abilities){
  return `<p class="panel-description">26 项能力均支持，包括五项守门能力；每项常驻加成为 0 至 +20。自定义项目可选择任意增能槽，随工程保存，并自动加入最多 10000 项的共享库。其他球员可引用同一增能；修改后重新引用可更新配置。此处展开已选增能和最近 20 项，更多项目可从共享库搜索引用后编辑。原版条件增能仍可直接选用。</p>${(project.custom_boosters||[]).filter((b,i,all)=>project.booster_ids.includes(b.id)||i>=all.length-20).map(b=>{
    const issues=boosterProblems(b,abilities);
    return `<details class="custom-booster" open><summary>${esc(b.label)}${issues.length?' · 待修正':''}</summary>${issues.length?`<div class="migration-status error">${issues.map(esc).join('<br>')}<br>旧配置已保留，不会自动修改。</div><button class="button secondary" data-custom-repair="${b.id}">将负值清零并改为常驻</button>`:''}<div class="field-grid" style="margin:14px 0"><label class="field"><span>增能名称</span><input class="input" data-custom-id="${b.id}" data-custom-field="label" value="${esc(b.label)}" maxlength="40"></label><p class="note">常驻增能 · 各项独立设置</p></div><div class="field-grid three">${Object.entries(abilities).map(([i,label])=>`<label class="field"><span>${esc(label)}</span><input class="input" type="number" min="0" max="20" ${Number(b.effects[i]||0)<0?'aria-invalid="true"':''} data-custom-id="${b.id}" data-custom-stat="${i}" value="${b.effects[i]||0}"></label>`).join('')}</div><button style="margin:14px 0" class="button subtle" data-custom-delete="${b.id}">删除此增能</button></details>`;
  }).join('')}<div class="welcome-actions"><button class="button secondary" data-action="new-custom-booster">＋ 新建自定义增能</button><button class="button primary" data-shared-boosters>从共享增能库引用</button></div>`;
}
