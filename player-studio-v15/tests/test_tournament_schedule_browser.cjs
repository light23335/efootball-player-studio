// Independent HTML verification only. Never connects to an emulator/game.
// node tests/test_tournament_schedule_browser.cjs <examples-folder> <qa-folder>
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const modules=process.env.STUDIO_QA_NODE_MODULES||'C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const {chromium}=require(path.join(modules,'playwright'));
const examples=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);
fs.mkdirSync(out,{recursive:true});
const errors=[],requests=[],checks=[];
const server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname.replace(/^\//,'').replace(/\.html$/,'');
  if(!/^[a-z0-9]+$/.test(name)){res.writeHead(404).end();return;}
  const file=path.join(examples,name+'.html');if(!fs.existsSync(file)){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}).end(fs.readFileSync(file));
});
const check=(name,details={})=>checks.push({name,...details});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
  try{
    browser=await chromium.launch({headless:true,executablePath:process.env.STUDIO_QA_CHROME||'C:/Users/1/.cache/puppeteer/chrome/win64-152.0.7977.75/chrome-win64/chrome.exe'});
    const context=await browser.newContext({viewport:{width:1440,height:1050},isMobile:false,hasTouch:true});
    const page=await context.newPage();
    page.on('pageerror',e=>{errors.push(String(e));console.error('UI error:',String(e));});
    page.on('request',r=>requests.push(r.url()));
    const go=async(name)=>{await page.goto('http://127.0.0.1:'+server.address().port+'/'+name);await page.waitForFunction(()=>window.tournamentScheduleReady,{},{timeout:10000});};
    const snap=async(name)=>{
      await page.evaluate(()=>{let mark=document.getElementById('qa-mark');if(!mark){mark=document.createElement('div');mark.id='qa-mark';Object.assign(mark.style,{position:'fixed',bottom:'5px',right:'12px',font:'10px sans-serif',color:'#a0b3cd',background:'#09121eda',padding:'5px 8px',borderRadius:'5px',zIndex:100,pointerEvents:'none'});mark.textContent='独立 UI 验证 · 合成赛果 · 非游戏截图';document.body.append(mark);}});
      await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
    };
    const noOverflow=async(label)=>{
      const sizes=await page.evaluate(()=>({viewport:innerWidth,body:document.documentElement.scrollWidth}));
      assert(sizes.body<=sizes.viewport+1,label+' has page overflow '+JSON.stringify(sizes));check(label,sizes);
    };
    await go('cup');
    assert.equal(await page.locator('#difficulty').textContent(),'游戏难度 · 顶尖');
    assert(!(await page.locator('body').textContent()).includes('DIVISION'));
    check('Chinese game difficulty replaces division label');
    assert((await page.locator('img.game-emblem').count())>0,'Actual game crests should be embedded');
    await page.waitForFunction(()=>[...document.querySelectorAll('img.game-emblem')].every(i=>i.complete&&i.naturalWidth>0));
    assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--blue').trim()),'#65aaff');
    check('blue palette and decoded embedded game emblems');
    assert.equal(await page.locator('.tie-card').count(),15);
    assert.equal(await page.locator('.wires path').count(),14);
    assert((await page.locator('.tie-card.pending').count())>0);
    await noOverflow('desktop bracket');await snap('desktop-bracket');
    await page.locator('.tie-card').first().click();await page.locator('#detail').waitFor({state:'visible'});
    assert((await page.locator('.detail-leg').count())===2);await page.locator('#detail-close').click();
    await page.locator('#zoom-out').click();assert.equal(await page.locator('#zoom-label').textContent(),'85%');
    await page.locator('#zoom-fit').click();assert((await page.locator('#zoom-label').textContent()).endsWith('%'));
    await page.locator('#own').click();assert((await page.locator('.tie-card.dim').count())>0);
    await page.locator('#own').click();
    await page.locator('#rules-toggle').click();assert((await page.locator('#rules').textContent()).includes('2 强例外'));
    await page.locator('#rules-toggle').click();
    await page.locator('#tab-fixtures').click();assert((await page.locator('.fixture-row').count())>0);
    await snap('desktop-fixtures');check('bracket details, zoom, own filter, round exceptions');
    await go('groups');await page.locator('#tab-tables').click();assert.equal(await page.locator('.table-section').count(),4);
    await noOverflow('desktop groups');await snap('desktop-groups');
    await page.locator('#group').selectOption('1');assert.equal(await page.locator('.table-section').count(),1);
    await page.locator('#group').selectOption('all');
    await page.locator('.stage[data-stage="1"]').click();assert((await page.locator('#panel-bracket').textContent()).includes('对阵尚未生成'));
    assert.equal(await page.locator('.tie-card').count(),0);check('groups and ungenerated future stage');
    await page.setViewportSize({width:390,height:844});await go('groups');await page.locator('.stage[data-stage="0"]').click();await page.locator('#tab-tables').click();
    await noOverflow('portrait group table');await snap('portrait-groups');
    const points=await page.locator('.table-section').first().locator('tbody tr').first().locator('td').last().boundingBox();
    assert(points.x+points.width<=390,'Portrait points must be visible without scrolling');
    await page.locator('.table-expand').first().click();assert.equal(await page.locator('.table-expand').first().getAttribute('aria-expanded'),'true');
    await page.locator('.table-expand').first().click();check('portrait points visible and all-statistics expansion');
    await page.locator('#tab-fixtures').click();await noOverflow('portrait fixture list');await snap('portrait-fixtures');
    await go('cup');await page.locator('#tab-bracket').click();await noOverflow('portrait bracket');await snap('portrait-bracket');
    await page.locator('#back').click();assert((await page.locator('#toast').textContent()).includes('独立界面预览'));check('preview back is honest');
    await page.setViewportSize({width:844,height:390});await go('cup');await page.locator('#tab-bracket').click();await noOverflow('landscape bracket');await snap('landscape-bracket');
    await page.setViewportSize({width:1440,height:1050});await go('league128');await page.locator('#tab-fixtures').click();
    assert.equal(await page.locator('.fixture-row').count(),40);
    assert((await page.locator('#count').textContent()).includes('16256'));
    await page.locator('#page-next').click();assert((await page.locator('#pagination').textContent()).includes('2 / 407'));
    await page.locator('#search').fill('皇家马德里');assert((await page.locator('#count').textContent()).includes('254 场'));
    await page.locator('#own').click();assert((await page.locator('#count').textContent()).includes('254 场'));
    await page.locator('#refresh').click();await page.waitForFunction(()=>window.tournamentScheduleReady);
    assert.equal(await page.locator('#tab-fixtures').getAttribute('aria-selected'),'true');
    check('128-team double round league: 16256 fixtures, 40 DOM rows, 407 pages, search and refresh');
    await page.locator('#tab-tables').click();assert.equal(await page.locator('tbody tr').count(),128);await snap('league128-table');
    await go('knockout128');assert.equal(await page.locator('.tie-card').count(),127);assert.equal(await page.locator('.wires path').count(),126);
    const before=await page.locator('#bracket-viewport').evaluate(e=>e.scrollTop);
    await page.locator('#bracket-viewport').evaluate(e=>e.scrollTop=e.scrollHeight);assert((await page.locator('#bracket-viewport').evaluate(e=>e.scrollTop))>before);
    const zoomBefore=await page.locator('#zoom-label').textContent();
    await page.locator('#bracket-viewport').evaluate(e=>{
      const touch=(id,x,y)=>new Touch({identifier:id,target:e,clientX:x,clientY:y});
      e.dispatchEvent(new TouchEvent('touchstart',{touches:[touch(1,80,80),touch(2,180,80)]}));
      e.dispatchEvent(new TouchEvent('touchmove',{touches:[touch(1,80,80),touch(2,230,80)],cancelable:true}));
      e.dispatchEvent(new TouchEvent('touchend',{touches:[]}));
    });
    assert.notEqual(await page.locator('#zoom-label').textContent(),zoomBefore);check('two-finger zoom gesture handler');
    await page.locator('#search').fill('皇家马德里');assert.equal(await page.locator('.tie-card:not(.dim)').count(),1);check('128-team tree has 127 ties and 126 links; scroll and filter');
    await go('byes');await page.locator('#tab-fixtures').click();assert((await page.locator('#fixtures').textContent()).includes('轮空记录 · 10 条'));check('odd league bye records');
    await go('history');await page.locator('.stage[data-stage="0"]').click();assert.equal(await page.locator('.table-section').count(),4);await snap('historical-tables');
    await page.locator('.stage[data-stage="1"]').click();await page.locator('#rules-toggle').click();assert((await page.locator('#rules').textContent()).includes('4 队轮空本阶段后汇合'));check('historical tables and playoff bypass');
    await go('xss');assert.equal(await page.evaluate(()=>window.pwned),undefined);assert((await page.locator('h1').textContent()).includes('</script>'));check('untrusted name stays inert');
    await page.goto('http://127.0.0.1:'+server.address().port+'/cup?host=android');await page.waitForFunction(()=>window.tournamentScheduleReady);await page.locator('#back').click();assert.equal(await page.title(),'player-studio-schedule:close');check('native return signal, no navigation');
    assert.equal(errors.length,0,errors.join('\n'));assert(requests.every(u=>u.startsWith('http://127.0.0.1:')||u.startsWith('data:image/png;base64,')), 'Unexpected external request');
    const hashes={};for(const name of fs.readdirSync(examples).filter(n=>n.endsWith('.html')))hashes[name]=crypto.createHash('sha256').update(fs.readFileSync(path.join(examples,name))).digest('hex');
    const report={kind:'independent-browser-ui-qa',device_game_tested:false,checks,errors,network:'loopback HTML + embedded game PNGs; no remote assets',example_sha256:hashes,screenshots:fs.readdirSync(out).filter(n=>n.endsWith('.png'))};
    fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
