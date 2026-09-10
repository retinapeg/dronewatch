(function () {
  'use strict';
  const Scenario = window.DroneWatchScenario;
  const $ = id => document.getElementById(id);
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text !== undefined && text !== null) node.textContent = text; if (className) node.className = className; return node; };
  const put = (id, text) => { const node = $(id); if (node && node.textContent !== String(text)) node.textContent = text; };
  const statusClass = status => ({ THREAT: 'threat', 'POSSIBLE THREAT': 'possible', TRACKED: 'tracked', UNKNOWN: 'unknown' }[status] || 'unknown');
  const color = status => ({ THREAT: '#ef9687', 'POSSIBLE THREAT': '#d7bd80', TRACKED: '#bed2c4', UNKNOWN: '#a2b6c6' }[status] || '#a2b6c6');
  const glyph = status => status === 'UNKNOWN' ? '◇' : '⌃';
  const sourceLabel = kind => ({ SENSOR_EVENT: 'Sensor event', SYNTHETIC_EVENT: 'SYNTHETIC EVENT', WEBHOOK_EVENT: 'Unverified webhook', TEST_EVENT: 'TEST EVENT' }[kind] || 'Unverified source');
  const targetKey = target => JSON.stringify([target.source_kind, target.source, target.target_id]);
  const shortID = (value, limit = 28) => value.length > limit ? `${value.slice(0, limit - 7)}…${value.slice(-6)}` : value;
  const confidenceText = target => typeof target.confidence === 'number' && Number.isFinite(target.confidence) ? `${Math.round(target.confidence * 100)}%` : 'Unavailable';
  const formatTime = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds) % 60).padStart(2, '0')}`;
  const formatDate = value => { const parsed = Date.parse(value); return Number.isFinite(parsed) ? new Date(parsed).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'Timestamp unverified'; };
  const params = new URLSearchParams(location.search);
  let mode = params.get('mode') === 'sensor' ? 'sensor' : 'demo';
  let elapsed = 0, count = 5, playing = true, focused = false;
  let tracks = Scenario.snapshot(0, count), sensorRecords = [], selectedKey = targetKey(tracks[0]);
  let sensorConnected = false, sensorAttempted = false, sensorError = '', sensorTruncated = false, request = null, requestEpoch = 0;
  let lastTick = performance.now(), lastActivity = -1;
  const markers = new Map();
  const observationFreshness = target => target.timestamp_basis === 'reported_event_time' ? Scenario.freshness(target.updated_at) : { fresh: false, label: 'Observation time unverified' };
  const selected = () => tracks.find(target => targetKey(target) === selectedKey) || null;
  const announce = message => put('announcements', message);
  function setLocationMode() {
    const url = new URL(location.href);
    if (mode === 'sensor') url.searchParams.set('mode', 'sensor'); else url.searchParams.delete('mode');
    history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }
  function setMode(next) {
    if (next === mode) return;
    mode = next; requestEpoch++; if (request) request.abort(); request = null;
    selectedKey = ''; focused = false; lastActivity = -1;
    tracks = mode === 'demo' ? Scenario.snapshot(elapsed, count) : sensorRecords;
    if (tracks.length) selectedKey = targetKey(tracks[0]);
    setLocationMode(); renderAll();
    announce(mode === 'demo' ? 'Synthetic demo mode. All targets and confidence values are illustrative.' : 'Sensor event mode. No inferred map positions.');
    if (mode === 'sensor') refreshSensors();
  }
  function inspect(key, scroll = true) {
    if (!tracks.some(target => targetKey(target) === key)) return;
    selectedKey = key; renderSelection();
    if (scroll && matchMedia('(max-width:760px)').matches) $('target-detail').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    announce(`${selected().target_id} selected. ${selected().status.toLowerCase()}.`);
  }
  function focusSelected() {
    if (!selected() || mode !== 'demo') return;
    focused = !focused; drawRadar(); renderFocusControl();
    $('air-picture').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    announce(focused ? `${selected().target_id} focused. Other targets remain accessible in the target register.` : 'Showing all synthetic targets.');
  }
  function renderFocusControl() {
    const label = focused ? 'Show all targets' : 'Focus selected target';
    $('focus-target').setAttribute('aria-label', label);
    $('focus-target').replaceChildren(el('span', '⌖'), document.createTextNode(` ${label}`));
    const detailFocus = $('detail-focus'); if (detailFocus) detailFocus.textContent = focused ? 'Show all targets on air picture' : 'Focus target on air picture';
    put('radar-scale', focused ? 'TARGET FOCUS · 1.7×' : 'OVERVIEW');
    put('selection-note', selected() ? `${selected().target_id} selected` : 'No target selected');
  }
  function camera() {
    const target = selected();
    if (!focused || !target?.position) return { scale: 1, x: 0, y: 0 };
    const scale = 1.7, half = .5 / scale;
    const centerX = Math.max(half, Math.min(1 - half, target.position.x));
    const centerY = Math.max(half, Math.min(1 - half, target.position.y));
    return { scale, x: .5 - centerX * scale, y: .5 - centerY * scale };
  }
  function drawRadar() {
    if (mode !== 'demo') return;
    const view = camera(), target = selected();
    $('world-layer').setAttribute('transform', `translate(${view.x * 1000} ${view.y * 1000}) scale(${view.scale})`);
    const zoneX = .5 * view.scale + view.x, zoneY = .53 * view.scale + view.y;
    $('zone-label').style.left = `${zoneX * 100}%`; $('zone-label').style.top = `${zoneY * 100}%`;
    $('zone-label').hidden = zoneX < .13 || zoneX > .87 || zoneY < .08 || zoneY > .9;
    const pathFragment = document.createDocumentFragment();
    for (const item of tracks) {
      const key = targetKey(item);
      let marker = markers.get(key);
      if (!marker) {
        marker = el('button', null, `target-marker ${statusClass(item.status)}`);
        marker.type = 'button'; marker.dataset.targetId = item.target_id;
        marker.setAttribute('aria-label', `Inspect target ${item.target_id}`);
        marker.append(el('span', '↑', 'marker-glyph'), el('span', item.target_id, 'marker-label'));
        marker.addEventListener('click', () => inspect(key)); markers.set(key, marker); $('marker-layer').append(marker);
      }
      const x = item.position.x * view.scale + view.x, y = item.position.y * view.scale + view.y;
      // Hide markers fully outside the view; the register always retains all targets.
      marker.hidden = x < .07 || x > .93 || y < .075 || y > .92;
      marker.querySelector('.marker-glyph').style.transform = `rotate(${item.course_degrees}deg)`;
      marker.style.left = `${x * 100}%`; marker.style.top = `${y * 100}%`;
      marker.setAttribute('aria-pressed', String(key === selectedKey));
      const drawPath = (points, predicted) => {
        if (points.length < 2) return;
        const line = document.createElementNS(ns, 'polyline');
        line.setAttribute('points', points.map(point => `${point.x * 1000},${point.y * 1000}`).join(' '));
        line.setAttribute('fill', 'none'); line.setAttribute('stroke', color(item.status));
        line.setAttribute('stroke-width', key === selectedKey ? '2.7' : '1.6');
        line.setAttribute('stroke-opacity', key === selectedKey ? '.9' : '.4');
        line.setAttribute('vector-effect', 'non-scaling-stroke');
        if (predicted) line.setAttribute('stroke-dasharray', '4 6');
        pathFragment.append(line);
      };
      drawPath(item.history, false); drawPath(item.predicted_path, true);
    }
    for (const [key, marker] of markers) if (!tracks.some(item => targetKey(item) === key)) { marker.remove(); markers.delete(key); }
    $('path-layer').replaceChildren(pathFragment);
    if (target) {
      put('detail-position', `${Math.round(target.position.x * 100)} E / ${Math.round(target.position.y * 100)} S · schematic`);
      put('detail-updated', `${formatTime(elapsed)} scenario time`);
    }
  }
  function renderRoster() {
    const activeKey = document.activeElement?.dataset?.targetKey;
    const fragment = document.createDocumentFragment();
    const idCounts = new Map(); for (const item of tracks) idCounts.set(item.target_id, (idCounts.get(item.target_id) || 0) + 1);
    for (const target of tracks) {
      const key = targetKey(target), button = el('button', null, `target-row ${statusClass(target.status)}`);
      button.type = 'button'; button.dataset.targetKey = key; button.dataset.targetId = target.target_id;
      const duplicateID = idCounts.get(target.target_id) > 1;
      button.setAttribute('aria-label', `Select target ${target.target_id}${duplicateID ? ` from ${target.source} (${sourceLabel(target.source_kind)})` : ''}`); button.setAttribute('aria-pressed', String(selectedKey === key));
      button.append(el('span', glyph(target.status), 'row-icon'));
      const main = el('span', null, 'row-main'); main.append(el('strong', target.target_id));
      if (duplicateID) main.append(el('small', `Source: ${shortID(target.source)}`, 'row-source'));
      const age = observationFreshness(target);
      main.append(el('small', mode === 'demo' ? `${target.direction} · scripted` : `${sourceLabel(target.source_kind)} · ${!sensorConnected ? 'cached' : age.label}`, mode === 'sensor' && (!sensorConnected || !age.fresh) ? 'stale-label' : undefined));
      const state = el('span', target.status, 'row-status');
      state.append(el('small', `${confidenceText(target)} ${mode === 'demo' ? 'illustrative' : target.source_kind === 'SYNTHETIC_EVENT' ? 'synthetic' : 'reported'}`));
      button.append(main, state); button.addEventListener('click', () => inspect(key)); fragment.append(button);
    }
    if (!tracks.length) fragment.append(el('p', sensorError ? 'The event feed is unavailable. Refresh to retry.' : 'No sensor observations yet. Incoming events will appear here.', 'empty-state'));
    $('target-list').replaceChildren(fragment);
    if (activeKey) Array.from($('target-list').querySelectorAll('button')).find(button => button.dataset.targetKey === activeKey)?.focus({ preventScroll: true });
  }
  function field(fragment, name, value, id, wide = false) {
    const row = el('div', null, wide ? 'wide-field' : undefined), term = el('dt', name), definition = el('dd', value);
    if (id) definition.id = id; row.append(term, definition); fragment.append(row);
  }
  function renderDetail() {
    const target = selected(), wasOpen = $('interpretation')?.open || false;
    const activeDetailID = $('detail-content').contains(document.activeElement) ? document.activeElement.id : '';
    const previousTarget = $('detail-content').dataset.targetKey;
    $('detail-content').dataset.targetKey = target ? targetKey(target) : '';
    $('detail-content').replaceChildren();
    if (!target) { $('detail-content').append(el('p', 'Select an observation when one becomes available. Missing sensor data is never replaced with synthetic positions.', 'empty-state')); return; }
    const demo = mode === 'demo';
    put('detail-subtitle', demo ? 'Scenario-authored observation' : sourceLabel(target.source_kind));
    const body = el('div', null, 'detail-body'), identity = el('div', null, 'detail-identity');
    identity.append(el('h3', target.target_id), el('span', target.status, `status-badge ${statusClass(target.status)}`)); body.append(identity);
    const confidence = el('div', null, 'confidence-line'); confidence.append(el('span', demo ? 'Scenario confidence' : 'Reported confidence'), el('strong', confidenceText(target))); body.append(confidence);
    const bar = el('div', null, 'confidence-track'), fill = el('span'); fill.style.width = `${typeof target.confidence === 'number' ? target.confidence * 100 : 0}%`; bar.append(fill); body.append(bar);
    body.append(el('p', demo ? 'Illustrative value · no classifier is running' : target.source_kind === 'SYNTHETIC_EVENT' ? 'Stored synthetic event · not sensor evidence' : 'Source-provided value · not independently verified', 'confidence-note'));
    const reason = el('div', null, 'reason'); reason.append(el('strong', demo ? 'WHY INSPECT' : 'REPORTED OBSERVATION'), el('p', demo ? target.reason : `Status ${target.status.toLowerCase()} is derived from the reported event. It does not establish identity or intent.`)); body.append(reason);
    const fields = el('dl', null, 'detail-fields');
    field(fields, demo ? 'Course' : 'Velocity / heading', demo ? `${target.direction} · scripted` : 'Unavailable');
    field(fields, 'Prediction', demo ? 'Route to 01:30 · scripted' : 'Unavailable');
    field(fields, demo ? 'Boundary' : 'Geographic position', demo ? (target.priority <= 2 ? 'Approaching · scripted' : 'Outside · scripted') : 'Unavailable');
    field(fields, 'Range / time to boundary', 'Not calibrated');
    field(fields, demo ? 'Position · schematic units / 100' : 'Reported frame position', demo ? `${Math.round(target.position.x * 100)} E / ${Math.round(target.position.y * 100)} S · schematic` : target.position ? `x ${target.position.x.toFixed(3)}, y ${target.position.y.toFixed(3)} · camera frame only` : 'Not provided', 'detail-position', true);
    field(fields, demo ? 'Scenario update' : 'Observation time', demo ? `${formatTime(elapsed)} scenario time` : formatDate(target.updated_at), 'detail-updated', true);
    if (!demo && target.last_received_at) field(fields, 'Received by DroneWatch', formatDate(target.last_received_at), null, true);
    if (!demo) field(fields, 'Freshness', !sensorConnected ? 'Cached · connection unavailable' : observationFreshness(target).label, 'detail-freshness', true);
    body.append(fields);
    if (demo) { const focus = el('button', focused ? 'Show all targets on air picture' : 'Focus target on air picture', 'detail-action'); focus.type = 'button'; focus.id = 'detail-focus'; focus.addEventListener('click', focusSelected); body.append(focus); }
    const detail = el('details', null, 'interpretation'); detail.id = 'interpretation'; detail.open = wasOpen;
    const summary = el('summary', 'Source & interpretation'); summary.id = 'source-interpretation-toggle'; detail.append(summary);
    detail.append(el('h4', 'Source'), el('p', demo ? 'SYNTHETIC · local deterministic scenario 01' : `${target.source_kind} · ${typeof target.source === 'string' ? target.source : 'Source unavailable'}`));
    detail.append(el('h4', 'Evidence available'));
    const evidence = el('ul'); for (const item of target.evidence || []) evidence.append(el('li', item)); if (!evidence.childNodes.length) evidence.append(el('li', 'No additional evidence provided.')); detail.append(evidence);
    detail.append(el('h4', 'Uncertainty'), el('p', typeof target.uncertainty === 'string' ? target.uncertainty : 'A reported observation does not verify identity, intent or geographic position.'));
    detail.append(el('h4', 'Alternative interpretation'), el('p', typeof target.alternative_interpretation === 'string' ? target.alternative_interpretation : 'Several explanations may fit the observation. Additional independent evidence is required.'));
    body.append(detail); $('detail-content').append(body);
    if (activeDetailID && previousTarget === targetKey(target)) $(activeDetailID)?.focus({ preventScroll: true });
  }
  function renderSelection() {
    for (const button of $('target-list').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.targetKey === selectedKey));
    renderDetail(); drawRadar(); renderFocusControl();
  }
  function renderPlayback() {
    const label = playing ? 'Pause scenario' : 'Resume scenario';
    $('play-pause').setAttribute('aria-label', label);
    $('play-pause').firstElementChild.textContent = playing ? 'Ⅱ' : '▷'; put('play-label', playing ? 'Pause' : 'Resume');
    put('playback-state', elapsed >= Scenario.DURATION ? 'COMPLETE' : playing ? 'PLAYING' : 'PAUSED');
    put('scenario-time', formatTime(elapsed)); $('progress-fill').style.width = `${elapsed / Scenario.DURATION * 100}%`;
  }
  function renderActivity(force = false) {
    const stage = Math.min(3, Math.floor(elapsed / 30));
    if (mode === 'demo' && stage === lastActivity && !force) return;
    lastActivity = stage; const fragment = document.createDocumentFragment();
    if (mode === 'demo') {
      const entries = [[0, `${count} synthetic tracks established. DW-01 marked for first review.`]];
      if (stage >= 1) entries.unshift([30, 'DW-01 continues on its scripted inbound course. Priorities remain scenario-authored.']);
      if (stage >= 2) entries.unshift([60, 'Inbound tracks approach the observation boundary. Inspect course and uncertainty.']);
      if (stage >= 3) entries.unshift([90, 'Scenario complete. Reset to replay the same deterministic sequence.']);
      for (const [time, description] of entries.slice(0, 3)) { const row = el('li'); row.append(el('span', formatTime(time), 'log-time'), el('span', description)); fragment.append(row); }
    } else {
      for (const target of tracks.slice(0, 3)) { const row = el('li'); row.append(el('span', 'EVENT', 'log-time'), el('span', `${target.target_id} · ${target.status.toLowerCase()} · ${observationFreshness(target).label.toLowerCase()}`)); fragment.append(row); }
      if (!tracks.length) { const row = el('li'); row.append(el('span', '—', 'log-time'), el('span', 'No sensor observations available.')); fragment.append(row); }
    }
    $('activity-list').replaceChildren(fragment);
  }
  function renderSensorStatus() {
    const notice = $('sensor-notice'); notice.hidden = mode !== 'sensor' || !sensorError;
    put('sensor-notice', sensorError);
    $('sensor-window-notice').hidden = mode !== 'sensor' || !sensorTruncated;
    put('sensor-window-notice', 'Showing a limited window of stored observations. Additional events are not included in this view.');
    const message = sensorError || (!sensorAttempted ? 'Connecting to the stored event feed…' : !sensorRecords.length ? 'No sensor observations yet · feed reachable' : 'Stored event feed reachable · observation freshness shown per target');
    put('sensor-feed-note', message);
    if (mode === 'sensor') put('footer-status', sensorError ? 'EVENT FEED UNAVAILABLE · AUTOMATIC RETRY' : 'STORED EVENT FEED · NO DIRECT SENSOR CONNECTION CLAIM');
  }
  function renderAll() {
    const demo = mode === 'demo';
    $('demo-mode').setAttribute('aria-pressed', String(demo)); $('sensor-mode').setAttribute('aria-pressed', String(!demo));
    $('demo-picture').hidden = !demo; $('sensor-picture').hidden = demo;
    document.body.dataset.mode = mode;
    document.querySelector('.local-status').lastChild.textContent = demo ? 'LOCAL SCENARIO' : 'STORED EVENTS';
    put('mission-title', demo ? 'Perimeter watch.' : 'Sensor observations.');
    put('mission-summary', demo ? `${{3: 'Three',5: 'Five',10: 'Ten'}[count] || count} tracks around a protected area. Two need attention.` : 'Review reported events, provenance and freshness.');
    $('provenance-badge').replaceChildren(el('i'), document.createTextNode(demo ? 'SYNTHETIC DEMO' : 'SENSOR EVENT VIEW'));
    put('provenance-description', demo ? 'Scripted targets. Illustrative confidence. No live sensor or classification claims.' : 'Stored webhook observations. Synthetic and test events retain their source labels.');
    put('picture-heading', demo ? 'Air picture' : 'Sensor context'); put('picture-subtitle', demo ? 'Schematic view · positions are not geographic' : 'Source-reported events · no invented trajectories');
    put('track-count', `${String(tracks.length).padStart(2, '0')} ${demo ? 'TRACKS' : 'EVENTS'}`);
    put('roster-heading', demo ? 'Target register' : 'Observation register'); put('roster-subtitle', demo ? 'Ordered by scenario priority' : 'Latest reported observations');
    put('detail-subtitle', demo ? 'Scenario-authored observation' : 'Source-reported observation');
    put('attention-eyebrow', demo ? 'REVIEW FIRST' : 'LATEST OBSERVATION');
    const first = tracks[0];
    put('attention-title', demo ? 'DW-01 · Approaching the protected area' : first ? `${shortID(first.target_id)} · ${first.status.toLowerCase()}` : 'Awaiting sensor observations');
    put('attention-description', demo ? 'Highest priority in this scripted scenario' : 'Reported event status does not establish intent');
    $('inspect-priority').disabled = !first;
    $('inspect-priority').replaceChildren(document.createTextNode(`Inspect ${first ? shortID(first.target_id, 18) : 'target'} `), el('span', '↗'));
    if (demo) put('footer-status', 'DEMO RUNS LOCALLY · NO EXTERNAL SERVICES');
    renderRoster(); renderDetail(); renderFocusControl(); drawRadar(); renderPlayback(); renderActivity(true); renderSensorStatus();
  }
  async function refreshSensors() {
    if (mode !== 'sensor' || request) return;
    const controller = new AbortController(), epoch = requestEpoch; request = controller;
    const timeout = setTimeout(() => controller.abort(), 6000);
    $('retry-sensors').disabled = true;
    try {
      const response = await fetch('/api/targets', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`Sensor feed unavailable (HTTP ${response.status})`);
      const payload = await response.json();
      const next = Scenario.normalizeSensorPayload(payload);
      if (epoch !== requestEpoch || mode !== 'sensor') return;
      sensorRecords = next; sensorTruncated = payload.truncated === true; sensorConnected = true; sensorAttempted = true; sensorError = ''; tracks = next;
      if (!tracks.some(target => targetKey(target) === selectedKey)) selectedKey = tracks.length ? targetKey(tracks[0]) : '';
      renderAll();
    } catch (error) {
      if (epoch !== requestEpoch || mode !== 'sensor') return;
      sensorConnected = false; sensorAttempted = true;
      sensorError = sensorRecords.length ? 'Sensor feed unavailable or invalid. Showing cached observations; freshness is not confirmed. Retrying automatically.' : 'Sensor feed unavailable or invalid. No sensor data can be verified. Retrying automatically; the synthetic demo remains available.';
      renderAll();
    } finally {
      clearTimeout(timeout);
      if (request === controller) request = null;
      if (epoch === requestEpoch) $('retry-sensors').disabled = false;
    }
  }
  $('demo-mode').addEventListener('click', () => setMode('demo'));
  $('sensor-mode').addEventListener('click', () => setMode('sensor'));
  $('inspect-priority').addEventListener('click', () => { if (tracks[0]) inspect(targetKey(tracks[0])); });
  $('focus-target').addEventListener('click', focusSelected);
  $('play-pause').addEventListener('click', () => {
    if (elapsed >= Scenario.DURATION) { elapsed = 0; tracks = Scenario.snapshot(elapsed, count); lastActivity = -1; playing = true; }
    else playing = !playing;
    lastTick = performance.now(); renderPlayback(); drawRadar(); renderActivity();
    announce(playing ? 'Synthetic scenario playing.' : 'Synthetic scenario paused.');
  });
  $('reset-scenario').addEventListener('click', () => {
    elapsed = 0; lastTick = performance.now(); focused = false; tracks = Scenario.snapshot(0, count); selectedKey = tracks.length ? targetKey(tracks[0]) : ''; lastActivity = -1;
    renderAll(); announce('Scenario reset to its deterministic starting positions.');
  });
  $('scenario-count').addEventListener('change', event => {
    count = [3, 5, 10].includes(Number(event.target.value)) ? Number(event.target.value) : 5;
    elapsed = 0; lastTick = performance.now(); focused = false; tracks = Scenario.snapshot(0, count);
    if (!tracks.some(target => targetKey(target) === selectedKey)) selectedKey = targetKey(tracks[0]);
    lastActivity = -1; renderAll(); announce(`${count} synthetic targets. Scenario reset.`);
  });
  $('retry-sensors').addEventListener('click', refreshSensors);
  document.addEventListener('visibilitychange', () => { lastTick = performance.now(); if (!document.hidden && mode === 'sensor') refreshSensors(); });
  setInterval(() => {
    const now = performance.now(), delta = (now - lastTick) / 1000; lastTick = now;
    if (mode !== 'demo' || !playing || document.hidden) return;
    elapsed = Math.min(Scenario.DURATION, elapsed + Math.min(delta, 1));
    if (elapsed >= Scenario.DURATION) playing = false;
    tracks = Scenario.snapshot(elapsed, count); drawRadar(); renderPlayback(); renderActivity();
  }, 250);
  setInterval(() => { if (mode === 'sensor' && !document.hidden) refreshSensors(); }, 5000);
  // Initial sensor deep links must not borrow a synthetic selection or record.
  if (mode === 'sensor') { tracks = []; selectedKey = ''; }
  $('sensor-feed-note').dataset.testid = 'sensor-status';
  renderAll(); if (mode === 'sensor') refreshSensors();
})();
