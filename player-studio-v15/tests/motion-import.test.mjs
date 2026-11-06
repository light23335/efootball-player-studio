import test from 'node:test';
import assert from 'node:assert/strict';
import {importCardMovie} from '../web/motion-import.js';
test('video HTTP requests are short and progress belongs to the original job',async()=>{
 const calls=[],states=[];const queue=[{phase:'working',job_id:'one'},{phase:'working',job_id:'one',frames:12},{phase:'done',job_id:'one',result:{mini:{asset_id:'good'}}}];
 const result=await importCardMovie(async(path,body)=>{calls.push([path,body]);return queue.shift();},{path:'video.mp4',role:'mini'},{pause:async()=>{},onState:s=>states.push(s)});
 assert.equal(result.mini.asset_id,'good');assert.equal(states[0].frames,undefined);assert.equal(states[1].frames,12);
 assert.deepEqual(calls.slice(1).map(c=>c[1]),[{job_id:'one'},{job_id:'one'}]);
});
test('cancel does not return a partial card replacement',async()=>{
 const q=[{phase:'working',job_id:'one'},{phase:'cancelled',job_id:'one',result:{mini:'partial'}}];
 assert.equal(await importCardMovie(async()=>q.shift(),{}, {pause:async()=>{}}),null);
});
test('encoder failure is reported and never applied',async()=>{
 const q=[{phase:'working',job_id:'one'},{phase:'error',job_id:'one',message:'unsupported encoder'}];
 await assert.rejects(importCardMovie(async()=>q.shift(),{}, {pause:async()=>{}}),/unsupported encoder/);
});
