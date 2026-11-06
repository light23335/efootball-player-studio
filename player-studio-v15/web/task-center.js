// 球员工坊 · 任务中心：耗时操作统一显示在右下角，可收起、离开页面也继续跟踪
const KINDS={
  'native-apk':{title:'生成 APK 实装包',page:'native',status:'native-apk/status'},
  'game-import':{title:'导入新版游戏数据',page:'apk',status:'game-import/status'},
  'library':{title:'准备原版美术资源',page:'library',status:'library/status'}
  ,'card-motion':{title:'导入动态卡面视频',page:'card',status:'card-motion/status'}
};
const RUNNING=new Set(['working','preparing']);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic=p=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const fmt=ms=>{const s=Math.max(0,Math.round(ms/1000));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
const size=b=>b>=1024**3?(b/1024**3).toFixed(2)+' GB':b>=1024**2?(b/1024**2).toFixed(1)+' MB':Math.round(b/1024)+' KB';

export class TaskCenter{
  constructor({api,navigate,toast,page}){
    Object.assign(this,{api,navigate,toast,page});this.tasks=new Map();this.expanded=false;
    this.el=document.createElement('aside');this.el.className='task-dock';this.el.setAttribute('aria-live','polite');this.el.hidden=true;document.body.append(this.el);
    this.el.addEventListener('click',e=>{
      if(e.target.closest('[data-task-toggle]')){this.expanded=!this.expanded;this.render(true);return;}
      const go=e.target.closest('[data-task-open]');if(go){this.navigate(KINDS[go.dataset.taskOpen].page);this.expanded=false;this.render(true);return;}
      const rm=e.target.closest('[data-task-remove]');if(rm){this.tasks.delete(rm.dataset.taskRemove);this.render(true);}
      const cancel=e.target.closest('[data-task-cancel]');if(cancel){const t=this.tasks.get(cancel.dataset.taskCancel);if(t?.jobId){cancel.disabled=true;this.api('card-motion/cancel',{job_id:t.jobId}).then(data=>this.observe('card-motion/status',data)).catch(error=>this.toast(error.message,true));}}
    });
    setInterval(()=>this.tick(),1000);
  }
  observe(path,data){
    const m=/^(native-apk|game-import|library|card-motion)\/(start|status|setup|import|cancel)$/.exec(path);if(!m||!data||typeof data!=='object'||!('phase' in data))return;
    const kind=m[1],running=RUNNING.has(data.phase);let t=this.tasks.get(kind);
    if(running){
      if(!t||t.state!=='running'){t={kind,state:'running',start:Date.now(),steps:[]};this.tasks.set(kind,t);if(m[2]!=='status')this.expanded=true;}
      if(data.message&&t.steps.at(-1)!==data.message)t.steps.push(data.message);
      if(data.files!=null)t.files=data.files;if(data.bytes!=null)t.bytes=data.bytes;
      if(kind==='card-motion'){t.jobId=data.job_id;t.frames=data.frames;t.frameTotal=data.frame_total;t.encoder=data.encoder;t.hardware=data.hardware_accelerated;t.cacheHits=data.cache_hits;t.stage=data.stage;t.role=data.role;}
      this.schedule(kind);
    }else if(t?.state==='running'){
      if(!['done','ready','error','failed','cancelled'].includes(data.phase)){this.schedule(kind);return;}
      t.state=['error','failed'].includes(data.phase)?'error':'done';t.end=Date.now();t.final=data.message||(t.state==='done'?'已完成':'未完成');
      if(data.phase==='cancelled')t.final='已取消；原卡面保持';
      if(this.page?.()!==KINDS[kind].page)this.toast(`${KINDS[kind].title}${t.state==='done'?'已完成':'未完成：'+t.final}`,t.state==='error');
    }else return;
    this.render();
  }
  schedule(kind){const t=this.tasks.get(kind);if(!t||t.timer)return;t.timer=setTimeout(()=>{t.timer=null;if(t.state==='running')this.api(KINDS[kind].status,kind==='card-motion'?{job_id:t.jobId}:{}).catch(()=>this.schedule(kind));},1500);}
  tick(){for(const t of this.tasks.values())if(t.state==='running'){const n=this.el.querySelector(`[data-elapsed="${t.kind}"]`);if(n)n.textContent=fmt(Date.now()-t.start);}
    const pill=this.el.querySelector('[data-pill-time]');const r=[...this.tasks.values()].find(t=>t.state==='running');if(pill&&r)pill.textContent=fmt(Date.now()-r.start);}
  render(user=false){
    const list=[...this.tasks.values()],running=list.filter(t=>t.state==='running');
    this.el.hidden=!list.length;document.body.classList.toggle('has-tasks',!!list.length);document.body.classList.toggle('tasks-open',!!list.length&&this.expanded);
    if(!list.length)return;
    const first=running[0]||list.at(-1);
    const pill=`<button class="task-pill ${running.length?'running':first.state}" data-task-toggle aria-expanded="${this.expanded}">${running.length?'<span class="task-ring"></span>':`<span class="task-state">${ic(first.state==='done'?'<path d="m5 12.5 4.2 4.2L19 7"/>':'<path d="M12 7.5v5.5m0 3.5h.01"/>')}</span>`}<span>${running.length?`${running.length} 项任务进行中`:first.state==='done'?'任务已完成':'任务未完成'}</span>${running.length?`<b data-pill-time>${fmt(Date.now()-first.start)}</b>`:''}<i class="task-chevron">${ic('<path d="m6 15 6-6 6 6"/>')}</i></button>`;
    const cards=list.map(t=>{const k=KINDS[t.kind],steps=t.steps.slice(-5),extra=[t.files!=null?t.files+' 个文件':'',t.bytes?size(t.bytes):''].filter(Boolean).join(' · ');
      return `<article class="task-card ${t.state}"><header><strong>${k.title}</strong><span class="task-badge">${t.state==='running'?'进行中':t.state==='done'?'已完成':'未完成'}</span><time data-elapsed="${t.kind}">${fmt((t.end||Date.now())-t.start)}</time></header>
      <div class="task-bar"><i></i></div>
      <ol class="task-steps">${steps.map((s,i)=>{const cur=i===steps.length-1&&t.state==='running';return `<li class="${cur?'current':'done'}"><span>${cur?'<i class="task-spin"></i>':ic('<path d="m5 12.5 4.2 4.2L19 7"/>')}</span>${esc(s)}</li>`;}).join('')}${t.state!=='running'?`<li class="final ${t.state}"><span>${ic(t.state==='done'?'<path d="m5 12.5 4.2 4.2L19 7"/>':'<path d="M12 7.5v5.5m0 3.5h.01"/>')}</span>${esc(t.final)}</li>`:''}</ol>
      ${extra?`<p class="task-extra">${extra}</p>`:''}${t.kind==='card-motion'?`<p class="task-extra">${t.frameTotal?`${t.role==='large'?'大卡':t.role==='mini'?'小卡':'共享取帧'} ${t.frames||0} / ${t.frameTotal} 帧`:'核对视频'}${t.encoder?` · ${esc(t.encoder)} · ${t.hardware?'硬件编码':'软件编码'}`:''}${t.cacheHits?.length?` · 已复用${t.cacheHits.map(x=>x==='large'?'大卡':'小卡').join('、')}`:''}</p>`:''}<footer><button class="button subtle" data-task-open="${t.kind}">查看详情</button>${t.kind==='card-motion'&&t.state==='running'?`<button class="button subtle" data-task-cancel="${t.kind}">取消导入</button>`:''}${t.state!=='running'?`<button class="button subtle" data-task-remove="${t.kind}">移除</button>`:''}</footer></article>`;}).join('');
    this.el.innerHTML=`<div class="task-panel" ${this.expanded?'':'hidden'}><div class="task-panel-head"><span>任务</span><small>耗时操作在后台继续，离开页面不会中断</small></div>${cards}</div>${pill}`;
    if(user&&this.expanded)this.el.querySelector('.task-panel')?.animate?.([{opacity:0,transform:'translateY(10px) scale(.98)'},{opacity:1,transform:'none'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)'});
  }
}
