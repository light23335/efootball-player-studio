import test from 'node:test';
import assert from 'node:assert/strict';
import {OnboardingUI,navigationGroups,tutorialTopics} from '../web/onboarding-ui.js';
import {NativePackageUI} from '../web/native-package-ui.js';
import {playerLoadChoices} from '../web/player-prompts.js';
import {LibraryUI} from '../web/library-ui.js';

test('beginner navigation retains all editing and management pages',()=>{
 const all=navigationGroups.flatMap(([,pages])=>pages);
 for(const page of ['library','personal','profile','abilities','training','skills','card','model','packs','coaches','native','apk','tools','migration'])assert.ok(all.includes(page),page);
 assert.ok(tutorialTopics.length>=12);
});
test('home shows cache cleanup and tutorial search keeps relevant entries',()=>{
 const old=globalThis.document;globalThis.document={addEventListener:()=>{}};
 try{
  const ui=new OnboardingUI({mode:()=> 'simple'});assert.match(ui.render(),/id="home-cache"/);assert.match(ui.render(),/查看详细教程/);
  ui.query='签名';assert.match(ui.topics(),/覆盖安装与保留存档/);assert.doesNotMatch(ui.topics(),/头模、身高与装备/);
 }finally{globalThis.document=old;}
});
test('first coexist action queues game after resource and uses one consistent mode',async()=>{
 const old=globalThis.document;globalThis.document={addEventListener:()=>{}};
 try{
  const calls=[];const ui=new NativePackageUI({api:async(path,body)=>{calls.push(body);return{phase:'working'};},project:()=>({package_id:'x'}),installationMode:'coexist',toast:()=>{}});ui.update=()=>{};ui.poll=()=>{};
  await ui.click({target:{closest:()=>({dataset:{},hasAttribute:name=>name==='data-native-first'})}});
  assert.equal(calls[0].operation,'companion');assert.equal(calls[0].installation_mode,'coexist');assert.equal(ui.queue.length,1);assert.equal(ui.queue[0].installation_mode,'coexist');assert.equal(ui.queue[0].project.package_id,'x');
 }finally{globalThis.document=old;}
});
test('new slot is the recommended choice and overwrite is marked dangerous',()=>{
 assert.equal(playerLoadChoices(false)[0].id,'new');assert.equal(playerLoadChoices(false)[1].danger,true);assert.equal(playerLoadChoices(true)[0].id,'current');
});
test('canceling template load does not read a player or change the current slot',async()=>{
 const old=globalThis.document;globalThis.document={addEventListener:()=>{}};
 try{
  let calls=0;const project={package_id:'existing'};
  const ui=new LibraryUI({project:()=>project,beforeLoadPlayer:async()=>false,api:async()=>{calls++;},toast:()=>{}});
  await ui.loadPlayer('7511');assert.equal(calls,0);assert.equal(project.package_id,'existing');
 }finally{globalThis.document=old;}
});
