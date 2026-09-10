const { test, expect } = require('@playwright/test');

test('initial view stays inside viewport and radar remains useful', async ({ page }) => {
  await page.goto('/');
  const size = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
  expect(size.document, 'The page must not require horizontal scrolling').toBeLessThanOrEqual(size.width + 1);
  const radar = page.locator('[data-testid="radar"], .radar').first();
  await expect(radar).toBeVisible();
  const bounds = await radar.boundingBox();
  expect(bounds.width).toBeGreaterThanOrEqual(Math.min(300, size.width - 24));
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(size.width + 1);
  const labels = await radar.locator('text').evaluateAll(elements => elements.filter(e => e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })).map(e => {
    const matrix = e.getScreenCTM();
    return { text: e.textContent, renderedPixels: parseFloat(getComputedStyle(e).fontSize) * Math.hypot(matrix.a, matrix.b) };
  }));
  // SVG CSS font-size alone is misleading: viewBox scaling caused 3–6px text.
  expect(labels.length, 'Radar should expose readable reference labels').toBeGreaterThan(0);
  expect(labels.filter(label => label.renderedPixels < 10), 'No visible radar label should shrink below 10 screen pixels').toEqual([]);
});

test('visible controls provide touch sized hit targets', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const small = await page.locator('button:visible, summary:visible, select:visible, [role="button"]:visible').evaluateAll(elements => elements.map(e => {
    const r = e.getBoundingClientRect();
    return { label: e.getAttribute('aria-label') || e.textContent.trim().slice(0, 80), width: r.width, height: r.height };
  }).filter(e => e.width < 43.5 || e.height < 43.5));
  expect(small, 'Important controls need at least 44px touch hit areas').toEqual([]);
});

test('normal load has no runtime, console or failed resource errors', async ({ page }) => {
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('requestfailed', request => requests.push(`${request.url()} ${request.failure()?.errorText}`));
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  expect(errors).toEqual([]);
  expect(requests, 'Demo resources must be available from the serving app').toEqual([]);
});
