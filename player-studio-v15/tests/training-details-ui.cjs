const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'../..'),qa=path.join(root,'.work/studio-qa'),runtime=JSON.parse(fs.readFileSync(process.env.STUDIO_RUNTIME||path.join(root,'.work/studio-v14-ui/runtime.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1640,height:1120}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(runtime.url);await page.waitForFunction(()=>window.__studio?.project);await page.locator('[data-page="training"]').click();
 const original=await page.evaluate(()=>window.__studio.project.identity.position);
 assert.equal(await page.locator('#training-target option').count(),13);
 assert.equal(await page.locator('[data-training-detail]').count(),26);
 assert.equal(await page.locator('[data-training-stat]').evaluateAll(rows=>new Set(rows.map(r=>r.dataset.trainingStat)).size),26);
 await page.locator('#training-target').selectOption('GK');await page.getByRole('button',{name:'按所选位置分配',exact:true}).click();
 const goalkeeper=await page.evaluate(()=>window.__studio.project.training);assert.ok(goalkeeper.GK1+goalkeeper.GK2+goalkeeper.GK3>0);
 await page.locator('#training-target').selectOption('CF');await page.getByRole('button',{name:'按所选位置分配',exact:true}).click();
 const striker=await page.evaluate(()=>window.__studio.project.training);assert.equal(striker.GK1+striker.GK2+striker.GK3,0);assert.notDeepEqual(goalkeeper,striker);
 assert.equal(await page.evaluate(()=>window.__studio.project.identity.position),original);
 const check=async()=>{const s=await page.evaluate(()=>window.__studio.simulation),cells=await page.locator('[data-training-stat="20"]').evaluate(el=>[...el.children].slice(1).map(n=>Number(n.textContent)));assert.deepEqual(cells,[s.base[20],s.trained[20],s.final[20]]);};
 await check();const before=await page.evaluate(()=>window.__studio.simulation.trained[20]);await page.locator('[data-step="-1"][data-group="SHOOT"]').click();await check();assert.equal(await page.evaluate(()=>window.__studio.simulation.trained[20]),before-1);
 await page.locator('[data-step="1"][data-group="SHOOT"]').click();await check();
 await page.screenshot({path:path.join(qa,'v14-training-details.png')});
 await page.evaluate(()=>window.__studio.flushSave(true));await page.reload();await page.waitForFunction(()=>window.__studio?.project);assert.equal(await page.evaluate(()=>window.__studio.project.preview.training_position),'CF');
 for(const width of [1080,700,500]){await page.setViewportSize({width,height:1000});await page.locator('[data-page="training"]').click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'width '+width);}
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(qa,'v14-training-ui-result.json'),JSON.stringify({positions:13,ability_rows:26,group_abilities:26,selected_position_persisted:true,main_position_preserved:true,manual_changes_live:true,errors},null,2));
 console.log(JSON.stringify({positions:13,abilities:26,errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
