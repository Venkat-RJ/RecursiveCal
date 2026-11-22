"""Versioned workbench adapter for the bounded electromechanical research rig.

The old force-domain simulator remains available as model version 2. This
adapter runs the same ResearchRig used by inquiry and the physical RL task.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from .physics import ModelParameters, SCENARIOS, gas_force, geometry, gravity_torque, passive_hold
from .physical_rig import Calibration, RigState, finite, integer, run_motion

MODEL_ID = "recursivecal.si-liftgate/3"


def capabilities() -> dict[str, Any]:
    from .research_rig import ResearchRig, configuration_schema
    rig = ResearchRig()
    return {"model_id": MODEL_ID, "rig_model_id": rig.model_id,
            "default_parameters": asdict(rig.parameters), "specification": rig.metadata(),
            "configuration_schema": configuration_schema(),
            "limits": {"duration_s_max": 15, "dt_s_min": 0.001, "dt_s_max": 0.02},
            "hardware_connected": False, "hardware_validated": False,
            "camera_role": "human inspection; no image observations in the agent contract"}


def simulate(parameters: ModelParameters | dict[str, Any] | None = None, *,
             duration_s: float = 6.5, dt_s: float = 0.01, seed: int = 0,
             scenario: str = "open", controller: str = "nominal",
             initial_angle_rad: float | None = None, initial_velocity_rad_s: float = 0.0,
             abort_on_limit: bool = True,
             controller_parameters: ModelParameters | dict[str, Any] | None = None,
             parameter_provenance: dict[str, Any] | None = None,
             drive: dict[str, Any] | None = None, sensors: dict[str, Any] | None = None,
             side_effectiveness: tuple[float, float] | list[float] = (1.0, 1.0)) -> dict[str, Any]:
    from .research_rig import ResearchRig
    finite(duration_s, "duration_s", 0.001, 15)
    finite(dt_s, "dt_s", 0.001, 0.02)
    integer(seed, "seed", 0, 2**31 - 1)
    finite(initial_velocity_rad_s, "initial_velocity_rad_s", -1.15, 1.15)
    if abort_on_limit is not True:
        raise ValueError("research rig 3 always stops on a declared limit; use model 2 for unguarded exploration")
    if scenario not in SCENARIOS or controller not in ("nominal", "disabled"):
        raise ValueError("unsupported research scenario or controller")
    if parameters is not None and not isinstance(parameters, (dict, ModelParameters)):
        raise ValueError("parameters must be a ModelParameters object or JSON object")
    try:
        p = ModelParameters(**parameters).validate() if isinstance(parameters, dict) else parameters
    except TypeError as exc:
        raise ValueError("unsupported model parameter") from exc
    if p is not None:
        p.validate()
    max_angle = (p or ModelParameters()).max_angle_rad
    start = max_angle if scenario in ("close", "passive_hold") else 0.0
    if initial_angle_rad is not None:
        start = finite(initial_angle_rad, "initial_angle_rad", 0, max_angle)
    rig = ResearchRig(p, seed=seed, state=RigState(angle_rad=start, velocity_rad_s=initial_velocity_rad_s),
                      drive=drive, sensors=sensors, side_effectiveness=side_effectiveness)
    p = rig.parameters
    estimate = Calibration()
    if controller_parameters is not None:
        try:
            cp = ModelParameters(**controller_parameters) if isinstance(controller_parameters, dict) else controller_parameters
            cp.validate()
        except (TypeError, AttributeError) as exc:
            raise ValueError("controller_parameters must contain valid model parameters") from exc
        if (cp.controller_kp_Nm_rad, cp.controller_kd_Nm_s_rad) != (178.0, 68.0):
            raise ValueError("research controller gains are fixed by the task contract")
        estimate = Calibration(**{key: getattr(cp, key) for key in asdict(Calibration())}).validate()
        canonical = asdict(estimate.model())
        supplied = controller_parameters if isinstance(controller_parameters, dict) else asdict(cp)
        unsupported = sorted(key for key, value in supplied.items()
                             if key not in asdict(estimate) and value != canonical[key])
        if unsupported:
            raise ValueError("research controller accepts only the five calibration estimates; "
                             "unsupported coefficients: " + ", ".join(unsupported)
                             + ". Use model 2 for a custom force-curve controller.")
    if parameter_provenance is not None:
        if not isinstance(parameter_provenance, dict) or parameter_provenance.get("source_kind") not in ("synthetic", "measured", "unknown"):
            raise ValueError("parameter_provenance needs a declared source_kind")
        parameter_provenance = json.loads(json.dumps(parameter_provenance, allow_nan=False))
    target = 0.0 if scenario == "close" else p.max_angle_rad
    if scenario == "passive_hold":
        target = start
    cutoff = p.power_loss_time_s if scenario == "power_loss" and p.power_loss_time_s <= duration_s else None
    motion = run_motion(rig, start_angle_rad=start, target_angle_rad=target,
                        duration_s=duration_s, profile_s=p.opening_duration_s, dt_s=dt_s,
                        calibration=estimate, powered=controller != "disabled" and scenario != "passive_hold",
                        power_loss_s=cutoff, include_truth=True)
    short_length = geometry(0.0, p)["length_m"]
    trace = []
    for source in motion["trace"]:
        q, velocity = source["true_angle_rad"], source["true_velocity_rad_s"]
        g = geometry(q, p)
        gas, motor = gas_force(q, p), source["true_motor_force_N_each"]
        row = {**source, "observed_angle_rad": source["angle_rad"],
               "observed_velocity_rad_s": source["velocity_rad_s"],
               "angle_rad": q, "velocity_rad_s": velocity,
               "length_m": g["length_m"], "stroke_m": g["length_m"] - short_length,
               "lever_m": g["lever_m"], "motor_force_N_each": motor,
               "requested_motor_force_N_each": source["command_N_each"],
               "gas_force_N_each": gas, "motor_torque_Nm": 2 * motor * g["lever_m"],
               "gas_torque_Nm": 2 * gas * g["lever_m"], "gravity_torque_Nm": gravity_torque(q, p),
               "tracking_error_rad": source["target_angle_rad"] - q,
               "motor_powered": controller != "disabled" and scenario != "passive_hold" and
                                (cutoff is None or source["time_s"] < cutoff) and
                                not (source.get("left_drive_tripped") or source.get("right_drive_tripped")),
               "force_saturated": bool(source.get("force_saturated", False))}
        trace.append(row)
    metrics = {**motion["metrics"], "force_saturation_fraction": motion["metrics"]["saturation_fraction"],
               "passive_hold": passive_hold(p), "event_count": len(motion["events"])}
    source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                     for name in ("physics.py", "physical_rig.py", "research_rig.py", "research_simulation.py")}
    return {"schema_version": "recursivecal.run/1", "model_id": MODEL_ID,
            "parameters": asdict(p), "controller_parameters": asdict(estimate.model()),
            "rig_specification": rig.metadata(),
            "configuration": {"scenario": scenario, "controller": controller, "duration_s": duration_s,
                              "dt_s": dt_s, "seed": seed, "abort_on_limit": True, "rig_version": 3,
                              "initial_angle_rad": start, "initial_velocity_rad_s": initial_velocity_rad_s},
            "provenance": {"source_kind": "synthetic", "hardware_validated": False,
                           "measured_data_used": bool(parameter_provenance and parameter_provenance["source_kind"] == "measured"),
                           "parameter_provenance": parameter_provenance, "source_sha256": source_hashes,
                           "signal_origin": "simulator state and sampled synthetic instrumentation",
                           "current_model": "two DC drives with voltage, current, back-EMF and lumped winding heat",
                           "camera_role": "inspection only; no camera observations supplied to the policy"},
            "trace": trace, "metrics": metrics, "events": motion["events"]}
