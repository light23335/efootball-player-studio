import test from 'node:test';import assert from 'node:assert/strict';
import {EditorAutosave,saveTarget,saveLabels} from '../web/editor-autosave.js';
import {skinToneLabels,bodyPanel} from '../web/body-ui.js';
const storage=()=>({setItem(){},removeItem(){}});
test('queued saves retain edits made while the previous request is in flight',async()=>{
 let value={uuid:'one',name:'A'},release;const calls=[];
 const saver=new EditorAutosave({read:()=>({coach:value}),storage:storage(),api:async(_path,row)=>{calls.push(structuredClone(row.value));if(calls.length===1)await new Promise(r=>release=r);return {committed:true};}});
 const running=saver.flush();await new Promise(r=>setTimeout(r,0));value.name='B';saver.capture();release();await running;
 assert.deepEqual(calls.map(v=>v.name),['A','B']);await saver.flush();assert.equal(calls.length,2);
});
test('a failed save stays retryable and newer data wins',async()=>{
 let value={uuid:'one',name:'A'},fail=true;const calls=[];
 const saver=new EditorAutosave({read:()=>({pack:value}),storage:storage(),api:async(_p,row)=>{if(fail)throw Error('offline');calls.push(row.value.name);return {committed:true};}});
 await assert.rejects(saver.flush());value.name='B';fail=false;await saver.flush();assert.deepEqual(calls,['B']);
});
test('contexts and six skin choices are explicit',()=>{
 assert.equal(saveLabels[saveTarget('coaches')],'保存教练');assert.equal(saveLabels[saveTarget('packs')],'保存卡包');assert.equal(saveLabels[saveTarget('skills')],'保存球员');
 assert.equal(skinToneLabels.length,6);const html=bodyPanel({model:{physique:{},skin_tone:3}},()=> '');
 assert.equal((html.match(/<option/g)||[]).length,6);assert.match(html,/3 · 中等肤色/);assert.doesNotMatch(html,/<option[^>]*disabled/);
});
