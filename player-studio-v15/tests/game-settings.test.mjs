import test from 'node:test';
import assert from 'node:assert/strict';
import {pressedButtons,bindingText,STANDARD_BUTTONS,updateControllerBinding,GameSettingsUI} from '../web/game-settings.js';

test('opponent system has an independent switch and keeps other AI preferences',()=>{
 const previous=globalThis.document,root={innerHTML:'',insertAdjacentHTML(_position,text){this.innerHTML=text+this.innerHTML;},append(node){this.innerHTML+=node.innerHTML;}};
 globalThis.document={querySelector:()=>root,createElement:()=>({innerHTML:'',querySelector:()=>({})})};
 try{
  const ui=new GameSettingsUI({});ui.drawBindings=()=>{};ui.schema={scopes:[]};
  ui.value={frame_rate:{enabled:false,target:160},display:{enabled:false,height:1080},controller:{preset:'default'},ai_cut_in_shots:{enabled:true}};
  ui.draw();assert.match(root.innerHTML,/data-game-enabled="ai_division_squads"/);
  root.onchange({target:{dataset:{gameEnabled:'ai_division_squads'},checked:false}});
  assert.equal(ui.value.ai_division_squads.enabled,false);assert.equal(ui.value.ai_cut_in_shots.enabled,true);
  root.onchange({target:{dataset:{gameEnabled:'action_trace'},checked:false}});
  assert.equal(ui.value.action_trace.enabled,false);assert.equal(ui.value.ai_cut_in_shots.enabled,true);
  ui.draw();assert.doesNotMatch(root.innerHTML,/data-game-enabled="ai_division_squads" checked/);
 }finally{globalThis.document=previous;}
});
test('physical button capture uses the standard controller layout and analog triggers',()=>{
 const buttons=Array.from({length:16},()=>({pressed:false,value:0}));buttons[5].pressed=true;buttons[1].value=1;
 assert.deepEqual(pressedButtons({buttons}),['B','RB']);assert.equal(bindingText(['RB','B']),'RB + B');
 buttons[5].pressed=false;buttons[1].value=0;buttons[6].value=.4;buttons[7].value=.8;
 assert.deepEqual(pressedButtons({buttons}),['LT','RT']);buttons[6].value=buttons[7].value=0;
 assert.deepEqual(pressedButtons({buttons}),[]);assert.equal(bindingText([]),'未绑定');
 assert.deepEqual(STANDARD_BUTTONS.slice(8,12),['SELECT','START','LS','RS']);
});

function controller(){return {manual_shortcuts:[],bindings:[
 {id:'attack.X',scope:'attack',input:['B'],output:['X']},
 {id:'attack.B',scope:'attack',input:['X'],output:['B']},
 {id:'attack.RB',scope:'attack',input:['LT'],output:['RB']},
 {id:'attack.finesse',scope:'attack',input:['RB','B'],output:['RB','X']},
 {id:'attack.stunning_loft',scope:'attack',input:['RT','X'],output:['RT','B']},
 {id:'defense.X',scope:'defense',input:['X'],output:['X']},
 ]};}
test('basic remaps update preset combinations without coupling attack and defense',()=>{
 const c=controller();updateControllerBinding(c,'attack.X',['Y']);
 assert.deepEqual(c.bindings.find(r=>r.id==='attack.finesse').input,['RB','Y']);
 assert.deepEqual(c.bindings.find(r=>r.id==='defense.X').input,['X']);
 updateControllerBinding(c,'attack.B',['A']);
 assert.deepEqual(c.bindings.find(r=>r.id==='attack.stunning_loft').input,['RT','A']);
 updateControllerBinding(c,'attack.RB',['LB']);
 assert.deepEqual(c.bindings.find(r=>r.id==='attack.finesse').input,['RB','Y']);
});
test('an explicitly edited shortcut survives future basic remaps and serialization',()=>{
 const c=controller();updateControllerBinding(c,'attack.finesse',['LS','B']);
 const reopened=JSON.parse(JSON.stringify(c));updateControllerBinding(reopened,'attack.X',['Y']);
 assert.deepEqual(reopened.bindings.find(r=>r.id==='attack.finesse').input,['LS','B']);
 assert.deepEqual(reopened.manual_shortcuts,['attack.finesse']);
});
