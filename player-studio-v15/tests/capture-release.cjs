const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
  const root=path.resolve(__dirname,'../..'),runtime=JSON.parse(fs.readFileSync(path.join(root,'球员工坊/data/runtime.json'),'utf8'));
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1600,height:1060},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(runtime.url);await page.waitForFunction(()=>window.__studio?.viewer?.subject&&document.querySelector('#player-card')?.width===1200);
  assert.equal(await page.evaluate(()=>window.__studio.project.card_id),null);
  assert.equal(await page.evaluate(()=>window.__studio.project.identity.name),'');
  assert.equal(await page.evaluate(()=>window.__studio.project.package_id),'f64c7ce3-bfe9-4d99-92ec-06952636dfb4');
  await page.waitForTimeout(400);
  await page.screenshot({path:path.join(root,'球员工坊/界面预览.png')});
  await page.locator('[data-page="model"]').click();await page.evaluate(()=>scrollTo(0,0));
  await page.waitForTimeout(400);await page.screenshot({path:path.join(root,'.work/studio-qa/release-model.png')});
  assert.deepEqual(errors,[]);console.log('Release EXE starts with the original empty personal project; live canvas and WebGL verified.');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
