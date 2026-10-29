const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export class GameImportUI{
 constructor({api,toast,apk,companion,rerender}){Object.assign(this,{api,toast,apk,companion,rerender});this.state={phase:'idle'};
  document.addEventListener('input',e=>{if(e.target.dataset.gameSource)this[e.target.dataset.gameSource]=e.target.value;});
  document.addEventListener('click',e=>this.click(e));
 }
 field(key,label){return `<label class="field"><span>${label}</span><div class="input-row"><input class="input" data-game-source="${key}" value="${esc(this[key])}"><button class="button secondary" data-game-pick="${key}">选择</button></div></label>`;}
 render(){return `<section class="panel"><div class="panel-title"><h2>导入 APK 与更新数据库</h2></div><div class="panel-body"><p class="panel-description">支持制作方原版主包、工坊生成的个人自建包，以及配套改签的离线资源 APK。软件会读取球员、等级、球队和美术索引；个人包内已有的球员、卡包与教练在再次生成时继续保留。同一永久身份更新原槽位，新建球员使用独立槽位。</p>${this.field('apk','主程序 APK（原版或个人包）')}${this.field('companion','配套离线资源 APK（支持个人签名）')}<div class="portrait-actions"><button class="button primary" data-game-import>校验并导入数据库</button><button class="button secondary" data-game-reload hidden>载入数据库界面</button></div><button class="button subtle" data-game-adapter>导入已核对的兼容适配 JSON</button><div id="game-import-status" class="migration-status"></div><p class="note">同系列小更新自动核对关键接口和数据布局，不因完整引擎指纹变化而拒绝。校验通过后启用新版库；不兼容时保留当前数据库和工程。</p></div></section><section class="panel"><div class="panel-title"><h2>实装与进度</h2></div><div class="panel-body"><p>导入完成后，在 APK 实装页选择本次新增或修改的内容，生成同签名完整安装包。本机工程与签名保留；数据库更新不会替换手机存档。</p></div></section>`;}
 activate(page){this.active=page==='apk';if(this.active)this.poll();else clearTimeout(this.timer);}
 async poll(){clearTimeout(this.timer);if(!this.active)return;try{this.state=await this.api('game-import/status',{});this.update();if(this.state.phase==='working')this.timer=setTimeout(()=>this.poll(),1000);}catch(e){this.toast(e.message,true);}}
 update(){const target=document.querySelector('#game-import-status');if(!target)return;const s=this.state;target.textContent=s.message||'当前数据库保持启用。';target.className='migration-status '+(s.phase==='error'?'error':s.phase==='done'?'success':'');
  if(s.result)target.textContent+=`\n版本 ${s.result.release_id}\n球员 ${s.result.counts.players.toLocaleString()} · 美术资源 ${s.result.counts.assets.toLocaleString()}\n游戏内效果由你验收。`;
  const start=document.querySelector('[data-game-import]');start.disabled=s.phase==='working';start.textContent=s.phase==='working'?'正在导入…':'校验并导入新版数据库';document.querySelector('[data-game-reload]').hidden=s.phase!=='done';
 }
 async click(e){const b=e.target.closest('[data-game-pick],[data-game-import],[data-game-reload],[data-game-adapter]');if(!b)return;try{
  if(b.hasAttribute('data-game-adapter')){const chosen=await this.api('dialog',{category:'project'});if(chosen.path){const result=await this.api('game-import/install-adapter',{path:chosen.path});this.toast(result.message);}return;}
  if(b.hasAttribute('data-game-reload')){location.reload();return;}
  if(b.dataset.gamePick){const r=await this.api('dialog',{category:'apk'});if(r.path){this[b.dataset.gamePick]=r.path;document.querySelector(`[data-game-source="${b.dataset.gamePick}"]`).value=r.path;}return;}
  this.state=await this.api('game-import/start',{apk:this.apk,companion:this.companion});this.update();this.poll();
 }catch(error){this.toast(error.message,true);}}
}

