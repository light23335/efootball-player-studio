import test from 'node:test';
import assert from 'node:assert/strict';
import {WorldUI,filteredTeams,sampleLeagueTeams,randomLeaguePool,teamAvailabilityText} from '../web/world-ui.js';
globalThis.document={addEventListener(){},querySelector(){return null;}};
function fixture(){let renders=0;const messages=[];const ui=new WorldUI({rerender:()=>renders++,toast:(m)=>messages.push(m)});
 ui.value={uuid:'world-workspace',stadium:{enabled:false,slots:[]},tournaments:[{uuid:'cup',name:'Cup',team_ids:[1],player_team_id:1,stages:[]}]};ui.tournament='cup';ui.paintTeams=()=>{};ui.paintSelected=()=>{};
 return {ui,messages,get renders(){return renders;}};
}
test('typing in tournament fields updates draft without replacing focused DOM and can undo',()=>{
 const f=fixture();f.ui.input({target:{dataset:{worldField:'tournaments.0.name'},type:'text',tagName:'INPUT',value:'Changed'}});
 assert.equal(f.ui.current.name,'Changed');assert.equal(f.renders,0);assert.equal(f.ui.draft.tournaments[0].name,'Changed');
 f.ui.history.undo();assert.equal(f.ui.current.name,'Cup');assert.equal(f.renders,1);f.ui.history.redo();assert.equal(f.ui.current.name,'Changed');
});
test('team selection enforces limit before changing draft, and selected IDs do not duplicate',()=>{
 const f=fixture();const el={dataset:{worldTeam:'1'},checked:true};f.ui.change({target:el});assert.deepEqual(f.ui.current.team_ids,[1]);
 f.ui.current.team_ids=Array.from({length:128},(_,i)=>i+1);el.dataset.worldTeam='129';f.ui.change({target:el});assert.equal(el.checked,false);assert.equal(f.ui.current.team_ids.length,128);assert.equal(f.messages.length,1);
});
test('team search accepts translated names and IDs; native device picker preserves unknown current IDs',()=>{
 assert.equal(filteredTeams([{id:101,name:'Liverpool',name_zh:'利物浦'},{id:108,name:'Chelsea'}],'利物').length,1);
 const f=fixture();f.ui.catalogue=[{id:1,name:'Banner <one>'}];const html=f.ui.nativeObject('slot',201);
 assert.match(html,/value="201" selected/);assert.match(html,/Banner &lt;one&gt;/);
});
test('national family labels distinguish IDs in both team picker and represented team without changing names',()=>{
 const f=fixture();f.ui.current.team_ids=[54,49206];f.ui.current.player_team_id=54;
 f.ui.teams=[{id:54,name:'中国',selection_label:'中国（国家队编号）'},{id:49206,name:'中国',selection_label:'中国（队套编号，同国家球员池）'}];
 assert.deepEqual(filteredTeams(f.ui.teams,'队套').map(r=>r.id),[49206]);
 const elements={'#world-teams':{innerHTML:''},'#world-team-selected':{innerHTML:''}};
 const original=document.querySelector;document.querySelector=s=>elements[s]||null;
 try{WorldUI.prototype.paintTeams.call(f.ui);WorldUI.prototype.paintSelected.call(f.ui);}finally{document.querySelector=original;}
 for(const element of Object.values(elements)){assert.match(element.innerHTML,/中国（国家队编号）/);assert.match(element.innerHTML,/中国（队套编号，同国家球员池）/);}
 assert.match(elements['#world-team-selected'].innerHTML,/value="54" selected/);
 assert.match(elements['#world-team-selected'].innerHTML,/value="49206"/);
 assert.deepEqual(f.ui.current.team_ids,[54,49206]);assert.deepEqual(f.ui.teams.map(r=>r.name),['中国','中国']);
});
test('league draw samples the union, excludes existing teams, and is one undoable addition',async()=>{
 const leagues=[{id:'a',team_ids:[1,2,3]},{id:'b',team_ids:[3,4,5]}];
 assert.deepEqual(sampleLeagueTeams(leagues,['a','b'],[1],4,()=>.99),[2,3,4,5]);
 assert.throws(()=>sampleLeagueTeams(leagues,['a'],[1],3),/只剩 2/);
 assert.throws(()=>sampleLeagueTeams(leagues,[],[],1),/至少一个/);
 assert.throws(()=>sampleLeagueTeams(leagues,['a'],Array(128).fill(9),1),/128/);
 const f=fixture();f.ui.leagues=leagues;f.ui.leagueSelection=['a','b'];f.ui.randomCount=4;
 const b={dataset:{},hasAttribute:n=>n==='data-world-random-teams'};await f.ui.click({target:{closest:()=>b}});
 assert.equal(f.ui.current.team_ids.length,5);f.ui.history.undo();assert.deepEqual(f.ui.current.team_ids,[1]);
});

function nationalCatalogue(){return [
 {id:90001,name:'同名球队',national_team_nation_id:7,national_team_kind:'native',random_national_team_id:90001},
 {id:3,name:'同名球队',national_team_nation_id:7,national_team_kind:'squad_alias',random_national_team_id:90001},
 {id:52,name:'Japan',national_team_nation_id:8,national_team_kind:'native',random_national_team_id:52},
 {id:49204,name:'Japan',national_team_nation_id:8,national_team_kind:'squad_alias',random_national_team_id:52},
 {id:101,name:'Club 1'},{id:102,name:'Club 2'}
];}
const randomButton={dataset:{},hasAttribute:n=>n==='data-world-random-teams'};
test('every random pool filters national squad aliases by native metadata and retains ordinary clubs',()=>{
 const teams=nationalCatalogue(),leagues=[{id:'national',team_ids:[3,90001,49204,52]},
  {id:'club',team_ids:[101,102]},{id:'imported',team_ids:[3,101,49204,52,90001]}];
 assert.deepEqual(sampleLeagueTeams(leagues,['national'],[],2,()=>.99,teams),[90001,52]);
 assert.deepEqual(sampleLeagueTeams(leagues,['imported'],[],3,()=>.99,teams),[101,52,90001]);
 assert.deepEqual(sampleLeagueTeams(leagues,['national','club','imported'],[],4,()=>.99,teams),[90001,52,101,102]);
 assert.deepEqual(sampleLeagueTeams(leagues,['club'],[],2,()=>.99,teams),[101,102]);
 assert.throws(()=>sampleLeagueTeams(leagues,['national'],[],3,()=>.99,teams),/只剩 2.*队套编号不补足/);
});
test('actual random add handler preserves manually selected aliases and blocks automatic same-country duplicates',async()=>{
 const f=fixture();f.ui.teams=nationalCatalogue();f.ui.current.team_ids=[3];f.ui.current.player_team_id=3;
 f.ui.leagues=[{id:'national',team_ids:[90001,52,49204,3]}];f.ui.leagueSelection=['national'];f.ui.randomCount=1;
 await f.ui.click({target:{closest:()=>randomButton}});
 assert.deepEqual(f.ui.current.team_ids,[3,52]);assert.equal(f.ui.current.player_team_id,3);
 assert.match(f.messages[0],/已随机添加 1/);
 f.ui.history.undo();assert.deepEqual(f.ui.current.team_ids,[3]);
 assert.equal(f.ui.current.player_team_id,3);
});
test('actual random add failure explains canonical shortage and leaves draft and history untouched',async()=>{
 const f=fixture();f.ui.teams=nationalCatalogue();f.ui.current.team_ids=[3];f.ui.current.player_team_id=3;
 f.ui.leagues=[{id:'national',team_ids:[90001,52,49204,3]}];f.ui.leagueSelection=['national'];f.ui.randomCount=2;
 const before=structuredClone(f.ui.value);
 await f.ui.click({target:{closest:()=>randomButton}});
 assert.deepEqual(f.ui.value,before);assert.equal(f.ui.dirty,false);
 assert.match(f.messages[0],/只剩 1.*同一国家只选一次.*队套编号不补足/);
 assert.equal(f.ui.history.canUndo,false);
});
test('random selection excludes ambiguous native references and manual controls still accept all alias IDs',()=>{
 const teams=nationalCatalogue();teams[0].random_national_team_id=null;
 assert.throws(()=>sampleLeagueTeams([{id:'national',team_ids:[90001,3]}],['national'],[],1,()=>.99,teams),/只剩 0/);
 const f=fixture();f.ui.teams=teams;
 f.ui.change({target:{dataset:{worldTeam:'3'},checked:true}});
 f.ui.change({target:{dataset:{worldTeam:'90001'},checked:true}});
 assert.deepEqual(f.ui.current.team_ids,[1,3,90001]);
});

function availability(source,current=source,pending=0){
 const status=n=>({source_people:source,current_people:n,real_people:n,local_pending_export:n===current?pending:0,mode:n<11?'insufficient':n<23?'fallback':'strict'});
 return {with_diy:{cpu:status(current),player:status(current)},without_diy:{cpu:status(source),player:status(source)}};
}
test('random pool excludes fewer than eleven real people and keeps eleven to twenty-two without a strict 23 gate',()=>{
 const teams=[0,10,11,22,23].map((n,i)=>({id:100+i,name:'Manual club '+n,tournament_eligibility:availability(n)}));
 const leagues=[{id:'clubs',team_ids:teams.map(r=>r.id)}];
 assert.deepEqual(randomLeaguePool(leagues,['clubs'],[],teams),[102,103,104]);
 assert.deepEqual(sampleLeagueTeams(leagues,['clubs'],[],3,()=>.99,teams),[102,103,104]);
 assert.throws(()=>sampleLeagueTeams(leagues,['clubs'],[],4,()=>.99,teams),/只剩 3.*至少 11/);
 const f=fixture();f.ui.teams=teams;f.ui.current.team_ids=[];
 f.ui.change({target:{dataset:{worldTeam:'100'},checked:true}});
 assert.deepEqual(f.ui.current.team_ids,[100]);
 assert.match(teamAvailabilityText(teams[0]),/当前 0.*仍可手选和导出/);
 assert.match(teamAvailabilityText(teams[2]),/真实首发.*替补不足/);
});
test('actual random add handler recalculates eleven-person eligibility when include DIY changes',async()=>{
 const f=fixture();f.ui.teams=[{id:777,name:'DIY shore-up club',tournament_eligibility:availability(10,11,1)}];
 f.ui.leagues=[{id:'clubs',team_ids:[777]}];f.ui.leagueSelection=['clubs'];f.ui.randomCount=1;
 await f.ui.click({target:{closest:()=>randomButton}});
 assert.deepEqual(f.ui.current.team_ids,[1,777]);
 f.ui.history.undo();assert.deepEqual(f.ui.current.team_ids,[1]);
 f.ui.change({target:{dataset:{worldField:'tournaments.0.include_diy'},type:'checkbox',tagName:'INPUT',checked:false}});
 await f.ui.click({target:{closest:()=>randomButton}});
 assert.deepEqual(f.ui.current.team_ids,[1]);assert.match(f.messages.at(-1),/只剩 0/);
 assert.match(teamAvailabilityText(f.ui.teams[0],true),/原库 10.*当前 11.*本地 DIY/);
 assert.match(teamAvailabilityText(f.ui.teams[0],false),/当前 10.*不足 11/);
});
test('selected chips warn about low people counts without deleting old teams or changing the controlled team',()=>{
 const f=fixture();f.ui.teams=[{id:5010,name:'Short club',tournament_eligibility:availability(0)}];
 f.ui.current.team_ids=[5010];f.ui.current.player_team_id=5010;
 const target={innerHTML:''},original=document.querySelector;document.querySelector=s=>s==='#world-team-selected'?target:null;
 try{WorldUI.prototype.paintSelected.call(f.ui);}finally{document.querySelector=original;}
 assert.match(target.innerHTML,/原库 0.*当前 0.*不足 11/);
 assert.match(target.innerHTML,/不阻止手动选择或导出/);
 assert.match(target.innerHTML,/value="5010" selected/);
 assert.deepEqual(f.ui.current.team_ids,[5010]);assert.equal(f.ui.current.player_team_id,5010);
});
test('random handler refreshes newly created DIY availability while preserving the unsaved competition draft',async()=>{
 const f=fixture();f.ui.current.name='Unsaved competition';
 f.ui.teams=[{id:777,name:'Club',tournament_eligibility:availability(10)}];
 f.ui.leagues=[{id:'clubs',team_ids:[777]}];f.ui.leagueSelection=['clubs'];f.ui.randomCount=1;
 const calls=[];f.ui.api=async name=>{calls.push(name);return {document:{tournaments:[]},
  teams:[{id:777,name:'Club',tournament_eligibility:availability(10,11,1)}],leagues:f.ui.leagues};};
 await f.ui.click({target:{closest:()=>randomButton}});
 assert.deepEqual(calls,['world/load']);assert.deepEqual(f.ui.current.team_ids,[1,777]);
 assert.equal(f.ui.current.name,'Unsaved competition');assert.equal(f.ui.current.uuid,'cup');
});
test('stadium unlock is independent and native positions include a keyboard target',()=>{
 const f=fixture();f.ui.value.stadium={enabled:false,unlock_all:true,selected:101,slots:[{stadium_id:101,custom_stadium_name:'Test',objects:[null,null,null,null,null,null],pitchside_objects:[0,0,0,0,0,0]}]};
 f.ui.anchors=[{id:1,position_cm:[-6000,1500,0],yaw:270,label:'A 端球门后方',description:'原生坐标'}];
 const html=f.ui.stadium();assert.match(html,/stadium.unlock_all" checked/);assert.match(html,/此处建议在游戏内修改并实时查看效果/);assert.match(html,/data-world-anchor="0"/);assert.match(html,/A 端球门后方/);
});
test('tournament cover upload, crop, clear and undo update one draft and keep competition rules',async()=>{
 const f=fixture(),calls=[],asset='a'.repeat(64)+'.png';
 f.ui.api=async(name,body)=>{calls.push([name,body]);return name==='dialog'?{path:'chosen.png'}:{id:asset};};
 await f.ui.chooseCover();
 assert.deepEqual(calls,[['dialog',{category:'image'}],['assets/import',{path:'chosen.png',category:'image'}]]);
 assert.deepEqual(f.ui.current.cover,{asset_id:asset,zoom:1,x:0,y:0});
 f.ui.input({target:{dataset:{worldField:'tournaments.0.cover.x'},type:'range',tagName:'INPUT',value:'35'}});
 assert.equal(f.ui.current.cover.x,35);assert.equal(typeof f.ui.current.cover.x,'number');
 assert.match(f.ui.tournaments(),/data-world-cover="choose"/);assert.match(f.ui.tournaments(),/16:9/);
 assert.match(f.ui.tournaments(),/object-position:67.5% 50%/);
 const b={dataset:{worldCover:'clear'},hasAttribute:()=>false};await f.ui.click({target:{closest:()=>b}});
 assert.equal(f.ui.current.cover,null);assert.deepEqual(f.ui.current.team_ids,[1]);
 f.ui.history.undo();assert.equal(f.ui.current.cover.asset_id,asset);assert.equal(f.ui.current.cover.x,35);
 f.ui.tournament=null;assert.match(f.ui.tournaments(),/锦标赛封面裁切预览/);
});
test('cancelled or outdated cover selection leaves the current tournament unchanged',async()=>{
 const f=fixture();let imports=0;
 f.ui.api=async(name)=>{if(name==='dialog')return{};imports++;};
 await f.ui.chooseCover();assert.equal(imports,0);assert.equal(f.ui.current.cover,undefined);
 let finish;f.ui.api=async(name)=>{if(name==='dialog')return new Promise(resolve=>finish=resolve);imports++;return{id:'a'.repeat(64)+'.png'};};
 const pending=f.ui.chooseCover();f.ui.tournament=null;finish({path:'chosen.png'});await pending;
 assert.equal(imports,0);assert.equal(f.ui.value.tournaments[0].cover,undefined);
});

test('each tournament has an undoable numeric duration and old drafts retain the native default',()=>{
 const f=fixture();
 const control=f.ui.durationControl(f.ui.current,'tournaments.0');
 assert.match(control,/data-world-field="tournaments.0.match_minutes"/);
 assert.match(control,/value="0" selected/);
 for(const n of [3,5,30])assert.match(control,new RegExp(`value="${n}"`));
 assert.equal((control.match(/<option /g)||[]).length,29);
 f.ui.value.tournaments.push({uuid:'another',name:'Other',team_ids:[2],player_team_id:2,stages:[],match_minutes:9});
 f.ui.change({target:{dataset:{worldField:'tournaments.0.match_minutes'},tagName:'SELECT',value:'5'}});
 assert.equal(f.ui.current.match_minutes,5);assert.equal(typeof f.ui.current.match_minutes,'number');
 assert.equal(f.ui.value.tournaments[1].match_minutes,9);assert.equal(f.renders,0);
 assert.match(f.ui.tournaments(),/value="5" selected/);
 assert.match(f.ui.tournaments(),/修改保留赛程和积分/);
 f.ui.history.undo();assert.equal(f.ui.current.match_minutes,undefined);
 f.ui.history.redo();assert.equal(f.ui.current.match_minutes,5);
});
