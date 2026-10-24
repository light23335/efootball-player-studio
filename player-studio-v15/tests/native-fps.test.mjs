import test from 'node:test';
import assert from 'node:assert/strict';
import {NativePackageUI} from '../web/native-package-ui.js';

test('160 FPS export checkbox defaults off, survives rendering and submits a boolean',async()=>{
 const handlers={};const previous=globalThis.document;
 globalThis.document={addEventListener:(name,handler)=>handlers[name]=handler,querySelector:()=>null};
 try{
  const requests=[];const ui=new NativePackageUI({api:async(path,body)=>{requests.push({path,body});return{phase:'done'};},project:()=>({package_id:'sample'}),toast:()=>{}});
  ui.update=()=>{};ui.poll=()=>{};
  assert.match(ui.render(),/data-native-fps160 >强开 160 帧/);
  await ui.click({target:{closest:()=>({disabled:false,dataset:{},hasAttribute:name=>name==='data-native-build'})}});
  assert.equal(requests.at(-1).body.force_fps160,false);
  handlers.change({target:{dataset:{},checked:true,hasAttribute:name=>name==='data-native-fps160'}});
  assert.match(ui.render(),/data-native-fps160 checked/);
  await ui.click({target:{closest:()=>({disabled:false,dataset:{},hasAttribute:name=>name==='data-native-build'})}});
  assert.equal(requests.at(-1).body.force_fps160,true);
  handlers.change({target:{dataset:{},checked:false,hasAttribute:name=>name==='data-native-fps160'}});
  assert.equal(ui.forceFps160,false);
 }finally{globalThis.document=previous;}
});
