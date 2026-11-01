import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import {normalizeBaseAbility}from '../web/base-abilities.js';
import {statGroups}from '../web/domain.js';
test('legacy level-one values clamp to 40/103 and valid values remain unchanged',()=>{
  for(const [value,expected]of [[0,40],[-10,40],[39,40],[40,40],[99,99],[103,103],[104,103],[105,103],[999,103],['105',103],['0',40]])assert.equal(normalizeBaseAbility(value),expected);
  for(const value of [null,undefined,'',false,{},NaN,Infinity])assert.equal(normalizeBaseAbility(value),65);
});
test('every base ability slider and number input has the same 40–103 bounds',()=>{
  const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
  const start=source.indexOf('function renderAbilities(){'),end=source.indexOf('\nfunction boosterLabel',start);
  const project={base_abilities:Object.fromEntries(statGroups.flatMap(g=>g.indices).map(k=>[k,65]))},catalog={ABILITIES:Object.fromEntries(Object.keys(project.base_abilities).map(k=>[k,'Ability '+k]))};
  const html=new Function('project','catalog','statGroups','abilityFilter','esc','icon',source.slice(start,end)+'\nreturn renderAbilities();')(project,catalog,statGroups,'all',String,()=> '');
  const inputs=html.match(/<input[^>]+data-bind="base_abilities\.[^"]+"[^>]*>/g);
  assert.equal(inputs.length,52);for(const input of inputs){assert.match(input,/min="40"/);assert.match(input,/max="103"/);assert.match(input,/step="1"/);}
  assert.match(html,/40–103/);assert.doesNotMatch(html,/1–105/);
  assert.match(source,/培养能力上限 105/);
});
