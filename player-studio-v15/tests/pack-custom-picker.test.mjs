import test from 'node:test';
import assert from 'node:assert/strict';
import {filterCustomPlayers,customMembersToAdd,PackUI} from '../web/pack-ui.js';

const players=[
  {package_id:'one',name:'Mohamed Salah',display_name:'萨拉赫',folder_id:'liverpool'},
  {package_id:'two',name:'Virgil van Dijk',display_name:'范戴克',folder_id:'liverpool'},
  {package_id:'three',name:'Thierry Henry',display_name:'亨利',folder_id:'arsenal'},
  {package_id:'four',name:'Ronaldo',display_name:'大罗',folder_id:null},
];

test('custom search matches name, display name and permanent ID within selected folder',()=>{
  assert.deepEqual(filterCustomPlayers(players,{query:'SALAH'}).map(r=>r.package_id),['one']);
  assert.deepEqual(filterCustomPlayers(players,{query:'范戴'}).map(r=>r.package_id),['two']);
  assert.deepEqual(filterCustomPlayers(players,{query:'three'}).map(r=>r.package_id),['three']);
  assert.equal(filterCustomPlayers(players,{query:'Salah',folder:'arsenal'}).length,0);
  assert.deepEqual(filterCustomPlayers(players,{folder:'unfiled'}).map(r=>r.package_id),['four']);
});

test('folder additions skip existing UUIDs and preserve names, weights and original cards',()=>{
  const members=[{kind:'custom',id:'one',name:'Old name',weight:9},{kind:'original',id:'123',name:'Native',weight:3}];
  const before=structuredClone(members),add=customMembersToAdd(members,[players[0],players[1],players[1]]);
  assert.deepEqual(members,before);assert.deepEqual(add,[{kind:'custom',id:'two',name:'范戴克',weight:1}]);
});

test('oversized folder is rejected atomically, while duplicates at the limit are harmless',()=>{
  const members=Array.from({length:2000},(_,i)=>({kind:'custom',id:String(i),weight:1}));
  assert.throws(()=>customMembersToAdd(members,players),/2000/);assert.equal(members.length,2000);
  assert.deepEqual(customMembersToAdd(members,[{package_id:'1',name:'existing'}]),[]);
});

test('whole-folder action ignores current search/page, refreshes folder and paints once after addition',async()=>{
  const calls=[],pack={uuid:'pack',members:[]},button={disabled:false};
  const state=Object.assign(Object.create(PackUI.prototype),{editing:pack,customFolder:'liverpool',customQuery:'Salah',customPage:3,custom:players,poolRevision:1,
    api:async(path,body)=>{calls.push([path,body]);return{rows:players.slice(0,2)};},
    members(){this.paints=(this.paints||0)+1;},paintCustomResults(){},toast(){}});
  await PackUI.prototype.addCustomFolder.call(state,button);
  assert.deepEqual(calls,[['players/list',{folder_id:'liverpool'}]]);
  assert.deepEqual(pack.members.map(r=>r.id),['one','two']);assert.equal(state.paints,1);assert.equal(button.disabled,false);
});

test('late folder result cannot add players after switching packs or changing members',async()=>{
  let resolve;const old={members:[]},state={editing:old,customFolder:'liverpool',custom:players,poolRevision:1,
    api:()=>new Promise(r=>resolve=r),members(){},paintCustomResults(){},toast(){}};
  const first=PackUI.prototype.addCustomFolder.call(state,{disabled:false});
  state.editing={members:[]};resolve({rows:players});await first;assert.equal(old.members.length,0);
  const second=PackUI.prototype.addCustomFolder.call(state,{disabled:false});
  state.poolRevision++;resolve({rows:players});await assert.rejects(second,/已变化/);assert.equal(state.editing.members.length,0);
});

test('rendered custom controls escape folder labels and contain stable search fields',()=>{
  const html=PackUI.prototype.customControls.call({customQuery:'"<script>',customFolder:'liverpool',customFolders:[{id:'liverpool',name:'<team>',count:2}]});
  assert.match(html,/id="pack-custom-query"/);assert.match(html,/id="pack-custom-folder"/);
  assert.match(html,/添加整个文件夹/);assert.match(html,/&lt;team&gt;/);assert.doesNotMatch(html,/<script>/);
});
