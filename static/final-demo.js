(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const C = window.StageCore;
  let state = null, fromTrack = null, fromDetection = null, receivedAt = 0;
  let busy = false, pending = false, actionVersion = 0, lastGood = 0, online = false;
  let eventSignature = '', toastTimer, acquisitionTimer;
  const setText = (id, value) => { if ($(id).textContent !== value) $(id).textContent = value; };
  const format = value => Math.round(value).toLocaleString('en-GB');
  const seconds = value => String(Math.floor(value)).padStart(2, '0');
  const humanState = value => ({NON_UAS:'NON-UAS CONTACT',RESTRICTED:'RESTRICTED',ACQUIRED:'ACQUIRED',APPROACHING:'APPROACHING',NORMAL:'NORMAL',WARNING:'WARNING'})[value] || value;

  function connection(value) {
    online = value;
    document.body.classList.toggle('disconnected', !value);
    setText('connection', value ? 'SYSTEM ONLINE' : 'BACKEND UNAVAILABLE');
    if (!value) {
      setText('banner', 'DEMO BACKEND DISCONNECTED');
      setText('banner-label', 'CONNECTION STATUS');
      setText('severity', 'RECONNECTING');
      setText('sequence', 'DISPLAY HELD · RETRYING');
      setText('status-symbol', '!');
    }
  }

  async function request(path, method = 'GET', body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2500);
    try {
      const options = {method, cache:'no-store', signal:controller.signal};
      if (body !== undefined) { options.headers = {'Content-Type':'application/json'}; options.body = JSON.stringify(body); }
      const response = await fetch(path, options);
      if (!response.ok) throw new Error('Backend status ' + response.status);
      const value = await response.json();
      if (!value.run_id || !value.zones || !Array.isArray(value.events)) throw new Error('Invalid demo state');
      return value;
    } finally { clearTimeout(timeout); }
  }

  function showToast(message) {
    setText('toast', message); $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
  }

  function accept(next) {
    const previous = state;
    const sameRun = previous && previous.run_id === next.run_id;
    const samePhase = sameRun && previous.system_state === next.system_state && !next.complete;
    const acquire = next.track && (!sameRun || !previous.track);
    const visual = displayedTrack();
    fromTrack = samePhase ? visual : next.track;
    fromDetection = samePhase ? displayedDetection() : next.detection;
    state = next;
    receivedAt = performance.now();
    lastGood = receivedAt;
    connection(true);
    document.body.dataset.severity = state.severity;
    setText('banner', state.banner);
    setText('banner-label', 'AIRSPACE STATUS');
    setText('severity', {HIGH:'HIGH PRIORITY',WARNING:'WARNING',NORMAL:state.track ? 'CONTACT TRACKED' : state.detection ? 'CLASSIFYING' : 'MONITORING'}[state.severity]);
    setText('sequence', state.complete ? 'SEQUENCE COMPLETE · STATE HELD' : state.has_started ? seconds(state.elapsed_s) + ' / ' + seconds(state.duration_s) + ' s · ' + state.scenario.toUpperCase() : 'READY TO RUN');
    setText('status-symbol', state.severity === 'NORMAL' ? (state.detection ? '•' : '✓') : '!');
    $('progress').style.width = (state.has_started ? state.elapsed_s / state.duration_s * 100 : 0) + '%';
    $('step-sensor').classList.toggle('active', true);
    $('step-class').classList.toggle('active', Boolean(state.detection));
    $('step-track').classList.toggle('active', Boolean(state.track));
    $('step-radar').classList.toggle('active', Boolean(state.track));
    $('step-alert').classList.toggle('active', state.severity !== 'NORMAL');
    document.querySelectorAll('[data-scenario]').forEach(button => button.setAttribute('aria-pressed', String(state.has_started && button.dataset.scenario === state.scenario)));
    setText('sensor-status', state.sensor_state);
    setText('sensor-time', state.sensor_timestamp.slice(11,19) + ' UTC');
    $('sensor-empty').hidden = Boolean(state.detection);
    $('eo-target').toggleAttribute('hidden', !state.detection);
    $('confidence-wrap').hidden = !state.detection;
    $('contact').toggleAttribute('hidden', !state.track);
    $('telemetry').hidden = !state.track;
    $('track-identity').hidden = !state.track;
    $('track-empty').hidden = Boolean(state.track);
    setText('contact-count', state.track ? '01' : '00');
    setText('track-id', state.track ? state.track.id : state.detection ? 'ACQUIRING' : 'NO CONTACT');
    setText('track-state', state.track ? humanState(state.track.state) : state.detection ? 'CLASSIFYING' : 'STANDBY');
    setText('track-empty', state.detection ? 'Visual contact identified. Acquiring a stable track…' : 'A confirmed visual detection becomes an operational track.');
    setText('detection-class', state.detection ? (state.scenario === 'drone' ? 'DRONE' : state.detection.class) : 'AIRSPACE CLEAR');
    setText('detection-note', state.detection ? ({drone:'UNCREWED AIRCRAFT · SYNTHETIC CLASSIFICATION',aircraft:'CLASS: AIRCRAFT · NORMAL TRANSIT',bird:'CLASS: BIRD · STATUS: NON-UAS CONTACT'})[state.scenario] : 'Monitoring the synthetic sensor environment');
    if (state.detection) {
      const confidence = Math.round(state.detection.confidence * 100);
      $('confidence').replaceChildren(document.createTextNode(String(confidence)), Object.assign(document.createElement('small'), {textContent:'%'}));
      $('confidence-fill').style.width = confidence + '%';
      setText('eo-label', state.detection.label + ' ' + confidence + '%');
      setText('eo-track-id', state.track ? state.track.id : 'VISUAL CONTACT');
      ['drone','aircraft','bird'].forEach(name => { $('shape-' + name).toggleAttribute('hidden', state.scenario !== name); });
    }
    if (state.track) {
      setText('radar-track-id', state.track.id);
      setText('track-class', state.track.class);
      setText('track-confidence', Math.round(state.track.confidence * 100) + '%');
      $('trail').setAttribute('points', state.track.history.map(point => { const p=C.project(point.x,point.y,state.zones.maximum_m); return p.x + ',' + p.y; }).join(' '));
    } else { $('trail').setAttribute('points', ''); }
    if (!sameRun || !state.track) { $('radar').classList.remove('acquired'); clearTimeout(acquisitionTimer); }
    if (acquire) {
      $('radar').classList.remove('acquired');
      // Restart a real acquisition pulse even when switching scenarios quickly.
      void $('radar').getBoundingClientRect();
      $('radar').classList.add('acquired');
      acquisitionTimer = setTimeout(() => $('radar').classList.remove('acquired'), 3200);
    }
    const signature = state.events.map(event => event.id).join('|');
    if (signature !== eventSignature) {
      eventSignature = signature;
      const nodes = state.events.slice(-6).map(event => {
        const li=document.createElement('li'), time=document.createElement('time'), category=document.createElement('span'), message=document.createElement('span');
        li.className = event.category;
        time.textContent=event.timestamp.slice(11,19); category.textContent=event.category; category.className='category'; message.textContent=event.message;
        li.append(time,category,message); return li;
      });
      $('event-log').replaceChildren(...nodes);
    }
  }

  function fraction() { return Math.min(1, Math.max(0, (performance.now() - receivedAt) / 200)); }
  function displayedTrack() { return state ? C.interpolate(fromTrack, state.track, fraction()) : null; }
  function displayedDetection() {
    if (!state || !state.detection) return null;
    if (!fromDetection) return state.detection;
    const p=fraction(), next={...state.detection};
    ['sensor_x','sensor_y','sensor_scale'].forEach(key => { next[key]=fromDetection[key]+(state.detection[key]-fromDetection[key])*p; });
    return next;
  }
  function metric(id, value, unit) {
    const element = $(id), content = value + ' ' + unit;
    if (element.dataset.value === content) return;
    element.dataset.value = content;
    element.replaceChildren(document.createTextNode(value), Object.assign(document.createElement('small'), {textContent:unit}));
  }
  function render() {
    if (state) {
      const track=displayedTrack(), detection=displayedDetection();
      if (track) {
        const point=C.project(track.x,track.y,state.zones.maximum_m);
        $('contact').setAttribute('transform', 'translate(' + point.x + ' ' + point.y + ')');
        // Heading is a velocity-derived bearing, not the contact's azimuth.
        $('contact-heading').toggleAttribute('hidden', track.heading_deg == null);
        $('contact-held').toggleAttribute('hidden', track.heading_deg != null);
        if (track.heading_deg != null) $('contact-heading').setAttribute('transform','rotate('+track.heading_deg+')');
        metric('range',format(track.range_m),'m');
        metric('bearing',String(Math.round(track.bearing_deg ?? 0) % 360).padStart(3,'0'),'°');
        metric('altitude',format(track.altitude_m),'m');
        metric('speed',track.speed_mps.toFixed(1),'m/s');
      }
      if (detection) {
        $('eo-target').setAttribute('transform','translate('+(detection.sensor_x*800)+' '+(detection.sensor_y*420)+') scale('+detection.sensor_scale+')');
        if (state.scenario === 'bird') {
          const wing = Math.sin(state.elapsed_s * 7) * 16;
          $('bird-wings').setAttribute('d','M-40 '+(-13+wing)+'Q-17-10 0 5Q17-10 40 '+(-13+wing)+'Q21 3 5 10L0 17-5 10Q-21 3-40 '+(-13+wing)+'Z');
        }
      }
    }
    if (online && performance.now() - lastGood > 3000) connection(false);
    requestAnimationFrame(render);
  }

  async function poll() {
    if (pending || busy) return;
    pending = true;
    const version = actionVersion;
    try { const next = await request('/api/demo/state'); if (version === actionVersion) accept(next); }
    catch (_) { if (version === actionVersion) connection(false); }
    finally { pending = false; }
  }
  async function action(kind, scenario) {
    if (busy) return;
    busy = true; actionVersion++;
    document.querySelectorAll('.controls button:not(#fullscreen)').forEach(button => {button.disabled=true;});
    try { accept(await request('/api/demo/'+kind,'POST',scenario ? {scenario} : undefined)); }
    catch (_) { connection(false); showToast('Could not reach the demo backend. Check the local server and try again.'); }
    finally { busy=false; document.querySelectorAll('.controls button').forEach(button => {button.disabled=false;}); }
  }
  document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click',()=>action('start',button.dataset.scenario)));
  $('reset').addEventListener('click',()=>action('reset'));
  $('fullscreen').addEventListener('click',async()=>{
    try { if(document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
    catch (_) { showToast('Use your browser’s fullscreen shortcut to fill the screen.'); }
  });
  document.addEventListener('fullscreenchange',()=>{$('fullscreen').setAttribute('aria-pressed',String(Boolean(document.fullscreenElement)));});
  poll(); setInterval(poll,200); requestAnimationFrame(render);
})();
