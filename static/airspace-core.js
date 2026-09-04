(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.Airspace=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const rank={HIGH:3,WARNING:2,INFO:1,NORMAL:0};
  function angle(east,north){return Math.hypot(east,north)<1e-9?null:(Math.atan2(east,north)*180/Math.PI+360)%360;}
  function telemetry(position,velocity){
    return {range_m:position?Math.hypot(position.x_m,position.y_m):null,
      bearing_deg:position?angle(position.x_m,position.y_m):null,altitude_m:position?position.z_m:null,
      ground_speed_mps:velocity?Math.hypot(velocity.vx_mps,velocity.vy_mps):null,
      heading_deg:velocity?angle(velocity.vx_mps,velocity.vy_mps):null};
  }
  function project(range,bearing,maxRange){
    if(!Number.isFinite(range)||!Number.isFinite(bearing)||!(maxRange>0))return null;
    const radians=bearing*Math.PI/180,radius=range/maxRange*430;
    return {x:500+Math.sin(radians)*radius,y:500-Math.cos(radians)*radius};
  }
  function point(position,maxRange){
    if(!position)return null;
    const data=telemetry(position,null);
    return data.range_m<1e-9?{x:500,y:500}:project(data.range_m,data.bearing_deg,maxRange);
  }
  function interpolate(previous,current,fraction){
    if(!current.position||!current.synthetic||!previous?.position)return current;
    const alpha=Math.max(0,Math.min(1,fraction)),position={},velocity={};
    for(const key of ['x_m','y_m','z_m'])position[key]=previous.position[key]+(current.position[key]-previous.position[key])*alpha;
    if(previous.velocity&&current.velocity)for(const key of ['vx_mps','vy_mps','vz_mps'])velocity[key]=previous.velocity[key]+(current.velocity[key]-previous.velocity[key])*alpha;
    const actualVelocity=current.velocity?Object.keys(velocity).length?velocity:current.velocity:null;
    return {...current,position,velocity:actualVelocity,...telemetry(position,actualVelocity)};
  }
  function primary(tracks){
    return tracks.filter(t=>t.position&&t.state!=='EXITED').slice().sort((a,b)=>
      (rank[b.severity]||0)-(rank[a.severity]||0)||a.range_m-b.range_m||a.track_id.localeCompare(b.track_id))[0]?.track_id||null;
  }
  class Frames{
    constructor(){this.previous=new Map();this.current=new Map();this.run=null;this.revision=-1;this.received=0;this.interval=200;}
    accept(snapshot,now){
      if(this.run===snapshot.run_id&&snapshot.revision<=this.revision)return false;
      const same=this.run===snapshot.run_id;
      this.previous=same?this.current:new Map();
      this.interval=same?Math.max(80,Math.min(400,now-this.received)):200;
      this.current=new Map(snapshot.tracks.map(track=>[track.track_id,track]));
      this.run=snapshot.run_id;this.revision=snapshot.revision;this.received=now;
      return true;
    }
    values(now){
      const alpha=(now-this.received)/this.interval;
      return [...this.current.values()].map(track=>interpolate(this.previous.get(track.track_id),track,alpha));
    }
    clear(){this.previous.clear();this.current.clear();this.run=null;this.revision=-1;}
  }
  function eventSource(event){
    return event?.raw_payload?.synthetic===true&&event?.is_simulated?'SYNTHETIC':null;
  }
  return {angle,telemetry,project,point,interpolate,primary,Frames,eventSource,rank};
});
