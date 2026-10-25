// Original assets and native widget states; browser composition, not UE rendering.
import {formatCardDate,originalCardDate} from './card-design.js';
// The blank preset's f04 can contain a fully opaque mechanical/background
// design. It must be below the replacement portrait, rather than treated as
// a transparent foreground frame. Original complete cards retain their order.
export function cardLayerOrder(card){
  return card.preset_id
    ? {f01:0,f02:1,f04:2,f03:3,f05:4,f07:5,portrait:6,f10:7,f09:8}
    : {f01:0,f02:1,portrait:2,f04:3,f03:4,f05:5,f06:6,f07:7,f10:8,f09:9};
}
export function nativeCardState(project){
  const card=project.native_card,ui=card?.ui;if(!ui)return null;
  const source=project.source_player?.original_payload,original=source?.initial_booster_id_list||[];
  const slotCount=Math.max((project.booster_ids||[]).filter(Boolean).length,original[1]?2:original[0]?1:0),hasBooster=slotCount>0;
  let type=card.card_type==='BigTime'?5:ui.native_dispatch.kind_states[card.card_type]??0;
  let state=`PlayerType_${type}`;
  if(hasBooster&&ui.states[state+'_Booster'])state+='_Booster';
  else if(type===3&&card.native_agent>=340)state+='_BoosterNone';
  const tracks=ui.states[state]||{};
  const widgets=Object.fromEntries(Object.entries(ui.widgets).map(([key,value])=>[key,{...value,...tracks[key]}]));
  const slots=ui.states['BoosterSlot_'+(slotCount||'None')]||{};
  for(const key of ['ScaleBox_BoosterSlot_1','ScaleBox_BoosterSlot_2'])Object.assign(widgets[key],slots[key]||{});
  return {state,type,widgets,slotCount,hasBooster};
}
export class NativeCardRenderer {
  constructor(canvas,onStatus,catalog={}){this.canvas=canvas;this.onStatus=onStatus;this.catalog=catalog;this.cache=new Map();this.generation=0;this.motion=true;this.key=null;this.resources=[];this.framesRendered=0;}
  async asset(layer){
    if(this.cache.has(layer.asset_id))return this.cache.get(layer.asset_id);
    const promise=new Promise(resolve=>{
      if(layer.kind==='video'){
        const el=document.createElement('video');el.muted=true;el.loop=true;el.playsInline=true;el.preload='auto';
        el.onloadeddata=()=>resolve(el);el.onerror=()=>resolve(null);el.src='/assets/'+layer.asset_id;el.load();
      }else{const el=new Image();el.onload=()=>resolve(el);el.onerror=()=>resolve(null);el.src='/assets/'+layer.asset_id;}
    });this.cache.set(layer.asset_id,promise);return promise;
  }
  async font(record){
    if(!record)return null;const key='font:'+record.asset_id;
    if(!this.cache.has(key))this.cache.set(key,(async()=>{const family='Native'+record.asset_id.slice(0,16);try{const font=await new FontFace(family,`url(/assets/${record.asset_id})`).load();document.fonts.add(font);return family;}catch{return null;}})());
    return this.cache.get(key);
  }
  async update(project,simulation){
    this.project=project;this.simulation=simulation;
    const card=project.native_card,dateOverride=project.appearance.card_date!==undefined||card?.preset_id||project.appearance.card_date_visible===false;
    const key=JSON.stringify([card?.source_id,card?.preset_id,card?.layers?.map(l=>[l.asset_id,l.blend]),card?.fonts,card?.info,project.appearance.portrait,project.appearance.hide_portrait,Boolean(dateOverride)]);
    if(this.key===key){this.draw();return;}
    this.clear();this.key=key;const generation=++this.generation;
    const frontLayers=card.layers.filter(layer=>!layer.slot.startsWith('b')&&!layer.slot.startsWith('m')&&layer.slot!=='portrait'&&!(dateOverride&&layer.slot==='f09'));
    if(project.appearance.portrait&&!project.appearance.hide_portrait)frontLayers.push({slot:'portrait',kind:'image',asset_id:project.appearance.portrait,blend:'source-over'});
    const order=cardLayerOrder(card);frontLayers.sort((a,b)=>(order[a.slot]??7)-(order[b.slot]??7));
    const layers=await Promise.all(frontLayers.map(async layer=>({...layer,element:await this.asset(layer)})));
    const decorations=await Promise.all(Object.entries(card.info?.assets||{}).map(async([key,asset])=>[key,await this.asset(asset)]));
    const [sans,headline,chinese]=await Promise.all(['sans','headline','chinese'].map(k=>this.font(card.fonts[k])));
    if(generation!==this.generation)return;
    this.resources=layers;this.decorations=Object.fromEntries(decorations);this.fonts={sans,headline,chinese};
    this.onStatus({layers:layers.filter(l=>l.element).length,videos:layers.filter(l=>l.element&&l.kind==='video').length,ui:decorations.filter(([,el])=>el).length,missing:layers.filter(l=>!l.element).length+(card.missing?.length||0)+(card.info?.missing?.length||0)});
    await Promise.all(layers.filter(l=>l.kind==='video'&&l.element).map(async layer=>{
      const video=layer.element;
      if(card.preview_only&&Number.isFinite(video.duration)&&video.duration>.5){await new Promise(resolve=>{video.addEventListener('seeked',resolve,{once:true});video.currentTime=Math.min(.8,video.duration/3);setTimeout(resolve,2000);});}
      else{video.currentTime=0;if(this.motion)video.play().catch(()=>{});}
    }));
    if(generation!==this.generation)return;
    this.draw();this.tick();
  }
  clear(){this.generation++;cancelAnimationFrame(this.frame);for(const layer of this.resources)if(layer.kind==='video')layer.element?.pause();this.resources=[];this.key=null;}
  setMotion(value){this.motion=value;for(const layer of this.resources)if(layer.kind==='video'&&layer.element){if(value)layer.element.play().catch(()=>{});else layer.element.pause();}this.draw();this.tick();}
  tick(){cancelAnimationFrame(this.frame);if(!this.key||!this.motion)return;this.frame=requestAnimationFrame(time=>{if(!document.hidden&&this.canvas.offsetParent&&(!this.lastFrame||time-this.lastFrame>=32)){this.draw();this.lastFrame=time;}this.tick();});}
  draw(){
    const p=this.project,card=p?.native_card;if(!card||!this.resources.length)return;
    const canvas=this.canvas,cw=card.preview_only?268:1200,ch=card.preview_only?384:1720;if(canvas.width!==cw||canvas.height!==ch){canvas.width=cw;canvas.height=ch;}
    const ctx=canvas.getContext('2d'),{width,height}=card.layout;
    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.save();ctx.scale(canvas.width/width,canvas.height/height);
    for(const layer of this.resources){
      const image=layer.element;if(!image||layer.kind==='video'&&image.readyState<2)continue;
      ctx.globalCompositeOperation=layer.slot==='f01'?'source-over':layer.blend||'source-over';
      if(layer.slot==='portrait'){
        const zoom=p.appearance.photo_zoom||1,contain=p.appearance.portrait_fit==='contain'||card.preset_id&&p.native_art?.portrait?.kind!=='portrait';
        const scale=contain?Math.min(width/image.width,height/image.height):null,w=contain?image.width*scale:width,h=contain?image.height*scale:height;
        const x=(width-w*zoom)/2+(p.appearance.photo_x||0)*width/600,y=height-h*zoom+(p.appearance.photo_y||0)*height/860;
        ctx.drawImage(image,x,y,w*zoom,h*zoom);
      }else ctx.drawImage(image,0,0,width,height);
    }
    ctx.globalCompositeOperation='source-over';
    if(p.appearance.native_overlay_text!==false){
      const state=nativeCardState(p),widgets=state?.widgets;
      const transform=(box,draw)=>{
        if(!box||box.visible===false)return;ctx.save();const px=box.w*(box.pivot?.X??.5),py=box.h*(box.pivot?.Y??.5);
        ctx.translate(box.x+(box.Translation||0)+px,box.y+(box['Translation[1]']||0)+py);
        ctx.rotate((box.Rotation??box.angle??0)*Math.PI/180);ctx.scale(box.Scale??1,box['Scale[1]']??1);ctx.translate(-px,-py);draw();ctx.restore();
      };
      const text=(value,box,family)=>transform(box,()=>{
        if(!family||!value)return;ctx.fillStyle='#fff';ctx.strokeStyle='rgba(0,0,0,.3)';ctx.lineWidth=1;ctx.textAlign=box.align||'center';ctx.textBaseline='alphabetic';
        // Slate uses points at 96 DPI. Center the font line, not the glyph ink:
        // stencil digits have a different ascent/descent from the name font.
        const factor=family===this.fonts.chinese ? .888889 : 1;ctx.font=`${box.size*96/72*factor}px "${family}"`;
        const metrics=ctx.measureText(value),ascent=metrics.fontBoundingBoxAscent??metrics.actualBoundingBoxAscent,descent=metrics.fontBoundingBoxDescent??metrics.actualBoundingBoxDescent;
        const x=ctx.textAlign==='center'?box.w/2:0,y=(box.h+ascent-descent)/2;
        ctx.strokeText(value,x,y,box.w);ctx.fillText(value,x,y,box.w);
      });
      const image=(key,box)=>transform(box,()=>{const el=this.decorations?.[key];if(el)ctx.drawImage(el,0,0,box.w,box.h);});
      const name=p.display_name||p.identity.name||'',nameFont=/[^\u0000-\u024f]/.test(name)?this.fonts.chinese:this.fonts.sans;
      if(widgets){
        text(String(this.simulation.ovr),widgets.Text_Overall,this.fonts.headline);text(p.identity.position,widgets.Text_Position,this.fonts.sans);
        for(let i=0;i<6;i++)text(name,widgets[`Text_PlayerName_${i}`],nameFont);
        const customDate=p.appearance.card_date!==undefined||card.preset_id;
        const date=formatCardDate(p.appearance.card_date??originalCardDate(card));
        if(date&&p.appearance.card_date_visible!==false)text(date,{...widgets.Text_Date,visible:customDate?card.card_type==='BigTime':widgets.Text_Date.visible},this.fonts.sans);
        image('logo',widgets.Img_eFootballLogo);
        const info=card.info||{},club=!!this.decorations.club;
        image(club?'club':'nation',{...(club?widgets.EmblemClub||widgets.EmblemNationality:widgets.EmblemNationality),visible:true});
        const stars=widgets.ScaleBox_RarityStar;
        const rarity=p.appearance.card_rarity||info.rarity;image('stars'+rarity,{...stars,x:stars.x-3,y:stars.y-3,w:117,h:27});
        for(let i=0;i<state.slotCount&&i<2;i++){
          const id=p.booster_ids?.[i]||0,booster=[...(p.custom_boosters||[]),...(this.catalog.boosters||[])].find(b=>b.id===id);
          const icon=!id?0:booster?.uuid?4:Math.min(5,Math.max(1,(booster?.category||0)+1));
          image('booster'+icon,widgets['ScaleBox_BoosterSlot_'+(i+1)]);
        }
        this.canvas.dataset.nativeLayout=state.state;
        this.canvas.dataset.nativeUiElements=JSON.stringify({stars:rarity,emblem:club?'club':'nation',boosters:state.slotCount,logo:true,name:state.type,date:customDate?date:null,portrait:!p.appearance.hide_portrait&&!!p.appearance.portrait});
      }else{
        text(String(this.simulation.ovr),card.layout.overall,this.fonts.headline);text(p.identity.position,card.layout.position,this.fonts.sans);text(name,card.layout.name,nameFont);
      }
    }
    ctx.restore();this.canvas.dataset.nativeSource=card.source_id;
    this.canvas.dataset.nativeVideoFrames=JSON.stringify(this.resources.filter(l=>l.kind==='video'&&l.element).map(l=>({slot:l.slot,time:Number(l.element.currentTime.toFixed(3)),paused:l.element.paused,ready:l.element.readyState})));
    this.framesRendered++;
  }
}
