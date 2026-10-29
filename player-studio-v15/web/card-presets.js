import {NativeCardRenderer} from './native-card.js';
import {applyCardPreset} from './card-design.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LABELS={BigTime:'BT · Big Time',Epic:'Epic · 史诗',Legendary:'传奇',Trending:'POTW / 趋势',Featured:'精选',Highlight:'高光 / Show Time',Standard:'标准'};
export class CardPresetsUI{
  constructor(context){Object.assign(this,context);this.kind='BigTime';this.query='';this.page=0;this.sequence=0;this.renderers=[];this.motionEnabled=true;this.previews=new Map();
    document.addEventListener('click',e=>this.click(e));
    document.addEventListener('input',e=>{if(e.target.id==='preset-query'){this.query=e.target.value;this.page=0;clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),250);}});
  }
  close(){this.sequence++;clearInterval(this.playbackTimer);this.playbackTimer=null;this.observer?.disconnect();this.observer=null;this.previews.clear();this.renderers.forEach(r=>r.clear());this.renderers=[];}
  previewStatus(item){
    const media=item.renderer.resources.filter(l=>l.kind==='video'),loaded=media.filter(l=>l.element);
    const kind=item.hasBackground?'背景动画':'动态光效（背景静态）';
    let state='static-layers',text='静态图层';
    if(item.animated){
      const advancing=loaded.some(l=>{const video=l.element,previous=item.lastTimes?.get(l.asset_id);return !video.paused&&video.readyState>=2&&previous!==undefined&&Math.abs(video.currentTime-previous)>.001;});
      state=!this.motionEnabled||!item.visible?'paused':!loaded.length?'unavailable':advancing?'playing':'waiting';
      text=kind+' · '+({paused:'已暂停',unavailable:'动画读取失败',playing:'播放中',waiting:'等待播放'})[state];
      item.lastTimes=new Map(loaded.map(l=>[l.asset_id,l.element.currentTime]));
    }
    item.canvas.dataset.motion=state;
    const tag=item.canvas.parentElement?.querySelector('.preset-tag');if(tag)tag.textContent=text+(item.limited?' · 限定':'');
  }
  previewMotion(item,visible){
    item.visible=visible;
    const playing=this.motionEnabled&&visible&&item.animated;
    item.renderer.setMotion(playing);
    this.previewStatus(item);
  }
  render(){return `<div class="preset-browser"><p class="panel-description">选择空白底板，直接套用到你的人物图。保留原版背景、卡框和动画；不带原球员、人名签名和固定日期。标注“动态光效（背景静态）”的预设只有光效视频，背景图本身不会移动。</p><div class="preset-filters">${[['','全部'],...Object.entries(LABELS)].map(([key,label])=>`<button class="${this.kind===key?'active':''}" data-preset-kind="${key}">${label}<small data-preset-count="${key}"></small></button>`).join('')}</div><div class="search-box"><span>⌕</span><input id="preset-query" value="${esc(this.query)}" placeholder="搜索系列、球队、设计编号或参考球员"><button class="text-link" data-preset-refresh>刷新</button></div><div class="library-result-bar" id="preset-result">读取原版预设…</div><div id="preset-grid" class="preset-grid"></div><div id="preset-pagination" class="library-pagination"></div></div>`;}
  async refresh(){
    const grid=document.querySelector('#preset-grid');if(!grid)return;this.close();const sequence=++this.sequence;
    grid.innerHTML='<div class="empty-state">正在读取空白预设…</div>';
    try{
      const data=await this.api('library/presets',{kind:this.kind,query:this.query,page:this.page});if(sequence!==this.sequence)return;
      this.page=data.page;this.result=data;
      document.querySelectorAll('[data-preset-count]').forEach(el=>el.textContent=' '+(el.dataset.presetCount?data.counts[el.dataset.presetCount]||0:data.all_count));
      const result=document.querySelector('#preset-result');result.textContent=`${data.total} 款系列 · ${data.usable_total} 款可套用 · 预览不含人物`;
      const motion=document.createElement('button');motion.className='text-link';motion.dataset.presetMotion='';motion.textContent=this.motionEnabled?'暂停预设动画':'播放预设动画';result.append(motion);
      document.querySelectorAll('[data-preset-kind]').forEach(el=>el.classList.toggle('active',el.dataset.presetKind===this.kind));
      grid.innerHTML=data.rows.map(r=>`<article class="preset-tile ${this.project().native_card?.preset_id===r.id?'selected':''}" data-preset-tile="${r.id}"><div class="preset-art"><canvas data-preset-canvas="${r.id}" width="268" height="384" aria-label="${esc(r.title)}空白卡面预览"></canvas><span class="preset-loading" data-preset-loading="${r.id}">读取原版图层…</span><span class="preset-tag">${r.animated?'原版动画':'原版静态'}${r.limited?' · 限定':''}</span></div><div class="preset-body"><strong>${esc(r.title)}</strong><small>${esc(r.design_code)}</small><p title="${esc(r.examples.join(' / '))}">${esc(r.examples.slice(0,2).join(' / ')||'原包公共设计')}</p><button class="button ${this.project().native_card?.preset_id===r.id?'primary':'secondary'}" data-preset-apply="${r.id}">${this.project().native_card?.preset_id===r.id?'已使用 · 再次套用':'使用此预设'}</button></div></article>`).join('')||'<div class="empty-state">没有匹配的原版设计</div>';
      document.querySelector('#preset-pagination').innerHTML=`<button class="button subtle" data-preset-page="${data.page-1}" ${data.page===0?'disabled':''}>上一页</button><span>${data.page+1} / ${data.pages}</span><button class="button subtle" data-preset-page="${data.page+1}" ${data.page+1>=data.pages?'disabled':''}>下一页</button>`;
      if(!data.rows.length)return;
      const response=await this.api('library/preset-previews',{ids:data.rows.map(r=>r.id)});if(sequence!==this.sequence)return;
      await Promise.all(data.rows.map(async row=>{
        const canvas=document.querySelector(`[data-preset-canvas="${row.id}"]`);if(!canvas)return;
        const card=response.results[row.id],renderer=new NativeCardRenderer(canvas,()=>{});renderer.motion=false;this.renderers.push(renderer);
        await renderer.update({native_card:card,appearance:{native_overlay_text:false}},{});
        if(sequence!==this.sequence){renderer.clear();return;}
        const item={renderer,canvas,animated:row.animated,hasBackground:card.layers.some(l=>l.kind==='video'&&l.slot==='f02'),limited:row.limited,visible:false};this.previews.set(canvas,item);
        this.playbackTimer??=setInterval(()=>{for(const item of this.previews.values())this.previewStatus(item);},400);
        this.observer??=new IntersectionObserver(entries=>{for(const entry of entries){const item=this.previews.get(entry.target);if(item)this.previewMotion(item,entry.isIntersecting);}},{threshold:.05});
        this.observer.observe(canvas);
        const loading=document.querySelector(`[data-preset-loading="${row.id}"]`);if(loading){loading.textContent=row.available===false?'此系列缺少独立空白图层':card.missing.length?'部分图层未读取':'';loading.hidden=row.available!==false&&!card.missing.length;}
        if(row.available===false){const button=document.querySelector(`[data-preset-apply="${row.id}"]`);if(button){button.disabled=true;button.textContent='缺少原版分层';button.title=row.unavailable_reason;}}
      }));
    }catch(e){if(sequence===this.sequence){grid.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`;this.toast(e.message,true);}}
  }
  async apply(id){
    const p=this.project(),uuid=p.package_id,identity=JSON.stringify(p.identity);
    const card=await this.api('library/preset',{id,team_id:p.identity.team_id||0,nation_id:p.identity.nation_id||0,
      rarity:p.appearance.card_rarity||((p.source_player?.original_payload?.default_rarity??4)+1)});
    if(this.project().package_id!==uuid||JSON.stringify(this.project().identity)!==identity)return;
    this.commit(()=>applyCardPreset(this.project(),card),'card-preset');this.rerender();
    this.toast('已套用空白预设；你的人物、能力、技能与培养方案保留');
  }
  async click(event){
    const el=event.target.closest('[data-preset-kind],[data-preset-page],[data-preset-apply],[data-preset-refresh],[data-preset-motion]');if(!el||el.disabled)return;
    if(el.hasAttribute('data-preset-motion')){this.motionEnabled=!this.motionEnabled;for(const item of this.previews.values())this.previewMotion(item,item.visible);el.textContent=this.motionEnabled?'暂停预设动画':'播放预设动画';return;}
    if(el.hasAttribute('data-preset-kind')){this.kind=el.dataset.presetKind;this.page=0;return this.refresh();}
    if(el.dataset.presetPage!==undefined){this.page=Number(el.dataset.presetPage);return this.refresh();}
    if(el.hasAttribute('data-preset-refresh'))return this.refresh();
    el.disabled=true;try{await this.apply(el.dataset.presetApply);}catch(e){this.toast(e.message,true);}finally{el.disabled=false;}
  }
}
