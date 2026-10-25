document.addEventListener('DOMContentLoaded',()=>{
 const navigation=document.getElementById('navigation'),migration=document.getElementById('migration-nav');
 const mobile=document.createElement('label');mobile.className='android-mobile-nav';
 const brand=document.createElement('strong');brand.textContent='球员工坊';mobile.append(brand);
 const select=document.createElement('select');select.id='android-page-select';select.setAttribute('aria-label','切换工作区');mobile.append(select);navigation.before(mobile);
 const syncNavigation=()=>{
  const buttons=[...navigation.querySelectorAll('[data-page]'),migration];
  const selected=buttons.find(button=>button.classList.contains('active'))?.dataset.page;
  const entries=buttons.map(button=>({id:button.dataset.page,title:button.querySelector('span:nth-child(2)')?.textContent||button.title}));
  if(select.dataset.options!==JSON.stringify(entries)){
   select.replaceChildren(...entries.map(entry=>{const option=document.createElement('option');option.value=entry.id;option.textContent=entry.title;return option;}));
   const help=document.createElement('option');help.value='__help';help.textContent='使用说明';select.append(help);select.dataset.options=JSON.stringify(entries);
  }
  if(selected)select.value=selected;
 };
 const buttonsFor=id=>[...navigation.querySelectorAll('[data-page]'),migration].find(button=>button.dataset.page===id);
 select.onchange=()=>{if(select.value==='__help'){document.getElementById('help-button').click();syncNavigation();return;}buttonsFor(select.value)?.click();};
 const navigationObserver=new MutationObserver(syncNavigation);navigationObserver.observe(navigation,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});navigationObserver.observe(migration,{attributes:true,attributeFilter:['class']});syncNavigation();
 const preview=document.querySelector('.preview-area'),header=preview.querySelector('.preview-header');
 const toggle=document.createElement('button');toggle.className='text-link android-preview-toggle';toggle.textContent='展开预览';toggle.setAttribute('aria-expanded','false');
 preview.classList.add('android-preview-collapsed');header.append(toggle);
 toggle.onclick=()=>{const collapsed=preview.classList.toggle('android-preview-collapsed');toggle.textContent=collapsed?'展开预览':'收起预览';toggle.setAttribute('aria-expanded',String(!collapsed));};
 const hints=()=>{
  document.querySelectorAll('.model-hint,.inline-tip').forEach(e=>{if(e.textContent.includes('左键'))e.textContent='单指旋转 · 双指缩放、平移';});
  document.querySelectorAll('.native-library .search-box').forEach(box=>{for(const node of box.childNodes)if(node.nodeType===Node.TEXT_NODE&&node.textContent.trim()==='⌕')node.textContent='';});
 };
 hints();new MutationObserver(hints).observe(document.getElementById('editor-content'),{childList:true,subtree:true});
 const toasts=document.getElementById('toasts');
 new MutationObserver(()=>{const seen=new Set();for(const toast of [...toasts.children].reverse()){const message=toast.textContent.trim();if(seen.has(message))toast.remove();else seen.add(message);}}).observe(toasts,{childList:true});
});
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
