import test from 'node:test';
import assert from 'node:assert/strict';
import {miniOverlayState,prepareMiniOverlay} from '../web/thumbnail-overlay.js';

test('mini overlay uses live position and simulated overall with club priority',()=>{
 const project={identity:{position:'AMF'},native_card:{info:{overall:97,assets:{club:{asset_id:'club'},nation:{asset_id:'nation'}}}}};
 const before=JSON.stringify(project),state=miniOverlayState(project,{ovr:111,baseOvr:101});
 assert.equal(state.position,'AMF');assert.equal(state.overall,111);assert.equal(state.emblem.asset_id,'club');assert.equal(state.boosted,true);
 assert.equal(JSON.stringify(project),before);
 assert.equal(miniOverlayState({identity:{position:'CF'}},{}).overall,'');
});

test('mini position and overall draw on their own overlay without changing artwork',async()=>{
 globalThis.document={querySelector:()=>({checked:true})};
 const calls=[],ctx={save(){},restore(){},scale(){},measureText:()=>({actualBoundingBoxAscent:30,actualBoundingBoxDescent:4}),strokeText(){},fillText:(...v)=>calls.push(v)};
 const draw=await prepareMiniOverlay({identity:{position:'CF'}},{ovr:112,baseOvr:90});draw(ctx);
 assert.deepEqual(calls.map(v=>v[0]),['CF','112']);assert.equal(ctx.fillStyle,'#ffff00');
 calls.length=0;document.querySelector=()=>({checked:false});draw(ctx);assert.deepEqual(calls,[]);
 delete globalThis.document;
});
