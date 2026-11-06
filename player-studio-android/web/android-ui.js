// Android tweaks for the Liquid Glass UI. Navigation, preview drawer and the
// phone dock come from the shared shell.js.
function setupAndroidProjectImport(){
 const ids=['undo-button','redo-button','open-project','export-project','save-player'];
 const buttons=ids.map(id=>document.getElementById(id)),actions=buttons[0]?.closest('.head-actions'),shell=document.querySelector('.app-shell');
 if(buttons.some(b=>!b)||!actions||!shell||document.getElementById('android-project-bar'))return;
 // Keep the real action container and controls: busy/disabled state, the active
 // page's undo history and save target continue to use their original handlers.
 const bar=document.createElement('div');bar.id='android-project-bar';bar.setAttribute('role','toolbar');bar.setAttribute('aria-label','工程操作');
 const heading=document.createElement('div');heading.className='android-project-heading';
 const title=document.createElement('span');title.className='android-project-title';title.textContent='球员工坊';heading.append(title);
 const status=document.getElementById('save-status');if(status)heading.append(status);
 actions.classList.add('android-project-actions');bar.append(heading,actions);shell.prepend(bar);
 // Keep the history controls recognizable on touch screens, where hover
 // titles are unavailable. Add text inside the existing buttons, not proxies.
 for(const [index,text] of [[0,'撤销'],[1,'重做']]){
  const label=document.createElement('span');label.className='android-action-label';label.textContent=text;
  buttons[index].append(label);buttons[index].setAttribute('aria-label',text);
 }
 const button=buttons[2],label=button.querySelector('.label');
 if(label)label.textContent='导入工程';button.title='导入工程';button.setAttribute('aria-label','导入工程');
}
function setupAndroid(){
 document.documentElement.dataset.android='';
 import('/android-power.js').then(m=>m.setupAndroidPower()).catch(()=>{});
 window.__studioLayout?.();
 setupAndroidProjectImport();
 const hints=()=>{
  document.querySelectorAll('.model-hint,.inline-tip').forEach(e=>{if(e.textContent.includes('左键'))e.textContent='单指旋转 · 双指缩放、平移';});
  document.querySelectorAll('.native-library .search-box').forEach(box=>{for(const node of box.childNodes)if(node.nodeType===Node.TEXT_NODE&&node.textContent.trim()==='⌕')node.textContent='';});
 };
 hints();new MutationObserver(hints).observe(document.getElementById('editor-content'),{childList:true,subtree:true});
 for(const hint of document.querySelectorAll('.preview-area .model-hint'))hint.textContent='单指旋转 · 双指缩放、平移';
 const toasts=document.getElementById('toasts');
 new MutationObserver(()=>{const seen=new Set();for(const toast of [...toasts.children].reverse()){const message=toast.textContent.trim();if(seen.has(message))toast.remove();else seen.add(message);}}).observe(toasts,{childList:true});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setupAndroid);else setupAndroid();
// Android WebView does not download blob URLs. Stage the generated PNG/GLB
// on the authenticated phone-local server, then use the system save picker.
const originalAnchorClick=HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click=function(){
 if(!this.href.startsWith('blob:'))return originalAnchorClick.call(this);
 const source=this.href,filename=this.download||'export.bin';
 (async()=>{
  const blob=await (await fetch(source)).blob();
  const response=await fetch('/api/android-export',{method:'POST',headers:{'X-Studio-Filename':encodeURIComponent(filename)},body:blob});
  const result=await response.json();if(!response.ok)throw Error(result.error||'导出失败');
  const link=document.createElement('a');link.href=result.url;link.download=result.filename;originalAnchorClick.call(link);
 })().catch(error=>{const toast=document.createElement('div');toast.className='toast error';toast.textContent='导出失败：'+error.message;document.getElementById('toasts').append(toast);setTimeout(()=>toast.remove(),10000);});
};
