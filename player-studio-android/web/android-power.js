// Loaded only by the Android overlay. This is an editor preference, not a
// game export option, and is stored by the phone host across port changes.
export async function setupAndroidPower(){
 const root=document.documentElement;let value=true,ready=false,pending=false;
 const apply=enabled=>{value=enabled;root.dataset.reducePower=String(enabled);window.dispatchEvent(new Event('studio-android-power'));sync();};
 const request=async body=>{const r=await fetch('/api/android-ui-options',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':new URLSearchParams(location.search).get('token')||''},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'无法保存界面设置');return d;};
 function sync(){
  const host=document.querySelector('#game-settings-body')?.closest('section.panel');if(!host)return;
  let panel=document.querySelector('#android-power-panel');
  if(!panel){panel=document.createElement('section');panel.id='android-power-panel';panel.className='panel';panel.innerHTML='<div class="panel-title"><h2>安卓版界面</h2></div><div class="panel-body"><label class="switch-label"><input type="checkbox" data-android-reduce-power>减少耗电</label><p class="note">默认开启。开启后关闭渐入渐出、过渡、数字滚动、背景流动、悬浮、闪烁、毛玻璃及触摸倾斜等界面特效；保留静态背景和换卡取色。卡面视频、小头像及模型动态预览仍可正常浏览，不改变游戏设置。</p><p class="note" data-android-power-status aria-live="polite"></p></div>';host.before(panel);
   panel.querySelector('input').onchange=async e=>{e.stopPropagation();if(pending)return;const old=value;pending=true;apply(e.target.checked);try{const d=await request({reduce_power:value});apply(d.reduce_power===true);panel.querySelector('[data-android-power-status]').textContent='已保存，立即生效。';}catch(error){apply(old);panel.querySelector('[data-android-power-status]').textContent=error.message;}finally{pending=false;sync();}};
  }
  const input=panel.querySelector('input');input.checked=value;input.disabled=!ready||pending;
 }
 apply(true);new MutationObserver(sync).observe(document.getElementById('editor-content'),{childList:true,subtree:true});
 try{const d=await request({});apply(d.reduce_power===true);ready=true;}catch(error){ready=true;sync();const status=document.querySelector('[data-android-power-status]');if(status)status.textContent=error.message;}
 sync();
}
