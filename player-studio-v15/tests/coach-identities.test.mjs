import test from 'node:test';
import assert from 'node:assert/strict';
import {coachIdentity,identityLabel,identityMatches} from '../web/coach-identities.js';
import {CoachUI} from '../web/coach-ui.js';
const options={nation:[{id:210,name:'德国',name_en:'Germany'},{id:208,name:'法国',name_en:'France'}],team:[{id:103,name:'利物浦 红',name_en:'Liverpool R'},{id:101,name:'阿森纳',name_en:'Arsenal FC'}]};
test('native copy keeps exact country, club and original coach source',()=>{
 const source={id:'17605071047055',type:'native',nation_id:210,team_id:103};const before=structuredClone(source);
 assert.deepEqual(coachIdentity(source),{nation_id:210,team_id:103,native_source_id:'17605071047055'});assert.deepEqual(source,before);
 assert.equal(coachIdentity({...source,type:'custom',native_source_id:source.id}).native_source_id,source.id);
});
test('identity search supports Chinese, English and exact native identifiers',()=>{
 assert.equal(identityMatches(options,'nation','德')[0].id,210);assert.equal(identityMatches(options,'nation','germany')[0].id,210);
 assert.equal(identityMatches(options,'team','#103')[0].id,103);assert.equal(identityMatches(options,'team','Liverpool')[0].id,103);
 assert.deepEqual(identityMatches(options,'team','missing'),[]);
});
test('unavailable stock club and old unknown country are explicit rather than another template',()=>{
 assert.equal(identityLabel({team_id:0,team_source:'unavailable'},'team',options),'原包未提供俱乐部');
 assert.equal(identityLabel({nation_id:0,identity_available:false},'nation',options),'国籍未读取');
 assert.equal(identityLabel({team_id:103},'team',options),'利物浦 红');
 assert.match(identityLabel({team_id:999},'team',options),/999/);
});
test('blank drafts stay unassigned and explicit zero does not inherit an owned club',()=>{
 assert.deepEqual(coachIdentity(),{nation_id:0,team_id:0,native_source_id:null});
 assert.equal(coachIdentity({team_id:0,raw_payload:{initial_base_team_id:103}}).team_id,0);
});
test('typing an identity query updates only results and does not rerender the form',()=>{
 const original=globalThis.document,events={},results={innerHTML:''},field={id:'coach-identity-query-nation',type:'search',value:'Fra',dataset:{coachIdentityQuery:'nation'}};
 let renders=0;globalThis.document={addEventListener:(name,fn)=>events[name]=fn,querySelector:selector=>selector==='#coach-identity-results-nation'?results:null,activeElement:field};
 try{
  const ui=new CoachUI({catalog:{},identities:()=>options,rerender:()=>renders++});ui.editing={name:'Keep this name',nation_id:210,team_id:103};events.input({target:field});
  assert.equal(renders,0);assert.equal(globalThis.document.activeElement,field);assert.equal(ui.editing.name,'Keep this name');assert.match(results.innerHTML,/France/);assert.equal(ui.identityQueries.nation,'Fra');
 }finally{globalThis.document=original;}
});
