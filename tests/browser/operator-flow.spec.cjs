const { test, expect } = require('@playwright/test');
const activate = async (locator, isMobile) => isMobile ? locator.tap() : locator.click();

async function expectNoOverflow(page) {
  const size = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
  expect(size.document).toBeLessThanOrEqual(size.width + 1);
}

test('five target demo can be inspected, focused, paused and reset by touch', async ({ page, isMobile }, testInfo) => {
  await page.goto('/');
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
  await expect(page.getByText(/Synthetic demo/i).first()).toBeVisible();
  await activate(page.getByRole('button', { name: 'Pause scenario', exact: true }), isMobile);
  await activate(page.getByRole('button', { name: 'Select target DW-03', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('DW-03');
  const distanceFromCentre = () => page.evaluate(() => {
    const radar = document.querySelector('[data-testid="radar"]').getBoundingClientRect();
    const marker = document.querySelector('#marker-layer [aria-pressed="true"]').getBoundingClientRect();
    return Math.hypot((marker.x + marker.width / 2) - (radar.x + radar.width / 2), (marker.y + marker.height / 2) - (radar.y + radar.height / 2));
  });
  const distanceBefore = await distanceFromCentre();
  await activate(page.getByRole('button', { name: 'Focus selected target', exact: true }), isMobile);
  await expect(page.getByRole('button', { name: 'Show all targets', exact: true })).toBeVisible();
  expect(await distanceFromCentre()).toBeLessThan(distanceBefore);
  await expect(page.locator('#world-layer')).toHaveAttribute('transform', /scale\(1\.7\)/);
  await expectNoOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('selected-focus.png'), fullPage: true });
  await activate(page.getByRole('button', { name: 'Show all targets', exact: true }), isMobile);
  await activate(page.getByRole('button', { name: 'Inspect target DW-01', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('DW-01');
  await activate(page.getByRole('button', { name: 'Reset scenario', exact: true }), isMobile);
  await expect(page.getByTestId('scenario-time')).toHaveText('00:00');
  const first = await page.getByTestId('radar').innerHTML();
  await page.waitForTimeout(1200);
  await expect(page.getByTestId('scenario-time')).toHaveText('00:00');
  expect(await page.getByTestId('radar').innerHTML()).toBe(first);
  await activate(page.getByRole('button', { name: 'Resume scenario', exact: true }), isMobile);
  await expect(page.getByTestId('scenario-time')).not.toHaveText('00:00');
  await page.screenshot({ path: testInfo.outputPath('operator-flow.png'), fullPage: true });
});

test('three and ten targets stay selectable and readable', async ({ page, isMobile }, testInfo) => {
  await page.goto('/');
  await activate(page.getByRole('button', { name: 'Pause scenario', exact: true }), isMobile);
  for (const count of [3, 10]) {
    await page.getByLabel('Scenario target count').selectOption(String(count));
    await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(count);
    const id = `DW-${String(count).padStart(2, '0')}`;
    await activate(page.getByRole('button', { name: `Select target ${id}`, exact: true }), isMobile);
    await expect(page.getByTestId('target-detail')).toContainText(id);
    await expectNoOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`${count}-targets.png`), fullPage: true });
  }
});

test('demo remains usable with event API unavailable', async ({ page, isMobile }) => {
  await page.route('**/api/**', route => route.fulfill({ status: 503, json: { detail: 'QA injected backend outage' } }));
  await page.goto('/');
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
  await activate(page.getByRole('button', { name: 'Select target DW-02', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('DW-02');
  await expect(page.getByText(/Synthetic demo/i).first()).toBeVisible();
  await expectNoOverflow(page);
});

test('orientation changes preserve selection and all controls', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'Orientation is a mobile regression');
  await page.goto('/');
  await activate(page.getByRole('button', { name: 'Pause scenario', exact: true }), true);
  await activate(page.getByRole('button', { name: 'Select target DW-04', exact: true }), true);
  await page.setViewportSize({ width: 873, height: 393 });
  await expectNoOverflow(page);
  await expect(page.getByTestId('target-detail')).toContainText('DW-04');
  await page.setViewportSize({ width: 360, height: 800 });
  await expectNoOverflow(page);
  await expect(page.getByTestId('target-detail')).toContainText('DW-04');
  await activate(page.getByRole('button', { name: 'Focus selected target', exact: true }), true);
  await expect(page.getByRole('button', { name: 'Show all targets', exact: true })).toBeVisible();
});

test('page reload keeps the demo usable with external internet unavailable', async ({ page, baseURL, isMobile }) => {
  const origin = new URL(baseURL).origin;
  const external = [], runtime = [];
  page.on('pageerror', error => runtime.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === origin) return route.continue();
    external.push(url.href);
    return route.abort('internetdisconnected');
  });
  await page.goto('/');
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
  await activate(page.getByRole('button', { name: 'Select target DW-05', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('DW-05');
  await page.reload();
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
  await activate(page.getByRole('button', { name: 'Select target DW-02', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('DW-02');
  expect(external, 'The local demo should not request external dependencies').toEqual([]);
  expect(runtime).toEqual([]);
});

test('highest priority target route is visible beyond its touch marker', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Pause scenario', exact: true }).click();
  await page.getByRole('button', { name: 'Reset scenario', exact: true }).click();
  const route = await page.evaluate(() => {
    const marker = document.querySelector('#marker-layer [aria-pressed="true"]').getBoundingClientRect();
    const path = document.querySelector('#path-layer polyline');
    const point = path.getPointAtLength(path.getTotalLength());
    const endpoint = new DOMPoint(point.x, point.y).matrixTransform(path.getScreenCTM());
    return { length: path.getTotalLength() * Math.hypot(path.getScreenCTM().a, path.getScreenCTM().b), endpointOutsideMarker: endpoint.x < marker.left || endpoint.x > marker.right || endpoint.y < marker.top || endpoint.y > marker.bottom };
  });
  expect(route.length).toBeGreaterThan(30);
  expect(route.endpointOutsideMarker, 'Selected-target styling must not hide the complete future path').toBe(true);
  await expect(page.locator('.radar-key')).toContainText(/scripted|scenario/i);
});
