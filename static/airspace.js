(() => {
  'use strict';
  const core=DroneWatch,world=Airspace,$=id=>document.getElementById(id),store=new core.EventStore(),frames=new world.Frames();
  const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const svg=(tag,attrs)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs||{}))n.setAttribute(k,String(v));return n;};
  const put=(id,value)=>{const text=value==null?'--':String(value);if($(id).textContent!==text)$(id).textContent=text;};
  const number=(value,digits=0)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('en-GB',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'--';
  const time=value=>value?new Date(value).toLocaleTimeString('en-GB',{hour12:false,timeZone:'UTC'}):'--';
  const elapsed=value=>Math.floor((value||0)/60).toString().padStart(2,'0')+':'+Math.floor((value||0)%60).toString().padStart(2,'0');
  let source='SYNTHETIC',snapshot=null,selected=null,automatic=true,tracksOnline=null,eventsOnline=null,streamOnline=false,viso=null;
  let busy=false,controlBusy=false,lastConfig='',lastLogKey='',lastTabsKey='',lastContactKey='',lastTelemetry=0,lastClock=0,toastTimer;
  const markers=new Map(),trails=new Map(),fields=new Map();
  function message(text){put('air-message',text);$('air-message').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('air-message').hidden=true;},6000);}
  function pulse(node){node.classList.remove('pulse');void node.getBoundingClientRect();node.classList.add('pulse');}
  function health(){
    const lost=tracksOnline===false,ready=tracksOnline===true;
    document.querySelector('.airspace-app').classList.toggle('disconnected',lost);
    put('air-backend',lost?'BACKEND CONNECTION LOST':ready?'BACKEND ONLINE':'BACKEND CONNECTING');
    $('air-backend').className=ready?'online':lost?'degraded':'';
    put('air-transport',streamOnline?'EVENT STREAM ONLINE':'2 S LOG POLLING / RECONNECTING');
    $('air-transport').className=streamOnline?'online':'degraded';
    put('air-viso','VISO '+(viso?.source?.online?'ONLINE':'STALE')+(viso?.source?.last_event?' / '+time(viso.source.last_event*1000)+' UTC':' / NO GENUINE EVENT'));
    $('air-viso').className=viso?.source?.online?'online':'';
    put('air-log-health',snapshot?.event_log_error?'MILESTONE LOG DEGRADED':eventsOnline===false?'EVENT HISTORY DISCONNECTED':'SQLITE / MILESTONES ONLY');
    $('air-log-health').className=snapshot?.event_log_error||eventsOnline===false?'degraded':'';
    if(lost){put('air-state','CONNECTION LOST');put('air-state-note','Retaining last known tracks; reconnecting automatically.');}
  }
  function drawGrid(config){
    const key=JSON.stringify(config);if(key===lastConfig)return;lastConfig=key;
    const grid=$('air-grid'),zones=$('air-zones');grid.replaceChildren();zones.replaceChildren();
    const maximum=config.max_range_m,step=maximum<=3000?500:maximum/5;
    for(let range=step;range<=maximum+0.01;range+=step){
      const radius=range/maximum*430;
      grid.append(svg('circle',{cx:500,cy:500,r:radius,fill:'none',stroke:'#39545f','stroke-width':range===maximum?2:1.2,opacity:range===maximum?.9:.55}));
      const label=svg('text',{x:508,y:500-radius+23,class:'radar-ring-label'});label.textContent=number(range)+' m';grid.append(label);
    }
    for(let bearing=0;bearing<360;bearing+=30){
      const p=world.project(maximum,bearing,maximum),end=world.project(maximum*1.025,bearing,maximum);
      grid.append(svg('line',{x1:500,y1:500,x2:p.x,y2:p.y,stroke:'#38505b','stroke-width':1,'stroke-dasharray':'4 9',opacity:.42}));
      grid.append(svg('line',{x1:p.x,y1:p.y,x2:end.x,y2:end.y,stroke:'#7a949e','stroke-width':2}));
    }
    for(const [range,name,color]of [[config.warning_radius_m,'WARNING','#d9b776'],[config.restricted_radius_m,'RESTRICTED','#ce827b']]){
      const radius=range/maximum*430;
      zones.append(svg('circle',{cx:500,cy:500,r:radius,fill:color,'fill-opacity':.045,stroke:color,'stroke-opacity':.56,'stroke-width':1.7,'stroke-dasharray':name==='WARNING'?'8 8':'none'}));
      const label=svg('text',{x:500,y:500+radius+21,'text-anchor':'middle',class:'radar-zone-label'});label.textContent=name+' / '+number(range)+' M';zones.append(label);
    }
    put('air-range-scale','MAX RANGE '+number(maximum)+' M');
  }
  function choose(identity){selected=identity;automatic=false;renderSummary();renderContact(frames.values(performance.now()));}
  function renderContacts(){
    const positioned=(snapshot?.tracks||[]).filter(t=>t.position),alive=new Set(positioned.map(t=>t.track_id));
    for(const[id,node]of markers)if(!alive.has(id)){node.remove();markers.delete(id);trails.get(id)?.remove();trails.delete(id);}
    for(const track of positioned){
      let group=markers.get(track.track_id);
      if(!group){
        group=svg('g',{class:'radar-contact',tabindex:0,role:'button','aria-label':'Select contact '+track.track_id});
        group.append(svg('circle',{class:'hit',r:38}),svg('circle',{class:'acquisition',r:35}),svg('circle',{class:'selection',r:26}));
        group.append(svg('path',{class:'marker',d:'M0 -20 L9 13 L0 7 L-9 13 Z'}));
        const label=svg('text',{class:'contact-label',x:25,y:-17});label.textContent=track.track_id;group.append(label);
        group.append(svg('text',{class:'contact-alt',x:25,y:8}));
        group.addEventListener('click',()=>choose(track.track_id));
        group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(track.track_id);}});
        $('air-markers').append(group);markers.set(track.track_id,group);
        const trail=svg('polyline',{class:'radar-trail'});$('air-trails').append(trail);trails.set(track.track_id,trail);
        pulse(group);
      }
      if(group.dataset.state&&group.dataset.state!==track.state)pulse(group);
      group.dataset.severity=track.severity;group.dataset.state=track.state;
      const points=track.history.map(p=>world.point(p,snapshot.config.max_range_m)).filter(Boolean).map(p=>p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ');
      const trail=trails.get(track.track_id);trail.setAttribute('points',points);
      trail.setAttribute('stroke',track.severity==='HIGH'?'#f08b84':track.severity==='WARNING'?'#e5bb79':'#8bc9a8');
    }
  }
  function renderSummary(){
    if(!snapshot)return;
    const synthetic=source==='SYNTHETIC',sim=snapshot.simulation,metrics=snapshot.metrics,threat=metrics.max_severity;
    const priority=snapshot.primary_track_id,ids=new Set(snapshot.tracks.map(t=>t.track_id));
    if(automatic||!ids.has(selected))selected=priority||(synthetic?null:snapshot.tracks[0]?.track_id)||null;
    $('air-banner').dataset.severity=threat;
    put('air-provenance',synthetic?'DEMO / SYNTHETIC AIRSPACE':'VISO / REAL VISUAL OBSERVATIONS');
    put('air-position-source',synthetic?'POSITION: SYNTHETIC GROUND TRUTH':'POSITION: NOT PROVIDED BY SENSOR');
    put('air-state',synthetic?(threat==='HIGH'?'HIGH / RESTRICTED':threat==='WARNING'?'WARNING':'NORMAL'):'SIGHTING ONLY');
    const lead=snapshot.tracks.find(t=>t.track_id===priority);
    put('air-state-note',lead?lead.track_id+' / '+lead.state.replaceAll('_',' '):synthetic?(sim.status==='COMPLETE'?'Scenario complete. Select a scenario to run again.':'No current synthetic contact.'):'No range, bearing or world coordinates have been inferred.');
    put('air-active',metrics.active_tracks);put('air-primary',priority||'NONE');
    put('air-nearest',number(metrics.nearest_range_m)+(metrics.nearest_range_m==null?'':' m'));
    put('air-threat',threat);put('air-sensor',synthetic?'SYNTHETIC / '+sim.status:'VISO / '+(snapshot.source_online?'ONLINE':'STALE'));
    put('air-scenario',sim.label);put('air-elapsed',elapsed(sim.elapsed_s));put('air-duration','/ '+elapsed(sim.duration_s));
    put('air-world-status',synthetic?'SYNTHETIC WORLD / '+sim.status:'VISUAL-ONLY SOURCE / NO POSITION');
    put('air-frame-label',synthetic?'LOCAL ENU / METRES':'WORLD POSITION UNAVAILABLE');
    put('air-selection-mode',automatic?'AUTO / HIGHEST PRIORITY':'MANUAL SELECTION');
    put('air-follow','FOLLOW PRIORITY: '+(automatic?'ON':'OFF'));$('air-follow').setAttribute('aria-pressed',String(automatic));
    $('air-zones').style.opacity=synthetic?'1':'0';$('air-sweep').hidden=!synthetic;
    $('air-sweep').style.animationPlayState=synthetic&&sim.active?'running':'paused';
    $('air-empty').hidden=synthetic&&snapshot.tracks.some(t=>t.position);
    if(!$('air-empty').hidden){
      const title=synthetic?(sim.status==='COMPLETE'?'SCENARIO COMPLETE':'AIRSPACE CLEAR'):'NO WORLD POSITION DATA';
      $('air-empty').replaceChildren(make('strong',title),make('span',synthetic?'Select a scenario. Positions are synthetic ground truth, not radar measurements.':'Viso sightings remain in the contact panel and event history. Nothing is plotted without positional evidence.'));
    }
    for(const button of document.querySelectorAll('[data-scenario]')){
      button.classList.toggle('running',synthetic&&sim.active&&button.dataset.scenario===sim.scenario);
      button.disabled=controlBusy||!snapshot.controls_enabled;
    }
    $('air-stop').disabled=controlBusy||!sim.active||!snapshot.controls_enabled;
    $('air-reset').disabled=controlBusy||!snapshot.controls_enabled;
    const tabsKey=JSON.stringify([selected,snapshot.tracks.map(t=>[t.track_id,t.severity])]);
    if(tabsKey!==lastTabsKey){
      lastTabsKey=tabsKey;const list=$('air-contact-list');list.replaceChildren();
      for(const track of snapshot.tracks){
        const button=make('button',track.track_id,(track.track_id===selected?'selected ':'')+(track.severity==='HIGH'?'high':''));
        button.setAttribute('aria-label','Select contact '+track.track_id);button.addEventListener('click',()=>choose(track.track_id));list.append(button);
      }
    }
    health();
  }
  function renderContact(tracks){
    const track=tracks.find(t=>t.track_id===selected),key=source+'|'+(track?.track_id||'')+'|'+(track?.state||'');
    if(key!==lastContactKey){
      lastContactKey=key;fields.clear();const root=$('air-contact');root.replaceChildren();
      if(!track){const empty=make('div',null,'contact-empty');empty.append(make('strong','NO CURRENT CONTACT'),make('p','Start a scenario to acquire synthetic tracks. The existing Viso webhook remains available independently.'));root.append(empty);return;}
      const title=make('div',null,'contact-title');title.append(make('strong',track.track_id),make('span',track.state.replaceAll('_',' ')));root.append(title);
      const provenance=make('div',null,'contact-source');provenance.append(make('div','DETECTION SOURCE: '+track.source),make('b','POSITION: '+track.position_source));root.append(provenance);
      const dl=make('dl',null,'telemetry');
      for(const[label,name,unit]of [['X / EAST','x_m','m'],['Y / NORTH','y_m','m'],['Z / UP','z_m','m'],['GROUND RANGE','range_m','m'],['BEARING','bearing_deg','deg'],['GROUND SPEED','ground_speed_mps','m/s'],['HEADING','heading_deg','deg'],['VX / EAST','vx_mps','m/s'],['VY / NORTH','vy_mps','m/s'],['VZ / UP','vz_mps','m/s'],['CONFIDENCE','confidence',''],['OBSERVATIONS','observation_count','']]){
        const cell=make('div'),dd=make('dd'),value=make('span','--');dd.append(value,make('small',unit?' '+unit:''));cell.append(make('dt',label),dd);dl.append(cell);fields.set(name,value);
      }
      const times=make('div',null,'wide'),first=make('span',''),last=make('span','');times.append(first,last);dl.append(times);fields.set('first_seen',first);fields.set('last_seen',last);root.append(dl);
    }
    if(!track)return;
    const values={...track,...track.position,...track.velocity};
    for(const[name,node]of fields){
      let value=values[name];
      if(name==='first_seen'||name==='last_seen')value=(name==='first_seen'?'FIRST ':'LAST ')+time(value)+' UTC';
      else if(name==='confidence')value=value==null?'--':Math.round(value*100)+'%'+(track.synthetic?' SYN':'');
      else value=number(value,['bearing_deg','heading_deg','ground_speed_mps','vx_mps','vy_mps','vz_mps'].includes(name)?1:0);
      if(node.textContent!==value)node.textContent=value;
    }
  }
  function renderLog(force=false){
    const scope=$('air-log-scope').value,events=store.events().filter(event=>{
      if(scope==='ALL')return true;
      if(source==='VISO')return core.kind(event)==='VISO';
      return event.raw_payload?.run_id===snapshot?.run_id&&world.eventSource(event)==='SYNTHETIC';
    });
    const key=source+'|'+scope+'|'+snapshot?.run_id+'|'+events.map(e=>e.id).join(',');
    put('air-stored',store.total+' STORED OBSERVATIONS');put('air-event-id',store.latest()?'SENSOR EVENT #'+store.latest().id:'NO EVENTS');
    if(!force&&key===lastLogKey)return;lastLogKey=key;
    const list=$('air-log'),open=new Set([...list.querySelectorAll('details[open]')].map(n=>n.dataset.id)),scroll=list.scrollTop;list.replaceChildren();
    for(const event of events){
      const raw=event.raw_payload||{},synthetic=world.eventSource(event)==='SYNTHETIC',details=make('details'),summary=make('summary');
      details.dataset.id=String(event.id);details.dataset.severity=event.severity;details.open=open.has(String(event.id));
      const label=synthetic?(raw.track_id?raw.track_id+' ':'')+(raw.event_type||event.state).replaceAll('_',' '):(event.detection_type||'OBSERVATION')+' / '+event.state;
      summary.append(make('time',time(raw.occurred_at||event.received_at)),make('span',label,'log-title'));
      if(raw.explanation)summary.append(make('span',raw.explanation,'log-explanation'));
      summary.append(make('span',(synthetic?'SYNTHETIC GROUND TRUTH':core.kind(event))+' / EVENT #'+event.id,'log-provenance'));
      details.append(summary,make('pre',JSON.stringify(raw,null,2)));list.append(details);
    }
    if(!events.length)list.append(make('p',source==='SYNTHETIC'?'Scenario milestones appear here. Reset clears the current view, not permanent history.':'No genuine Viso observations in the current history window.','air-log-empty'));
    list.scrollTop=scroll;
  }
  function accept(data,expectedSource=source){
    if(expectedSource!==source||data.source!==source)return;
    if(snapshot?.source===source&&data.generated_at<snapshot.generated_at)return;
    const changedRun=snapshot?.run_id!==data.run_id;
    snapshot=data;
    if(changedRun){frames.clear();markers.forEach(n=>n.remove());trails.forEach(n=>n.remove());markers.clear();trails.clear();automatic=true;selected=null;}
    frames.accept(data,performance.now());drawGrid(data.config);renderSummary();renderContacts();renderLog();renderContact(frames.values(performance.now()));
  }
  async function pollTracks(){
    if(busy)return;busy=true;const requested=source;
    try{
      const response=await fetch('/api/tracks?source='+requested+'&t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(3000)});
      if(!response.ok)throw new Error('Track feed unavailable');
      const data=await response.json();if(!Array.isArray(data.tracks))throw new Error('Invalid track response');
      tracksOnline=true;accept(data,requested);
    }catch{tracksOnline=false;health();}finally{busy=false;}
  }
  async function control(action,scenario){
    if(controlBusy)return;controlBusy=true;renderSummary();
    try{
      if(source!=='SYNTHETIC'){source='SYNTHETIC';$('air-source').value=source;frames.clear();snapshot=null;}
      const response=await fetch('/dev/scenario/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(scenario?{scenario}:{}),signal:AbortSignal.timeout(8000)});
      const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Scenario control failed.');
      tracksOnline=true;accept(data);await logTransport.poll();
      if(action==='reset')message('Synthetic tracks cleared. All permanent observations are preserved.');
      else if(action==='stop')message('Simulation stopped. Displayed positions are frozen synthetic state.');
    }catch(error){message(error.message);}finally{controlBusy=false;renderSummary();}
  }
  const logTransport=core.transport({store,getMode:()=> 'VISO_LIVE',onEvents:changed=>{renderLog();if(changed){const node=$('air-event-id');node.classList.remove('new-event');void node.getBoundingClientRect();node.classList.add('new-event');}},onConsole:data=>{viso=data;health();},onConnection:(component,online)=>{if(component==='stream')streamOnline=online;else eventsOnline=online;health();}});
  document.querySelectorAll('[data-scenario]').forEach(button=>button.addEventListener('click',()=>control('start',button.dataset.scenario)));
  $('air-stop').addEventListener('click',()=>control('stop'));$('air-reset').addEventListener('click',()=>control('reset'));
  $('air-follow').addEventListener('click',()=>{automatic=true;renderSummary();renderContact(frames.values(performance.now()));});
  $('air-source').addEventListener('change',()=>{source=$('air-source').value;snapshot=null;frames.clear();selected=null;lastContactKey='';pollTracks();});
  $('air-log-scope').addEventListener('change',()=>renderLog(true));
  function animate(now){
    const tracks=frames.values(now),maximum=snapshot?.config?.max_range_m||2500;
    for(const track of tracks){
      if(!track.position)continue;const group=markers.get(track.track_id),p=world.point(track.position,maximum);if(!group||!p)continue;
      group.setAttribute('transform','translate('+p.x.toFixed(3)+' '+p.y.toFixed(3)+')');
      group.querySelector('.marker').setAttribute('transform','rotate('+(track.heading_deg||0)+')');
      group.querySelector('.contact-alt').textContent=number(track.altitude_m)+' m UP';
      group.classList.toggle('selected',track.track_id===selected);
    }
    if(now-lastTelemetry>100){renderContact(tracks);lastTelemetry=now;}
    if(now-lastClock>1000){put('air-clock',time(Date.now())+' UTC');lastClock=now;}
    requestAnimationFrame(animate);
  }
  pollTracks();const polling=setInterval(pollTracks,200);requestAnimationFrame(animate);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){pollTracks();logTransport.poll();}});
  window.addEventListener('pagehide',()=>{clearInterval(polling);logTransport.stop();},{once:true});
})();
