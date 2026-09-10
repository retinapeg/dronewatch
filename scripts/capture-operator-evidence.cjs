const { chromium } = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const baseURL = process.env.DRONEWATCH_BASE_URL || 'http://127.0.0.1:8000';
const output = path.resolve(process.env.DRONEWATCH_EVIDENCE_DIR || 'test-results/operator-evidence');
const viewports = [
  { name: 'android-360', width: 360, height: 800, mobile: true },
  { name: 'android-393', width: 393, height: 873, mobile: true },
  { name: 'android-412', width: 412, height: 915, mobile: true },
  { name: 'android-landscape', width: 873, height: 393, mobile: true },
  { name: 'desktop', width: 1440, height: 1000, mobile: false },
];
(async () => {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, isMobile: viewport.mobile, hasTouch: viewport.mobile, deviceScaleFactor: 1, reducedMotion: 'reduce', ...(viewport.mobile ? { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36' } : {}) });
    const page = await context.newPage();
    const errors = [], measurements = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    const activate = locator => viewport.mobile ? locator.tap() : locator.click();
    const capture = async state => {
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.screenshot({ path: path.join(output, `${viewport.name}-${state}.png`), fullPage: true });
      const dimensions = await page.evaluate(() => {
        const radar = document.querySelector('[data-testid="radar"]');
        const r = radar.getBoundingClientRect();
        const controls = [...document.querySelectorAll('button, summary, select')].filter(e => e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })).map(e => { const b = e.getBoundingClientRect(); return { label: e.getAttribute('aria-label') || e.textContent.trim(), width: b.width, height: b.height }; });
        return { viewportWidth: innerWidth, documentWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight, radar: { x: r.x, y: r.y, width: r.width, height: r.height }, smallestControlWidth: Math.min(...controls.map(c => c.width)), smallestControlHeight: Math.min(...controls.map(c => c.height)), smallControls: controls.filter(c => c.width < 43.5 || c.height < 43.5), targetCount: document.querySelectorAll('[data-testid="target-list"] button').length, selectedTarget: document.querySelector('[data-testid="target-list"] [aria-pressed="true"]')?.dataset.targetId || null, scenarioTime: document.querySelector('[data-testid="scenario-time"]').textContent };
      });
      measurements.push({ state, ...dimensions });
    };
    await page.goto(baseURL);
    await activate(page.getByRole('button', { name: 'Pause scenario', exact: true }));
    await activate(page.getByRole('button', { name: 'Reset scenario', exact: true }));
    await capture('default-five');
    await activate(page.getByRole('button', { name: 'Select target DW-03', exact: true }));
    await activate(page.getByRole('button', { name: 'Focus selected target', exact: true }));
    await capture('selected-focus');
    await activate(page.getByRole('button', { name: 'Show all targets', exact: true }));
    for (const count of [3, 10]) {
      await page.getByLabel('Scenario target count').selectOption(String(count));
      await activate(page.getByRole('button', { name: `Select target DW-${String(count).padStart(2, '0')}`, exact: true }));
      await capture(`${count}-targets`);
    }
    await page.route('**/api/targets', route => route.fulfill({ json: { schema_version: 1, targets: [], received_at: new Date().toISOString() } }));
    await activate(page.getByRole('button', { name: 'Sensor mode', exact: true }));
    await page.getByTestId('sensor-status').filter({ hasText: /No sensor observations/i }).waitFor();
    await capture('empty-sensor');
    results.push({ viewport: viewport.name, measurements, errors });
    await context.close();
  }
  await browser.close();
  const report = { capturedAt: new Date().toISOString(), baseURL, candidate: process.env.DRONEWATCH_CANDIDATE || 'Source revision not supplied', method: 'Desktop Chromium; Android touch and viewport emulation. Reduced-motion screenshots at paused scenario time 00:00. Empty sensor response is a QA mock.', results };
  await fs.writeFile(path.join(output, 'measurements.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
