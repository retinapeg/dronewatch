const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'preview.html'), 'utf8');
const source = html.match(/<script id="operator-core">([\s\S]*?)<\/script>/)[1];
// Run in this realm so deepEqual does not fail on cross-realm prototypes.
const op = vm.runInThisContext(`(()=>{${source}\nreturn OP;})()`);

test('project round-trips: toScreen then toWorld returns the original point', () => {
  const camera = {cx: 100, cy: 200, scale: 0.5};
  const viewport = {w: 1000, h: 800};
  const proj = op.project(camera, viewport);

  // Test various points
  const points = [{x: 150, y: 250}, {x: 0, y: 0}, {x: -500, y: 1000}];
  for (const point of points) {
    const screen = proj.toScreen(point.x, point.y);
    const back = proj.toWorld(screen.px, screen.py);
    assert.ok(Math.abs(back.x - point.x) < 1e-6, `x round-trip failed for ${point.x}`);
    assert.ok(Math.abs(back.y - point.y) < 1e-6, `y round-trip failed for ${point.y}`);
  }
});

test('project maps camera centre to viewport centre', () => {
  const camera = {cx: 500, cy: 300, scale: 1};
  const viewport = {w: 1000, h: 600};
  const proj = op.project(camera, viewport);
  const centre = proj.toScreen(camera.cx, camera.cy);

  assert.equal(centre.px, viewport.w / 2, 'camera cx must map to viewport centre x');
  assert.equal(centre.py, viewport.h / 2, 'camera cy must map to viewport centre y');
});

test('project inverts the y axis: larger world y produces smaller screen py', () => {
  const camera = {cx: 0, cy: 0, scale: 1};
  const viewport = {w: 1000, h: 1000};
  const proj = op.project(camera, viewport);

  const lower = proj.toScreen(0, -100);
  const higher = proj.toScreen(0, 100);

  assert.ok(higher.py < lower.py, 'larger world y must produce smaller screen y because simulation y grows north whilst screen y grows down');
});

test('fitCamera centres on supplied points and returns scale within limits', () => {
  const points = [{x: 0, y: 0}, {x: 100, y: 100}, {x: 200, y: 50}];
  const viewport = {w: 1000, h: 800};
  const result = op.fitCamera(points, viewport);

  assert.ok(result !== null, 'fitCamera must return a camera for non-empty points');
  assert.ok(result.scale >= op.MIN_SCALE, 'scale must not go below MIN_SCALE');
  assert.ok(result.scale <= op.MAX_SCALE, 'scale must not exceed MAX_SCALE');

  // Camera should centre on the midpoint of the bounding box
  const midX = (0 + 200) / 2, midY = (0 + 100) / 2;
  assert.ok(Math.abs(result.cx - midX) < 20, 'camera should centre roughly on x range');
  assert.ok(Math.abs(result.cy - midY) < 20, 'camera should centre roughly on y range');
});

test('fitCamera returns null for empty points array', () => {
  const viewport = {w: 1000, h: 800};
  const result = op.fitCamera([], viewport);
  assert.equal(result, null, 'fitCamera must return null for empty points');
});

test('scenarioEnvelope includes site monitored area and track positions', () => {
  const frames = [
    {tracks: [{x: 1000, y: 1000}]},
    {tracks: [{x: -2000, y: 500}]}
  ];
  const site = {x: 0, y: 0, radius_m: 600};
  const points = op.scenarioEnvelope(frames, site);

  assert.ok(Array.isArray(points), 'scenarioEnvelope must return an array');
  assert.ok(points.length > 0, 'envelope must include at least the site boundary');

  // Find the extent
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);

  assert.ok(minX <= -2000, 'envelope must span the track at x=-2000');
  assert.ok(maxX >= 1000, 'envelope must span the track at x=1000');
});

test('scenarioEnvelope returns site points even when frames is empty', () => {
  const site = {x: 0, y: 0, radius_m: 600};
  const points = op.scenarioEnvelope([], site);

  assert.ok(Array.isArray(points), 'scenarioEnvelope must return an array');
  assert.ok(points.length > 0, 'envelope must include site boundary even when frames is empty');
});

test('stepCamera moves toward target and never overshoots', () => {
  const camera = {cx: 0, cy: 0, scale: 1};
  const target = {cx: 100, cy: 0, scale: 1};
  const dt = 0.1;

  let current = camera;
  let lastCx = current.cx;

  // One step should move closer to target
  current = op.stepCamera(current, target, dt);
  assert.ok(current.cx > lastCx && current.cx < target.cx, 'stepCamera must move toward target without overshooting');

  // Repeated steps should converge
  for (let i = 0; i < 40; i++) {
    current = op.stepCamera(current, target, dt);
  }
  assert.ok(Math.abs(current.cx - target.cx) < 1, 'after many steps, camera should converge to target');
});

test('stepCamera with null target returns camera unchanged', () => {
  const camera = {cx: 50, cy: 50, scale: 1.5};
  const result = op.stepCamera(camera, null, 0.1);

  assert.deepEqual(result, camera, 'stepCamera with null target must return the same camera');
});

test('zoomAt keeps world point under cursor fixed', () => {
  const camera = {cx: 0, cy: 0, scale: 1};
  const viewport = {w: 1000, h: 800};
  const cursorPx = 500, cursorPy = 400;

  const projBefore = op.project(camera, viewport);
  const worldBefore = projBefore.toWorld(cursorPx, cursorPy);

  const zoomed = op.zoomAt(camera, 2, cursorPx, cursorPy, viewport);
  const projAfter = op.project(zoomed, viewport);
  const worldAfter = projAfter.toWorld(cursorPx, cursorPy);

  assert.ok(Math.abs(worldAfter.x - worldBefore.x) < 1e-6, 'world x under cursor must remain fixed');
  assert.ok(Math.abs(worldAfter.y - worldBefore.y) < 1e-6, 'world y under cursor must remain fixed');
});

test('zoomAt respects scale limits when zooming in', () => {
  const camera = {cx: 0, cy: 0, scale: op.MAX_SCALE - 0.1};
  const viewport = {w: 1000, h: 800};

  let current = camera;
  for (let i = 0; i < 10; i++) {
    current = op.zoomAt(current, 2, 500, 400, viewport);
  }

  assert.ok(current.scale <= op.MAX_SCALE, 'scale must never exceed MAX_SCALE even with repeated zoom in');
});

test('zoomAt respects scale limits when zooming out', () => {
  const camera = {cx: 0, cy: 0, scale: op.MIN_SCALE + 0.1};
  const viewport = {w: 1000, h: 800};

  let current = camera;
  for (let i = 0; i < 10; i++) {
    current = op.zoomAt(current, 0.5, 500, 400, viewport);
  }

  assert.ok(current.scale >= op.MIN_SCALE, 'scale must never go below MIN_SCALE even with repeated zoom out');
});

test('niceScale returns a round number from the allowed set', () => {
  const allowed = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
  const result = op.niceScale(1, 120);

  assert.ok(allowed.includes(result.metres), 'niceScale must return one of the allowed values');
  assert.ok(result.pixels <= 120, 'pixel width must not exceed requested maximum');
});

test('sortTracks orders by priority then range then id, and does not mutate input', () => {
  const tracks = [
    {id: 'c', priority: 'LOW PRIORITY', range_m: 100},
    {id: 'a', priority: 'HIGH PRIORITY', range_m: 500},
    {id: 'b', priority: 'WATCH', range_m: 200},
    {id: 'd', priority: 'HIGH PRIORITY', range_m: 100}
  ];
  const original = JSON.stringify(tracks);
  const sorted = op.sortTracks(tracks);

  assert.equal(JSON.stringify(tracks), original, 'sortTracks must not mutate the input array');

  const priorities = sorted.map(t => t.priority);
  assert.equal(priorities[0], 'HIGH PRIORITY', 'HIGH PRIORITY must come first');
  assert.equal(priorities[1], 'HIGH PRIORITY', 'multiple HIGH PRIORITY entries follow');
  assert.equal(priorities[2], 'WATCH', 'WATCH must come after HIGH PRIORITY');
  assert.equal(priorities[3], 'LOW PRIORITY', 'LOW PRIORITY must come last');

  // Check that HIGH PRIORITY entries are sorted by range
  assert.equal(sorted[0].id, 'd', 'among HIGH PRIORITY, smaller range comes first');
  assert.equal(sorted[1].id, 'a', 'then larger range');

  // Check that id is used as tiebreaker for same priority and range
  const samePrio = [{id: 'z', priority: 'WATCH', range_m: 100}, {id: 'a', priority: 'WATCH', range_m: 100}];
  const sameSort = op.sortTracks(samePrio);
  assert.equal(sameSort[0].id, 'a', 'same priority and range must be ordered by id');
  assert.equal(sameSort[1].id, 'z', 'id tiebreaker must be alphabetical');
});

test('resolveSelection finds a track by id and returns null for unknown id', () => {
  const tracks = [
    {id: 'a', priority: 'HIGH PRIORITY'},
    {id: 'b', priority: 'WATCH'}
  ];

  const found = op.resolveSelection('a', tracks);
  assert.equal(found.id, 'a', 'resolveSelection must find the track with matching id');

  const notFound = op.resolveSelection('unknown', tracks);
  assert.equal(notFound, null, 'resolveSelection must return null for unknown id');

  const noId = op.resolveSelection(null, tracks);
  assert.equal(noId, null, 'resolveSelection must return null when selectedId is null');
});

test('selection survives reordering: object identity is stable by id', () => {
  let tracks = [
    {id: 'a', priority: 'HIGH PRIORITY', range_m: 100},
    {id: 'b', priority: 'WATCH', range_m: 200}
  ];

  const first = op.resolveSelection('a', tracks);

  // Reorder by sorting
  tracks = op.sortTracks(tracks);

  const second = op.resolveSelection('a', tracks);

  assert.equal(first.id, second.id, 'resolveSelection must find the same id after reordering');
});

test('declutter separates labels that would overlap vertically', () => {
  const labels = [
    {id: 'a', px: 100, py: 0, text: 'A'},
    {id: 'b', px: 100, py: 5, text: 'B'}
  ];
  const minGapY = 20, minGapX = 64;
  const placed = op.declutter(labels, minGapY, minGapX);

  assert.ok(Math.abs(placed[1].py - placed[0].py) >= minGapY, 'overlapping labels must be separated by at least minGapY');
});

test('declutter leaves horizontally distant labels untouched', () => {
  const labels = [
    {id: 'a', px: 0, py: 0, text: 'A'},
    {id: 'b', px: 200, py: 5, text: 'B'}
  ];
  const minGapY = 20, minGapX = 64;
  const placed = op.declutter(labels, minGapY, minGapX);

  // If they are far apart horizontally, they should not be moved
  assert.equal(placed[0].py, labels[0].py, 'labels far apart horizontally must not be adjusted');
  assert.equal(placed[1].py, labels[1].py, 'labels far apart horizontally must not be adjusted');
});

test('priorityClass maps priority strings to CSS class names', () => {
  assert.equal(op.priorityClass('HIGH PRIORITY'), 'p-high', 'HIGH PRIORITY maps to p-high');
  assert.equal(op.priorityClass('WATCH'), 'p-watch', 'WATCH maps to p-watch');
  assert.equal(op.priorityClass('LOW PRIORITY'), 'p-low', 'LOW PRIORITY maps to p-low');
});

test('createPlayback is bounded: index starts at 0, step advances by one', () => {
  const frames = [{t: 0}, {t: 1}, {t: 2}];
  const playback = op.createPlayback(frames);

  assert.equal(playback.index, 0, 'playback index must start at 0');
  assert.equal(playback.total, 3, 'playback total must match frame count');

  playback.step();
  assert.equal(playback.index, 1, 'step must advance index by one');

  playback.step();
  assert.equal(playback.index, 2, 'step must continue advancing');
});

test('createPlayback clamps step to bounds and stops playing at end', () => {
  const frames = [{t: 0}, {t: 1}, {t: 2}];
  const playback = op.createPlayback(frames);

  playback.step(1000);
  assert.equal(playback.index, frames.length - 1, 'step must clamp to frames.length-1');
  assert.equal(playback.playing, false, 'reaching the end must stop playback');
});

test('createPlayback reset returns index to 0 and sets playing false', () => {
  const frames = [{t: 0}, {t: 1}, {t: 2}];
  const playback = op.createPlayback(frames);

  playback.play();
  playback.step(2);
  assert.equal(playback.index, 2, 'precondition: index must be advanced');

  playback.reset();
  assert.equal(playback.index, 0, 'reset must return index to 0');
  assert.equal(playback.playing, false, 'reset must set playing to false');
});

test('createPlayback play on empty list returns false', () => {
  const playback = op.createPlayback([]);

  const result = playback.play();
  assert.equal(result, false, 'play on empty frame list must return false');
  assert.equal(playback.playing, false, 'play on empty list must not enter playing state');
});

test('createPlayback seek clamps to valid range', () => {
  const frames = [{t: 0}, {t: 1}, {t: 2}];
  const playback = op.createPlayback(frames);

  playback.seek(-10);
  assert.equal(playback.index, 0, 'seek with negative value must clamp to 0');

  playback.seek(1000);
  assert.equal(playback.index, frames.length - 1, 'seek with too-large value must clamp to frames.length-1');
});

test('createPlayback frame returns frame at current index', () => {
  const frames = [{t: 0, id: 'a'}, {t: 1, id: 'b'}];
  const playback = op.createPlayback(frames);

  assert.equal(playback.frame().id, 'a', 'frame must return the frame at current index');
  playback.step();
  assert.equal(playback.frame().id, 'b', 'frame must update as index advances');
});

test('createPlayback frame never returns undefined for non-empty list', () => {
  const frames = [{t: 0}];
  const playback = op.createPlayback(frames);

  playback.step(100); // Clamp to end
  const frame = playback.frame();
  assert.notEqual(frame, undefined, 'frame must never be undefined for non-empty list even at boundary');
});

// ---------------- camera check ----------------
const REPLAY = {scenario: 'operator_demo', seed: 42, count: 6, mode: 'radar_off_30s_viso'};
const linked = (filename, start, end, extra = {}) => ({filename, url: '/api/camera/media/' + filename,
  scenario_context: {...REPLAY, sim_start_s: start, sim_end_s: end, ...extra}});
const CAPTURED = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'viso', 'captured', 'drone_detected_2026-11-23.json'), 'utf8'));

test('the camera clip follows the replay: next before its window, live inside it, kept after it', () => {
  const media = [linked('a.mp4', 43, 47), linked('b.mp4', 47, 51), linked('whole.mp4', 40, 70), linked('a.png', 45, 45),
                 {...linked('other.mp4', 43, 47), scenario_context: {...REPLAY, seed: 7, sim_start_s: 43, sim_end_s: 47}}];
  const pick = t => { const got = op.cameraClip(media, REPLAY, t); return [got.clip && got.clip.filename, got.phase]; };
  assert.deepEqual(pick(10), ['whole.mp4', 'before']);
  assert.deepEqual(pick(44), ['a.mp4', 'live']);       // the narrowest open window wins
  assert.deepEqual(pick(48), ['b.mp4', 'live']);
  assert.deepEqual(pick(60), ['whole.mp4', 'live']);
  assert.deepEqual(pick(80), ['whole.mp4', 'after']);
  assert.deepEqual(op.cameraClip([], REPLAY, 44), {clip: null, phase: 'none'});
  assert.deepEqual(op.cameraClip(media, {...REPLAY, mode: 'normal'}, 44), {clip: null, phase: 'none'});
});

test('real-time clips run one second per replay second; other clips stretch across their window', () => {
  const realtime = {sim_start_s: 43, sim_end_s: 47, playback: 'realtime'};
  assert.deepEqual(op.clipTime(realtime, 45, 10, 2), {time: 2, rate: 2});
  assert.equal(op.clipTime(realtime, 40, 10, 1).time, 0);
  assert.equal(op.clipTime(realtime, 90, 10, 1).time, 9.95);      // holds on the last frame
  const stretched = {sim_start_s: 40, sim_end_s: 70};
  assert.deepEqual(op.clipTime(stretched, 55, 8, 1), {time: 4, rate: 8 / 30});
  assert.deepEqual(op.clipTime(stretched, 55, NaN, 1), {time: 0, rate: 1});
});

test('a camera finding is attached to the contact the camera was cued at when the clip began', () => {
  const cues = [{t: 0, target: null}, {t: 43, target: 'DW-001'}, {t: 47, target: 'DW-003'}];
  assert.equal(op.cueTargetAt(cues, 42.9), null);
  assert.equal(op.cueTargetAt(cues, 46.9), 'DW-001');
  const result = {scenario_context: {sim_start_s: 43, sim_end_s: 47}, verdict: {label: 'drone', confidence: 0.95}};
  assert.deepEqual(op.cameraFindings([result, {verdict: {label: 'drone'}}], cues), {'DW-001': {label: 'DRONE', pct: 95}});
  assert.deepEqual(op.cameraFindings([{...result, verdict: null}], cues), {});
});

test('the verdict is the sender’s own label in one line, with report markup removed', () => {
  const label = CAPTURED.labels[0];
  const view = op.verdictView({verdict: {label: label.label, confidence: label.confidence, detail: label.structure,
                                         motion: label.motion_state, tracking: label.tracking_status}});
  assert.deepEqual(view, {headline: 'DRONE', confidence: '95% confidence', pct: 95,
    chips: ['Moving', 'Tracking: continuous'],
    detail: 'Four-rotor multirotor UAV with visible body, propellers, and landing gear'});
  assert.equal(op.verdictView({summary: 'A drone was seen.'}), null);
  assert.equal(op.verdictView({verdict: {label: 'drone', confidence: 95}}).confidence, '');
  const plain = op.plainText(CAPTURED.summary, 160);
  assert.ok(plain.startsWith('The video captures a rural agricultural landscape'));
  assert.ok(!/[#*`|]/.test(plain) && plain.length <= 161);
  assert.equal(op.plainText(null), '');
});

test('the page is pinned to the window width, so a long top bar cannot push the contact list off screen', () => {
  // Without an explicit column the grid takes the top bar's natural width. On a 1366 px laptop that was
  // wider than the window and the right-hand panel was cut off. Checked in a browser from 900 to 1728 px.
  assert.match(html, /\.app\{display:grid;grid-template-columns:minmax\(0,1fr\);/);
  assert.match(html, /\.top\{gap:10px;min-width:0\}/);
});
