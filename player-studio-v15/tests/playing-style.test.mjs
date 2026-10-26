import test from 'node:test';
import assert from 'node:assert/strict';
import {styleCompatibility} from '../web/playing-style-ui.js';
test('playing-style position checks keep attacking and defending restrictions',()=>{
 assert.equal(styleCompatibility(1,'CF'),'compatible');
 assert.equal(styleCompatibility(1,'GK'),'incompatible');
 assert.equal(styleCompatibility(33,'GK'),'compatible');
 assert.equal(styleCompatibility(33,'CB'),'incompatible');
 assert.equal(styleCompatibility(0,'CMF'),'basic');
 assert.equal(styleCompatibility(999,'CF'),'unknown');
});
