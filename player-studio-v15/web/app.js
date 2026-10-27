import {skillCapacityNotice} from './skill-capacity.js';
import {renderStyleHelp,syncStyleHelp,setStyleCheckPosition} from './playing-style-ui.js';
import {MotionUI} from './motion-ui.js';
import {TaskCenter} from './task-center.js';
import {ReleaseUpdatesUI} from './release-updates.js';
import {AndroidSidebarResize} from './sidebar-layout.js';
import {WindowSession} from './window-session.js';
import {BoosterLibraryUI} from './booster-library-ui.js';
import {WorkspaceNavigation,editorPages,playerReady} from './navigation-ui.js';
import {choosePlayerAction,playerLoadChoices} from './player-prompts.js';
import {OnboardingUI,navigationGroups} from './onboarding-ui.js';
import {WorkspaceTools} from './workspace-tools.js';
import {renderThumbnailPanel,drawThumbnail} from './thumbnail-ui.js';
import {renderCustomBoosterBody} from './custom-boosters.js';
import {simulate,autoAllocate,trainingCost,ratingColor,cardTypes,cardTypeName,selectCardType,selectCardSeries,series,statGroups,positionNames} from './domain.js';
import {ModelViewer} from './model-viewer.js';
import {LibraryUI} from './library-ui.js';
import {GameImportUI} from './game-import-ui.js';
import {NativePackageUI} from './native-package-ui.js';
import {PackUI} from './pack-ui.js';
import {bodyPanel,equipmentPanel} from './body-ui.js';
import {headPanel} from './head-tools.js';
import {PersonalUI} from './personal-ui.js';
import {CoachUI} from './coach-ui.js';
import {NativeCardRenderer} from './native-card.js';
import {CardPresetsUI} from './card-presets.js';
import {originalCardDate} from './card-design.js';

const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone=v=>structuredClone(v);
const token=new URLSearchParams(location.search).get('token')||'';
const icons={
 user:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
 chart:'<path d="M4 20V10m8 10V4m8 16v-7"/>',
 grow:'<path d="m3 17 6-6 4 4 8-10m-6 0h6v6"/>',
 spark:'<path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7L12 3Z"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m3 16 5-5 6 6 4-4 3 3"/>',
 cube:'<path d="m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 10 9-5m-9 5L3 8m9 5v9M7.5 5.5l9 5"/>',
 archive:'<path d="M5 9h14v11H5zM3 3h18v6H3zM9 13h6"/>',
 fingerprint:'<path d="M5 11a7 7 0 0 1 14 0v4m-10 6V11a3 3 0 0 1 6 0v7m-3-7v10M5 14v3m14 1v2M2 11a10 10 0 0 1 20 0"/>',
 folder:'<path d="M3 7V5a2 2 0 0 1 2-2h4l3 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
 export:'<path d="M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2l-1.5 1v2m0 3h.01"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
 undo:'<path d="M8 4 3 9l5 5M4 9h10a6 6 0 0 1 0 12h-3"/>',
 redo:'<path d="m16 4 5 5-5 5m4-5H10a6 6 0 0 0 0 12h3"/>',
 plus:'<path d="M12 4v16M4 12h16"/>',
 search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
 check:'<path d="m4 12 5 5L20 6"/>',
 camera:'<path d="m8 5 2-3h4l2 3h4a1 1 0 0 1 1 1v14H3V6a1 1 0 0 1 1-1h4Z"/><circle cx="12" cy="12" r="4"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 2M4 17l2 2a8 8 0 0 0 13-3"/>',
 download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>'
};
function icon(name){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.spark}</svg>`;}
function hydrateIcons(root=document){root.querySelectorAll('[data-icon]').forEach(n=>n.innerHTML=icon(n.dataset.icon));}
const pages={
 home:{title:'开始使用',short:'开始',icon:'folder',description:'读取游戏、编辑球员、生成安装包。'},
 tutorial:{title:'详细教程',short:'教程',icon:'help',description:'逐步操作说明、安装方式与常见问题。'},
 tools:{title:'导出与游戏设置',short:'导出与设置',icon:'archive',description:'管理导出文件、直接安装及 AI 组别进度。'},
 personal:{title:'我的球员',short:'我的球员',icon:'folder',description:'保存多名自建球员，随时打开编辑或导出独立工程。'},
 packs:{title:'卡包编辑',short:'卡包编辑',icon:'archive',description:'混编原版与自建球员，设置抽取权重、卡池规则与原版封面。'},
 motion:{title:'动作风格',short:'动作风格',icon:'grow',description:'参考原版球员的比赛姿态，为每张卡保存和复用动作预设。'},
 coaches:{title:'教练管理',short:'教练管理',icon:'user',description:'选择原版教练，或新建教练并自定义战术与能力加成。'},
 library:{title:'从已有球员复制',short:'复制球员',icon:'search',description:'复制原版球员到独立自建槽位；编辑和保存不会影响原球员数据。'},
 profile:{title:'球员资料',short:'资料',icon:'user',description:'从名字到球场位置，定义属于你的球员。'},
 abilities:{title:'基础能力',short:'基础能力',icon:'chart',description:'先设定 1 级基础值，实时查看培养与增能带来的变化。'},
 training:{title:'培养模拟',short:'培养模拟',icon:'grow',description:'按本版规则分配培养点，比较不同位置的成长方案。'},
 skills:{title:'技能与风格',short:'技能风格',icon:'spark',description:'搭配天生与追加技能，确定你的球场风格。'},
 card:{title:'卡面设计',short:'卡面设计',icon:'image',description:'选择游戏原版卡图、背景与图层，实时预览你的编辑结果。'},
 model:{title:'模型预览',short:'模型预览',icon:'cube',description:'从游戏已有模型中选择，检查原始网格、贴图、骨架与动画。'},
 migration:{title:'更新与迁移',short:'更新迁移',icon:'archive',description:'导出已实装球员的最新快照，保留数据和培养进度。'},
 native:{title:'APK 球员实装',short:'APK 实装',icon:'cube',description:'选择内容与安装方式，生成可安装的游戏 APK。'},
 apk:{title:'游戏来源与更新',short:'游戏来源与更新',icon:'refresh',description:'导入新版游戏主包，校验后更新球员数据库与原版资源索引。'}
};
let project,catalog,currentPage='home',preview='card',abilityFilter='all',skillQuery='',skillMode='innate',skillSelectedOnly=false;
let past=[],future=[],lastChangeKey='',lastChangeTime=0,version=0,savedVersion=0,saveTimer=null,savePromise=null,viewer;
let toolsUI,onboardingUI,releaseUpdatesUI,boosterLibraryUI,motionUI,taskCenter,navigationMode='simple';
const workspaceNavigation=new WorkspaceNavigation($('#navigation'));
let simulation,imageCache=new Map(),cardDrawVersion=0,modelMetadata={},libraryUI,updateUI,nativePackageUI,personalUI,coachUI,presetsUI,packUI,nativeCard,identityOptions={nation:[],team:[]};
const migrationState={mode:'export',save:'',apk:'',package:'',previous:'',prefer:'package',players:[],selected:null,plan:null,status:'',statusType:'',resultUrl:null};

async function api(path,body){
  const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'操作未完成');taskCenter?.observe(path,data);return data;
}
function toast(message,error=false){const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=message;$('#toasts').append(el);while($('#toasts').children.length>3)$('#toasts').firstElementChild.remove();setTimeout(()=>el.remove(),error?8500:4200);}
function get(path){return path.split('.').reduce((v,k)=>v?.[k],project);}
function set(path,value){const keys=path.split('.');let target=project;for(const key of keys.slice(0,-1))target=target[key]??=( {});target[keys.at(-1)]=value;if(path==='model.skin_tone')project.model.skin_tone_edited=true;if(path==='model.torso_length')project.model.physique.leg_length=14-value;if(path==='model.physique.leg_length')project.model.torso_length=14-value;if(path==='model.torso_length'||path==='model.physique.leg_length'){for(const k of ['model.torso_length','model.physique.leg_length'])$$(`[data-bind="${k}"]`).forEach(el=>el.value=get(k));}}
function commit(mutator,key='action'){
  const now=performance.now();if(key!==lastChangeKey||now-lastChangeTime>600){past.push(clone(project));if(past.length>60)past.shift();}
  lastChangeKey=key;lastChangeTime=now;future=[];mutator();version++;scheduleSave();updateLive();updateUndo();libraryUI?.scheduleCardInfo();
}
function scheduleSave(){clearTimeout(saveTimer);$('#save-status').className='save-status saving';$('#save-status').innerHTML='<i class="status-dot"></i>正在保存';saveTimer=setTimeout(()=>flushSave().catch(()=>{}),650);}
async function flushSave(manual=false){
  clearTimeout(saveTimer);
  if(savePromise){await savePromise;if(savedVersion<version)return flushSave(manual);return;}
  if(savedVersion===version&&!manual)return;
  const currentVersion=version,snapshot=clone(project);
  savePromise=api('project/save',{project:snapshot,manual}).then(()=>{
    savedVersion=currentVersion;
    window.dispatchEvent(new CustomEvent('studio-project-saved',{detail:snapshot}));
    if(savedVersion===version){$('#save-status').className='save-status';$('#save-status').innerHTML='<i class="status-dot"></i>已保存到本机';}
  }).catch(error=>{$('#save-status').className='save-status error';$('#save-status').textContent='保存失败，点 Ctrl+S 重试';toast(error.message,true);throw error;}).finally(()=>savePromise=null);
  await savePromise;
  if(savedVersion<version)return flushSave();
}
function updateUndo(){$('#undo-button').disabled=!past.length;$('#redo-button').disabled=!future.length;}
function undo(){if(!past.length)return;future.push(clone(project));project=past.pop();lastChangeKey='';version++;scheduleSave();renderPage();}
function redo(){if(!future.length)return;past.push(clone(project));project=future.pop();lastChangeKey='';version++;scheduleSave();renderPage();}
function bindInput(path,label,type='text',options={}){
  const val=get(path),extra=`${options.min!==undefined?' min="'+options.min+'"':''}${options.max!==undefined?' max="'+options.max+'"':''}${options.step?' step="'+options.step+'"':''}`;
  const input=options.choices?`<select data-bind="${path}" ${options.numeric?'data-number="1"':''}>${options.choices.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(val)?'selected':''}>${esc(t)}</option>`).join('')}</select>`:
    `<input class="input" data-bind="${path}" type="${type}" value="${esc(val)}" placeholder="${esc(options.placeholder||'')}"${extra}>`;
  return `<label class="field${options.wide?' span-two':''}"><span>${label}</span>${options.unit?`<div class="input-with-unit">${input}<span>${options.unit}</span></div>`:input}${options.hint?`<small>${options.hint}</small>`:''}</label>`;
}
function panel(title,body,tag=''){return `<section class="panel"><div class="panel-title"><h2>${title}</h2>${tag?`<span class="tag">${tag}</span>`:''}</div><div class="panel-body">${body}</div></section>`;}
function range(path,label,min,max,step=1,unit=''){
  return `<label class="range-field field"><div class="row-between"><span>${label}</span><output data-value="${path}" data-unit="${unit}">${esc(get(path))}${unit}</output></div><input type="range" data-bind="${path}" min="${min}" max="${max}" step="${step}" value="${esc(get(path))}"></label>`;
}
function selectPosition(){return catalog.POSITIONS.map(p=>[p,`${p} · ${positionNames[p]}`]);}
function identityInput(kind,label){const field=kind==='nation'?'nationality':'team';return `<label class="field"><span>${label}</span><input class="input" data-bind="identity.${field}" data-identity-kind="${kind}" list="identities-${kind}" value="${esc(project.identity[field])}" placeholder="输入中文或英文名称筛选"><datalist id="identities-${kind}">${identityOptions[kind].map(r=>`<option value="${esc(r.name)} · #${r.id}">${esc(r.name_en)}</option>`).join('')}</datalist><small>输入名称可搜索；原始编号在资料详情中查看。</small></label>`;}

function renderProfile(){
  return panel('基本信息',`<div class="field-grid">${bindInput('identity.name','球员姓名','text',{placeholder:'输入你的名字'})}${bindInput('identity.shirt_name','球衣背后名字','text',{placeholder:'可与卡面姓名不同'})}${bindInput('display_name','卡面显示名','text',{placeholder:'可与姓名相同'})}${identityInput('nation','国籍 / 地区')}${identityInput('team','球队名称')}${bindInput('identity.position','主要位置','text',{choices:selectPosition()})}${bindInput('identity.preferred_foot','惯用脚','text',{choices:[['右脚','右脚'],['左脚','左脚']]})}</div><details class="note"><summary>查看原始资料编号</summary>国家：<span data-identity-code="nation">${esc(project.identity.nation_id??'未选择')}</span> · 球队：<span data-identity-code="team">${esc(project.identity.team_id??'未选择')}</span></details><div class="section-spacer"></div><div class="field-grid three" style="margin-top:16px">${bindInput('identity.height_cm','身高','number',{min:140,max:220,unit:'cm'})}${bindInput('identity.weight_kg','体重','number',{min:40,max:140,unit:'kg'})}${bindInput('identity.age','年龄','number',{min:15,max:60,unit:'岁'})}${bindInput('identity.number','球衣号码','number',{min:1,max:999,hint:project.identity.number_source||'按原生阵容读取，也可手动修改'})}</div>`,'PROFILE')+
  equipmentPanel(project,catalog.equipment)+panel('原游戏球员身份',`<label class="switch-label"><input type="checkbox" data-bind="identity.bind_original_player" ${project.identity.bind_original_player?'checked':''}>绑定原游戏球员 ID</label><div class="field-grid" style="margin-top:14px">${bindInput('identity.original_player_id','原游戏球员 ID','text',{placeholder:'从已有球员复制时自动填写',hint:'可填当前库中的基础球员 ID 或完整卡号，导出时会核对。'})}</div><p class="note">开启后与对应原版球员视作同一人；关闭后使用独立身份。同一人的不同卡通常不能同时上场。自建卡仍单独保存，修改不会覆盖原版球员。</p>`)+
  panel('卡种与系列',`<div class="type-grid">${cardTypes.map(([type,label])=>`<button class="type-option ${project.card_type===type?'active':''}" data-card-type="${type}"><strong>${cardTypeName(type)}</strong><small>${label}</small></button>`).join('')}</div><div class="field-grid">${bindInput('card_series','卡面系列','text',{choices:series,hint:'Big Time 与 Epic 分别选择、筛选和保存。原版卡面资源在卡面设计中选择。'})}${bindInput('max_level','等级上限','number',{min:1,max:100,hint:project.max_level_known===false?'原包未收录此条上限；当前值是模拟值，请按游戏资料填写。':'已知上限按原包资料载入；可编辑范围 1–100 级。'})}</div><p class="note">${project.card_type==='Trending'?'Trending 常规规则下不可培养。若希望自由培养，请选择其他基础卡种。':'卡面样式与增能、特殊技能分别设置，可在后续页面自由搭配。'}</p>`,'CARD TYPE')+
  panel('其他特征',`<div class="field-grid">${bindInput('traits.weak_foot_usage','逆足使用频率','text',{choices:[['低','低'],['普通','普通'],['高','高'],['极高','极高']]})}${bindInput('traits.weak_foot_accuracy','逆足精准度','text',{choices:[['低','低'],['普通','普通'],['高','高'],['极高','极高']]})}${bindInput('traits.form','状态持续性','text',{choices:[['稳定','稳定'],['普通','普通'],['不稳定','不稳定']]})}${bindInput('traits.injury','受伤耐性','text',{choices:[['低','低'],['普通','普通'],['高','高']]})}${bindInput('celebration','庆祝动作编号','number',{min:0,max:511,hint:'读取源卡原生编号；留空沿用源球员。V15 范围 0–511，0 不代表没有庆祝动画。'})}${bindInput('weekly_condition','实时更新状态','text',{choices:[['auto','跟随默认规则（BT / 史诗 / 传奇为 B）'],...['A','B','C','D','E'].map(v=>[v,v])]})}</div><p class="note">A–E 是实时更新状态，与状态持续性及比赛内箭头分别设置。同一卡号的持有副本使用同一状态；手动选择优先于默认 B 规则。</p>`);
}

function renderAbilities(){
  return `<div class="row-between" style="margin-bottom:16px"><div class="inline-tip">输入 1 级基础能力 · 不含培养与增能</div><button class="button subtle" data-action="preset">${icon('spark')}载入前锋参考模板</button></div><div class="filter-tabs">${[['all','全部 26 项'],...statGroups.map((g,i)=>[String(i),g.name])].map(([key,name])=>`<button class="${abilityFilter===key?'active':''}" data-ability-filter="${key}">${name}</button>`).join('')}</div><section class="panel"><div class="panel-title"><h2>基础能力</h2><span class="tag">基础 → 预览</span></div>${statGroups.filter((g,i)=>abilityFilter==='all'||abilityFilter===String(i)).map(group=>`<div class="stat-section-label">${group.name}</div>${group.indices.map(index=>`<div class="stat-row"><label for="ability-${index}">${esc(catalog.ABILITIES[index])}</label><input type="range" aria-label="${esc(catalog.ABILITIES[index])}滑杆" data-bind="base_abilities.${index}" min="1" max="105" value="${project.base_abilities[index]}"><input id="ability-${index}" aria-label="${esc(catalog.ABILITIES[index])}" class="input" type="number" min="1" max="105" data-bind="base_abilities.${index}" value="${project.base_abilities[index]}"><div class="stat-final" data-stat-final="${index}"></div></div>`).join('')}`).join('')}<div style="height:15px"></div></section>`;
}

function boosterLabel(b){if(!b.label.includes('�'))return b.label;const entries=Object.entries(b.effects);return entries.length===26?'全能力 '+(entries[0][1]>=0?'+':'')+entries[0][1]:entries.map(([i,v])=>catalog.ABILITIES[i]+(v>=0?'+':'')+v).join(' / ')||'无常驻效果';}
function boosterSelect(slot){const current=project.booster_ids[slot]||0;return `<label class="field"><span>增能槽 ${slot+1}</span><select data-booster-slot="${slot}"><option value="0">不使用增能</option>${[...catalog.boosters,...(project.custom_boosters||[]).filter((b,i,all)=>project.booster_ids.includes(b.id)||i>=all.length-20)].filter(b=>slot===1||b.id<=255||b.uuid).map(b=>`<option value="${b.id}" ${current===b.id?'selected':''}>${esc(boosterLabel(b))}${b.conditional?' · 条件':''}</option>`).join('')}</select></label>`;}
function renderCustomBoosters(){return panel('自定义增能',renderCustomBoosterBody(project,catalog.ABILITIES));}
function renderTraining(){
  const target=project.preview?.training_position||project.identity.position;
  return panel('等级设置',`<div class="field-grid">${bindInput('initial_level','模拟当前等级','number',{min:1,max:project.max_level})}${bindInput('max_level','等级上限','number',{min:1,max:100})}</div><p class="note">每提升 1 级获得 2 点；同项目每 4 次加点，下一阶段的单次消耗增加 1 点。培养能力上限 105。</p>`)+
  `<div class="budget-card" id="budget-card"><div class="budget-metrics"><div><span>等级提供</span><strong id="budget-total">0<small>点</small></strong></div><div><span>已分配</span><strong id="budget-spent">0<small>点</small></strong></div><div><span>剩余培养点</span><strong id="budget-remaining">0<small>点</small></strong></div></div><div class="budget-track"><i id="budget-progress"></i></div></div><div class="training-actions"><label class="training-position"><span>加点目标位置</span><select id="training-target" data-bind="preview.training_position">${catalog.POSITIONS.map(pos=>`<option value="${pos}" ${target===pos?'selected':''}>${pos} · ${positionNames[pos]}</option>`).join('')}</select></label><button class="button secondary" data-action="auto-train">${icon('spark')}按所选位置分配</button><button class="button subtle" data-action="reset-training">${icon('refresh')}重置加点</button><span class="inline-tip" id="training-target-note"></span></div><p class="note">每项能力显示基础、加点后和最终数值；最终值计入当前球员增能与所选教练。</p><div class="training-grid">${catalog.training_groups.map(group=>`<section class="training-card"><h3>${group.label}<span data-group-cost="${group.id}"></span></h3><div class="training-stat-head"><span>能力</span><span>基础</span><span>培养</span><span>最终</span></div><div class="training-stat-list" data-training-stats="${group.id}"></div><div class="stepper"><div class="stepper-group"><button data-step="-1" data-group="${group.id}" aria-label="减少${group.label}">−</button><input data-bind="training.${group.id}" type="number" min="0" max="40" aria-label="${group.label}加点次数" value="${project.training[group.id]}"><button data-step="1" data-group="${group.id}" aria-label="增加${group.label}">+</button></div><span data-group-next="${group.id}"></span></div></section>`).join('')}</div><div style="height:19px"></div>`+
  panel('球员增能',`<div class="field-grid">${boosterSelect(0)}${boosterSelect(1)}</div><label class="switch-label" style="margin-top:17px"><input type="checkbox" data-bind="conditional_boosters" ${project.conditional_boosters?'checked':''}>将条件增能计入预览</label><p class="note">目录包含 418 项本版增能。条件类只有在上面的开关启用时计入；不模拟教练与状态箭头。</p>`)+
  renderCustomBoosters()+
  panel('全部 26 项能力变化',`<div class="training-table-wrap"><table class="training-detail-table"><thead><tr><th>能力</th><th>基础</th><th>培养后</th><th>增能后</th><th>含教练</th><th>总提升</th></tr></thead><tbody id="training-comparison"></tbody></table></div>`,'全部明细');
}

function renderSkills(){
  return `<div class="skill-toolbar"><div class="segmented"><button data-skill-mode="innate" class="${skillMode==='innate'?'active':''}">天生技能</button><button data-skill-mode="additional" class="${skillMode==='additional'?'active':''}">额外习得</button></div><div class="skill-counts"><span>天生 <strong id="innate-count">${project.innate_skills.length}/100</strong></span><span>追加 <strong id="additional-count">${project.additional_skills.length}/100</strong></span></div></div><div class="search-box">${icon('search')}<input id="skill-search" placeholder="搜索中文名称、英文技能或编号" value="${esc(skillQuery)}"><label class="switch-label"><input type="checkbox" id="selected-skills-only" ${skillSelectedOnly?'checked':''}>已选</label></div><div class="skill-legend"><span><i></i>天生</span><span><i class="blue"></i>追加</span><span>点击添加，再次点击取消</span></div><p id="skill-capacity-note" class="note" role="status" ${skillCapacityNotice(project)?'':'hidden'}>${esc(skillCapacityNotice(project))}</p><div class="skill-grid" id="skill-grid"></div><div style="height:20px"></div>`+
  panel('比赛风格与适用位置',renderStyleHelp(project,catalog,bindInput))+
  panel('AI 比赛风格',`<p class="panel-description">影响电脑控制球员时的倾向。可多选，也可全部取消；载入原版资料时自动读取该球员的设置。</p><div class="ai-style-grid">${Object.entries(catalog.AI_PLAYING_STYLES).map(([key,f])=>`<label class="ai-style-option"><input type="checkbox" data-ai-style="${key}" ${(project.ai_playing_styles||[]).includes(key)?'checked':''}><span>${esc(f.label)}<small>${esc(f.english)}</small></span></label>`).join('')}</div>`)+
  panel('位置适应度',`<div class="field-grid three">${catalog.POSITIONS.map(pos=>bindInput('position_aptitudes.'+pos,`${pos} · ${positionNames[pos]}`,'text',{numeric:true,choices:[[0,'不适应'],[1,'部分适应'],[2,'完全适应']]})).join('')}</div>`);
}
function updateSkillGrid(){
  const grid=$('#skill-grid');if(!grid)return;
  const q=skillQuery.trim().toLowerCase();
  const entries=catalog.SKILL_NAMES.map((code,id)=>({code,id,name:catalog.SKILL_LABELS[id]||code})).filter(s=>(!q||`${s.name} ${s.code} ${s.id} ${(catalog.SKILL_ALIASES?.[s.id]||[]).join(' ')}`.toLowerCase().includes(q))&&(!skillSelectedOnly||project.innate_skills.includes(s.id)||project.additional_skills.includes(s.id)));
  grid.innerHTML=entries.length?entries.map(s=>{
    const innate=project.innate_skills.includes(s.id),additional=project.additional_skills.includes(s.id),unsupported=catalog.PARAMETER_BY_SKILL[s.id]===undefined||s.name.includes('预留');
    return `<button class="skill-tile ${innate?'innate':additional?'additional':''} ${unsupported?'unsupported':''}" data-skill="${s.id}" ${unsupported?'disabled':''} aria-pressed="${innate||additional}" title="${esc(unsupported?'本版预留或映射未核对，暂不写入':catalog.SKILL_DESCRIPTIONS?.[s.id]||s.code)}"><span class="skill-name">${esc(s.name)}<small>${String(s.id).padStart(2,'0')} · ${esc(unsupported?'本版预留 / 待适配':s.code)}</small>${catalog.SKILL_DESCRIPTIONS?.[s.id]?`<small>${esc(catalog.SKILL_DESCRIPTIONS[s.id])}</small>`:''}</span><span class="skill-state">${innate?'天':additional?'追':'+'}</span></button>`;
  }).join(''):'<div class="no-matches">没有匹配的技能</div>';
  $('#innate-count').textContent=project.innate_skills.length+'/100';$('#additional-count').textContent=project.additional_skills.length+'/100';
  const capacityNote=$('#skill-capacity-note');if(capacityNote){capacityNote.textContent=skillCapacityNotice(project);capacityNote.hidden=!capacityNote.textContent;}
}

function renderCard(){
  const art=project.native_art||{},native=project.native_card,bt=(native?.card_type||project.card_type)==='BigTime';
  const photo=project.appearance.portrait,date=project.appearance.card_date??originalCardDate(native);
  return panel('你的人物与卡面资料',`<div class="card-person"><div class="card-person-image">${photo?`<img src="/assets/${esc(photo)}" alt="当前人物图">`:'<span>导入透明 PNG 人物图</span>'}</div><div><p class="panel-description">先导入人物，再从下方选择空白底板。换预设会保留你的人物、能力、技能和培养方案。</p><div class="portrait-actions"><button class="button primary" data-action="upload-portrait">导入 / 替换自己的人物</button><button class="button secondary" data-action="native-portrait-library">选择游戏人物</button></div><label class="switch-label"><input type="checkbox" data-bind="appearance.hide_portrait" ${project.appearance.hide_portrait?'checked':''}>仅预览空白底板（暂时隐藏人物）</label></div></div><div class="field-grid" style="margin-top:18px">${bt?`<label class="field"><span>BT 日期</span><input class="input" type="date" id="card-date" data-bind="appearance.card_date" value="${esc(date)}"><small>可直接修改日期；留空则不显示。</small></label>`:''}<label class="field"><span>卡面星级</span><select data-bind="appearance.card_rarity" data-number="1">${[1,2,3,4,5].map(n=>`<option value="${n}" ${n===(project.appearance.card_rarity||native?.info?.rarity||5)?'selected':''}>${n} 星</option>`).join('')}</select></label></div>${bt?`<label class="switch-label" style="margin-top:13px"><input type="checkbox" data-bind="appearance.card_date_visible" ${project.appearance.card_date_visible!==false?'checked':''}>显示 BT 日期</label>`:''}<p class="note">当前设计：${native?esc(cardTypeName(native.card_type)+' · '+(native.preset?.title||native.source_label||'原版卡面')):'尚未选择；请在下方点击“使用此预设”。'}</p>`)+
  panel('原版空白卡面预设',presetsUI.render())+
  renderThumbnailPanel(project,range)+
  panel('构图与导出',`${range('appearance.photo_zoom','人物缩放',.5,2.8,.02,'×')}${range('appearance.photo_x','水平位置',-180,180,1)}${range('appearance.photo_y','垂直位置',-180,180,1)}<label class="switch-label"><input type="checkbox" data-bind="appearance.native_overlay_text" ${project.appearance.native_overlay_text!==false?'checked':''}>显示姓名、位置、星级与计算总评</label><div class="portrait-actions"><button class="button secondary" data-action="photo-reset">重置构图</button><button class="button primary" data-action="export-card">导出当前帧 PNG</button></div>`)+
  panel('高级：原版图层与来源',`<details class="note"><summary>手动选择图层或查看来源</summary><p>预设使用原版公共背景、框架和特效。人物已烘焙在整张图中的卡片，不作为干净底板使用。浏览器合成材质仍需与游戏内核对。</p><div class="portrait-actions"><button class="button secondary" data-action="native-card-library">手动选择图层</button><button class="button subtle" data-action="native-rebuild-card">读取来源球员卡面</button></div>${(native?.layers||[]).map(row=>`<div class="native-source-line"><span>${esc(row.slot)}</span><code>${esc(row.path)}</code></div>`).join('')}${!native?Object.entries(art).filter(([,v])=>v).map(([k,v])=>`<div class="native-source-line"><span>${esc(k)}</span><code>${esc(v.path)}</code></div>`).join(''):''}</details>`);
}
function renderModel(){
  const source=project.model.native_source;
  const variants=project.model.variants||[],resolution=project.model.resolution;
  return `<div class="model-toolbar"><button class="button primary" data-action="native-model-library">选择游戏原版模型</button><button class="button subtle" data-action="upload-model">导入已转换的 GLB / OBJ</button><button class="button secondary" data-action="export-model">导出 GLB</button></div><div class="model-stage main-model-stage" id="main-model-stage"></div><div class="row-between" style="margin:12px 0 17px"><span class="inline-tip">左键旋转 · 滚轮缩放 · 右键平移</span><span class="view-mode-label" id="model-kind-label">${source?'游戏原版网格':project.model.asset?'已导入模型':'尚未选择原版模型'}</span></div><div class="model-toolbar"><div style="display:flex;gap:7px"><button class="button subtle" data-view="full">适应画面</button><button class="button subtle" data-view="head">局部</button><button class="button subtle" data-view="front">正面</button></div><button class="button secondary" data-action="model-to-card">取景为球员图</button></div><div class="model-view-options">${[['wireframe','线框'],['skeleton','已有骨架'],['rotate','自动旋转']].map(([key,name])=>`<label class="switch-label"><input type="checkbox" data-model-option="${key}" ${viewer?.options[key]?'checked':''}>${name}</label>`).join('')}</div>`+
  panel('原版资源来源',`<div class="native-source-line"><code>${esc(source?.path||'从原版模型库选择脸部、头发或身体网格。')}</code></div><p class="note">${esc(resolution?.message||'')}${source?`已解析原贴图的材质 ${source.textured_materials} / ${source.materials}。` : ''}使用原始几何、UV 和可解析的原贴图；浏览器材质与游戏着色效果可能不同。</p>${variants.length?`<p class="note">本球员可用的原版脸模（${variants.length}）</p><div class="portrait-actions">${variants.map(v=>`<button class="button ${source?.name===v.name?'primary':'secondary'}" data-lib-apply="${esc(v.id)}" data-lib-slot="model">${esc(v.name.replace('SK_','').replace('_Face',''))}</button>`).join('')}</div>`:''}`)+
  headPanel(project,viewer)+bodyPanel(project,range)+equipmentPanel(project,catalog.equipment)+panel('视图与已有动画',`<div class="field-grid">${range('model.scale','整体显示缩放',.4,1.8,.01,'×')}${range('model.rotation','模型转向',-180,180,1,'°')}</div><label class="field" style="margin-top:15px"><span>模型已有动画</span><select id="model-animation"><option value="-1">暂无动画</option></select></label><div id="model-morphs" class="morph-grid"></div><div class="model-info" id="model-info"></div>`);
}

function pathField(key,label,category){return `<div class="path-field"><label for="migration-${key}">${label}</label><div class="input-row"><input class="input" id="migration-${key}" data-migration="${key}" value="${esc(migrationState[key])}" placeholder="选择文件，或粘贴完整路径"><button class="button secondary" data-migration-pick="${key}" data-category="${category}">${icon('folder')}选择</button></div></div>`;}
function renderMigration(){
  return `<div class="segmented migration-tabs"><button data-migration-mode="export" class="${migrationState.mode==='export'?'active':''}">导出最新球员包</button><button data-migration-mode="import" class="${migrationState.mode==='import'?'active':''}">更新后重新导入</button></div>`+
  (migrationState.mode==='export'?panel('导出已实装球员的当前状态',`<p class="panel-description">使用游戏导出的最新存档。这里只保存所选实例的实际能力与培养记录，设计草稿不会直接写入存档。</p>${pathField('save','当前游戏存档','save')}${pathField('apk','当前版本 APK','apk')}${pathField('previous','上一份球员包 选填，用于沿用永久身份','package')}<div class="portrait-actions"><button class="button secondary" data-action="read-players">读取球员列表</button><button class="button primary" data-action="export-snapshot" ${migrationState.selected?'':'disabled'}>导出最新快照</button></div><div id="migration-players"></div>`,'SNAPSHOT'):
  panel('合并到新版存档',`<p class="panel-description">先启动新版完成其自身迁移，再导出新版目标存档。检查通过后生成新文件，原文件和其他球员保持。</p>${pathField('package','更新前最新球员包','package')}${pathField('save','新版导出的目标存档','save')}${pathField('apk','新版 APK','apk')}<label class="field" style="margin-bottom:17px"><span>状态冲突时的选择</span><select id="migration-prefer">${[['package','恢复包内状态，拒绝覆盖更新的培养进度'],['stop','发现差异时停止'],['target','保留目标球员的当前状态']].map(([v,label])=>`<option value="${v}" ${migrationState.prefer===v?'selected':''}>${label}</option>`).join('')}</select></label><div class="portrait-actions"><button class="button secondary" data-action="inspect-package">检查球员包</button><button class="button secondary" data-action="migration-plan">预览迁移计划</button><button class="button primary" data-action="migration-apply" ${migrationState.plan?'':'disabled'}>生成迁移后存档</button></div>`,'MIGRATION'))+
  `<div id="migration-output"></div>`+
  panel('更新前记得刷新快照',`<p class="panel-description" style="margin:0">旧球员包只能还原导出当时的状态。每次更新前，先导出最新存档并刷新快照，后续经验与培养才能保留下来。原版数据布局或引擎发生变化时，工具会停止并等待适配。</p><div class="version-note">${icon('check')}已核对 V13 · 147 项参数布局</div>`);
}
function updateMigrationOutput(){
  const target=$('#migration-output');if(!target)return;
  target.innerHTML=(migrationState.status?`<div class="migration-status ${migrationState.statusType}">${esc(migrationState.status)}</div>`:'')+(migrationState.resultUrl?`<div class="download-result"><span>文件已生成并保存在本机</span><a class="button secondary" download href="${esc(migrationState.resultUrl)}">下载文件</a></div>`:'');
  const list=$('#migration-players');if(list)list.innerHTML=migrationState.players.length?`<div class="player-list">${migrationState.players.map((p,i)=>`<label class="player-option"><input type="radio" name="native-player" value="${i}" ${migrationState.selected?.id===p.id&&migrationState.selected?.serial===p.serial?'checked':''}><div><strong>${p.id}</strong><div>实例 ${p.serial} · ${p.games} 场 · ${p.goal} 球</div></div><small>Lv.${p.level} · ${p.exp_total} EXP</small></label>`).join('')}</div>`:'';
}

function renderPage(){
  if(project&&version===savedVersion)window.dispatchEvent(new CustomEvent('studio-project-saved',{detail:project}));
  presetsUI?.close();
  document.body.dataset.workspacePage=currentPage;
  const page=pages[currentPage];
  workspaceNavigation.activate(currentPage,playerReady(project));
  $('#compact-page-select').value=currentPage==='library'?'personal':currentPage;
  $('#page-title').textContent=page.title;$('#breadcrumb-page').textContent=page.short;$('#page-description').textContent=page.description;
  $('#page-eyebrow').textContent=currentPage==='migration'?'KEEP YOUR PROGRESS':currentPage==='model'?'SHAPE YOUR PLAYER':'CREATE YOUR OWN LEGACY';
  $$('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.page===currentPage));
  $('#editor-content').innerHTML=({home:()=>onboardingUI.render(),tutorial:()=>onboardingUI.renderTutorial(),tools:()=>toolsUI.render(),packs:()=>packUI.render(),personal:()=>personalUI.render(),coaches:()=>coachUI.render(),library:()=>libraryUI.render(),profile:renderProfile,abilities:renderAbilities,training:renderTraining,skills:renderSkills,motion:()=>motionUI.render(),card:renderCard,model:renderModel,migration:renderMigration,apk:()=>updateUI.render(),native:()=>nativePackageUI.render()})[currentPage]();
  workspaceNavigation.activate(currentPage,playerReady(project));
  if(currentPage==='skills')updateSkillGrid();
  if(currentPage==='migration')updateMigrationOutput();
  if(currentPage==='model'){viewer?.attach($('#main-model-stage'));updateModelControls();}
  else if(preview==='model')viewer?.attach($('#mini-model-stage'));
  if(currentPage==='model'&&!project.model.physique)loadPhysique();
  coachUI?.renderPreview();updateLive();updateUndo();libraryUI?.activate(currentPage);updateUI?.activate(currentPage);nativePackageUI?.activate(currentPage);personalUI?.activate(currentPage);coachUI?.activate(currentPage);
  releaseUpdatesUI?.activate(currentPage).catch(()=>{});
  onboardingUI?.activate(currentPage).catch(e=>toast(e.message,true));
  packUI?.activate(currentPage);toolsUI?.activate(currentPage).catch(e=>toast(e.message,true));
  motionUI?.activate(currentPage);
  if(currentPage==='card')presetsUI.refresh();
}
function navigate(page){if(!pages[page])return;if(editorPages.has(page)&&!playerReady(project)){toast('请先从资源库读取球员，或打开“我的球员”中的工程');$('#compact-page-select').value=currentPage==='library'?'personal':currentPage;return;}currentPage=page;if(!project||!viewer)return;renderPage();window.scrollTo({top:0,behavior:'instant'});}
async function loadPhysique(){const uid=project.package_id,id=project.model.appearance_source_id||project.source_player?.id||project.native_card?.source_id||'7511';try{const p=await api('appearance/profile',{id});if(project.package_id!==uid||project.model.physique||!p.physique)return;commit(()=>{project.model.physique=p.physique;project.model.skin_tone=p.skin_tone||1;project.model.appearance_source_id=p.source_id;project.model.torso_length=14-p.physique.leg_length;},'load-physique');if(currentPage==='model')renderPage();}catch(e){toast(e.message,true);}}
function showPreview(name){preview=name;$$('[data-preview]').forEach(b=>b.classList.toggle('active',b.dataset.preview===name));for(const kind of ['card','stats','model'])$('#preview-'+kind).classList.toggle('hidden',kind!==name);
  if(name==='model'&&currentPage!=='model')viewer?.attach($('#mini-model-stage'));updateLive();}

function sixStats(values){
  const groups=[[34,38],[20,37,27],[21,22],[17,18,19],[15,24,26],[35,39,40]];
  return groups.map(ids=>Math.round(ids.reduce((n,i)=>n+values[i],0)/ids.length));
}
function updateLive(){
  if(!project||!catalog)return;
  simulation=simulate(project,catalog);
  syncStyleHelp(project,catalog);
  $$('[data-identity-code]').forEach(el=>el.textContent=project.identity[el.dataset.identityCode==='nation'?'nation_id':'team_id']??'未选择');
  $('#project-uuid').textContent=project.package_id.slice(0,8)+' · '+project.package_id.slice(-8);
  $('#preview-series').textContent=(project.card_series||project.card_type).replace('BigTime','BIG TIME').toUpperCase()+' · '+(project.appearance.card_title||'PERSONAL EDITION');
  $('#preview-level').textContent=`Lv.${project.initial_level} / ${project.max_level}`;
  $('#preview-overall').innerHTML=`<div><span>计算总评 · ${esc(project.identity.position)}</span><strong style="color:${ratingColor(simulation.ovr)}">${simulation.ovr}</strong></div><p>基础 ${simulation.baseOvr} → 培养 ${simulation.trainedOvr}<br>增能 ${simulation.boostedOvr}${simulation.coach?' → 教练 '+simulation.ovr:''}<small>实时计算 · 原包参考公式${simulation.coach?' · 已计入所选教练':''}</small></p>`;
  coachUI?.updatePreview();
  const current=sixStats(simulation.final),base=sixStats(simulation.base);
  $('#preview-summary').innerHTML=['速度','射门','传球','盘带','防守','身体'].map((name,i)=>`<div class="mini-stat"><span>${name}</span><strong style="color:${ratingColor(current[i])}">${current[i]}</strong>${current[i]!==base[i]?`<small>${current[i]>base[i]?'+':''}${current[i]-base[i]}</small>`:''}</div>`).join('');
  $$('[data-stat-final]').forEach(n=>{const i=n.dataset.statFinal,delta=simulation.final[i]-simulation.base[i];n.style.color=ratingColor(simulation.final[i]);n.innerHTML=`${simulation.final[i]}${delta?`<small>${delta>0?'+':''}${delta}</small>`:''}`;});
  $$('[data-value]').forEach(n=>n.textContent=get(n.dataset.value)+(n.dataset.unit||''));
  const budget=$('#budget-card');if(budget){
    budget.classList.toggle('invalid',!simulation.valid);$('#budget-total').innerHTML=simulation.budget+'<small>点</small>';$('#budget-spent').innerHTML=simulation.spent+'<small>点</small>';$('#budget-remaining').innerHTML=simulation.remaining+'<small>点</small>';
    $('#budget-progress').style.width=(simulation.budget?Math.min(100,simulation.spent/simulation.budget*100):0)+'%';$('#budget-progress').style.background=simulation.valid?'var(--mint)':'var(--red)';
    for(const group of catalog.training_groups){const count=project.training[group.id],next=trainingCost(count+1)-trainingCost(count);$(`[data-group-cost="${group.id}"]`).textContent='已用 '+trainingCost(count)+' 点';$(`[data-group-next="${group.id}"]`).textContent='下次 '+next+' 点';$(`[data-step="1"][data-group="${group.id}"]`).disabled=next>simulation.remaining||count>=40;$(`[data-step="-1"][data-group="${group.id}"]`).disabled=!count;}
    for(const group of catalog.training_groups){$(`[data-training-stats="${group.id}"]`).innerHTML=group.indices.map(i=>`<div class="training-stat-row" data-training-stat="${i}"><span>${esc(catalog.ABILITIES[i])}</span><span>${simulation.base[i]}</span><strong style="color:${ratingColor(simulation.trained[i])}">${simulation.trained[i]}</strong><strong style="color:${ratingColor(simulation.final[i])}">${simulation.final[i]}</strong></div>`).join('');}
    const trainingTarget=project.preview?.training_position||project.identity.position;$('#training-target-note').textContent=`目标 ${trainingTarget} · 该位置参考总评 ${simulation.positionOvrs[trainingTarget]} · 方案可撤销`;
    $('#training-comparison').innerHTML=Object.entries(catalog.ABILITIES).map(([i,label])=>{const delta=simulation.final[i]-simulation.base[i];return `<tr data-training-detail="${i}"><th>${esc(label)}</th><td>${simulation.base[i]}</td><td>${simulation.trained[i]}</td><td>${simulation.boosted[i]}</td><td style="color:${ratingColor(simulation.final[i])}">${simulation.final[i]}</td><td>${delta>0?'+':''}${delta}</td></tr>`;}).join('');
  }
  updateRadar();drawCard();drawThumbnail(project,api);viewer?.update(project);
}
function updateRadar(){
  const values=sixStats(simulation.final),base=sixStats(simulation.base),labels=['速度','射门','传球','盘带','防守','身体'];
  const point=(i,r)=>[155+Math.sin(i*Math.PI/3)*r,143-Math.cos(i*Math.PI/3)*r];
  const polygon=(vs)=>vs.map((v,i)=>point(i,Math.max(5,v/110*102)).join(',')).join(' ');
  const rings=[.25,.5,.75,1].map(f=>`<polygon points="${Array.from({length:6},(_,i)=>point(i,102*f).join(',')).join(' ')}" fill="none" stroke="#2b4050" stroke-width="1"/>`).join('');
  $('#radar-chart').innerHTML=`<svg viewBox="0 0 310 295" aria-label="六维能力雷达图">${rings}${Array.from({length:6},(_,i)=>{const [x,y]=point(i,102);return `<path d="M155 143 ${x} ${y}" stroke="#2b4050"/>`;}).join('')}<polygon points="${polygon(base)}" fill="#6786a118" stroke="#6685a1" stroke-dasharray="3 4"/><polygon points="${polygon(values)}" fill="#71d4a72b" stroke="#85d8b4" stroke-width="2"/>${labels.map((name,i)=>{const [x,y]=point(i,128);return `<text x="${x}" y="${y}" fill="#8ba4b7" font-size="10" text-anchor="middle">${name}</text><text x="${x}" y="${y+15}" fill="#b7dbc9" font-size="11" text-anchor="middle">${values[i]}</text>`;}).join('')}</svg><div class="radar-caption">实线 培养及增能后 · 虚线 1 级基础</div>`;
  $('#stat-overview').innerHTML=[['计算总评',simulation.ovr,'基础 '+simulation.baseOvr],['模拟等级',project.initial_level,'上限 '+project.max_level],['剩余培养点',simulation.remaining,'已用 '+simulation.spent],['天生技能',project.innate_skills.length,'追加 '+project.additional_skills.length+'/100']].map(([label,value,note])=>`<div class="overview-row"><span>${label}</span><strong>${value}<small>${note}</small></strong></div>`).join('')+`<div class="position-ratings"><p>各位置计算总评</p>${Object.entries(simulation.positionOvrs).map(([pos,value])=>`<span class="${pos===project.identity.position?'active':''}">${pos} <strong>${value}</strong></span>`).join('')}</div>`;
}

async function loadImage(id){if(!id)return null;if(imageCache.has(id))return imageCache.get(id);const promise=new Promise(resolve=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>resolve(null);image.src='/assets/'+id;});imageCache.set(id,promise);return promise;}
function rounded(ctx,x,y,w,h,r){ctx.beginPath();ctx.roundRect(x,y,w,h,r);}
function cover(ctx,image,x,y,w,h,zoom=1,dx=0,dy=0){const s=Math.max(w/image.width,h/image.height)*zoom;ctx.drawImage(image,x+(w-image.width*s)/2+dx,y+(h-image.height*s)/2+dy,image.width*s,image.height*s);}
async function drawCard(){
  if(project.native_card?.layers?.length){++cardDrawVersion;$('#card-empty').hidden=true;return nativeCard.update(project,simulation);}
  nativeCard?.clear();$('#native-card-status').textContent='';$('#card-motion-toggle').hidden=true;
  const generation=++cardDrawVersion,p=clone(project),art=p.native_art||{};
  const [portrait,background,foreground,full]=await Promise.all([loadImage(p.appearance.portrait),loadImage(art.background?.asset_id||p.appearance.background_image),loadImage(art.foreground?.asset_id),loadImage(art.full?.asset_id)]);
  if(generation!==cardDrawVersion)return;
  const canvas=$('#player-card'),ctx=canvas.getContext('2d');if(canvas.width!==1200){canvas.width=1200;canvas.height=1720;}ctx.clearRect(0,0,1200,1720);ctx.save();ctx.scale(2,2);
  const fit=(image,x=0,y=0,w=600,h=860,zoom=1,dx=0,dy=0)=>{const scale=Math.min(w/image.width,h/image.height)*zoom;ctx.drawImage(image,x+(w-image.width*scale)/2+dx,y+(h-image.height*scale)/2+dy,image.width*scale,image.height*scale);};
  if(full)fit(full);else{
    if(background)fit(background);
    if(portrait)fit(portrait,0,background?70:0,600,background?670:860,p.appearance.photo_zoom,p.appearance.photo_x,p.appearance.photo_y);
    if(foreground)fit(foreground);
  }
  const visible=Boolean(portrait||background||foreground||full);$('#card-empty').hidden=visible;
  if(visible&&p.appearance.native_overlay_text){ctx.fillStyle='#fff';ctx.textAlign='left';ctx.font='700 72px Arial';ctx.fillText(simulation.ovr,35,100);ctx.font='24px Arial';ctx.fillText(p.identity.position,40,132);ctx.font='600 34px "Microsoft YaHei",Arial';ctx.fillText(p.display_name||p.identity.name||'',35,790,530);}
  ctx.restore();
}

function download(data,filename,mime='application/octet-stream'){
  const blob=data instanceof Blob?data:new Blob([data],{type:mime}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}
async function exportCard(){await drawCard();if(!$('#card-empty').hidden)throw Error('请先选择游戏原版图像或导入自己的照片');const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=1720;canvas.getContext('2d').drawImage($('#player-card'),0,0,1200,1720);canvas.toBlob(blob=>{download(blob,(project.display_name||project.identity.name||'我的球员')+'-卡面.png','image/png');toast('已导出 1200 × 1720 卡面 PNG');},'image/png');}
async function choose(category){const result=await api('dialog',{category});return result.path;}
async function importAsset(category,target){const path=await choose(category);if(!path)return;const asset=await api('assets/import',{path,category});commit(()=>{set(target,asset.id);if(target==='appearance.thumbnail_image')Object.assign(project.appearance,{thumbnail_mode:'image',thumbnail_zoom:1,thumbnail_x:0,thumbnail_y:0});if(target==='appearance.background_image'){project.native_card=null;project.native_card_disabled=true;}if(target==='model.asset')project.model.native_source=null;if(target==='appearance.portrait'){project.native_art??={};project.native_art.portrait={asset_id:asset.id,path:asset.name,kind:'personal-photo'};project.native_art.full=null;project.appearance.portrait_fit='contain';project.appearance.hide_portrait=false;}if(target==='appearance.background_image'&&project.native_art){project.native_art.background=null;project.native_art.full=null;}},target);if(currentPage==='card'||currentPage==='model')renderPage();toast('已导入 '+asset.name);}
async function busy(button,fn){if(button?.classList.contains('busy'))return;button?.classList.add('busy');try{return await fn();}catch(error){toast(error.message,true);}finally{button?.classList.remove('busy');}}

function updateModelControls(){
  const notice=$('#head-fit-notice');if(notice){const spec=modelMetadata.headPreview;notice.textContent=spec?[spec.neck?.warning||'颈部已按当前导出设置处理。',spec.notice].filter(Boolean).join(' '):'正在读取导出接合预览…';}
  if(currentPage!=='model')return;
  const info=$('#model-info');if(info)info.textContent=modelMetadata.meshes?`${modelMetadata.meshes} 个网格 · ${modelMetadata.triangles.toLocaleString()} 个三角面 · ${modelMetadata.bones||0} 根骨骼 · ${(modelMetadata.animations||[]).length} 段动画`:'正在准备模型';
  const select=$('#model-animation');if(select){select.innerHTML=modelMetadata.animations?.length?'<option value="-1">暂停动画</option>'+modelMetadata.animations.map((name,i)=>`<option value="${i}" ${i===0?'selected':''}>${esc(name)}</option>`).join(''):'<option value="-1">模型不包含动画</option>';}
  const morphs=$('#model-morphs');if(morphs)morphs.innerHTML=(modelMetadata.morphs||[]).slice(0,30).map(m=>`<label class="range-field field"><div class="row-between"><span>${esc(m.name)}</span></div><input type="range" min="0" max="1" step=".01" value="${project.model.morphs?.[m.key]??m.value??0}" data-morph-key="${esc(m.key)}" data-morph-mesh="${m.mesh}" data-morph-index="${m.index}"></label>`).join('');
  $('#model-kind-label').textContent=project.model.native_source?'游戏原版模型':project.model.asset?'已导入模型':'尚未选择原版模型';
}

const actions={
  'native-rebuild-card':()=>libraryUI.loadCard(project.native_card?.source_id),
  'new-custom-booster':()=>{const used=new Set((project.custom_boosters||[]).map(b=>b.id)),id=Array.from({length:10000},(_,i)=>1000+i).find(id=>!used.has(id));if(!id)return toast('一个工程最多保存 10000 项自定义增能',true);commit(()=>{project.custom_boosters??=[];project.custom_boosters.push({id,uuid:crypto.randomUUID(),label:'我的增能',conditional:false,effects:{}});project.booster_ids[1]=id;});renderPage();},
  'native-card-library':()=>libraryUI.open('card',project.source_player?.id||''),
  'native-portrait-library':()=>libraryUI.open('portrait',project.source_player?.id||''),
  'native-model-library':()=>libraryUI.open('model',project.source_player?.base_id||''),
  'clear-native-background':()=>{commit(()=>{if(project.native_art)project.native_art.background=null;project.appearance.background_image=null;});renderPage();},
  'clear-native-foreground':()=>{commit(()=>{if(project.native_art)project.native_art.foreground=null;});renderPage();},
  'clear-native-full':()=>{commit(()=>{if(project.native_art)project.native_art.full=null;});renderPage();},
  'preset':()=>{commit(()=>{const vals={14:84,15:48,16:40,17:84,18:84,19:80,20:86,21:72,22:66,23:74,24:45,25:62,26:48,27:68,28:75,29:40,30:40,31:40,32:40,34:86,35:76,36:82,37:82,38:87,39:73,40:76};project.base_abilities=vals;},'preset');renderPage();toast('已载入前锋参考基础值，可撤销或继续调整');},
  'auto-train':()=>{commit(()=>project.training=autoAllocate(project,catalog),'auto-train');renderPage();toast('已按 '+(project.preview?.training_position||project.identity.position)+' 生成参考加点方案');},
  'reset-training':()=>{commit(()=>{for(const g of catalog.training_groups)project.training[g.id]=0;},'reset-training');renderPage();},
  'upload-portrait':()=>importAsset('image','appearance.portrait'),
  'browse-thumbnail':()=>libraryUI.open('thumbnail',project.source_player?.id||''),
  'upload-thumbnail':async()=>{await importAsset('image','appearance.thumbnail_image');},
  'thumbnail-from-portrait':()=>{commit(()=>Object.assign(project.appearance,{thumbnail_mode:'portrait',thumbnail_zoom:1,thumbnail_x:0,thumbnail_y:0}),'thumbnail-source');renderPage();},
  'thumbnail-reset':()=>{commit(()=>Object.assign(project.appearance,{thumbnail_zoom:1,thumbnail_x:0,thumbnail_y:0}),'thumbnail-reset');renderPage();},
  'upload-background':()=>importAsset('image','appearance.background_image'),
  'remove-portrait':()=>{commit(()=>project.appearance.portrait=null,'portrait-remove');renderPage();},
  'remove-background':()=>commit(()=>project.appearance.background_image=null,'background-remove'),
  'photo-reset':()=>{commit(()=>Object.assign(project.appearance,{photo_zoom:1,photo_x:0,photo_y:0}),'photo-reset');renderPage();},
  'export-card':exportCard,
  'upload-model':()=>importAsset('model','model.asset'),
  'reset-model':()=>{commit(()=>project.model.asset=null,'model-reset');renderPage();},
  'upload-model-texture':()=>importAsset('image','model.texture'),
  'remove-model-texture':()=>commit(()=>project.model.texture=null,'texture-remove'),
  'head-handles-reset':()=>{commit(()=>{project.model.binding_handles={head:[0,0,0],neck_root:[0,0,0]};project.model.head_vertical_cm=0;});renderPage();},
  'export-model':async()=>{const data=await viewer.exportGLB();download(data,'我的球员-头模预览.glb','model/gltf-binary');toast('已导出头模预览；游戏实装请在 APK 实装页生成安装包');},
  'model-to-card':async()=>{const result=await api('assets/data',{data:viewer.snapshot()});commit(()=>{project.appearance.portrait=result.id;project.native_art??={};project.native_art.full=null;project.native_art.portrait={asset_id:result.id,kind:'model-capture',path:(project.model.native_source?.path||'导入模型')+' · 预览取景'};project.appearance.photo_zoom=1;project.appearance.photo_x=0;project.appearance.photo_y=0;},'model-to-card');showPreview('card');toast('当前模型取景已用于卡面照片');},
  'read-players':async()=>{const data=await api('save/players',{path:migrationState.save});migrationState.players=data.players;migrationState.selected=null;renderPage();toast(`读取到 ${data.players.length} 名持有球员`);},
  'export-snapshot':async()=>{if(!migrationState.selected)throw Error('请先选择持有球员实例');await flushSave();const p=migrationState.selected;const data=await api('package/export',{save:migrationState.save,apk:migrationState.apk,previous:migrationState.previous,id:p.id,serial:p.serial});if(data.binding)commit(()=>Object.assign(project,data.binding),'native-binding');migrationState.resultUrl=data.url;migrationState.statusType='success';migrationState.status=`已导出最新球员快照\n永久身份 ${data.package_id}\n等级 ${data.progress.level} · 累计经验 ${data.progress.exp_total}\n保存位置 ${data.output}`;updateMigrationOutput();toast('独立球员快照已生成');},
  'inspect-package':async()=>{const data=await api('package/inspect',{path:migrationState.package});const m=data.manifest;migrationState.statusType='success';migrationState.status=`球员包校验通过\n永久身份 ${m.package_id}\n卡牌 ID ${m.card_id} · 实例 ${m.serial}\n等级 ${m.progress.level} · 经验 ${m.progress.exp_total}\n培养记录 ${data.careerplan_rows} 条`;migrationState.resultUrl=null;updateMigrationOutput();},
  'migration-plan':async()=>{try{const data=await api('migration/plan',migrationBody());migrationState.plan=data;migrationState.statusType='success';migrationState.status=formatPlan(data);migrationState.resultUrl=null;renderPage();toast('迁移检查通过，可以生成新存档');}catch(error){migrationState.plan=null;migrationState.statusType='error';migrationState.status=error.message;renderPage();throw error;}},
  'migration-apply':async()=>{if(!migrationState.plan)throw Error('请先预览并通过迁移检查');const data=await api('migration/import',migrationBody());migrationState.statusType='success';migrationState.status=formatPlan(data)+`\n\n输出 ${data.output}\n备份 ${data.backup}`;migrationState.resultUrl=data.url;migrationState.plan=null;renderPage();toast('新存档已生成，原文件已保留并备份');}
};
function migrationBody(){return {save:migrationState.save,package:migrationState.package,apk:migrationState.apk,prefer:migrationState.prefer};}
function formatPlan(data){const labels={insert:'恢复缺失的球员实例',unchanged:'球员数据一致，登记独立包', 'keep-target':'保留目标当前状态','replace-registered':'恢复已登记个人球员'};return `迁移检查通过 · ${labels[data.action]||data.action}\n永久身份 ${data.package_id}\n等级 ${data.progress_after.level} · 经验 ${data.progress_after.exp_total}\n培养记录 ${data.careerplan_rows} 条\n目标版本 ${data.target_release}\n\n只合并这一名球员；卡面、脸模等客户端资源需与版本匹配。`;}

function handleInput(event){
  const el=event.target;
  if(el.dataset.aiStyle){commit(()=>{const selected=new Set(project.ai_playing_styles||[]);if(el.checked)selected.add(el.dataset.aiStyle);else selected.delete(el.dataset.aiStyle);project.ai_playing_styles=Object.keys(catalog.AI_PLAYING_STYLES).filter(k=>selected.has(k));},'ai-style-'+el.dataset.aiStyle);return;}
  if(el.dataset.equipment){const key=el.dataset.equipment;commit(()=>{project.equipment??={boots_id:null,sleeves:'keep'};project.equipment[key]=key==='boots_id'?(el.value===''?null:Number(el.value)):el.value;},'equipment-'+key);return;}
  if(el.dataset.customId){
    const b=project.custom_boosters.find(b=>b.id===Number(el.dataset.customId));if(!b)return;
    commit(()=>{if(el.dataset.customStat){if(el.value==='')return;const n=Math.max(0,Math.min(20,Math.round(Number(el.value))));if(Number.isFinite(n)){b.effects[el.dataset.customStat]=n;el.value=n;}}else b[el.dataset.customField]=el.type==='checkbox'?el.checked:el.value;},'custom-'+el.dataset.customId+'-'+(el.dataset.customStat||el.dataset.customField));
    if(el.dataset.customField==='label'){el.closest('details').querySelector('summary').textContent=el.value;$$('[data-booster-slot] option').filter(o=>Number(o.value)===b.id).forEach(o=>o.textContent=b.label);}
  }else if(el.dataset.bind){
    let value=el.type==='checkbox'?el.checked:el.value;
    if(['number','range'].includes(el.type)||el.dataset.number){if(el.value===''){if(el.dataset.bind==='celebration'){commit(()=>project.celebration=null,'celebration');scheduleSave();}return;}value=Number(el.value);if(!Number.isFinite(value))return;if(el.hasAttribute('min'))value=Math.max(Number(el.min),value);if(el.hasAttribute('max'))value=Math.min(Number(el.max),value);}
    const path=el.dataset.bind;
    if(path==='appearance.thumbnail_mode'){commit(()=>set(path,value),path);renderPage();return;}
    if(path==='card_series'){commit(()=>selectCardSeries(project,value),path);renderPage();return;}
    commit(()=>{set(path,value);if(path==='max_level'){project.initial_level=Math.min(project.initial_level,value);project.max_level_known=true;}if(el.dataset.identityKind){const kind=el.dataset.identityKind,exact=identityOptions[kind].find(r=>r.name+' · #'+r.id===value),matches=identityOptions[kind].filter(r=>r.name===value||r.name_en===value),row=exact||(matches.length===1?matches[0]:null);project.identity[kind==='nation'?'nation_id':'team_id']=row?.id??null;if(row){value=row.name;set(path,value);el.value=value;}}},path);
    $$(`[data-bind="${path}"]`).forEach(other=>{if(other!==el){if(other.type==='checkbox')other.checked=value;else other.value=value;}});
    if(path==='max_level'){$$('[data-bind="initial_level"]').forEach(n=>{n.max=project.max_level;n.value=project.initial_level;});}
  }else if(el.id==='skill-search'){skillQuery=el.value;updateSkillGrid();}
  else if(el.id==='selected-skills-only'){skillSelectedOnly=el.checked;updateSkillGrid();}
  else if(el.dataset.boosterSlot!==undefined){
    const slot=Number(el.dataset.boosterSlot),value=Number(el.value),other=project.booster_ids[slot===0?1:0]||0;
    if(value&&value===other&&!project.custom_boosters.some(b=>b.id===value)){el.value=project.booster_ids[slot]||0;return toast('两个增能槽请选择不同项目',true);}
    commit(()=>{const ids=[project.booster_ids[0]||0,project.booster_ids[1]||0];if(value&&value===other)ids[1-slot]=0;ids[slot]=value;project.booster_ids=ids;},'booster'+slot);$$('[data-booster-slot]').forEach(select=>select.value=project.booster_ids[Number(select.dataset.boosterSlot)]);
  }else if(el.dataset.headTest){viewer.setHeadTest({[el.dataset.headTest]:Number(el.value)});
  }else if(el.dataset.headOption){viewer.setHeadTest({[el.dataset.headOption]:el.type==='checkbox'?el.checked:el.value});
  }else if(el.dataset.modelOption){viewer.setOption(el.dataset.modelOption,el.checked);}
  else if(el.id==='model-animation'){viewer.play(Number(el.value));}
  else if(el.dataset.morphMesh){commit(()=>{project.model.morphs??={};project.model.morphs[el.dataset.morphKey]=Number(el.value);},'morph-'+el.dataset.morphKey);viewer.setMorph(el.dataset.morphMesh,Number(el.dataset.morphIndex),Number(el.value));}
  else if(el.dataset.migration){migrationState[el.dataset.migration]=el.value;migrationState.plan=null;const apply=$('[data-action="migration-apply"]');if(apply)apply.disabled=true;if(el.dataset.migration==='save'){migrationState.players=[];migrationState.selected=null;const exportButton=$('[data-action="export-snapshot"]');if(exportButton)exportButton.disabled=true;}}
  else if(el.name==='native-player'){migrationState.selected=migrationState.players[Number(el.value)];$('[data-action="export-snapshot"]').disabled=false;}
  else if(el.id==='migration-prefer'){migrationState.prefer=el.value;migrationState.plan=null;$('[data-action="migration-apply"]').disabled=true;}
}

document.addEventListener('input',handleInput);
document.addEventListener('click',event=>{
  const customDelete=event.target.closest('[data-custom-delete]');if(customDelete){const id=Number(customDelete.dataset.customDelete);commit(()=>{project.custom_boosters=project.custom_boosters.filter(b=>b.id!==id);project.booster_ids=project.booster_ids.map(v=>v===id?0:v);});renderPage();return;}
  const customRepair=event.target.closest('[data-custom-repair]');if(customRepair){const b=project.custom_boosters.find(b=>b.id===Number(customRepair.dataset.customRepair));if(b){commit(()=>{b.conditional=false;for(const k of Object.keys(b.effects))if(b.effects[k]<0)b.effects[k]=0;},'repair-custom-booster-'+b.id);renderPage();toast('已将负值清零并改为常驻，原永久身份保留，可撤销');}return;}
  const nav=event.target.closest('[data-page]');if(nav){if(!nav.disabled)navigate(nav.dataset.page);return;}
  const previewButton=event.target.closest('[data-preview]');if(previewButton)return showPreview(previewButton.dataset.preview);
  const action=event.target.closest('[data-action]');if(action)return busy(action,actions[action.dataset.action]);
  const type=event.target.closest('[data-card-type]');if(type){commit(()=>selectCardType(project,type.dataset.cardType),'card-type');renderPage();return;}
  const filter=event.target.closest('[data-ability-filter]');if(filter){abilityFilter=filter.dataset.abilityFilter;renderPage();return;}
  const step=event.target.closest('[data-step]');if(step){const key=step.dataset.group,delta=Number(step.dataset.step);commit(()=>project.training[key]=Math.max(0,Math.min(40,project.training[key]+delta)),'training.'+key);$$(`[data-bind="training.${key}"]`).forEach(n=>n.value=project.training[key]);return;}
  const mode=event.target.closest('[data-skill-mode]');if(mode){skillMode=mode.dataset.skillMode;$$('[data-skill-mode]').forEach(n=>n.classList.toggle('active',n===mode));return;}
  const skill=event.target.closest('[data-skill]');if(skill&&!skill.disabled){const id=Number(skill.dataset.skill),target=skillMode==='innate'?'innate_skills':'additional_skills';commit(()=>{const selected=project[target].includes(id);project.innate_skills=project.innate_skills.filter(v=>v!==id);project.additional_skills=project.additional_skills.filter(v=>v!==id);if(!selected)project[target].push(id);},'skill'+id);updateSkillGrid();return;}
  const palette=event.target.closest('[data-palette]');if(palette){const [accent,background,jersey]=palette.dataset.palette.split(',');commit(()=>Object.assign(project.appearance,{accent,background,jersey}),'palette');renderPage();return;}
  const view=event.target.closest('[data-view]');if(view)return viewer.view(view.dataset.view);
  const migrationMode=event.target.closest('[data-migration-mode]');if(migrationMode){migrationState.mode=migrationMode.dataset.migrationMode;migrationState.plan=null;migrationState.status='';migrationState.resultUrl=null;renderPage();return;}
  const picker=event.target.closest('[data-migration-pick]');if(picker)return busy(picker,async()=>{const path=await choose(picker.dataset.category);if(path){migrationState[picker.dataset.migrationPick]=path;migrationState.plan=null;if(picker.dataset.migrationPick==='save'){migrationState.players=[];migrationState.selected=null;}renderPage();}});
});

$('#undo-button').onclick=undo;$('#redo-button').onclick=redo;
$('#open-project').onclick=event=>busy(event.currentTarget,async()=>{await flushSave();const path=await choose('project');if(!path)return;const data=await api('project/import',{path});past=[];future=[];project=data.project;version++;savedVersion=version;renderPage();toast(project.project_import?.models_skipped?'工程已打开；跨平台模型已跳过，资料与卡图已导入':'工程已打开，永久身份与资源已恢复');});
$('#export-project').onclick=()=>toolsUI.exportDialog().catch(e=>toast(e.message,true));
async function createPlayerSlot(prompt=true){
 if(prompt&&await choosePlayerAction('新建独立球员','将建立新的球员槽位和永久身份。当前球员会先保存到“我的球员”，已有球员和游戏存档不变。',[{id:'new',label:'确认新建独立球员',primary:true}])!=='new')return false;
 await flushSave(true);const data=await api('project/new',{});past=[];future=[];project=data.project;version++;savedVersion=version;navigate('library');toast('已建立独立球员槽位，请读取球员模板；旧球员已保存');return true;
}
async function preparePlayerLoad(){
 const emptySlot=project.status==='new-player-slot'&&!project.source_player&&!project.appearance.portrait&&!project.model.asset&&!past.length;
 const choice=await choosePlayerAction('读取球员前，请选择槽位',emptySlot?'当前是空的新建槽位，可以把模板载入这个槽位。另建槽位也会保留当前球员。':`正在编辑“${project.display_name||project.identity.name||'未命名球员'}”。新建独立球员会保留当前工程；覆盖会替换当前球员的资料、能力、卡面及头模。`,playerLoadChoices(emptySlot));
 if(choice==='cancel')return false;
 if(choice==='new')return createPlayerSlot(false);
 if(choice==='overwrite'&&await choosePlayerAction('确认覆盖当前球员？','将保留当前永久身份并用所选模板替换编辑内容。继续前会备份完整当前工程；本次载入可撤销。若想制作另一名球员，请取消并选择新建独立球员。',[{id:'overwrite',label:'备份并覆盖当前球员',danger:true}])!=='overwrite')return false;
 await flushSave(true);if(choice==='overwrite')await api('project/checkpoint',{project});return true;
}
$('#new-project').onclick=event=>busy(event.currentTarget,()=>createPlayerSlot());
$('#help-button').onclick=()=>navigate('tutorial');$('#close-help').onclick=()=>$('#help-dialog').close();$('#help-done').onclick=()=>$('#help-dialog').close();
$('#open-model-page').onclick=()=>{showPreview('card');navigate('model');};
$('#export-card').onclick=()=>busy($('#export-card'),exportCard);
$('#save-player').onclick=event=>busy(event.currentTarget,()=>personalUI.save());
$('#card-motion-toggle').onclick=event=>{nativeCard.setMotion(!nativeCard.motion);event.currentTarget.textContent=nativeCard.motion?'暂停原版动画':'播放原版动画';};
document.addEventListener('keydown',event=>{
  if(event.ctrlKey&&event.key.toLowerCase()==='s'){event.preventDefault();flushSave(true).then(()=>toast('工程已保存')).catch(()=>{});}
  if(event.ctrlKey&&event.key.toLowerCase()==='z'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){event.preventDefault();event.shiftKey?redo():undo();}
});
let drag=null;
$('#player-card').addEventListener('pointerdown',event=>{if(!project?.appearance.portrait)return;drag={x:event.clientX,y:event.clientY,px:project.appearance.photo_x,py:project.appearance.photo_y};event.target.setPointerCapture(event.pointerId);});
$('#player-card').addEventListener('pointermove',event=>{if(!drag)return;const scale=600/event.target.clientWidth;commit(()=>{project.appearance.photo_x=Math.max(-180,Math.min(180,Math.round(drag.px+(event.clientX-drag.x)*scale)));project.appearance.photo_y=Math.max(-180,Math.min(180,Math.round(drag.py+(event.clientY-drag.y)*scale)));},'photo-drag');for(const key of ['photo_x','photo_y']){$$(`[data-bind="appearance.${key}"]`).forEach(n=>n.value=project.appearance[key]);}});
$('#player-card').addEventListener('pointerup',()=>drag=null);$('#player-card').addEventListener('pointercancel',()=>drag=null);

function renderNavigation(){
 document.body.dataset.navigation=navigationMode;
 $('#compact-page-select').innerHTML=navigationGroups.map(([label,ids])=>`<optgroup label="${label}">${ids.map(id=>`<option value="${id}">${pages[id].title}</option>`).join('')}</optgroup>`).join('');$('#compact-page-select').value=currentPage==='library'?'personal':currentPage;$('#compact-page-select').onchange=e=>navigate(e.target.value);
 const item=id=>{const p=pages[id];return `<button class="nav-item ${id===currentPage?'active':''}" data-page="${id}" title="${p.title}"><span>${icon(p.icon)}</span><span>${p.title}</span></button>`;};
 const top=$('#navigation').scrollTop;
 $('#navigation').innerHTML=navigationMode==='full'?Object.keys(pages).filter(id=>!['migration','library'].includes(id)).map(item).join(''):navigationGroups.map(([label,ids],index)=>`<section class="nav-group" data-nav-section="${index}"><button type="button" class="nav-group-toggle" data-nav-group="${index}" aria-expanded="false" aria-controls="nav-section-${index}"><span class="nav-chevron" aria-hidden="true">▸</span>${label}${index===2?'<small data-player-required>先读取球员</small>':''}</button><div id="nav-section-${index}" hidden>${ids.filter(id=>!['migration','library'].includes(id)).map(item).join('')}</div></section>`).join('');
 workspaceNavigation.activate(currentPage,playerReady(project));$('#navigation').scrollTop=top;
 const switcher=document.querySelector('#navigation-mode-toggle');if(switcher){switcher.textContent=navigationMode==='simple'?'切换完整导航':'切换新手导航';switcher.dataset.navigation=navigationMode==='simple'?'full':'simple';}
}

async function boot(){
  hydrateIcons();
  taskCenter=new TaskCenter({api,navigate,toast,page:()=>currentPage});
  const data=await api('bootstrap');new AndroidSidebarResize(data.platform);const setup=await api('setup/status',{}).catch(()=>({preferences:{navigation:'simple'},recommended_mode:'coexist',resources_needed:{update:true,coexist:true}}));navigationMode=setup.preferences.navigation;renderNavigation();project=data.project;catalog=data.catalog;identityOptions=data.identities||identityOptions;migrationState.apk=data.default_apk;
  libraryUI=new LibraryUI({api,commit,project:()=>project,catalog,toast,navigate,rerender:renderPage,beforeLoadPlayer:preparePlayerLoad,status:data.library,apk:data.default_apk,companion:data.default_companion});
  updateUI=new GameImportUI({api,toast,apk:data.default_apk,companion:data.default_companion,rerender:renderPage});
  nativePackageUI=new NativePackageUI({api,toast,platform:data.platform,project:()=>project,apk:data.default_apk,companion:data.default_companion,installationMode:setup.recommended_mode,resourcesNeeded:setup.resources_needed,rigged:data.default_rigged||''});
  releaseUpdatesUI=new ReleaseUpdatesUI({api,toast});
  onboardingUI=new OnboardingUI({api,toast,flushSave,mode:()=>navigationMode,setMode:mode=>{navigationMode=mode;renderNavigation();renderPage();},setSources:(selected,mode)=>{for(const ui of [libraryUI,updateUI])for(const key of ['apk','companion'])if(selected[key])ui[key]=selected[key];migrationState.apk=selected.apk||migrationState.apk;}});
  toolsUI=new WorkspaceTools({api,toast,project:()=>project,flushSave});
  boosterLibraryUI=new BoosterLibraryUI({api,toast,project:()=>project,flushSave,commit,rerender:renderPage});
  packUI=new PackUI({api,toast,rerender:renderPage});
  motionUI=new MotionUI({api,toast,project:()=>project,commit,rerender:renderPage});
  personalUI=new PersonalUI({api,toast,beforeOpenPlayer:async()=>{if(await choosePlayerAction('读取已保存球员','将切换当前编辑内容。当前工程会先备份；切换到其他球员时会保存当前球员。若要创建另一名球员，请使用新建独立槽位。',[{id:'open',label:'备份并读取球员',primary:true}])!=='open')return false;await api('project/checkpoint',{project});return true;},project:()=>project,flushSave,navigate,rerender:renderPage,onPlayerDeleted:id=>{if(packUI.editing)packUI.editing.members=packUI.editing.members.filter(m=>m.kind!=='custom'||m.id!==id);},replaceProject:p=>{past=[];future=[];project=p;version++;savedVersion=version;}});
  coachUI=new CoachUI({api,toast,catalog,identities:()=>identityOptions,project:()=>project,commit,flushSave,navigate,rerender:renderPage,resourceKey:()=>libraryUI.status.cache_directory+':'+libraryUI.status.phase,custom:data.custom_coaches?.rows||[]});
  presetsUI=new CardPresetsUI({api,toast,project:()=>project,commit,rerender:renderPage});
  nativeCard=new NativeCardRenderer($('#player-card'),state=>{$('#native-card-status').textContent=`原版图层 ${state.layers} · 动画 ${state.videos} · 资料素材 ${state.ui||0}${state.missing?' · '+state.missing+' 项未读取':''}`;$('#card-motion-toggle').hidden=!state.videos;},catalog);
  viewer=new ModelViewer(meta=>{if(meta.error){toast(meta.error,true);return;}modelMetadata=meta;updateModelControls();});
  viewer.previewApi=p=>api('model/head-preview',{project:p});
  viewer.onBindingChange=(key,values)=>{commit(()=>{project.model.binding_handles||={head:[0,0,0],neck_root:[0,0,0]};project.model.binding_handles[key]=values;},'head-handle-'+key);values.forEach((v,i)=>{const el=document.querySelector(`[data-bind="model.binding_handles.${key}.${i}"]`);if(el)el.value=v;});};
  viewer.onHeadSelection=key=>{const el=document.querySelector('[data-head-option="selected"]');if(el)el.value=key;};
  const badge=document.querySelector('.workspace-badge>span:last-child');if(badge)badge.textContent=(data.library.game_version||'V15')+' · '+data.version;document.querySelector('#help-dialog h2').textContent='球员工坊 '+(data.library.game_version||'V15')+' · '+data.version;
  viewer.attach($('#mini-model-stage'));renderPage();
  if(data.platform==='pc')await new WindowSession(api,()=>project,token).start();
  releaseUpdatesUI.poll();
  for(const path of ['native-apk/status','game-import/status','library/status'])api(path,{}).catch(()=>{});
  libraryUI.refreshLoaded();
  setInterval(()=>api('ping').catch(()=>{}),12000);
  window.__studio={get project(){return project;},get simulation(){return simulation;},get catalog(){return catalog;},get viewer(){return viewer;},get library(){return libraryUI;},get presets(){return presetsUI;},get nativeCard(){return nativeCard;},flushSave,navigate};
}
boot().catch(error=>{$('#editor-content').innerHTML=`<div class="empty-state">软件未能打开工程<br>${esc(error.message)}<br>请关闭窗口后重新启动球员工坊。</div>`;toast(error.message,true);});


document.addEventListener('change',event=>{const group=event.target.dataset.styleCheckPosition;if(group&&project){setStyleCheckPosition(group,event.target.value,project,catalog);syncStyleHelp(project,catalog);}});
