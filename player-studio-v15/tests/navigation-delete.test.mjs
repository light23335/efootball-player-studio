import test from 'node:test';
import assert from 'node:assert/strict';
import {playerReady,editorPages,WorkspaceNavigation} from '../web/navigation-ui.js';
import {PersonalUI} from '../web/personal-ui.js';
import {CoachUI} from '../web/coach-ui.js';
import {WindowSession,windowDelta} from '../web/window-session.js';
import {BoosterLibraryUI} from '../web/booster-library-ui.js';

test('only player editing needs a loaded player; fresh slots stay locked until template loads',()=>{
 assert.equal(playerReady({identity:{name:''}}),false);
 assert.equal(playerReady({identity:{name:'新建球员 1'},status:'new-player-slot'}),false);
 assert.equal(playerReady({identity:{name:'新建球员 1'},status:'new-player-slot',source_player:{id:'7511'}}),true);
 assert.equal(playerReady({identity:{name:'导入的自制球员'}}),true);
 for(const id of ['library','personal','packs','coaches','native','tools','apk'])assert.equal(editorPages.has(id),false);
});
test('a user-collapsed active navigation group stays closed through background rerenders',()=>{
 const old=globalThis.document;globalThis.document={body:{dataset:{}},querySelectorAll:()=>[]};
 try{let handler;const button={dataset:{navGroup:'2'},setAttribute(){},getAttribute(){return 'section';}},content={hidden:true};
  const root={scrollTop:120,addEventListener(_,f){handler=f;},querySelectorAll:()=>[button],querySelector:selector=>selector==='#section'?content:{closest:()=>({dataset:{navSection:'2'}})}};
  const nav=new WorkspaceNavigation(root);nav.activate('model',true);assert.equal(content.hidden,false);
  handler({target:{closest:()=>button}});assert.equal(content.hidden,true);nav.activate('model',true);assert.equal(content.hidden,true);assert.equal(root.scrollTop,120);
 }finally{globalThis.document=old;}
});
test('canceling delete sends no save or delete request',async()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{let calls=0;const ui=new PersonalUI({project:()=>({package_id:'one'}),confirmDelete:async()=> 'cancel',api:async()=>{calls++;},flushSave:async()=>{calls++;}});
  ui.rows=[{package_id:'one',name:'测试球员'}];await ui.remove('one');assert.equal(calls,0);assert.equal(ui.deleting,false);
 }finally{globalThis.document=old;}
});
test('coach preview finds Chinese, English and pack names without native select',()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{const ui=new CoachUI({catalog:{coaches:[{id:'1',name:'瓜迪奥拉',name_en:'Pep Guardiola',pack_title:'Club pack'},{id:'2',name:'克洛普',name_en:'Jurgen Klopp'}]},project:()=>({})});
  for(const query of ['瓜迪','GUARDIOLA','club']){ui.previewQuery=query;assert.equal(ui.previewMatches()[0].id,'1');}
  ui.previewQuery='不存在';assert.equal(ui.previewMatches().length,0);
 }finally{globalThis.document=old;}
});

test('coach pagination reaches every row and clamps when searching narrows results',()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{const ui=new CoachUI({catalog:{coaches:Array.from({length:55},(_,id)=>({id:String(id),name:'Coach '+id}))},project:()=>({})});
  assert.equal(ui.resultPage().rows.length,24);assert.equal(ui.resultPage().pages,3);
  ui.page=2;assert.deepEqual(ui.resultPage().rows.map(r=>r.id),['48','49','50','51','52','53','54']);
  ui.query='Coach 54';assert.equal(ui.resultPage().total,1);assert.equal(ui.page,0);
  ui.query='not present';assert.equal(ui.resultPage().pages,1);assert.equal(ui.resultPage().rows.length,0);
 }finally{globalThis.document=old;}
});

test('native coach portrait hydration updates avatar elements without redrawing the page',async()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{let calls=0,updates=0;const row={id:'8',name:'Coach',type:'native'},ui=new CoachUI({catalog:{coaches:[row]},project:()=>({}),api:async()=>{calls++;return {ready:true,portraits:{8:{asset_id:'exact.png',x:0,y:0,zoom:1}}};},rerender(){throw Error('Input focus would be lost');}});
  ui.updatePortraitElements=()=>updates++;await ui.loadPortraits([row]);await ui.loadPortraits([row]);
  assert.equal(calls,1);assert.equal(updates,1);assert.match(ui.portraitImage(row),/exact.png/);
 }finally{globalThis.document=old;}
});

test('preparing game resources allows an unavailable coach portrait to retry',async()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{let key='missing',calls=0;const row={id:'8',type:'native'},ui=new CoachUI({catalog:{coaches:[row]},project:()=>({}),resourceKey:()=>key,api:async()=>{calls++;return key==='missing'?{ready:false,portraits:{}}:{ready:true,portraits:{8:{asset_id:'ready.png',x:0,y:0,zoom:1}}};}});
  ui.updatePortraitElements=()=>{};await ui.loadPortraits([row]);assert.match(ui.portraitImage(row),/暂未就绪/);await ui.loadPortraits([row]);assert.equal(calls,1);
  key='ready';await ui.loadPortraits([row]);assert.equal(calls,2);assert.match(ui.portraitImage(row),/ready.png/);
 }finally{globalThis.document=old;}
});

test('window unload sends latest project once and reload can register again',async()=>{
 const before={window:globalThis.window,navigator:globalThis.navigator};const handlers={},calls=[],beacons=[];
 globalThis.window={addEventListener:(name,handler)=>handlers[name]=handler};
 Object.defineProperty(globalThis,'navigator',{configurable:true,value:{sendBeacon:(url,body)=>{beacons.push({url,body});return true;}}});
 try{let project={package_id:'saved-player',identity:{name:'before'}};const session=new WindowSession(async(path,body)=>calls.push({path,body}),()=>project,'local-test-token');
  await session.start();project.identity.name='latest unsaved edit';handlers.beforeunload();handlers.pagehide();
  assert.equal(beacons.length,1);assert.equal(JSON.parse(await beacons[0].body.text()).project.identity.name,'latest unsaved edit');assert.match(beacons[0].url,/window\/close\?token=local-test-token/);
  handlers.pageshow({persisted:true});await Promise.resolve();assert.equal(calls.length,2);
 }finally{globalThis.window=before.window;Object.defineProperty(globalThis,'navigator',{configurable:true,value:before.navigator});}
});

test('reusing a shared booster in another slot preserves UUID and does not duplicate it',()=>{
 const old=globalThis.document;globalThis.document={addEventListener(){}};
 try{const project={custom_boosters:[],booster_ids:[0,0]},row={uuid:'shared',id:1000,label:'共享增能',effects:{34:3}};
  const ui=new BoosterLibraryUI({project:()=>project,commit:fn=>fn(),rerender(){},toast(){}});
  ui.attach(row,0);assert.equal(project.booster_ids[0],1000);ui.attach(row,1);assert.deepEqual(project.booster_ids,[0,1000]);assert.equal(project.custom_boosters.length,1);assert.equal(project.custom_boosters[0].uuid,'shared');
 }finally{globalThis.document=old;}
});

test('closing a large shared definition project transmits only the small unsaved delta',()=>{
 const before={custom_boosters:Array.from({length:10000},(_,id)=>({id,effects:{34:3}}))},after=structuredClone(before);
 after.custom_boosters[9999].effects[34]=7;const delta=windowDelta(before,after);
 assert.equal(delta.length,1);assert.equal(delta[0].value,7);assert.ok(JSON.stringify(delta).length<500);
});
