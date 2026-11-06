(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('schedule-data').textContent);
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const teams = new Map(data.teams.map(t => [t.id,t]));
  const fixtures = new Map(data.fixtures.map(f => [f.id,f]));
  const team = id => teams.get(id) || {id:null,name:'待定',own:false};
  const badge = id => {
    if(id==null)return '<span class="badge">?</span>';
    const t=team(id);
    return t.emblem?`<img class="game-emblem" src="${esc(t.emblem.uri)}" alt="${esc(t.name)}队徽" width="24" height="26" decoding="async">`:
      `<span class="badge ${t.own?'own':''}" aria-label="${esc(t.name)}队徽未读取" title="队徽未读取">${esc(t.name.slice(0,2))}</span>`;
  };
  const key = 'studio-schedule:'+data.uuid+':'+data.run_id;
  let saved = {};
  try { saved=JSON.parse(sessionStorage.getItem(key)||'{}'); } catch (_) { /* WebViews may disable storage. */ }
  const state = {stage:Number.isInteger(saved.stage)&&data.stages[saved.stage]?saved.stage:data.stage_index,
    view:['bracket','fixtures','tables'].includes(saved.view)?saved.view:'bracket',query:'',own:false,group:'all',round:'all',page:0,zoom:1};
  const stage = () => data.stages[state.stage];
  const isTable = () => ['groups','league'].includes(stage().type);
  const persist = () => {try {sessionStorage.setItem(key,JSON.stringify({stage:state.stage,view:state.view}));} catch (_) {}};
  const empty = (heading,description) => `<div class="empty"><span class="empty-mark" aria-hidden="true">◇</span><strong>${esc(heading)}</strong>${esc(description)}</div>`;
  const stageStatus = s => ({complete:'已结束',current:'进行中',pending:'待开始'}[s.status]);
  const matchesSearch = ids => (!state.own || ids.includes(data.player_team_id)) && (!state.query || ids.some(id=>team(id).name.toLocaleLowerCase().includes(state.query)));
  const score = f => f.bye?'轮空':f.played?f.score.join(' : '):'VS';
  function toast(message) {$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,4500);}
  function showDialog(html) {
    $('detail-body').innerHTML=html;
    if(typeof $('detail').showModal==='function') $('detail').showModal();
    else $('detail').setAttribute('open','');
  }
  function closeDialog() {if(typeof $('detail').close==='function') $('detail').close();else $('detail').removeAttribute('open');}
  function legDetail(f) {
    let more=[];
    if(f.penalties)more.push('点球 '+f.penalties.join(' : '));
    if(f.extra_time_score&&f.extra_time_score.some(Boolean))more.push('加时进球 '+f.extra_time_score.join(' : ')+'（已计入比分）');
    return `<div class="detail-leg"><div>${f.legs===2?'第 '+f.leg+' 回合 · ':''}${esc(team(f.home).name)}${f.bye?' · 轮空':' vs '+esc(team(f.away).name)}</div><strong>${score(f)}</strong><div>${f.played?'已结束':'未开赛'}${f.neutral?' · 中立场地':''}${more.length?' · '+esc(more.join(' · ')):''}</div></div>`;
  }
  function ruleText(r,kind) {
    if(['groups','league'].includes(kind)) {
      const sort={points:'积分',goal_difference:'净胜球',goals_for:'进球',head_to_head:'相互战绩',wins:'胜场',seed:'种子顺序'};
      return [`${r.groups} 组 · ${r.cycles===1?'单循环':r.cycles===2?'双循环':r.cycles+' 循环'} · ${r.rounds} 轮`,
        `胜 ${r.win_points} / 平 ${r.draw_points} / 负 ${r.loss_points} 分`,
        `每组前 ${r.advance_per_group} 名直接晋级${r.playoff_per_group?'，随后 '+r.playoff_per_group+' 名进入附加赛':''}`,
        '同分排序：'+r.tiebreakers.map(k=>sort[k]||k).join(' → ')];
    }
    return [r.legs===2?'主客场两回合':'单回合',r.away_goals?'采用客场进球'+(r.away_goals_extra_time?'（含加时）':'（不含加时）'):'不采用客场进球',
      r.extra_time?'平局加时':'不进行加时',r.penalties?'最终平局点球决胜':'',r.neutral?'中立场地':''].filter(Boolean);
  }
  function detailFixture(f) {
    const s=data.stages[f.stage];
    const same=f.tie?data.fixtures.filter(r=>r.stage===f.stage&&r.tie===f.tie).sort((a,b)=>a.leg-b.leg):[f];
    showDialog(`<h2>${esc(s.name)} · 第 ${f.round+1} 轮</h2>${same.map(legDetail).join('')}<p>${esc(ruleText(['groups','league'].includes(s.type)?s.rules:Object.assign({},f,{penalties:f.penalties_allowed}),s.type).join(' · '))}</p><p>比赛结果来自已保存进度。</p>`);
  }
  function header() {
    $('title').textContent=data.name;
    document.title=data.name+' · 赛程中心';
    $('difficulty').textContent='游戏难度 · '+data.difficulty_name;
    $('progress-label').textContent=data.completed?'TOURNAMENT COMPLETE':'TOURNAMENT IN PROGRESS';
    $('subtitle').textContent=data.completed?'本届赛事已结束 · 冠军 '+team(data.champion).name:data.stages[data.stage_index].name+' · 第 '+(data.current_round+1)+' 轮';
    const played=data.fixtures.filter(f=>f.played&&!f.bye).length;
    $('hero-stats').innerHTML=[[data.teams.length,'参赛球队'],[data.stages.length,'赛事阶段'],[played,'已完成比赛']].map(([n,t])=>`<div class="stat"><strong>${n}</strong><span>${t}</span></div>`).join('');
    const f=fixtures.get(data.next_fixture_id);
    const statuses={champion:'本届冠军',complete:'本届赛事已结束',waiting:'等待下一阶段对阵',eliminated:'本届征程已结束',playing:'下一场比赛'};
    $('next-card').innerHTML=`<div class="next-kicker"><span>${esc(f?'UP NEXT / 下一场':statuses[data.player_status]||'我的球队')}</span><span>● ${esc(team(data.player_team_id).name)}</span></div>`+
      (f?`<h3>${badge(f.home)}${esc(team(f.home).name)}<small>VS</small>${badge(f.away)}${esc(team(f.away).name)}</h3><p>${esc(data.stages[f.stage].name)} · 第 ${f.round+1} 轮${f.legs===2?' · 第 '+f.leg+' 回合':''}</p><button id="jump-next">查看对阵 ↗</button>`:
      `<h3>${esc(team(data.player_team_id).name)}</h3><p>${esc(data.completed?'冠军：'+team(data.champion).name:'已完成 '+data.player_played+' 场 · '+(statuses[data.player_status]||'等待对阵'))}</p>`);
    if(f)$('jump-next').onclick=()=>{state.stage=f.stage;state.view='fixtures';state.round=String(f.round);state.own=true;state.page=0;render(true);$('workspace');document.querySelector('.workspace').scrollIntoView({block:'start',behavior:'smooth'});};
  }
  function renderStages() {
    $('stages').innerHTML=data.stages.map(s=>`<button class="stage" data-stage="${s.index}" aria-current="${s.index===state.stage}"><span class="step">${s.status==='complete'?'✓':s.index+1}</span>${esc(s.name)}<span class="stage-status">${stageStatus(s)}</span></button>`).join('');
    $('stages').querySelectorAll('button').forEach(b=>b.onclick=()=>{state.stage=Number(b.dataset.stage);state.group='all';state.round='all';state.page=0;state.zoom=1;state.view=isTable()?'tables':'bracket';render(true);});
  }
  function renderRules() {
    const s=stage(),r=s.rules,parts=ruleText(r,s.type);
    if(!isTable()) {
      parts.unshift(`${r.input_count} 队参赛 · ${r.output_count} 队晋级${r.bypass_count?' · '+r.bypass_count+' 队轮空本阶段后汇合':''}`);
      if(r.neutral_final)parts.push('单回合决赛中立场地');
      Object.entries(r.round_overrides||{}).forEach(([size,opt])=>{
        const rr=Object.assign({},r,opt);if(rr.legs===1)rr.away_goals=false;
        parts.push(size+' 强例外：'+ruleText(rr,s.type).join(' / '));
      });
    }
    $('rules').innerHTML=parts.map(p=>`<span>${esc(p)}</span>`).join('');
  }
  function renderFilters() {
    const s=stage(),r=s.rules;
    $('group').innerHTML='<option value="all">全部小组</option>'+s.groups.map(g=>`<option value="${g.index}">${esc(g.name)}</option>`).join('');
    $('group').parentElement.hidden=!isTable()||s.groups.length<=1;
    $('group').value=state.group;
    const rounds=isTable()?Array.from({length:r.rounds},(_,i)=>i):s.bracket.map(b=>b.index);
    $('round').innerHTML='<option value="all">全部轮次</option>'+rounds.map(i=>`<option value="${i}">${isTable()?'第 '+(i+1)+' 轮':esc(s.bracket[i].name)}</option>`).join('');
    $('round').value=state.round;
    $('own').setAttribute('aria-pressed',String(state.own));
    $('tab-bracket').hidden=isTable();$('tab-tables').hidden=!isTable();
    if(isTable()&&state.view==='bracket')state.view='tables';
    if(!isTable()&&state.view==='tables')state.view='bracket';
    document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===state.view;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
    ['bracket','fixtures','tables'].forEach(v=>$('panel-'+v).hidden=v!==state.view);
  }
  let canvasWidth=0,canvasHeight=0;
  function applyZoom(value) {
    state.zoom=Math.max(.25,Math.min(1.65,value));
    $('bracket-canvas').style.transform=`scale(${state.zoom})`;
    $('bracket-space').style.width=canvasWidth*state.zoom+'px';$('bracket-space').style.height=canvasHeight*state.zoom+'px';
    $('zoom-label').textContent=Math.round(state.zoom*100)+'%';
    pinRoundLabels();
  }
  function pinRoundLabels() {const y=$('bracket-viewport').scrollTop/state.zoom;$('bracket-canvas').querySelectorAll('.round-label').forEach(label=>label.style.top=y+'px');}
  function renderBracket() {
    const s=stage(),rounds=s.bracket;
    $('bracket-title').textContent=s.type==='playoff'?'附加赛 · 晋级之路':'晋级之路';
    if(!rounds.length){$('bracket-canvas').innerHTML=empty('对阵尚未生成','本阶段开始后显示实际参赛球队及对阵，当前不预填晋级球队。');canvasWidth=Math.max(270,$('bracket-viewport').clientWidth-50);canvasHeight=300;applyZoom(1);$('count').textContent='等待阶段开始';return;}
    const nodes=rounds.flatMap(r=>r.nodes),map=new Map(nodes.map(n=>[n.id,n]));
    const gapY=166,gapX=294,cardH=132;let leaf=0;
    function position(n) {if(n.y!=null)return n.y;if(!n.sources.length)n.y=54+(leaf++)*gapY;else n.y=n.sources.map(id=>position(map.get(id))).reduce((a,b)=>a+b,0)/n.sources.length;return n.y;}
    // Final roots determine leaf order, so exact reverse-pairing links remain a
    // clean tree instead of crossing every round. No draw is rearranged.
    nodes.forEach(n=>{delete n.y;});rounds[rounds.length-1].nodes.forEach(position);
    canvasWidth=(rounds.length-1)*gapX+248;canvasHeight=Math.max(300,54+leaf*gapY);
    const svg=[];
    nodes.forEach(n=>n.sources.forEach(id=>{const p=map.get(id),x1=p.round*gapX+228,x2=n.round*gapX,y1=p.y+cardH/2,y2=n.y+cardH/2;svg.push(`<path d="M${x1} ${y1}H${x1+28}V${y2}H${x2}"/>`);}));
    const labels=rounds.map(r=>`<div class="round-label" style="left:${r.index*gapX}px"><b>${esc(r.name)}</b><small>${r.generated?'已生成':'待定'} · ${r.nodes[0].rules.legs===2?'两回合':'单回合'}</small></div>`).join('');
    let matched=0;
    const cards=nodes.map(n=>{
      const ff=n.fixtures.map(id=>fixtures.get(id));
      const chosen=matchesSearch(n.teams)&&(state.round==='all'||String(n.round)===state.round);if(chosen)matched++;
      const total=n.teams.map(id=>ff.reduce((sum,f)=>sum+(f.played?f.score[f.home===id?0:1]:0),0));
      const complete=ff.length&&ff.every(f=>f.played);const played=ff.filter(f=>f.played).length;
      const last=ff[ff.length-1];
      const names=n.teams.map((id,i)=>id!=null?team(id).name:n.bye?'轮空':n.sources.length?'上轮对阵 '+(Number(n.sources[i].split(':')[2])+1)+' 胜者':'待定');
      const body=n.teams.map((id,i)=>`<div class="tie-team ${n.winner!=null&&id===n.winner?'winner':''}">${badge(id)}<span class="name">${esc(names[i])}</span>${n.rules.legs===2&&!n.bye?ff.map(f=>`<span class="tie-score leg">${f.played?f.score[f.home===id?0:1]:'–'}</span>`).join(''):''}<span class="tie-score">${n.bye?'–':played?total[i]:'–'}</span></div>`).join('');
      const status=n.bye?'轮空晋级':complete?'已结束':n.generated?played?'次回合待赛':'未开赛':'晋级球队待定';
      const decision=last&&last.penalties?'点球 '+last.penalties.join(':'):last&&last.extra_time_score&&last.extra_time_score.some(Boolean)?'含加时':n.rules.legs===2?'总比分':'单场决胜';
      return `<button class="tie-card ${n.teams.includes(data.player_team_id)?'own':''} ${!n.generated?'pending':''} ${!chosen?'dim':''}" data-tie="${n.id}" style="left:${n.round*gapX}px;top:${n.y}px;height:${cardH}px" aria-label="${esc(names.join(' 对 '))}，${status}"><div class="tie-head"><span>对阵 ${Number(n.id.split(':')[2])+1}</span><span>${n.rules.legs===2?'首 / 次 / 总':'比分'}</span></div>${body}<div class="tie-foot"><span class="${complete?'success':''}">${status}</span><span>${esc(decision)}</span></div></button>`;
    }).join('');
    $('bracket-canvas').style.width=canvasWidth+'px';$('bracket-canvas').style.height=canvasHeight+'px';
    $('bracket-canvas').innerHTML=`<svg class="wires" width="${canvasWidth}" height="${canvasHeight}" aria-hidden="true">${svg.join('')}</svg>${labels}${cards}`;
    $('bracket-canvas').querySelectorAll('[data-tie]').forEach(b=>b.onclick=()=>{
      if(dragMoved)return;
      const n=map.get(b.dataset.tie),ff=n.fixtures.map(id=>fixtures.get(id));
      if(ff.length)detailFixture(ff[0]);
      else showDialog(`<h2>${esc(rounds[n.round].name)} · 对阵 ${Number(n.id.split(':')[2])+1}</h2><p>晋级球队待定。本轮对阵尚未生成。</p><p>${esc(ruleText(n.rules,s.type).join(' · '))}</p>`);
    });
    $('bracket-hint').textContent=rounds.some(r=>!r.generated)?'未来轮次仅显示规则与晋级连线，球队待定':'';
    $('count').textContent=state.query||state.own||state.round!=='all'?matched+' 组对阵匹配 · 其余淡显':nodes.length+' 组对阵 · '+s.rules.input_count+' 支球队';
    applyZoom(state.zoom);
  }
  function filteredFixtures() {
    return stage().fixture_ids.map(id=>fixtures.get(id)).filter(f=>matchesSearch([f.home,f.away])&&(state.group==='all'||String(f.group)===state.group)&&(state.round==='all'||String(f.round)===state.round)).sort((a,b)=>a.round-b.round||a.leg-b.leg||a.id-b.id);
  }
  function renderFixtures() {
    const rows=filteredFixtures(),pageSize=40,pages=Math.max(1,Math.ceil(rows.length/pageSize));state.page=Math.min(state.page,pages-1);
    const visible=rows.slice(state.page*pageSize,(state.page+1)*pageSize);let last='',html='';
    visible.forEach(f=>{
      const heading=f.round+':'+f.leg;
      if(heading!==last){last=heading;html+=`<h2 class="round-heading"><span>第 ${f.round+1} 轮${f.legs===2?' · 第 '+f.leg+' 回合':''}</span><small>${esc(stage().name)}</small></h2>`;}
      html+=`<button class="fixture-row ${[f.home,f.away].includes(data.player_team_id)?'own':''}" data-fixture="${f.id}"><span class="meta">${f.group!=null?esc(stage().groups.find(g=>g.index===f.group)?.name||''):'淘汰对阵 '+(Number(f.tie.split(':')[2])+1)}<br>${f.neutral?'中立场地':f.legs===2?'主客场两回合':'单回合'}</span><span class="fixture-team home"><span class="name">${esc(team(f.home).name)}</span>${badge(f.home)}</span><span class="match-score">${score(f)}${f.penalties?'<small>点球 '+f.penalties.join(':')+'</small>':f.extra_time_score&&f.extra_time_score.some(Boolean)?'<small>含加时</small>':''}</span><span class="fixture-team away">${f.bye?'':badge(f.away)}<span class="name">${f.bye?'轮空晋级':esc(team(f.away).name)}</span></span><span class="match-state ${f.played?'done':''}">${f.bye?'轮空':f.played?'已结束':'未开赛'}</span></button>`;
    });
    const byes=stage().byes.filter(b=>matchesSearch([b.team])&&(state.group==='all'||String(b.group)===state.group)&&(state.round==='all'||String(b.round)===state.round));
    if(byes.length){html+=`<div class="bye-row">轮空记录 · ${byes.length} 条（无比赛）</div>`;html+=byes.slice(state.page*pageSize,(state.page+1)*pageSize).map(b=>`<div class="bye-row">第 ${b.round+1} 轮 · ${esc(stage().groups[b.group].name)} · ${esc(team(b.team).name)} 轮空</div>`).join('');}
    if(!rows.length&&!byes.length)html=stage().status==='pending'?empty('赛程尚未生成','本阶段开始后显示真实对阵，不预填未来球队。'):empty('没有匹配的比赛','请更换球队、小组或轮次筛选。');
    $('fixtures').innerHTML=html;
    $('fixtures').querySelectorAll('[data-fixture]').forEach(b=>b.onclick=()=>detailFixture(fixtures.get(Number(b.dataset.fixture))));
    $('count').textContent=rows.length+' 场比赛'+(byes.length?' · '+byes.length+' 次轮空':'');
    $('pagination').hidden=pages<=1;
    $('pagination').innerHTML=`<button id="page-prev" ${state.page===0?'disabled':''}>← 上一页</button><span>${state.page+1} / ${pages}</span><button id="page-next" ${state.page===pages-1?'disabled':''}>下一页 →</button>`;
    $('page-prev').onclick=()=>{state.page--;renderFixtures();};$('page-next').onclick=()=>{state.page++;renderFixtures();};
  }
  function renderTables() {
    const s=stage();let count=0;
    const groups=s.groups.filter(g=>(state.group==='all'||String(g.index)===state.group)&&(!state.own||g.teams.includes(data.player_team_id))&&(!state.query||g.teams.some(t=>team(t).name.toLocaleLowerCase().includes(state.query))));
    $('tables').innerHTML=groups.map(g=>{
      count+=g.table.length;
      return `<section class="table-section"><div class="table-heading"><h2>${esc(g.name)}</h2><span>${s.status==='complete'?'最终积分榜':'当前积分榜'} · ${g.table.length} 队</span><button class="table-expand" aria-expanded="false">全部统计 ↔</button></div><div class="table-scroll" tabindex="0" aria-label="${esc(g.name)}积分表，可横向滚动"><table><thead><tr>${['排名','球队','赛','胜','平','负','进','失','净胜','积分'].map(t=>`<th scope="col">${t}</th>`).join('')}</tr></thead><tbody>${g.table.map((r,i)=>`<tr class="${r.team===data.player_team_id?'own':''}"><td><span class="rank ${i<s.rules.advance_per_group?'direct':i<s.rules.advance_per_group+s.rules.playoff_per_group?'playoff':''}">${i+1}</span></td><td><span class="table-team">${badge(r.team)}${esc(team(r.team).name)}${r.team===data.player_team_id?' <small>我的球队</small>':''}</span></td>${['played','wins','draws','losses','goals_for','goals_against','goal_difference','points'].map(k=>`<td>${k==='points'?'<strong>'+r[k]+'</strong>':r[k]}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="table-key"><span><i></i>直接晋级区</span>${s.rules.playoff_per_group?'<span><i class="purple"></i>附加赛区</span>':''}<span>${s.status==='complete'?'本阶段已结束':'排名随已保存赛果更新；色块表示当前排名所在区域'}</span></div></section>`;
    }).join('')||(s.status==='pending'?empty('积分榜尚未生成','本阶段尚未开始，参赛名单与分组待定。'):empty('没有匹配的小组','请调整球队或小组筛选。'));
    $('count').textContent=groups.length+' 个积分榜 · '+count+' 支球队';
    $('tables').querySelectorAll('.table-expand').forEach(b=>b.onclick=()=>{const section=b.closest('.table-section'),expanded=section.classList.toggle('expanded');b.setAttribute('aria-expanded',String(expanded));b.textContent=expanded?'收起统计':'全部统计 ↔';});
    // Round selection filters schedules only; never mislabel current standings
    // as a historical table for a selected round.
    $('round').parentElement.hidden=true;
  }
  function render(resetScroll=false) {
    renderStages();renderFilters();renderRules();
    $('round').parentElement.hidden=state.view==='tables';
    if(state.view==='bracket')renderBracket();else if(state.view==='fixtures')renderFixtures();else renderTables();
    if(resetScroll){$('bracket-viewport').scrollLeft=0;$('bracket-viewport').scrollTop=Math.max(0,(canvasHeight*state.zoom-$('bracket-viewport').clientHeight)/2);}
    if(state.view==='bracket')pinRoundLabels();
    persist();
  }
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{state.view=b.dataset.view;state.page=0;render();});
  document.querySelector('.tabs').onkeydown=e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
    const buttons=[...document.querySelectorAll('[data-view]')].filter(b=>!b.hidden),at=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');
    const n=e.key==='Home'?0:e.key==='End'?buttons.length-1:(at+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[n].click();buttons[n].focus();
  };
  $('search').oninput=()=>{state.query=$('search').value.trim().toLocaleLowerCase();state.page=0;render();};
  $('group').onchange=()=>{state.group=$('group').value;state.page=0;render();};
  $('round').onchange=()=>{state.round=$('round').value;state.page=0;render();};
  $('own').onclick=()=>{state.own=!state.own;state.page=0;render();if(state.own&&state.view==='bracket'){const cards=[...$('bracket-canvas').querySelectorAll('.tie-card.own:not(.dim)')];const card=cards[cards.length-1];if(card){$('bracket-viewport').scrollTop=(parseFloat(card.style.top)+66)*state.zoom-$('bracket-viewport').clientHeight/2;$('bracket-viewport').scrollLeft=Math.max(0,parseFloat(card.style.left)*state.zoom-30);}}};
  $('rules-toggle').onclick=()=>{const expanded=$('rules-toggle').getAttribute('aria-expanded')==='true';$('rules-toggle').setAttribute('aria-expanded',String(!expanded));$('rules').hidden=expanded;};
  $('detail-close').onclick=closeDialog;
  $('detail').onclick=e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeDialog();}};
  $('refresh').onclick=()=>{persist();location.reload();};
  $('back').onclick=()=>{
    // The native host receives WebView's title callback without exposing a
    // broad JavascriptInterface. Outside that host show an honest message.
    if(new URLSearchParams(location.search).get('host')==='android')document.title='player-studio-schedule:close';
    else toast('这是独立界面预览；游戏内承载接入后，此按钮关闭赛程并返回游戏。');
  };
  $('zoom-in').onclick=()=>applyZoom(state.zoom+.15);$('zoom-out').onclick=()=>applyZoom(state.zoom-.15);
  $('zoom-fit').onclick=()=>applyZoom(($('bracket-viewport').clientWidth-48)/Math.max(1,canvasWidth));
  const viewport=$('bracket-viewport');let drag=null,dragMoved=false,pinch=null;
  viewport.addEventListener('scroll',pinRoundLabels,{passive:true});
  viewport.addEventListener('pointerdown',e=>{if(e.pointerType!=='mouse'||e.button!==0)return;drag={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};dragMoved=false;});
  window.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>5){dragMoved=true;viewport.classList.add('dragging');viewport.scrollLeft=drag.left-dx;viewport.scrollTop=drag.top-dy;}});
  window.addEventListener('pointerup',()=>{drag=null;viewport.classList.remove('dragging');setTimeout(()=>dragMoved=false,0);});
  viewport.addEventListener('touchstart',e=>{if(e.touches.length===2)pinch={distance:Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY),zoom:state.zoom};},{passive:true});
  viewport.addEventListener('touchmove',e=>{if(pinch&&e.touches.length===2){e.preventDefault();applyZoom(pinch.zoom*Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY)/pinch.distance);}},{passive:false});
  viewport.addEventListener('touchend',()=>pinch=null,{passive:true});
  header();render(true);
  window.tournamentScheduleReady=true;
})();
