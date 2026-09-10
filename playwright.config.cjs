const { defineConfig } = require('@playwright/test');
const baseURL = process.env.DRONEWATCH_BASE_URL || 'http://127.0.0.1:8012';
const shellQuote = value => "'" + value.replace(/'/g, "'\\''") + "'";
const mobile = { isMobile: true, hasTouch: true, deviceScaleFactor: 1, userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36' };
module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 20_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }], ['json', { outputFile: process.env.DRONEWATCH_TEST_REPORT || 'test-results/results.json' }]],
  use: { baseURL, browserName: 'chromium', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'android-360', use: { ...mobile, viewport: { width: 360, height: 800 } } },
    { name: 'android-393', use: { ...mobile, viewport: { width: 393, height: 873 } } },
    { name: 'android-412', use: { ...mobile, viewport: { width: 412, height: 915 } } },
    { name: 'android-landscape', use: { ...mobile, viewport: { width: 873, height: 393 } } },
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 }, isMobile: false, hasTouch: false } },
  ],
  ...(process.env.DRONEWATCH_BASE_URL ? {} : { webServer: {
    command: `${shellQuote(process.env.DRONEWATCH_PYTHON || '.venv/bin/python')} -m uvicorn main:app --host 127.0.0.1 --port 8012`,
    url: baseURL + '/health', reuseExistingServer: !process.env.CI,
    env: { DRONEWATCH_DB_PATH: 'test-results/browser.sqlite3', DRONEWATCH_SIMULATION: '0' },
    timeout: 30_000,
  } }),
});
