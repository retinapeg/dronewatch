(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.DroneWatch = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  function kind(event) {
    const raw=event?.raw_payload||{},source=String(event?.source||'').toLowerCase();
    if(event?.is_simulated||raw.SIMULATED===true||source.includes('simulat'))return 'SIMULATED';
    if(/manual|test/.test(source)||raw._dronewatch_check)return 'TEST';
    if(raw.appId&&(raw.incidentId||raw.incidentNumber))return 'VISO';
    return 'WEBHOOK';
  }
  function safeURL(value) {
    if(typeof value!=='string'||!/^https?:\/\//i.test(value))return null;
    try { const url=new URL(value);return !url.username&&!url.password?url.href:null; } catch { return null; }
  }
  function confidence(value, label) {
    if(typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1)return `${Math.round(value*1000)/10}%`;
    if(typeof label==='string'&&/^(high|medium|low)$/i.test(label))return `${label.toUpperCase()} / QUALITATIVE`;
    return '\u2014';
  }
  class EventStore {
    constructor(limit=200) { this.limit=limit;this.records=new Map();this.total=0; }
    merge(payload) {
      const before=this.latest()?.id??0;
      const list=payload.events||[payload];
      for(const event of list)if(event&&Number.isFinite(Number(event.id)))this.records.set(Number(event.id),event);
      for(const id of [...this.records.keys()].sort((a,b)=>b-a).slice(this.limit))this.records.delete(id);
      if(Number.isFinite(payload.total_count))this.total=payload.total_count;
      else this.total=Math.max(this.total,this.records.size);
      return Number(this.latest()?.id??0)>Number(before);
    }
    events() { return [...this.records.values()].sort((a,b)=>Number(b.id)-Number(a.id)); }
    latest() { return this.events()[0]||null; }
  }
  function backoff(attempt) { return Math.min(30000,1000*2**Math.min(attempt,5)); }
  function transport(options) {
    const {store,onEvents,onConsole,onConnection,getMode}=options;
    const fetcher=options.fetch||fetch,EventSourceImpl=options.EventSource||EventSource;
    const timers=options.timers||globalThis;
    let source=null,retry=null,attempt=0,stopped=false,busy=false,lastBeat=0;
    const notify=payload=>{const changed=store.merge(payload);onEvents(changed);};
    const applyState=payload=>{if(payload?.mode===getMode())onConsole(payload);};
    function reconnect() {
      if(stopped)return;
      if(source)source.close();source=null;
      onConnection('stream',false);
      if(retry!==null)return;
      retry=timers.setTimeout(()=>{retry=null;connect();},backoff(attempt++));
    }
    function connect() {
      if(stopped)return;
      source=new EventSourceImpl(`/api/stream?mode=${encodeURIComponent(getMode())}&after_id=${store.latest()?.id||0}`);
      source.onopen=()=>{attempt=0;lastBeat=Date.now();onConnection('stream',true);onConnection('backend',true);};
      source.onerror=reconnect;
      for(const type of ['snapshot','observation','console','heartbeat'])source.addEventListener(type,event=>{
        try {
          const payload=JSON.parse(event.data);lastBeat=Date.now();attempt=0;
          onConnection('stream',true);onConnection('backend',true);
          if(type==='snapshot'||type==='observation')notify(payload);
          if(type==='console')applyState(payload);else if(payload.console)applyState(payload.console);
        } catch { reconnect(); }
      });
    }
    async function poll() {
      if(busy||stopped)return;busy=true;
      const mode=getMode(),timestamp=Date.now();
      try {
        const responses=await Promise.all([
          fetcher(`/api/events?limit=200&t=${timestamp}`,{cache:'no-store',signal:AbortSignal.timeout(6000)}),
          fetcher(`/api/console?mode=${encodeURIComponent(mode)}&t=${timestamp}`,{cache:'no-store',signal:AbortSignal.timeout(6000)})
        ]);
        if(responses.some(response=>!response.ok))throw new Error('Backend unavailable');
        const [events,consoleState]=await Promise.all(responses.map(response=>response.json()));
        if(!Array.isArray(events.events))throw new Error('Invalid event response');
        notify(events);applyState(consoleState);onConnection('backend',true);
      } catch { onConnection('backend',false); }
      finally { busy=false; }
    }
    const pollTimer=timers.setInterval(poll,2000);
    const watchdog=timers.setInterval(()=>{if(source&&lastBeat&&Date.now()-lastBeat>25000)reconnect();},5000);
    connect();poll();
    return {
      poll,
      changeMode() { if(source)source.close();if(retry!==null)timers.clearTimeout(retry);retry=null;attempt=0;connect();poll(); },
      stop() { stopped=true;if(source)source.close();if(retry!==null)timers.clearTimeout(retry);timers.clearInterval(pollTimer);timers.clearInterval(watchdog); }
    };
  }
  return {kind,safeURL,confidence,EventStore,backoff,transport};
});
