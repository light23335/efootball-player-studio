const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export class UpdateUI {
  constructor({api,toast,apk,rerender}) {
    Object.assign(this,{api,toast,rerender});this.operation='apply';this.source=apk;this.target='';this.patch='';this.state={phase:'idle'};
    document.addEventListener('input',e=>{if(e.target.dataset.updatePath)this[e.target.dataset.updatePath]=e.target.value;});
    document.addEventListener('click',e=>this.click(e));
  }
  field(key,label,category){return `<label class="field"><span>${label}</span><div class="input-row"><input class="input" data-update-path="${key}" value="${esc(this[key])}" placeholder="选择文件或粘贴路径"><button class="button secondary" data-update-pick="${key}" data-update-category="${category}">选择</button></div></label>`;}
  render(){return `<div class="segmented migration-tabs">${[['apply','合成新版 APK'],['create','制作增量包'],['inspect','检查 APK']].map(([id,label])=>`<button data-update-operation="${id}" class="${this.operation===id?'active':''}">${label}</button>`).join('')}</div><section class="panel"><div class="panel-title"><h2>${this.operation==='apply'?'用已有 APK 和增量包生成新版':this.operation==='create'?'只打包两个 APK 之间的改动':'读取版本、哈希与签名证书'}</h2></div><div class="panel-body"><p class="panel-description">${this.operation==='apply'?'合成前核对原包哈希，完成后核对新版哈希。输出新文件，原包继续保留。':this.operation==='create'?'需要原 APK 和已经完成修改、签名的新版 APK。接收方只需取得生成的 .efupdate。':'证书指纹用于比较签名身份；该检查不替代 Android 安装器的签名验证。'}</p><div class="field-grid">${this.field('source',this.operation==='inspect'?'要检查的 APK':'原 APK','apk')}${this.operation==='apply'?this.field('patch','增量更新包','update'):this.operation==='create'?this.field('target','新版完整 APK','apk'):''}</div><div class="portrait-actions"><button class="button primary" data-update-start ${this.state.phase==='working'?'disabled':''}>${this.state.phase==='working'?'正在处理…':this.operation==='apply'?'合成并校验':this.operation==='create'?'生成增量包':'检查 APK'}</button></div></div></section><div id="update-status"></div><section class="panel"><div class="panel-title"><h2>覆盖安装与培养进度</h2></div><div class="panel-body"><p>同包名、同签名且版本满足安装要求时，新版 APK 可以覆盖安装。增量包本身不是 APK，不能直接交给 Android 安装器。</p><p class="note">改签后的包无法直接覆盖旧签名。首次转换前应从游戏导出最新存档和球员快照；后续沿用同一签名密钥，并保留独立球员包以便重新导入。增量包不包含你的存档或签名私钥。</p></div></section>`;}
  activate(page){this.active=page==='apk';if(this.active){this.update();this.poll();}}
  update(){const el=document.querySelector('#update-status');if(!el)return;const s=this.state,r=s.result,m=r?.manifest;
    let detail=s.message||'';if(s.phase==='working'&&s.total)detail+=` · ${Math.round(100*s.done/s.total)}%`;
    if(r?.sha256)detail+=`\nSHA-256 ${r.sha256}\n签名证书 ${r.signer_sha256.join('，')||'未读取到 v2/v3 签名证书'}\n版本 ${r.release_id||'未标注'}`;
    if(m)detail+=`\n原包 ${(m.source.size/1024**2).toFixed(1)} MB → 新版 ${(m.target.size/1024**2).toFixed(1)} MB\n${m.same_signer?'签名证书相同；安装器仍会校验签名与版本。':'签名证书不同或未读取到，不能据此直接覆盖安装。'}${r.saving_percent!==undefined?'\n增量包 '+(r.size/1024**2).toFixed(2)+' MB · 减少传输 '+r.saving_percent+'%':''}\n${r.path}`;
    el.innerHTML=(detail?`<div class="migration-status ${s.phase==='error'?'error':s.phase==='done'?'success':''}">${esc(detail)}</div>`:'')+(r?.url?`<div class="download-result"><span>已保存在软件 data/exports 中</span><a class="button secondary" download href="${esc(r.url)}">下载${this.operation==='create'?'增量包':'新版 APK'}</a></div>`:'');
    const button=document.querySelector('[data-update-start]');if(button){button.disabled=s.phase==='working';button.textContent=s.phase==='working'?'正在处理…':this.operation==='apply'?'合成并校验':this.operation==='create'?'生成增量包':'检查 APK';}
  }
  async poll(){clearTimeout(this.timer);if(!this.active)return;try{this.state=await this.api('apk-delta/status',{});this.update();if(this.state.phase==='working')this.timer=setTimeout(()=>this.poll(),1000);}catch(e){this.toast(e.message,true);}}
  async click(e){const b=e.target.closest('[data-update-operation],[data-update-pick],[data-update-start]');if(!b||b.disabled)return;
    try{if(b.dataset.updateOperation){this.operation=b.dataset.updateOperation;this.rerender();return;}
      if(b.dataset.updatePick){const r=await this.api('dialog',{category:b.dataset.updateCategory});if(r.path){this[b.dataset.updatePick]=r.path;document.querySelector(`[data-update-path="${b.dataset.updatePick}"]`).value=r.path;}return;}
      this.state=await this.api('apk-delta/start',{operation:this.operation,source:this.source,target:this.target,patch:this.patch});this.update();this.poll();
    }catch(error){this.toast(error.message,true);}
  }
}
