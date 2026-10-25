import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {simulate,trainingCost,autoAllocate,selectCardType,selectCardSeries,coachFactor} from '../web/domain.js';
import {nativeCardState,cardLayerOrder} from '../web/native-card.js';
import {applyCardPreset,formatCardDate,originalCardDate} from '../web/card-design.js';
const catalog=JSON.parse(readFileSync(new URL('../resources/catalog.json',import.meta.url)));
catalog.coaches=JSON.parse(readFileSync(new URL('../resources/coaches.json',import.meta.url))).coaches;
function project(){return {identity:{position:'CF'},card_type:'Epic',initial_level:35,
  base_abilities:Object.fromEntries(Object.keys(catalog.ABILITIES).map(k=>[k,65])),
  training:Object.fromEntries(catalog.training_groups.map(g=>[g.id,0])),booster_ids:[0,0],conditional_boosters:false};}

test('replacement portrait is visible above opaque BT preset mechanics',()=>{
  const preset=JSON.parse(readFileSync(new URL('../resources/native-card-presets.json',import.meta.url))).rows.find(p=>p.id==='0228d3fa5b56402988236642');
  assert.ok(preset.layers.some(l=>l.slot==='f04'&&l.name==='0501_5_f04_lim'));
  const order=cardLayerOrder({preset_id:preset.id});
  const layers=[...preset.layers,{slot:'portrait'}].sort((a,b)=>order[a.slot]-order[b.slot]);
  assert.ok(layers.findIndex(l=>l.slot==='f04')<layers.findIndex(l=>l.slot==='portrait'));
  assert.ok(layers.findIndex(l=>l.slot==='f10')>layers.findIndex(l=>l.slot==='portrait'));
  assert.ok(cardLayerOrder({}).f04>cardLayerOrder({}).portrait);
});

test('original card states dispatch by native card art and booster slots',()=>{
  const ui=JSON.parse(readFileSync(new URL('../resources/native-card-widgets.json',import.meta.url)));
  for(const [kind,type] of Object.entries({Standard:0,Legendary:1,BigTime:5,Trending:3,Featured:4,Epic:1,Highlight:4})){
    const p=project();p.native_card={card_type:kind,native_agent:1,ui};
    let s=nativeCardState(p);assert.equal(s.type,type);
    assert.equal(s.widgets['Text_PlayerName_'+type].visible,true);
    assert.equal(Object.keys(s.widgets).filter(k=>k.startsWith('Text_PlayerName_')&&s.widgets[k].visible).length,1);
    p.source_player={original_payload:{initial_booster_id_list:[1,136,0]}};s=nativeCardState(p);
    assert.equal(s.slotCount,2);assert.equal(s.widgets.ScaleBox_RarityStar.Scale,.8);
  }
  const p=project();p.native_card={card_type:'Trending',native_agent:340,ui};
  assert.equal(nativeCardState(p).state,'PlayerType_3_BoosterNone');
});

test('blank presets preserve personal player data, portrait, model and training',()=>{
  const p=project();Object.assign(p,{package_id:'keep-uuid',max_level:39,source_player:{id:'original'},model:{asset:'own.glb'},native_art:{portrait:{kind:'personal-photo',asset_id:'own.png'},full:{asset_id:'old.png'}},appearance:{portrait:'own.png',photo_zoom:1.4,photo_x:20,photo_y:-6}});
  const before=structuredClone(p),preset={preset_id:'design-a',card_type:'BigTime',native_style:'0501',preset:{sample_date:'2002-06-21'}};
  applyCardPreset(p,preset);
  for(const key of ['package_id','identity','base_abilities','training','booster_ids','source_player','model','max_level'])assert.deepEqual(p[key],before[key]);
  for(const key of ['portrait','photo_zoom','photo_x','photo_y'])assert.equal(p.appearance[key],before.appearance[key]);
  assert.equal(p.appearance.card_date,'2002-06-21');assert.equal(p.native_art.full,null);assert.equal(p.native_art.portrait.asset_id,'own.png');
  p.appearance.card_date='1998-08-03';applyCardPreset(p,{...preset,preset_id:'design-b',preset:{sample_date:'2022-12-18'}});assert.equal(p.appearance.card_date,'1998-08-03');
  assert.equal(formatCardDate(p.appearance.card_date),"3 Aug '98");assert.equal(originalCardDate({source_label:"Big Time Brazil 21 Jun '02"}),'2002-06-21');
});

test('allocation target is independently selectable without changing main position',()=>{
 const p=project();p.identity.position='SS';p.preview={training_position:'GK'};
 const gk=autoAllocate(p,catalog);assert.ok(gk.GK1+gk.GK2+gk.GK3>0);assert.equal(p.identity.position,'SS');
 p.preview.training_position='CF';const cf=autoAllocate(p,catalog);assert.equal(cf.GK1+cf.GK2+cf.GK3,0);assert.notDeepEqual(gk,cf);assert.equal(p.identity.position,'SS');
});

test('custom booster effects, conditional switch and native ability caps',()=>{
  const p=project();p.custom_boosters=[{id:1000,label:'我的增能',effects:{20:7,34:-3},conditional:true}];p.booster_ids=[0,1000];
  assert.equal(simulate(p,catalog).boosted[20],65);p.conditional_boosters=true;
  assert.equal(simulate(p,catalog).boosted[20],72);assert.equal(simulate(p,catalog).boosted[34],62);
  p.base_abilities[20]=105;p.custom_boosters[0].effects[20]=20;assert.equal(simulate(p,catalog).boosted[20],125);
});
test('training costs cross native four-upgrade thresholds',()=>{
  assert.deepEqual([0,1,4,5,8,9,12].map(trainingCost),[0,1,4,6,12,15,24]);
});

test('Big Time and Epic select independently without changing training or player identity',()=>{
  const p=project();p.package_id='permanent';p.training.SHOOT=4;
  const before=simulate(p,catalog);
  selectCardType(p,'BigTime');assert.equal(p.card_series,'BigTime');
  assert.equal(p.package_id,'permanent');assert.deepEqual(simulate(p,catalog),before);
  selectCardType(p,'Epic');assert.equal(p.card_series,'Epic');
  selectCardSeries(p,'BigTime');assert.equal(p.card_type,'BigTime');
  selectCardSeries(p,'Epic');assert.equal(p.card_type,'Epic');
  assert.equal(p.training.SHOOT,4);
});
test('group allocation affects the exact native ability indices',()=>{
  const p=project();p.training.SHOOT=5;p.training.GK1=2;p.training.AERIAL=1;
  const s=simulate(p,catalog);assert.equal(s.trained[20],70);assert.equal(s.trained[27],70);
  assert.equal(s.trained[39],68);assert.equal(s.trained[16],67);assert.equal(s.trained[34],65);
  assert.equal(s.spent,9);assert.equal(s.remaining,59);
});
test('conditional boosters only apply when enabled',()=>{
  const p=project(),booster=catalog.boosters.find(b=>b.conditional&&Object.keys(b.effects).length);
  p.booster_ids=[0,booster.id];const off=simulate(p,catalog);p.conditional_boosters=true;const on=simulate(p,catalog);
  for(const [index,delta]of Object.entries(booster.effects))assert.equal(on.boosted[index]-off.boosted[index],delta);
});
test('auto allocation stays in budget at all supported levels and positions',()=>{
  for(const position of catalog.POSITIONS)for(const level of [1,2,10,35,50,61,80,100]){
    const p=project();p.initial_level=level;p.identity.position=position;p.training=autoAllocate(p,catalog);
    const s=simulate(p,catalog);assert.ok(s.spent<=2*(level-1));assert.ok(Object.values(s.trained).every(v=>v<=105));
    assert.equal(s.valid,true);
  }
});
test('trending has no ordinary training points and over-allocation stays visible',()=>{
  const p=project();p.card_type='Trending';p.training.SHOOT=1;const s=simulate(p,catalog);
  assert.equal(s.budget,0);assert.equal(s.remaining,-1);assert.equal(s.valid,false);
});
test('native position priorities keep outfield players out of goalkeeper training',()=>{
  for(const position of catalog.POSITIONS.filter(p=>p!=='GK')){
    const p=project();p.identity.position=position;const allocation=autoAllocate(p,catalog);
    assert.equal(allocation.GK1+allocation.GK2+allocation.GK3,0);
  }
  const p=project();p.identity.position='GK';const allocation=autoAllocate(p,catalog);
  assert.equal(allocation.SHOOT+allocation.PASS+allocation.DRIBLE+allocation.DEFENCE,0);
  assert.ok(allocation.GK1+allocation.GK2+allocation.GK3>0);
});

test('native and custom coaches alter the preview without changing player training or boosters',()=>{
  const p=project();p.preview={coach_id:'17609097478250'};
  const coach=catalog.coaches.find(c=>c.id===p.preview.coach_id),base=structuredClone(p.base_abilities);
  const native=simulate(p,catalog);assert.equal(native.final[15],68);assert.equal(native.final[37],68);assert.equal(native.final[40],67);assert.equal(native.final[21],67);assert.deepEqual(p.base_abilities,base);
  assert.deepEqual(coach.unmapped_abilities,[]);assert.deepEqual(coach.linkups.map(c=>c.template_id),[7,12]);
  p.custom_coaches=[{id:'custom:test',name:'自建教练',effects:{20:6,34:2}}];p.preview.coach_id='custom:test';
  const custom=simulate(p,catalog);assert.equal(custom.final[20],71);assert.equal(custom.boosted[20],65);assert.deepEqual(p.training,project().training);
});

test('coach proficiency matches the native float32 calibration and changes with tactics',()=>{
  assert.equal(coachFactor(88),Math.fround(1.0353086));assert.equal(coachFactor(127),1);
  const p=project();p.preview={coach_id:'17609097478250',team_style:'short_counter'};
  const quick=simulate(p,catalog);p.preview.team_style='long_ball';const long=simulate(p,catalog);
  assert.equal(quick.final[15],68);assert.equal(long.final[15],66);assert.ok(quick.ovr>long.ovr);assert.deepEqual(quick.trained,long.trained);
});
