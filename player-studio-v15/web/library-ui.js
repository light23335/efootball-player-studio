import {cardTypes,cardTypeName} from './domain.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=s=>document.querySelector(s);
export class LibraryUI {
  constructor(context){
    Object.assign(this,context);this.mode='players';this.query='';this.page=0;this.kind='';this.position='';this.rows=[];this.active=false;this.request=0;
    document.addEventListener('click',e=>this.click(e));
    document.addEventListener('input',e=>{
      if(e.target.id==='library-query'){this.query=e.target.value;this.page=0;clearTimeout(this.timer);this.timer=setTimeout(()=>this.refresh(),320);}
      if(e.target.id==='library-kind'){this.kind=e.target.value;this.page=0;this.refresh();}
      if(e.target.id==='library-position'){this.position=e.target.value;this.page=0;this.refresh();}
      if(e.target.dataset.librarySource)this[e.target.dataset.librarySource]=e.target.value;
    });
  }
  render(){
    const labels=[['players','全部球员'],['portrait','原版球员图'],['thumbnail','游戏内小头像'],['card','原版卡面图层'],['model','原版模型'],['setup','资源设置']];
    return `<div class="native-library"><div class="library-summary"><strong>${this.status.players.toLocaleString()}<small>条球员记录</small></strong><strong>${this.status.assets.toLocaleString()}<small>项原版美术资源</small></strong><span class="inline-badge ${this.status.phase==='ready'?'':'warning'}" id="library-ready">${this.status.phase==='ready'?'原版资源已就绪':'需要准备美术资源'}</span></div><div class="filter-tabs library-tabs">${labels.map(([id,label])=>`<button data-lib-mode="${id}" class="${this.mode===id?'active':''}">${label}</button>`).join('')}</div>${this.mode==='setup'?this.setupHtml():`<div class="search-box">⌕<input id="library-query" value="${esc(this.query)}" placeholder="${['players','thumbnail'].includes(this.mode)?'搜索姓名、英文名、球员 ID':'搜索原始文件名或球员编号'}">${this.mode==='players'?`<select id="library-position"><option value="">全部位置</option>${this.catalog.POSITIONS.map(p=>`<option ${p===this.position?'selected':''}>${p}</option>`).join('')}</select><select id="library-kind"><option value="">全部卡种</option>${cardTypes.map(([k,label])=>`<option value="${k}" ${this.kind===k?'selected':''}>${cardTypeName(k)} · ${label}</option>`).join('')}</select>`:''}</div><div class="library-result-bar"><span id="library-total">正在读取本地数据库…</span><button class="button subtle" data-lib-load>读取本页原图</button></div><div id="library-results"></div><div id="library-pagination" class="library-pagination"></div>`}<p class="note">资料与美术来自你提供的 APK。选择“载入资料”会建立可编辑草稿；不会改写原始 APK 或现有球员。原版图像和模型没有自绘替代。</p></div>`;
  }
  setupHtml(){return `<section class="panel"><div class="panel-title"><h2>读取你已有的两个 APK</h2></div><div class="panel-body"><p class="panel-description">第一次使用会在程序旁建立原版美术缓存，约占 4 GB。转换后的图片与模型按需缓存；准备完成后不需要联网。</p>${[['apk','主程序 APK'],['companion','离线资源包 APK']].map(([key,label])=>`<label class="field"><span>${label}</span><div class="input-row"><input class="input" data-library-source="${key}" id="library-source-${key}" value="${esc(this[key])}"><button class="button secondary" data-lib-pick="${key}">选择</button></div></label>`).join('<div style="height:15px"></div>')}<button style="margin-top:18px" class="button primary" data-lib-setup>准备原版资源</button><p class="native-status" id="native-setup-status">${esc(this.status.message||'所有源文件保持只读。')}</p></div></section>`;}
  activate(page){this.active=page==='library';if(this.active&&this.mode!=='setup')this.refresh();if(this.active&&this.mode==='setup')this.poll();}
  async refresh(){
    if(!this.active||this.mode==='setup')return;
    const request=++this.request;$('#library-results').innerHTML='<div class="loading-state"><span class="spinner"></span>读取数据库…</div>';
    try{
      const data=await this.api(this.mode==='players'?'library/search':'library/assets',{query:this.query,page:this.page,position:this.position,kind:this.mode==='players'?this.kind:this.mode});
      if(!this.active||request!==this.request)return;
      this.rows=data.rows;this.result=data;this.renderRows();this.loadImages();
    }catch(e){this.toast(e.message,true);}
  }
  renderRows(){
    if(!$('#library-results'))return;
    const data=this.result;$('#library-total').textContent=`共 ${data.total.toLocaleString()} 项 · 第 ${data.page+1} / ${data.pages} 页`;
    if(this.mode==='players')$('#library-results').innerHTML=`<div class="library-player-grid">${data.rows.map(r=>`<article class="library-player"><div class="native-avatar" data-native-avatar="${r.portrait||''}"><span>原版球员图</span></div><div class="library-player-info"><strong>${esc(r.name)}</strong><small>${esc(r.name_en)}</small><div class="native-tags"><span>${r.position}</span><span>${esc(cardTypeName(r.card_type))}</span>${r.overall?`<span>原库总评 ${r.overall}</span>`:''}</div><code>${esc(r.id)}</code><button class="button secondary" data-lib-player="${r.id}">载入资料并编辑</button></div></article>`).join('')}</div>`;
    else $('#library-results').innerHTML=`<div class="native-asset-grid">${data.rows.map(r=>`<article class="native-asset">${r.kind==='model'?'<div class="native-model-mark">原版 3D 网格<br><small>点击后读取模型与原材质</small></div>':`<div class="native-asset-image" data-native-avatar="${r.id}">${r.converted?`<img src="${r.converted.url}" alt="${esc(r.name)}">`:'<span>等待读取原图</span>'}</div>`}<strong>${esc(r.player_name||r.name)}</strong><small title="${esc(r.path)}">${esc(r.path)}</small><div class="native-asset-actions">${r.kind==='model'?`<button class="button primary" data-lib-apply="${r.id}" data-lib-slot="model">预览原版模型</button>`:`<button class="button secondary" data-lib-apply="${r.id}" data-lib-slot="${this.mode==='thumbnail'?'thumbnail':r.kind==='portrait'?'portrait':'background'}">${this.mode==='thumbnail'?'设为游戏内小头像':r.kind==='portrait'?'设为球员图':'设为卡面背景'}</button>${r.kind==='card'?`<button class="button subtle" data-lib-apply="${r.id}" data-lib-slot="foreground">设为前景图层</button><button class="button subtle" data-lib-apply="${r.id}" data-lib-slot="full">完整原图</button>`:''}`}</div></article>`).join('')}</div>`;
    if(!data.rows.length)$('#library-results').innerHTML='<div class="no-matches">没有匹配的原版条目，换一个姓名、编号或文件名试试。</div>';
    $('#library-pagination').innerHTML=`<button class="button secondary" data-lib-page="${data.page-1}" ${data.page===0?'disabled':''}>上一页</button><span>${data.page+1} / ${data.pages}</span><button class="button secondary" data-lib-page="${data.page+1}" ${data.page+1>=data.pages?'disabled':''}>下一页</button>`;
  }
  async convert(ids){
    const data=await this.api('library/convert',{ids});return data.results;
  }
  async loadImages(){
    if(!this.active||this.mode==='setup'||this.mode==='model'||this.status.phase!=='ready')return;
    const request=this.request,ids=this.rows.map(r=>this.mode==='players'?r.portrait:r.id).filter(Boolean);if(!ids.length)return;
    try{
      const result=await this.convert([...new Set(ids)]);
      if(request!==this.request||!this.active)return;
      for(const [id,asset] of Object.entries(result)){
        for(const box of document.querySelectorAll(`[data-native-avatar="${id}"]`))box.innerHTML=asset.error?`<span>${esc(asset.error)}</span>`:`<img src="${asset.url}" alt="游戏原图">`;
      }
    }catch(e){this.toast(e.message,true);}
  }
  async loadPlayer(id){
    if(this.beforeLoadPlayer&&!await this.beforeLoadPlayer(id))return;
    const slot=this.project().package_id,request=this.loadRequest=(this.loadRequest||0)+1;
    const row=await this.api('library/player',{id}),payload=row.payload,params=payload.parameters;
    let image=null,thumbnail=null,model=null,background=null,card=null;
    const layer=row.card_layers?.find(a=>a.name.includes('_m01_'+row.id+'_')&&!a.name.endsWith('_max'));
    if(this.status.phase==='ready'){
      this.toast('正在自动读取原版球员图、卡面图层与脸模…');
      const ids=[row.portrait,row.thumbnail,row.auto_model,layer?.id].filter(Boolean);
      if(ids.length){try{const items=await this.convert(ids);image=items[row.portrait];thumbnail=items[row.thumbnail];model=items[row.auto_model];background=items[layer?.id];}catch(e){this.toast('资料会正常载入；原版资源读取失败：'+e.message,true);}}
      if(image?.error)image=null;if(thumbnail?.error)thumbnail=null;if(model?.error){this.toast('原版脸模未转换：'+model.error,true);model=null;}if(background?.error)background=null;
      try{card=await this.api('library/card',{id});}catch(e){this.toast('原版竖版卡面暂未载入：'+e.message,true);}
    }
    if(this.project().package_id!==slot||this.loadRequest!==request)return;
    this.commit(()=>{
      const p=this.project();p.source_player={id:row.id,name:row.name,name_en:row.name_en,base_id:row.base_id,source:row.source,original_payload:payload};
      p.ai_playing_styles=[...(payload.ai_playing_styles||[])];
      p.identity.number=Number.isInteger(payload.uniform_number)&&payload.uniform_number>=1?payload.uniform_number:1;
      p.identity.number_source=payload._studio_number_source||'原包未提供号码';
      p.identity.original_player_id=String(row.id);p.identity.bind_original_player=false;
      p.identity.name=row.name;p.identity.shirt_name=payload._studio_names?.[3]||payload._studio_names?.[1]||row.name;p.celebration=params[59]??null;p.display_name=row.name;p.identity.position=row.position;p.identity.height_cm=params[47];p.identity.weight_kg=params[48];p.identity.age=params[46]||22;
      p.identity.team_id=row.identity_names?.team?.id||0;p.identity.nation_id=row.identity_names?.nation?.id||0;
      p.identity.team=row.identity_names?.team?.name||'未收录球队名称';p.identity.nationality=row.identity_names?.nation?.name||'未收录国家名称';p.identity.preferred_foot=params[43]===1?'左脚':'右脚';
      p.traits={weak_foot_usage:['低','普通','高','极高'][params[45]]||'普通',weak_foot_accuracy:['低','普通','高','极高'][params[33]]||'普通',form:['不稳定','普通','稳定'][params[41]]||'普通',injury:['低','普通','高'][params[42]]||'普通'};
      p.card_type=row.card_type;p.card_series=payload._studio_card_label?.startsWith('Show Time')?'ShowTime':p.card_type;
      p.max_level=Math.max(1,Math.min(100,row.level_limit||35));p.max_level_known=Boolean(row.level_limit);p.initial_level=1;
      p.base_abilities=Object.fromEntries(Object.keys(this.catalog.ABILITIES).map(i=>[i,params[i]]));
      const visibleSkills=values=>[...new Set(values.map(i=>[51,68].includes(i)?52:i))].filter(i=>!this.catalog.SKILL_LABELS[i]?.includes('预留'));
      p.innate_skills=visibleSkills(payload._studio_skill_ids||Object.entries(this.catalog.PARAMETER_BY_SKILL).filter(([i,index])=>params[index]===1).map(([i])=>Number(i)));
      p.additional_skills=visibleSkills(payload.additional_skill_id||[]).filter(i=>!p.innate_skills.includes(i));p.position_aptitudes=Object.fromEntries(this.catalog.APTITUDES.map((pos,i)=>[pos,params[i+1]||0]));
      p.play_style={attack:payload.play_style?.[0]||0,defense:payload.play_style?.[1]||0};p.training=Object.fromEntries(this.catalog.training_groups.map(g=>[g.id,0]));
      const boosterIds=new Set(this.catalog.boosters.map(b=>b.id));p.booster_ids=(payload.initial_booster_id_list||[]).slice(0,2).map(id=>boosterIds.has(id)?id:0);while(p.booster_ids.length<2)p.booster_ids.push(0);
      p.appearance.portrait=image?.asset_id||null;p.appearance.background_image=background?.asset_id||null;p.appearance.photo_zoom=1;p.appearance.photo_x=0;p.appearance.photo_y=0;p.native_art={portrait:image,background,foreground:null,full:null};p.model.asset=model?.asset_id||null;p.model.native_source=model;p.model.morphs={};
      p.model.variants=row.face_variants||[];p.model.resolution=row.model_resolution;
      if(row.appearance_profile?.physique){p.model.physique=row.appearance_profile.physique;p.model.skin_tone=row.appearance_profile.skin_tone||1;p.model.appearance_source_id=row.appearance_profile.source_id;p.model.torso_length=14-p.model.physique.leg_length;}else{delete p.model.physique;delete p.model.skin_tone;delete p.model.appearance_source_id;}
      Object.assign(p.appearance,{thumbnail_image:thumbnail?.asset_id||null,thumbnail_mode:thumbnail?'image':'card',thumbnail_zoom:1,thumbnail_x:0,thumbnail_y:0});p.native_art.thumbnail=thumbnail;
      p.native_card=card;p.native_card_disabled=false;
      p.appearance.portrait_fit='native';p.appearance.hide_portrait=false;delete p.appearance.card_date;delete p.appearance.card_rarity;delete p.appearance.card_date_visible;
      if(card&&p.appearance.native_overlay_text===undefined)p.appearance.native_overlay_text=true;
    },'load-native-player');
    this.navigate('profile');this.toast(`已载入 ${row.name}${model?'，原版脸模已自动加载':''}${row.level_limit?' · 上限 '+row.level_limit+' 级':'；原表未提供等级上限，35 仅为可编辑的模拟值'}`);
    if(model&&row.model_resolution?.message)this.toast(row.model_resolution.message);
    if(!row.auto_model&&row.model_resolution?.message)this.toast(row.model_resolution.message,true);
  }
  async refreshLoaded(){
    const original=this.project(),id=original.source_player?.id,uuid=original.package_id;
    if(!id)return;
    try{
      const row=await this.api('library/player',{id}),layer=row.card_layers?.find(a=>a.name.includes('_m01_'+id+'_')&&!a.name.endsWith('_max'));
      const preset=Boolean(original.native_card?.preset_id);
      const ids=[!preset&&!original.appearance.portrait&&row.portrait,!original.model.asset&&row.auto_model,!preset&&!original.appearance.background_image&&layer?.id].filter(Boolean);
      let items={};if(this.status.phase==='ready'&&ids.length){try{items=await this.convert(ids);}catch(e){this.toast('原版资源暂未载入：'+e.message,true);}}
      let card=null;
      if(!preset&&this.status.phase==='ready'&&original.native_card?.composition_revision!==3&&!original.native_card_disabled&&!original.native_art?.full&&original.native_art?.portrait?.asset_id===original.appearance.portrait){try{card=await this.api('library/card',{id:original.native_card?.source_id||id});}catch(e){this.toast('原版竖版卡面：'+e.message,true);}}
      if(this.project().package_id!==uuid||this.project().source_player?.id!==id)return;
      this.commit(()=>{
        const p=this.project(),n=row.identity_names?.nation,t=row.identity_names?.team;p.native_art??={};
        if(card&&p.native_card?.composition_revision!==3&&!p.native_card_disabled){p.native_card=card;if(p.appearance.native_overlay_text===undefined)p.appearance.native_overlay_text=true;}
        if(n?.name&&/^国家编号\s*\d+$/.test(p.identity.nationality)){p.identity.nationality=n.name;p.identity.nation_id=n.id;}
        if(t?.name&&/^\d+$/.test(p.identity.team)){p.identity.team=t.name;p.identity.team_id=t.id;}
        if(p.max_level===1&&p.max_level_known===undefined&&p.source_player.original_payload?._studio_unknown_level_limit&&row.level_limit){p.max_level=row.level_limit;p.max_level_known=true;p.source_player.original_payload=row.payload;}
        if(p.card_type==='Epic'&&p.card_series==='BigTime')p.card_type='BigTime';
        for(const [asset,slot,field] of [[items[row.portrait],'portrait','portrait'],[items[layer?.id],'background','background_image']]){
          if(asset&&!asset.error&&!p.appearance[field]){p.appearance[field]=asset.asset_id;p.native_art[slot]=asset;}
        }
        p.model.variants=row.face_variants||[];p.model.resolution=row.model_resolution;
        const model=items[row.auto_model];if(model&&!model.error&&!p.model.asset){p.model.asset=model.asset_id;p.model.native_source=model;}
      },'repair-native-links');
      this.rerender();
    }catch(e){this.toast('自动读取原版资源：'+e.message,true);}
  }
  async applyAsset(id,slot){
    const result=(await this.convert([id]))[id];if(result.error)throw Error(result.error);
    this.commit(()=>{
      const p=this.project();p.native_art??={};
      if(slot==='thumbnail'){Object.assign(p.appearance,{thumbnail_image:result.asset_id,thumbnail_mode:'image',thumbnail_zoom:1,thumbnail_x:0,thumbnail_y:0});p.native_art.thumbnail=result;}
      else if(slot==='model'){p.model.asset=result.asset_id;p.model.native_source=result;p.model.scale=1;p.model.rotation=0;p.model.morphs={};}
      else{p.native_art[slot]=result;if(slot!=='full')p.native_art.full=null;if(slot==='portrait')p.appearance.portrait=result.asset_id;if(slot==='background')p.appearance.background_image=result.asset_id;}
      if(slot==='portrait'){p.appearance.portrait_fit='native';p.appearance.hide_portrait=false;}
      else if(slot!=='model'&&slot!=='thumbnail'){p.native_card=null;p.native_card_disabled=true;}
    },'native-art-'+slot);
    if(slot==='model'){this.navigate('model');this.toast(`已载入游戏原版网格；${result.textured_materials}/${result.materials} 项材质使用已解析的原始贴图`);}
    else{this.navigate('card');this.toast(slot==='thumbnail'?'已选择游戏内小头像，可继续裁切并随球员实装':'已使用游戏原版图像，来源已随工程保存');}
  }
  scheduleCardInfo(){
    clearTimeout(this.infoTimer);const p=this.project(),card=p.native_card;if(!card?.ui||this.status.phase!=='ready')return;
    const team=p.identity.team_id??card.info?.team_id??0,nation=p.identity.nation_id??card.info?.nation_id??0;
    if(card.info?.symbol_revision===2&&card.info?.team_id===team&&card.info?.nation_id===nation)return;
    const uuid=p.package_id,id=card.source_id;
    this.infoTimer=setTimeout(async()=>{try{
      const info=await this.api('library/card-info',{id,team_id:team,nation_id:nation}),current=this.project();
      if(current.package_id!==uuid||current.native_card?.source_id!==id||current.identity.team_id!==team||current.identity.nation_id!==nation)return;
      this.commit(()=>{current.native_card.info=info;},'native-symbols');
    }catch(e){this.toast('队徽读取：'+e.message,true);}},450);
  }
  async loadCard(id=this.project().source_player?.id){
    if(!id)throw Error('请先从原版资源库选择球员卡面');
    const uuid=this.project().package_id,card=await this.api('library/card',{id});
    if(this.project().package_id!==uuid)return;
    this.commit(()=>{const p=this.project();p.native_card=card;p.native_card_disabled=false;
      const portrait=card.layers.find(l=>l.slot==='portrait');if(portrait&&!p.appearance.portrait){p.appearance.portrait=portrait.asset_id;p.native_art??={};p.native_art.portrait=portrait;p.native_art.full=null;}
      if(p.appearance.native_overlay_text===undefined)p.appearance.native_overlay_text=true;
    },'native-complete-card');this.navigate('card');this.toast('已读取原版竖版图层、动画和字体，能力与培养方案保留');
  }
  async poll(){
    try{this.status=await this.api('library/status',{});const status=$('#native-setup-status');if(status)status.textContent=(this.status.message||'原版资源已就绪')+(this.status.bytes?' · '+(this.status.bytes/1024**3).toFixed(2)+' GB':'');
      if(this.status.phase==='preparing')setTimeout(()=>this.poll(),1000);
      else if(this.status.phase==='ready'){const badge=$('#library-ready');if(badge){badge.textContent='原版资源已就绪';badge.classList.remove('warning');}}
    }catch(e){this.toast(e.message,true);}
  }
  async click(event){
    const button=event.target.closest('[data-lib-mode],[data-lib-player],[data-lib-apply],[data-lib-page],[data-lib-load],[data-lib-pick],[data-lib-setup]');if(!button||button.disabled)return;
    try{
      if(button.dataset.libMode){this.mode=button.dataset.libMode;this.page=0;this.query='';this.rerender();return;}
      if(button.dataset.libPage!==undefined){this.page=Number(button.dataset.libPage);this.refresh();return;}
      if(button.hasAttribute('data-lib-load'))return this.loadImages();
      if(button.dataset.libPick){const r=await this.api('dialog',{category:'apk'});if(r.path){this[button.dataset.libPick]=r.path;$('#library-source-'+button.dataset.libPick).value=r.path;}return;}
      button.classList.add('busy');
      if(button.dataset.libPlayer)await this.loadPlayer(button.dataset.libPlayer);
      else if(button.dataset.libApply)await this.applyAsset(button.dataset.libApply,button.dataset.libSlot);
      else if(button.hasAttribute('data-lib-setup')){this.status=await this.api('library/setup',{apk:this.apk,companion:this.companion});this.poll();}
    }catch(e){this.toast(e.message,true);}finally{button.classList.remove('busy');}
  }
  open(kind,query=''){this.mode=kind;this.query=query;this.page=0;this.navigate('library');}
}
