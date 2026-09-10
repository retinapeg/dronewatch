const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const path = require('node:path');

// Exercise the real ingestion/normalization code in an isolated temporary DB.
// The running demonstration database receives no writes from this test.
const normalizeThroughAPI = String.raw`
import os, tempfile, json
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='dronewatch-browser-ingestion-') as temp:
    os.environ['DRONEWATCH_DB_PATH'] = str(Path(temp) / 'qa.sqlite3')
    from fastapi.testclient import TestClient
    import main
    assert str(main.DB_PATH).startswith(temp)
    with TestClient(main.app) as client:
        samples = [
            {'event_id':'QA-NORMALIZED-001','tracking_id':'QA-CANONICAL','source':'QA mocked Viso camera','appId':'qa-app','incidentId':'qa-incident','timestamp':'2000-01-01T00:00:00Z','label':'drone','confidence':.88,'state':'approaching','position':{'x':0,'y':.4}},
            {'event_id':'QA-NO-TIME-002','tracking_id':'QA-RECEIPT-ONLY','source':'QA mocked Viso camera','label':'drone','state':'detected','confidence':.72}
        ]
        for sample in samples:
            assert client.post('/webhook/viso', json=sample).status_code == 200
        response = client.get('/api/targets')
        assert response.status_code == 200
        print(json.dumps(response.json()))
`;

test('actual webhook normalization retains provenance and event-time uncertainty in the browser', async ({ page, isMobile }, testInfo) => {
  const sourceRoot = path.resolve(process.env.DRONEWATCH_SOURCE_ROOT || process.cwd());
  const python = process.env.DRONEWATCH_PYTHON || path.join(sourceRoot, '.venv/bin/python');
  const payload = JSON.parse(execFileSync(python, ['-c', normalizeThroughAPI], { cwd: sourceRoot, encoding: 'utf8', timeout: 10_000 }));
  const stale = payload.targets.find(target => target.target_id === 'QA-CANONICAL');
  const unknownTime = payload.targets.find(target => target.target_id === 'QA-RECEIPT-ONLY');
  expect(stale.timestamp_basis).toBe('reported_event_time');
  expect(stale.source_kind).toBe('WEBHOOK_EVENT');
  expect(stale.position).toEqual({ x: 0, y: .4, coordinate_system: 'normalized_frame' });
  expect(unknownTime.timestamp_basis).toBe('receipt_time_only');
  expect(unknownTime.updated_at).toBe('');
  await testInfo.attach('actual-normalized-webhooks', { body: JSON.stringify(payload, null, 2), contentType: 'application/json' });
  await page.route('**/api/targets', route => route.fulfill({ json: payload }));
  await page.goto('/?mode=sensor');
  const activate = locator => isMobile ? locator.tap() : locator.click();
  await activate(page.getByRole('button', { name: 'Select target QA-RECEIPT-ONLY', exact: true }));
  await expect(page.getByTestId('target-detail')).toContainText('Observation time unverified');
  await activate(page.getByRole('button', { name: 'Select target QA-CANONICAL', exact: true }));
  await expect(page.getByTestId('target-detail')).toContainText('Stale observation');
  await expect(page.getByTestId('target-detail')).toContainText('x 0.000, y 0.400');
  await expect(page.getByTestId('target-detail')).toContainText('WEBHOOK_EVENT');
  await expect(page.getByTestId('radar')).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath('actual-ingestion.png'), fullPage: true });
});
