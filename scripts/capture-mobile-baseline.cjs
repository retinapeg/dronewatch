const { chromium } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const baseURL = process.env.DRONEWATCH_BASE_URL || 'http://127.0.0.1:8011';
const output = path.resolve(process.env.DRONEWATCH_EVIDENCE_DIR || 'docs/evidence/baseline');
const viewports = [
  { name: 'android-360', width: 360, height: 800, mobile: true },
  { name: 'android-393', width: 393, height: 873, mobile: true },
  { name: 'android-412', width: 412, height: 915, mobile: true },
  { name: 'android-landscape', width: 873, height: 393, mobile: true },
  { name: 'desktop', width: 1440, height: 1000, mobile: false },
];
async function measure(page) {
  return page.evaluate(() => {
    const visible = element => { const r = element.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const rect = element => { const r = element.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }; };
    return {
      viewport: { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight },
      overflow: [...document.querySelectorAll('body *')].filter(visible).filter(e => { const r = e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; }).slice(0, 25).map(e => ({ selector: e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + e.className, ...rect(e), text: (e.textContent || '').trim().slice(0, 100) })),
      smallControls: [...document.querySelectorAll('button, summary, input, [role="button"]')].filter(visible).filter(e => { const r = e.getBoundingClientRect(); return r.width < 44 || r.height < 44; }).map(e => ({ selector: e.id ? '#' + e.id : e.tagName.toLowerCase(), ...rect(e), text: (e.textContent || '').trim().slice(0, 80) })),
      radar: document.querySelector('.radar') ? rect(document.querySelector('.radar')) : null,
      labels: [...document.querySelectorAll('.radar text')].filter(visible).map(e => { const m = e.getScreenCTM(); return { text: e.textContent, cssFont: getComputedStyle(e).fontSize, renderedFont: parseFloat(getComputedStyle(e).fontSize) * Math.sqrt(m.a * m.a + m.b * m.b) }; }),
      demoControlsHidden: document.querySelector('#demo-controls')?.hidden,
      videoURL: document.querySelector('video')?.currentSrc || null,
    };
  });
}
(async () => {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, isMobile: viewport.mobile, hasTouch: viewport.mobile, deviceScaleFactor: 1, ...(viewport.mobile ? { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36' } : {}) });
    const page = await context.newPage();
    const errors = [], failedRequests = [];
    page.on('pageerror', e => errors.push({ kind: 'runtime', message: e.message }));
    page.on('console', e => { if (e.type() === 'error') errors.push({ kind: 'console', message: e.text() }); });
    page.on('requestfailed', r => failedRequests.push({ url: r.url(), error: r.failure()?.errorText }));
    await page.goto(baseURL, { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(output, `${viewport.name}-initial.png`), fullPage: true });
    const initial = await measure(page);
    // Enable the existing local browser scenario through its public config boundary.
    // Production default above is captured unmodified; this allows a separate touch audit.
    await page.route('**/api/config', route => route.fulfill({ json: { simulation_enabled: true } }));
    await page.reload({ waitUntil: 'networkidle' });
    const activate = async locator => viewport.mobile ? locator.tap() : locator.click();
    await activate(page.locator('#demo-controls > summary'));
    await page.screenshot({ path: path.join(output, `${viewport.name}-controls.png`), fullPage: true });
    const controls = await measure(page);
    await activate(page.locator('#run-demo'));
    await page.waitForTimeout(3500);
    await page.locator('.radar').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `${viewport.name}-scenario.png`), fullPage: true });
    const scenario = await measure(page);
    results.push({ name: viewport.name, initial, controls, scenario, errors, failedRequests });
    await context.close();
  }
  await browser.close();
  await fs.writeFile(path.join(output, 'measurements.json'), JSON.stringify({ capturedAt: new Date().toISOString(), baseURL, description: 'Desktop Chromium with Android viewport/user-agent/touch emulation; not a physical Android device.', results }, null, 2));
  console.log(JSON.stringify(results.map(r => ({ name: r.name, initial: r.initial.viewport, overflow: r.initial.overflow, smallControls: r.initial.smallControls, labels: r.initial.labels, demoControlsHidden: r.initial.demoControlsHidden, errors: r.errors, failedRequests: r.failedRequests })), null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
