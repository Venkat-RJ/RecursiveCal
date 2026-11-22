"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");
if (!globalThis.crypto) globalThis.crypto = require("node:crypto").webcrypto;
const C = require("../recursivecal_lab/web/workspace-core.js");
const rows = [{t:0,q:0,command:10,powered:true},{t:.07,q:.14,command:20,powered:false},{t:.21,q:.35,command:30,powered:false}];
assert.equal(C.sample(rows,.035).q,.07);
assert.equal(C.sample(rows,.035).powered,true);
assert.equal(C.sample(rows,.07).powered,false);
assert.equal(C.sample(rows,5).q,.35);
assert.equal(C.sample(rows,5).ended,true);
assert.equal(C.sample(rows,-1).q,0);
assert.equal(C.stepTime(rows,.035,1),.07);
assert.equal(C.stepTime(rows,.035,-1),0);
assert.equal(C.stepTime(rows,.07,1),.21);
assert.equal(C.stepTime(rows,.21,1),.21);
assert.equal(C.sample([],0),null);
const secret = {time_s:0,angle_rad:.4,true_angle_rad:.7,velocity_rad_s:.2,true_velocity_rad_s:.9,
  true_motor_force_N_each:500,motor_force_N_each:450,strut_force_N_each:123,command_N_each:300};
const observed=C.normalized(secret,"investigate");
assert.equal(observed.q,.4);
assert.equal(observed.velocity,.2);
assert.equal(observed.force,123);
assert.equal(observed.drive,undefined);
assert.equal(observed.command,undefined);
const driveTruth={...secret,left_current_A:4.2,right_current_A:3.1,left_temperature_C:42,sensor_age_s:.01};
assert.equal(C.normalized(driveTruth,"investigate").left_current_A,undefined);
assert.equal(C.normalized(driveTruth,"verify").left_current_A,4.2);
assert.equal(C.sample([{t:0,left_current_A:2},{t:.1,left_current_A:4}],.025).left_current_A,2.5);
assert.ok(C.traceCsv([C.normalized(driveTruth,"verify")]).includes("left_current_A"));
assert.ok(!JSON.stringify(observed).includes("true_"));
assert.equal(C.normalized(secret,"verify").q,.7);
const biased = C.normalized({...secret,angle_rad:.7,observed_angle_rad:.4},"simulation");
assert.equal(biased.q,.7);
assert.equal(biased.angle,.4);
const exported = C.traceCsv([biased]).trim().split("\n");
const columns = exported[0].split(","), values = exported[1].split(",");
assert.equal(Number(values[columns.indexOf("observed_angle_rad")]),.4);
assert.equal(Number(values[columns.indexOf("display_angle_rad")]),.7);
assert.equal(C.stroke(0),0);
assert.ok(C.stroke(1)>.1);
const good={metrics:{termination:"completed",tracking_rmse_deg:3,final_error_deg:-2,peak_speed_rad_s:1.15,saturation_fraction:.35}};
assert.equal(C.accepted(good),true);
for(const [key,value] of [["tracking_rmse_deg",3.01],["final_error_deg",-2.01],["peak_speed_rad_s",1.151],["saturation_fraction",.351],["termination","aborted_speed_limit"]])
  assert.equal(C.accepted({metrics:{...good.metrics,[key]:value}}),false,key);
assert.throws(()=>C.validateRows([{time_s:1,q:0},{time_s:1,q:1}],["q"]),/strictly/);
assert.throws(()=>C.validateRows([{time_s:0,q:NaN}],["q"]),/nonfinite/);
assert.equal(C.csvCell("=IMPORTXML()"),"'=IMPORTXML()");
assert.equal(C.csvCell(-3),"-3");
assert.equal(C.csvCell('a,"b"'),'"a,""b"""');
assert.ok(!C.traceCsv([observed]).includes("modeled_drive"));
assert.ok(C.traceCsv([observed]).includes("observed_strut_force_N_each"));

function recordedReference(filename, variable) {
  const source = fs.readFileSync(path.join(__dirname,"../recursivecal_lab/web",filename),"utf8");
  const match = source.match(new RegExp("window\\."+variable+' = "([A-Za-z0-9+/=]+)";'));
  assert.ok(match,"Missing recorded reference: "+filename);
  return JSON.parse(zlib.gunzipSync(Buffer.from(match[1],"base64")).toString("utf8"));
}
function archivedReport(name) {
  const file = path.join(__dirname,"../research/releases/physical-inquiry-v1",name+"-bayes-seed7.json.gz");
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(file)).toString("utf8"));
}
async function rehashedRejection(report, edit, expected) {
  const changed = structuredClone(report);
  edit(changed);
  const {report_sha256, ...payload} = changed;
  changed.report_sha256 = await C.digest(payload);
  await assert.rejects(C.validateReport(changed),expected);
}
async function importContracts() {
  const current = recordedReference("workspace-reference.js","RecursiveWorkspaceReference").investigation;
  const archived = recordedReference("inquiry-reference.js","RecursiveCalInquiryReferenceGzip");
  const failed = archivedReport("compound"), guarded = archivedReport("overload");
  assert.equal(current.model_id,"recursivecal.physical-rig/3");
  assert.equal(archived.model_id,"recursivecal.physical-rig/1");
  for (const report of [current,archived])
    assert.equal(await C.validateReport(report),report);
  const archiveDirectory = path.join(__dirname,"../research/releases/physical-inquiry-v1");
  const archiveFiles = fs.readdirSync(archiveDirectory).filter(name => name.endsWith(".json.gz")).sort();
  assert.ok(archiveFiles.length > 0,"Historical inquiry evidence is missing.");
  for (const filename of archiveFiles) {
    const report = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(archiveDirectory,filename))).toString("utf8"));
    assert.equal(await C.validateReport(report),report,filename);
  }
  assert.equal(failed.outcome,"verification_failed");
  const cold = failed.verification.comparisons.find(pair => pair.name === "cold_open").after;
  assert.ok(cold.metrics.final_error_deg > 2);
  assert.equal(cold.accepted,false);

  // Regression: changing the digest as well as the failed outcome must not
  // promote the unchanged cold-opening trace into a successful calibration.
  await rehashedRejection(failed, report => {
    const run = report.verification.comparisons.find(pair => pair.name === "cold_open").after;
    run.metrics.final_error_deg = 0;
    run.accepted = true;
    report.verification.all_motion_profiles_passed = true;
    report.outcome = "verified_in_simulation";
  },/final error/);
  await rehashedRejection(failed, report => {report.outcome="verified_in_simulation";},/outcome/);
  await rehashedRejection(failed, report => {
    report.verification.comparisons.find(pair => pair.name === "cold_open").after.accepted=true;
  },/Profile acceptance/);
  await rehashedRejection(archived, report => {report.verification.acceptance_limits.final_error_deg_max=100;},/acceptance limits/);
  await rehashedRejection(archived, report => {report.verification.comparisons[0].temperature_C=-10;},/conditions/);
  await rehashedRejection(archived, report => {report.verification.comparisons[0].after.duration_s=5.7;},/duration/);
  await rehashedRejection(archived, report => {
    report.verification.comparisons[0].after.trace[1].target_angle_rad+=.001;
  },/target trajectory/);
  await rehashedRejection(archived, report => {report.verification.comparisons[0].after.metrics.tracking_rmse_deg=0;},/tracking error/);
  await rehashedRejection(archived, report => {report.verification.after_mean_rmse_deg=0;},/Mean tracking error/);
  await rehashedRejection(archived, report => {report.verification.comparisons[0].after.metrics.peak_speed_rad_s=0;},/peak speed/);
  await rehashedRejection(guarded, report => {
    report.verification.comparisons.find(pair => pair.name === "full_close").after.events=[];
  },/termination/);
  await rehashedRejection(current, report => {
    delete report.verification.comparisons[0].after.trace[1].force_saturated;
  },/saturation flags/);
  await rehashedRejection(current, report => {report.verification.comparisons[0].after.metrics.saturation_fraction=.1;},/saturation differs/);
  await rehashedRejection(archived, report => {report.verification.hardware_validated=true;},/hardware readiness/);
  await rehashedRejection(archived, report => {
    report.verification.comparisons[0].before.metrics.peak_speed_rad_s=1.2;
  },/speed guard/);
  await rehashedRejection(archived, report => {
    report.verification.comparisons[0].after.final_state.angle_rad+=.1;
  },/state snapshot/);
  await rehashedRejection(archived, report => {
    report.verification.passive_hold.static.holding_margin_Nm=1;
    report.verification.passive_hold.static.can_hold_open_without_motor=true;
    report.verification.passive_hold.static.additional_holding_torque_required_Nm=0;
  },/static torque balance/);
  await rehashedRejection(archived, report => {report.verification.passive_hold.run.metrics.final_error_deg=0;},/final error/);
  await rehashedRejection(archived, report => {report.verification.power_loss.metrics.tracking_rmse_deg=0;},/tracking error/);
  await rehashedRejection(archived, report => {report.verification.power_loss.events=[];},/power-loss event/);
  await rehashedRejection(archived, report => {
    report.verification.power_loss.trace.at(-1).command_N_each=10;
  },/power was removed/);
  await rehashedRejection(current, report => {
    report.verification.power_loss.metrics.mechanical_work_signed_J+=1;
  },/signed work/);
  console.log(`Workspace contracts passed: playback, observations, CSV, current and ${archiveFiles.length} archived imports, and 22 rehashed evidence rejections.`);
}
importContracts().catch(error => {console.error(error);process.exitCode=1;});
