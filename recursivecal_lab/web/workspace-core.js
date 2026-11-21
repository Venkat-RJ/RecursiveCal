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
        !["recursivecal.si-liftgate/1","recursivecal.si-liftgate/2"].includes(run.model_id))
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
  async function validateReport(report) {
    if (report?.schema_version !== "recursivecal.physical-inquiry/1" ||
        !["recursivecal.physical-rig/1","recursivecal.physical-rig/2"].includes(report.model_id))
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
    const names = new Set();
    for (const pair of report.verification.comparisons) {
      if (!profiles[pair.name] || names.has(pair.name)) throw new Error("Invalid verification profiles.");
      names.add(pair.name);
      for (const side of ["before","after"]) {
        validateRows(pair[side]?.trace, ["true_angle_rad","angle_rad","target_angle_rad","velocity_rad_s"]);
        for (const key of ["tracking_rmse_deg","final_error_deg","peak_speed_rad_s","saturation_fraction"])
          if (!finite(pair[side].metrics?.[key])) throw new Error("Invalid verification metric.");
      }
    }
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
    return {t:row.time_s, q, angle:row.angle_rad, target:row.target_angle_rad,
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
    const present = fields.filter(([key]) => rows.some(row => finite(row[key])));
    return present.map(([,label]) => label).join(",") + "\n" +
      rows.map(row => present.map(([key]) => csvCell(row[key])).join(",")).join("\n") + "\n";
  }
  const api = {clamp, defaults, parameters, actions, profiles, profileConditions, canonical, digest, validateRows,
    validateRun, validateReport, sample, stepTime, geometry, stroke, normalized, diagnosticRows, publicRows, acceptance, accepted, csvCell, traceCsv};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.RecursiveWorkspace = api;
})(typeof window !== "undefined" ? window : globalThis);
