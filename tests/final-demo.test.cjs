const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const core = require('../static/stage-core.js');
const source = fs.readFileSync(path.join(__dirname,'../static/final-demo.js'),'utf8');
const html = fs.readFileSync(path.join(__dirname,'../final-demo.html'),'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor(id='') {
    this.id=id; this.dataset={}; this.style={}; this.attributes=new Map(); this.listeners={}; this.children=[]; this._text=''; this.hidden=false;
    const classes=new Set();
    this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)};
  }
  get textContent() { return this.children.length ? this.children.map(x=>x.textContent).join('') : this._text; }
  set textContent(value) { this._text=String(value); this.children=[]; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; this._text=''; }
  setAttribute(key,value) { this.attributes.set(key,String(value)); }
  toggleAttribute(key,on) { if(on) this.attributes.set(key,''); else this.attributes.delete(key); }
  hasAttribute(key) { return this.attributes.has(key); }
  addEventListener(event,callback) { this.listeners[event]=callback; }
  getBoundingClientRect() { return {x:0,y:0,width:100,height:100}; }
}

function payload(scenario='drone',t=0,run='run-1') {
  const specs={drone:['UAS','UAS',.96,'DW-001'],aircraft:['AIRCRAFT','AIRCRAFT',.94,'AC-001'],bird:['BIRD','BIRD',.88,'BD-001']};
  const [category,label,confidence,id]=specs[scenario];
  const detection=t>=3?{class:category,label,confidence,sensor_x:.65,sensor_y:.4,sensor_scale:1}:null;
  const track=t>=6?{id,track_id:id,class:category,confidence,state:scenario==='bird'?'NON_UAS':'APPROACHING',x:300,y:400,z:120,range_m:500,bearing_deg:core.geometry(300,400,120).bearing_deg,altitude_m:120,speed_mps:15,heading_deg:221,history:[{x:400,y:500},{x:300,y:400}]}:null;
  return {run_id:run,scenario,elapsed_s:t,duration_s:35,running:true,has_started:t>0,complete:false,system_state:track?track.state:detection?'DETECTED':'CLEAR',severity:'NORMAL',banner:track?'TRACK ACQUIRED — '+id:detection?'VISUAL CONTACT DETECTED':'AIRSPACE CLEAR',sensor_state:detection?'TRACKING':'MONITORING',sensor_timestamp:'2026-09-04T12:00:00+00:00',zones:{maximum_m:2500},detection,track,events:[{id:run+'-0',timestamp:'2026-09-04T12:00:00+00:00',category:'SYSTEM',message:'AIRSPACE MONITORING'}]};
}

function harness() {
  const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],new Element(match[1])]));
  ['eo-target','contact','contact-held','shape-aircraft','shape-bird'].forEach(id=>elements.get(id).setAttribute('hidden',''));
  const scenarioButtons=['run','aircraft','bird'].map(id=>elements.get(id));
  scenarioButtons.forEach((element,i)=>{element.dataset.scenario=['drone','aircraft','bird'][i];});
  const buttons=[...scenarioButtons,elements.get('reset'),elements.get('fullscreen')];
  const body=new Element(), requests=[];
  let next=payload(), now=0, frame, poll, fail=false, serial=1;
  const document={body,fullscreenElement:null,getElementById:id=>elements.get(id),createTextNode:text=>({textContent:text}),createElement:()=>new Element(),addEventListener(){},
    querySelectorAll:selector=>selector==='[data-scenario]'?scenarioButtons:selector==='.controls button:not(#fullscreen)'?buttons.slice(0,-1):buttons,
    documentElement:{requestFullscreen:async()=>{}},exitFullscreen:async()=>{}};
  const sandbox={document,window:{StageCore:core},performance:{now:()=>now},AbortController,
    setTimeout:()=>1,clearTimeout(){},setInterval:fn=>{poll=fn;return 1;},requestAnimationFrame:fn=>{frame=fn;},
    fetch:async(url,options)=>{
      requests.push({url,options}); if(fail) throw Error('offline');
      if(url.endsWith('/start')) next=payload(JSON.parse(options.body).scenario,0,'run-'+(++serial));
      if(url.endsWith('/reset')) next=payload('drone',0,'run-'+(++serial));
      return {ok:true,json:async()=>next};
    }};
  vm.runInNewContext(source,sandbox);
  return {elements,body,requests,setNext:value=>{next=value;},setFail:value=>{fail=value;},
    async tick(value){now=value;await poll();await flush();frame();},
    async click(id){await elements.get(id).listeners.click();await flush();}};
}

test('backend detection reveals SVG target; acquisition reveals radar and coherent telemetry',async()=>{
  const h=harness(); await flush();
  assert.ok(h.elements.get('eo-target').hasAttribute('hidden'));
  assert.ok(h.elements.get('contact').hasAttribute('hidden'));
  h.setNext(payload('drone',3)); await h.tick(200);
  assert.equal(h.elements.get('eo-target').hasAttribute('hidden'),false);
  assert.equal(h.elements.get('contact').hasAttribute('hidden'),true);
  assert.equal(h.elements.get('eo-label').textContent,'UAS 96%');
  assert.equal(h.elements.get('detection-class').textContent,'DRONE');
  h.setNext(payload('drone',8)); await h.tick(400);
  assert.equal(h.elements.get('contact').hasAttribute('hidden'),false);
  assert.equal(h.elements.get('track-id').textContent,'DW-001');
  assert.equal(h.elements.get('track-class').textContent,'UAS');
  assert.equal(h.elements.get('track-confidence').textContent,'96%');
  assert.equal(h.elements.get('range').textContent,'500m');
  assert.equal(h.elements.get('bearing').textContent,'037°');
  assert.equal(h.elements.get('altitude').textContent,'120m');
  assert.equal(h.elements.get('speed').textContent,'15.0m/s');
});

test('scenario buttons call backend; bird and aircraft shapes and classes replace drone',async()=>{
  const h=harness(); await flush();
  for(const scenario of ['aircraft','bird']) {
    await h.click(scenario);
    assert.equal(h.requests.at(-1).url,'/api/demo/start');
    assert.equal(JSON.parse(h.requests.at(-1).options.body).scenario,scenario);
    h.setNext(payload(scenario,8,scenario)); await h.tick(scenario==='bird'?600:400);
    assert.equal(h.elements.get('shape-'+scenario).hasAttribute('hidden'),false);
    assert.equal(h.elements.get('shape-drone').hasAttribute('hidden'),true);
    assert.equal(h.elements.get('detection-class').textContent,scenario.toUpperCase());
  }
  assert.equal(h.elements.get('track-state').textContent,'NON-UAS CONTACT');
  assert.equal(h.body.dataset.severity,'NORMAL');
  await h.click('reset');
  assert.equal(h.requests.at(-1).url,'/api/demo/reset');
  assert.ok(h.elements.get('eo-target').hasAttribute('hidden'));
  assert.ok(h.elements.get('contact').hasAttribute('hidden'));
  assert.equal(h.elements.get('event-log').children.length,1);
});

test('final hold has no invented heading and event log is deduplicated',async()=>{
  const h=harness(); await flush();
  const end=payload('drone',35); end.complete=true; end.running=false;
  end.track.speed_mps=0; end.track.heading_deg=null;
  h.setNext(end); await h.tick(400);
  assert.equal(h.elements.get('contact-heading').hasAttribute('hidden'),true);
  assert.equal(h.elements.get('contact-held').hasAttribute('hidden'),false);
  assert.equal(h.elements.get('sequence').textContent,'SEQUENCE COMPLETE · STATE HELD');
  await h.tick(1000);
  assert.equal(h.elements.get('event-log').children.length,1);
});

test('backend failure is visible and controls recover without a fake live state',async()=>{
  const h=harness(); await flush();
  h.setFail(true); await h.tick(3000);
  assert.equal(h.elements.get('connection').textContent,'BACKEND UNAVAILABLE');
  assert.equal(h.elements.get('banner').textContent,'DEMO BACKEND DISCONNECTED');
  h.setFail(false); await h.click('run');
  assert.equal(h.elements.get('connection').textContent,'SYSTEM ONLINE');
  assert.equal(h.elements.get('run').disabled,false);
  assert.equal(h.elements.get('banner').textContent,'AIRSPACE CLEAR');
});
