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
  await activate(page.getByRole('button', { name: 'Focus selected target', exact: true }), isMobile);
  await expect(page.getByRole('button', { name: 'Show all targets', exact: true })).toBeVisible();
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
