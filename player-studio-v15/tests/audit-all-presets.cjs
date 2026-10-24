const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const root=path.resolve(__dirname,'../..'),qa=path.join(root,'.work/studio-qa'),runtime=JSON.parse(fs.readFileSync(process.env.STUDIO_RUNTIME||path.join(root,'.work/studio-v14-ui/runtime.json'),'utf8'));
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1640,height:1120}});await page.goto(runtime.url);await page.waitForFunction(()=>window.__studio?.presets);await page.locator('[data-page="card"]').click();
 const samples=[];
 for(const kind of ['BigTime','Epic']){
   await page.locator(`[data-preset-kind="${kind}"]`).click();let index=0;
   for(;;){
     await page.waitForFunction(()=>window.__studio.presets.result?.rows.length>0&&[...document.querySelectorAll('[data-preset-loading]')].length>0&&[...document.querySelectorAll('[data-preset-loading]')].every(e=>e.hidden),{},{timeout:60000});
     await page.evaluate(async()=>{
       const visible=c=>{const p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let n=0;for(let i=0;i<p.length;i+=4)if(p[i+3]>16&&Math.max(p[i],p[i+1],p[i+2])>16)n++;return n;};
       for(const renderer of window.__studio.presets.renderers){
         let count=visible(renderer.canvas);
         if(count<100)for(const time of [.2,1.8,3.8]){
           await Promise.all(renderer.resources.filter(r=>r.kind==='video').map(r=>new Promise(resolve=>{r.element.addEventListener('seeked',resolve,{once:true});r.element.currentTime=Math.min(time,r.element.duration-.05);setTimeout(resolve,700);})));renderer.draw();count=Math.max(count,visible(renderer.canvas));
         }
         renderer.canvas.dataset.visiblePixels=count;
       }
     });
     samples.push(...await page.locator('[data-preset-tile]').evaluateAll(els=>els.map(e=>({id:e.dataset.presetTile,label:e.querySelector('strong').textContent,code:e.querySelector('small').textContent,png:e.querySelector('canvas').toDataURL(),visiblePixels:Number(e.querySelector('canvas').dataset.visiblePixels)}))));
     const state=await page.evaluate(()=>({page:window.__studio.presets.result.page,pages:window.__studio.presets.result.pages}));
     assert.equal(state.page,index);if(state.page+1>=state.pages)break;
     await page.locator(`[data-preset-page="${index+1}"]`).click();index++;
   }
 }
 assert.equal(new Set(samples.map(s=>s.id)).size,94);
 const contact=await browser.newPage({viewport:{width:1100,height:1510}});
 for(let i=0;i<samples.length;i+=20){
   await contact.setContent('<body style="margin:0;background:#192331;color:#dcebe5;font:12px Arial"><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:9px;padding:10px">'+samples.slice(i,i+20).map(s=>`<article><img src="${s.png}" style="width:100%;display:block;background:#223242"><div style="padding:7px;height:42px">${s.code}<br>${s.label.replace(/[<>]/g,'')}</div></article>`).join('')+'</div></body>');
   await contact.screenshot({path:path.join(qa,`v14-presets-contact-${i/20+1}.png`),fullPage:true});
 }
 fs.writeFileSync(path.join(qa,'v14-all-bt-epic-audit.json'),JSON.stringify({verified:samples.length,ids:samples.map(({id,code,label,visiblePixels})=>({id,code,label,visiblePixels})),missing:[],emptyDesigns:samples.filter(s=>s.visiblePixels<100).map(s=>s.id)},null,2));
 console.log(JSON.stringify({verified:samples.length,missing:[]}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
