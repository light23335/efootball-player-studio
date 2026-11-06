import test from 'node:test';
import assert from 'node:assert/strict';
import {NativePackageUI} from '../web/native-package-ui.js';

function setup(platform='pc'){
  const previous=globalThis.document, nodes=new Map(), buttons=['build','first','companion'].map(kind=>({
    kind,disabled:true,dataset:{},hasAttribute:name=>name==='data-native-'+kind
  }));
  globalThis.document={addEventListener(){},querySelector(selector){
    if(selector.startsWith('[data-native-'))return buttons.find(b=>selector==='[data-native-'+b.kind+']')||null;
    if(!nodes.has(selector))nodes.set(selector,{});
    return nodes.get(selector);
  },querySelectorAll(selector){return selector.includes('[data-native-build]')?buttons.filter(b=>selector.includes('[data-native-'+b.kind+']')):[];}};
  const calls=[],ui=new NativePackageUI({platform,project:()=>({package_id:'blank-draft'}),toast(){},api:async(route,body)=>{
    calls.push({route,body});
    if(route==='native-apk/candidates')return {rows:[],coaches:[],packs:[],tournaments:[{uuid:'cup',name:'欧冠',teams:36}],write_source:{token:'verified',players:43}};
    if(route==='native-apk/start')return {phase:'working'};
    throw Error('Unexpected API '+route);
  }});
  ui.apk='source.apk';ui.initialized=true;ui.tournaments=[{uuid:'cup',name:'欧冠',teams:36}];ui.tournamentIds=new Set(['cup']);ui.poll=()=>{};
  return {ui,calls,buttons,nodes,restore(){globalThis.document=previous;}};
}
const click=button=>({target:{closest:()=>button}});

for(const platform of ['pc','android'])test(platform+': tournament-only export can verify a stale source and queue the game without selecting players',async()=>{
  const {ui,calls,buttons,restore}=setup(platform);
  try{
    ui.update();assert.equal(buttons[0].disabled,false,'must allow source recheck instead of silently staying grey');
    await ui.click(click(buttons[0]));
    assert.deepEqual(calls.map(c=>c.route),['native-apk/candidates','native-apk/start']);
    const body=calls[1].body;
    assert.deepEqual(body.selected_ids,[]);assert.deepEqual(body.coach_ids,[]);assert.deepEqual(body.pack_ids,[]);
    assert.deepEqual(body.tournament_ids,['cup']);assert.equal(body.write_source_token,'verified');
    assert.equal(body.project.package_id,'blank-draft');assert.equal(buttons[0].disabled,true);
  }finally{restore();}
});

test('candidate refresh locks export until the source proof arrives and then restores tournament-only export',async()=>{
  const {ui,buttons,restore}=setup();let finish;
  try{
    ui.api=()=>new Promise(resolve=>{finish=resolve;});
    const pending=ui.loadCandidates();ui.update();assert.equal(buttons[0].disabled,true);
    finish({rows:[],coaches:[],packs:[],tournaments:ui.tournaments,write_source:{token:'ready'}});
    await pending;assert.equal(buttons[0].disabled,false);assert.deepEqual([...ui.selected],[]);
  }finally{restore();}
});

test('failed source check stays actionable, explains the failure, and never starts the game or resource signer',async()=>{
  const {ui,calls,buttons,restore}=setup();
  try{
    ui.api=async route=>{calls.push({route});throw Error('来源 APK 不兼容，请重新选择');};
    ui.update();await ui.click(click(buttons[1]));
    assert.deepEqual(calls.map(c=>c.route),['native-apk/candidates']);assert.deepEqual(ui.queue,[]);
    assert.equal(ui.state.phase,'error');assert.match(ui.state.message,/来源 APK 不兼容/);
    assert.equal(buttons[0].disabled,false);assert.equal(ui.writeSource,null);
  }finally{restore();}
});

test('no source gives a visible selection instruction before any signer starts',async()=>{
  const {ui,calls,buttons,restore}=setup();
  try{ui.apk='';ui.update();await ui.click(click(buttons[0]));assert.equal(calls.length,0);assert.equal(ui.state.phase,'error');assert.match(ui.state.message,/游戏主 APK/);}
  finally{restore();}
});

test('tournament-only resource-first export validates its queued game body before signing resources',async()=>{
  const {ui,calls,buttons,restore}=setup();
  try{
    ui.companion='resource.apk';ui.update();await ui.click(click(buttons[1]));
    assert.deepEqual(calls.map(c=>c.route),['native-apk/candidates','native-apk/start']);
    assert.equal(calls[1].body.operation,'companion');assert.equal(ui.queue.length,1);
    assert.deepEqual(ui.queue[0].selected_ids,[]);assert.deepEqual(ui.queue[0].tournament_ids,['cup']);
  }finally{restore();}
});
