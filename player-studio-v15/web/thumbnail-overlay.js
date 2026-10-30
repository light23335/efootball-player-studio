// Preview-only native MobileIconInfo layout (192 x 192). Never exported to art.
import {emblemKind} from './native-card.js';
const cache=new Map();
async function font(record){
  if(!record?.asset_id)return 'Arial';
  const id=record.asset_id,key='font:'+id;
  if(!cache.has(key))cache.set(key,(async()=>{try{const family='Mini'+id.slice(0,16),face=await new FontFace(family,`url(/assets/${id})`).load();document.fonts.add(face);return family;}catch{return 'Arial';}})());
  return cache.get(key);
}
async function image(record){
  if(!record?.asset_id)return null;
  const key='image:'+record.asset_id;
  if(!cache.has(key))cache.set(key,(async()=>{try{const el=new Image();el.src='/assets/'+record.asset_id;await el.decode();return el;}catch{return null;}})());
  return cache.get(key);
}
export function miniOverlayState(project,simulation={}){
  const assets=project.native_card?.info?.assets||{};
  return {position:project.identity?.position||'',overall:simulation.ovr??project.native_card?.info?.overall??'',
    emblem:assets[emblemKind(project)],fonts:project.native_card?.fonts||{},boosted:simulation.ovr>simulation.baseOvr};
}
export async function prepareMiniOverlay(project,simulation){
  const state=miniOverlayState(project,simulation);
  const [sans,headline,emblem]=await Promise.all([font(state.fonts.sans),font(state.fonts.headline),image(state.emblem)]);
  return ctx=>{
    if(document.querySelector('#thumbnail-ui-overlay')?.checked===false)return;
    ctx.save();ctx.globalCompositeOperation='source-over';ctx.scale(512/192,512/192);
    function text(value,box,family,color){
      if(value==='')return;
      ctx.font=`${box.size*96/72}px "${family}"`;ctx.fillStyle=color;ctx.strokeStyle='rgba(0,0,0,.3)';ctx.lineWidth=1;ctx.textAlign='center';ctx.textBaseline='alphabetic';
      const m=ctx.measureText(String(value)),ascent=m.fontBoundingBoxAscent??m.actualBoundingBoxAscent,descent=m.fontBoundingBoxDescent??m.actualBoundingBoxDescent;
      const x=box.x+box.w/2,y=box.y+(box.h+ascent-descent)/2;
      ctx.strokeText(String(value),x,y,box.w);ctx.fillText(String(value),x,y,box.w);
    }
    text(state.position,{x:6,y:5,w:84,h:62,size:30},sans,'#fff');
    text(state.overall,{x:6,y:38,w:84,h:86,size:40},headline,state.boosted?'#ffff00':'#fff');
    if(emblem){const scale=Math.min(60/emblem.width,60/emblem.height),w=emblem.width*scale,h=emblem.height*scale;ctx.drawImage(emblem,18+(60-w)/2,109+(60-h)/2,w,h);}
    ctx.restore();
  };
}
