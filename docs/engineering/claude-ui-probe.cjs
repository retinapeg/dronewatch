// Android-emulated probe against the throwaway server on 127.0.0.1:8899 (own temp DB).
const { chromium } = require('@playwright/test');
const base = 'http://127.0.0.1:8899';
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36' });
  const page = await context.newPage();
  const requests = [];
  page.on('request', r => requests.push({ url: r.url(), t: Date.now() }));
  const responses = [];
  page.on('response', async r => { if (r.url().includes('/api/events')) { const b = await r.body().catch(() => Buffer.alloc(0)); responses.push(b.length); } });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const out = {};
  out.spoofedProvenance = await page.evaluate(() => ({
    visoStatus: document.getElementById('viso-status').textContent,
    visoNote: document.getElementById('viso-note').textContent,
    pipeline: document.getElementById('pipeline-state').textContent,
    pipelineActive: document.getElementById('pipeline-indicator').dataset.active,
    provenanceBadge: document.getElementById('track-provenance').textContent,
    displayMode: document.getElementById('display-mode').textContent,
    contactNote: document.getElementById('contact-note').textContent,
    webhook: document.getElementById('webhook-status').textContent,
  }));
  // Evidence panel: open the details and see whether the browser fetched the attacker media URL.
  await page.locator('.sensor-evidence-details > summary').tap();
  await page.waitForTimeout(1500);
  out.beaconRequests = requests.filter(r => r.url.includes('8898')).map(r => r.url);
  out.videoRetryRequests8001 = requests.filter(r => r.url.includes('127.0.0.1:8001')).length;
  // Pin a historical observation and see whether the next poll un-pins it.
  const rows = page.locator('.event-row');
  out.rowCount = await rows.count();
  await rows.nth(2).locator('summary').tap();
  await page.waitForTimeout(300);
  const showButton = rows.nth(2).locator('button');
  const box = await showButton.boundingBox();
  out.showObservationButton = box ? { w: Math.round(box.width), h: Math.round(box.height) } : null;
  await showButton.tap();
  await page.waitForTimeout(200);
  const pinnedRead = () => page.evaluate(() => ({ contactEvent: document.getElementById('contact-event').textContent, modeMessage: document.getElementById('mode-message').textContent, returnHidden: document.getElementById('return-live').hidden, stateDetail: document.getElementById('state-detail').textContent }));
  out.pinnedImmediately = await pinnedRead();
  await page.waitForTimeout(2600);
  out.pinnedAfterOnePoll = await pinnedRead();
  // Track marker interactivity.
  out.marker = await page.evaluate(() => { const m = document.getElementById('track-marker'); const r = m.getBoundingClientRect(); return { pointerEvents: getComputedStyle(m).pointerEvents, listeners: typeof m.onclick, w: Math.round(r.width), h: Math.round(r.height), hasTabIndex: m.hasAttribute('tabindex'), role: m.getAttribute('role') }; });
  // Rendered radar text sizes and the callout box.
  out.calloutPx = await page.evaluate(() => { const r = document.querySelector('#marker-callout rect').getBoundingClientRect(); const t = document.getElementById('marker-id'); const m = t.getScreenCTM(); return { boxW: Math.round(r.width), boxH: Math.round(r.height), idFontPx: +(parseFloat(getComputedStyle(t).fontSize) * Math.sqrt(m.a * m.a + m.b * m.b)).toFixed(2) }; });
  out.smallText = await page.evaluate(() => { const seen = {}; for (const e of document.querySelectorAll('body *')) { const r = e.getBoundingClientRect(); if (!r.width || !r.height || !e.textContent.trim() || e.children.length) continue; const s = parseFloat(getComputedStyle(e).fontSize); if (s < 11) seen[s] = (seen[s] || 0) + 1; } return seen; });
  // Poll volume over 10 s.
  const before = requests.length; const t0 = Date.now();
  await page.waitForTimeout(10000);
  out.pollsIn10s = requests.slice(before).filter(r => r.url.includes('/api/events')).length;
  out.videoRetriesIn10s = requests.slice(before).filter(r => r.url.includes('8001')).length;
  out.eventsResponseBytes = responses.slice(-3);
  out.consoleErrors = [];
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})();
