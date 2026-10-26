import test from 'node:test';
import assert from 'node:assert/strict';
import {sidebarBounds,sidebarWidth,AndroidSidebarResize} from '../web/sidebar-layout.js';

function fixture({width=900,landscape=true,stored=null,platform='android'}={}){
 const events={},attributes={},values={},classes=new Set(),storage=new Map(stored===null?[]:[['studio-android-sidebar-width-v1',stored]]);
 const handle={hidden:true,addEventListener:(key,fn)=>events[key]=fn,setAttribute:(key,value)=>attributes[key]=value,
  setPointerCapture:id=>handle.capture=id,hasPointerCapture:id=>handle.capture===id,releasePointerCapture:()=>{handle.capture=null;}};
 const media={matches:landscape,addEventListener:(key,fn)=>media.change=fn};
 const win={innerWidth:width,matchMedia:()=>media,addEventListener:(key,fn)=>win[key]=fn,
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)}};
 const doc={documentElement:{style:{setProperty:(key,value)=>values[key]=value}},getElementById:()=>handle,
  body:{dataset:{},classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)}}};
 const layout=new AndroidSidebarResize(platform,{windowRef:win,documentRef:doc});
 const pointer=(x,id=1)=>({clientX:x,pointerId:id,isPrimary:true,button:0,preventDefault(){}});
 return {layout,handle,media,win,doc,classes,events,storage,values,attributes,pointer};
}

test('navigation width leaves room for the editor and clamps corrupt saved values',()=>{
 for(const width of [480,568,640,896,1280]){
  const bounds=sidebarBounds(width);assert.ok(bounds.max<=width-320);
  assert.equal(sidebarWidth(-999,width),bounds.min);assert.equal(sidebarWidth(9999,width),bounds.max);
 }
 assert.equal(sidebarWidth(NaN,896),232);
});
test('touch/mouse drag changes only width and persists after release',()=>{
 const f=fixture();f.events.pointerdown(f.pointer(230));f.events.pointermove(f.pointer(310));
 assert.equal(f.layout.width,312);assert.equal(f.storage.size,0);assert.ok(f.classes.has('sidebar-resizing'));
 f.events.pointerup(f.pointer(310));assert.equal(f.storage.get('studio-android-sidebar-width-v1'),'312');
 assert.equal(f.classes.size,0);assert.equal(f.layout.pointer,null);assert.equal(f.attributes['aria-valuenow'],'312');
 assert.equal(fixture({stored:'312'}).layout.width,312);
});
test('rotation clamps transient width without losing preference and hides the divider in portrait',()=>{
 const f=fixture({stored:'400'});f.win.innerWidth=568;f.win.resize();assert.equal(f.layout.width,248);
 f.media.matches=false;f.media.change();assert.equal(f.handle.hidden,true);
 f.win.innerWidth=900;f.media.matches=true;f.media.change();assert.equal(f.layout.width,400);assert.equal(f.handle.hidden,false);
 assert.equal(f.storage.get('studio-android-sidebar-width-v1'),'400');
});
test('cancelled or secondary pointer cannot leave the page stuck in resize mode',()=>{
 const f=fixture();f.events.pointerdown(f.pointer(230));f.events.pointermove(f.pointer(350,9));assert.equal(f.layout.width,232);
 f.events.pointermove(f.pointer(350));f.events.pointercancel(f.pointer(350));assert.equal(f.layout.width,232);
 assert.equal(f.classes.size,0);assert.equal(f.storage.size,0);
});
test('keyboard adjustment and default reset work while desktop stays unchanged',()=>{
 const f=fixture();f.events.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(f.layout.width,248);
 f.events.dblclick();assert.equal(f.layout.width,232);
 const desktop=fixture({platform:'pc',stored:'350'});assert.equal(desktop.handle.hidden,true);assert.deepEqual(desktop.values,{});assert.deepEqual(desktop.events,{});
});
