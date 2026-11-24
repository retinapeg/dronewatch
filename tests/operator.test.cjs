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

test('recorded footage runs at its own speed whatever the replay does; rendered excerpts stretch across their window', () => {
  // Recorded footage must never sit on a still frame: it is not held to the replay clock or its speed.
  const recorded = {sim_start_s: 43, sim_end_s: 47, playback: 'realtime'};
  for (const [t, speed] of [[45, 2], [40, 1], [90, 0.5]]) {
    assert.deepEqual(op.clipTime(recorded, t, 10, speed), {free: true, time: null, rate: 1});
  }
  const stretched = {sim_start_s: 40, sim_end_s: 70};
  assert.deepEqual(op.clipTime(stretched, 55, 8, 1), {free: false, time: 4, rate: 8 / 30});
  assert.deepEqual(op.clipTime(stretched, 55, NaN, 1), {free: false, time: 0, rate: 1});
  assert.equal(op.clipTime(stretched, 90, 8, 1).time, 7.95);      // holds on the last frame
});

test('the footage clock reads minutes, seconds and tenths', () => {
  assert.deepEqual([0, 3.44, 9.99, 10.03, 59.99, 75.56].map(op.timecode), ['0:00.0', '0:03.4', '0:09.9', '0:10.0', '0:59.9', '1:15.5']);
  assert.deepEqual([NaN, -1, undefined].map(op.timecode), ['0:00.0', '0:00.0', '0:00.0']);
});

// A camera schedule as the server writes it: the camera turns to three contacts, arrives, picks them up,
// turns to another three and picks those up one after another. `planned` is what it was sent for,
// `targets` what it picks up during the look, `seen` what it has by now.
const WEST = ['DW-002', 'DW-005', 'DW-001'], EAST = ['DW-003', 'DW-006', 'DW-004'], SENT_EAST = ['DW-003', 'DW-004', 'DW-006'];
const LOOKS = [
  {t: 0, centre_deg: 90, target: null, targets: [], planned: [], seen: [], settled: true},
  {t: 12.2, centre_deg: 98, target: 'DW-001', targets: WEST, planned: WEST, seen: [], settled: false},
  {t: 12.6, centre_deg: 110, target: 'DW-001', targets: WEST, planned: WEST, seen: [], settled: true},
  {t: 13.4, centre_deg: 110, target: 'DW-001', targets: WEST, planned: WEST, seen: WEST, settled: true},
  {t: 18.2, centre_deg: 102, target: 'DW-003', targets: SENT_EAST, planned: SENT_EAST, seen: [], settled: false},
  {t: 19, centre_deg: 71, target: 'DW-003', targets: EAST, planned: SENT_EAST, seen: [], settled: true},
  {t: 19.4, centre_deg: 71, target: 'DW-003', targets: EAST, planned: SENT_EAST, seen: ['DW-003', 'DW-006'], settled: true},
  {t: 19.6, centre_deg: 71, target: 'DW-003', targets: EAST, planned: SENT_EAST, seen: EAST, settled: true},
  {t: 41.2, centre_deg: 80, target: null, targets: [], planned: [], seen: [], settled: false},
  {t: 42, centre_deg: 90, target: null, targets: [], planned: [], seen: [], settled: true},
];

test('the camera is at rest, turning, looking, or on the contacts it has picked up', () => {
  const at = t => op.cameraState(op.cueAt(LOOKS, t));
  const word = t => op.cameraWord(at(t));
  assert.deepEqual(at(5), {state: 'rest', seen: [], look: [], sent: []});
  assert.deepEqual(at(12.4), {state: 'turning', seen: [], look: [], sent: WEST});
  // Arrived, and nothing claimed until the camera has picked a contact up.
  assert.deepEqual(at(12.8), {state: 'looking', seen: [], look: WEST, sent: WEST});
  assert.deepEqual(at(15), {state: 'on', seen: WEST, look: WEST, sent: WEST});
  assert.deepEqual(at(19.5), {state: 'on', seen: ['DW-003', 'DW-006'], look: EAST, sent: SENT_EAST});
  assert.deepEqual(at(41.5), {state: 'turning', seen: [], look: [], sent: []});      // on its way back to rest
  assert.deepEqual([5, 12.4, 12.8, 15, 19.5, 41.5, 60].map(word),
    ['AT REST', 'TURNING', 'LOOKING', 'ON 3 CONTACTS', 'ON 2 CONTACTS', 'TURNING', 'AT REST']);
  assert.equal(op.cameraWord(op.cameraState({target: 'DW-009', targets: ['DW-009'], settled: true, seen: ['DW-009'], planned: ['DW-009']})), 'ON DW-009');
  // A look that finds nothing is never called a rest: the camera was sent somewhere and is looking.
  assert.equal(op.cameraState({t: 30.4, targets: [], planned: ['DW-003'], seen: [], settled: true}).state, 'looking');
  // A schedule written before `planned` and `seen` existed: its targets are both.
  assert.deepEqual(op.cameraState({target: 'DW-001', targets: ['DW-001'], settled: true}), {state: 'on', seen: ['DW-001'], look: ['DW-001'], sent: ['DW-001']});
  assert.deepEqual(op.cameraState(null), {state: 'rest', seen: [], look: [], sent: []});
});

test('a cue names the contacts of its look, and the camera is on none of them until it has picked them up', () => {
  assert.equal(op.cueAt(LOOKS, 15).centre_deg, 110);
  assert.equal(op.cueAt(LOOKS, -1), null);
  assert.deepEqual(op.cueTargets(op.cueAt(LOOKS, 15)), WEST);
  assert.equal(op.cueTargetAt(LOOKS, 15), 'DW-001');           // the most urgent of the three
  assert.deepEqual(op.cueTargets({target: 'DW-009'}), ['DW-009']);   // a schedule with one target per cue
  assert.deepEqual(op.cueTargets(null), []);
  // Turning towards the west group, then arrived with nothing picked up yet: nothing is claimed as "on".
  assert.deepEqual(op.cameraSubject(null, LOOKS, 12.4), {ids: [], phase: 'none', now: [], turning: WEST, looking: []});
  assert.deepEqual(op.cameraSubject(null, LOOKS, 12.6), {ids: [], phase: 'none', now: [], turning: [], looking: WEST});
  assert.deepEqual(op.cameraSubject(null, LOOKS, 13.4), {ids: [], phase: 'none', now: WEST, turning: [], looking: []});
});

test('the camera window is about the contacts in its clip: live while the camera is on them, afterwards while it moves on', () => {
  const clip = {scenario_context: {sim_start_s: 12.6, sim_end_s: 18.2}};
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 12.5), {ids: [], phase: 'before', now: [], turning: WEST, looking: []});
  // The window opens on the look's three contacts as the camera arrives; they are "on" once picked up.
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 12.6), {ids: WEST, phase: 'live', now: [], turning: [], looking: WEST, since: 12.6});
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 18.1), {ids: WEST, phase: 'live', now: WEST, turning: [], looking: [], since: 12.6});
  // The window keeps the west group's footage and result while the camera turns to, then sits on, the east group.
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 18.4), {ids: WEST, phase: 'after', now: [], turning: SENT_EAST, looking: [], since: 12.6});
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 20), {ids: WEST, phase: 'after', now: EAST, turning: [], looking: [], since: 12.6});
  assert.deepEqual(op.cameraSubject(clip, LOOKS, 60), {ids: WEST, phase: 'after', now: [], turning: [], looking: [], since: 12.6});
  // A clip linked to the second look is about the contacts picked up in it, in the camera's left-to-right order.
  assert.deepEqual(op.cameraSubject({scenario_context: {sim_start_s: 19, sim_end_s: 24.2}}, LOOKS, 19.5).ids, EAST);
  // No clip linked: there is no subject, but what the camera is on is still known.
  assert.deepEqual(op.cameraSubject(null, LOOKS, 20), {ids: [], phase: 'none', now: EAST, turning: [], looking: []});
  assert.deepEqual(op.cameraSubject({scenario_context: {}}, LOOKS, 20), {ids: [], phase: 'none', now: EAST, turning: [], looking: []});
  // A schedule with one target per cue and no "settled" flag still works.
  const single = [{t: 0, target: null}, {t: 43, target: 'DW-001'}, {t: 47, target: 'DW-003'}];
  assert.deepEqual(op.cameraSubject({scenario_context: {sim_start_s: 43, sim_end_s: 47}}, single, 48),
    {ids: ['DW-001'], phase: 'after', now: ['DW-003'], turning: [], looking: [], since: 43});
});

test('several labelled objects read as a count, with every confidence shown', () => {
  const drone = (confidence, structure) => ({label: 'drone', confidence, structure});
  const three = op.verdictView({labels: [drone(0.95, 'Quadcopter, upper left'), drone(0.88), drone(0.91)], verdict: {label: 'drone', confidence: 0.95}});
  assert.deepEqual(three, {headline: '3 DRONES', confidence: '88–95% confidence', pct: 88, count: 3, drones: 3, tone: 'drone',
    chips: ['Drone 95%', 'Drone 88%', 'Drone 91%'], detail: 'Quadcopter, upper left'});
  // A bird among them: it is a count of objects, not of drones, and it is not the confirmed colour.
  const mixed = op.verdictView({labels: [drone(0.9), {label: 'Bird', confidence: 0.7}]});
  assert.deepEqual([mixed.headline, mixed.count, mixed.drones, mixed.tone, mixed.chips], ['2 OBJECTS', 2, 1, 'other', ['Drone 90%', 'Bird 70%']]);
  assert.equal(op.verdictView({labels: [drone(0.9), drone(0.9)]}).confidence, '90% confidence');
  // One label in the list is the single-object verdict, as before.
  assert.equal(op.verdictView({labels: [drone(0.95)], verdict: {label: 'drone', confidence: 0.95}}).headline, 'DRONE');
});

test('the camera tag is short on the map, long in the list, and reports the room it takes', () => {
  const group = { label: '3 OF 3 DRONES', pct: null, tone: 'drone', seen: 3, of: 3 };
  assert.deepEqual(op.findingTag(group, true), { text: '3 OF 3 DRONES', width: 100, drone: true });
  assert.equal(op.findingTag(group, false).text, 'CAMERA: 3 OF 3 DRONES');
  assert.ok(op.findingTag(group, false).width > op.findingTag(group, true).width);
  const single = op.findingTag({ label: 'DRONE', pct: 95, tone: 'drone' }, true);
  assert.equal(single.text, 'DRONE 95%');
  assert.equal(op.findingTag({ label: 'BIRD', pct: 80, tone: 'other' }, false).drone, false);
  assert.equal(op.findingTag(undefined, true), null);
});

test('a label with a camera tag is given the room the tag takes', () => {
  // Two contacts side by side, 150 px apart. Untagged labels fit beside their symbols; a
  // tagged one is wider, and the placer has to be told so or the tag lands on its neighbour.
  const tag = op.findingTag({ label: '3 OF 3 DRONES', pct: null, tone: 'drone' }, true);
  const items = [{ id: 'A', px: 300, py: 300, w: Math.max(56, tag.width), h: 44 }, { id: 'B', px: 450, py: 300, w: 56, h: 26 }];
  const placed = op.placeLabels(items);
  const [a, b] = ['A', 'B'].map(id => placed.find(l => l.id === id));
  const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  assert.equal(overlap, false);
  assert.equal(a.w, tag.width);
});

test('a label with no free place takes the one that covers least, not a fixed corner', () => {
  // A ring of neighbours leaves no clear position round the middle contact.
  const ring = [];
  for (let i = 0; i < 16; i++) ring.push({ id: 'N' + i, px: 400 + 60 * Math.cos(i * Math.PI / 8), py: 300 + 60 * Math.sin(i * Math.PI / 8), w: 56, h: 26, rank: 1 });
  const placed = op.placeLabels([...ring, { id: 'MID', px: 400, py: 300, w: 114, h: 38 }]);
  const boxes = placed.filter(l => l.id !== 'MID'), mid = placed.find(l => l.id === 'MID');
  const symbols = ring.map(r => ({ x: r.px - 11, y: r.py - 11, w: 22, h: 22 }));
  const area = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const cover = box => [...boxes, ...symbols].reduce((sum, b) => sum + area(box, b), 0);
  const fixedCorner = { x: 400 + 14, y: 300 - 6 - 19, w: 114, h: 38 };
  assert.ok(cover(mid) <= cover(fixedCorner), `${cover(mid)} > ${cover(fixedCorner)}`);
  assert.ok(Number.isFinite(mid.x) && Number.isFinite(mid.y) && ['start', 'end', 'middle'].includes(mid.anchor));
});

test('a verdict says the day it was received', () => {
  assert.equal(op.receivedOn('2026-11-23T19:07:44.512+00:00'), '23 NOV');
  assert.equal(op.receivedOn('2026-01-05T00:30:00Z'), '5 JAN');
  assert.deepEqual([undefined, '', 'yesterday', 12].map(op.receivedOn), ['', '', '', '']);
});

test('a count of drones is compared with the number of contacts in view, never matched one to one', () => {
  const view = n => op.verdictView({labels: Array.from({length: n}, () => ({label: 'drone', confidence: 0.9}))});
  assert.deepEqual(op.lookVerdict(view(3), 3), {confirmed: true, text: 'All 3 contacts in view were seen as drones.'});
  assert.deepEqual(op.lookVerdict(view(2), 3), {confirmed: false, text: '2 drones seen; 3 contacts were in view.'});
  assert.deepEqual(op.lookVerdict(view(4), 3), {confirmed: true, text: 'All 3 contacts in view were seen as drones.'});
  const one = op.verdictView({verdict: {label: 'drone', confidence: 0.95}});
  assert.deepEqual(op.lookVerdict(one, 1), {confirmed: true, text: ''});
  assert.deepEqual(op.lookVerdict(one, 3), {confirmed: false, text: '1 drone seen; 3 contacts were in view.'});
  assert.deepEqual(op.lookVerdict(op.verdictView({verdict: {label: 'bird', confidence: 0.8}}), 1), {confirmed: false, text: ''});
  assert.equal(op.lookVerdict(null, 3), null);
  assert.equal(op.lookVerdict(one, 0), null);
});

test('a verdict on a look at several contacts is carried by every contact in it, as a count', () => {
  const result = n => ({scenario_context: {sim_start_s: 12.6, sim_end_s: 18.2}, labels: Array.from({length: n}, () => ({label: 'drone', confidence: 0.9}))});
  const all = op.cameraFindings([result(3)], LOOKS);
  assert.deepEqual(Object.keys(all).sort(), [...WEST].sort());
  assert.deepEqual(all['DW-005'], {label: '3 OF 3 DRONES', pct: null, tone: 'drone', seen: 3, of: 3});
  // Two seen where three were in view: every contact says so, and none is marked confirmed.
  const short = op.cameraFindings([result(2)], LOOKS);
  assert.deepEqual(short['DW-002'], {label: '2 OF 3 DRONES', pct: null, tone: 'other', seen: 2, of: 3});
  // The east group was not in that clip.
  assert.equal(all['DW-003'], undefined);
});

test('the line from a contact stops at the nearest edge of the camera window', () => {
  const win = {left: 400, top: 300, right: 800, bottom: 700};
  // Level with the window: straight across to its left edge, starting outside the marker.
  assert.deepEqual(op.leaderLine({px: 100, py: 500}, win, 30), {x1: 130, y1: 500, x2: 400, y2: 500});
  // Above and to the left: to the window's corner.
  const diagonal = op.leaderLine({px: 100, py: 100}, win, 0);
  assert.deepEqual([diagonal.x2, diagonal.y2], [400, 300]);
  // Under the window, or so close that a line would be a stub: no line.
  assert.equal(op.leaderLine({px: 500, py: 400}, win, 30), null);
  assert.equal(op.leaderLine({px: 370, py: 500}, win, 30), null);
});

test('only a label that names a drone gets the confirmed colour', () => {
  assert.deepEqual(['drone', 'DRONE', 'Drones', 'UAV', 'quadcopter', 'multirotor UAV'].map(op.verdictTone), Array(6).fill('drone'));
  assert.deepEqual(['bird', 'helicopter', 'uncertain_detection', 'airplane', 'dronelike', '', null, 7].map(op.verdictTone), Array(8).fill('other'));
});

test('the map is framed in the corridor between the summary box and the camera window', () => {
  const site = {x: 0, y: 0, radius_m: 600}, viewport = {w: 1140, h: 800};
  const tracks = [{x: -700, y: 2000}, {x: 700, y: 1900}];
  const screen = (camera, x, y) => op.project(camera, viewport).toScreen(x, y);
  const open = op.operatorCamera(tracks, site, viewport);
  const framed = op.operatorCamera(tracks, site, viewport, {left: 214, right: 462});
  // Every contact, and the whole site circle, sits between the two.
  for (const [x, y] of [[-700, 2000], [700, 1900], [-600, 0], [600, 0]]) {
    const at = screen(framed, x, y);
    assert.ok(at.px >= 214 && at.px <= 1140 - 462, `x=${x} lands at ${at.px}`);
    assert.ok(at.py >= 0 && at.py <= 800);
  }
  // Centred in that corridor, and no larger than the open framing.
  assert.ok(Math.abs(screen(framed, 0, 0).px - (214 + (1140 - 214 - 462) / 2)) < 1e-6);
  assert.ok(framed.scale <= open.scale);
  // With nothing to clear, the framing is exactly what it was.
  assert.deepEqual(op.operatorCamera(tracks, site, viewport, null), open);
  assert.deepEqual(op.operatorCamera(tracks, site, viewport, {left: 214, right: 0}), open);
  // Too narrow to hold both: only the camera window is cleared.
  const narrow = {w: 760, h: 700};
  assert.deepEqual(op.operatorCamera(tracks, site, narrow, {left: 214, right: 340}), op.operatorCamera(tracks, site, narrow, {right: 340}));
});

test('a locked contact’s label sits outside its lock brackets, and other labels keep off them', () => {
  const plain = op.placeLabels([{id: 'a', px: 300, py: 300, w: 60, h: 26}])[0];
  const locked = op.placeLabels([{id: 'a', px: 300, py: 300, w: 60, h: 26, symbol: 56}])[0];
  assert.ok(plain.x < 300 + 28, 'an ordinary label hugs its marker');
  assert.ok(locked.x >= 300 + 28, 'a locked one starts beyond the brackets, 28 px either side');
  const near = op.placeLabels([{id: 'a', px: 300, py: 300, w: 60, h: 26, symbol: 56, rank: 1}, {id: 'b', px: 262, py: 300, w: 60, h: 26}]);
  const b = near.find(label => label.id === 'b');
  assert.ok(b.x + b.w < 300 - 28 || b.x > 300 + 28 || b.y + b.h < 300 - 28 || b.y > 300 + 28, 'the neighbour’s label is off the brackets');
});

test('a camera finding is attached to the contact the camera was cued at when the clip began', () => {
  const cues = [{t: 0, target: null}, {t: 43, target: 'DW-001'}, {t: 47, target: 'DW-003'}];
  assert.equal(op.cueTargetAt(cues, 42.9), null);
  assert.equal(op.cueTargetAt(cues, 46.9), 'DW-001');
  const result = {scenario_context: {sim_start_s: 43, sim_end_s: 47}, verdict: {label: 'drone', confidence: 0.95}};
  assert.deepEqual(op.cameraFindings([result, {verdict: {label: 'drone'}}], cues), {'DW-001': {label: 'DRONE', pct: 95, tone: 'drone'}});
  assert.deepEqual(op.cameraFindings([{...result, verdict: {label: 'bird', confidence: 0.8}}], cues), {'DW-001': {label: 'BIRD', pct: 80, tone: 'other'}});
  assert.deepEqual(op.cameraFindings([{...result, verdict: null}], cues), {});
});

test('the verdict is the sender’s own label in one line, with report markup removed', () => {
  const label = CAPTURED.labels[0];
  const view = op.verdictView({verdict: {label: label.label, confidence: label.confidence, detail: label.structure,
                                         motion: label.motion_state, tracking: label.tracking_status}});
  assert.deepEqual(view, {headline: 'DRONE', confidence: '95% confidence', pct: 95, count: 1, drones: 1, tone: 'drone',
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

test('labels keep off the boxes that sit on top of the map', () => {
  const item = {id: 'a', px: 300, py: 300, w: 80, h: 26};
  const free = op.placeLabels([item])[0];
  assert.equal(free.anchor, 'start');                          // by default the label goes to the right
  // A camera window covering everything to the right: the label has to go somewhere else.
  const win = {left: 318, top: 0, right: 900, bottom: 900};
  const moved = op.placeLabels([item], {avoid: [win]})[0];
  assert.ok(moved.x + moved.w < win.left, `label spans ${moved.x}..${moved.x + moved.w}`);
});

test('every element id on the page is used once', () => {
  // Two elements shared id="mode": the sensor-loss menu and the map's view badge. Code meant for the badge
  // reached the menu instead, so Reset hid the menu and dragging the map emptied it.
  const ids = [...html.matchAll(/<[a-z][^>]*\sid="([^"]+)"/g)].map(match => match[1]);
  const repeated = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
  assert.deepEqual(repeated, []);
  assert.ok(ids.includes('mode') && ids.includes('view-mode'));
});

/* ---------------- camera network ---------------- */
const fence = {id: 'cam-nw-3', kind: 'fixed-camera', place: 'NW CORNER', x: -425, y: 425, heading_deg: 80, hfov_deg: 12, reach_m: 2750, near_m: 735};
const fence2 = {id: 'cam-nw-4', kind: 'fixed-camera', place: 'NW CORNER', x: -425, y: 425, heading_deg: 92, hfov_deg: 12, reach_m: 2750, near_m: 735};
const gate = {id: 'cam-gate-n', kind: 'fixed-camera', place: 'N GATE', x: 0, y: 1500, heading_deg: 90, hfov_deg: 12, reach_m: 2750, near_m: 752};
const radarSensor = {id: 'radar-north', kind: 'radar', x: 0, y: 0, reach_m: 1400};

test('a replay’s sensors are sorted into fixed cameras and the radar, and a replay without them has neither', () => {
  const net = op.network([{id: 'viso-eo', kind: 'eo-camera'}, fence, gate, radarSensor, null, {kind: 'fixed-camera'}]);
  assert.deepEqual(net.cameras.map(c => c.id), ['cam-nw-3', 'cam-gate-n']);
  assert.equal(net.byId['cam-gate-n'], gate);
  assert.equal(net.radar, radarSensor);
  assert.deepEqual(op.network(undefined), {cameras: [], byId: {}, radar: null});
  assert.equal(op.network([{id: 'viso-eo', kind: 'eo-camera'}]).radar, null);
});

test('a line is drawn only from a camera that has just sighted the contact', () => {
  const byId = op.network([fence, gate]).byId;
  const track = {src: {'cameras': 0.2, 'radar-north': 0.4, 'cam-nw-3': 0.2, 'cam-gate-n': 2.6, 'cam-unknown': 0.1}};
  assert.deepEqual(op.camerasOn(track, byId), ['cam-nw-3'], 'the gate saw it 2.6 s ago; the radar and the fix source are not cameras');
  assert.deepEqual(op.camerasOn(track, byId, 3), ['cam-nw-3', 'cam-gate-n']);
  assert.deepEqual(op.camerasOn({}, byId), []);
  assert.deepEqual(op.camerasOn(null, byId), []);
});

test('a camera’s view runs from where a drone comes into the picture out to its reach', () => {
  const view = op.cameraWedge(gate);                    // at (0, 1500), looking north through a 12 degree lens
  assert.equal(view.near, 752);
  assert.equal(view.far, 2750);
  const [nearRight, farRight, farLeft, nearLeft] = view.corners;
  assert.ok(farRight.x > 0 && farLeft.x < 0, 'angles grow anticlockwise, so the first edge is the right-hand one');
  assert.ok(Math.abs(farRight.x + farLeft.x) < 1e-6 && Math.abs(farRight.y - farLeft.y) < 1e-6, 'symmetric about north');
  assert.ok(Math.abs(Math.hypot(farRight.x, farRight.y - 1500) - 2750) < 1e-6);
  assert.ok(Math.abs(Math.hypot(nearLeft.x, nearLeft.y - 1500) - 752) < 1e-6);
  assert.ok(Math.abs(farRight.x - 2750 * Math.sin(6 * Math.PI / 180)) < 1e-6, 'half of twelve degrees either side');
  assert.ok(nearRight.y < farRight.y);
  assert.equal(op.cameraWedge({...gate, near_m: 9000}).near, 2750, 'never further out than the reach');
});

test('directions are counted by place, because two lenses on one pole cannot cross', () => {
  const byId = op.network([fence, fence2, gate]).byId;
  assert.equal(op.placesWithADirection([['cam-nw-3', 81.2, 2400], ['cam-nw-4', 81.2, null]], byId), 1);
  assert.equal(op.placesWithADirection([['cam-nw-3', 81.2, 2400], ['cam-gate-n', 95, 1900], ['cam-gone', 0, 0]], byId), 2);
  assert.equal(op.placesWithADirection(undefined, byId), 0);
});

const early = {
  first_fix: {id: 'DW-001', fix_t: 26.2, fix_range_m: 3256, radar_t: 99.2, radar_range_m: 1388, gain_s: 73},
  first_radar: {id: 'DW-001', fix_t: 26.2, fix_range_m: 3256, radar_t: 99.2, radar_range_m: 1388, gain_s: 73},
};

test('the early-warning counter waits, then counts, then holds the lead once the radar has seen something', () => {
  assert.deepEqual(op.warningHeadline(early, 20), {state: 'waiting', seconds: 0, fix: null, radar: null});
  const ahead = op.warningHeadline(early, 61.2);
  assert.equal(ahead.state, 'ahead');
  assert.ok(Math.abs(ahead.seconds - 35) < 1e-9);
  assert.equal(ahead.radar, null, 'the radar’s first detection is still in the future and is not shown');
  const gained = op.warningHeadline(early, 140);
  assert.equal(gained.state, 'gained');
  assert.ok(Math.abs(gained.seconds - 73) < 1e-9, 'fixed at the lead the cameras had; it does not keep counting');
  assert.equal(gained.radar.radar_range_m, 1388);
  // A replay in which the radar never sees anything keeps counting; one with no fix never starts.
  assert.equal(op.warningHeadline({first_fix: early.first_fix, first_radar: null}, 140).state, 'ahead');
  assert.equal(op.warningHeadline({first_fix: null, first_radar: null}, 140).state, 'waiting');
  assert.equal(op.warningHeadline(undefined, 140).state, 'waiting');
});

test('a contact’s tag counts while only cameras hold it and turns into the time gained when the radar sees it', () => {
  const row = {id: 'DW-002', fix_t: 39.6, fix_range_m: 3117, radar_t: 116.8, radar_range_m: 1388, gain_s: 77.2};
  assert.equal(op.warningTag(row, 30, 1400), null, 'before the cameras placed it there is nothing to say');
  const counting = op.warningTag(row, 80.9, 1400);
  assert.deepEqual([counting.state, counting.short, counting.text, counting.drone], ['ahead', '+41 s', 'CAMERAS +41 s', false]);
  const gained = op.warningTag(row, 150, 1400);
  assert.deepEqual([gained.state, gained.short, gained.text, gained.drone], ['gained', '+77 s', '+77 s BEFORE RADAR', true]);
  assert.equal(gained.width, Math.ceil('+77 s'.length * 6.7 + 12), 'the map label is sized for the short form');
  // A wing that turns away and never comes inside the radar's reach keeps counting.
  assert.equal(op.warningTag({...row, radar_t: null, radar_range_m: null, gain_s: null}, 150, 1400).short, '+110 s');
  // First placed inside the radar's reach, or seen by the radar at the same moment: never early, no tag.
  assert.equal(op.warningTag({id: 'DW-009', fix_t: 101.8, fix_range_m: 1330, radar_t: null, gain_s: null}, 105, 1400), null);
  assert.equal(op.warningTag({id: 'DW-009', fix_t: 101.8, fix_range_m: 1330, radar_t: 101.8, gain_s: 0}, 105, 1400), null);
  assert.equal(op.warningTag(undefined, 105, 1400), null);
});

test('with a camera network the view takes in every camera and the contacts, beside the boxes on the left', () => {
  const site = {x: 0, y: 0, radius_m: 600}, viewport = {w: 1100, h: 800};
  const cameras = [{x: -1900, y: 1500}, {x: 1900, y: 1500}, {x: 2000, y: -200}, {x: -2000, y: -200}, {x: 0, y: -1500}, {x: 0, y: 1500}];
  const far = [{x: -150, y: 3250}], near = [{x: -150, y: 1200}, {x: 300, y: 900}];
  const onScreen = (view, p, left) => {
    const q = op.project(view, viewport).toScreen(p.x, p.y);
    return q.px >= (left || 0) + 30 && q.px <= viewport.w - 30 && q.py >= 30 && q.py <= viewport.h - 30;
  };
  const open = op.operatorCamera(far, site, viewport, {left: 262, right: 0}, cameras);
  for (const p of [...cameras, ...far, {x: 0, y: -600}]) assert.ok(onScreen(open, p, 262), JSON.stringify(p));
  // As the group comes in the furthest thing to show is nearer, so the picture closes in on the network.
  const closed = op.operatorCamera(near, site, viewport, {left: 262, right: 0}, cameras);
  assert.ok(closed.scale > open.scale * 1.25, `${closed.scale} vs ${open.scale}`);
  for (const p of [...cameras, ...near]) assert.ok(onScreen(closed, p, 262), JSON.stringify(p));
  // The site is not pinned to a place on the screen in this mode, and without cameras nothing changes.
  const sitePy = v => op.project(v, viewport).toScreen(0, 0).py;
  assert.ok(Math.abs(sitePy(open) - sitePy(closed)) > 40);
  assert.deepEqual(op.operatorCamera(far, site, viewport, null, []), op.operatorCamera(far, site, viewport, null));
});

test('the camera network has its key, its counter and its demo link on the page', () => {
  for (const id of ['net-box', 'net-title', 'net-radar', 'net-note']) assert.ok(html.includes(`id="${id}"`), id);
  assert.ok(html.includes("demo==='cameras'") && html.includes("state.lossMode='camera_network'"));
  assert.ok(html.includes('Camera detections here are simulated.'), 'the page says what is simulated');
  assert.ok(/\.net-box\[hidden\]\{display:none\}/.test(html));
});

test('the view is left alone for a small drift and moved at once for a contact off the picture', () => {
  const viewport = {w: 1100, h: 800}, ref = {cx: 0, cy: 900, scale: 0.15};
  const inside = [{x: 0, y: 2000}], above = [{x: 0, y: 900 + 400 / 0.15}];      // 400 px above the middle: off the top
  const nudge = {cx: 0, cy: 930, scale: 0.155};
  // Ordinary modes: only a large drift, or a contact under a box at the side, moves the view.
  assert.equal(op.needsReframe(ref, nudge, inside, viewport, null, false), false);
  assert.equal(op.needsReframe(ref, {cx: 0, cy: 900, scale: 0.17}, inside, viewport, null, false), true, 'thirteen percent closer');
  assert.equal(op.needsReframe(ref, nudge, above, viewport, null, false), false, 'without boxes or a network nothing is checked');
  const underBox = [{x: (120 - 550) / 0.15, y: 900}];                             // 120 px from the left edge
  assert.equal(op.needsReframe(ref, nudge, underBox, viewport, {left: 262, right: 0}, false), true);
  // With a camera network the view is steadier, and the top and bottom of the picture count too.
  assert.equal(op.needsReframe(ref, {cx: 0, cy: 900, scale: 0.17}, inside, viewport, {left: 262, right: 0}, true), false, 'thirteen percent is not enough here');
  assert.equal(op.needsReframe(ref, {cx: 0, cy: 900, scale: 0.19}, inside, viewport, {left: 262, right: 0}, true), true);
  assert.equal(op.needsReframe(ref, nudge, above, viewport, {left: 262, right: 0}, true), true, 'a contact above the picture');
  assert.equal(op.needsReframe(ref, ref, above, viewport, {left: 262, right: 0}, true), false, 'nothing better to move to');
});
