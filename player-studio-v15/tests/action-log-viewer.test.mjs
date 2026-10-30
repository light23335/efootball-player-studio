import test from 'node:test';
import assert from 'node:assert/strict';
import {readActionLog,filterActions,actionRow} from '../web/action-log-viewer.js';
const row=(n,extra={})=>({event:'action_change',sequence:n,team:0,slot:7,team_slot:7,player_id:123,player_name:'Mohamed Salah',action:{id:10,name:'控制射门'},request:{id:25,subtype:1,name:'控制射门'},skills:['弧线落叶射门'],...extra});
test('log import streams all rows but retains only bounded recent history',async()=>{
 const text=[{event:'trace_header',version:1},...Array.from({length:20},(_,i)=>row(i+1))].map(JSON.stringify).join('\n')+'\ninvalid\n';
 const value=await readActionLog(new Blob([text]),5);
 assert.equal(value.total,20);assert.equal(value.invalid,1);assert.equal(value.retained,5);
 assert.deepEqual(value.rows.map(r=>r.sequence),[16,17,18,19,20]);
});
test('name, player ID, team and action filters do not modify original records',()=>{
 const rows=[row(1),row(2,{team:1,player_name:'Henry',player_id:456}),row(3,{event:'motion_selection'})];
 assert.equal(filterActions(rows,'salah','0','action_change').length,1);
 assert.equal(filterActions(rows,'456','1').length,1);assert.equal(rows.length,3);
});
test('log text cannot create HTML and missing events stay visibly marked',()=>{
 const html=actionRow(row(1,{player_name:'<img src=x onerror=alert(1)>'}));
 assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));
 assert.ok(actionRow({event:'trace_contention',count_is_lower_bound:true}).includes('未计数'));
});
test('v2 zero-event diagnostics and match metadata remain readable',async()=>{
 const text=[{event:'trace_header',version:2},{event:'trace_heartbeat',native:{published:0,sources:{action_change:{entered:0}}}},{event:'native_diagnostic',diagnostic:{reason:'identity_mismatch'}},{event:'match_end',game_id:123}].map(JSON.stringify).join('\n');
 const value=await readActionLog(new Blob([text]));assert.equal(value.invalid,0);assert.equal(value.total,3);
 assert.ok(actionRow(value.rows[0]).includes('采集心跳'));assert.ok(actionRow(value.rows[1]).includes('identity_mismatch'));
});
test('v3 dribble decision and movement samples are readable and filterable',async()=>{
 const events=[{event:'trace_header',version:3},row(1,{event:'ai_candidate_choice',candidate:{original_name:'传球',selected_name:'盘带',changed:true}}),row(2,{event:'movement_sample',position:[25,0,12]})];
 const value=await readActionLog(new Blob([events.map(JSON.stringify).join('\n')]));
 assert.equal(value.invalid,0);assert.equal(value.total,2);
 assert.ok(actionRow(value.rows[0]).includes('传球 → 盘带'));
 assert.equal(filterActions(value.rows,'盘带','','ai_candidate_choice').length,1);
 assert.ok(actionRow(value.rows[1]).includes('移动轨迹'));
});
