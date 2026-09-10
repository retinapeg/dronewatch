/* Local Chromium observations, not physical Android or real-device CPU claims. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

async function run() {
  const baseURL = process.env.DRONEWATCH_BASE_URL || 'http://127.0.0.1:8000';
  const output = process.env.DRONEWATCH_BENCHMARK_OUTPUT || 'docs/evidence/final/performance.json';
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const [name, viewport, mobile, slowdown] of [
      ['android-360-throttled', { width: 360, height: 800 }, true, 4],
      ['desktop', { width: 1440, height: 1000 }, false, 1],
    ]) {
      const context = await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1 });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(() => {
        window.__longTasks = [];
        new PerformanceObserver(list => {
          for (const entry of list.getEntries()) window.__longTasks.push(entry.duration);
        }).observe({ type: 'longtask', buffered: true });
      });
      const cdp = await context.newCDPSession(page);
      await cdp.send('Performance.enable');
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: slowdown });
      await page.goto(baseURL, { waitUntil: 'networkidle' });
      await page.getByLabel('Scenario target count').selectOption('10');
      await page.waitForTimeout(1500);
      const metrics = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m => [m.name, m.value]));
      const before = await metrics();
      const domBefore = await page.locator('*').count();
      await page.waitForTimeout(6000);
      const after = await metrics();
      const interactionTimes = [];
      for (const id of ['DW-02', 'DW-05', 'DW-10', 'DW-01']) {
        const start = performance.now();
        const button = page.getByRole('button', { name: `Select target ${id}`, exact: true });
        await (mobile ? button.tap() : button.click());
        await page.getByTestId('target-detail').getByText(id, { exact: true }).first().waitFor();
        interactionTimes.push({ id, milliseconds: Math.round(performance.now() - start) });
      }
      const longTasks = await page.evaluate(() => window.__longTasks);
      results.push({
        name, viewport, chromiumCPUThrottleRate: slowdown, targetCount: 10,
        sampleSeconds: after.Timestamp - before.Timestamp,
        taskSeconds: after.TaskDuration - before.TaskDuration,
        scriptSeconds: after.ScriptDuration - before.ScriptDuration,
        layoutSeconds: after.LayoutDuration - before.LayoutDuration,
        domElementsBefore: domBefore, domElementsAfter: await page.locator('*').count(),
        heapBytesBefore: before.JSHeapUsedSize, heapBytesAfter: after.JSHeapUsedSize,
        longTaskCountIncludingLoad: longTasks.length,
        longestTaskMilliseconds: Math.max(0, ...longTasks), interactionTimes,
        pageErrors: errors,
      });
      if (errors.length) throw new Error(`Runtime errors: ${errors.join('; ')}`);
      await context.close();
    }
  } finally {
    await browser.close();
  }
  const report = {
    capturedAt: new Date().toISOString(), baseURL,
    method: 'Desktop Chromium with optional touch/viewport and 4x CPU throttling. TaskDuration is browser task time, not a phone CPU or battery measurement. Interaction timing includes automation/scroll overhead. Heap changes over six seconds do not establish absence of a memory leak.',
    results,
  };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify(report, null, 2));
}

run().catch(error => { console.error(error); process.exitCode = 1; });
