(() => {
  'use strict';
  const core=DroneWatch,$=id=>document.getElementById(id),store=new core.EventStore();
  const put=(id,text)=>{$(id).textContent=text==null||text===''?'\u2014':String(text);};
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
  const svg=(tag,attributes)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attributes))node.setAttribute(k,v);return node;};
  let mode='VISO_LIVE',state=null,lastStateStamp=0,mediaKey='',backendOnline=false,streamOnline=false;
  const seconds=value=>Number.isFinite(value)?`${Math.floor(value/60).toString().padStart(2,'0')}:${(value%60).toFixed(1).padStart(4,'0')}`:'\u2014';
  const utc=value=>{const date=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(date.getTime())?date.toLocaleTimeString('en-GB',{timeZone:'UTC',hour12:false}):'\u2014';};
  const timestamp=value=>mode==='BENCHMARK_REPLAY'?`T+${seconds(value)}`:utc(value);
  const severity=event=>event.state==='RESTRICTED_ZONE'||event.severity==='HIGH'?'warning':event.state==='APPROACHING'||event.severity==='WARNING'?'watch':'information';
  const eventLabel=event=>({DETECTED:'OBSERVED',APPROACHING:'WATCH',RESTRICTED_ZONE:'ZONE ENTRY',EXITED:'TRACK LOST',UNKNOWN:'RECEIVED'})[event.state]||'RECEIVED';
  function flash(node){node.classList.remove('new-event');void node.getBoundingClientRect();node.classList.add('new-event');}
  function health(){
    put('health-backend-text',backendOnline?'BACKEND ONLINE':'BACKEND CONNECTION LOST');$('health-backend').dataset.online=String(backendOnline);
    put('health-stream-text',streamOnline?'EVENT STREAM ONLINE':'POLLING FALLBACK / RECONNECTING');$('health-stream').dataset.online=String(streamOnline);
    put('health-source-text',`SOURCE ${state?.source?.status||'WAITING'}`);$('health-source').dataset.online=String(!!state?.source?.online);
    put('last-update',`LAST EVENT ${timestamp(state?.source?.last_event)}${mode==='BENCHMARK_REPLAY'?'':' UTC'}`);
    if(!backendOnline)put('state-detail','BACKEND CONNECTION LOST. Retaining the last observation and reconnecting automatically.');
  }
  function renderState(changed=false){
    const latest=store.latest(),tracks=state?.tracks||[],warnings=state?.alerts?.filter(a=>a.severity==='warning')||[];
    put('backend-event-id',latest?`SENSOR EVENT #${latest.id}`:'NO SENSOR EVENTS');put('stored-count',`${store.total} STORED OBSERVATIONS`);
    put('active-tracks',state?.metrics?.active_tracks??0);put('confirmed-sightings',state?.metrics?.confirmed_sightings??0);put('open-warnings',state?.metrics?.open_warnings??0);
    put('spatial-note',mode==='VISO_LIVE'&&!state?.spatial_available?'Sighting-level input / no measured boxes':'Persistent spatial tracks');
    if(mode==='LOCAL_INFERENCE'&&Number.isFinite(state?.processing_fps)){put('performance-value',state.processing_fps.toFixed(1));put('performance-label','PROCESSING FPS');put('performance-note','Measured detector throughput');}
    else {put('performance-label',mode==='BENCHMARK_REPLAY'?'REPLAY TIME':'EVENT AGE');put('performance-value',mode==='BENCHMARK_REPLAY'?seconds(state?.replay?.time):latest?`${Math.max(0,Math.floor((Date.now()-Date.parse(latest.received_at))/1000))}s`:'\u2014');put('performance-note',mode==='BENCHMARK_REPLAY'?'Recorded annotation timeline':'Since latest backend observation');}
    let title='WAITING FOR OBSERVATIONS',level='information';
    if(warnings.length){title='ZONE ENTRY';level='warning';}
    else if(tracks.some(t=>t.state==='lost')){title='TRACK LOST';level='watch';}
    else if(tracks.some(t=>t.state==='confirmed'))title='OBSERVED';
    else if(tracks.length){title='WATCH';level='watch';}
    else if(mode==='VISO_LIVE'&&latest){title=eventLabel(latest);level=severity(latest);}
    else if(mode==='BENCHMARK_REPLAY')title=state?.replay?.playing?'NO CURRENT DETECTION':'REPLAY READY';
    else if(mode==='LOCAL_INFERENCE')title=state?.source?.status==='ONLINE'?'NO CURRENT DETECTION':'LOCAL INFERENCE OPTIONAL';
    put('system-state',title);$('state-bar').dataset.severity=level;
    put('state-detail',mode==='VISO_LIVE'?(latest?`${core.kind(latest)} / ${utc(latest.received_at)} UTC / ${state?.spatial_available?'Measured coordinates available':'Sighting only; no spatial position inferred'}`:'Waiting for Viso webhook events.'):
      mode==='BENCHMARK_REPLAY'?'Recorded annotations drive this view. This is not live model inference.':state?.source?.error||state?.availability?.reason||'Model observations are associated across sequential frames.');
    put('source-description',mode==='VISO_LIVE'?'VISO LIVE / GENUINE ACTIVITY REPORTED SEPARATELY':mode==='BENCHMARK_REPLAY'?'RECORDED BENCHMARK REPLAY':'LOCAL INFERENCE / OPTIONAL MODEL');
    if(changed){flash($('backend-event-id'));flash($('state-bar'));}
    health();renderTracks();renderVideo();renderLog(changed);
  }
  function addField(list,name,value){const cell=el('div');cell.append(el('dt',name),el('dd',value==null?'\u2014':String(value)));list.append(cell);}
  function renderTracks(){
    const list=$('track-list');list.replaceChildren();const tracks=state?.tracks||[];
    for(const track of tracks){
      const card=el('article',null,`track-card ${track.zone_state==='inside'?'warning':''}`),heading=el('h3',track.track_id);heading.append(el('small',track.state.toUpperCase()));
      const fields=el('dl',null,'fields');addField(fields,'CAMERA',track.camera_id);addField(fields,'OBSERVATIONS',track.observations);addField(fields,'FIRST SEEN',timestamp(track.first_seen));addField(fields,'LAST SEEN',timestamp(track.last_seen));addField(fields,'DURATION',`${track.duration.toFixed(1)}s`);addField(fields,'CONFIDENCE',core.confidence(track.smoothed_confidence));addField(fields,'ZONE',track.zone_state);addField(fields,'SOURCE',track.source);
      card.append(heading,fields);list.append(card);
    }
    if(!tracks.length){
      const latest=store.latest(),detection=state?.sightings?.[0];
      list.append(el('h3',mode==='VISO_LIVE'?'SIGHTING-LEVEL OBSERVATIONS':'NO ACTIVE TRACKS','sighting-header'));
      list.append(el('p',mode==='VISO_LIVE'?'This source has not supplied usable bounding boxes. Observations remain in the event history; positions and trajectories are not invented.':'Tracks appear after measured or annotated boxes arrive. Three observations in five eligible frames confirm a sighting.','sighting-note'));
      if(mode==='VISO_LIVE'&&latest){const fields=el('dl',null,'fields');addField(fields,'LATEST EVENT',`#${latest.id}`);addField(fields,'SOURCE',core.kind(latest));addField(fields,'CLASS',detection?.class_name||latest.detection_type);addField(fields,'CONFIDENCE',core.confidence(detection?.confidence??latest.confidence,detection?.confidence_label));addField(fields,'LAST RECEIVED',utc(latest.received_at));addField(fields,'REPORTED ZONE',detection?.zone_state);list.append(fields);}
    }
  }
  function renderVideo(){
    const replay=state?.replay,latest=store.latest();
    $('watermark').hidden=mode!=='BENCHMARK_REPLAY';$('replay-controls').hidden=mode!=='BENCHMARK_REPLAY';$('local-controls').hidden=mode!=='LOCAL_INFERENCE';
    put('panel-source',mode.replaceAll('_',' '));put('video-time',mode==='BENCHMARK_REPLAY'?`${seconds(replay?.time)} / ${seconds(replay?.duration)}`:mode==='LOCAL_INFERENCE'?'MODEL OUTPUT':'SENSOR EVIDENCE');
    if(replay){put('replay-toggle',replay.playing?'PAUSE':'PLAY');$('loop').checked=replay.loop;}
    const mediaURL=mode==='BENCHMARK_REPLAY'?(replay?.video_available?'/api/replay/video':null):mode==='LOCAL_INFERENCE'?(state?.source?.status==='ONLINE'?'/api/local/frame':null):core.safeURL(latest?.media_url)||core.safeURL(latest?.raw_payload?.mediaLink);
    const key=`${mode}|${mediaURL||''}`;
    if(mediaKey!==key){
      mediaKey=key;const old=$('media');old.replaceChildren();
      if(mediaURL){
        const isVideo=mode==='BENCHMARK_REPLAY'||/\.(mp4|webm|mov)(\?|$)/i.test(mediaURL)||latest?.raw_payload?.fileType==='mp4';
        const media=el(isVideo?'video':'img');media.id='source-media';media.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain';
        if(isVideo){media.muted=true;media.playsInline=true;media.controls=mode==='VISO_LIVE';media.preload='metadata';}else media.alt=mode==='LOCAL_INFERENCE'?'Current local inference frame':'Supplied sensor evidence';
        media.addEventListener('error',()=>{old.replaceChildren(el('p','MEDIA UNAVAILABLE / CHECK SOURCE','empty-media media-error'));});media.src=mediaURL;old.append(media);
      }
    }
    const sourceMedia=$('source-media');
    if(mode==='BENCHMARK_REPLAY'&&sourceMedia?.tagName==='VIDEO'&&replay){if(Number.isFinite(sourceMedia.duration)&&Math.abs(sourceMedia.currentTime-replay.time)>.6)sourceMedia.currentTime=replay.time;if(replay.playing)sourceMedia.play().catch(()=>{});else sourceMedia.pause();}
    const synthetic=mode==='BENCHMARK_REPLAY'&&!mediaURL&&!!replay;
    $('synthetic-label').hidden=!synthetic;$('empty-media').hidden=!!mediaURL||synthetic;
    put('empty-title',mode==='LOCAL_INFERENCE'?'OPTIONAL MODEL NOT RUNNING':'NO SENSOR MEDIA PROVIDED');
    put('empty-description',mode==='LOCAL_INFERENCE'?state?.availability?.reason||state?.source?.error||'Start a configured model source to receive frames.':'No playable media URL was supplied in the webhook. Event observations remain available.');
    put('annotation-note',mode==='BENCHMARK_REPLAY'?(replay?.synthetic?'SYNTHETIC ANNOTATION FIXTURE / NOT VIDEO OR MODEL INFERENCE':'GROUND-TRUTH ANNOTATIONS / NOT MODEL INFERENCE'):state?.spatial_available?'MEASURED IMAGE COORDINATES / NO GEOGRAPHIC RANGE':'SIGHTING ONLY / NO SPATIAL COORDINATES');
    const overlay=$('overlay');overlay.replaceChildren();
    const width=replay?.width||1280,height=replay?.height||720;overlay.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const zone=replay?.zone||state?.zone;
    if(zone&&state?.spatial_available){overlay.append(svg('polygon',{points:zone.map(p=>`${p[0]*width},${p[1]*height}`).join(' '),fill:'#e5bb7910',stroke:'#c4b48f','stroke-width':1,'stroke-dasharray':'6 5'}));const label=svg('text',{x:zone[0][0]*width,y:zone[0][1]*height-8,fill:'#b7b7a7','font-size':14,'font-family':'monospace'});label.textContent='CONFIGURED IMAGE-SPACE ZONE';overlay.append(label);}
    for(const track of state?.tracks||[]){
      if(!track.bbox)continue;const color=track.zone_state==='inside'?'#f08b84':track.state==='tentative'||track.state==='lost'?'#e5bb79':'#91bbd4';const [x1,y1,x2,y2]=track.bbox;
      const history=track.centroid_history||[];if(history.length>1)overlay.append(svg('polyline',{points:history.map(p=>`${p.x*width},${p.y*height}`).join(' '),fill:'none',stroke:color,'stroke-width':1.5,'stroke-opacity':.7}));
      overlay.append(svg('rect',{x:x1*width,y:y1*height,width:(x2-x1)*width,height:(y2-y1)*height,fill:'none',stroke:color,'stroke-width':2,'stroke-dasharray':track.state==='lost'?'5 4':'none'}));
      const text=svg('text',{x:x1*width,y:Math.max(25,y1*height-10),fill:color,'font-size':17,'font-family':'monospace'});text.textContent=`${track.track_id} / ${track.state.toUpperCase()}${track.smoothed_confidence!=null?' / '+core.confidence(track.smoothed_confidence):''}`;overlay.append(text);
    }
  }
  function renderLog(changed=false){
    const target=$('timeline'),scroll=target.scrollTop,open=new Set([...target.querySelectorAll('details[open]')].map(n=>n.dataset.key));
    const sourceFilter=$('filter-source').value,severityFilter=$('filter-severity').value;
    let rows=(state?.lifecycle||[]).map(item=>({...item,key:`life:${mode}:${item.id}`,description:item.explanation,time:timestamp(item.timestamp)}));
    if(mode==='VISO_LIVE')rows=[...rows,...store.events().map(event=>({key:`event:${event.id}`,event_id:event.id,source:core.kind(event),label:eventLabel(event),severity:severity(event),time:utc(event.received_at),timestamp:Date.parse(event.received_at)/1000,description:event.detection_type||'Unclassified webhook observation',raw:event.raw_payload}))];
    rows=rows.filter(row=>(sourceFilter==='ALL'||row.source===sourceFilter)&&(severityFilter==='ALL'||row.severity===severityFilter)).sort((a,b)=>b.timestamp-a.timestamp);
    const fragment=document.createDocumentFragment();
    for(const row of rows){const details=el('details',null,'log-row');details.dataset.key=row.key;details.dataset.severity=row.severity;details.open=open.has(row.key);if(changed&&row.event_id===store.latest()?.id)details.classList.add('new-event');const summary=el('summary');summary.append(el('time',row.time),el('span',row.source,'source'),el('span',row.label,'label'),el('span',row.description,'description'),el('span',row.event_id?`#${row.event_id}`:row.track_id,'event-id'),el('span','+'));const raw=el('div',null,'raw');raw.append(el('p',row.raw?'RAW SOURCE PAYLOAD / preserved without alteration':'TRACK LIFECYCLE EVENT'),el('pre',JSON.stringify(row.raw??row,null,2)));details.append(summary,raw);fragment.append(details);}
    if(!rows.length)fragment.append(el('p','No events match this source and severity.','empty-log'));
    target.replaceChildren(fragment);target.scrollTop=scroll;
  }
  async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),signal:AbortSignal.timeout(10000)});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Request failed');return data;}
  function acceptState(incoming){if(incoming.generated_at&&incoming.generated_at<lastStateStamp)return;lastStateStamp=incoming.generated_at||0;state=incoming;renderState();}
  const transport=core.transport({store,getMode:()=>mode,onEvents:changed=>renderState(changed),onConsole:acceptState,onConnection:(which,online)=>{if(which==='stream')streamOnline=online;else backendOnline=online;health();}});
  $('source-mode').addEventListener('change',async event=>{mode=event.target.value;state=null;lastStateStamp=0;mediaKey='';renderState();transport.changeMode();if(mode==='BENCHMARK_REPLAY'){try{acceptState(await post('/api/replay/control',{action:'play'}));}catch(error){put('operator-message',error.message);}}});
  $('reset-demo').addEventListener('click',async()=>{try{const result=await post('/api/demo/reset',{mode});acceptState(result.console);put('operator-message','Transient tracks, alerts and counters reset. Permanent events preserved.');}catch(error){put('operator-message',error.message);}});
  $('replay-toggle').addEventListener('click',async()=>{try{acceptState(await post('/api/replay/control',{action:state?.replay?.playing?'pause':'play',loop:$('loop').checked}));}catch(error){put('operator-message',error.message);}});
  $('replay-restart').addEventListener('click',async()=>{try{acceptState(await post('/api/replay/control',{action:'restart',loop:$('loop').checked}));}catch(error){put('operator-message',error.message);}});
  $('loop').addEventListener('change',async()=>{try{acceptState(await post('/api/replay/control',{action:state?.replay?.playing?'play':'pause',loop:$('loop').checked}));}catch(error){put('operator-message',error.message);}});
  $('local-start').addEventListener('click',async()=>{try{acceptState(await post('/api/local/start'));}catch(error){put('operator-message',error.message);}});$('local-stop').addEventListener('click',async()=>{try{acceptState(await post('/api/local/stop'));}catch(error){put('operator-message',error.message);}});
  for(const id of ['filter-source','filter-severity'])$(id).addEventListener('change',()=>renderLog());
  document.querySelectorAll('[data-scenario]').forEach(button=>button.addEventListener('click',async()=>{try{await post('/dev/simulate',{scenario:button.dataset.scenario});await transport.poll();put('operator-message','Stored as SIMULATED. Genuine Viso counters are unchanged.');}catch(error){put('operator-message',error.message);}}));
  fetch('/api/config',{cache:'no-store'}).then(r=>r.json()).then(config=>{$('dev-controls').hidden=!config.simulation_enabled;}).catch(()=>{});
  setInterval(()=>{put('clock-utc',`${utc(Date.now()/1000)} UTC`);put('clock-local',new Date().toLocaleTimeString([], {hour12:false})+' LOCAL');if(state)health();},1000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)transport.poll();});
  renderState();
})();
