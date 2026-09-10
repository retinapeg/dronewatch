const { test, expect } = require('@playwright/test');
const activate = async (locator, isMobile) => isMobile ? locator.tap() : locator.click();
const envelope = targets => ({ schema_version: 1, targets, received_at: new Date().toISOString() });
const sensor = (overrides = {}) => ({
  target_id: 'camera-track-7', event_id: 'qa-evt-1', source_kind: 'SENSOR_EVENT',
  status: 'POSSIBLE THREAT', confidence: .71,
  position: { x: .25, y: .4, coordinate_system: 'normalized_frame' },
  velocity: null, heading: null, source: 'QA mocked Viso camera',
  updated_at: new Date().toISOString(), timestamp_basis: 'reported_event_time', evidence: ['Provider reported an approaching observation.'],
  alternative_interpretation: 'An approaching course does not establish intent.',
  uncertainty: 'No calibrated range or geographical position.', status_basis: 'reported_event', ...overrides,
});
async function openSensor(page, isMobile) {
  await page.goto('/');
  await activate(page.getByRole('button', { name: 'Sensor mode', exact: true }), isMobile);
}

test('empty sensor feed clears synthetic targets and explains the empty state', async ({ page, isMobile }) => {
  await page.route('**/api/targets', route => route.fulfill({ json: envelope([]) }));
  await openSensor(page, isMobile);
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(0);
  await expect(page.getByTestId('sensor-status')).toContainText(/empty|no .*observations|no .*targets|no .*events|waiting/i);
  await expect(page.getByTestId('target-detail')).not.toContainText('DW-01');
  await activate(page.getByRole('button', { name: 'Demo mode', exact: true }), isMobile);
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
});

test('old mocked Viso observation remains stale when server response is fresh', async ({ page, isMobile }) => {
  await page.route('**/api/targets', route => route.fulfill({ json: envelope([sensor({ updated_at: new Date(Date.now() - 300_000).toISOString() })]) }));
  await openSensor(page, isMobile);
  await activate(page.getByRole('button', { name: 'Select target camera-track-7', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText(/stale observation/i);
  await expect(page.getByTestId('target-detail')).toContainText('QA mocked Viso camera');
  await expect(page.getByTestId('target-detail')).not.toContainText(/recent observation/i);
});

test('malformed API response reports a failure without inventing targets', async ({ page, isMobile }) => {
  const runtime = [];
  page.on('pageerror', error => runtime.push(error.message));
  await page.route('**/api/targets', route => route.fulfill({ json: { schema_version: 1, targets: [{ target_id: 'bad', confidence: 'certain' }] } }));
  await openSensor(page, isMobile);
  await expect(page.getByTestId('sensor-status')).toContainText(/unavailable|malformed|offline|error|retry|invalid/i);
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(0);
  expect(runtime).toEqual([]);
  await activate(page.getByRole('button', { name: 'Demo mode', exact: true }), isMobile);
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
});

test('backend outage is explicit and recovers without losing selected target', async ({ page, isMobile }) => {
  let outage = false, version = 1;
  await page.route('**/api/targets', route => outage
    ? route.fulfill({ status: 503, json: { detail: 'QA simulated backend restart' } })
    : route.fulfill({ json: envelope([sensor(), sensor({ target_id: 'camera-track-8', event_id: `qa-${version}`, confidence: version === 1 ? .63 : .84 })]) }));
  await openSensor(page, isMobile);
  await activate(page.getByRole('button', { name: 'Select target camera-track-8', exact: true }), isMobile);
  await expect(page.getByTestId('target-detail')).toContainText('camera-track-8');
  outage = true;
  await expect(page.getByTestId('sensor-status')).toContainText(/unavailable|offline|lost|error|retry/i, { timeout: 10_000 });
  await expect(page.getByTestId('target-detail')).toContainText('camera-track-8');
  outage = false; version = 2;
  await expect(page.getByTestId('target-detail')).toContainText('84%', { timeout: 10_000 });
  await expect(page.getByTestId('target-detail')).toContainText('camera-track-8');
});

test('delayed sensor response cannot overwrite a return to synthetic mode', async ({ page, isMobile }) => {
  let pending;
  const requestStarted = new Promise(resolve => { pending = resolve; });
  let release;
  const responseAllowed = new Promise(resolve => { release = resolve; });
  await page.route('**/api/targets', async route => {
    pending();
    await responseAllowed;
    await route.fulfill({ json: envelope([sensor()]) }).catch(() => {});
  });
  await openSensor(page, isMobile);
  await requestStarted;
  await activate(page.getByRole('button', { name: 'Demo mode', exact: true }), isMobile);
  release();
  await page.waitForTimeout(500);
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(5);
  await expect(page.getByTestId('target-list')).not.toContainText('camera-track-7');
});

test('sensor mode deep link and reload never show synthetic fallback targets', async ({ page }) => {
  await page.route('**/api/targets', route => route.fulfill({ json: envelope([sensor()]) }));
  await page.goto('/?mode=sensor');
  await expect(page.getByRole('button', { name: 'Sensor mode', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('target-list').getByRole('button', { name: /^Select target/ })).toHaveCount(1);
  await expect(page.getByTestId('target-list')).toContainText('camera-track-7');
  await expect(page.getByTestId('radar')).toBeHidden();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sensor mode', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('target-list')).toContainText('camera-track-7');
  await expect(page.getByTestId('target-detail')).not.toContainText('DW-01');
});

test('sensor details keep keyboard focus and expanded evidence across polling', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One desktop check covers detail-node focus persistence.');
  let responses = 0;
  await page.route('**/api/targets', route => { responses++; return route.fulfill({ json: envelope([sensor()]) }); });
  await page.goto('/?mode=sensor');
  const summary = page.getByText('Source & interpretation', { exact: true });
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(summary).toBeFocused();
  await expect.poll(() => responses, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(200);
  await expect(summary).toBeFocused();
  await expect(page.getByTestId('target-detail').getByText('QA mocked Viso camera', { exact: false })).toBeVisible();
});

test('long valid sensor identifiers and literal evidence cannot break the layout or execute HTML', async ({ page, isMobile }) => {
  const targetId = 'Z'.repeat(256);
  const literalHTML = '<img src="/qa-nope.png" onerror="window.__qaInjected=true">';
  await page.route('**/api/targets', route => route.fulfill({ json: envelope([sensor({ target_id: targetId, source: 'Long camera source '.repeat(24), evidence: [literalHTML], uncertainty: { unexpected: 'object' } })]) }));
  await openSensor(page, isMobile);
  await activate(page.getByRole('button', { name: `Select target ${targetId}`, exact: true }), isMobile);
  const summary = page.getByText('Source & interpretation', { exact: true });
  await activate(summary, isMobile);
  await expect(page.getByTestId('target-detail')).toContainText(targetId);
  await expect(page.getByTestId('target-detail')).toContainText(literalHTML);
  const state = await page.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth, injected: window.__qaInjected === true, image: !!document.querySelector('img[src="/qa-nope.png"]') }));
  expect(state.documentWidth).toBeLessThanOrEqual(state.width + 1);
  expect(state.injected).toBe(false);
  expect(state.image).toBe(false);
});
