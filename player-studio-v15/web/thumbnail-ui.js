export function renderThumbnailPanel(project,range){
  const mode=project.appearance.thumbnail_mode||'card';
  return `<section class="panel"><div class="panel-title"><h2>游戏内小头像</h2></div><div class="panel-body"><p class="panel-description">背景跟随大卡面预设。优先使用原生小头像背景动画；没有配套动画时，联动所选大卡面的背景视频。人物可独立裁切、上传或选择原版小头像。原预设只有静态背景时保留静态背景，叠加可用光效。</p><div class="thumbnail-editor"><div><canvas id="thumbnail-preview" width="512" height="512" aria-label="带卡面背景的小头像预览"></canvas><p class="note" id="thumbnail-status"></p></div><div><label class="check"><input type="checkbox" data-bind="appearance.thumbnail_animation" ${project.appearance.thumbnail_animation!==false?'checked':''}>小头像动态背景与光效</label><p class="note">每名球员单独保存；关闭后使用静态背景。</p><label class="field"><span>小头像人物来源</span><select data-bind="appearance.thumbnail_mode">${[['card','跟随大卡面人物构图'],['portrait','从大图裁切'],['image','独立图片 / 原版小头像']].map(([v,n])=>`<option value="${v}" ${v===mode?'selected':''}>${n}</option>`).join('')}</select></label><div class="portrait-actions"><button class="button secondary" data-action="browse-thumbnail">浏览游戏内小头像</button><button class="button primary" data-action="upload-thumbnail">上传小头像</button><button class="button secondary" data-action="thumbnail-from-portrait">从大图截取</button></div>${mode!=='card'?`${range('appearance.thumbnail_zoom','裁切缩放',.5,8,.02,'×')}${range('appearance.thumbnail_x','水平位置',-100,100,1)}${range('appearance.thumbnail_y','垂直位置',-100,100,1)}<button class="button secondary" data-action="thumbnail-reset">重置裁切</button>`:''}</div></div></div></section>`;
}
let generation=0,timer,frame,videos=[];
function stop(){cancelAnimationFrame(frame);for(const video of videos){video.pause();video.removeAttribute('src');video.load();}videos=[];}
async function loadImage(src){const image=new Image();image.src=src;await image.decode();return image;}
function loadVideo(layer){return new Promise((resolve,reject)=>{
  const video=document.createElement('video');videos.push(video);video.muted=true;video.loop=true;video.playsInline=true;video.preload='auto';
  const timeout=setTimeout(()=>{video.pause();reject(new Error('小头像动画读取超时'));},20000);
  video.onloadeddata=()=>{clearTimeout(timeout);resolve({...layer,element:video});};
  video.onerror=()=>{clearTimeout(timeout);reject(new Error('小头像动画无法播放'));};video.src=layer.url||('/assets/'+layer.asset_id);video.load();
});}
export function drawThumbnail(project,api){
  const canvas=document.querySelector('#thumbnail-preview');if(!canvas)return;
  const snapshot=structuredClone(project),a=snapshot.appearance,mode=a.thumbnail_mode||'card';
  const fields=Object.fromEntries(Object.entries(a).filter(([k])=>k.startsWith('thumbnail_')||k.startsWith('photo_')||['portrait','portrait_fit','background_image','background'].includes(k)));
  const key=JSON.stringify([fields,snapshot.native_card,snapshot.native_art]);if(canvas.dataset.requestKey===key)return;canvas.dataset.requestKey=key;
  const serial=++generation,ctx=canvas.getContext('2d'),status=document.querySelector('#thumbnail-status');clearTimeout(timer);stop();
  if(!(mode==='image'?a.thumbnail_image:a.portrait)){ctx.clearRect(0,0,512,512);status.textContent=mode==='image'?'请上传小头像图片。':'请先导入人物大图。';return;}
  status.textContent='正在合成与大卡面联动的小头像…';
  timer=setTimeout(async()=>{try{
    const data=await api('thumbnail/preview',{project:snapshot});if(serial!==generation||!canvas.isConnected)return;
    const image=await loadImage(data.image);if(serial!==generation||!canvas.isConnected)return;
    ctx.clearRect(0,0,512,512);ctx.drawImage(image,0,0,512,512);canvas.dataset.backgroundLinked='true';canvas.dataset.animated='false';status.textContent='512 × 512 · '+data.note;
    if(!data.animation?.animated)return;
    const [backdrop,foreground]=await Promise.all([loadImage(data.background),loadImage(data.foreground)]);
    if(serial!==generation||!canvas.isConnected)return;
    const layers=await Promise.all(data.animation.layers.map(loadVideo));
    if(serial!==generation||!canvas.isConnected){for(const l of layers)l.element.pause();return;}
    await Promise.all(layers.map(l=>l.element.play().catch(()=>{})));canvas.dataset.animated='true';let last=0,count=0;
    function tick(time){
      if(serial!==generation)return;
      if(!canvas.isConnected){stop();return;}
      if(!document.hidden&&canvas.offsetParent&&time-last>=32){
        last=time;ctx.globalCompositeOperation='source-over';ctx.clearRect(0,0,512,512);ctx.drawImage(backdrop,0,0,512,512);
        for(const l of layers.filter(l=>l.role==='background'))if(l.element.readyState>=2){ctx.globalCompositeOperation=l.blend;ctx.drawImage(l.element,0,0,512,512);}
        ctx.globalCompositeOperation='source-over';ctx.drawImage(foreground,0,0,512,512);
        for(const l of layers.filter(l=>l.role==='effect'))if(l.element.readyState>=2){ctx.globalCompositeOperation=l.blend;ctx.drawImage(l.element,0,0,512,512);}
        ctx.globalCompositeOperation='source-over';canvas.dataset.frames=String(++count);
      }
      frame=requestAnimationFrame(tick);
    }frame=requestAnimationFrame(tick);
  }catch(error){if(serial===generation&&canvas.isConnected){canvas.dataset.requestKey='';status.textContent='小头像背景未能合成：'+error.message;}}},140);
}
