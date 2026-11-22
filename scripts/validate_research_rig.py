"""Independent numerical audit of the declared electromechanical research rig.

Run in the foreground with the validation extra installed:
    python scripts/validate_research_rig.py --output artifacts/research-rig-validation.json

The reference equations rederive geometry, forces, current control and heat.
They do not call production force, geometry, electrical or integration helpers.
This verifies a bounded synthetic model. It is not measured hardware validation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from recursivecal_lab.inquiry import ACCEPTANCE
from recursivecal_lab.physical_rig import Calibration, RigState, run_motion
from recursivecal_lab.physics import ModelParameters
from recursivecal_lab.research_rig import MODEL_ID, DriveParameters, ResearchRig, SensorParameters


# Engineering regression limits selected before running this audit. The angular
# limit is below the declared noisy encoder's 0.002 rad standard deviation.
# These are not hardware-accuracy requirements or statistical coverage bounds.
LIMITS = {
    "angle_error_deg": 0.05,
    "velocity_error_rad_s": 0.005,
    "current_error_A": 0.05,
    "temperature_error_C": 0.05,
    "energy_absolute_J": 0.002,
    "energy_relative": 0.002,
    "electrical_identity_relative": 1e-8,
    "reference_energy_relative": 1e-8,
    "minimum_finest_refinement": 1.3,
}
STATE_COLUMNS = ["angle_rad", "velocity_rad_s", "left_current_A", "right_current_A",
                 "left_temperature_C", "right_temperature_C"]
TRACE_COLUMNS = ["time_s", "true_angle_rad", "true_velocity_rad_s", "angle_rad",
                 "velocity_rad_s", "strut_force_N_each", "sensor_sample_time_s", "sensor_age_s",
                 "left_current_A", "right_current_A", "left_temperature_C", "right_temperature_C",
                 "left_voltage_V", "right_voltage_V", "brake_engaged", "force_saturated"]
SOURCE_FILES = ("recursivecal_lab/physics.py", "recursivecal_lab/physical_rig.py", "recursivecal_lab/research_rig.py",
                "recursivecal_lab/inquiry.py", "recursivecal_lab/research_simulation.py", "scripts/validate_research_rig.py")


def source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def reference_geometry(angle: float, p: ModelParameters) -> tuple[float, float]:
    """Rotate the hatch mount, then differentiate its distance to the body mount."""
    c, s = math.cos(angle), math.sin(angle)
    radial_x = c * p.hatch_anchor_x_m + s * p.hatch_anchor_down_m
    radial_z = s * p.hatch_anchor_x_m - c * p.hatch_anchor_down_m
    dx = radial_x - p.body_anchor_x_m
    dz = radial_z + p.hinge_height_m - p.body_anchor_z_m
    length = math.hypot(dx, dz)
    return length, (dx * -radial_z + dz * radial_x) / length


def reference_gas(length: float, p: ModelParameters) -> float:
    short = reference_geometry(0, p)[0]
    long = reference_geometry(p.max_angle_rad, p)[0]
    fraction = (length - short) / (long - short)
    return (p.gas_scale * (p.temperature_C + 273.15) / (p.gas_reference_temperature_C + 273.15)
            * (p.gas_force_compressed_N_each * (1 - fraction) + p.gas_force_extended_N_each * fraction))


def reference_energy(angle: float, velocity: float, p: ModelParameters) -> float:
    """Mechanical potential plus kinetic energy, independently integrating gas force."""
    short = reference_geometry(0, p)[0]
    long = reference_geometry(p.max_angle_rad, p)[0]
    length = reference_geometry(angle, p)[0]
    delta = length - short
    temperature = (p.temperature_C + 273.15) / (p.gas_reference_temperature_C + 273.15)
    slope = (p.gas_force_extended_N_each - p.gas_force_compressed_N_each) / (long - short)
    gas_potential = -2 * p.gas_scale * temperature * (
        p.gas_force_compressed_N_each * delta + .5 * slope * delta * delta)
    return (.5 * p.inertia_kg_m2 * velocity * velocity
            - p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.cos(angle + p.com_offset_rad)
            + p.external_closing_torque_Nm * angle + gas_potential)


def reference_drive(state: np.ndarray, p: ModelParameters, d: DriveParameters,
                    gains: tuple[float, float], command: float):
    ratio = math.tau * d.gear_ratio / d.screw_lead_m
    length, arm = reference_geometry(float(state[0]), p)
    speed = ratio * arm * state[1]
    data = []
    for side, gain in enumerate(gains):
        current, integral, temperature = state[2 + side], state[4 + side], state[6 + side]
        resistance = d.resistance_ohm * max(.2, 1 + d.resistance_temperature_coefficient_K * (temperature - 20))
        kt = d.torque_constant_Nm_A * p.motor_efficiency * gain
        limit = d.max_current_A * max(0, min(1, (d.trip_temperature_C - temperature)
                                            / (d.trip_temperature_C - d.derate_start_C)))
        target = max(-limit, min(limit, command / (d.torque_constant_Nm_A * ratio)))
        error = target - current
        desired_voltage = (d.resistance_ohm * target + d.torque_constant_Nm_A * speed
                           + d.current_kp_ohm * error + integral)
        voltage = max(-d.supply_voltage_V, min(d.supply_voltage_V, desired_voltage))
        integrating = not ((desired_voltage > d.supply_voltage_V and error > 0)
                           or (desired_voltage < -d.supply_voltage_V and error < 0))
        data.append({"current": current, "resistance": resistance, "kt": kt,
                     "voltage": voltage, "desired_voltage": desired_voltage,
                     "current_limit": limit, "force": ratio * kt * current,
                     "current_derivative": (voltage - kt * speed - resistance * current) / d.inductance_H,
                     "integral_derivative": d.current_ki_ohm_s * error if integrating else 0.0,
                     "temperature_derivative": (current * current * resistance
                         - (temperature - p.temperature_C) / d.thermal_resistance_K_W) / d.coil_heat_capacity_J_K,
                     "terminal_power": voltage * current, "copper_power": resistance * current * current,
                     "shaft_power": kt * speed * current})
    return length, arm, data


def reference_rhs(p: ModelParameters, d: DriveParameters, gains: tuple[float, float], command: float):
    def rhs(_time, state):
        length, arm, motors = reference_drive(state, p, d, gains, command)
        velocity = state[1]
        gravity = p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.sin(state[0] + p.com_offset_rad)
        damping = p.friction_viscous_Nm_s + 2 * p.strut_damping_N_s_m_each * arm * arm
        acceleration = ((motors[0]["force"] + motors[1]["force"] + 2 * reference_gas(length, p)) * arm
                        - gravity - p.external_closing_torque_Nm - damping * velocity) / p.inertia_kg_m2
        return [velocity, acceleration,
                *(m["current_derivative"] for m in motors), *(m["integral_derivative"] for m in motors),
                *(m["temperature_derivative"] for m in motors),
                *(m["terminal_power"] for m in motors), *(m["copper_power"] for m in motors),
                *(m["shaft_power"] for m in motors), damping * velocity * velocity]
    return rhs


def independent_reference(case: dict) -> dict:
    p, d, gains = case["parameters"], case["drive"], case["side_effectiveness"]
    initial = np.array([*case["initial"], 0., 0., 0., 0., p.temperature_C, p.temperature_C, *([0.] * 7)])
    states, times = [initial], [0.0]
    finite_interior = True
    energy_errors = []
    initial_energy = reference_energy(initial[0], initial[1], p)
    for index, command in enumerate(case["commands"]):
        begin, end = index * .04, (index + 1) * .04
        solution = solve_ivp(reference_rhs(p, d, gains, command), (begin, end), states[-1],
                             method="DOP853", rtol=2e-11, atol=2e-12, max_step=.001, dense_output=True)
        if not solution.success:
            raise RuntimeError(solution.message)
        for t in np.linspace(begin, end, 25):
            state = solution.sol(t)
            _, _, drives = reference_drive(state, p, d, gains, command)
            finite_interior = finite_interior and bool(
                np.isfinite(state).all() and .01 < state[0] < p.max_angle_rad - .01
                and all(abs(m["desired_voltage"]) < d.supply_voltage_V - .001
                        and abs(m["current"]) < m["current_limit"] - .001 for m in drives))
            magnetic = .5 * d.inductance_H * (state[2]**2 + state[3]**2)
            mechanical_delta = reference_energy(state[0], state[1], p) - initial_energy
            defect = state[8] + state[9] - state[10] - state[11] - magnetic - mechanical_delta - state[14]
            scale = 1 + abs(state[8]) + abs(state[9]) + abs(mechanical_delta)
            energy_errors.append(abs(float(defect)) / scale)
        states.append(solution.y[:, -1])
        times.append(end)
    return {"times_s": times, "full_states": np.asarray(states), "finite_smooth_interior": finite_interior,
            "relative_energy_defect_max": max(energy_errors)}


def compact_state(rig: ResearchRig) -> list[float]:
    t = rig.telemetry()
    return [rig.state.angle_rad, rig.state.velocity_rad_s, t["left_current_A"], t["right_current_A"],
            t["left_temperature_C"], t["right_temperature_C"]]


def production_case(case: dict, refinement: int) -> dict:
    p, d = case["parameters"], case["drive"]
    sensors = replace(SensorParameters(), command_delay_s=0, latency_s=0,
                      angle_noise_std_rad=0, velocity_noise_std_rad_s=0, force_noise_std_N=0)
    rig = ResearchRig(p, drive=d, sensors=sensors, side_effectiveness=case["side_effectiveness"],
                      state=RigState(angle_rad=case["initial"][0], velocity_rad_s=case["initial"][1]))
    effective = rig.metadata()["effective_internal_step_s"]
    # Constant commands are unchanged under refinement. Shorter outer steps also
    # refine the adaptive stiff cases below the user-configurable maximum step.
    outer = .01 if refinement == 1 else effective / refinement
    states = [compact_state(rig)]
    friction = impact = mechanical_work = 0.0
    contacts = 0
    saturated = tripped = False
    initial_energy = reference_energy(rig.state.angle_rad, rig.state.velocity_rad_s, p)
    for index, command in enumerate(case["commands"]):
        end = (index + 1) * .04
        while rig.state.time_s < end - 1e-13:
            step = rig.advance(command, min(outer, end - rig.state.time_s))
            friction += step["friction_dissipation_J"]
            impact += step["impact_dissipation_J"]
            mechanical_work += step["mechanical_work_signed_J"]
            contacts += len(step["contacts"])
            saturated = saturated or step["saturated"]
            tripped = tripped or step["drive_trip"]
        states.append(compact_state(rig))
    telemetry = rig.telemetry()
    electrical = sum(telemetry[side + "_electrical_energy_J"] for side in ("left", "right"))
    copper = sum(telemetry[side + "_copper_loss_J"] for side in ("left", "right"))
    dump = sum(telemetry[side + "_dump_loss_J"] for side in ("left", "right"))
    magnetic = sum(telemetry[side + "_inductive_energy_J"] for side in ("left", "right"))
    shaft = sum(telemetry[side + "_shaft_work_J"] for side in ("left", "right"))
    mechanical_delta = reference_energy(rig.state.angle_rad, rig.state.velocity_rad_s, p) - initial_energy
    defect = electrical - copper - dump - magnetic - mechanical_delta - friction - impact
    scale = max(abs(electrical), abs(mechanical_delta), abs(shaft), 1e-12)
    return {"refinement": refinement, "requested_internal_step_s": d.integration_dt_s,
            "effective_initial_internal_step_s": effective, "outer_command_step_s": outer,
            "states": states, "contacts": contacts, "drive_trip": tripped, "saturated": saturated,
            "energy": {"terminal_J": electrical, "copper_J": copper, "dump_J": dump,
                       "magnetic_J": magnetic, "shaft_work_J": shaft, "mechanical_work_J": mechanical_work,
                       "mechanical_energy_change_J": mechanical_delta, "friction_J": friction, "impact_J": impact,
                       "coupling_residual_J": telemetry["coupling_residual_J"], "total_defect_J": defect,
                       "electrical_identity_defect_J": electrical - copper - dump - magnetic - shaft,
                       "scale_J": scale}}


def smooth_cases() -> list[dict]:
    bare = replace(ModelParameters(), gravity_m_s2=0, gas_force_extended_N_each=0,
                   gas_force_compressed_N_each=0, friction_coulomb_Nm=0, friction_static_Nm=0,
                   friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0)
    drive = DriveParameters()
    cases = []
    def add(name, p=bare, d=drive, initial=(.5, 0.), gains=(1., 1.), commands=(50.,) * 5):
        cases.append({"name": name, "parameters": p, "drive": d, "initial": initial,
                      "side_effectiveness": gains, "commands": commands})
    add("nominal_dc_coupling")
    add("bidirectional_current", initial=(.65, .1), commands=(30., -60., -60., 30., 30.))
    add("asymmetric_motor_constants", p=replace(bare, mass_kg=28, inertia_kg_m2=13,
        motor_efficiency=.82, friction_viscous_Nm_s=2, strut_damping_N_s_m_each=3),
        initial=(.7, -.05), gains=(.65, 1.), commands=(50., 70., 80., 50., 0.))
    add("gravity_gas_damping_cold", p=replace(ModelParameters(), friction_coulomb_Nm=0,
        friction_static_Nm=0, gas_scale=.9, temperature_C=-10), initial=(.65, .05), commands=(50.,) * 5)
    add("stiff_current_loop", d=replace(drive, current_kp_ohm=2, current_ki_ohm_s=100,
        inductance_H=.001), commands=(30.,) * 5)
    add("stiff_transmission", d=replace(drive, torque_constant_Nm_A=.05, gear_ratio=20,
        screw_lead_m=.006), commands=(1.,) * 5)
    add("hot_high_resistance", p=replace(bare, temperature_C=50), d=replace(drive,
        resistance_ohm=2, inductance_H=.001, current_kp_ohm=2, current_ki_ohm_s=100), commands=(30.,) * 5)
    return cases


def accepted(run: dict) -> bool:
    m = run["metrics"]
    return (m["termination"] == "completed" and m["tracking_rmse_deg"] <= ACCEPTANCE["tracking_rmse_deg_max"]
            and abs(m["final_error_deg"]) <= ACCEPTANCE["final_error_deg_max"]
            and m["peak_speed_rad_s"] <= ACCEPTANCE["peak_speed_rad_s_max"]
            and m["saturation_fraction"] <= ACCEPTANCE["saturation_fraction_max"])


def trace_checks(run: dict, latency: float) -> dict:
    rows = run["trace"]
    finite = all(not isinstance(value, (float, int)) or math.isfinite(value)
                 for row in rows for value in row.values())
    causal = all(row["sensor_sample_time_s"] <= row["absolute_time_s"] + 1e-10
                 and row["sensor_age_s"] >= -1e-10
                 and abs(row["sensor_age_s"] - (row["absolute_time_s"] - row["sensor_sample_time_s"])) < 1e-8
                 and (row["sensor_sample_time_s"] == 0 or row["sensor_age_s"] >= latency - 1e-9)
                 for row in rows)
    timestamps = all(b["time_s"] > a["time_s"] for a, b in zip(rows, rows[1:]))
    residual = 0.0
    for row in rows:
        for side in ("left", "right"):
            energy = row[side + "_electrical_energy_J"]
            terms = [row[side + suffix] for suffix in ("_copper_loss_J", "_dump_loss_J", "_shaft_work_J")]
            magnetic = row[side + "_inductive_energy_J"] - row[side + "_initial_inductive_energy_J"]
            residual = max(residual, abs(energy - sum(terms) - magnetic) / (1 + abs(energy) + sum(abs(v) for v in terms)))
    return {"finite": finite, "sensor_causal": causal, "timestamps_increase": timestamps,
            "electrical_identity_relative_max": residual,
            "electrical_identity_passed": residual <= LIMITS["electrical_identity_relative"]}


def recorded_motion(run: dict, parameters: ModelParameters, rig: ResearchRig, seed: int) -> dict:
    return {"parameters": asdict(parameters), "drive": asdict(rig.drive), "sensors": asdict(rig.sensors),
            "side_effectiveness": list(rig.side_effectiveness), "seed": seed,
            "accepted": accepted(run), "metrics": run["metrics"], "events": run["events"],
            "checks": trace_checks(run, rig.sensors.latency_s), "trace_columns": TRACE_COLUMNS,
            "trace": [[row.get(key) for key in TRACE_COLUMNS] for row in run["trace"]]}


def run_audit() -> dict:
    began = time.monotonic()
    before_hashes = source_hashes()
    records = []
    gates = {}
    print("Comparing seven coupled DC-drive mechanisms with independent DOP853 equations.", flush=True)
    for case in smooth_cases():
        reference = independent_reference(case)
        truth = reference["full_states"][:, [0, 1, 2, 3, 6, 7]]
        trials = []
        for refinement in (1, 2, 4):
            trial = production_case(case, refinement)
            delta = np.max(np.abs(np.asarray(trial["states"]) - truth), axis=0)
            trial["errors"] = {"angle_deg": float(np.degrees(delta[0])), "velocity_rad_s": float(delta[1]),
                               "current_A": float(max(delta[2:4])), "temperature_C": float(max(delta[4:6]))}
            trial["normalized_state_error"] = max(
                trial["errors"]["angle_deg"] / LIMITS["angle_error_deg"],
                trial["errors"]["velocity_rad_s"] / LIMITS["velocity_error_rad_s"],
                trial["errors"]["current_A"] / LIMITS["current_error_A"],
                trial["errors"]["temperature_C"] / LIMITS["temperature_error_C"])
            trials.append(trial)
        row = {"name": case["name"], "parameters": asdict(case["parameters"]), "drive": asdict(case["drive"]),
               "side_effectiveness": case["side_effectiveness"], "initial_state": case["initial"],
               "commands_N_each": case["commands"], "command_interval_s": .04,
               "comparison_times_s": reference["times_s"], "state_columns": STATE_COLUMNS,
               "reference_states": truth.tolist(), "reference_energy_relative_max": reference["relative_energy_defect_max"],
               "reference_stays_smooth": reference["finite_smooth_interior"], "trials": trials}
        records.append(row)
        print(f"  {case['name']}: default angle error {trials[0]['errors']['angle_deg']:.6f} deg; "
              f"energy defect {trials[0]['energy']['total_defect_J']:.6g} J", flush=True)
    gates["independent_reference_stays_in_declared_smooth_scope"] = all(r["reference_stays_smooth"] for r in records)
    gates["independent_reference_energy_identity"] = all(r["reference_energy_relative_max"] <= LIMITS["reference_energy_relative"] for r in records)
    gates["default_coupled_state_errors_within_limits"] = all(r["trials"][0]["normalized_state_error"] <= 1 for r in records)
    gates["smooth_production_has_no_unexpected_contact_or_trip"] = all(
        trial["contacts"] == 0 and not trial["drive_trip"] and not trial["saturated"]
        for r in records for trial in r["trials"])
    gates["default_total_energy_defect_within_limits"] = all(
        abs(r["trials"][0]["energy"]["total_defect_J"]) <= LIMITS["energy_absolute_J"]
        + LIMITS["energy_relative"] * r["trials"][0]["energy"]["scale_J"] for r in records)
    gates["coupled_state_error_improves_under_refinement"] = all(
        r["trials"][-1]["normalized_state_error"] <= max(1e-5, r["trials"][0]["normalized_state_error"] / LIMITS["minimum_finest_refinement"])
        and all(b["normalized_state_error"] <= max(1e-5, a["normalized_state_error"])
                for a, b in zip(r["trials"], r["trials"][1:]))
        for r in records)
    gates["energy_defect_improves_under_refinement"] = all(
        abs(r["trials"][-1]["energy"]["total_defect_J"]) <= max(1e-7, abs(r["trials"][0]["energy"]["total_defect_J"]) / LIMITS["minimum_finest_refinement"])
        and all(abs(b["energy"]["total_defect_J"]) <= max(1e-7, abs(a["energy"]["total_defect_J"]))
                for a, b in zip(r["trials"], r["trials"][1:]))
        for r in records)

    print("Checking healthy opening, closing, partial reversal and cold opening.", flush=True)
    healthy = []
    profiles = (("full_open", 0, 78, 4.8, 5.8, 20), ("full_close", 78, 0, 5.6, 6.6, 20),
                ("partial_reverse", 64, 27, 3.1, 4.1, 20), ("cold_open", 0, 78, 5.2, 6.2, -10))
    for index, (name, start, target, profile, duration, temperature) in enumerate(profiles):
        seed = 271828 + index
        p = replace(ModelParameters(), temperature_C=temperature)
        rig = ResearchRig(p, seed=seed, state=RigState(angle_rad=math.radians(start)))
        run = run_motion(rig, start_angle_rad=math.radians(start), target_angle_rad=math.radians(target),
                         duration_s=duration, profile_s=profile, include_truth=True)
        healthy.append({"name": name, "target_deg": target, "duration_s": duration, "profile_s": profile,
                        **recorded_motion(run, rig.parameters, rig, seed)})
        print(f"  {name}: {run['metrics']['termination']}; accepted={accepted(run)}", flush=True)
    gates["healthy_reference_passes_all_four_motion_profiles"] = all(r["accepted"] for r in healthy)

    print("Checking passive support, delayed power-loss brake and the zero-brake negative case.", flush=True)
    support = []
    for name, brake in (("healthy_brake", 120.0), ("brake_removed", 0.0)):
        rig = ResearchRig(drive={"brake_capacity_Nm": brake}, seed=314159,
                          state=RigState(angle_rad=ModelParameters().max_angle_rad))
        run = run_motion(rig, start_angle_rad=rig.state.angle_rad, target_angle_rad=rig.state.angle_rad,
                         duration_s=.8, powered=False, include_truth=True)
        support.append({"name": name, **recorded_motion(run, rig.parameters, rig, 314159)})
    rig = ResearchRig(seed=314160, state=RigState(angle_rad=math.radians(55)))
    loss = run_motion(rig, start_angle_rad=math.radians(55), target_angle_rad=math.radians(70),
                      duration_s=2.2, profile_s=1.7, power_loss_s=.8, include_truth=True)
    loss_record = recorded_motion(loss, rig.parameters, rig, 314160)
    after_loss = [row for row in loss["trace"] if row["time_s"] >= .8 - 1e-10]
    first_brake = next((row["time_s"] for row in after_loss if row["brake_engaged"]), None)
    loss_record["first_brake_record_s"] = first_brake
    gates["healthy_brake_holds_without_power"] = (support[0]["metrics"]["termination"] == "completed"
        and abs(support[0]["metrics"]["final_error_deg"]) < .001
        and support[0]["metrics"]["peak_speed_rad_s"] < 1e-9)
    gates["removing_brake_exposes_support_failure"] = (support[1]["metrics"]["final_error_deg"] > 1
        and support[1]["metrics"]["peak_speed_rad_s"] > .1)
    gates["power_loss_is_recorded_once_at_requested_time"] = [e["time_s"] for e in loss["events"] if e["type"] == "power_loss"] == [.8]
    gates["brake_engagement_respects_declared_delay"] = first_brake is not None and .82 - 1e-9 <= first_brake <= .83 + 1e-9
    gates["healthy_power_loss_settles_within_guard"] = (loss["metrics"]["termination"] == "completed"
        and abs(loss["trace"][-1]["true_velocity_rad_s"]) < 1e-6)

    print("Running 12 stratified conditions; failed calibrations are retained as outcomes.", flush=True)
    sweep = []
    for index in range(12):
        mass = (18., 25., 32., 45.)[index % 4]
        p = replace(ModelParameters(), mass_kg=mass, inertia_kg_m2=12 + (mass - 25) * .55**2,
                    motor_efficiency=(.4, .65, .85, 1.2)[(index * 3) % 4],
                    gas_scale=(.4, .75, 1., 1.4)[(index + index // 4) % 4],
                    temperature_C=(-10., 20., 50.)[index % 3],
                    friction_coulomb_Nm=(0., 6., 14., 25.)[(index + 1) % 4],
                    friction_static_Nm=(0., 6., 14., 25.)[(index + 1) % 4] + 2,
                    sensor_bias_rad=(-.08, 0., .08)[(index // 2) % 3])
        drive = replace(DriveParameters(), supply_voltage_V=(6., 9., 12., 16.)[(index + 2) % 4])
        sensors = replace(SensorParameters(), latency_s=(0., .01, .025, .05)[index % 4],
                          command_delay_s=(.05, .025, .01, 0.)[index % 4],
                          dropout_probability=.05 if index % 3 == 2 else 0.)
        gains = (.6, 1.) if index % 3 == 1 else (1., 1.)
        seed = 161803 + index
        row = {"case": index, "parameters": asdict(p), "drive": asdict(drive), "sensors": asdict(sensors),
               "side_effectiveness": list(gains), "seed": seed, "error": None,
               "target_deg": 78, "duration_s": 5.8, "profile_s": 4.8}
        try:
            rig = ResearchRig(p, seed=seed, drive=drive, sensors=sensors, side_effectiveness=gains,
                              state=RigState(angle_rad=0))
            run = run_motion(rig, start_angle_rad=0, target_angle_rad=p.max_angle_rad,
                             duration_s=5.8, profile_s=4.8, calibration=Calibration(), include_truth=True)
            row.update(recorded_motion(run, rig.parameters, rig, seed))
            print(f"  case {index:02}: {run['metrics']['termination']}; accepted={accepted(run)}", flush=True)
        except Exception as error:
            row["error"] = {"type": type(error).__name__, "message": str(error)}
            print(f"  case {index:02}: ERROR {type(error).__name__}: {error}", flush=True)
        sweep.append(row)
    gates["stratified_conditions_have_no_unhandled_errors"] = all(row["error"] is None for row in sweep)
    all_motions = healthy + support + [loss_record] + [r for r in sweep if r["error"] is None]
    gates["all_recorded_motion_states_finite"] = all(r["checks"]["finite"] for r in all_motions)
    gates["all_sensor_observations_are_causal"] = all(r["checks"]["sensor_causal"] for r in all_motions)
    gates["all_trace_timestamps_increase"] = all(r["checks"]["timestamps_increase"] for r in all_motions)
    gates["all_motion_electrical_energy_identities_hold"] = all(r["checks"]["electrical_identity_passed"] for r in all_motions)
    after_hashes = source_hashes()
    gates["source_files_unchanged_during_audit"] = before_hashes == after_hashes
    maxima = [{"refinement": refinement,
               **{key: max(row["trials"][index]["errors"][key] for row in records)
                  for key in ("angle_deg", "velocity_rad_s", "current_A", "temperature_C")}}
              for index, refinement in enumerate((1, 2, 4))]
    return {"schema_version": "recursivecal.research-rig-validation/1", "model_id": MODEL_ID,
            "scope": "Numerical verification of specified synthetic DC-drive equations and finite development conditions. No measured hardware validation or worst-case bound over all accepted inputs.",
            "hardware_validated": False, "measured_data_used": False,
            "reference_method": "Independent geometry/force/DC-current/continuous-PI/heat RHS; SciPy DOP853 rtol2e-11, atol2e-12. Smooth comparisons exclude voltage/current limits, contact and dry friction; complete motion checks exercise the hybrid application separately.",
            "convergence_scope": "PI voltage is held between internal updates. State accuracy is measured by refinement; global second-order convergence is not asserted.",
            "gates_fixed_before_run": LIMITS, "acceptance_limits": ACCEPTANCE,
            "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "wall_time_s": time.monotonic() - began},
            "source_sha256": before_hashes, "source_sha256_after_audit": after_hashes,
            "gates": gates, "passed": all(gates.values()), "smooth_maxima": maxima, "smooth_cases": records,
            "healthy_profiles": healthy, "passive_support": support, "power_loss": loss_record,
            "stratified_conditions": sweep,
            "condition_counts": {"distinct_sweep_conditions": len(sweep), "accepted": sum(r.get("accepted", False) for r in sweep),
                                 "unhandled_errors": sum(r["error"] is not None for r in sweep)},
            "limitations": ["Engineering development cases are not population-level independent experiments.",
                            "The ideal transmission excludes backlash, rotor inertia and efficiency losses.",
                            "No panel torsion, latch, obstacle contact, battery chemistry or physical I/O is modeled.",
                            "Physical accuracy requires independent measured trajectories from a matched mechanism."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/research-rig-validation.json"))
    args = parser.parse_args()
    report = run_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for name, passed in report["gates"].items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}", flush=True)
    print(f"Audit wrote {args.output}; {sum(report['gates'].values())}/{len(report['gates'])} gates passed.", flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
