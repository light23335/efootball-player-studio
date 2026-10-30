export function windowDelta(before,after,path=[],out=[]){
 if(before===after)return out;
 if(Array.isArray(before)&&Array.isArray(after)){
  if(before.length===after.length){after.forEach((v,i)=>windowDelta(before[i],v,[...path,i],out));return out;}
  let start=0,end=0;while(start<Math.min(before.length,after.length)&&JSON.stringify(before[start])===JSON.stringify(after[start]))start++;
  while(end<Math.min(before.length,after.length)-start&&JSON.stringify(before[before.length-1-end])===JSON.stringify(after[after.length-1-end]))end++;
  out.push({op:'splice',path,start,count:before.length-start-end,items:after.slice(start,after.length-end)});return out;
 }
 if(before&&after&&typeof before==='object'&&typeof after==='object'&&!Array.isArray(before)&&!Array.isArray(after)){
  for(const key of new Set([...Object.keys(before),...Object.keys(after)])){
   if(!(key in after))out.push({op:'remove',path:[...path,key]});else windowDelta(before[key],after[key],[...path,key],out);
  }return out;
 }
 out.push({op:'set',path,value:after});return out;
}
export class WindowSession{
 constructor(api,project,token,extra=()=>[]){this.api=api;this.project=project;this.extra=extra;this.baseline=structuredClone(project());this.token=token;this.id=crypto.randomUUID();this.started=false;}
 async start(){await this.api('window/open',{session:this.id});this.started=true;
  const close=()=>{if(!this.started)return;this.started=false;
   const project=this.project(),editor_drafts=this.extra();let body=JSON.stringify({session:this.id,project,editor_drafts});
   if(new Blob([body]).size>55000)body=JSON.stringify({session:this.id,package_id:project.package_id,patch:windowDelta(this.baseline,project),editor_drafts});
   const url='/api/window/close?token='+encodeURIComponent(this.token);
   if(!navigator.sendBeacon(url,new Blob([body],{type:'application/json'})))fetch(url,{method:'POST',body,keepalive:true,headers:{'Content-Type':'application/json'}}).catch(()=>{});
  };
  window.addEventListener('pagehide',close);window.addEventListener('beforeunload',close);
  window.addEventListener('studio-project-saved',event=>this.baseline=structuredClone(event.detail));
  window.addEventListener('pageshow',event=>{if(event.persisted)this.api('window/open',{session:this.id}).then(()=>this.started=true).catch(()=>{});});
 }
}
