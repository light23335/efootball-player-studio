import test from 'node:test';
import assert from 'node:assert/strict';
import {setTeamOptions,teamLabel,identitySelection} from '../web/team-identities.js';
import {filteredTeams} from '../web/world-ui.js';
import {identityMatches} from '../web/coach-identities.js';
const options={team:[{id:173,name:'曼城',name_en:'Manchester City',source_name:'曼彻斯特 蓝',source_name_en:'Manchester B',aliases:['曼彻斯特 蓝','Manchester B']},{id:109,name:'皇家马德里',name_en:'Real Madrid',source_name:'马德里查马丁 白'}]};
test('real labels render without migrating a project; selecting same ID preserves original text',()=>{
 const identity={team_id:173,team:'曼彻斯特 蓝'},old=structuredClone(identity);setTeamOptions(options.team);
 assert.equal(teamLabel(identity),'曼城');assert.deepEqual(identity,old);
 for(const value of ['曼城','Manchester City','曼城 · #173','Manchester B']){
  const selected=identitySelection(value,'team',options,identity);assert.equal(selected.stored,'曼彻斯特 蓝');assert.equal(selected.id,173);assert.deepEqual(identity,old);
 }
 const changed=identitySelection('皇家马德里 · #109','team',options,identity);assert.equal(changed.id,109);assert.equal(changed.stored,'马德里查马丁 白');
});
test('tournament and coach searches retain old aliases as well as real names',()=>{
 assert.equal(filteredTeams(options.team,'曼城')[0].id,173);assert.equal(filteredTeams(options.team,'Manchester B')[0].id,173);
 assert.equal(identityMatches(options,'team','City')[0].id,173);assert.equal(identityMatches(options,'team','曼彻斯特')[0].id,173);
});
