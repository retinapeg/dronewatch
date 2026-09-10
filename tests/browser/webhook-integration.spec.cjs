const { test, expect } = require('@playwright/test');

test('mock webhook reaches the real API and touch detail with honest provenance and age', async ({ page, request, isMobile, baseURL }, testInfo) => {
  // This case writes explicit test events. Never point it at an external service.
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(new URL(baseURL).hostname);
  const id = `boundary-${testInfo.project.name}`;
  const oldTime = new Date(Date.now() - 300_000).toISOString();
  const event = {
    event_id: `${id}-old`, target_id: id, source: 'manual-test',
    label: 'drone', state: 'APPROACHING', confidence: .71, timestamp: oldTime,
    position: { x: .25, y: .4, coordinate_system: 'normalized_frame' },
  };
  const posted = await request.post('/webhook/viso', { data: event });
  expect(posted.status()).toBe(200);
  const response = await request.get('/api/targets');
  expect(response.status()).toBe(200);
  const record = (await response.json()).targets.find(target => target.target_id === id);
  expect(record.source_kind).toBe('TEST_EVENT');
  expect(record.timestamp_basis).toBe('reported_event_time');
  expect(Date.parse(record.updated_at)).toBe(Date.parse(oldTime));
  expect(Date.parse(record.last_received_at)).toBeGreaterThan(Date.parse(oldTime));
  expect(record.velocity).toBeNull();
  expect(record.heading).toBeNull();
  expect(record.raw_payload).toBeUndefined();

  await page.goto('/?mode=sensor');
  const select = page.getByRole('button', { name: `Select target ${id}`, exact: true });
  await (isMobile ? select.tap() : select.click());
  const detail = page.getByTestId('target-detail');
  await expect(detail).toContainText(id);
  await expect(detail).toContainText(/stale observation/i);
  await expect(detail).toContainText('manual-test');
  await expect(page.getByTestId('radar')).toBeHidden();

  expect((await request.post('/webhook/viso', { data: {
    ...event, event_id: `${id}-new`, timestamp: new Date().toISOString(), confidence: .84,
  } })).status()).toBe(200);
  await expect(detail).toContainText('84%', { timeout: 10_000 });
  await expect(detail).toContainText(id);
  await expect(detail).toContainText(/recent observation/i);
  await expect(detail).not.toContainText(/stale observation/i);
});
