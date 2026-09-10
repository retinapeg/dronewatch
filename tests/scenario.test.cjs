const { test } = require('node:test');
const assert = require('node:assert/strict');
const { snapshot, DURATION, normalizeSensorPayload, freshness } = require('../assets/scenario.js');
const record = (overrides = {}) => ({ target_id: 'track-1', event_id: 'event-1', source_kind: 'SENSOR_EVENT', source: 'camera-a', status: 'UNKNOWN', confidence: null, position: null, updated_at: '2026-09-10T10:00:00Z', evidence: [], ...overrides });
const payload = targets => ({ schema_version: 1, targets });

test('scenario snapshots are identical across independent calls and preserve the initial fixture', () => {
  const initial = snapshot(0, 5);
  snapshot(30, 10); snapshot(90, 3);
  assert.deepEqual(snapshot(0, 5), initial);
  assert.deepEqual(snapshot(37.25, 10), snapshot(37.25, 10));
  initial[0].position.x = 999;
  assert.equal(snapshot(0, 5)[0].position.x, .75);
});
test('3, 5 and 10 targets are distinct with bounded positions, histories and predictions', () => {
  for (const count of [3, 5, 10]) for (const seconds of [0, 15, 45, 89, 90]) {
    const tracks = snapshot(seconds, count);
    assert.equal(tracks.length, count);
    assert.equal(new Set(tracks.map(track => track.target_id)).size, count);
    for (const track of tracks) for (const point of [track.position, ...track.history, ...track.predicted_path]) {
      assert.ok(point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1);
      assert.equal(point.coordinate_system, 'synthetic_schematic');
    }
  }
});
test('synthetic producer makes source, status and confidence provenance explicit', () => {
  for (const track of snapshot(30)) {
    assert.equal(track.source_kind, 'SYNTHETIC_EVENT');
    assert.equal(track.status_basis, 'scenario_authored');
    assert.equal(track.confidence_basis, 'illustrative');
    assert.equal(track.synthetic, true);
    assert.equal(track.velocity, null);
    assert.equal(track.heading, null);
    assert.match(track.uncertainty, /No real detection/);
  }
  assert.equal(snapshot()[0].target_id, 'DW-01');
  assert.equal(snapshot()[0].status, 'THREAT');
});
test('scenario completes at its fixed endpoint and invalid inputs cannot create NaN geometry', () => {
  assert.deepEqual(snapshot(DURATION + 100), snapshot(DURATION));
  assert.deepEqual(snapshot(-1), snapshot(0));
  assert.deepEqual(snapshot(NaN), snapshot(0));
  assert.deepEqual(snapshot(Infinity), snapshot(0));
  assert.equal(snapshot(0, 999).length, 10);
  assert.equal(snapshot(0, -1).length, 0);
});
test('scenario order is the actual priority order and direction agrees with authored path', () => {
  const tracks = snapshot(0, 10);
  assert.deepEqual(tracks.map(track => track.priority), [1,2,3,4,5,6,7,8,9,10]);
  for (const track of tracks) {
    const [start, end] = track.predicted_path;
    const direction = Math.atan2(end.x-start.x, -(end.y-start.y))*180/Math.PI;
    assert.equal(track.course_degrees, direction);
  }
});

test('predicted movement never exceeds the authored final position', () => {
  const end = snapshot(DURATION);
  const almost = snapshot(DURATION - 2);
  almost.forEach((track, i) => assert.deepEqual(track.predicted_path.at(-1), end[i].position));
});
test('empty canonical sensor response stays empty', () => assert.deepEqual(normalizeSensorPayload(payload([])), []));
test('malformed full responses and individual records fail closed', () => {
  for (const input of [null, {}, [], { targets: [] }, { schema_version: 9, targets: [] }, payload([null]), payload([record({ confidence: NaN })]), payload([record({ confidence: 5 })]), payload([record({ target_id: {} })]), payload([record({ status: 'HOSTILE' })])]) {
    assert.throws(() => normalizeSensorPayload(input));
  }
});
test('independent cameras with the same target ID remain distinct; within-source duplicate coalesces', () => {
  const result = normalizeSensorPayload(payload([record(), record({ source: 'camera-b' }), record({ event_id: 'older' })]));
  assert.equal(result.length, 2);
  assert.deepEqual(result.map(item => item.source), ['camera-a', 'camera-b']);
});
test('synthetic and reported source identity never coalesce', () => {
  const result = normalizeSensorPayload(payload([record(), record({ source_kind: 'SYNTHETIC_EVENT' })]));
  assert.equal(result.length, 2);
});
test('invalid source/evidence types do not become display text or runtime failures', () => {
  const result = normalizeSensorPayload(payload([record({ source: {}, evidence: [null, {}, 'reported observation'] })]));
  assert.equal(result[0].source, 'Unspecified source');
  assert.deepEqual(result[0].evidence, ['reported observation']);
});
test('only bounded measured normalized frame positions survive; missing positions are not fabricated', () => {
  const positions = [null, {}, { x: 1.2, y: .1, coordinate_system: 'normalized_frame' }, { x: .2, y: .1, coordinate_system: 'geographic' }, { x: .2, y: NaN, coordinate_system: 'normalized_frame' }];
  for (const position of positions) assert.equal(normalizeSensorPayload(payload([record({ position })]))[0].position, null);
  const position = { x: 0, y: 0, coordinate_system: 'normalized_frame' };
  assert.deepEqual(normalizeSensorPayload(payload([record({ position })]))[0].position, position);
});
test('freshness rejects invalid and future dates and expires stale observations', () => {
  const now = Date.parse('2026-09-10T10:00:00Z');
  assert.equal(freshness('2026-09-10T09:59:30Z', now).fresh, true);
  assert.equal(freshness('2026-09-10T09:57:59Z', now).fresh, false);
  assert.equal(freshness('2026-09-11T10:00:00Z', now).fresh, false);
  assert.equal(freshness('', now).label, 'Timestamp unverified');
});
