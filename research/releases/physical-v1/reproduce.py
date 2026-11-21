"""Recreate physical-v1 evidence using the installed RecursiveCal package."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import platform

from recursivecal_lab import physics, measurements
from recursivecal_lab.measurements import compare_trajectory, fit_force_curve
from recursivecal_lab.physics import ModelParameters, geometry, simulate


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def energy(row, p):
    return .5 * p.inertia_kg_m2 * row["velocity_rad_s"] ** 2 - p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.cos(row["angle_rad"] + p.com_offset_rad)


def evaluate_gates(audit):
    """Executable software-regression gates, not hardware acceptance limits."""
    numeric = audit["numerical_verification"]
    scenario = audit["scenarios"]
    refinement = numeric["trajectory_refinement"]
    differences = [row["final_angle_difference_from_finest_rad"] for row in refinement]
    energy_runs = numeric["conservative_energy_refinement"]
    energy_drift = [abs(row["mechanical_energy_drift_J"]) for row in energy_runs]
    brake = audit["explicit_70Nm_brake_passive_hold"]["metrics"]
    power_loss_times = [event["time_s"] for event in scenario["power_loss"]["events"] if event["type"] == "power_loss"]
    gates = []

    def gate(name, passed, observed, criterion):
        gates.append({"name": name, "passed": bool(passed), "observed": observed, "criterion": criterion})

    residual = numeric["geometry_derivative_max_absolute_residual_m"]
    gate("geometry_derivative", math.isfinite(residual) and residual <= 1e-8,
         residual, "maximum finite-difference residual <= 1e-8 m")
    work = abs(numeric["constant_force_work_residual_J"])
    gate("constant_force_virtual_work", math.isfinite(work) and work <= 1e-5,
         work, "absolute quadrature/analytic work difference <= 1e-5 J")
    times = [row["completed_time_s"] for row in refinement]
    gate("exact_final_duration", all(t == 2.553 for t in times), times,
         "each refinement run reports exactly 2.553 s")
    gate("trajectory_refinement", all(math.isfinite(x) for x in differences) and differences[0] < .004
         and all(a > b for a, b in zip(differences, differences[1:])), differences,
         "20 ms endpoint difference from 2.5 ms <0.004 rad and decreases at each refinement")
    gate("conservative_energy_refinement", all(math.isfinite(x) for x in energy_drift)
         and energy_drift[-1] < .001 and all(b < a / 3 for a, b in zip(energy_drift, energy_drift[1:]))
         and all(row["contact_events"] == 0 for row in energy_runs), energy_drift,
         "contact-free absolute energy drift falls by >3x at each halving; finest <0.001 J")
    energy_change = numeric["dissipative_case"]["energy_change_J"]
    gate("dissipation", math.isfinite(energy_change) and energy_change < 0,
         energy_change, "mechanical energy decreases in the unpowered dissipative case")
    powered = {name: {"termination": scenario[name]["metrics"]["termination"],
                      "duration_s": scenario[name]["metrics"]["completed_duration_s"]} for name in ("open", "close")}
    gate("powered_scenarios_complete", all(row["termination"] == "completed" and row["duration_s"] == 6.5 for row in powered.values()),
         powered, "both nominal powered scenarios complete 6.5 s")
    passive = scenario["passive_hold"]["metrics"]
    gate("known_passive_hold_failure_preserved", not passive["passive_hold"]["can_hold_open_without_motor"]
         and passive["termination"] == "aborted_speed_limit" and passive["completed_duration_s"] < 6.5,
         {"termination": passive["termination"], "static_hold": passive["passive_hold"]["can_hold_open_without_motor"]},
         "the assumed default architecture fails static hold and the falling run triggers a speed abort")
    gate("explicit_brake_holds", brake["termination"] == "completed" and brake["completed_duration_s"] == 6.5
         and brake["peak_speed_rad_s"] == 0 and abs(brake["final_angle_deg"] - 78) <= 1e-9,
         {"termination": brake["termination"], "peak_speed_rad_s": brake["peak_speed_rad_s"], "final_angle_deg": brake["final_angle_deg"]},
         "explicit 70 Nm brake maintains 78 degrees without motion for 6.5 s")
    gate("power_loss_boundary_and_failure", power_loss_times == [4.8]
         and scenario["power_loss"]["metrics"]["termination"] == "aborted_speed_limit",
         {"event_times_s": power_loss_times, "termination": scenario["power_loss"]["metrics"]["termination"]},
         "power loss is recorded exactly at 4.8 s and the unsupported hatch triggers a speed abort")
    force_rmse = audit["data_path"]["force_validation"]["rmse"]
    gate("synthetic_force_import_regression", math.isfinite(force_rmse) and force_rmse < 3,
         force_rmse, "bundled synthetic force validation RMSE <3 N; a software example tolerance")
    angle_rmse = audit["data_path"]["trajectory_comparison"]["angle_rad"]["rmse"]
    gate("synthetic_trajectory_import_regression", math.isfinite(angle_rmse) and angle_rmse < .005,
         angle_rmse, "bundled synthetic trajectory RMSE <0.005 rad; a software example tolerance")
    return gates


def main():
    destination = Path(__file__).resolve().parent
    root = destination.parents[2]
    q0, q1, steps, force = .1, 1.2, 2000, 100
    dq = (q1 - q0) / steps
    integrated_work = sum(2 * force * geometry(q0 + (i + .5) * dq)["lever_m"] * dq for i in range(steps))
    exact_work = 2 * force * (geometry(q1)["length_m"] - geometry(q0)["length_m"])
    derivative_residual = max(abs((geometry(q + 1e-6)["length_m"] - geometry(q - 1e-6)["length_m"]) / 2e-6 - geometry(q)["lever_m"])
                              for q in (.1, .4, .8, 1.2))
    refinement = []
    for dt in (.02, .01, .005, .0025):
        run = simulate(dt_s=dt, duration_s=2.553)
        refinement.append({"dt_s": dt, "completed_time_s": run["trace"][-1]["time_s"],
                           "final_angle_rad": run["trace"][-1]["angle_rad"],
                           "tracking_rmse_deg": run["metrics"]["tracking_rmse_deg"]})
    fine_angle = refinement[-1]["final_angle_rad"]
    for row in refinement:
        row["final_angle_difference_from_finest_rad"] = abs(row["final_angle_rad"] - fine_angle)
    p = replace(ModelParameters(), gas_scale=0, friction_coulomb_Nm=0, friction_static_Nm=0,
                friction_viscous_Nm_s=0, strut_damping_N_s_m_each=0)
    energy_runs = []
    for dt in (.02, .01, .005, .0025):
        run = simulate(p, dt_s=dt, duration_s=.2, controller="disabled", initial_angle_rad=.8, abort_on_limit=False)
        energy_runs.append({"dt_s": dt, "duration_s": .2,
                            "mechanical_energy_drift_J": energy(run["trace"][-1], p) - energy(run["trace"][0], p),
                            "contact_events": sum("stop" in event["type"] for event in run["events"])})
    dissipative = simulate(replace(p, friction_coulomb_Nm=6, friction_static_Nm=8, friction_viscous_Nm_s=5),
                          controller="disabled", initial_angle_rad=.8, duration_s=.2, dt_s=.005, abort_on_limit=False)
    dissipation = {"initial_energy_J": energy(dissipative["trace"][0], p),
                   "final_energy_J": energy(dissipative["trace"][-1], p),
                   "energy_change_J": energy(dissipative["trace"][-1], p) - energy(dissipative["trace"][0], p)}
    scenario_runs = {name: simulate(scenario=name) for name in physics.SCENARIOS}
    brake_run = simulate(replace(ModelParameters(), holding_brake_Nm=70), scenario="passive_hold")
    force_fit = fit_force_curve(root / "examples/measurements/synthetic_force.csv")
    comparison = compare_trajectory(root / "examples/measurements/synthetic_trajectory.csv", scenario_runs["open"])
    write(destination / "synthetic_force_fit.json", force_fit)
    write(destination / "synthetic_trajectory_comparison.json", comparison)
    (destination / "open_run.json").write_text(json.dumps(scenario_runs["open"], separators=(",", ":"), allow_nan=False) + "\n")
    audit = {
        "schema_version": "recursivecal.physical-audit/1", "model_id": physics.MODEL_ID,
        "provenance": {"all_experiments_synthetic": True, "hardware_validated": False,
                       "python": platform.python_version(),
                       "model_source_sha256": hashlib.sha256(Path(physics.__file__).read_bytes()).hexdigest(),
                       "measurement_source_sha256": hashlib.sha256(Path(measurements.__file__).read_bytes()).hexdigest(),
                       "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "numerical_verification": {
            "geometry_derivative_max_absolute_residual_m": derivative_residual,
            "constant_force_work_analytic_J": exact_work, "constant_force_work_quadrature_J": integrated_work,
            "constant_force_work_residual_J": integrated_work - exact_work,
            "trajectory_refinement": refinement, "conservative_energy_refinement": energy_runs,
            "dissipative_case": dissipation,
        },
        "scenarios": {name: {"metrics": run["metrics"], "events": run["events"]} for name, run in scenario_runs.items()},
        "explicit_70Nm_brake_passive_hold": {"metrics": brake_run["metrics"], "events": brake_run["events"]},
        "data_path": {"force_validation": force_fit["validation_metrics_N_each"], "trajectory_comparison": comparison["metrics"],
                      "data_kind": "synthetic examples from the same simulator; not independent validation"},
    }
    audit["gates"] = evaluate_gates(audit)
    failed = [gate["name"] for gate in audit["gates"] if not gate["passed"]]
    audit["software_checks_passed"] = not failed
    audit["gate_scope"] = "Explicit regression tolerances for these synthetic examples, selected during software development. Not empirical accuracy limits or independently preregistered criteria."
    audit["interpretation"] = (
        "Software numerical/regression gates passed, including preservation of the default passive-hold failure. This is not a physical-accuracy or hardware-safety pass."
        if not failed else "One or more software gates failed. Inspect the recorded criteria before using these artifacts.")
    write(destination / "audit.json", audit)
    if failed:
        raise RuntimeError("Physical software audit gates failed: " + ", ".join(failed))
    print(json.dumps({"output": str(destination), "model_id": physics.MODEL_ID,
                      "default_passive_hold": scenario_runs["passive_hold"]["metrics"]["termination"],
                      "brake_passive_hold": brake_run["metrics"]["termination"],
                      "force_validation_rmse_N": force_fit["validation_metrics_N_each"]["rmse"],
                      "geometry_residual_m": derivative_residual,
                      "software_gates_passed": len(audit["gates"])}, indent=2))


if __name__ == "__main__":
    main()
