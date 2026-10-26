export const editorPages=new Set(['profile','abilities','training','skills','card','model','motion']);
export function playerReady(project){
 const authored=project&&(project.native_card||project.model?.asset||project.appearance?.portrait);
 return Boolean(project&&(project.source_player?.id||project.editor_ready||
  (project.identity?.name?.trim()&&(project.status!=='new-player-slot'||authored))));
}

// Keep the scroll container and group controls stable while editing rerenders.
export class WorkspaceNavigation{
 constructor(root){this.root=root;this.open=new Set([0,1]);this.page=null;
  root.addEventListener('click',event=>{const button=event.target.closest('[data-nav-group]');if(!button)return;
   const index=Number(button.dataset.navGroup),top=root.scrollTop;
   if(this.open.has(index))this.open.delete(index);else this.open.add(index);
   this.syncGroups();root.scrollTop=top;
  });
 }
 syncGroups(){for(const button of this.root.querySelectorAll('[data-nav-group]')){
  const expanded=this.open.has(Number(button.dataset.navGroup));
  button.setAttribute('aria-expanded',String(expanded));
  this.root.querySelector('#'+button.getAttribute('aria-controls')).hidden=!expanded;
 }}
 activate(page,ready){
  document.body.dataset.playerReady=String(ready);
  const navPage=page==='library'?'personal':page;
  const top=this.root.scrollTop;
  if(page!==this.page){const group=this.root.querySelector(`[data-page="${navPage}"]`)?.closest('[data-nav-section]');if(group)this.open.add(Number(group.dataset.navSection));this.page=page;}
  this.syncGroups();
  for(const element of document.querySelectorAll('[data-page],#compact-page-select option')){
   const id=element.dataset.page||element.value,locked=editorPages.has(id)&&!ready;
   element.disabled=locked;element.setAttribute('aria-disabled',String(locked));
   if(element.classList.contains('nav-item'))element.classList.toggle('active',id===navPage);
  }
  this.root.scrollTop=top;
 }
}
