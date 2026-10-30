import test from 'node:test';
import assert from 'node:assert/strict';
import {CoachHeads} from '../web/coach-heads.js';

globalThis.document={querySelector:()=>null};

test('no separate test workspace is displayed before a coach is selected',()=>{
  assert.equal(CoachHeads.prototype.render.call({open:false}),'');
});

test('browsing a personal coach passes its own identity and imported model',async()=>{
  const coach={id:'custom:one',type:'custom',name:'Mine',native_source_id:'437',head_model:{asset_id:'my.glb'}};
  const calls=[];
  const state={sequence:0,lookupCoach:id=>id===coach.id?coach:null,rerender(){},paint(){},
    api:async(path,body)=>{calls.push([path,body]);return {asset_id:'compiled.glb',template_path:'native',personal:true,head_model:body.coach.head_model};}};
  await CoachHeads.prototype.openFor.call(state,coach.id);
  assert.equal(calls[0][0],'coaches/model/current');assert.equal(calls[0][1].coach.id,coach.id);
  assert.equal(state.previewData.asset_id,'compiled.glb');assert.equal(state.target,'native');assert.equal(state.busy,false);
  assert.match(state.message,/上传/);
});

test('late preview of the previous coach cannot replace the current coach',async()=>{
  const pending=[];
  const state={sequence:0,lookupCoach:id=>({id,name:id,type:'custom'}),rerender(){},paint(){},
    api:()=>new Promise(resolve=>pending.push(resolve))};
  const first=CoachHeads.prototype.openFor.call(state,'custom:first');
  const second=CoachHeads.prototype.openFor.call(state,'custom:second');
  pending[1]({asset_id:'second.glb',template_path:'second',personal:true});await second;
  pending[0]({asset_id:'first.glb',template_path:'first',personal:true});await first;
  assert.equal(state.previewData.asset_id,'second.glb');assert.equal(state.currentCoach.id,'custom:second');
});
