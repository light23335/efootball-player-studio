import {choosePlayerAction} from './player-prompts.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export class PlayerFoldersUI {
  constructor(context){
    Object.assign(this,context);this.selected='';this.rows=[];this.sequence=0;
    document.addEventListener('click',e=>{
      const tab=e.target.closest('[data-folder-select]');
      if(tab){this.selected=tab.dataset.folderSelect;this.paint();this.changed();return;}
      const remove=e.target.closest('[data-folder-remove-player]');
      if(remove){this.removePlayer(remove.dataset.folderRemovePlayer).catch(error=>this.toast(error.message,true));return;}
      const button=e.target.closest('[data-folder-action]');if(!button||button.disabled)return;
      this.action(button.dataset.folderAction).catch(error=>this.toast(error.message,true));
    });
  }
  render(){return '<section class="personal-folders" aria-label="球员文件夹"><div id="player-folder-controls"></div></section>';}
  async load(){
    const seq=++this.sequence;
    try{
      const data=await this.api('players/folders/list',{});if(seq!==this.sequence)return;
      this.rows=data.rows;this.stats=data;this.error='';
      if(this.selected&&this.selected!=='unfiled'&&!this.rows.some(r=>r.id===this.selected))this.selected='';
    }catch(error){if(seq!==this.sequence)return;this.error=error.message;this.selected='';this.rows=[];}
    this.paint();
  }
  paint(){
    const box=document.querySelector('#player-folder-controls');if(!box)return;
    const row=this.rows.find(r=>r.id===this.selected);
    const tabs=[{id:'',name:'全部球员',count:this.stats?.all_count??'—'},{id:'unfiled',name:'未分类',count:this.stats?.unfiled_count??'—'},...this.rows];
    box.innerHTML=`<div class="folder-heading"><h3>球员文件夹</h3><button class="button secondary" data-folder-action="create" ${this.error?'disabled':''}>＋ 新建文件夹</button></div><div class="folder-tabs" role="group" aria-label="选择球员文件夹">${tabs.map(r=>`<button type="button" class="folder-tab" data-folder-select="${esc(r.id)}" aria-pressed="${r.id===this.selected}" title="${esc(r.name)}"><span>${r.id&&r.id!=='unfiled'?'▱ ':''}${esc(r.name)}</span><small>${esc(r.count)}</small></button>`).join('')}</div>${row?`<div class="folder-current"><strong>${esc(row.name)}</strong><div class="folder-actions"><button class="button primary" data-folder-action="add">添加已有球员</button><button class="button subtle" data-folder-action="rename">重命名</button><button class="button subtle" data-folder-action="delete">删除文件夹</button></div></div>`:'<p class="note">将已有球员勾选加入文件夹，已建文件夹可随时继续添加。分类不会复制或修改球员工程。</p>'}${this.error?`<p class="migration-status error">${esc(this.error)} 全部球员仍可正常查看。</p>`:''}`;
  }
  async action(action){
    const row=this.rows.find(r=>r.id===this.selected);
    if(action==='create'||action==='add'||action==='rename')return this.editor(action,row);
    if(action==='delete'&&row){
      if(await choosePlayerAction('删除球员文件夹？',`删除“${row.name}”后，其中球员归入“未分类”。球员工程、素材和游戏数据均保留。`,[{id:'delete',label:'确认删除文件夹',danger:true}])!=='delete')return;
      await this.api('players/folders/delete',{folder_id:row.id,confirmed:true});
      this.selected='';await this.changed();this.toast('文件夹已删除，球员已保留');
    }
  }
  async removePlayer(id){
    if(!this.selected||this.selected==='unfiled')return;
    await this.api('players/folders/remove',{folder_id:this.selected,player_ids:[id]});
    await this.changed();this.toast('已移到未分类，球员工程保留');
  }
  editor(mode,row){
    if(this.dialog?.isConnected)return;
    if(mode!=='create'&&!row)throw Error('请先选择一个文件夹');
    const dialog=document.createElement('dialog'),state={mode,folder:row,selected:new Set(),query:'',offset:0,request:0,rows:[],busy:false};
    this.dialog=dialog;dialog.className='player-folder-dialog';
    dialog.innerHTML=`<h2>${mode==='create'?'新建球员文件夹':mode==='add'?'添加球员到 '+esc(row.name):'重命名文件夹'}</h2>${mode!=='add'?`<label class="field"><span>文件夹名称</span><input class="input" data-folder-name maxlength="60" value="${mode==='rename'?esc(row.name):''}" placeholder="例如：利物浦、经典球员"></label>`:''}${mode!=='rename'?`<p class="note">勾选已有球员加入。球员只保留一份；从其他文件夹加入时会移动分类，工程内容不变。</p><input class="input" type="search" data-folder-query placeholder="搜索球员姓名或永久身份" aria-label="搜索要加入的球员" autocomplete="off"><div class="folder-pick-actions"><button class="button subtle" data-folder-pick-page>勾选本页</button><button class="button subtle" data-folder-clear>清空勾选</button><span data-folder-selected role="status">已勾选 0 人</span></div><div class="folder-player-choices" data-folder-choices aria-live="polite"></div><div class="folder-picker-pages" data-folder-pages></div>`:''}<p class="migration-status error" data-folder-error role="alert"></p><div class="folder-dialog-footer"><button class="button secondary" data-folder-cancel>取消</button><button class="button primary" data-folder-submit>${mode==='create'?'创建文件夹':mode==='rename'?'保存名称':'添加所选球员'}</button></div>`;
    const q=s=>dialog.querySelector(s);
    const count=()=>{if(q('[data-folder-selected]'))q('[data-folder-selected]').textContent=`已勾选 ${state.selected.size} 人`;};
    const paintRows=()=>{
      q('[data-folder-choices]').innerHTML=state.rows.length?state.rows.map(p=>{
        const existing=mode==='add'&&p.folder_id===row.id;
        return `<label class="folder-player-choice"><input type="checkbox" data-folder-player="${esc(p.package_id)}" ${existing||state.selected.has(p.package_id)?'checked':''} ${existing?'disabled':''}><span><strong>${esc(p.display_name||p.name)}</strong><small>${existing?'已在此文件夹':p.folder_name?'当前文件夹：'+esc(p.folder_name):'未分类'} · ${esc(p.position)}<br>${esc(p.package_id)}</small></span></label>`;
      }).join(''):'<p class="note">没有符合条件的球员。请先保存球员，或换一个搜索词。</p>';
      q('[data-folder-pages]').innerHTML=`<button class="button secondary" data-folder-page="-1" ${state.offset?'':'disabled'}>上一页</button><span>第 ${Math.floor(state.offset/60)+1} / ${Math.max(1,Math.ceil((state.total||0)/60))} 页</span><button class="button secondary" data-folder-page="1" ${state.offset+60<(state.total||0)?'':'disabled'}>下一页</button>`;count();
    };
    const load=async()=>{
      const req=++state.request;
      try{
        const data=await this.api('players/list',{query:state.query,offset:state.offset,limit:60});
        if(req!==state.request||!dialog.isConnected)return;
        state.rows=data.rows;state.total=data.total;paintRows();
      }catch(error){if(req===state.request&&dialog.isConnected)q('[data-folder-error]').textContent=error.message;}
    };
    dialog.addEventListener('input',e=>{
      if(!e.target.hasAttribute('data-folder-query')||state.busy)return;
      state.query=e.target.value;state.offset=0;clearTimeout(state.timer);state.request++;
      state.timer=setTimeout(load,200);
    });
    dialog.addEventListener('change',e=>{
      const id=e.target.dataset.folderPlayer;if(!id||state.busy)return;
      if(e.target.checked)state.selected.add(id);else state.selected.delete(id);count();
    });
    dialog.addEventListener('click',e=>{
      if(state.busy)return;
      const b=e.target.closest('button');if(!b||b.disabled)return;
      if(b.hasAttribute('data-folder-cancel'))dialog.close();
      if(b.hasAttribute('data-folder-pick-page')){for(const p of state.rows)if(mode!=='add'||p.folder_id!==row.id)state.selected.add(p.package_id);paintRows();}
      if(b.hasAttribute('data-folder-clear')){state.selected.clear();paintRows();}
      if(b.dataset.folderPage){state.offset=Math.max(0,state.offset+Number(b.dataset.folderPage)*60);clearTimeout(state.timer);load();}
      if(b.hasAttribute('data-folder-submit'))submit().catch(error=>{if(dialog.isConnected)q('[data-folder-error]').textContent=error.message;});
    });
    const submit=async()=>{
      state.busy=true;q('[data-folder-submit]').disabled=true;q('[data-folder-cancel]').disabled=true;q('[data-folder-error]').textContent='';
      try{
        const body={name:q('[data-folder-name]')?.value,folder_id:row?.id,player_ids:[...state.selected]};
        const result=await this.api('players/folders/'+mode,body);
        this.selected=result.folder.id;dialog.close();await this.changed();
        this.toast(mode==='rename'?'文件夹名称已更新':`已${mode==='create'?'创建文件夹并加入':'加入'} ${result.added} 名球员`);
      }finally{state.busy=false;if(dialog.isConnected){q('[data-folder-submit]').disabled=false;q('[data-folder-cancel]').disabled=false;}}
    };
    dialog.addEventListener('cancel',e=>{if(state.busy)e.preventDefault();});
    dialog.onclose=()=>{state.request++;clearTimeout(state.timer);dialog.remove();if(this.dialog===dialog)this.dialog=null;};
    document.body.append(dialog);dialog.showModal();q('[data-folder-name]')?.focus();
    if(mode!=='rename'){q('[data-folder-choices]').textContent='正在读取已有球员…';load();}
  }
}
