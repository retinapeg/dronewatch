const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const source = html.match(/<script id="dronewatch-core">([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({ URL });
vm.runInContext(`${source}\nglobalThis.helpers = DW;`, context);
const dw = context.helpers;

test('latest observation follows backend ID 8 instead of preferring genuine Viso event 6', () => {
  const genuine = { id: 6, source: 'VISO', state: 'DETECTED', raw_payload: { appId: 'app', incidentId: 'incident' } };
  const simulation = { id: 8, source: 'SIMULATED', state: 'DETECTED', is_simulated: true };
  const payload = { latest: simulation, events: [simulation, genuine] };
  assert.equal(dw.latest(payload), simulation);
  assert.equal(dw.kind(dw.latest(payload)), 'SIMULATED');
  assert.equal(dw.latest({ events: payload.events }), simulation);
  assert.equal(dw.latest({ events: [] }), null);
});

test('separate event IDs advance even when both observations classify the same drone', () => {
  assert.equal(dw.advanced(8, 9), true);
  assert.equal(dw.advanced('8', '9'), true);
  assert.equal(dw.advanced(8, 8), false);
  assert.equal(dw.advanced(8, 6), false);
  assert.equal(dw.advanced(null, 8), false);
  const events = [{ id: 9, detection_type: 'drone' }, { id: 8, detection_type: 'drone' }];
  assert.equal(dw.latest({ events }).id, 9);
  assert.equal(events.length, 2);
});

test('Viso metadata is distinguished from simulations and generic webhook tests', () => {
  const event = { source: "{'connectionId': None}", raw_payload: { appId: 'app', incidentId: 'incident' } };
  assert.equal(dw.kind(event), 'VISO');
  assert.equal(dw.kind({ ...event, is_simulated: true }), 'SIMULATED');
  assert.equal(dw.kind({ source: 'VISO', raw_payload: {} }), 'WEBHOOK');
  assert.equal(dw.kind({ source: 'manual-test' }), 'TEST');
});

test('qualitative confidence is not converted into a fabricated percentage', () => {
  assert.equal(dw.confidence({ confidence: null, raw_payload: { confidence: { confidence_if_available: 'high' } } }), 'HIGH (QUALITATIVE)');
  assert.equal(dw.confidence({ confidence: 0 }), '0%');
  assert.equal(dw.confidence({ confidence: 0.91 }), '91%');
  assert.equal(dw.confidence({ raw_payload: {} }), '\u2014');
});

test('missing positions stay event-derived; qualitative Viso positions are retained', () => {
  assert.equal(dw.spatial({ state: 'RESTRICTED_ZONE' }).mode, 'derived');
  const pos = dw.spatial({ state: 'DETECTED', raw_payload: { labels: [{ approximate_position: 'center-right to right' }] } });
  assert.equal(pos.mode, 'qualitative');
  assert.equal(pos.reported, 'center-right to right');
  assert.ok(pos.x > 0.7);
});

test('real frame coordinates and bounding boxes preserve zero values', () => {
  const origin = dw.spatial({ raw_payload: { position: { x: 0, y: 0 } } });
  assert.equal(origin.mode, 'frame');
  assert.equal(origin.x, 0);
  assert.equal(origin.y, 0);
  const box = dw.spatial({ raw_payload: { frame_width: 1920, frame_height: 1080, bbox: { x: 192, y: 108, width: 384, height: 216 } } });
  assert.equal(box.mode, 'frame');
  assert.ok(Math.abs(box.x - 0.2) < 0.00001);
  assert.ok(Math.abs(box.y - 0.2) < 0.00001);
});

test('ambiguous bbox arrays and geographic coordinates are not plotted as measured frame data', () => {
  assert.equal(dw.spatial({ raw_payload: { bbox: [10, 20, 30, 40] } }).mode, 'derived');
  const geo = dw.spatial({ raw_payload: { coordinates: { latitude: 51.5, longitude: -0.12 } } });
  assert.equal(geo.mode, 'derived');
  assert.equal(geo.reported, 'LAT 51.5 / LON -0.12');
});

test('relative media paths are not invented URLs; simulation media is not sensor evidence', () => {
  assert.equal(dw.media({ raw_payload: { mediaLink: 'media/video_files/demo.mp4' } }).url, null);
  assert.equal(dw.media({ is_simulated: true, media_url: 'https://example.com/fake.mp4' }).url, null);
  assert.equal(dw.media({ raw_payload: { mediaLink: 'https://sensor.example/frame.mp4', fileType: 'mp4' } }).video, true);
  assert.equal(dw.safeURL('javascript:alert(1)'), null);
});

test('sensor freshness expires after two minutes and rejects invalid or future timestamps', () => {
  const now = Date.parse('2026-09-03T19:00:00Z');
  assert.equal(dw.recent({ received_at: '2026-09-03T18:59:00Z' }, now), true);
  assert.equal(dw.recent({ received_at: '2026-09-03T18:57:00Z' }, now), false);
  assert.equal(dw.recent({ received_at: 'ITM-0002' }, now), false);
  assert.equal(dw.recent({ received_at: '2026-09-04T19:00:00Z' }, now), false);
});

test('unknown backend events never become clear or incursion through narrative interpretation', () => {
  assert.equal(dw.state({ state: 'UNKNOWN', raw_payload: { summary: 'No DRONE_ZONE_INTRUSION event emitted' } }), 'UNKNOWN');
  assert.equal(dw.state({ state: 'CLEAR' }), 'UNKNOWN');
  assert.equal(dw.state({ state: 'CLEAR', local_demo: true }), 'CLEAR');
  assert.equal(dw.state({ state: 'EXITED' }), 'EXITED');
});
