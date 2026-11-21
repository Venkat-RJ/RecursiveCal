// Exact synthetic dynamics and evaluation formulas ported from recursivecal.py.
// This is a LOCAL VISUAL DEMO. An RL evaluator must keep the plant host-side.
const RCDT = 0.02;
const RC_POSITION_LIMIT = 0.50;
const RC_SPEED_LIMIT = 0.75;
const RC_TORQUE_LIMIT = 0.85;
const RC_EVAL_TRAJECTORIES = [[-0.15,0.28],[0.15,-0.28],[-0.05,0.32],[0.05,-0.32]];
const RC_GAINS = [0.75,0.90,1.00,1.12,1.25,1.40];
const RC_FRICTION = [0,0.08,0.16,0.24,0.32];
const RC_BIASES = [-0.08,-0.04,0,0.04,0.08];
const RC_DEFAULT = {gain:1.00,friction_ff:0.08,sensor_offset:0};
const rcClamp=(x,lo,hi)=>Math.min(hi,Math.max(lo,x));
function rcAcceleration(p,x,v,torque){
  const delivered = Math.sign(torque)*Math.max(0,Math.abs(torque)-p.torque_deadzone);
  return p.motor*delivered - p.friction*Math.tanh(v/0.035)
       - p.damping*v - p.load*Math.sin(Math.PI*x/1.1);
}
function rcPulseTrace(plant,probe){
  if(probe.kind==='reference') return {frames:[{t:0,x:0,v:0,torque:0}],result:[plant.sensor_bias],risk:0};
  const torque=probe.torque,fixture=probe.fixture_x,seconds=probe.seconds;
  if(Math.abs(torque)>RC_TORQUE_LIMIT || Math.abs(fixture)>0.30 || seconds<=0 || seconds>0.6) throw new Error('Unsafe diagnostic command');
  let x=fixture,v=0,risk=0;
  const frames=[{t:0,x,v,torque}];
  for(let i=0;i<Math.round(seconds/RCDT);i++){
    const a=rcAcceleration(plant,x,v,torque);
    const vn=v+a*RCDT, xn=x+vn*RCDT;
    if(Math.abs(vn)>RC_SPEED_LIMIT || Math.abs(xn)>RC_POSITION_LIMIT){risk++;break;}
    x=xn;v=vn;
    frames.push({t:(i+1)*RCDT,x,v,torque});
  }
  return {frames,result:[x-fixture,v],risk};
}
function rcClosedLoop(plant,cal,x0,target){
  let x=x0,v=0,risk=0,effort=0,cumulative=0;
  const frames=[{t:0,x,v,torque:0,target}];
  for(let i=0;i<Math.round(1.8/RCDT);i++){
    const observed=x+plant.sensor_bias;
    const err=target-(observed-cal.sensor_offset);
    const raw=cal.gain*(3.1*err-1.25*v+cal.friction_ff*Math.tanh(err/0.045));
    const torque=rcClamp(raw,-RC_TORQUE_LIMIT,RC_TORQUE_LIMIT);
    const a=rcAcceleration(plant,x,v,torque);
    const vn=v+a*RCDT,xn=x+vn*RCDT;
    if(Math.abs(xn)>=RC_POSITION_LIMIT || Math.abs(vn)>=RC_SPEED_LIMIT){risk++;break;}
    x=xn;v=vn;
    cumulative+=Math.abs(target-x)*RCDT;
    effort+=Math.abs(torque)*RCDT;
    frames.push({t:(i+1)*RCDT,x,v,torque,target});
  }
  const loss=3.8*Math.abs(x-target)+0.45*Math.abs(v)+0.05*cumulative+0.006*effort+(risk?3*risk:0);
  return {frames,x,v,risk,effort,cumulative,loss,target};
}
function rcQuality(plant,cal){
  const runs=RC_EVAL_TRAJECTORIES.map(([x,t])=>rcClosedLoop(plant,cal,x,t));
  const quality=Math.exp(-runs.reduce((s,r)=>s+r.loss,0)/runs.length);
  return {quality,interventions:runs.reduce((s,r)=>s+r.risk,0),
          meanError:runs.reduce((s,r)=>s+Math.abs(r.x-r.target),0)/runs.length,
          meanEffort:runs.reduce((s,r)=>s+r.effort,0)/runs.length,runs};
}
function rcNoise(seed,sigma){
  let s=(seed>>>0)||1;
  s=(Math.imul(s^0x9e3779b9,1664525)+1013904223)>>>0;
  const u=Math.max(1e-10,s/4294967296);
  s=(Math.imul(s,22695477)+1)>>>0;
  const v=Math.max(1e-10,s/4294967296);
  return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)*sigma;
}
