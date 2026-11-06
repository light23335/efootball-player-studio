import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {HeadTools} from '../web/head-tools.js';
import {expressionPanel,expressionSpec,previewModel,applyExpressionTest} from '../web/coach-expression.js';

test('coach expression controls preserve the saved switch while real jaw and eyelid bones move',()=>{
 const viewer={controls:{},setHeadTest(values){tools.setTest(values);}},tools=new HeadTools(viewer,{anchors:{}});viewer.headTools=tools;
 tools.actual=new THREE.Group();tools.raw=new THREE.Group();tools.reference=new THREE.Group();
 const jaw=new THREE.Bone(),eye=new THREE.Bone();jaw.name='skf_jaw';eye.name='skf_eyelid_t_l';tools.raw.add(jaw,eye);
 tools.base.set('skin',[jaw,eye].map(bone=>({bone,quaternion:bone.quaternion.clone(),axis:new THREE.Vector3(1,0,0)})));
 const saved={model:{preserve_expression:true}};tools.project=saved;const notice={};
 applyExpressionTest(viewer,{jaw:1,blink:1},notice);
 assert.ok(jaw.quaternion.angleTo(new THREE.Quaternion())>.4);assert.ok(eye.quaternion.angleTo(new THREE.Quaternion())>.2);
 assert.equal(tools.raw.visible,true);assert.equal(tools.actual.visible,false);assert.equal(saved.model.preserve_expression,true);
 applyExpressionTest(viewer,{jaw:0,blink:0},notice);
 assert.ok(jaw.quaternion.angleTo(new THREE.Quaternion())<1e-6);assert.ok(eye.quaternion.angleTo(new THREE.Quaternion())<1e-6);
 assert.equal(tools.actual.visible,true);assert.equal(tools.raw.visible,false);assert.equal(saved.model.preserve_expression,true);
});

test('missing coach facial skeleton is reported and each editor has its own controls',()=>{
 const notice={};applyExpressionTest({setHeadTest(){}},{jaw:1,blink:1},notice);assert.match(notice.textContent,/没有可用/);
 for(const scope of ['personal','stock']){const html=expressionPanel(scope,true,true,{jaw:.5,blink:.75});
  assert.match(html,new RegExp('data-coach-expression="'+scope+'" checked'));assert.match(html,/张嘴检查/);assert.match(html,/闭眼检查/);
  assert.doesNotMatch(html,/data-bind="model\./);
 }
});

test('coach preview always uses returned cooked and original-weight URLs without player fitting',()=>{
 const r={asset_id:'cooked.glb',url:'/cooked.glb',report:{mode:'custom'},head_preview:{export_url:'/cooked.glb',raw_url:'/raw.glb',anchors:{}}};
 assert.equal(expressionSpec(r),r.head_preview);assert.equal(previewModel(r,true).model.preserve_expression,true);
 assert.equal(previewModel(r,true).model.native_source,null);assert.equal(previewModel(r,true).model.neck_seam,false);
 assert.deepEqual(expressionSpec({url:'/native.glb'}).raw_url,'/native.glb');
});
