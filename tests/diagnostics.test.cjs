const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'diagnostics.html'), 'utf8');
const source = html.match(/<script id="preview-core">([\s\S]*?)<\/script>/)[1];
// Run in this realm: objects built inside a fresh vm context carry different
// Array/Object prototypes, which makes deepEqual fail on identical structures.
const pv = vm.runInThisContext(`(()=>{${source}\nreturn PV;})()`);

const obs = (id, received, extra = {}) => ({
  observation_id: id, received_at: received, modality: 'RADAR',
  sensor_id: 'radar-north', sim_time_s: 0, transport_delay_s: 0,
  position: { frame: 'LOCAL_SIM_METRES', x: 0, y: 0, z: 10 }, ...extra,
});

test('delivery order is stable when received_at ties', () => {
  const list = [obs('b', '2026-09-09T12:00:01Z'), obs('a', '2026-09-09T12:00:01Z'),
                obs('c', '2026-09-09T12:00:00Z')];
  const ordered = pv.order(list).map(o => o.observation_id);
  assert.deepEqual(ordered, ['c', 'a', 'b']);
  // Repeating the sort on an already-sorted list must not change it.
  assert.deepEqual(pv.order(pv.order(list)).map(o => o.observation_id), ordered);
});

test('a duplicate sharing an observation_id keeps both copies in order', () => {
  const list = [obs('dup', '2026-09-09T12:00:02Z'), obs('dup', '2026-09-09T12:00:01Z')];
  assert.deepEqual(pv.order(list).map(o => o.received_at),
    ['2026-09-09T12:00:01Z', '2026-09-09T12:00:02Z']);
});

test('only an explicit local simulation frame is plottable', () => {
  assert.deepEqual(pv.frame({ frame: 'LOCAL_SIM_METRES', x: 5, y: 6, z: 7 }), { x: 5, y: 6, z: 7 });
  // Geographic key names are refused outright, whatever else they carry.
  assert.equal(pv.frame({ latitude: 51.5, longitude: -0.12 }), null);
  assert.equal(pv.frame({ frame: 'LOCAL_SIM_METRES', latitude: 51.5, longitude: -0.12 }), null);
  assert.equal(pv.frame({ x: 1, y: 2 }), null);
  assert.equal(pv.frame(null), null);
  assert.equal(pv.frame({ frame: 'LOCAL_SIM_METRES', x: 'a', y: 2 }), null);
});

test('a missing altitude is reported as unknown rather than zero', () => {
  assert.deepEqual(pv.frame({ frame: 'LOCAL_SIM_METRES', x: 1, y: 2 }), { x: 1, y: 2, z: null });
});

test('observations without a position go to the non-spatial list, not the map', () => {
  const withPosition = obs('a', '1');
  const without = obs('b', '2', { position: null, modality: 'RF' });
  const geographic = obs('c', '3', { position: { latitude: 1, longitude: 2 } });
  const split = pv.splitBySpace([withPosition, without, geographic]);
  assert.deepEqual(split.spatial.map(o => o.observation_id), ['a']);
  assert.deepEqual(split.nonSpatial.map(o => o.observation_id), ['b', 'c']);
});

test('projection maps simulation metres into the viewport with y inverted', () => {
  const box = { minX: 0, maxX: 100, minY: 0, maxY: 100 };
  const bottomLeft = pv.project({ frame: 'LOCAL_SIM_METRES', x: 0, y: 0 }, box, 200, 400);
  assert.equal(bottomLeft.px, 0);
  assert.equal(bottomLeft.py, 400);
  const topRight = pv.project({ frame: 'LOCAL_SIM_METRES', x: 100, y: 100 }, box, 200, 400);
  assert.equal(topRight.px, 200);
  assert.equal(topRight.py, 0);
  assert.equal(pv.project({ latitude: 1, longitude: 2 }, box, 200, 400), null);
});

test('the clock shows simulation time, never wall-clock age', () => {
  assert.equal(pv.simClock(0), 'T+0000.0 s');
  assert.equal(pv.simClock(12.34), 'T+0012.3 s');
  assert.equal(pv.simClock(-5), 'T+0000.0 s');
  assert.equal(pv.simClock(undefined), 'T+0000.0 s');
});

test('playback is bounded and cannot run past the end', () => {
  const list = [obs('a', '1'), obs('b', '2'), obs('c', '3')];
  const playback = pv.createPlayback(list);
  assert.equal(playback.total, 3);
  assert.equal(playback.index, 0);
  assert.equal(playback.latest(), null);

  playback.step();
  assert.equal(playback.index, 1);
  assert.equal(playback.latest().observation_id, 'a');
  assert.deepEqual(playback.delivered().map(o => o.observation_id), ['a']);

  playback.step(50);
  assert.equal(playback.index, 3, 'index must clamp to the list length');
  assert.equal(playback.done, true);
  assert.equal(playback.playing, false, 'reaching the end stops playback');

  playback.step();
  assert.equal(playback.index, 3, 'stepping past the end changes nothing');
});

test('play and pause toggle correctly and an empty scenario cannot play', () => {
  const playback = pv.createPlayback([obs('a', '1')]);
  assert.equal(playback.play(), true);
  assert.equal(playback.playing, true);
  playback.pause();
  assert.equal(playback.playing, false);

  const empty = pv.createPlayback([]);
  assert.equal(empty.play(), false, 'an empty scenario must never enter playing state');
  assert.equal(empty.done, true);
});

test('reset returns to the start and stops playback', () => {
  const playback = pv.createPlayback([obs('a', '1'), obs('b', '2')]);
  playback.play();
  playback.step(2);
  assert.equal(playback.index, 2);
  assert.equal(playback.reset(), 0);
  assert.equal(playback.index, 0);
  assert.equal(playback.playing, false);
  assert.equal(playback.latest(), null);
  assert.deepEqual(playback.delivered(), []);
});

test('a fractional or negative step still advances exactly one', () => {
  const playback = pv.createPlayback([obs('a', '1'), obs('b', '2')]);
  playback.step(-3);
  assert.equal(playback.index, 1);
  playback.step(0.4);
  assert.equal(playback.index, 2);
});

test('every modality has a distinct legend colour', () => {
  const colours = ['RADAR', 'RF', 'EO', 'IR', 'ACOUSTIC'].map(pv.colour);
  assert.equal(new Set(colours).size, 5);
  assert.equal(pv.colour('SOMETHING_NEW'), '#93a6b5');
});

test('modality counts drive the legend', () => {
  const counts = pv.modalityCounts([obs('a', '1'), obs('b', '2', { modality: 'RF' }), obs('c', '3')]);
  assert.deepEqual(counts, { RADAR: 2, RF: 1 });
});

test('bounds ignore observations that have no plottable position', () => {
  const list = [obs('a', '1', { position: { frame: 'LOCAL_SIM_METRES', x: 0, y: 0 } }),
                obs('b', '2', { position: null }),
                obs('c', '3', { position: { frame: 'LOCAL_SIM_METRES', x: 100, y: 100 } })];
  const box = pv.bounds(list);
  assert.ok(box.minX < 0 && box.maxX > 100);
  assert.equal(pv.bounds([obs('x', '1', { position: null })]), null);
});

test('outlying observations do not squash the framed view', () => {
  const cluster = Array.from({ length: 50 }, (_, i) =>
    obs(`c${i}`, String(i), { position: { frame: 'LOCAL_SIM_METRES', x: i, y: i } }));
  const outlier = obs('far', '99', { position: { frame: 'LOCAL_SIM_METRES', x: 500000, y: 500000 } });
  const box = pv.bounds([...cluster, outlier]);
  // The frame follows the activity, not the single distant spurious report.
  assert.ok(box.maxX < 1000, `frame should ignore the outlier, got ${box.maxX}`);
  // The outlier is still in the data; it simply falls outside the framed area.
  assert.equal(pv.splitBySpace([...cluster, outlier]).spatial.length, 51);
});

test('a single point still produces a usable frame', () => {
  const box = pv.bounds([obs('a', '1', { position: { frame: 'LOCAL_SIM_METRES', x: 10, y: 10 } })]);
  assert.ok(box.maxX > box.minX && box.maxY > box.minY);
});

test('ticks span the frame so distances are readable in metres', () => {
  const box = { minX: 0, maxX: 100, minY: -50, maxY: 50 };
  const marks = pv.ticks(box, 4);
  assert.equal(marks.x.length, 5);
  assert.equal(marks.x[0], 0);
  assert.equal(marks.x[4], 100);
  assert.equal(marks.y[0], -50);
  assert.equal(marks.y[4], 50);
  assert.deepEqual(pv.ticks(null, 4), { x: [], y: [] });
});
