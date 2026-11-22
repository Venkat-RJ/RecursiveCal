/* Data and playback contracts. No dynamics are computed in the browser. */
(function (root) {
  "use strict";
  const finite = Number.isFinite;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const defaults = {mass_kg:25, motor_efficiency:1, gas_scale:1, friction_coulomb_Nm:6, sensor_bias_rad:0};
  const parameters = [
    ["mass_kg", "Hatch mass", "kg", 2],
    ["motor_efficiency", "Effective drive factor", "ratio", 3],
    ["gas_scale", "Gas assistance", "ratio", 3],
    ["friction_coulomb_Nm", "Coulomb friction", "N·m", 2],
    ["sensor_bias_rad", "Encoder offset", "rad", 4]
  ];
  const actions = {low_sweep:"Move to 20°", high_sweep:"Move to 60°", mid_sweep:"Move to 40°",
    hold:"Hold and observe", coast:"Release motor", reference:"Reference fixture"};
  const profiles = {full_open:"Full opening", full_close:"Full closing",
    partial_reverse:"Partial reversal", cold_open:"Cold opening"};
  const profileConditions = {full_open:"0 → 78° · 20°C", full_close:"78 → 0° · 20°C",
    partial_reverse:"64 → 27° · 20°C", cold_open:"0 → 78° · −10°C"};
  // Versioned protocol values, independent of the imported report's claims.
  const verificationProfiles = {full_open:[0,78,4.8,5.8,20], full_close:[78,0,5.6,6.6,20],
    partial_reverse:[64,27,3.1,4.1,20], cold_open:[0,78,5.2,6.2,-10]};
  const acceptanceLimits = {tracking_rmse_deg_max:3, final_error_deg_max:2,
    peak_speed_rad_s_max:1.15, saturation_fraction_max:.35};
  function canonical(value) {
    if (value === null) return ["null"];
    if (typeof value === "boolean") return ["bool", value];
    if (typeof value === "number") {
      if (!finite(value)) throw new Error("Evidence contains a nonfinite number.");
      const buffer = new DataView(new ArrayBuffer(8));
      buffer.setFloat64(0, value === 0 ? 0 : value, false);
      return ["number", Array.from(new Uint8Array(buffer.buffer), b => b.toString(16).padStart(2,"0")).join("")];
    }
    if (typeof value === "string") return ["string", value];
    if (Array.isArray(value)) return ["array", value.map(canonical)];
    if (value && typeof value === "object") return ["object", Object.keys(value).sort().map(k => [k, canonical(value[k])])];
    throw new Error("Unsupported evidence value.");
  }
  async function digest(value) {
    if (!root.crypto?.subtle) throw new Error("Evidence integrity checks require HTTPS or localhost.");
    const bytes = new TextEncoder().encode(JSON.stringify(canonical(value)));
    return Array.from(new Uint8Array(await root.crypto.subtle.digest("SHA-256", bytes)),
      b => b.toString(16).padStart(2,"0")).join("");
  }
  function validateRows(rows, required, allowEmpty = false) {
    if (!Array.isArray(rows) || (!allowEmpty && !rows.length) || rows.length > 250001)
      throw new Error("Invalid trace sample count.");
    let previous = -Infinity;
    for (const row of rows) {
      if (!row || !finite(row.time_s) || row.time_s < 0 || row.time_s <= previous)
        throw new Error("Trace times must be finite, nonnegative and strictly increasing.");
      if (!required.every(k => finite(row[k]))) throw new Error("A required trace signal is missing or nonfinite.");
      previous = row.time_s;
    }
  }
  function validateRun(run) {
    if (run?.schema_version !== "recursivecal.run/1" ||
        !["recursivecal.si-liftgate/1","recursivecal.si-liftgate/2","recursivecal.si-liftgate/3"].includes(run.model_id))
      throw new Error("Expected an SI liftgate simulation report.");
    validateRows(run.trace, ["angle_rad","target_angle_rad","velocity_rad_s","motor_force_N_each","gas_force_N_each","stroke_m"]);
    if (!run.parameters || typeof run.parameters !== "object" || !run.provenance || !run.metrics)
      throw new Error("Simulation parameters, metrics and provenance are required.");
    for (const value of Object.values(run.parameters)) if (!finite(value)) throw new Error("Invalid model parameter.");
    for (const key of ["tracking_rmse_deg","peak_speed_rad_s","mechanical_work_abs_J","force_saturation_fraction","completed_duration_s"])
      if (!finite(run.metrics[key])) throw new Error("Invalid simulation metric: " + key);
    if (typeof run.metrics.termination !== "string") throw new Error("The termination status is missing.");
    for (const event of run.events || []) if (!finite(event?.time_s) || typeof event.type !== "string")
      throw new Error("Invalid simulation event.");
    return run;
  }
  function validateMotion(run, {start,target,profileSeconds,duration,temperature,modelId,speedGuard,powerLoss=null,unpowered=false}) {
    const rows = run?.trace, m = run?.metrics;
    validateRows(rows, ["true_angle_rad","true_velocity_rad_s","true_motor_force_N_each","absolute_time_s",
      "angle_rad","target_angle_rad","velocity_rad_s","ambient_temperature_C","command_N_each"]);
    if (rows.length < 2 || rows[0].time_s !== 0)
      throw new Error("A verification trace must begin at zero and contain a completed interval.");
    const elapsed = rows.at(-1).time_s;
    if (!m || !["tracking_rmse_deg","final_error_deg","peak_speed_rad_s","saturation_fraction","completed_duration_s",
      "mechanical_work_abs_J","mechanical_work_signed_J"].every(key => finite(m[key])) ||
        m.tracking_rmse_deg < 0 || m.peak_speed_rad_s < 0 || m.mechanical_work_abs_J < 0 || m.saturation_fraction < 0 || m.saturation_fraction > 1)
      throw new Error("Invalid verification metric.");
    if (!finite(run.duration_s) || Math.abs(run.duration_s-duration) > 1e-9 || elapsed > duration+1e-9 ||
        Math.abs(elapsed-m.completed_duration_s) > 1e-9 ||
        (m.termination === "completed" && Math.abs(elapsed-duration) > 1e-9))
      throw new Error("Verification duration differs from the declared motion.");
    if (Math.abs(rows[0].true_angle_rad-start*Math.PI/180) > 1e-9 || Math.abs(rows[0].true_velocity_rad_s) > 1e-9)
      throw new Error("Verification initial state differs from the declared motion.");
    let integral = 0, saturatedTime = 0, lowerPeak = 0;
    const hasFlags = modelId === "recursivecal.physical-rig/3" || rows.some(row => Object.hasOwn(row,"force_saturated"));
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index], r = clamp(row.time_s/profileSeconds,0,1);
      const reference = start*Math.PI/180 + (target-start)*Math.PI/180*(10*r**3-15*r**4+6*r**5);
      if (Math.abs(row.target_angle_rad-reference) > 1e-9)
        throw new Error("Verification target trajectory differs from the declared motion.");
      if (Math.abs(row.absolute_time_s-row.time_s) > 1e-9 || Math.abs(row.ambient_temperature_C-temperature) > 1e-9)
        throw new Error("Verification trace time or temperature differs from the declared condition.");
      if ((unpowered || (powerLoss !== null && row.time_s > powerLoss+1e-9)) && Math.abs(row.command_N_each) > 1e-9)
        throw new Error("Verification command continues after power was removed.");
      lowerPeak = Math.max(lowerPeak,Math.abs(row.true_velocity_rad_s));
      if (hasFlags && typeof row.force_saturated !== "boolean")
        throw new Error("Interval saturation flags are missing or invalid.");
      if (index) {
        const previous = rows[index-1], dt = row.time_s-previous.time_s;
        integral += dt*(previous.target_angle_rad-previous.true_angle_rad)**2;
        if (hasFlags && row.force_saturated) saturatedTime += dt;
      }
    }
    // Legacy rigs may lack interval flags. Their recorded saturation is
    // retained as a provenance limitation, never inferred from force alone.
    if (hasFlags && Math.abs(saturatedTime/elapsed-m.saturation_fraction) > 1e-9)
      throw new Error("Verification saturation differs from the complete trace.");
    const rmse = Math.sqrt(integral/elapsed)*180/Math.PI;
    if (Math.abs(rmse-m.tracking_rmse_deg) > 1e-7)
      throw new Error("Verification tracking error differs from the complete trace.");
    if (Math.abs(target-rows.at(-1).true_angle_rad*180/Math.PI-m.final_error_deg) > 1e-7)
      throw new Error("Verification final error differs from the requested endpoint.");
    for (const [name,row] of [["initial_state",rows[0]],["final_state",rows.at(-1)]]) {
      const state = run[name];
      for (const [field,signal] of [["time_s","absolute_time_s"],["angle_rad","true_angle_rad"],
        ["velocity_rad_s","true_velocity_rad_s"],["motor_force_N_each","true_motor_force_N_each"]])
        if (!finite(state?.[field]) || Math.abs(state[field]-row[signal]) > 1e-9)
          throw new Error("Verification state snapshot differs from its trace endpoint.");
    }
    if (!finite(run.initial_state.mechanical_work_abs_J) || !finite(run.final_state.mechanical_work_abs_J) ||
        !finite(m.mechanical_work_abs_J) || m.mechanical_work_abs_J < 0 ||
        Math.abs(m.mechanical_work_abs_J-(run.final_state.mechanical_work_abs_J-run.initial_state.mechanical_work_abs_J)) > 1e-7)
      throw new Error("Verification absolute work differs from the state work change.");
    const workFields = ["left_shaft_work_J","right_shaft_work_J","coupling_residual_J"];
    if ([rows[0],rows.at(-1)].some(row => workFields.some(key => Object.hasOwn(row,key)))) {
      if (![rows[0],rows.at(-1)].every(row => workFields.every(key => finite(row[key]))) || !finite(m.mechanical_work_signed_J))
        throw new Error("Verification drive work telemetry is incomplete.");
      const delta = key => rows.at(-1)[key]-rows[0][key];
      if (Math.abs(m.mechanical_work_signed_J-(delta("left_shaft_work_J")+delta("right_shaft_work_J")-delta("coupling_residual_J"))) > 1e-7)
        throw new Error("Verification signed work differs from the drive telemetry.");
    }
    if (!Array.isArray(run.events)) throw new Error("Verification events are missing.");
    let impact = false;
    const kinds = new Set();
    for (const event of run.events) {
      if (!finite(event?.time_s) || event.time_s < -1e-9 || event.time_s > elapsed+1e-9 || typeof event.type !== "string")
        throw new Error("Verification event is outside the recorded motion.");
      kinds.add(event.type);
      if (["lower_stop","upper_stop"].includes(event.type)) {
        if (!finite(event.incident_speed_rad_s) || event.incident_speed_rad_s < 0)
          throw new Error("Invalid verification contact speed.");
        lowerPeak = Math.max(lowerPeak,event.incident_speed_rad_s);
        impact ||= event.incident_speed_rad_s > .12;
      }
    }
    // The trace bounds the peak from below; internal extrema need not
    // occur at exported sample times, so equality would reject valid runs.
    if (m.peak_speed_rad_s+1e-9 < lowerPeak)
      throw new Error("Verification peak speed is below a recorded speed.");
    if (kinds.has("speed_limit") !== (m.peak_speed_rad_s > speedGuard))
      throw new Error("Verification peak speed contradicts its speed guard event.");
    const losses = run.events.filter(event => event.type === "power_loss");
    const reachedLoss = powerLoss !== null && elapsed >= powerLoss;
    if (losses.length !== (reachedLoss ? 1 : 0) || (reachedLoss && Math.abs(losses[0].time_s-powerLoss) > 1e-9))
      throw new Error("Verification power-loss event differs from the declared schedule.");
    const termination = kinds.has("speed_limit") ? "aborted_speed_limit" : impact ? "aborted_stop_impact" :
      kinds.has("drive_trip") ? "aborted_drive_trip" : "completed";
    if (m.termination !== termination)
      throw new Error("Verification termination differs from recorded guard events.");
    return rmse;
  }
  function validatePassiveStatic(recorded, p, closingExtra) {
    // Static geometry and torque balance only. This never advances the plant.
    const fields = ["max_angle_rad","hatch_anchor_x_m","hatch_anchor_down_m","hinge_height_m",
      "body_anchor_x_m","body_anchor_z_m","gas_force_extended_N_each","gas_scale","temperature_C",
      "gas_reference_temperature_C","mass_kg","gravity_m_s2","com_radius_m","com_offset_rad",
      "external_closing_torque_Nm","friction_static_Nm","holding_brake_Nm"];
    if (!recorded || !fields.every(key => finite(p[key])) || !finite(closingExtra) || closingExtra < 0)
      throw new Error("Passive support requires the disclosed physical parameters.");
    const q = p.max_angle_rad, c = Math.cos(q), s = Math.sin(q);
    const x = p.hatch_anchor_x_m*c+p.hatch_anchor_down_m*s;
    const z = p.hinge_height_m+p.hatch_anchor_x_m*s-p.hatch_anchor_down_m*c;
    const dx = -p.hatch_anchor_x_m*s+p.hatch_anchor_down_m*c;
    const dz = p.hatch_anchor_x_m*c+p.hatch_anchor_down_m*s;
    const ux = x-p.body_anchor_x_m, uz = z-p.body_anchor_z_m;
    const arm = (ux*dx+uz*dz)/Math.hypot(ux,uz);
    const gas = 2*arm*p.gas_force_extended_N_each*p.gas_scale*(p.temperature_C+273.15)/(p.gas_reference_temperature_C+273.15);
    const gravity = p.mass_kg*p.gravity_m_s2*p.com_radius_m*Math.sin(q+p.com_offset_rad)+p.external_closing_torque_Nm;
    const deficit = gravity-gas, capacity = p.friction_static_Nm+closingExtra+p.holding_brake_Nm;
    const expected = {angle_deg:q*180/Math.PI,lever_m:arm,gas_opening_torque_Nm:gas,gravity_closing_torque_Nm:gravity,
      closing_torque_deficit_Nm:deficit,static_friction_and_brake_capacity_Nm:capacity,holding_margin_Nm:capacity-deficit,
      additional_holding_torque_required_Nm:Math.max(0,deficit-capacity),gas_force_for_gravity_balance_N_each:gravity/(2*arm)};
    if (!Object.entries(expected).every(([key,value]) => finite(value) && finite(recorded[key]) && Math.abs(recorded[key]-value) <= 1e-8) ||
        recorded.gas_alone_holds_open !== (deficit <= 1e-9) || recorded.can_hold_open_without_motor !== (deficit <= capacity+1e-9))
      throw new Error("Passive support differs from the disclosed static torque balance.");
  }
  function validateVerification(verification, modelId, truth) {
    const p = truth?.parameters;
    if (!p || !finite(p.speed_limit_rad_s) || p.speed_limit_rad_s <= 0 || !finite(p.max_angle_rad) || !finite(p.temperature_C))
      throw new Error("Verification requires the disclosed physical parameters.");
    const speedGuard = Math.min(1.15,p.speed_limit_rad_s);
    if (Object.hasOwn(verification,"model_id") && verification.model_id !== modelId)
      throw new Error("Verification model differs from the investigation.");
    const limits = verification.acceptance_limits;
    if (!limits || Object.keys(limits).length !== Object.keys(acceptanceLimits).length ||
        !Object.entries(acceptanceLimits).every(([key,value]) => limits[key] === value))
      throw new Error("Motion acceptance limits differ from the protocol.");
    const names = new Set(), rmses = {before:[], after:[]};
    for (const pair of verification.comparisons) {
      if (!Object.hasOwn(verificationProfiles, pair.name) || names.has(pair.name))
        throw new Error("Invalid verification profiles.");
      names.add(pair.name);
      const [start, target, profileSeconds, duration, temperature] = verificationProfiles[pair.name];
      if (pair.temperature_C !== temperature || pair.profile_duration_s !== profileSeconds)
        throw new Error("Verification conditions differ from the declared profile.");
      for (const side of ["before","after"]) {
        const run = pair[side];
        rmses[side].push(validateMotion(run,{start,target,profileSeconds,duration,temperature,modelId,speedGuard}));
        if (typeof run.accepted !== "boolean" || run.accepted !== accepted(run))
          throw new Error("Profile acceptance differs from the declared thresholds.");
      }
    }
    for (const side of ["before","after"]) {
      const mean = verification[side+"_mean_rmse_deg"];
      if (!finite(mean) || Math.abs(mean-rmses[side].reduce((sum,value) => sum+value,0)/4) > 1e-7)
        throw new Error("Mean tracking error differs from the complete traces.");
    }
    const passed = verification.comparisons.every(pair => accepted(pair.after));
    if (typeof verification.all_motion_profiles_passed !== "boolean" || verification.all_motion_profiles_passed !== passed)
      throw new Error("Overall motion acceptance differs from the individual profiles.");
    if (verification.hardware_validated !== false || verification.system_ready_for_hardware !== false)
      throw new Error("Synthetic verification cannot claim hardware readiness.");
    const hold = verification.passive_hold;
    validatePassiveStatic(hold?.static,p,truth.closing_friction_extra_Nm);
    const upper = p.max_angle_rad*180/Math.PI;
    validateMotion(hold.run,{start:upper,target:upper,profileSeconds:.8,duration:.8,
      temperature:p.temperature_C,modelId,speedGuard,unpowered:true});
    validateMotion(verification.power_loss,{start:55,target:70,profileSeconds:1.7,duration:2.2,
      temperature:p.temperature_C,modelId,speedGuard,powerLoss:.8});
    return passed;
  }
  async function validateReport(report) {
    if (report?.schema_version !== "recursivecal.physical-inquiry/1" ||
        !["recursivecal.physical-rig/1","recursivecal.physical-rig/2","recursivecal.physical-rig/3"].includes(report.model_id))
      throw new Error("Expected a physical investigation report.");
    if (!Array.isArray(report.agent_history) || report.agent_history.length > 6 ||
        !Array.isArray(report.diagnostics) || report.diagnostics.length !== report.agent_history.length ||
        !Array.isArray(report.verification?.comparisons) || report.verification.comparisons.length !== 4)
      throw new Error("The investigation structure is incomplete.");
    if (!["verified_in_simulation","verification_failed","abstained"].includes(report.outcome))
      throw new Error("Invalid investigation outcome.");
    const {report_sha256, ...payload} = report;
    if (await digest(payload) !== report_sha256) throw new Error("Report integrity check failed. The saved digest does not match.");
    if (await digest(report.agent_history) !== report.commitment?.history_sha256)
      throw new Error("The observations differ from the committed history.");
    const passed = validateVerification(report.verification,report.model_id,report.evaluator_only_truth);
    const disposition = report.commitment.disposition;
    if (!["candidate","abstain"].includes(disposition)) throw new Error("Invalid committed disposition.");
    const outcome = disposition === "candidate" ? (passed ? "verified_in_simulation" : "verification_failed") : "abstained";
    if (report.outcome !== outcome) throw new Error("Investigation outcome differs from independent verification.");
    for (const record of report.diagnostics)
      validateRows(record.trace, ["angle_rad","velocity_rad_s","strut_force_N_each"], true);
    for (const item of report.prediction_history || [])
      for (const candidate of item.candidates || [])
        validateRows(candidate.trace, ["angle_rad","velocity_rad_s","strut_force_N_each"], true);
    return report;
  }
  function sample(rows, time) {
    if (!rows?.length) return null;
    if (time <= rows[0].t) return {...rows[0], sampledAt:rows[0].t, ended:false};
    if (time >= rows.at(-1).t) return {...rows.at(-1), sampledAt:rows.at(-1).t, ended:time > rows.at(-1).t + 1e-9};
    let lo = 0, hi = rows.length - 1;
    while (hi - lo > 1) { const mid = (hi + lo) >> 1; if (rows[mid].t <= time) lo = mid; else hi = mid; }
    const a = rows[lo], b = rows[hi], weight = (time - a.t) / (b.t - a.t), result = {...a, t:time, sampledAt:time, ended:false};
    for (const key of Object.keys(a))
      if (finite(a[key]) && finite(b[key])) result[key] = a[key] + (b[key] - a[key]) * weight;
    return result;
  }
  function stepTime(rows, time, direction) {
    if (!rows?.length) return 0;
    if (direction > 0) return rows.find(r => r.t > time + 1e-8)?.t ?? rows.at(-1).t;
    return [...rows].reverse().find(r => r.t < time - 1e-8)?.t ?? rows[0].t;
  }
  function geometry(q, p = {}) {
    const hinge = p.hinge_height_m ?? 1.76, hx = p.hatch_anchor_x_m ?? .018, down = p.hatch_anchor_down_m ?? .3;
    const x = hx*Math.cos(q) + down*Math.sin(q), z = hinge + hx*Math.sin(q) - down*Math.cos(q);
    const dx = x - (p.body_anchor_x_m ?? -.47), dz = z - (p.body_anchor_z_m ?? 1.17);
    return {x, z, length:Math.hypot(dx,dz)};
  }
  function stroke(q, p) { return geometry(q,p).length - geometry(0,p).length; }
  function normalized(row, mode, p = {}) {
    // Investigation views never read true_* values, even from a sealed report.
    const q = mode === "simulation" ? row.angle_rad : mode === "verify" ? row.true_angle_rad : row.angle_rad;
    const telemetry = mode === "investigate" ? {} : Object.fromEntries(Object.entries(row).filter(([key,value]) =>
      (/^(left_|right_)/.test(key) || ["brake_engaged","sensor_age_s"].includes(key)) && (finite(value)||typeof value==="boolean")));
    return {...telemetry,t:row.time_s, q, angle:mode === "simulation" ? row.observed_angle_rad : row.angle_rad, target:row.target_angle_rad,
      velocity:mode === "verify" ? (row.true_velocity_rad_s ?? row.velocity_rad_s) : row.velocity_rad_s,
      drive:mode === "simulation" ? row.motor_force_N_each : undefined,
      command:mode === "simulation" ? row.requested_motor_force_N_each : undefined,
      gas:mode === "simulation" ? row.gas_force_N_each : undefined,
      force:row.strut_force_N_each, stroke:mode === "simulation" ? row.stroke_m : stroke(q,p),
      powered:row.motor_powered, saturated:row.force_saturated};
  }
  function diagnosticRows(report, index) {
    const record = report.agent_history[index], diagnostic = report.diagnostics[index];
    if (diagnostic?.trace?.length) return diagnostic.trace.map(r => normalized(r,"investigate"));
    if (!record) return [];
    // Fixture positioning is external. Show the acquired fixture readings,
    // not an invented trajectory between the previous and fixture positions.
    return (record.observations || []).map(r => normalized({...r,time_s:r.sample_time_s},"investigate"));
  }
  function publicRows(record) {
    const rows = record.action === "reference" ? [] : [{...record.start_observation,time_s:0}];
    for (const row of record.observations || []) rows.push({...row,time_s:row.sample_time_s});
    return rows.map(r => normalized(r,"investigate"));
  }
  function acceptance(run) {
    const m = run.metrics;
    return [
      {label:"Completed", value:m.termination === "completed" ? "Yes" : m.termination.replaceAll("_"," "), limit:"Required", pass:m.termination === "completed"},
      {label:"Tracking RMSE", value:m.tracking_rmse_deg, unit:"°", limit:"≤ 3.0°", pass:m.tracking_rmse_deg <= 3},
      {label:"Final error", value:Math.abs(m.final_error_deg), unit:"°", limit:"≤ 2.0°", pass:Math.abs(m.final_error_deg) <= 2},
      {label:"Peak speed", value:m.peak_speed_rad_s, unit:" rad/s", limit:"≤ 1.15 rad/s", pass:m.peak_speed_rad_s <= 1.15},
      {label:"Saturation time", value:m.saturation_fraction*100, unit:"%", limit:"≤ 35%", pass:m.saturation_fraction <= .35}
    ];
  }
  function accepted(run) { return acceptance(run).every(check => check.pass); }
  function csvCell(value) {
    let s = value == null || (typeof value === "number" && !finite(value)) ? "" : String(value);
    if (/^[=+@]/.test(s) || (/^-/.test(s) && !finite(Number(s)))) s = "'" + s;
    return /[",\r\n]/.test(s) ? '"' + s.replaceAll('"','""') + '"' : s;
  }
  function traceCsv(rows) {
    const fields = [["t","time_s"],["angle","observed_angle_rad"],["q","display_angle_rad"],["target","target_angle_rad"],
      ["velocity","velocity_rad_s"],["drive","modeled_drive_force_N_each"],["command","command_N_each"],
      ["gas","gas_force_N_each"],["force","observed_strut_force_N_each"],["stroke","derived_stroke_m"]];
    for (const side of ["left","right"]) for (const suffix of ["current_A","voltage_V","motor_speed_rad_s","temperature_C","force_N","rotor_angle_rad","electrical_energy_J"]) fields.push([side+"_"+suffix,side+"_"+suffix]);
    fields.push(["sensor_age_s","sensor_age_s"]);
    const present = fields.filter(([key]) => rows.some(row => finite(row[key])));
    return present.map(([,label]) => label).join(",") + "\n" +
      rows.map(row => present.map(([key]) => csvCell(row[key])).join(",")).join("\n") + "\n";
  }
  const api = {clamp, defaults, parameters, actions, profiles, profileConditions, canonical, digest, validateRows,
    validateRun, validateReport, sample, stepTime, geometry, stroke, normalized, diagnosticRows, publicRows, acceptance, accepted, csvCell, traceCsv};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.RecursiveWorkspace = api;
})(typeof window !== "undefined" ? window : globalThis);
