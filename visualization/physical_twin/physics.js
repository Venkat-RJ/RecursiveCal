/* Experimental one-hinge vehicle tailgate model. All numeric parameters are
   illustrative, not manufacturer-derived or calibrated against real equipment.
   Equations mirror physics.py for independent parity checks. */
(function (global) {
'use strict';
const PI=Math.PI, MAX_Q=1.36, HINGE_Z=1.76, AX=-.48, AZ=1.10, BX=.025, BD=.67;
const DT=.01, GRAVITY=9.81, OPEN_SECONDS=4.8, RUNTIME=6.5;
const healthy={mass:25,motor_eff:1,hinge_friction:1,sensor_bias:0,strut_gas:1,damping:1};
const scenarioTable={
 healthy:{...healthy},
 friction:{...healthy,hinge_friction:3.1},
 motor:{...healthy,motor_eff:.57},
 load:{...healthy,mass:33},
 sensor:{...healthy,sensor_bias:.085},
 combined:{...healthy,motor_eff:.63,hinge_friction:2.5,mass:28},
 gas:{...healthy,strut_gas:.48}
};
const factory={gain:1,friction_ff:8,gravity_ff:1,sensor_comp:0};
function clamp(x,l,h){return Math.min(h,Math.max(l,x));}
function strutGeom(q){
 const x=BX*Math.cos(q)+BD*Math.sin(q),z=HINGE_Z+BX*Math.sin(q)-BD*Math.cos(q);
 const dx=-BX*Math.sin(q)+BD*Math.cos(q),dz=BX*Math.cos(q)+BD*Math.sin(q);
 const vx=x-AX,vz=z-AZ, L=Math.sqrt(vx*vx+vz*vz);
 return {length:L,lever:(vx*dx+vz*dz)/L,x,z};
}
function reference(t){const r=clamp(t/OPEN_SECONDS,0,1),q=MAX_Q*r*r*(3-2*r);
 if(r<=0||r>=1)return {q,v:0,a:0};
 return {q,v:MAX_Q*(6*r-6*r*r)/OPEN_SECONDS,a:MAX_Q*(6-12*r)/(OPEN_SECONDS*OPEN_SECONDS)};
}
function gasForce(q,p){return (63+19*(1.27-strutGeom(q).length))*p.strut_gas;}
function gravTorque(q,p){return p.mass*GRAVITY*.57*Math.sin(q+.16);}
function frictionTorque(v,p){return (5*Math.tanh(v/.025)+5.5*v)*p.hinge_friction*p.damping;}
function simulate(p=healthy,cal=factory,duration=RUNTIME){
 let q=0,v=0,frames=[],safety=0;
 const count=Math.round(duration/DT); const nominal=healthy;
 for(let i=0;i<=count;i++){
  const t=Math.round(i*DT*1000000)/1000000;
  const ref=reference(t),sg=strutGeom(q),gf=gasForce(q,p),gastau=2*gf*sg.lever;
  const nomgas=2*gasForce(q,nominal)*sg.lever;
  const observed=q+p.sensor_bias-cal.sensor_comp;
  const positional=cal.gain*(150*(ref.q-observed)+59*(ref.v-v));
  const commanded=17*ref.a+positional+cal.gravity_ff*gravTorque(q,nominal)-nomgas+cal.friction_ff*Math.tanh(ref.v/.04);
  const requested=commanded/(2*Math.max(.22,sg.lever));
  const motorF=clamp(requested,-260,260)*p.motor_eff;
  const motorTau=2*motorF*sg.lever;
  const net=motorTau+gastau-gravTorque(q,p)-frictionTorque(v,p);
  const accel=net/17, current=Math.abs(motorF)/17.5+.55;
  if(Math.abs(v)>1.1||current>17||q>=MAX_Q+.0001)safety++;
  if(i%3===0||i===count)frames.push({t,q,target:ref.q,vel:v,current,force:motorF,
    stroke:sg.length-strutGeom(0).length,tau:motorTau,error:ref.q-q,saturated:Math.abs(requested)>260});
  if(i<count){let vn=v+accel*DT,qn=q+vn*DT;
   if(qn<0){qn=0;vn=0;} if(qn>MAX_Q){qn=MAX_Q;vn=0;}
   q=qn;v=vn;
  }
 }
 let err=0,effort=0,maxCurrent=0;for(const f of frames){err+=Math.abs(f.error);effort+=Math.abs(f.current)*DT*3;maxCurrent=Math.max(maxCurrent,f.current);}
 const round=(n,d)=>Math.round((n+Number.EPSILON)*Math.pow(10,d))/Math.pow(10,d);
 return {frames,metrics:{mae_deg:round(err/frames.length*180/PI,2),final_error_deg:round(Math.abs(MAX_Q-frames.at(-1).q)*180/PI,2),
 peak_current_A:round(maxCurrent,2),total_charge_As:round(effort,2),safety_flags:safety,
 open_angle_deg:round(frames.at(-1).q*180/PI,1)}};
}
global.TailgatePhysics={MAX_Q,DT,RUNTIME,OPEN_SECONDS,scenarios:scenarioTable,factory,strutGeom,reference,simulate,clamp,healthy};
if(typeof module!=='undefined'&&module.exports)module.exports=global.TailgatePhysics;
})(typeof window==='object'?window:globalThis);