const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'camera.html'), 'utf8');
const source = html.match(/<script id="camera-core">([\s\S]*?)<\/script>/)[1];
const camera = vm.runInThisContext(`(()=>{${source}\nreturn CAMERA;})()`);

test('connection probes never turn an empty analysis feed into detections', () => {
  const state = camera.feedState({configured: true, delivery_count: 2, probe_count: 2, results: []});
  assert.equal(state.label, 'Waiting');
  assert.equal(state.mapped, 0);
});

test('synthetic sender callbacks cannot be displayed as Viso incident results', () => {
  const results = [
    {id: 1, outcome: 'MAPPED', synthetic_sender: true},
    {id: 2, outcome: 'MAPPED', synthetic_sender: false},
    {id: 3, outcome: 'UNMAPPED', synthetic_sender: false},
  ];
  assert.deepEqual(camera.visibleResults(results).map(result => result.id), [2, 3]);
  assert.equal(camera.feedState({results}).mapped, 1);
  assert.equal(camera.feedState({results}).unmapped, 1);
});

test('unrecognised callback produces needs-mapping state and zero incident results', () => {
  const state = camera.feedState({results: [{outcome: 'UNMAPPED', summary: 'Drone detected'}]});
  assert.equal(state.label, 'Needs mapping');
  assert.equal(state.mapped, 0);
  assert.equal(state.unmapped, 1);
});

test('media and download links reject executable, external, and escaping URLs', () => {
  for (const url of ['javascript:alert(1)', 'https://example.org/a.mp4', '//example.org/a.mp4', '/api/camera/media/../../secrets', '/api/camera/media/../status', '/api/camera/media/\\evil.mp4']) {
    assert.equal(camera.sourceUrl(url), null, url);
  }
  assert.equal(camera.sourceUrl('/api/camera/media/clip-02.mp4'), '/api/camera/media/clip-02.mp4');
});

test('player chooses video assets over their still-image posters', () => {
  const media = ['clip-02.png', 'clip-02.mp4'].map(filename => ({id:filename,filename,url:'/api/camera/media/'+filename}));
  assert.deepEqual(camera.mediaItems(media).map(item => item.filename), ['clip-02.mp4']);
  assert.deepEqual(camera.mediaItems([media[0]]).map(item => item.filename), ['clip-02.png']);
});

test('missing receipt timestamps stay unknown and future clock skew never shows negative age', () => {
  assert.equal(camera.ageLabel(null), '—');
  assert.equal(camera.ageLabel('bad timestamp'), '—');
  assert.equal(camera.ageLabel('2026-09-10T19:00:00Z', Date.parse('2026-09-10T18:59:00Z')), 'Just now');
});

test('long report surfaces the sender’s own Summary without inferring a detection', () => {
  const full = '### Scene Context\nA shape crossed the frame.\n\n### Summary\nNo drone intrusion event emitted.\n\n### Further details\nReview needed.';
  const view = camera.summaryView(full);
  assert.equal(view.excerpt, 'No drone intrusion event emitted.');
  assert.equal(view.full, full);
  assert.equal(view.hasMore, true);
  assert.equal(camera.summaryView('<script>alert(1)</script>').excerpt, '<script>alert(1)</script>');
});
