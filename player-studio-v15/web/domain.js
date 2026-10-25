export function trainingCost(count) {
  const q = Math.floor(count / 4), r = count % 4;
  return 2 * q * (q + 1) + r * (q + 1);
}

export function overall(stats, position, catalog, source=null) {
  const weights=catalog.ovr_weights[position];
  if(!weights)return 0;
  const score=values=>{let value=weights.intercept;Object.keys(catalog.ABILITIES).forEach((index,i)=>value+=(weights.abilities[catalog.stat_keys[i]]||0)*values[index]);return value;};
  let value=score(stats);
  if(Number.isInteger(source?._overall)&&catalog.POSITIONS[source.parameters?.[0]]===position)value=source._overall+value-score(source.parameters);
  const floor=Math.floor(value),rounded=value-floor===.5?(floor%2===0?floor:floor+1):Math.round(value);
  return Math.max(1,Math.min(127,rounded));
}

export function selectedCoach(project,catalog){return [...(project.custom_coaches||[]),...(catalog.coaches||[])].find(c=>c.id===project.preview?.coach_id)||null;}
export function coachFactor(proficiency){
  if(proficiency===null||proficiency===undefined||proficiency===127)return 1;
  const f=Math.fround;let value=f(proficiency);
  if(proficiency<90){const x=f(value-f(99));value=f(f(f(f(x*f(x*f(-38)))/f(99))/f(99))+f(104));}
  else value=f(f(value*f(.048500001430511475))+f(99.25299835205078));
  return f(value/f(100));
}

export function simulate(project, catalog) {
  const base = {...project.base_abilities}, trained = {...base}, boosted = {}, playerBoosts={};
  const budget = project.card_type === 'Trending' ? 0 : 2 * (project.initial_level - 1);
  let spent = 0;
  for (const group of catalog.training_groups) {
    const count = Number(project.training[group.id] || 0);
    spent += trainingCost(count);
    for (const index of group.indices) trained[index] = Math.min(105, trained[index] + count);
  }
  Object.assign(boosted, trained);
  for (const id of project.booster_ids || []) {
    const booster = [...catalog.boosters,...(project.custom_boosters||[])].find(b => b.id === id);
    if (!booster || (booster.conditional && !project.conditional_boosters)) continue;
    for (const [index, delta] of Object.entries(booster.effects)){boosted[index] = Math.max(1,Math.min(127, boosted[index] + delta));playerBoosts[index]=(playerBoosts[index]||0)+delta;}
  }
  const coach=selectedCoach(project,catalog),final={...boosted};
  const teamStyle=project.preview?.team_style||Object.entries(coach?.tactics||{}).sort((a,b)=>b[1]-a[1])[0]?.[0],proficiency=coach?.tactics?.[teamStyle],multiplier=coachFactor(proficiency);
  if(coach)for(const index of Object.keys(base)){const value=trained[index],delta=Math.trunc(Math.fround(Math.fround(multiplier*Math.fround(value))-Math.fround(value)));final[index]=Math.max(40,Math.min(120,value+delta+(playerBoosts[index]||0)+(coach.effects[index]||0)));}
  const source=project.source_player?.original_payload,ovr = stats => overall(stats,project.identity.position,catalog,source);
  return {base, trained, boosted, final, coach, teamStyle, proficiency, coachMultiplier:multiplier, budget, spent, remaining: budget - spent, valid: spent <= budget,
    ovr: ovr(final), baseOvr: ovr(base), trainedOvr: ovr(trained), boostedOvr:ovr(boosted),
    positionOvrs:Object.fromEntries(catalog.POSITIONS.map(pos=>[pos,overall(final,pos,catalog,source)]))};
}

export function autoAllocate(project, catalog) {
  const p = structuredClone(project);
  for (const g of catalog.training_groups) p.training[g.id] = 0;
  let current = simulate(p, catalog);
  const target=p.preview?.training_position||p.identity.position;
  const weights = catalog.auto_position_weights[target]||catalog.auto_position_weights[p.identity.position];
  while (current.remaining > 0) {
    let best = null;
    for (const [groupIndex, group] of catalog.training_groups.entries()) {
      const count = p.training[group.id];
      const cost = trainingCost(count + 1) - trainingCost(count);
      if (cost > current.remaining || count >= 40) continue;
      const available = group.indices.filter(index => current.trained[index] < 105).length / group.indices.length;
      const score = (weights[groupIndex] || 0) * available / ((count + 1) * cost);
      if (score > 0 && (!best || score > best.score)) best = {group, score};
    }
    if (!best) break;
    p.training[best.group.id]++;
    current = simulate(p, catalog);
  }
  return p.training;
}

export function ratingColor(value) {
  return value >= 95 ? '#78dfb3' : value >= 85 ? '#95d6ff' : value >= 75 ? '#cdb577' : '#a3aabc';
}

export const cardTypes = [
  ['BigTime','Big Time 系列'], ['Epic','史诗'], ['Legendary','传奇'], ['Highlight','高光'], ['Featured','精选'], ['Trending','趋势 / POTW'], ['Standard','标准'], ['UNKNOWN','原库未标注']
];
export const cardTypeName = type => type === 'BigTime' ? 'Big Time' : type;
export function selectCardType(project, type) {
  project.card_type=type;
  project.card_series=type==='Trending'?'POTW':type;
}
export function selectCardSeries(project, value) {
  project.card_series=value;
  const family={ShowTime:'Highlight',POTW:'Trending',IconicMoment:'Legendary'};
  if(cardTypes.some(([type])=>type===value))project.card_type=value;
  else if(family[value])project.card_type=family[value];
}
export const series = [['Epic','史诗'],['Legendary','传奇'],['Highlight','高光'],['Featured','精选'],['Trending','趋势 / POTW'],['UNKNOWN','原库未标注'],['BigTime','Big Time'],['ShowTime','Show Time'],['POTW','周精选 POTW'],['IconicMoment','旧版时刻'],['Standard','经典简洁']];
export const statGroups = [
  {name:'进攻与技术', indices:[14,18,17,19,20,21,22,23,27,28]},
  {name:'速度与身体', indices:[34,38,37,35,36,39,40]},
  {name:'防守', indices:[15,24,25,26]},
  {name:'守门', indices:[16,29,30,31,32]}
];
export const positionNames = {GK:'门将',CB:'中后卫',LB:'左后卫',RB:'右后卫',DMF:'后腰',CMF:'中前卫',LMF:'左前卫',RMF:'右前卫',AMF:'前腰',LWF:'左边锋',RWF:'右边锋',SS:'影锋',CF:'中锋'};
