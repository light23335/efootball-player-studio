import test from 'node:test';
import assert from 'node:assert/strict';
import {pressedButtons,bindingText,STANDARD_BUTTONS} from '../web/game-settings.js';
test('physical button capture uses the standard controller layout and analog triggers',()=>{
 const buttons=Array.from({length:16},()=>({pressed:false,value:0}));buttons[5].pressed=true;buttons[1].value=1;
 assert.deepEqual(pressedButtons({buttons}),['B','RB']);assert.equal(bindingText(['RB','B']),'RB + B');
 buttons[5].pressed=false;buttons[1].value=0;buttons[6].value=.4;buttons[7].value=.8;
 assert.deepEqual(pressedButtons({buttons}),['LT','RT']);buttons[6].value=buttons[7].value=0;
 assert.deepEqual(pressedButtons({buttons}),[]);assert.equal(bindingText([]),'未绑定');
 assert.deepEqual(STANDARD_BUTTONS.slice(8,12),['SELECT','START','LS','RS']);
});
