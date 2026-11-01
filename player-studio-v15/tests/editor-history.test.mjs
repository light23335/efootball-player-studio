import test from 'node:test';
import assert from 'node:assert/strict';
import {DraftHistory,activeHistory,historyShortcut} from '../web/editor-history.js';
import {PackUI} from '../web/pack-ui.js';
import {EditorAutosave} from '../web/editor-autosave.js';

function fixture(value={uuid:'a',name:'original',members:[]}){
  let current=structuredClone(value),time=0;
  const history=new DraftHistory({read:()=>current,write:v=>current=v,clock:()=>time});
  return {history,get value(){return current;},set value(v){current=v;},tick:n=>time+=n};
}
test('draft histories isolate permanent identities and do not undo another editor',()=>{
  const pack=fixture(),coach=fixture({uuid:'coach',name:'Coach'}),player={};
  pack.history.commit(()=>pack.value.name='Pack');coach.history.commit(()=>coach.value.name='New coach');
  activeHistory('packs',{pack:pack.history,coach:coach.history,player}).undo();
  assert.equal(pack.value.name,'original');assert.equal(coach.value.name,'New coach');
  assert.equal(activeHistory('tools',{pack,coach,player}),null);
  pack.value={uuid:'different',name:'Untouched'};assert.equal(pack.history.canUndo,false);assert.equal(pack.history.canRedo,false);
});
test('undo/redo restores whole pool, exact weights and cover; new branch invalidates redo',()=>{
  const f=fixture(),h=f.history;
  h.commit(()=>f.value.members.push({kind:'original',id:'1',weight:7}));
  h.commit(()=>f.value.cover={asset_id:'image.png',x:25,zoom:2});
  h.commit(()=>f.value.members=[]);h.undo();assert.equal(f.value.members[0].weight,7);
  h.undo();assert.equal(f.value.cover,undefined);h.redo();assert.equal(f.value.cover.x,25);
  h.commit(()=>f.value.name='branch');assert.equal(h.canRedo,false);
});
test('typing groups only consecutive edits of one field; discrete actions and focus breaks remain separate',()=>{
  const f=fixture(),h=f.history;
  h.commit(()=>f.value.name='A','name');f.tick(100);h.commit(()=>f.value.name='AB','name');
  h.commit(()=>f.value.members.push({id:'one'}));h.commit(()=>f.value.members.push({id:'two'}));
  h.undo();assert.deepEqual(f.value.members,[{id:'one'}]);h.undo();h.undo();assert.equal(f.value.name,'original');
  h.redo();h.endGroup();h.commit(()=>f.value.name='C','name');h.undo();assert.equal(f.value.name,'AB');
});
test('no-op and failed edits do not destroy redo or leave a partially changed draft',()=>{
  const f=fixture(),h=f.history;h.commit(()=>f.value.name='new');h.undo();
  h.commit(()=>f.value.name='original');assert.equal(h.canRedo,true);
  assert.throws(()=>h.commit(()=>{f.value.name='broken';throw Error('validation');}));
  assert.equal(f.value.name,'original');assert.equal(h.canRedo,true);
});
test('history is bounded without restricting the size of the current card pool',()=>{
  const f=fixture();for(let i=0;i<75;i++)f.history.commit(()=>f.value.members.push({id:i}));
  assert.equal(f.history.past.length,60);for(let i=0;i<60;i++)f.history.undo();assert.equal(f.value.members.length,15);
});
test('keyboard shortcuts route editable draft fields, preserve native search undo and support redo on Windows/macOS',()=>{
  const field={tagName:'INPUT',matches:()=>true},search={tagName:'INPUT',matches:()=>false};
  assert.equal(historyShortcut({ctrlKey:true,key:'z',target:field}),'undo');
  assert.equal(historyShortcut({metaKey:true,shiftKey:true,key:'Z',target:field}),'redo');
  assert.equal(historyShortcut({ctrlKey:true,key:'y',target:{tagName:'BODY'}}),'redo');
  assert.equal(historyShortcut({ctrlKey:true,key:'z',target:search}),null);
});
test('pack bulk additions and special clear/restore actions also enter normal undo history',()=>{
  const savedDocument=globalThis.document;globalThis.document={querySelector:()=>({textContent:'',disabled:false})};
  try{
    const state=Object.assign(Object.create(PackUI.prototype),{editing:{uuid:'pack',name:'pack',members:[]},members(){},rerender(){},toast(){}});
    state.add({kind:'custom',id:'one',name:'One'});state.change(()=>state.editing.members[0].weight=8);
    state.clearMembers();assert.equal(state.editing.members.length,0);state.restoreMembers();assert.equal(state.editing.members[0].weight,8);
    state.history.undo();assert.equal(state.editing.members.length,0);state.history.undo();assert.equal(state.editing.members[0].weight,8);
    state.history.undo();assert.equal(state.editing.members[0].weight,1);state.history.undo();assert.equal(state.editing.members.length,0);
    state.history.redo();assert.equal(state.editing.members[0].id,'one');
  }finally{globalThis.document=savedDocument;}
});
test('undo to an in-flight draft discards a newer queued edit instead of saving it later',async()=>{
  let value={uuid:'pack',name:'A'},release;const calls=[];
  const saver=new EditorAutosave({read:()=>({pack:value}),storage:{setItem(){},removeItem(){}},api:async(_p,row)=>{calls.push(row.value.name);if(calls.length===1)await new Promise(r=>release=r);return{committed:true};}});
  const first=saver.flush();await new Promise(r=>setTimeout(r,0));value.name='B';saver.capture();value.name='A';saver.capture();release();await first;
  assert.deepEqual(calls,['A']);assert.equal(saver.pending.size,0);
});
test('undo while a newer save is in flight queues the restored value last',async()=>{
  let value={uuid:'pack',name:'A'},release;const calls=[];
  const saver=new EditorAutosave({read:()=>({pack:value}),storage:{setItem(){},removeItem(){}},api:async(_p,row)=>{calls.push(row.value.name);if(calls.length===2)await new Promise(r=>release=r);return{committed:true};}});
  await saver.flush();value.name='B';const second=saver.flush();await new Promise(r=>setTimeout(r,0));value.name='A';saver.capture();release();await second;
  assert.deepEqual(calls,['A','B','A']);
});
