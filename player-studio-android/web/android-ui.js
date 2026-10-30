// Android tweaks for the Liquid Glass UI. Navigation, preview drawer and the
// phone dock come from the shared shell.js.
function setupAndroid(){
 document.documentElement.dataset.android='';
 window.__studioLayout?.();
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
