const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export class BoosterLibraryUI{
 constructor(context){Object.assign(this,context);document.addEventListener('click',event=>{if(event.target.closest('[data-shared-boosters]'))this.open().catch(e=>this.toast(e.message,true));});}
 attach(row,slot){const p=this.project();p.custom_boosters??=[];const existing=p.custom_boosters.find(b=>b.uuid===row.uuid),used=new Set(p.custom_boosters.map(b=>b.id));
  const id=existing?.id||(!used.has(row.id)?row.id:Array.from({length:10000},(_,i)=>1000+i).find(i=>!used.has(i)));
  if(!id)throw Error('当前工程的增能定义已达到 10000 项');
  this.commit(()=>{const booster={...structuredClone(row),id};if(existing)p.custom_boosters=p.custom_boosters.map(b=>b.uuid===row.uuid?booster:b);else p.custom_boosters.push(booster);if(p.booster_ids[1-slot]===id)p.booster_ids[1-slot]=0;p.booster_ids[slot]=id;},'reference-shared-booster');
  this.rerender();this.toast(`已引用“${row.label}”到增能槽 ${slot+1}`);
 }
 async open(){await this.flushSave(true);let query='',offset=0,request=0,rows=[];
  const dialog=document.createElement('dialog');dialog.className='player-action-dialog booster-library-dialog';dialog.innerHTML='<h2>共享增能库</h2><p>最多保存 10,000 项定义。可跨球员引用到任意增能槽。修改后，其他球员可重新引用以更新配置；本次实装才分配兼容的原生编号。</p><input class="input" type="search" aria-label="搜索共享增能" placeholder="搜索增能名称或永久身份"><div class="shared-booster-results"></div><div class="welcome-actions"><button class="button secondary" data-shared-prev>上一页</button><button class="button secondary" data-shared-next>下一页</button><button class="button subtle" data-shared-close>关闭</button></div>';
  const results=dialog.querySelector('.shared-booster-results');
  const refresh=async()=>{const serial=++request,result=await this.api('boosters/list',{query,offset});if(serial!==request||!dialog.open)return;rows=result.rows;results.innerHTML=`<p class="note">共享库 ${result.saved_total} / ${result.capacity} 项 · 匹配 ${result.total} 项</p>${rows.map((r,i)=>`<article class="shared-booster-row"><strong>${esc(r.label)}</strong><small>${esc(r.uuid)}</small><div class="welcome-actions"><button class="button secondary" data-share-index="${i}" data-share-slot="0">用于槽 1</button><button class="button secondary" data-share-index="${i}" data-share-slot="1">用于槽 2</button></div></article>`).join('')||'<p>暂无匹配增能；创建并保存球员后会自动加入共享库。</p>'}`;dialog.querySelector('[data-shared-prev]').disabled=!offset;dialog.querySelector('[data-shared-next]').disabled=offset+50>=result.total;};
  dialog.querySelector('input').oninput=event=>{query=event.target.value;offset=0;refresh().catch(e=>this.toast(e.message,true));};
  dialog.onclick=event=>{const ref=event.target.closest('[data-share-index]');if(ref){this.attach(rows[Number(ref.dataset.shareIndex)],Number(ref.dataset.shareSlot));dialog.close();}if(event.target.closest('[data-shared-close]'))dialog.close();if(event.target.closest('[data-shared-prev]')){offset=Math.max(0,offset-50);refresh().catch(e=>this.toast(e.message,true));}if(event.target.closest('[data-shared-next]')){offset+=50;refresh().catch(e=>this.toast(e.message,true));}};
  dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();await refresh();
 }
}
