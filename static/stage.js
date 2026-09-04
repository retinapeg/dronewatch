(() => {
  'use strict';
  const $ = id => document.getElementById(id), C = StageCore, svgNS = 'http://www.w3.org/2000/svg';
  let state = null, fromTrack = null, displayed = null, targetAt = 0, pending = false, actionVersion = 0, busy = false, lost = false, previousKey = '', eventKey = '', toastTimer;
  const text = (id, value) => { $(id).textContent = value; };
  const number = (value, decimals = 0) => Number.isFinite(value) ? value.toFixed(decimals) : '--';
  function toast(message) { text('toast', message); $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
  async function request(path, method = 'GET') {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 2500);
    try {
      const response = await fetch(path + (path.includes('?') ? '&' : '?') + 't=' + Date.now(), {method, cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Backend returned ' + response.status);
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function connection(ok) {
    lost = !ok; $('connection').classList.toggle('lost', !ok); document.body.classList.toggle('connection-lost', !ok);
    text('connection', ok ? 'DEMO SYSTEM ONLINE' : 'BACKEND CONNECTION LOST');
    if (!ok) { text('banner', 'BACKEND CONNECTION LOST'); text('severity', 'LAST RECEIVED STATE'); }
  }
  function accept(next) {
    if (!next || !Number.isFinite(next.elapsed_s) || !Array.isArray(next.events)) throw new Error('Invalid demo state');
    connection(true);
    const newRun = state && next.run_id !== state.run_id;
    fromTrack = newRun ? null : displayed;
    state = next; targetAt = performance.now();
    const t = state.track, coast = t?.state === 'COASTING';
    document.body.classList.toggle('warning', state.threat === 'WARNING');
    document.body.classList.toggle('high', state.threat === 'HIGH');
    document.body.classList.toggle('coasting', coast);
    text('banner', state.banner); text('severity', state.threat === 'HIGH' ? 'HIGH PRIORITY' : coast ? 'PREDICTED POSITION' : state.threat === 'WARNING' ? 'WARNING' : t ? 'CONTACT TRACKED' : 'MONITORING');
    text('contact-count', t ? '01' : '00'); text('radar-caption', t ? t.state : 'NO CURRENT CONTACT');
    text('track-id', t?.track_id || 'NO CONTACT'); text('track-state', t?.state || 'STANDBY');
    text('position-source', t?.position_source || 'AWAITING DETECTION');
    text('last-observation', t ? number(t.last_observation_age_s, 1) + ' s AGO' : 'NO OBSERVATION');
    $('uncertainty-row').hidden = !coast; text('uncertainty-value', t ? '+/- ' + number(t.uncertainty_m) + ' m' : '--');
    $('association-row').hidden = t?.state !== 'REACQUIRED';
    if (state.association) text('association-value', (state.association.accepted ? 'PASS / ' : 'FAIL / ') + number(state.association.residual_m, 1) + ' m < ' + state.association.threshold_m + ' m');
    $('sensor-view').classList.toggle('signal-lost', coast);
    const pulseKey = state.run_id + ':' + (t?.state || 'CLEAR');
    if (pulseKey !== previousKey) {
      $('contact').classList.remove('acquired'); $('sensor-view').classList.remove('reacquired');
      if (t && ['DETECTED', 'REACQUIRED'].includes(t.state)) {
        void $('contact').getBoundingClientRect(); $('contact').classList.add('acquired');
        if (t.state === 'REACQUIRED') $('sensor-view').classList.add('reacquired');
      }
      previousKey = pulseKey;
    }
    $('sensor-overlay').hidden = !!state.measurement;
    $('eo-target').hidden = !state.measurement;
    text('sensor-message', coast ? 'SIGNAL LOST' : 'MONITORING');
    text('sensor-submessage', 'NO CURRENT OBSERVATION');
    text('sensor-status', coast ? 'SIGNAL LOST' : state.measurement ? (t?.state === 'REACQUIRED' ? 'CONTACT REACQUIRED' : 'UAS DETECTED') : 'MONITORING');
    if (state.measurement) text('eo-label', 'UAS ' + number(state.measurement.confidence * 100) + '%');
    text('pause', state.running ? 'PAUSE' : state.has_started && !state.complete ? 'RESUME' : 'PAUSE');
    text('elapsed', '00:' + String(Math.floor(state.elapsed_s)).padStart(2, '0') + ' / 01:00');
    text('timeline-label', state.complete ? 'FINAL STATE HELD / RESET TO REPEAT' : !state.has_started ? 'READY TO RUN' : !state.running ? 'PAUSED' : 'PROTECTED SITE APPROACH');
    $('progress').style.width = Math.min(100, state.elapsed_s / 60 * 100) + '%';
    $('warning-zone').setAttribute('r', state.zones.warning_m / 2500 * 415);
    const key = state.events.map(e => e.id).join('|');
    if (key !== eventKey) {
      eventKey = key; const fragment = document.createDocumentFragment();
      state.events.slice(-6).reverse().forEach(event => {
        const li = document.createElement('li'); li.className = event.category;
        const time = document.createElement('time'); time.textContent = 'T+' + number(event.time_s, 1).padStart(4, '0');
        const category = document.createElement('span'); category.className = 'category'; category.textContent = event.category;
        const message = document.createElement('span'); message.className = 'message'; message.textContent = event.message; message.title = event.message;
        li.append(time, category, message); fragment.append(li);
      });
      $('event-log').replaceChildren(fragment);
    }
    const trail = document.createDocumentFragment(), history = t?.history || [];
    for (let i = 1; i < history.length; i++) {
      const a = C.project(history[i - 1].x, history[i - 1].y), b = C.project(history[i].x, history[i].y);
      const line = document.createElementNS(svgNS, 'line');
      Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:history[i].predicted?'#e6b765':'#8dc5d5','stroke-width':2.5,'stroke-opacity':.2+.65*i/history.length}).forEach(([k,v])=>line.setAttribute(k,v));
      if (history[i].predicted) line.setAttribute('stroke-dasharray', '5 5'); trail.append(line);
    }
    $('trail').replaceChildren(trail);
  }
  function render(now) {
    if (state) {
      displayed = C.interpolate(fromTrack, state.track, lost ? 1 : (now - targetAt) / 190);
      $('contact').hidden = !displayed;
      if (displayed) {
        const t = displayed, p = C.project(t.x, t.y); $('contact').setAttribute('transform', `translate(${p.x} ${p.y})`);
        $('contact').querySelector('.contact-shape').setAttribute('transform', 'rotate(' + (t.heading_deg || 0) + ')');
        $('uncertainty').setAttribute('r', t.uncertainty_m / 2500 * 415); text('radar-state', t.state);
        $('range').innerHTML = number(t.range_m) + ' <small>m</small>';
        $('bearing').innerHTML = number(t.bearing_deg, 1) + ' <small>deg</small>';
        $('altitude').innerHTML = number(t.altitude_m) + ' <small>m</small>';
        $('speed').innerHTML = number(t.speed_mps, 1) + ' <small>m/s</small>';
        if (state.measurement) {
          // Procedural sensor illustration, not a calibrated camera projection.
          const x = 320 + t.x / 2500 * 110, y = 145 - t.y / 2500 * 28;
          $('eo-target').setAttribute('transform', `translate(${x} ${y})`);
        }
      } else {
        ['range','bearing','altitude','speed'].forEach(id => text(id, '--'));
      }
    }
    text('sensor-time', new Date().toISOString().slice(11,19) + ' UTC');
    requestAnimationFrame(render);
  }
  async function poll() {
    if (pending || busy) return;
    pending = true; const version = actionVersion;
    try { const next = await request('/api/stage/state'); if (version === actionVersion) accept(next); }
    catch (_) { if (version === actionVersion) connection(false); }
    finally { pending = false; }
  }
  async function action(path) {
    if (busy) return;
    busy = true; actionVersion++;
    try { accept(await request('/api/stage/' + path, 'POST')); }
    catch (error) { connection(false); toast('Could not reach the backend. Controls will recover automatically.'); }
    finally { busy = false; }
  }
  $('run').addEventListener('click', () => action('start'));
  $('reset').addEventListener('click', () => action('reset'));
  $('pause').addEventListener('click', () => action('pause'));
  $('fullscreen').addEventListener('click', async () => { try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch (_) { toast('Use your browser fullscreen shortcut to enlarge the dashboard.'); } });
  document.querySelectorAll('[data-manual]').forEach(button => button.addEventListener('click', () => { action('manual/' + button.dataset.manual); $('operator-controls').open = false; }));
  document.addEventListener('keydown', event => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || ['INPUT','TEXTAREA','SELECT','BUTTON','SUMMARY'].includes(event.target.tagName)) return;
    if (event.code === 'Space') { event.preventDefault(); action(!state?.has_started || state.complete ? 'start' : 'pause'); }
    else if (event.key.toLowerCase() === 'r') action('reset');
  });
  poll(); setInterval(poll, 200); requestAnimationFrame(render);
})();
