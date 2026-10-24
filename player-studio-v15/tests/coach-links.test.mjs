import test from 'node:test';
import assert from 'node:assert/strict';
import {renderLinkups,updateLinkup,linkupText} from '../web/coach-links.js';

const type={template_id:8,label:'突破传球B',effect:3,source_positions:[2,3],target_positions:[12],source_style:7,target_style:1,coaches:['Beckenbauer']};
const catalog={POSITIONS:['GK','CB','LB','RB','DMF','CMF','LMF','RMF','AMF','LWF','RWF','SS','CF'],PLAY_STYLES:{attack:{0:'无风格',1:'偷猎者'},defense:{}},COACH_LINK_TYPES:[type],COACH_LINK_SCHEMA:{style_to_parameter:[0,1]}};
test('choosing an existing type copies editable conditions without sharing catalogue objects',()=>{
  const row={};assert.equal(updateLinkup(row,{dataset:{linkSlot:'0',linkField:'template_id'},value:'8'},[type]),'render');
  assert.equal(row.linkups[0].template_id,8);assert.equal(row.linkups[0].label,undefined);
  updateLinkup(row,{dataset:{linkSlot:'0',linkField:'position',linkRole:'source'},value:'0',checked:true},[type]);
  assert.deepEqual(row.linkups[0].source_positions,[0,2,3]);assert.deepEqual(type.source_positions,[2,3]);
  assert.match(renderLinkups(row,catalog),/门将/);assert.match(renderLinkups(row,catalog),/左边锋/);assert.match(linkupText(row,catalog),/GK\/LB\/RB/);
});
test('clearing one link preserves the other link and unsupported types cannot be introduced',()=>{
  const row={linkups:[structuredClone(type),structuredClone(type)]};
  updateLinkup(row,{dataset:{linkSlot:'0',linkField:'template_id'},value:''},[type]);assert.equal(row.linkups[0],null);assert.equal(row.linkups[1].template_id,8);
  updateLinkup(row,{dataset:{linkSlot:'0',linkField:'template_id'},value:'999'},[type]);assert.equal(row.linkups[0],null);
});
