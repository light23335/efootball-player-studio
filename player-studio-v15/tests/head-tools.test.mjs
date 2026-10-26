import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {HeadTools} from '../web/head-tools.js';

test('mouth testing uses source weights while expression protection remains set',()=>{
  const tools=new HeadTools({}, {anchors:{}});
  tools.actual=new THREE.Group();tools.raw=new THREE.Group();tools.reference=new THREE.Group();
  tools.project={model:{preserve_expression:true}};
  tools.setTest({jaw:1});assert.equal(tools.raw.visible,true);assert.equal(tools.actual.visible,false);
  tools.setTest({jaw:0});assert.equal(tools.raw.visible,false);assert.equal(tools.actual.visible,true);
  assert.equal(tools.project.model.preserve_expression,true);
});

test('a rotated native jaw pivots down in head coordinates rather than sideways',()=>{
  const tools=new HeadTools({}, {anchors:{}}),bone=new THREE.Bone();bone.name='skf_jaw';
  bone.quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),Math.PI/2);
  const quaternion=bone.quaternion.clone(),bind=new THREE.Matrix4().makeRotationFromQuaternion(quaternion).invert();
  tools.base.set('mesh',[{bone,quaternion,axis:new THREE.Vector3(1,0,0).transformDirection(bind)}]);
  const before=new THREE.Vector3(0,0,.1).applyQuaternion(quaternion);
  tools.test.jaw=1;tools.applyTest();const after=new THREE.Vector3(0,0,.1).applyQuaternion(bone.quaternion);
  assert.ok(after.y<before.y-.02);assert.ok(Math.abs(after.x-before.x)<1e-6);
  tools.test.jaw=0;tools.applyTest();assert.ok(bone.quaternion.angleTo(quaternion)<1e-6);
});
