import test from 'node:test';
import assert from 'node:assert/strict';
import {CoachHeads} from '../web/coach-heads.js';
import {NativePackageUI} from '../web/native-package-ui.js';

const target='PesMobile/Content/Assets/character/DemoFace/Manager/SK_437_Face.uasset';
const asset='a'.repeat(64)+'.glb';
function setup(){
  const old=globalThis.document,body={};
  globalThis.document={addEventListener(){},querySelector:s=>s==='#coach-head-body'?body:null,querySelectorAll:()=>[],documentElement:{hasAttribute:()=>false}};
  return {body,restore:()=>{globalThis.document=old;}};
}
function editor(api){
  return Object.assign(Object.create(CoachHeads.prototype),{api,sequence:0,ready:true,open:true,
    currentCoach:{id:'437',name:'Selected coach',type:'original'},target,
    rows:[{path:target,label:'Selected coach',name:'SK_437_Face',variant:0,coach_ids:['437']}],
    toast(){},rerender(){},attach:async()=>{}});
}

test('PC and Android export UI have no independent global head toggle or payload',()=>{
  const {restore}=setup();try{for(const platform of ['pc','android']){
    const ui=new NativePackageUI({platform,project:()=>({package_id:'p'})});
    ui.apk='source.apk';ui.writeSource={token:'source'};
    assert.doesNotMatch(ui.render(),/data-native-heads|native-head-candidates|写入已保存的教练头模替换/);
    assert.match(ui.render(),/打开对应教练并导入/);
    ui.selectOptional(true);
    assert.equal(Object.hasOwn(ui.buildBody(),'include_coach_heads'),false);
    assert.equal(Object.hasOwn(ui.buildBody(),'coach_heads'),false);
  }}finally{restore();}
});

test('selected original coach retains import, preview, export and save controls',()=>{
  const {body,restore}=setup();try{
    const ui=editor();ui.paint();
    for(const action of ['upload','native','original','draft','export','save'])assert.match(body.innerHTML,new RegExp('data-head-action="'+action+'"'));
    assert.match(body.innerHTML,/保存这名教练的头模/);
    assert.doesNotMatch(body.innerHTML,/coach-head-target|coach-head-query|头模工作区/);
    ui.legacyAvailable=true;ui.paint();assert.match(body.innerHTML,/data-head-action="migrate"/);
    ui.open=false;assert.equal(ui.render(),'');
  }finally{restore();}
});

test('import previews the selected target and save carries the selected coach identity',async()=>{
  const {restore}=setup();try{
    const calls=[],head={target,mode:'custom',asset_id:asset,preserve_expression:true};
    const ui=editor(async(path,body)=>{
      calls.push([path,body]);
      if(path==='dialog')return {path:'my-head.glb'};
      if(path==='assets/import')return {id:asset};
      if(path==='coaches/heads/preview')return {asset_id:'preview.glb',report:{mode:'custom'}};
      if(path==='coaches/model/save')return {head:{...head,coach_id:body.coach.id},asset_id:'saved.glb'};
      throw Error('Unexpected route '+path);
    });
    await ui.action('upload');assert.deepEqual(ui.draft,head);assert.equal(ui.previewData.asset_id,'preview.glb');
    await ui.action('save');
    assert.deepEqual(calls.map(c=>c[0]),['dialog','assets/import','coaches/heads/preview','coaches/model/save']);
    assert.equal(calls.at(-1)[1].coach.id,'437');assert.equal(calls.at(-1)[1].head.target,target);
    assert.equal(ui.replacement.coach_id,'437');assert.equal(ui.previewData.asset_id,'saved.glb');
  }finally{restore();}
});

test('migration is an explicit selected-coach request, with no global save',async()=>{
  const {restore}=setup();try{
    let request;
    const ui=editor(async(path,body)=>{request=[path,body];return {head:{target,mode:'custom',asset_id:asset,coach_id:body.coach.id}};});
    ui.legacyAvailable=true;await ui.action('migrate');
    assert.equal(request[0],'coaches/model/migrate');assert.equal(request[1].coach.id,'437');
    assert.equal(ui.legacyAvailable,false);assert.equal(ui.replacement.asset_id,asset);
  }finally{restore();}
});

test('changing coaches while a dialog is open cannot import into a shared target',async()=>{
  const {restore}=setup();try{
    let resolveDialog,calls=0;
    const ui=editor(async()=>{calls++;return new Promise(resolve=>{resolveDialog=resolve;});});
    const pending=ui.action('upload');
    ui.currentCoach={id:'other',name:'Another coach',type:'original'};
    resolveDialog({path:'my.glb'});await pending;
    assert.equal(calls,1);assert.equal(ui.draft,undefined);
  }finally{restore();}
});
