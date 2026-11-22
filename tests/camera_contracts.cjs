"use strict";
// Camera contracts use independently known projective geometry, not screenshots.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "mechanics/cad_v1/viewer/cad_renderer.js"), "utf8");
assert.equal(source, fs.readFileSync(path.join(root, "recursivecal_lab/web/inquiry-renderer.js"), "utf8"));
const context = {window:{}, CustomEvent:class {constructor(type, options){this.type=type;this.detail=options.detail;}}};
vm.runInNewContext(source, context);
const camera = Object.create(context.window.PhysicalRenderer.prototype);
let draws = 0;
const events = [];
camera.canvas = {clientWidth:800,clientHeight:500,dataset:{},dispatchEvent:e=>events.push(e)};
camera.mechanics = false;
camera.compare = false;
camera.draw = ()=>draws++;
camera.resetCamera();
const json = value => JSON.parse(JSON.stringify(value));
const initial = json(camera.getCamera());
assert.equal(initial.schema_version, "recursivecal.inspection-camera/1");
assert.equal(camera.getView(), "isometric");
const detached = camera.getCamera();
detached.target_m[0] = 99;
assert.deepEqual(json(camera.getCamera()), initial);
events.at(-1).detail.target_m[0] = -99;
assert.deepEqual(json(camera.getCamera()), initial);
camera.setCamera(JSON.parse(JSON.stringify(initial)));
assert.deepEqual(json(camera.getCamera()), initial);

// Imported invalid state must fail atomically, including malformed JSON types.
const invalid = [
  {...initial,schema_version:"future/2"}, {...initial,focus:"prototype"},
  {...initial,focus:["assembly"]}, {...initial,distance_m:0},
  {...initial,distance_m:12}, {...initial,distance_m:NaN},
  {...initial,yaw_rad:Infinity}, {...initial,yaw_rad:4},
  {...initial,elevation_rad:Math.PI}, {...initial,vertical_fov_deg:true},
  {...initial,vertical_fov_deg:180}, {...initial,target_m:[0,0]},
  {...initial,target_m:[0,0,NaN]}, {...initial,target_m:[0,0,10]},
  {...initial,unknown:1}, null, [], {focus:"assembly"},
];
for(const state of invalid){
  const oldDraws=draws, oldEvents=events.length;
  assert.throws(()=>camera.setCamera(state));
  assert.deepEqual(json(camera.getCamera()), initial);
  assert.equal(draws,oldDraws);
  assert.equal(events.length,oldEvents);
}

const close = (a,b,tolerance=1e-9)=>assert.ok(Math.abs(a-b)<tolerance, `${a} differs from ${b}`);
// Every preset keeps the point being inspected at the optical centre.
for(const view of ["isometric","front","side","top"]){
  camera.setView(view);
  assert.equal(camera.getView(),view);
  const projected=camera.projectPoint(camera.target);
  close(projected.x,400);close(projected.y,250);
  assert.ok(projected.visible);
  close(Math.hypot(...camera.eye().map((v,i)=>v-camera.target[i])),camera.radius);
  assert.ok(camera.cameraMatrix(800,500).every(Number.isFinite));
}

// Known front-facing perspective: 10 cm horizontally projects by f * offset / distance.
camera.setView("front");
const f=250/Math.tan(camera.fovDeg*Math.PI/360);
const front=camera.projectPoint([camera.target[0],camera.target[1]+.1,camera.target[2]]);
close(front.x,400+f*.1/camera.radius);
close(front.y,250);
const above=camera.projectPoint([camera.target[0],camera.target[1],camera.target[2]+.1]);
close(above.y,250-f*.1/camera.radius);
camera.setView("side");
assert.ok(camera.projectPoint([camera.target[0]+.1,camera.target[1],camera.target[2]]).x<400);
camera.setView("top");
assert.ok(camera.projectPoint([camera.target[0]+.1,camera.target[1],camera.target[2]]).x>400);
assert.ok(camera.projectPoint([camera.target[0],camera.target[1]+.1,camera.target[2]]).y<250);

// Comparison views share the same camera with two independently centred viewports.
camera.compare=true;
close(camera.projectPoint(camera.target,0).x,200);
close(camera.projectPoint(camera.target,1).x,600);
camera.compare=false;
camera.setFocus("mechanism");
camera.setView("side");
assert.equal(camera.mechanics,true);
camera.resetCamera();
assert.equal(camera.mechanics,true);
assert.equal(camera.getView(),"isometric");
close(camera.radius,2.75);
camera.setFocus("assembly");
assert.deepEqual(json(camera.getCamera()),initial);
assert.throws(()=>camera.setView("__proto__"));
assert.throws(()=>camera.setFocus("constructor"));
assert.throws(()=>camera.setView(["front"]));

// Panning changes the inspected target, never the simulated mechanism state.
camera.q=.7;camera.q2=.3;
const old=camera.getCamera();
camera.setCamera(camera.panCamera(50,20));
assert.notDeepEqual(json(camera.getCamera().target_m),json(old.target_m));
close(camera.radius,old.distance_m);
close(camera.q,.7);close(camera.q2,.3);
console.log("Camera contracts passed: atomic camera import, detached state, projective geometry, top view, comparison centring, focus reset and pan.");
