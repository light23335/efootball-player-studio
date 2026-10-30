// Liquid Glass shell: presentation layer around app.js.
// Navigation always goes through #compact-page-select (the control app.js wires
// to navigate()); hub data comes from the existing read-only players/list API.
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const svg=paths=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const ICONS={
 home:'<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
 tutorial:'<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2Z"/><path d="M4 19V5M9 7h6M9 11h4"/>',
 personal:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/>',
 library:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
 profile:'<rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="9" cy="11" r="2.2"/><path d="M5.8 16.5a3.4 3.4 0 0 1 6.4 0M14.5 10h4M14.5 13.5h3"/>',
 abilities:'<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z"/><path d="m12 8 4 2.5-.5 4.5L12 17l-3.5-3 1-4.5Z"/>',
 training:'<path d="M6 7v10M3.5 9.5v5M18 7v10M20.5 9.5v5M6 12h12"/>',
 skills:'<path d="m12 3 2.2 5.3L19.5 10l-5.3 2.2L12 17.5l-2.2-5.3L4.5 10l5.3-1.7Z"/><path d="m19 15.5.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8Z"/>',
 motion:'<circle cx="14.5" cy="4.5" r="2"/><path d="M7 21l3.5-6 3 2.5V22M5 11.5 8.5 8h5l3 4 3.5.5M10.5 15l2-6"/>',
 card:'<rect x="5" y="2.5" width="14" height="19" rx="2.5"/><path d="m12 7 1.3 2.7 3 .4-2.2 2 .6 3L12 13.6 9.3 15l.6-3-2.2-2 3-.4Z"/>',
 model:'<path d="m12 3 8.5 4.8v8.4L12 21l-8.5-4.8V7.8Z"/><path d="m3.5 7.8 8.5 4.8 8.5-4.8M12 12.6V21"/>',
 packs:'<path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 12.5 9 5 9-5"/><path d="m3 16.5 9 5 9-5"/>',
 coaches:'<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2.8h6V4M8.5 10h7M8.5 14h7M8.5 18h4"/>',
 native:'<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M12 7v7m-3-3 3 3 3-3M10.5 18.5h3"/>',
 apk:'<ellipse cx="11" cy="5.5" rx="7" ry="2.5"/><path d="M4 5.5v6c0 1.4 3.1 2.5 7 2.5M18 5.5V9M4 11.5v6c0 1.4 3.1 2.5 7 2.5"/><path d="M21.5 16a3.5 3.5 0 1 1-1-2.5M21.5 12v3h-3"/>',
 tools:'<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
 edit:'<path d="M4 20h4L19 9l-4-4L4 16Z"/><path d="m13.5 6.5 4 4"/>',
 grid:'<rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 4 2l-1.5 1v2m0 3h.01"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
 eye:'<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
 undo:'<path d="M8 4 3 9l5 5M4 9h10a6 6 0 0 1 0 12h-3"/>',redo:'<path d="m16 4 5 5-5 5m4-5H10a6 6 0 0 0 0 12h3"/>',
 folder:'<path d="M3 7V5a2 2 0 0 1 2-2h4l3 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
 export:'<path d="M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6"/>'
};
const SECTIONS=[{label:'总览',icon:'home'},{label:'我的球员',icon:'personal'},{label:'编辑球员',icon:'edit'},{label:'卡包与教练',icon:'packs'},{label:'生成安装',icon:'native'},{label:'更多工具',icon:'grid'}];
const EYEBROW={home:'Overview',tutorial:'Playbook',personal:'My Squad',library:'Scouting',profile:'Profile',abilities:'Attributes',training:'Training',skills:'Skills & Style',motion:'Motion',card:'Card Design',model:'3D Model',packs:'Packs',coaches:'Coaching Staff',native:'Build APK',apk:'Game Source',tools:'Settings'};
// eFootball ratings top out at 120: gauges and bars use this as their full scale.
const STAT_MAX=120;
const EDITOR=new Set(['profile','abilities','training','skills','motion','card','model']);
const DEFAULT_PALETTE={c1:'hsl(196 92% 60%)',c2:'hsl(232 88% 64%)',c3:'hsl(272 80% 62%)',tint:'hsl(222 40% 5%)'};
const token=new URLSearchParams(location.search).get('token')||'';
const select=$('#compact-page-select'),body=document.body,root=document.documentElement;
const pageId=()=>{const page=body.dataset.workspacePage||'home';return page==='library'?'personal':page;};
const groups=()=>[...select.querySelectorAll('optgroup')].map((group,index)=>({index,label:group.label,pages:[...group.querySelectorAll('option')].map(o=>({id:o.value,title:o.textContent,disabled:o.disabled}))}));
const sectionIndex=()=>groups().findIndex(g=>g.pages.some(p=>p.id===pageId()));
const studio=()=>window.__studio;
const project=()=>studio()?.project;
function go(id){
 const option=[...select.options].find(o=>o.value===id);
 if(!option||option.disabled)return false;
 closeOverlays();
 if(pageId()!==id){select.value=id;select.dispatchEvent(new Event('change',{bubbles:true}));}
 return true;
}
function goSection(index){
 const group=groups()[index];if(!group||group.pages.some(p=>p.id===pageId()))return;
 const target=group.pages.find(p=>!p.disabled);if(target)go(target.id);
}

/* ---------- dock + page tabs ---------- */
const dock=$('#section-tabs'),tabs=$('#page-tabs');
function renderNavigation(){
 const list=groups();if(!list.length)return;
 const active=sectionIndex(),page=pageId();
 dock.innerHTML=list.map(g=>{const meta=SECTIONS[g.index]||{label:g.label,icon:'grid'},locked=g.pages.every(p=>p.disabled);
  return `<button type="button" class="dock-button" data-section="${g.index}" ${g.index===active?'aria-current="page"':''} ${locked?'disabled':''} aria-label="${meta.label}">${svg(ICONS[meta.icon])}<span class="dock-tip">${meta.label}${locked?' · 先读取球员':''}</span></button>`;}).join('');
 const group=list[active];
 tabs.innerHTML=group&&group.pages.length>1?'<span class="thumb"></span>'+group.pages.map(p=>`<button type="button" class="page-tab" data-go="${p.id}" ${p.id===page?'aria-current="page"':''} ${p.disabled?'disabled':''}>${svg(ICONS[p.id]||ICONS.grid)}${esc(p.title)}</button>`).join(''):'';
 placeThumb(false);
}
function placeThumb(animate=true){
 const thumb=tabs.querySelector('.thumb'),current=tabs.querySelector('[aria-current]');if(!thumb||!current)return;
 if(!animate)thumb.style.transition='none';
 thumb.style.left=current.offsetLeft+'px';thumb.style.width=current.offsetWidth+'px';
 if(!animate)requestAnimationFrame(()=>thumb.style.transition='');
 current.scrollIntoView({block:'nearest',inline:'center'});
}
dock.addEventListener('click',event=>{const button=event.target.closest('[data-section]');if(button&&!button.disabled)goSection(Number(button.dataset.section));});
tabs.addEventListener('click',event=>{const button=event.target.closest('[data-go]');if(!button||button.disabled)return;
 // slide the thumb first; app.js re-renders the page right after
 tabs.querySelectorAll('[aria-current]').forEach(b=>b.removeAttribute('aria-current'));button.setAttribute('aria-current','page');placeThumb();go(button.dataset.go);});
addEventListener('resize',()=>placeThumb(false));
$('#shell-home').addEventListener('click',event=>{event.preventDefault();go('home');});

/* ---------- drawer with the original full navigation ---------- */
const drawer=$('#workspace-sidebar'),menuButton=$('#shell-menu-button');
const scrim=document.createElement('div');scrim.className='shell-scrim';body.append(scrim);
const quick=document.createElement('div');quick.className='drawer-quick';
quick.innerHTML=[['undo-button','撤销','undo'],['redo-button','重做','redo'],['open-project','打开工程','folder'],['export-project','导出工程','export']].map(([id,label,icon])=>`<button type="button" class="button subtle" data-proxy="${id}">${svg(ICONS[icon])}${label}</button>`).join('');
$('.workspace-badge').after(quick);
quick.addEventListener('click',event=>{const proxy=event.target.closest('[data-proxy]');if(!proxy)return;closeOverlays();document.getElementById(proxy.dataset.proxy)?.click();});
function setDrawer(open){body.classList.toggle('drawer-open',open);menuButton.setAttribute('aria-expanded',String(open));if(open){body.classList.remove('preview-sheet-open');for(const b of quick.querySelectorAll('[data-proxy]'))b.disabled=document.getElementById(b.dataset.proxy)?.disabled;}}
menuButton.onclick=()=>setDrawer(!body.classList.contains('drawer-open'));
$('#shell-menu-close').onclick=()=>setDrawer(false);
drawer.addEventListener('click',event=>{if(event.target.closest('.nav-item,#help-button'))setTimeout(()=>setDrawer(false),60);if(event.target.closest('.brand')){event.preventDefault();go('home');}});
scrim.onclick=closeOverlays;
function closeOverlays(){setDrawer(false);body.classList.remove('preview-sheet-open');}

/* ---------- stage drawer ---------- */
const fab=document.createElement('button');fab.type='button';fab.className='preview-fab';fab.setAttribute('aria-label','查看球员卡');body.append(fab);
fab.onclick=()=>{if(root.dataset.uiStage!=='sheet')return;setDrawer(false);body.classList.add('preview-sheet-open');};
$('.preview-close').onclick=closeOverlays;
const overall=()=>studio()?.simulation?.ovr??'';

/* ---------- palette sampled from the card ---------- */
const cardCanvas=$('#player-card'),cardEmpty=$('#card-empty');
const sample=document.createElement('canvas');sample.width=40;sample.height=58;
const sampleCtx=sample.getContext('2d',{willReadFrequently:true});
function hsl(r,g,b){r/=255;g/=255;b/=255;const M=Math.max(r,g,b),m=Math.min(r,g,b),l=(M+m)/2,d=M-m;if(!d)return[0,0,l];
 const s=d/(1-Math.abs(2*l-1));const h=M===r?((g-b)/d)%6:M===g?(b-r)/d+2:(r-g)/d+4;return[(h*60+360)%360,s,l];}
const color=(h,s,l)=>`hsl(${Math.round(h)} ${Math.round(s*100)}% ${Math.round(l*100)}%)`;
function paletteFrom(source){
 sampleCtx.clearRect(0,0,40,58);sampleCtx.drawImage(source,0,0,40,58);
 const data=sampleCtx.getImageData(0,0,40,58).data,bins=Array.from({length:24},()=>({w:0,h:0}));
 for(let i=0;i<data.length;i+=4){if(data[i+3]<200)continue;const [H,S,L]=hsl(data[i],data[i+1],data[i+2]);if(S<.22||L<.1||L>.92)continue;
  const w=S*(1-Math.abs(L-.5)),bin=bins[Math.floor(H/15)];bin.w+=w;bin.h+=H*w;}
 const ranked=bins.filter(b=>b.w>0).sort((a,b)=>b.w-a.w);if(!ranked.length)return null;
 const top=ranked[0].w,picks=[];
 // small accents such as club badges must not steer the whole interface
 for(const b of ranked){if(b.w<top*.14)break;const H=b.h/b.w;if(picks.every(p=>Math.min(Math.abs(p-H),360-Math.abs(p-H))>=30))picks.push(H);if(picks.length===3)break;}
 while(picks.length<3)picks.push((picks[0]+(picks.length===1?32:-36)+360)%360);
 return {c1:color(picks[0],.9,.6),c2:color(picks[1],.85,.58),c3:color(picks[2],.8,.55),tint:color(picks[0],.42,.05)};
}
let paletteKey='';
function updatePalette(){
 let palette=DEFAULT_PALETTE;
 if(cardEmpty?.hidden&&cardCanvas.width){try{palette=paletteFrom(cardCanvas)||DEFAULT_PALETTE;}catch{palette=DEFAULT_PALETTE;}}
 const key=JSON.stringify(palette);if(key===paletteKey)return;paletteKey=key;
 for(const [k,v] of Object.entries(palette))root.style.setProperty('--'+k,v);
}
setInterval(()=>{if(!document.hidden)updatePalette();},1500);

/* ---------- holographic tilt (off while the photo is being dragged) ---------- */
const stage=$('#stage'),tilt=$('#card-tilt');let dragging=false;
cardCanvas.addEventListener('pointerdown',()=>{dragging=true;resetTilt();});
addEventListener('pointerup',()=>dragging=false);addEventListener('pointercancel',()=>dragging=false);
function tiltTowards(event){
 if(dragging||event.pointerType==='touch')return;
 const r=tilt.getBoundingClientRect();if(!r.width)return;
 const px=Math.min(1,Math.max(0,(event.clientX-r.left)/r.width)),py=Math.min(1,Math.max(0,(event.clientY-r.top)/r.height));
 tilt.classList.add('active');tilt.style.setProperty('--rx',((.5-py)*16)+'deg');tilt.style.setProperty('--ry',((px-.5)*20)+'deg');
 tilt.style.setProperty('--px',(px*100)+'%');tilt.style.setProperty('--py',(py*100)+'%');tilt.style.setProperty('--hyp',Math.min(1,Math.hypot(px-.5,py-.5)*1.7));
}
function resetTilt(){tilt.classList.remove('active');tilt.style.setProperty('--rx','0deg');tilt.style.setProperty('--ry','0deg');tilt.style.setProperty('--hyp',0);}
stage.addEventListener('pointermove',tiltTowards);
stage.addEventListener('pointerleave',resetTilt);

/* ---------- identity strip (editor pages) ---------- */
const identity=$('#identity'),stageName=$('#stage-name');
const clean=v=>String(v||'').replace(/\s*·\s*#\d+$/,'').trim();
function countUp(el,to){const from=Number(el.textContent)||0;if(from===to)return;const start=performance.now(),d=900;
 const step=t=>{const p=Math.min(1,(t-start)/d),e=1-Math.pow(1-p,4);el.textContent=Math.round(from+(to-from)*e);if(p<1)requestAnimationFrame(step);};requestAnimationFrame(step);}
function renderIdentity(fresh){
 const p=project(),sim=studio()?.simulation;
 const name=p?.identity?.name?.trim()||p?.display_name||'未命名球员';
 // the outlined backdrop name only reads well in Latin letters
 const latin=[p?.identity?.shirt_name,p?.display_name,name].find(v=>v&&/^[ -~]+$/.test(v.trim()));
 stageName.textContent=latin||'';
 if(!EDITOR.has(pageId())||!p){identity.hidden=true;return;}
 identity.hidden=false;
 if(fresh||!identity.firstChild){
  identity.innerHTML=`<div class="gauge"><svg viewBox="0 0 120 120"><circle class="bg" cx="60" cy="60" r="50"/><circle class="fg" cx="60" cy="60" r="50"/></svg><b>0</b><small>OVR</small></div>
   <div class="identity-name"><h1></h1><div class="cn"></div><div class="tags"></div></div>
   <div class="identity-budget"><div class="row"><span>剩余培养点</span><b><span class="left">0</span> / <span class="total">0</span></b></div><div class="track"><i></i></div><div class="levels"><span class="lv"></span><span class="series"></span></div></div>`;
  identity.dataset.enter='';setTimeout(()=>delete identity.dataset.enter,900);
 }
 identity.querySelector('h1').textContent=name;
 const alt=[p.display_name,p.identity.shirt_name].find(v=>v&&v.trim()&&v.trim()!==name);
 identity.querySelector('.cn').textContent=alt||'';
 identity.querySelector('.tags').innerHTML=[p.identity.position,p.identity.preferred_foot,clean(p.identity.nationality),clean(p.identity.team),p.identity.height_cm&&p.identity.height_cm+' cm'].filter(Boolean).map(t=>`<span class="tag">${esc(t)}</span>`).join('');
 const ovr=Number(sim?.ovr)||0;
 countUp(identity.querySelector('.gauge b'),ovr);
 requestAnimationFrame(()=>identity.querySelector('.gauge .fg').style.strokeDashoffset=314*(1-Math.min(1,ovr/STAT_MAX)));
 const budget=sim?.budget||0,left=sim?.remaining??0;
 identity.querySelector('.left').textContent=left;identity.querySelector('.total').textContent=budget;
 identity.querySelector('.track i').style.width=(budget?Math.min(100,(budget-left)/budget*100):0)+'%';
 identity.querySelector('.lv').textContent=`Lv.${p.initial_level} / ${p.max_level}`;
 identity.querySelector('.series').textContent=$('#preview-series')?.textContent||'';
}
function renderFab(){const ovr=overall();fab.innerHTML=`<b>${ovr||svg(ICONS.eye)}</b>球员卡`;}

/* ---------- overview hub ---------- */
const hub=$('#hub');let squad=null,squadAt=0;
// The native card only animates while its canvas is laid out (native-card.js
// checks offsetParent), so the overview borrows the real card instead of a copy.
const cardHome=$('#preview-card');
function returnCard(reset=true){if(tilt.parentElement!==cardHome){if(reset)resetTilt();cardHome.prepend(tilt);}}
async function loadSquad(force){
 if(!force&&squad&&Date.now()-squadAt<15000)return;
 squadAt=Date.now();
 try{const response=await fetch('/api/players/list',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:JSON.stringify({query:'',offset:0,limit:12})});
  const data=await response.json();if(response.ok){squad=data;if(pageId()==='home')renderHub();}}catch{}
}
const pageTitle=id=>[...select.options].find(o=>o.value===id)?.textContent||id;
// Game resources must be imported before anything can be built: the feature tile follows the library state.
const libraryPhase=()=>studio()?.library?.status?.phase||'';
const SETUP_TILE={ready:null,preparing:['资源库准备中','正在读取球员数据库与原版资源，完成后即可生成游戏 APK'],missing:['导入游戏资源库','选择游戏 APK 与离线资源包，读取球员数据库与原版资源']};
function tile(id,{kicker,title,sub,icon,cls='',count=''}){
 const option=[...select.options].find(o=>o.value===id),locked=!option||option.disabled;
 return `<button type="button" class="tile glass ${cls}" data-go="${id}" ${locked?'disabled':''}><i class="tile-icon">${svg(ICONS[icon||id]||ICONS.grid)}</i>${count}<span class="tile-kicker">${kicker}</span><strong>${title||esc(pageTitle(id))}</strong>${sub?`<small>${sub}</small>`:''}</button>`;
}
function renderHub(){
 // re-rendering the overview keeps the card's tilt; leaving it puts the card back on the stage
 if(pageId()!=='home'){returnCard();hub.hidden=true;return;}
 returnCard(false);
 hub.hidden=false;
 const p=project(),ready=body.dataset.playerReady==='true',name=p?.identity?.name?.trim(),ovr=overall();
 const phase=libraryPhase(),libraryReady=phase==='ready',setup=SETUP_TILE[libraryReady?'ready':phase==='preparing'?'preparing':'missing'];
 hubPhase=phase;
 const featureTile=setup?`<button type="button" class="tile glass feature" data-setup-jump><i class="tile-icon">${phase==='preparing'?'<span class="spinner"></span>':svg(ICONS.apk)}</i><span class="tile-kicker">Setup</span><strong>${setup[0]}</strong><small>${setup[1]}</small></button>`:tile('native',{kicker:'Build',title:'生成游戏 APK',sub:'选择球员、教练与卡包，写入游戏安装包',cls:'feature'});
 const heroActions=ready?'<button type="button" class="button primary" data-go="profile">继续编辑</button><button type="button" class="button secondary" data-go="personal">我的球员</button>':libraryReady?'<button type="button" class="button primary" data-new-player>新建球员</button><button type="button" class="button secondary" data-go="personal">我的球员</button>':'<button type="button" class="button primary" data-setup-jump>导入游戏资源库</button><button type="button" class="button secondary" data-go="tutorial">详细教程</button>';
 const count=squad?`<span class="tile-count">${squad.saved_total??squad.total}<small>名</small></span>`:'';
 const rail=(squad?.rows||[]).map(r=>`<button type="button" class="rail-card" data-go="personal">${r.portrait?`<img src="/assets/${esc(r.portrait)}" alt="" loading="lazy">`:''}<b>${esc(r.overall?.current??'')}<small>${esc(r.position||'')}</small></b><strong>${esc(r.display_name||r.name)}</strong><span>${esc([r.card_type,r.folder_name].filter(Boolean).join(' · '))}</span></button>`).join('');
 const heroName=ready?[p?.identity?.shirt_name,p?.display_name,name].find(v=>v&&/^[ -~]+$/.test(v.trim()))||'':'PLAYER STUDIO';
 hub.innerHTML=`<div class="hub-hero glass"><span class="hero-name">${esc(heroName)}</span>
   <div class="hero-copy"><div class="eyebrow">${ready?'Current Player':'Player Studio'}</div><h2>${esc(ready?(name||'未命名球员'):'打造你的传奇球员')}</h2>
    ${ready?`<div class="hero-meta">${ovr?`<b>${ovr}</b>`:''}${[p.identity.position,clean(p.identity.team),$('#preview-series')?.textContent].filter(Boolean).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div>`:`<p>${libraryReady?'从原版球员复制或新建一名球员，编辑能力、技能与卡面，再生成可安装的游戏 APK。':'先导入游戏资源库，再从原版球员复制或新建一名球员，编辑能力、技能与卡面，最后生成可安装的游戏 APK。'}</p>`}
    <div class="hero-actions">${heroActions}</div></div>
   <div class="hero-card"></div></div>
  <div class="hub-tiles">${featureTile}${tile('personal',{kicker:'Squad',sub:'保存、分组与导出自建球员',count})}${tile('packs',{kicker:'Packs',sub:'混编原版与自建球员，设置抽取权重'})}${tile('coaches',{kicker:'Staff',sub:'原版与自建教练、战术加成'})}${tile('apk',{kicker:'Source',sub:'导入新版游戏，刷新资源库'})}${tile('tools',{kicker:'Settings',sub:'导出文件、直接安装与 AI 进度'})}</div>
  <div class="hub-rail-head"><h3>我的球员<small>Recent</small></h3><button type="button" class="text-link" data-go="personal">查看全部</button></div>
  <div class="hub-rail">${rail}<button type="button" class="rail-card new" data-new-player><i>＋</i>新建球员</button></div>
  <div class="hub-setup-head"><span>游戏准备</span><em>Get ready</em></div>`;
 hub.querySelector('.hero-card').append(tilt);
}
hub.addEventListener('click',event=>{
 if(event.target.closest('[data-new-player]')){$('#new-project').click();return;}
 if(event.target.closest('[data-setup-jump]')){jumpToSetup();return;}
 const target=event.target.closest('[data-go]');if(target&&!target.disabled)go(target.dataset.go);
});
// The import controls live in the onboarding step right below the overview.
function jumpToSetup(){
 // the step's controls render after setup/status returns; the step panel itself is always there
 const step=$('#editor-content [data-setup-import]')?.closest('.panel')||$('#editor-content .beginner-steps .panel');
 if(!step){go('apk');return;}
 step.scrollIntoView({behavior:'smooth',block:'center'});
 step.classList.remove('flash');void step.offsetWidth;step.classList.add('flash');
 setTimeout(()=>step.classList.remove('flash'),2200);
}
let hubPhase='';
setInterval(()=>{if(pageId()==='home'&&!document.hidden&&libraryPhase()!==hubPhase)renderHub();},1500);
hub.addEventListener('pointermove',event=>{if(event.target.closest('.hub-hero'))tiltTowards(event);else resetTilt();});
hub.addEventListener('pointerleave',resetTilt);

/* ---------- command palette (Ctrl+K) ---------- */
const palette=document.createElement('dialog');palette.className='palette-dialog';
palette.innerHTML=`<div class="palette-search">${svg(ICONS.search)}<input type="search" placeholder="搜索页面，回车跳转" aria-label="搜索页面"><kbd>Esc</kbd></div><div class="palette-list" role="listbox"></div>`;
body.append(palette);
const paletteInput=palette.querySelector('input'),paletteList=palette.querySelector('.palette-list');
let paletteItems=[],paletteIndex=0;
function renderPalette(){
 const query=paletteInput.value.trim().toLowerCase();
 const pages=groups().flatMap(g=>g.pages.map(p=>({...p,group:(SECTIONS[g.index]||{}).label||g.label}))).concat([{id:'__help',title:'使用说明',group:'帮助'}]);
 paletteItems=pages.filter(p=>!query||(p.title+p.group+p.id).toLowerCase().includes(query));
 paletteIndex=Math.min(paletteIndex,Math.max(0,paletteItems.length-1));
 let group='';
 paletteList.innerHTML=paletteItems.length?paletteItems.map((p,i)=>{const head=p.group!==group?`<div class="palette-group">${esc(p.group)}</div>`:'';group=p.group;
  return head+`<button type="button" class="palette-item" role="option" data-index="${i}" aria-selected="${i===paletteIndex}" ${p.disabled?'disabled':''}><i>${svg(ICONS[p.id]||ICONS.help)}</i>${esc(p.title)}${p.disabled?'<small>先读取或新建球员</small>':p.id===pageId()?'<small>当前页面</small>':''}</button>`;}).join(''):'<div class="palette-empty">没有匹配的页面</div>';
 paletteList.querySelector('[aria-selected=true]')?.scrollIntoView({block:'nearest'});
}
function choose(index){const item=paletteItems[index];if(!item||item.disabled)return;palette.close();if(item.id==='__help')$('#help-button').click();else go(item.id);}
function openPalette(){if(palette.open)return;closeOverlays();paletteInput.value='';paletteIndex=0;renderPalette();palette.showModal();paletteInput.focus();}
paletteInput.addEventListener('input',()=>{paletteIndex=0;renderPalette();});
paletteInput.addEventListener('keydown',event=>{
 if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const delta=event.key==='ArrowDown'?1:-1;
  for(let i=0;i<paletteItems.length;i++){paletteIndex=(paletteIndex+delta+paletteItems.length)%paletteItems.length;if(!paletteItems[paletteIndex].disabled)break;}renderPalette();}
 else if(event.key==='Enter'){event.preventDefault();choose(paletteIndex);}
});
paletteList.addEventListener('click',event=>{const item=event.target.closest('[data-index]');if(item)choose(Number(item.dataset.index));});
palette.addEventListener('click',event=>{if(event.target===palette)palette.close();});
$('#shell-command').onclick=openPalette;
document.addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openPalette();return;}
 if(event.key==='Escape'&&(body.classList.contains('drawer-open')||body.classList.contains('preview-sheet-open')))closeOverlays();
});

/* ---------- slider fill, nav icons, page entrance ---------- */
function fill(range){const min=Number(range.min)||0,max=Number(range.max)||100,value=Number(range.value);range.style.setProperty('--fill',(max>min?(value-min)/(max-min)*100:0)+'%');}
document.addEventListener('input',event=>{if(event.target.type==='range')fill(event.target);},true);
let fillQueued=false;
function fillAll(){if(fillQueued)return;fillQueued=true;requestAnimationFrame(()=>{fillQueued=false;$$('input[type=range]').forEach(fill);});}
function skinNavigation(){
 for(const item of $$('.nav-item[data-page]')){const id=item.dataset.page,slot=item.firstElementChild;
  if(!slot||!ICONS[id]||slot.dataset.skin===id)continue;slot.dataset.skin=id;slot.innerHTML=svg(ICONS[id]);}
}
const heading=$('.page-heading'),content=$('#editor-content');let lastPage=null,enterTimer;
function onPage(){
 const page=body.dataset.workspacePage;if(!page)return;
 body.classList.toggle('is-editor',EDITOR.has(page));
 renderNavigation();
 const fresh=page!==lastPage;
 renderIdentity(fresh);renderFab();
 if(!fresh)return;
 lastPage=page;$('#page-eyebrow').textContent=EYEBROW[page]||'Player Studio';
 closeOverlays();window.scrollTo({top:0});
 // phones show the card itself above the editor; make sure it is the card pane
 if(EDITOR.has(page)&&root.dataset.uiShell==='phone'&&$('#preview-card').classList.contains('hidden'))$('[data-preview="card"]')?.click();
 content.dataset.enter='';heading.dataset.enter='';clearTimeout(enterTimer);
 enterTimer=setTimeout(()=>{delete content.dataset.enter;delete heading.dataset.enter;},900);
 if(page==='home')loadSquad();
 renderHub();updatePalette();
}

/* ---------- observers ---------- */
new MutationObserver(skinNavigation).observe($('#navigation'),{childList:true,subtree:true});
new MutationObserver(()=>{renderNavigation();if(pageId()==='home')renderHub();if(palette.open)renderPalette();}).observe(select,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
new MutationObserver(onPage).observe(body,{attributes:true,attributeFilter:['data-workspace-page','data-player-ready']});
// updateLive() rewrites #preview-overall on every change: refresh the strip and FAB with it
new MutationObserver(()=>{renderIdentity(false);renderFab();}).observe($('#preview-overall'),{childList:true,subtree:true,characterData:true});
new MutationObserver(fillAll).observe(content,{childList:true,subtree:true});
new MutationObserver(()=>{const want=EYEBROW[body.dataset.workspacePage];const el=$('#page-eyebrow');if(want&&el.textContent!==want)el.textContent=want;}).observe($('#page-eyebrow'),{childList:true,characterData:true,subtree:true});
new MutationObserver(updatePalette).observe(cardEmpty,{attributes:true,attributeFilter:['hidden']});
addEventListener('studio-project-saved',()=>{if(pageId()==='home')loadSquad(true);});
skinNavigation();onPage();fillAll();updatePalette();
