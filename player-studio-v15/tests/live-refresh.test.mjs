import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {normalizeTraining,simulate,ratingColor,trainingCost} from '../web/domain.js';

const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const catalog=JSON.parse(readFileSync(new URL('../resources/catalog.json',import.meta.url)));
const extract=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
function fixture(){
  const project={package_id:'same-player',identity:{position:'CF',number:7},weekly_condition:'B',max_level:25,initial_level:60,
    card_type:'Epic',appearance:{},model:{},training:Object.fromEntries(catalog.training_groups.map(g=>[g.id,0])),
    base_abilities:Object.fromEntries(Object.keys(catalog.ABILITIES).map(k=>[k,65])),booster_ids:[]};
  const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,{style:{},classList:{toggle(){}}});return nodes.get(id);};
  let normalized=0,saves=0,reads=0,lastSeen;
  const context=vm.createContext({project,catalog,normalizeTraining:(...args)=>{normalized++;return normalizeTraining(...args);},
    simulate,ratingColor,trainingCost,normalizedTrainingOwner:null,simulation:null,
    $:id=>id==='#budget-card'?null:node(id),$$:()=>[],document:{querySelectorAll:()=>[]},
    syncStyleHelp(){},coachUI:null,updateRadar(){},drawCard(){},drawThumbnail(){},viewer:null,api(){},esc:String,
    clone:structuredClone,performance,past:[],future:[],lastChangeKey:'',lastChangeTime:0,version:0,
    scheduleSave:()=>saves++,updateUndo(){},libraryUI:{scheduleCardInfo(){if(lastSeen!==context.project){lastSeen=context.project;reads++;}}}});
  vm.runInContext(extract('function sixStats(','function updateRadar(')+extract('function commit(','function scheduleSave('),context);
  return {context,project,counts:()=>({normalized,saves,reads})};
}
test('actual updateLive preserves project/training identity and never saves on repeated refresh',()=>{
  const f=fixture(),training=f.project.training,identity=f.project.identity;
  for(let i=0;i<200;i++){vm.runInContext('updateLive();libraryUI.scheduleCardInfo()',f.context);}
  assert.equal(f.context.project,f.project);assert.equal(f.project.training,training);assert.equal(f.project.identity,identity);
  assert.deepEqual(f.counts(),{normalized:1,saves:0,reads:1});assert.equal(f.project.initial_level,25);
  assert.equal(f.project.identity.number,7);assert.equal(f.project.weekly_condition,'B');
});
test('actual commit plus refresh does not look like switching players during number and weekly edits',()=>{
  const f=fixture(),training=f.project.training;
  vm.runInContext('updateLive();libraryUI.scheduleCardInfo()',f.context);
  for(const number of [1,12,123]){
    f.context.typedNumber=number;
    vm.runInContext('commit(()=>project.identity.number=typedNumber,"identity.number");for(let i=0;i<20;i++)updateLive()',f.context);
    assert.equal(f.context.project,f.project);assert.equal(f.project.identity.number,number);assert.equal(f.project.training,training);
  }
  vm.runInContext('commit(()=>project.weekly_condition="A","weekly_condition");for(let i=0;i<20;i++)updateLive()',f.context);
  assert.equal(f.project.weekly_condition,'A');assert.deepEqual(f.counts(),{normalized:5,saves:4,reads:1});
  f.context.project={...f.project,package_id:'another-player',training:{...training}};
  vm.runInContext('updateLive();libraryUI.scheduleCardInfo();updateLive()',f.context);
  assert.deepEqual(f.counts(),{normalized:6,saves:4,reads:2});
});
