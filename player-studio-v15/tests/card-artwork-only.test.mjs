import test from 'node:test';
import assert from 'node:assert/strict';
import {cardFrontLayers,NativeCardRenderer} from '../web/native-card.js';

test('artwork-only keeps background, animation and portrait but removes baked date and signature layers',()=>{
  const card={layers:['f01','f02','f03','f04','f05','f06','f07','f09','f10','m01','b01'].map(slot=>({slot,asset_id:slot,kind:slot==='f02'?'video':'image'}))};
  const visible=cardFrontLayers(card,{portrait:'photo',hide_card_ui:true});
  assert.deepEqual(new Set(visible.map(x=>x.slot)),new Set(['f01','f02','f03','f04','f05','f07','f10','portrait']));
  assert.equal(visible.find(x=>x.slot==='portrait').asset_id,'photo');
  assert.ok(cardFrontLayers(card,{portrait:'photo'}).some(x=>x.slot==='f09'));
  assert.ok(!cardFrontLayers(card,{portrait:'photo',hide_portrait:true,hide_card_ui:true}).some(x=>x.slot==='portrait'));
});
test('custom movies keep playing under artwork-only, with portrait on top',()=>{
  const card={custom_motion:{large:{preview:{asset_id:'movie'}}},layers:[]};
  assert.deepEqual(cardFrontLayers(card,{hide_card_ui:true,portrait:'photo'}).map(x=>[x.slot,x.kind]),[['f02','video'],['portrait','image']]);
});
test('renderer draws the same artwork canvas used for PNG without generating UI text or badges',()=>{
  const calls=[],ctx={setTransform(){},clearRect(){},save(){},scale(){},restore(){},drawImage(...a){calls.push(['image',...a]);},fillText(){throw Error('UI text was drawn');}};
  const canvas={width:1200,height:1720,dataset:{},getContext(){return ctx;}};
  const renderer=new NativeCardRenderer(canvas,()=>{});
  renderer.project={native_card:{source_id:'1',layout:{width:600,height:860}},appearance:{hide_card_ui:true,portrait:'photo'}};
  renderer.resources=[{slot:'f02',kind:'image',element:{width:600,height:860}},{slot:'portrait',kind:'image',element:{width:600,height:860}}];
  renderer.draw();assert.equal(calls.length,2);assert.equal(JSON.parse(canvas.dataset.nativeUiElements).hidden,true);
});
