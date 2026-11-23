// The hosted static pages answer the operator view's requests from recorded files.
// These run the shim that scripts/build_site_pages.py puts at the top of each page.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SITE = path.join(__dirname, '..', 'site');

// Load a page's shim with a stand-in for the browser's fetch that records what was asked for.
function load(page, respond) {
  const html = fs.readFileSync(path.join(SITE, page), 'utf8');
  const source = html.match(/<head>\s*<script>([\s\S]*?)<\/script>/)[1];
  const asked = [];
  const window = {
    fetch: async (url) => {
      asked.push(String(url));
      return respond ? respond(String(url), asked.length) : new Response(JSON.stringify({ file: String(url) }), { status: 200 });
    },
  };
  vm.runInNewContext(source, { window, location: { origin: 'https://example.test' }, URL, Response, Promise, JSON, Math, parseFloat, String, Error });
  return { fetch: window.fetch, asked };
}

for (const [page, base] of [['index.html', ''], ['preview/index.html', '../']]) {
  test(`${page}: a replay request is answered by its recorded file`, async () => {
    const { fetch, asked } = load(page);
    await fetch('/api/preview/tracks?name=operator_demo_signal_loss&seed=42&count=10&mode=radar_off_30s_viso');
    assert.deepEqual(asked, [`${base}api/tracks__operator_demo_signal_loss__42__10__radar_off_30s_viso.json`]);
    assert.ok(fs.existsSync(path.join(SITE, 'api', 'tracks__operator_demo_signal_loss__42__10__radar_off_30s_viso.json')));
  });

  test(`${page}: a path-cloud request is answered by the cloud recorded for that two seconds`, async () => {
    // Build the request from a cloud that exists, at both ends of its two-second window.
    const file = fs.readdirSync(path.join(SITE, 'api', 'paths')).sort()[0];
    const [name, seed, count, mode, track, bucket] = file.replace(/\.json$/, '').split('__');
    for (const t of [Number(bucket) * 2, Number(bucket) * 2 + 1.9]) {
      const { fetch, asked } = load(page);
      await fetch(`/api/preview/paths?name=${name}&seed=${seed}&count=${count}&mode=${mode}&track=${track}&t=${t}&paths=140&horizon_s=20`);
      assert.deepEqual(asked, [`${base}api/paths/${file}`]);
    }
  });

  test(`${page}: the status files are fetched once however often the page polls`, async () => {
    const { fetch, asked } = load(page);
    for (let i = 0; i < 20; i += 1) {
      const camera = await (await fetch('/api/camera/status', { cache: 'no-store' })).json();
      const viso = await (await fetch('/api/preview/viso/status')).json();
      assert.equal(camera.file, `${base}api/camera_status.json`);
      assert.equal(viso.file, `${base}api/viso_status.json`);
    }
    assert.deepEqual(asked.sort(), [`${base}api/camera_status.json`, `${base}api/viso_status.json`]);
  });
}

test('a status file that failed to load is asked for again on the next poll', async () => {
  const { fetch, asked } = load('index.html', (url, n) => (n === 1
    ? new Response('missing', { status: 404 })
    : new Response(JSON.stringify({ state: 'NOT CONFIGURED' }), { status: 200 })));
  await assert.rejects(fetch('/api/preview/viso/status'));
  assert.deepEqual(await (await fetch('/api/preview/viso/status')).json(), { state: 'NOT CONFIGURED' });
  assert.equal(asked.length, 2);
});

test('camera results come back empty without any request', async () => {
  const { fetch, asked } = load('index.html');
  const reply = await fetch('/api/preview/viso/evidence?name=operator_demo&seed=42&count=6&mode=normal&t=43');
  assert.equal(reply.ok, true);
  assert.deepEqual(await reply.json(), { results: [], uncorrelated_results: [], pending_count: 0, static_demo: true });
  assert.deepEqual(asked, []);
});

test('anything else is passed through unchanged', async () => {
  const { fetch, asked } = load('preview/index.html');
  await fetch('../assets/drone-types.png');
  assert.deepEqual(asked, ['../assets/drone-types.png']);
});
