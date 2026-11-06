import test from 'node:test';
import assert from 'node:assert/strict';
import {WorldUI} from '../web/world-ui.js';

test('stand editor separates the native giant poster from the unavailable audience-card feature',()=>{
 const html=WorldUI.prototype.stand({stand_tifo:{asset:'photo.png',name:'Photo',layout:'poster'}},'stadium.slots.0');
 assert.match(html,/value="poster" selected>巨幅海报（整图）/);
 assert.match(html,/value="crowd" disabled>观众逐人举牌拼图（暂未接通）/);
 assert.doesNotMatch(html,/value="mosaic"|色块海报/);
 assert.match(html,/独立 GLB 预览，支持双面与透明遮罩/);
 assert.match(html,/旗手、拱门、地毯等部件保持一致/);
});

test('removed layouts display as a whole poster and the empty state states the audience feature gap',()=>{
 const html=WorldUI.prototype.stand({stand_tifo:{asset:'photo.png',name:'Old',layout:'mosaic'}},'stadium.slots.0');
 assert.match(html,/value="poster" selected>巨幅海报（整图）/);
 assert.doesNotMatch(html,/value="mosaic"|色块海报/);
 assert.match(WorldUI.prototype.stand({stand_tifo:null},'stadium.slots.0'),/观众逐人举牌拼图尚未接通/);
});
