import test from 'node:test';
import assert from 'node:assert/strict';
import {styleCompatibility,renderStyleHelp} from '../web/playing-style-ui.js';
import fs from 'node:fs';
test('playing-style position checks keep attacking and defending restrictions',()=>{
 assert.equal(styleCompatibility(1,'CF'),'compatible');
 assert.equal(styleCompatibility(1,'GK'),'incompatible');
 assert.equal(styleCompatibility(33,'GK'),'compatible');
 assert.equal(styleCompatibility(33,'CB'),'incompatible');
 assert.equal(styleCompatibility(0,'CMF'),'basic');
 assert.equal(styleCompatibility(999,'CF'),'unknown');
});

test('every verified native playing style is selectable with correct compatible positions',()=>{
 const catalog=JSON.parse(fs.readFileSync(new URL('../resources/catalog.json',import.meta.url)));
 const rows=JSON.parse(fs.readFileSync(new URL('../resources/native-playing-styles.json',import.meta.url))).rows;
 assert.equal(rows.length,35);
 for(const row of rows){
  assert.ok(catalog.PLAY_STYLES[row.phase][row.id]);
  for(const position of catalog.POSITIONS)assert.equal(styleCompatibility(row.id,position),row.positions.includes(position)?'compatible':'incompatible');
 }
 const calls=[];const html=renderStyleHelp({package_id:'style-test',identity:{position:'CF'}},catalog,(path,label,type,options)=>{calls.push({path,choices:options.choices});return '<select></select>';});
 const attack=calls.find(c=>c.path==='play_style.attack').choices;
 assert.ok(attack.some(([id,name])=>id==='22'&&name.includes('站桩式中锋')&&name.includes('CF')));
 assert.ok(attack.some(([id,name])=>id==='35'&&name.includes('高位防线门将')&&name.includes('GK')));
 assert.match(html,/查看全部比赛风格与触发位置/);
 assert.match(html,/站桩式中锋/);assert.match(html,/高位防线门将/);
});
