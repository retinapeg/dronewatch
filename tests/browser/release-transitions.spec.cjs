const { test, expect } = require('@playwright/test');
const activate = (locator, isMobile) => isMobile ? locator.tap() : locator.click();
const sensor = id => ({ target_id: id, event_id: id, source_kind: 'WEBHOOK_EVENT', source: 'Independent review fixture', status: 'UNKNOWN', confidence: null, position: null, updated_at: '', timestamp_basis: 'receipt_time_only' });
const envelope = targets => ({ schema_version: 1, targets, received_at: new Date().toISOString() });

test('complete ten-target scenario can focus every target and replay without a reload', async ({ page, isMobile }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.clock.install();
  await page.goto('/');
  await activate(page.getByRole('button', { name: 'Pause scenario', exact: true }), isMobile);
  await page.getByLabel('Scenario target count').selectOption('10');
  await activate(page.getByRole('button', { name: 'Resume scenario', exact: true }), isMobile);
  // Execute every timer callback: fastForward skips callbacks and cannot validate playback.
  await page.clock.runFor(91_000);
  await expect(page.locator('#playback-state')).toHaveText('COMPLETE');
  await expect(page.locator('#scenario-time')).toHaveText('01:30');
  await activate(page.getByRole('button', { name: 'Focus selected target', exact: true }), isMobile);
  for (let n = 1; n <= 10; n++) {
    const id = `DW-${String(n).padStart(2, '0')}`;
    await activate(page.getByRole('button', { name: `Select target ${id}`, exact: true }), isMobile);
    await expect(page.locator('.detail-identity h3')).toHaveText(id);
    const marker = page.getByRole('button', { name: `Inspect target ${id}`, exact: true });
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute('aria-pressed', 'true');
    const geometry = await page.evaluate(() => {
      const radar = document.querySelector('#radar').getBoundingClientRect();
      const selected = document.querySelector('.target-marker[aria-pressed="true"]').getBoundingClientRect();
      return { overflow: document.documentElement.scrollWidth - innerWidth, contained: selected.left >= radar.left && selected.right <= radar.right && selected.top >= radar.top && selected.bottom <= radar.bottom };
    });
    expect(geometry).toEqual({ overflow: 0, contained: true });
  }
  await page.screenshot({ path: testInfo.outputPath('completed-ten-target-focus.png'), fullPage: true });
  await activate(page.getByRole('button', { name: 'Resume scenario', exact: true }), isMobile);
  await expect(page.locator('#playback-state')).toHaveText('PLAYING');
  await page.clock.runFor(1250);
  await expect(page.locator('#scenario-time')).toHaveText('00:01');
  await expect(page.locator('.detail-identity h3')).toHaveText('DW-10');
  expect(errors).toEqual([]);
});

test('obsolete first sensor request cannot replace a newer sensor generation', async ({ page, isMobile }) => {
  let releaseOld;
  const oldAllowed = new Promise(resolve => { releaseOld = resolve; });
  let signalStarted;
  const started = new Promise(resolve => { signalStarted = resolve; });
  let calls = 0;
  await page.route('**/api/targets', async route => {
    if (++calls === 1) {
      signalStarted();
      await oldAllowed;
      await route.fulfill({ json: envelope([sensor('OBSOLETE')]) }).catch(() => {});
    } else await route.fulfill({ json: envelope([sensor('CURRENT')]) });
  });
  await page.goto('/?mode=sensor');
  await started;
  await activate(page.getByRole('button', { name: 'Demo mode', exact: true }), isMobile);
  await activate(page.getByRole('button', { name: 'Sensor mode', exact: true }), isMobile);
  await expect(page.locator('.detail-identity h3')).toHaveText('CURRENT');
  releaseOld();
  await page.waitForTimeout(250);
  await expect(page.locator('.detail-identity h3')).toHaveText('CURRENT');
  await expect(page.getByTestId('target-list')).not.toContainText('OBSOLETE');
  await expect(page.locator('#detail-freshness')).toHaveText('Observation time unverified');
  await expect(page.getByRole('button', { name: 'Refresh sensor events', exact: true })).toBeEnabled();
});

test('empty refresh removes a selected observation and its expanded evidence', async ({ page, isMobile }) => {
  let records = [sensor('REMOVED')];
  await page.route('**/api/targets', route => route.fulfill({ json: envelope(records) }));
  await page.goto('/?mode=sensor');
  await expect(page.locator('.detail-identity h3')).toHaveText('REMOVED');
  await activate(page.getByText('Source & interpretation', { exact: true }), isMobile);
  records = [];
  await activate(page.getByRole('button', { name: 'Refresh sensor events', exact: true }), isMobile);
  await expect(page.getByTestId('target-list').getByRole('button')).toHaveCount(0);
  await expect(page.getByTestId('target-detail')).not.toContainText('REMOVED');
  await expect(page.getByTestId('target-detail')).not.toContainText('Independent review fixture');
  await expect(page.locator('#inspect-priority')).toBeDisabled();
  await expect(page.getByTestId('target-detail')).toContainText('Select an observation');
  await activate(page.getByRole('button', { name: 'Demo mode', exact: true }), isMobile);
  await expect(page.getByTestId('target-list').getByRole('button')).toHaveCount(5);
});
