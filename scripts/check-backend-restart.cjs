/* Actual process-restart acceptance, using a private temporary SQLite database. */
const { chromium, expect } = require('@playwright/test');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { setTimeout: delay } = require('node:timers/promises');

(async () => {
  const root = path.resolve(__dirname, '..');
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'dronewatch-restart-'));
  const output = path.resolve(process.env.DRONEWATCH_RESTART_EVIDENCE || path.join(root, 'test-results/backend-restart'));
  fs.mkdirSync(output, { recursive: true });
  const reservation = net.createServer();
  reservation.listen(0, '127.0.0.1'); await once(reservation, 'listening');
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const baseURL = 'http://127.0.0.1:' + port;
  let server, browser;
  const serverLog = fs.openSync(path.join(temporary, 'server.log'), 'a');
  const stop = async () => {
    if (!server || !server.pid || server.exitCode !== null) return;
    const exited = once(server, 'exit'); server.kill('SIGTERM');
    await Promise.race([exited, delay(5000).then(() => { if (server.exitCode === null) server.kill('SIGKILL'); })]);
    if (server.exitCode === null) await exited;
  };
  const start = async () => {
    server = spawn(process.env.DRONEWATCH_PYTHON || path.join(root, '.venv/bin/python'),
      ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(port)],
      { cwd: root, env: { ...process.env, DRONEWATCH_DB_PATH: path.join(temporary, 'events.db'), DRONEWATCH_SIMULATION: '0' }, stdio: ['ignore', serverLog, serverLog] });
    let startupError; server.once('error', error => { startupError = error; });
    for (let n = 0; n < 100; n++) {
      if (startupError) throw startupError;
      if (server.exitCode !== null) throw new Error('Private test server exited during startup');
      try { if ((await fetch(baseURL + '/health')).ok) return; } catch {}
      await delay(100);
    }
    throw new Error('Private test server did not become ready');
  };
  const post = async (id, confidence) => {
    const response = await fetch(baseURL + '/webhook/viso', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ event_id: id, target_id: 'restart-test', source: 'manual-test', is_test: true,
        label: 'drone', state: 'APPROACHING', confidence, timestamp: new Date().toISOString() }) });
    expect(response.status).toBe(200);
  };
  const result = { candidate: process.env.DRONEWATCH_CANDIDATE || 'unspecified', method: 'Real private Uvicorn termination/restart and persisted temporary SQLite, with 360x800 Chromium touch emulation; no mocked HTTP responses.', steps: [], runtimeErrors: [], expectedNetworkErrors: [] };
  try {
    await start(); await post('restart-before', .71);
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    page.on('pageerror', error => result.runtimeErrors.push(error.message));
    page.on('requestfailed', request => result.expectedNetworkErrors.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText }));
    await page.goto(baseURL + '/?mode=sensor');
    await page.getByRole('button', { name: 'Select target restart-test', exact: true }).tap();
    await expect(page.locator('#detail-freshness')).toHaveText('Recent observation');
    await page.locator('#source-interpretation-toggle').tap();
    await expect(page.locator('#interpretation')).toHaveAttribute('open', '');
    result.steps.push('Initial actual webhook record selected with recent source timestamp');
    await stop();
    await expect(page.locator('#detail-freshness')).toHaveText('Cached · connection unavailable', { timeout: 12000 });
    await expect(page.locator('#interpretation')).toHaveAttribute('open', '');
    await page.screenshot({ path: path.join(output, 'android-360-backend-down.png'), fullPage: true });
    result.steps.push('Server termination visibly marks the selected observation cached and preserves expanded evidence');
    await page.getByRole('button', { name: 'Demo mode', exact: true }).tap();
    await page.getByLabel('Scenario target count').selectOption('10');
    await page.getByRole('button', { name: 'Select target DW-10', exact: true }).tap();
    await page.getByRole('button', { name: 'Focus selected target', exact: true }).tap();
    await expect(page.locator('#target-list button')).toHaveCount(10);
    result.steps.push('Ten-target synthetic demo remains touch-selectable and focusable with backend stopped');
    await page.getByRole('button', { name: 'Sensor mode', exact: true }).tap();
    await expect(page.locator('#detail-freshness')).toHaveText('Cached · connection unavailable');
    await start();
    const persisted = await (await fetch(baseURL + '/api/targets')).json();
    expect(persisted.targets.find(target => target.target_id === 'restart-test').confidence).toBe(.71);
    await post('restart-after', .84);
    await expect(page.getByTestId('target-detail')).toContainText('84%', { timeout: 12000 });
    await expect(page.locator('#detail-freshness')).toHaveText('Recent observation');
    await expect(page.locator('#target-list [aria-pressed="true"]')).toHaveAttribute('data-target-id', 'restart-test');
    await expect(page.locator('#sensor-notice')).toBeHidden();
    await page.screenshot({ path: path.join(output, 'android-360-backend-restored.png'), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(360);
    expect(result.runtimeErrors).toEqual([]);
    result.steps.push('Restart retains SQLite history and automatically restores fresh selected detail without reload or overflow');
    result.passed = true;
  } finally {
    if (browser) await browser.close();
    await stop(); fs.closeSync(serverLog);
    result.completedAt = new Date().toISOString();
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    fs.rmSync(temporary, { recursive: true, force: true });
  }
  console.log(JSON.stringify(result, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
