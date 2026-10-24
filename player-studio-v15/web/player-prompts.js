const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function choosePlayerAction(title,message,choices){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.className='player-action-dialog';dialog.innerHTML=`<h2>${esc(title)}</h2><p>${esc(message)}</p><div class="player-action-choices">${choices.map(c=>`<button class="button ${c.danger?'danger':c.primary?'primary':'secondary'}" data-choice="${esc(c.id)}">${esc(c.label)}</button>`).join('')}<button class="button subtle" data-choice="cancel">取消</button></div>`;
  dialog.querySelectorAll('[data-choice]').forEach(button=>button.onclick=()=>dialog.close(button.dataset.choice));dialog.onclose=()=>{const result=dialog.returnValue||'cancel';dialog.remove();resolve(result);};document.body.append(dialog);dialog.showModal();
 });
}
export function playerLoadChoices(emptySlot){return emptySlot?[{id:'current',label:'使用当前新建槽位（推荐）',primary:true},{id:'new',label:'另建一个独立球员槽位'}]:[{id:'new',label:'新建独立球员（推荐）',primary:true},{id:'overwrite',label:'覆盖当前编辑球员',danger:true}];}
