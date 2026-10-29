import {styleRules} from './playing-style-rules.js';
import {positionNames} from './domain.js';
let owner,checks={attack:null,defense:null};
const labels={attack:'进攻',defense:'防守'};
const positionLabel=p=>`${p} · ${positionNames[p]||p}`;
const positionsText=r=>r.positions.map(p=>positionLabel(p)).join('、');
function checkOwner(project){if(owner!==project.package_id){owner=project.package_id;checks={attack:null,defense:null};}}
export function styleCompatibility(id,position){if(Number(id)===0)return 'basic';const rule=styleRules[id];return !rule?'unknown':rule.positions.includes(position)?'compatible':'incompatible';}
export function setStyleCheckPosition(group,position,project,catalog){checkOwner(project);if(group in checks&&(position===''||catalog.POSITIONS.includes(position)))checks[group]=position||null;}
export function renderStyleHelp(project,catalog,bindInput){
  checkOwner(project);
  const groupHtml=group=>{const label=labels[group],choices=Object.entries(catalog.PLAY_STYLES[group]).map(([id,name])=>[id,name+(styleRules[id]?' · '+styleRules[id].positions.join('/'):'')]);return `<section class="style-phase">${bindInput('play_style.'+group,label+'比赛风格','text',{numeric:true,choices})}<label class="field"><span>${label}时站位（仅检查）</span><select data-style-check-position="${group}" aria-label="${label}时站位检查"><option value="">跟随注册位置 · ${positionLabel(project.identity.position)}</option>${catalog.POSITIONS.map(p=>`<option value="${p}" ${checks[group]===p?'selected':''}>${positionLabel(p)}</option>`).join('')}</select></label><div class="style-result" data-style-result="${group}" role="status" aria-live="polite"></div></section>`;};
  return `<p class="note">按比赛阵型中的实际站位判断；进攻和防守可分别检查。下方站位仅用于查看条件，不会修改球员注册位置或比赛阵型。</p><div class="field-grid">${groupHtml('attack')}${groupHtml('defense')}</div><p class="note">位置符合只表示满足风格的位置条件；还要处于对应攻守阶段。位置适应度是另一项属性，给某位置改成“完全适应”不会扩大风格的兼容位置。</p><details class="style-reference"><summary>查看全部比赛风格与触发位置</summary>${['attack','defense'].map(group=>`<h3>${labels[group]}风格</h3><div class="style-table-wrap"><table><thead><tr><th>${labels[group]}风格</th><th>兼容位置</th><th>作用</th></tr></thead><tbody>${Object.entries(catalog.PLAY_STYLES[group]).map(([id,name])=>`<tr><th>${name}</th><td>${styleRules[id]?positionsText(styleRules[id]):'无特定风格'}</td><td>${styleRules[id]?.description||'按基础行为运行。'}</td></tr>`).join('')}</tbody></table></div>`).join('')}</details><p class="note">位置及作用取自本版APK的中英文游戏说明；这是规则检查，未读取比赛实时站位。</p>`;
}
export function syncStyleHelp(project,catalog){
  if(!document.querySelector('[data-style-result]'))return;checkOwner(project);
  for(const group of ['attack','defense']){
    const select=document.querySelector(`[data-style-check-position="${group}"]`),result=document.querySelector(`[data-style-result="${group}"]`);if(!select||!result)continue;
    select.options[0].textContent='跟随注册位置 · '+positionLabel(project.identity.position);select.value=checks[group]||'';
    const id=project.play_style[group],position=checks[group]||project.identity.position,rule=styleRules[id],state=styleCompatibility(id,position),label=labels[group];result.dataset.state=state;result.replaceChildren();
    const line=text=>{const p=document.createElement('p');p.textContent=text;result.append(p);};
    line(({basic:'无风格 · 按基础行为运行',unknown:'本版未核对 · 暂不判定',compatible:`位置符合 · ${label}时可触发`,incompatible:`位置不符 · ${label}时不触发`})[state]);
    line('检查站位：'+positionLabel(position));
    if(rule){line('兼容位置：'+positionsText(rule));line(rule.description);}
    const aptitude=project.position_aptitudes?.[position];if(aptitude!==undefined)line('此位置适应度：'+(['不适应','部分适应','完全适应'][aptitude]||'未标定')+'（与风格条件分别判断）');
  }
}
