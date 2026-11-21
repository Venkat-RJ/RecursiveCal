const p=require('../physics.js');
const assert=require('node:assert/strict');
for(const [label,plant] of Object.entries(p.scenarios)){
  const out=p.simulate(plant);
  assert(out.frames.length>200);
  for(const f of out.frames){
    assert(Number.isFinite(f.q)&&Number.isFinite(f.current));
    assert(f.q>=-1e-9&&f.q<=p.MAX_Q+1e-9);
  }
}
assert(p.simulate(p.scenarios.motor).metrics.open_angle_deg<p.simulate(p.scenarios.healthy).metrics.open_angle_deg);
assert(p.strutGeom(1).length>p.strutGeom(0).length);
console.log('RecursiveCal physical model: 7 scenarios, hinge bounds, strut kinematics PASS');
