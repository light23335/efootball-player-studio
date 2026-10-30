import test from 'node:test';
import assert from 'node:assert/strict';
import {PlayerFoldersUI} from '../web/player-folders.js';

test('older folder response cannot override a newer category selection',async()=>{
  const pending=[];let paints=0;
  const state={sequence:0,selected:'one',api:()=>new Promise(resolve=>pending.push(resolve)),paint(){paints++;}};
  const first=PlayerFoldersUI.prototype.load.call(state),second=PlayerFoldersUI.prototype.load.call(state);
  pending[1]({rows:[{id:'one',name:'New',count:2}],all_count:2,unfiled_count:0});await second;
  pending[0]({rows:[{id:'old',name:'Old',count:1}]});await first;
  assert.equal(state.rows[0].name,'New');assert.equal(state.selected,'one');assert.equal(paints,1);
});

test('a deleted folder falls back to all players rather than hiding the library',async()=>{
  const state={sequence:0,selected:'deleted',api:async()=>({rows:[],all_count:2,unfiled_count:2}),paint(){}};
  await PlayerFoldersUI.prototype.load.call(state);assert.equal(state.selected,'');assert.equal(state.error,'');
});

test('corrupt folder metadata does not prevent browsing all saved players',async()=>{
  const state={sequence:0,selected:'one',api:async()=>{throw new Error('index damaged');},paint(){}};
  await PlayerFoldersUI.prototype.load.call(state);assert.equal(state.selected,'');assert.match(state.error,/index damaged/);
});

test('remove from folder never calls player deletion',async()=>{
  const calls=[];const state={selected:'one',api:async(path,body)=>calls.push({path,body}),changed:async()=>{},toast(){}};
  await PlayerFoldersUI.prototype.removePlayer.call(state,'player');
  assert.equal(calls[0].path,'players/folders/remove');assert.deepEqual(calls[0].body,{folder_id:'one',player_ids:['player']});
});
