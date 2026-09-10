const {chromium,expect}=require('@playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const base=process.env.DRONEWATCH_BASE_URL || 'http://127.0.0.1:8828';
if (!['127.0.0.1', 'localhost', '[::1]'].includes(new URL(base).hostname)) throw Error('This probe only targets a local demo.');
(async()=>{
  fs.mkdirSync('.runtime', {recursive:true});
  const freshnessBrowser=await chromium.launch();
  try {
    const context=await freshnessBrowser.newContext({viewport:{width:360,height:800},isMobile:true,hasTouch:true});
    const page=await context.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const now=Date.parse('2026-09-10T11:40:00Z');
    await page.clock.install({time:now});
    let calls=0;
    const target={target_id:'FOLLOWUP-AGE',event_id:'age-check',source_kind:'WEBHOOK_EVENT',source:'Local independent review',status:'UNKNOWN',confidence:null,position:null,updated_at:new Date(now-118000).toISOString(),timestamp_basis:'reported_event_time',evidence:['Fixed observation used to test an age transition.']};
    await page.route('**/api/targets',route=>{calls++;return route.fulfill({json:{schema_version:1,targets:[target],received_at:new Date(now).toISOString()}});});
    await page.goto(base+'/?mode=sensor');
    await expect(page.locator('#detail-freshness')).toHaveText('Recent observation');
    await page.getByText('Source & interpretation',{exact:true}).tap();
    await page.clock.runFor(6000);
    await expect(page.locator('#detail-freshness')).toHaveText('Stale observation');
    await expect(page.locator('#interpretation')).toHaveAttribute('open','');
    await expect(page.locator('.detail-identity h3')).toHaveText('FOLLOWUP-AGE');
    expect(calls).toBeGreaterThanOrEqual(2);expect(errors).toEqual([]);
    console.log(JSON.stringify({probe:'freshness crosses threshold with identical payload',result:'PASS',calls,freshness:'Stale observation',selected:'FOLLOWUP-AGE',sourceExpanded:true,runtimeErrors:errors}));
  } finally {await freshnessBrowser.close();}

  // Normal Playwright pages force focus, so every tab reports visible. Use an
  // isolated Chromium profile and the default-context noDefaults CDP option to
  // exercise genuine visibility changes without overwriting document.hidden.
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'dw-followup-browser-'));
  const proc=spawn(chromium.executablePath(),['--headless=new','--remote-debugging-port=0','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','about:blank'],{stdio:['ignore','ignore','pipe']});
  proc.stderr.pipe(fs.createWriteStream('.runtime/visibility-chromium.stderr'));
  let browser;
  try {
    let port;
    for(let n=0;n<100;n++) {
      try {port=fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0];break;} catch {}
      await new Promise(r=>setTimeout(r,100));
    }
    if(!port)throw Error('No debug endpoint');
    browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{noDefaults:true});
    const context=browser.contexts()[0];
    const page=context.pages()[0];
    page.setDefaultTimeout(10000);
    await page.setViewportSize({width:360,height:800});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/');
    await page.bringToFront();
    await page.getByRole('button',{name:'Select target DW-03',exact:true}).click();
    await page.getByText('Source & interpretation',{exact:true}).click();
    await page.getByRole('button',{name:'Focus target on air picture',exact:true}).click();
    await page.evaluate(()=>{window.log=[];document.addEventListener('visibilitychange',()=>window.log.push({v:document.visibilityState,t:document.getElementById('scenario-time').textContent}));});
    const other=await context.newPage();await other.goto('about:blank');await other.bringToFront();
    await expect.poll(()=>page.evaluate(()=>document.visibilityState)).toBe('hidden');
    const before=await page.locator('#scenario-time').textContent();
    await new Promise(r=>setTimeout(r,3500));
    const hidden=await page.locator('#scenario-time').textContent();expect(hidden).toBe(before);
    await page.bringToFront();
    await new Promise(r=>setTimeout(r,1250));
    const after=await page.locator('#scenario-time').textContent();
    const seconds=s=>s.split(':').map(Number).reduce((a,b)=>a*60+b);
    expect(seconds(after)-seconds(hidden)).toBeGreaterThanOrEqual(1);
    expect(seconds(after)-seconds(hidden)).toBeLessThanOrEqual(2);
    await expect(page.locator('.detail-identity h3')).toHaveText('DW-03');
    await expect(page.locator('#interpretation')).toHaveAttribute('open','');
    await expect(page.locator('#radar-scale')).toHaveText('TARGET FOCUS · 1.7×');
    const session=await context.newCDPSession(page);await session.send('Emulation.setTouchEmulationEnabled',{enabled:true});
    const button=page.getByRole('button',{name:'Show all targets',exact:true});await button.scrollIntoViewIfNeeded();const box=await button.boundingBox();
    await session.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:box.x+box.width/2,y:box.y+box.height/2}]});
    await session.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await expect(page.locator('#radar-scale')).toHaveText('OVERVIEW');
    expect(errors).toEqual([]);
    console.log(JSON.stringify({result:'PASS',probe:'actual foreground background and touch return',before,hidden,after,events:await page.evaluate(()=>window.log),selected:'DW-03',sourceOpen:true,focusPreserved:true,touchAfterReturn:true,runtimeErrors:errors,scope:'Chromium at360px, actual hidden and visible states; not physical Android'}));
  } finally {if(browser)await browser.close();proc.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1});
