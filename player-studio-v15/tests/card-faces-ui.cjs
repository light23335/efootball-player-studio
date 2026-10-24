const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'../..'),qa=path.join(root,'.work/studio-qa');
 const runtime=JSON.parse(fs.readFileSync(process.env.STUDIO_RUNTIME||path.join(root,'.work/studio-v131-ui/runtime.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1640,height:1120}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(runtime.url);await page.waitForFunction(()=>window.__studio?.library?.rows?.length>0);
 const result=[];
 for(const pid of ['370537029180759','89138556575063','89138288266704','89138288270047',...process.argv.slice(2)]){
   await page.evaluate(id=>window.__studio.library.loadPlayer(id),pid);
   await page.waitForFunction(id=>window.__studio.project.native_card?.source_id===id&&window.__studio.nativeCard.framesRendered>3&&window.__studio.nativeCard.key?.includes(id),pid);
   await page.waitForFunction(id=>document.querySelector('#player-card').dataset.nativeSource===id,pid);
   const card=await page.evaluate(()=>({id:window.__studio.project.source_player.id,layout:document.querySelector('#player-card').dataset.nativeLayout,
     elements:JSON.parse(document.querySelector('#player-card').dataset.nativeUiElements),fonts:window.__studio.nativeCard.fonts,
     model:window.__studio.project.model.native_source,variants:window.__studio.project.model.variants?.length,
     layers:window.__studio.project.native_card.layers.map(l=>l.name),missing:window.__studio.project.native_card.info.missing}));
   assert.ok(card.elements.stars>=1&&card.elements.stars<=5);assert.deepEqual(card.missing,[]);assert.ok(Object.values(card.fonts).every(Boolean));
   await page.locator('#card-motion-toggle').click().catch(()=>{});
   await page.locator('#player-card').screenshot({path:path.join(qa,`v131-card-${pid}.png`)});
   if(['89138288266704','89138288270047'].includes(pid)){
     assert.ok(card.model);assert.equal(card.model.textured_materials,2);assert.equal(card.model.materials,2);
     await page.locator('[data-page="model"]').click();await page.waitForFunction(()=>window.__studio.viewer?.subject?.userData.asset===window.__studio.project.model.asset);
     await page.screenshot({path:path.join(qa,`v131-face-${pid}.png`)});
   }
   result.push(card);
 }
 for(const width of [1273,1080,700,500]){
   await page.setViewportSize({width,height:716});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   if(width>760){const box=await page.locator('#player-card').boundingBox();assert.ok(box.y+box.height<716,'full card fits '+width);}
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(qa,'v131-card-faces-result.json'),JSON.stringify({cards:result,errors},null,2));
 console.log(JSON.stringify({cards:result.map(r=>({id:r.id,layout:r.layout,model:r.model?.name})),errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
