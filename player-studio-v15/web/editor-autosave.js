export function saveTarget(page){return page==='coaches'?'coach':page==='packs'?'pack':page==='tools'?'settings':'player';}
export const saveLabels={coach:'保存教练',pack:'保存卡包',player:'保存球员',settings:'保存设置'};

// A single serialized queue prevents an older slow response overwriting a
// newer edit. No render is performed after an automatic save.
export class EditorAutosave{
 constructor({api,read,onState=()=>{},storage=globalThis.localStorage}){Object.assign(this,{api,read,onState,storage});this.saved=new Map();this.pending=new Map();this.inflight=new Map();this.failures=new Map();this.results=new Map();this.tail=Promise.resolve();}
 key(category,value){return category+':'+(value?.uuid||category);}
 capture(){
  for(const [category,value] of Object.entries(this.read())){
   if(!value)continue;const key=this.key(category,value),json=JSON.stringify(value);
   if(this.pending.get(key)?.json===json||this.inflight.get(key)?.json===json||!this.pending.has(key)&&!this.inflight.has(key)&&this.saved.get(key)===json)continue;
   this.pending.set(key,{category,value:structuredClone(value),json});this.onState(category,'pending');
  }
  if(this.pending.size||this.inflight.size)try{this.storage?.setItem('studio-pending-drafts',JSON.stringify(this.closeRows()));}catch{}
 }
 closeRows(){const rows=new Map(this.inflight);for(const [k,v] of this.pending)rows.set(k,v);return [...rows.values()];}
 async drain(){
  while(this.pending.size){
   const [key,row]=this.pending.entries().next().value;this.pending.delete(key);this.inflight.set(key,row);
   try{this.onState(row.category,'saving');const result=await this.api('editor/drafts/save',row);
    this.saved.set(key,row.json);this.failures.delete(key);this.results.set(row.category,result);this.onState(row.category,result.committed?'saved':'draft',result.message);
    globalThis.window?.dispatchEvent(new CustomEvent('studio-editor-saved',{detail:{category:row.category,result,value:row.value}}));
   }catch(error){if(!this.pending.has(key))this.pending.set(key,row);this.failures.set(key,error);this.onState(row.category,'error',error.message);throw error;}
   finally{this.inflight.delete(key);}
  }
  try{this.storage?.removeItem('studio-pending-drafts');}catch{}
 }
 flush(){this.capture();this.tail=this.tail.catch(()=>{}).then(()=>this.drain());return this.tail;}
 async start(){
  try{const cached=JSON.parse(this.storage?.getItem('studio-pending-drafts')||'[]');for(const row of cached)this.pending.set(this.key(row.category,row.value),row);if(this.pending.size)await this.drain();}catch{}
  this.timer=setInterval(()=>this.flush().catch(()=>{}),700);
  for(const type of ['input','change'])document.addEventListener(type,()=>queueMicrotask(()=>this.capture()));
  document.addEventListener('click',()=>this.capture(),true);
  document.addEventListener('focusout',()=>this.flush().catch(()=>{}));
  for(const type of ['pagehide','beforeunload'])window.addEventListener(type,()=>{this.capture();});
 }
}
