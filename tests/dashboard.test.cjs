const { test } = require('node:test');
const assert = require('node:assert/strict');
const dw = require('../static/core.js');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const intervals = new Map(), timeouts = new Map(), connections = [], sources = [], requests = [];
  let nextId = 1, failed = false, mode = 'VISO', payload = {events: [], total_count: 0};
  let consoleState = {mode: 'VISO'};
  const timers = {
    setInterval(fn, ms) { const id=nextId++; intervals.set(id,{fn,ms}); return id; },
    clearInterval(id) { intervals.delete(id); },
    setTimeout(fn, ms) { const id=nextId++; timeouts.set(id,{fn,ms}); return id; },
    clearTimeout(id) { timeouts.delete(id); }
  };
  class FakeSource {
    constructor(url) { this.url=url; this.handlers={}; this.closed=false; sources.push(this); }
    addEventListener(name, fn) { this.handlers[name]=fn; }
    emit(name, data) { this.handlers[name]({data:JSON.stringify(data)}); }
    close() { this.closed=true; }
  }
  const store = new dw.EventStore();
  const changes=[], states=[];
  const transport=dw.transport({store, timers, EventSource:FakeSource,
    getMode:()=>mode,
    onEvents:changed=>changes.push(changed), onConsole:state=>states.push(state),
    onConnection:(component,online)=>connections.push([component,online]),
    fetch:async (url,options)=>{
      requests.push({url,options});
      if(failed) throw new Error('offline');
      return {ok:true,json:async()=>url.startsWith('/api/events')?payload:consoleState};
    }
  });
  return {transport,store,intervals,timeouts,connections,sources,requests,changes,states,
    fail(value) { failed=value; },
    setEvents(value) { payload=value; },
    setMode(value) { mode=value; consoleState={mode:value}; },
    runRetry() { const [id,item]=timeouts.entries().next().value; timeouts.delete(id); item.fn(); return item.ms; }
  };
}

test('event 8 remains the latest observation instead of freezing on genuine Viso event 6',()=>{
  const store=new dw.EventStore();
  store.merge({events:[{id:6,raw_payload:{appId:'app',incidentId:'incident'}}],total_count:6});
  assert.equal(store.merge({events:[{id:8,is_simulated:true},{id:6}],total_count:8}),true);
  assert.equal(store.latest().id,8);
  assert.equal(store.total,8);
  assert.equal(dw.kind(store.latest()),'SIMULATED');
});

test('same drone category with distinct webhook IDs remains separate history',()=>{
  const store=new dw.EventStore();
  store.merge({events:[{id:8,detection_type:'drone'},{id:9,detection_type:'drone'}],total_count:9});
  assert.deepEqual(store.events().map(event=>event.id),[9,8]);
  assert.equal(store.total,9);
});

test('SSE replay and polling merge repeated IDs without duplicate observations',()=>{
  const store=new dw.EventStore();
  store.merge({id:8,detection_type:'drone'});
  assert.equal(store.merge({events:[{id:8},{id:7}],total_count:8}),false);
  assert.equal(store.merge({id:9,detection_type:'drone'}),true);
  assert.equal(store.merge({id:9,detection_type:'drone'}),false);
  assert.deepEqual(store.events().map(event=>event.id),[9,8,7]);
});

test('late older responses cannot move latest ID backwards; browser history is bounded',()=>{
  const store=new dw.EventStore(2);
  store.merge({events:[{id:8},{id:9},{id:10}],total_count:10});
  assert.equal(store.merge({events:[{id:6},{id:7}]}),false);
  assert.equal(store.latest().id,10);
  assert.deepEqual(store.events().map(event=>event.id),[10,9]);
});

test('source attribution never upgrades simulations or manual tests to genuine Viso',()=>{
  const event={raw_payload:{appId:'app',incidentId:'incident'}};
  assert.equal(dw.kind(event),'VISO');
  assert.equal(dw.kind({...event,is_simulated:true}),'SIMULATED');
  assert.equal(dw.kind({source:'manual-test'}),'TEST');
  assert.equal(dw.kind({source:'VISO',raw_payload:{}}),'WEBHOOK');
  assert.equal(dw.kind({raw_payload:{...event.raw_payload,_dronewatch_check:true}}),'TEST');
});

test('qualitative confidence and zero are preserved without invented percentages',()=>{
  assert.equal(dw.confidence(null,'high'),'HIGH / QUALITATIVE');
  assert.equal(dw.confidence(0),'0%');
  assert.equal(dw.confidence(.913),'91.3%');
  assert.equal(dw.confidence(null),'\u2014');
  assert.equal(dw.confidence(94),'\u2014');
});

test('relative Viso media paths, executable URLs and URLs with credentials are rejected',()=>{
  assert.equal(dw.safeURL('media/video_files/demo.mp4'),null);
  assert.equal(dw.safeURL('javascript:alert(1)'),null);
  assert.equal(dw.safeURL('https://user:secret@example.org/a.mp4'),null);
  assert.equal(dw.safeURL('https://sensor.example.org/a.mp4'),'https://sensor.example.org/a.mp4');
});

test('polling runs every two seconds with timestamp cache busting and no-store',async()=>{
  const h=harness(); await flush();
  assert.ok([...h.intervals.values()].some(item=>item.ms===2000));
  assert.equal(h.requests.length,2);
  for(const request of h.requests) {
    assert.match(request.url,/[?&]t=\d+/);
    assert.equal(request.options.cache,'no-store');
    assert.ok(request.options.signal);
  }
  h.transport.stop();
  assert.equal(h.intervals.size,0);
});

test('polling works when stream is unavailable and recovers after backend failure',async()=>{
  const h=harness(); await flush();
  h.sources[0].onerror(); h.fail(true); await h.transport.poll();
  assert.deepEqual(h.connections.at(-1),['backend',false]);
  h.fail(false); h.setEvents({events:[{id:8}],total_count:8}); await h.transport.poll();
  assert.deepEqual(h.connections.at(-1),['backend',true]);
  assert.equal(h.store.latest().id,8);
  h.setEvents({events:[{id:9},{id:8}],total_count:9}); await h.transport.poll();
  assert.equal(h.store.latest().id,9);
  assert.equal(h.changes.at(-1),true);
  h.transport.stop();
});

test('reconnect uses bounded exponential delays and resumes after the last stored ID',async()=>{
  const h=harness(); await flush();
  h.store.merge({id:8});
  for(const delay of [1000,2000,4000,8000,16000,30000,30000]) {
    h.sources.at(-1).onerror();
    assert.equal(h.runRetry(),delay);
    assert.match(h.sources.at(-1).url,/after_id=8/);
  }
  h.transport.stop();
});

test('stream snapshot, observation, heartbeat and fallback share one event store',async()=>{
  const h=harness(); await flush(); const stream=h.sources[0];
  stream.onopen();
  stream.emit('snapshot',{events:[{id:8}],total_count:8,console:{mode:'VISO'}});
  stream.emit('observation',{id:9});
  stream.emit('heartbeat',{console:{mode:'VISO'}});
  h.setEvents({events:[{id:9},{id:8}],total_count:9}); await h.transport.poll();
  assert.deepEqual(h.store.events().map(event=>event.id),[9,8]);
  assert.equal(h.states.length,4);
  assert.equal(h.store.total,9);
  h.transport.stop();
});

test('switching mode ignores a late snapshot from the previous source',async()=>{
  const h=harness(); await flush();
  h.setMode('BENCHMARK_REPLAY'); h.transport.changeMode(); await flush();
  const before=h.states.length;
  h.sources.at(-1).emit('console',{mode:'VISO'});
  assert.equal(h.states.length,before);
  h.sources.at(-1).emit('console',{mode:'BENCHMARK_REPLAY'});
  assert.equal(h.states.length,before+1);
  assert.ok(h.sources[0].closed);
  h.transport.stop();
});

test('malformed stream messages reconnect instead of freezing the UI',async()=>{
  const h=harness(); await flush();
  h.sources[0].handlers.observation({data:'broken JSON'});
  assert.equal(h.timeouts.size,1);
  assert.ok(h.sources[0].closed);
  h.transport.stop();
});

const StageCore = require('../static/stage-core.js');
test('stage radar uses ENU geometry and cardinal projection', () => {
  assert.deepEqual(StageCore.project(0, 2500), {x:500,y:85});
  assert.deepEqual(StageCore.project(2500, 0), {x:915,y:500});
  assert.equal(StageCore.geometry(300,400,140).range_m, 500);
  assert.equal(StageCore.geometry(0,-10,140).bearing_deg, 180);
});
test('stage interpolation derives range and bearing from the same displayed position', () => {
  const a = {track_id:'DW-001',x:300,y:400,z:140};
  const b = {track_id:'DW-001',x:100,y:200,z:150,state:'COASTING',confidence:null};
  const result = StageCore.interpolate(a,b,.5);
  assert.equal(result.x,200); assert.equal(result.y,300); assert.equal(result.z,145);
  assert.equal(result.range_m,Math.hypot(200,300));
  assert.equal(result.state,'COASTING'); assert.equal(result.confidence,null);
  assert.equal(a.x,300); assert.equal(b.x,100);
  assert.equal(StageCore.interpolate(a,null,.5),null);
});
