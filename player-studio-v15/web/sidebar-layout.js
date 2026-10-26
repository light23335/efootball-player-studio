const STORAGE_KEY='studio-android-sidebar-width-v1';
const DEFAULT_WIDTH=232;

export function sidebarBounds(viewport){
 const available=Math.max(144,Number(viewport)-320);
 return {min:Math.min(200,available),max:Math.max(Math.min(200,available),Math.min(420,available))};
}
export function sidebarWidth(value,viewport){
 const {min,max}=sidebarBounds(viewport),number=Number(value);
 return Math.round(Math.max(min,Math.min(max,Number.isFinite(number)?number:DEFAULT_WIDTH)));
}

export class AndroidSidebarResize{
 constructor(platform,{windowRef=window,documentRef=document}={}){
  this.window=windowRef;this.document=documentRef;this.root=documentRef.documentElement;
  this.handle=documentRef.getElementById('sidebar-resizer');this.pointer=null;
  documentRef.body.dataset.platform=platform;
  if(platform!=='android'||!this.handle)return;
  this.media=windowRef.matchMedia('(orientation: landscape)');
  let saved;try{saved=windowRef.localStorage.getItem(STORAGE_KEY);}catch{}
  this.preferred=saved===null||saved===undefined?DEFAULT_WIDTH:Number(saved);
  if(!Number.isFinite(this.preferred))this.preferred=DEFAULT_WIDTH;
  this.handle.addEventListener('pointerdown',event=>this.start(event));
  this.handle.addEventListener('pointermove',event=>this.move(event));
  this.handle.addEventListener('pointerup',event=>{if(event.pointerId===this.pointer)this.finish(true);});
  this.handle.addEventListener('pointercancel',event=>{if(event.pointerId===this.pointer)this.finish(false);});
  this.handle.addEventListener('lostpointercapture',event=>{if(event.pointerId===this.pointer)this.finish(true);});
  this.handle.addEventListener('keydown',event=>this.key(event));
  this.handle.addEventListener('dblclick',()=>{this.preferred=DEFAULT_WIDTH;this.apply();this.save();});
  windowRef.addEventListener('resize',()=>this.refresh());
  if(this.media.addEventListener)this.media.addEventListener('change',()=>this.refresh());
  else this.media.addListener(()=>this.refresh());
  this.refresh();
 }
 refresh(){
  if(!this.media)return;
  if(this.pointer!==null)this.finish(false);
  this.handle.hidden=!this.media.matches;
  if(this.media.matches)this.apply();
 }
 apply(value=this.preferred){
  this.width=sidebarWidth(value,this.window.innerWidth);
  this.root.style.setProperty('--android-sidebar-width',this.width+'px');
  const {min,max}=sidebarBounds(this.window.innerWidth);
  for(const [key,item] of Object.entries({'aria-valuemin':min,'aria-valuemax':max,'aria-valuenow':this.width,'aria-valuetext':'导航宽度 '+this.width+' 像素'}))this.handle.setAttribute(key,String(item));
 }
 start(event){
  if(!this.media.matches||event.isPrimary===false||(event.button!==undefined&&event.button!==0))return;
  event.preventDefault();this.pointer=event.pointerId;this.startX=event.clientX;this.startWidth=this.width;
  this.handle.setPointerCapture(event.pointerId);this.document.body.classList.add('sidebar-resizing');
 }
 move(event){
  if(event.pointerId!==this.pointer||this.pointer===null)return;
  event.preventDefault();this.apply(this.startWidth+event.clientX-this.startX);
 }
 finish(commit){
  if(this.pointer===null)return;
  const pointer=this.pointer;this.pointer=null;
  if(commit){this.preferred=this.width;this.save();}else this.apply();
  this.document.body.classList.remove('sidebar-resizing');
  if(this.handle.hasPointerCapture(pointer))this.handle.releasePointerCapture(pointer);
 }
 save(){try{this.window.localStorage.setItem(STORAGE_KEY,String(this.preferred));}catch{}}
 key(event){
  if(!this.media.matches)return;
  const {min,max}=sidebarBounds(this.window.innerWidth),step=event.shiftKey?32:16;
  const value=event.key==='ArrowLeft'?this.width-step:event.key==='ArrowRight'?this.width+step:event.key==='Home'?min:event.key==='End'?max:null;
  if(value===null)return;
  event.preventDefault();this.apply(value);this.preferred=this.width;this.save();
 }
}
