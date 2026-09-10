const { test, expect } = require('@playwright/test');
const record = (source, target_id = 'shared-track') => ({
  target_id, source, source_kind: 'WEBHOOK_EVENT', status: 'UNKNOWN', confidence: .5,
  updated_at: new Date().toISOString(), timestamp_basis: 'reported_event_time',
  position: null, evidence: [], uncertainty: 'Source report not independently verified.'
});

test('same target ID from different sources has distinct visible and accessible selection', async ({ page }) => {
  await page.route('**/api/targets', route => route.fulfill({ json: { schema_version: 1, targets: [record('camera-north'), record('camera-south')] } }));
  await page.goto('/?mode=sensor');
  const north = page.getByRole('button', { name: 'Select target shared-track from camera-north (Unverified webhook)', exact: true });
  const south = page.getByRole('button', { name: 'Select target shared-track from camera-south (Unverified webhook)', exact: true });
  await expect(north).toContainText('Source: camera-north');
  await expect(south).toContainText('Source: camera-south');
  await south.click();
  await expect(south).toHaveAttribute('aria-pressed', 'true');
  await expect(north).toHaveAttribute('aria-pressed', 'false');
  await page.getByText('Source & interpretation', { exact: true }).click();
  await expect(page.getByTestId('target-detail')).toContainText('WEBHOOK_EVENT · camera-south');
});

test('colon-bearing source identity tuples preserve independently selectable records', async ({ page }) => {
  await page.route('**/api/targets', route => route.fulfill({ json: { schema_version: 1, targets: [record('camera:west', 'track1'), record('camera', 'west:track1')] } }));
  await page.goto('/?mode=sensor');
  await expect(page.getByTestId('target-list').getByRole('button')).toHaveCount(2);
  const first = page.getByRole('button', { name: 'Select target track1', exact: true });
  const second = page.getByRole('button', { name: 'Select target west:track1', exact: true });
  await second.click();
  await expect(second).toHaveAttribute('aria-pressed', 'true');
  await expect(first).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('target-detail').locator('h3')).toHaveText('west:track1');
});

test('unchanged failure retries do not rewrite the screen-reader status announcement', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/targets', route => { requests++; return route.fulfill({ status: 503, json: { error: 'offline' } }); });
  await page.goto('/?mode=sensor');
  await expect(page.locator('#sensor-notice')).toBeVisible();
  await page.evaluate(() => {
    window.statusMutations = 0;
    window.statusObserver = new MutationObserver(changes => { window.statusMutations += changes.length; });
    window.statusObserver.observe(document.getElementById('sensor-notice'), { childList: true, characterData: true, subtree: true });
  });
  await page.getByRole('button', { name: 'Refresh sensor events', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThanOrEqual(2);
  await expect(page.getByRole('button', { name: 'Refresh sensor events', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => window.statusMutations)).toBe(0);
});

test('a truncated canonical window is labelled without becoming a connection failure', async ({ page }) => {
  let limited = true;
  await page.route('**/api/targets', route => route.fulfill({ json: { schema_version: 1, truncated: limited, targets: [record('camera-north', 'unique-track')] } }));
  await page.goto('/?mode=sensor');
  await expect(page.locator('#sensor-window-notice')).toBeVisible();
  await expect(page.locator('#sensor-window-notice')).toContainText('Showing a limited window of stored observations');
  await expect(page.locator('#sensor-notice')).toBeHidden();
  await expect(page.getByTestId('target-list').getByRole('button')).toHaveCount(1);
  limited = false;
  await page.getByRole('button', { name: 'Refresh sensor events', exact: true }).click();
  await expect(page.locator('#sensor-window-notice')).toBeHidden();
  await expect(page.locator('#sensor-notice')).toBeHidden();
});
