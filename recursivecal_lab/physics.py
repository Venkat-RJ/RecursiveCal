"""A dimensioned, synthetic single-axis liftgate model.

This module is for software-in-the-loop experiments. None of the default
coefficients is a measurement of a production vehicle. The frozen v0.2
diagnostic benchmark is deliberately not imported or changed here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import random
import json
from typing import Any

MODEL_ID = "recursivecal.si-liftgate/1"
SCENARIOS = ("open", "close", "passive_hold", "power_loss")


@dataclass(frozen=True)
class ModelParameters:
    mass_kg: float = 25.0
    inertia_kg_m2: float = 12.0
    gravity_m_s2: float = 9.80665
    com_radius_m: float = 0.55
    com_offset_rad: float = 0.15
    hinge_height_m: float = 1.76
    body_anchor_x_m: float = -0.470
    body_anchor_z_m: float = 1.170
    hatch_anchor_x_m: float = 0.018
    hatch_anchor_down_m: float = 0.300
    max_angle_rad: float = math.radians(78.0)
    gas_force_extended_N_each: float = 165.0
    gas_force_compressed_N_each: float = 212.0
    gas_scale: float = 1.0
    temperature_C: float = 20.0
    gas_reference_temperature_C: float = 20.0
    friction_coulomb_Nm: float = 6.0
    friction_static_Nm: float = 8.0
    friction_viscous_Nm_s: float = 5.0
    strut_damping_N_s_m_each: float = 6.0
    external_closing_torque_Nm: float = 0.0
    motor_force_max_N_each: float = 330.0
    motor_efficiency: float = 1.0
    actuator_time_constant_s: float = 0.06
    holding_brake_Nm: float = 0.0
    sensor_bias_rad: float = 0.0
    sensor_noise_std_rad: float = 0.0
    controller_kp_Nm_rad: float = 178.0
    controller_kd_Nm_s_rad: float = 68.0
    opening_duration_s: float = 4.8
    power_loss_time_s: float = 4.8
    speed_limit_rad_s: float = 1.15

    def validate(self) -> "ModelParameters":
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{field.name} must be a finite number")
            if abs(value) > 1e6:
                raise ValueError(f"{field.name} exceeds the numerical input bound of 1e6")
        for name in ("mass_kg", "inertia_kg_m2", "com_radius_m", "motor_force_max_N_each",
                     "actuator_time_constant_s", "opening_duration_s", "speed_limit_rad_s"):
            if getattr(self, name) < 1e-6:
                raise ValueError(f"{name} must be at least 1e-6")
        for name in ("gravity_m_s2", "gas_force_extended_N_each", "gas_force_compressed_N_each",
                     "gas_scale", "friction_coulomb_Nm", "friction_static_Nm",
                     "friction_viscous_Nm_s", "strut_damping_N_s_m_each", "holding_brake_Nm",
                     "sensor_noise_std_rad", "controller_kp_Nm_rad", "controller_kd_Nm_s_rad",
                     "power_loss_time_s"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.friction_static_Nm < self.friction_coulomb_Nm:
            raise ValueError("friction_static_Nm must be at least friction_coulomb_Nm")
        if not 0 <= self.motor_efficiency <= 1.5:
            raise ValueError("motor_efficiency must be between 0 and 1.5")
        if not -100 <= self.temperature_C <= 150 or not -100 <= self.gas_reference_temperature_C <= 150:
            raise ValueError("temperature_C and gas_reference_temperature_C must be in [-100, 150]")
        if not 1e-4 <= self.max_angle_rad < math.pi:
            raise ValueError("max_angle_rad must lie between 1e-4 and pi")
        # The extension-coordinate controller needs a positive, nonsingular arm.
        for index in range(101):
            g = geometry(self.max_angle_rad * index / 100, self)
            if g["length_m"] < 0.01 or g["lever_m"] < 0.01:
                raise ValueError("mount geometry must have a positive lever arm of at least 0.01 m")
        return self


def _parameters(value: ModelParameters | dict[str, Any] | None) -> ModelParameters:
    if value is None:
        return ModelParameters().validate()
    if isinstance(value, ModelParameters):
        return value.validate()
    if isinstance(value, dict):
        unknown = set(value) - {field.name for field in fields(ModelParameters)}
        if unknown:
            raise ValueError("unknown model parameters: " + ", ".join(sorted(unknown)))
        return ModelParameters(**value).validate()
    raise ValueError("parameters must be an object or ModelParameters")


def parameter_schema() -> list[dict[str, Any]]:
    """Serializable parameter metadata for a CLI or web form."""
    defaults = asdict(ModelParameters())
    descriptions = {
        "mass_kg": "Hatch mass", "inertia_kg_m2": "Hinge moment of inertia",
        "motor_efficiency": "Delivered motor-force multiplier", "gas_scale": "Gas-force multiplier",
        "holding_brake_Nm": "Explicit unpowered holding-brake torque capacity",
        "actuator_time_constant_s": "First-order motor-force response time",
        "sensor_bias_rad": "Additive angle-sensor bias", "sensor_noise_std_rad": "Angle-sensor noise standard deviation",
        "speed_limit_rad_s": "Simulation abort threshold for angular speed",
    }
    units = {"motor_efficiency": "1", "gas_scale": "1", "mass_kg": "kg", "inertia_kg_m2": "kg m^2",
             "gravity_m_s2": "m/s^2", "friction_viscous_Nm_s": "Nm s/rad",
             "strut_damping_N_s_m_each": "N s/m", "controller_kp_Nm_rad": "Nm/rad",
             "controller_kd_Nm_s_rad": "Nm s/rad"}
    for name in defaults:
        if name in units:
            continue
        units[name] = next((unit for suffix, unit in (("_N_each", "N per strut"), ("_rad_s", "rad/s"),
                        ("_rad", "rad"), ("_Nm", "Nm"), ("_m", "m"), ("_s", "s"), ("_C", "degC"))
                           if name.endswith(suffix)), "1")
    return [{"name": name, "default": value, "unit": units[name],
             "description": descriptions.get(name, name.replace("_", " "))}
            for name, value in defaults.items()]


def geometry(angle_rad: float, parameters: ModelParameters | None = None) -> dict[str, float]:
    """CAD mount length and d(length)/d(angle), both in metres."""
    p = parameters or ModelParameters()
    q = float(angle_rad)
    x = p.hatch_anchor_x_m * math.cos(q) + p.hatch_anchor_down_m * math.sin(q)
    z = p.hinge_height_m + p.hatch_anchor_x_m * math.sin(q) - p.hatch_anchor_down_m * math.cos(q)
    dx = -p.hatch_anchor_x_m * math.sin(q) + p.hatch_anchor_down_m * math.cos(q)
    dz = p.hatch_anchor_x_m * math.cos(q) + p.hatch_anchor_down_m * math.sin(q)
    ux, uz = x - p.body_anchor_x_m, z - p.body_anchor_z_m
    length = math.hypot(ux, uz)
    if length <= 0:
        raise ValueError("strut anchors must not coincide")
    return {"length_m": length, "lever_m": (ux * dx + uz * dz) / length,
            "hatch_anchor_x_m": x, "hatch_anchor_z_m": z}


def gas_force(angle_rad: float, parameters: ModelParameters | None = None) -> float:
    """Linear force/length curve, scaled by an explicit ideal-gas assumption."""
    p = parameters or ModelParameters()
    short, long = geometry(0, p)["length_m"], geometry(p.max_angle_rad, p)["length_m"]
    compression = max(0.0, min(1.0, (long - geometry(angle_rad, p)["length_m"]) / (long - short)))
    reference_force = p.gas_force_extended_N_each + compression * (
        p.gas_force_compressed_N_each - p.gas_force_extended_N_each)
    return reference_force * p.gas_scale * (p.temperature_C + 273.15) / (p.gas_reference_temperature_C + 273.15)


def gravity_torque(angle_rad: float, parameters: ModelParameters | None = None) -> float:
    p = parameters or ModelParameters()
    return p.mass_kg * p.gravity_m_s2 * p.com_radius_m * math.sin(angle_rad + p.com_offset_rad) + p.external_closing_torque_Nm


def passive_hold(parameters: ModelParameters | dict[str, Any] | None = None) -> dict[str, Any]:
    """Conditional static balance at the upper stop, with the motor disengaged."""
    p = _parameters(parameters)
    arm = geometry(p.max_angle_rad, p)["lever_m"]
    gas_torque = 2 * gas_force(p.max_angle_rad, p) * arm
    gravity = gravity_torque(p.max_angle_rad, p)
    closing_deficit = gravity - gas_torque
    capacity = p.friction_static_Nm + p.holding_brake_Nm
    return {
        "angle_deg": math.degrees(p.max_angle_rad), "lever_m": arm,
        "gas_opening_torque_Nm": gas_torque, "gravity_closing_torque_Nm": gravity,
        "closing_torque_deficit_Nm": closing_deficit,
        "static_friction_and_brake_capacity_Nm": capacity,
        "holding_margin_Nm": capacity - closing_deficit,
        "gas_alone_holds_open": closing_deficit <= 1e-9,
        "can_hold_open_without_motor": closing_deficit <= capacity + 1e-9,
        "additional_holding_torque_required_Nm": max(0.0, closing_deficit - capacity),
        "gas_force_for_gravity_balance_N_each": gravity / (2 * arm),
        "scope": "Synthetic static calculation at the upper stop; not a hardware safety certification.",
    }


def reference(time_s: float, parameters: ModelParameters, scenario: str) -> tuple[float, float, float]:
    if scenario == "passive_hold":
        return parameters.max_angle_rad, 0.0, 0.0
    r = max(0.0, min(1.0, time_s / parameters.opening_duration_s))
    q = parameters.max_angle_rad * (10 * r ** 3 - 15 * r ** 4 + 6 * r ** 5)
    v = parameters.max_angle_rad * (30 * r ** 2 - 60 * r ** 3 + 30 * r ** 4) / parameters.opening_duration_s
    a = parameters.max_angle_rad * (60 * r - 180 * r ** 2 + 120 * r ** 3) / parameters.opening_duration_s ** 2
    if scenario == "close":
        return parameters.max_angle_rad - q, -v, -a
    return q, v, a


def _clip(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _friction_velocity(v: float, external: float, viscous: float, h: float,
                       p: ModelParameters, brake: float) -> float:
    """Implicit viscous damping and a Coulomb/stiction velocity projection."""
    if abs(v) < 1e-12 and abs(external) <= p.friction_static_Nm + brake:
        return 0.0
    free = (v + h * external / p.inertia_kg_m2) / (1 + h * viscous / p.inertia_kg_m2)
    decrement = h * (p.friction_coulomb_Nm + brake) / (p.inertia_kg_m2 + h * viscous)
    return math.copysign(max(0.0, abs(free) - decrement), free)


def simulate(parameters: ModelParameters | dict[str, Any] | None = None, *,
             duration_s: float = 6.5, dt_s: float = 0.01, seed: int = 0,
             scenario: str = "open", controller: str = "nominal",
             initial_angle_rad: float | None = None, initial_velocity_rad_s: float = 0.0,
             abort_on_limit: bool = True,
             controller_parameters: ModelParameters | dict[str, Any] | None = None,
             parameter_provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a deterministic SI simulation and return the versioned trace contract.

    Controller feedforward always uses the nominal parameter set unless a
    separate controller_parameters object is supplied. It never silently reads
    the faulted plant's force/mass/friction values. Mount geometry is known.
    The velocity update is dissipative and the final time step is shortened.
    """
    p = _parameters(parameters)
    control_model = _parameters(controller_parameters)
    if parameter_provenance is not None:
        if not isinstance(parameter_provenance, dict) or parameter_provenance.get("source_kind") not in ("synthetic", "measured", "unknown"):
            raise ValueError("parameter_provenance needs source_kind synthetic, measured, or unknown")
        try:
            parameter_provenance = json.loads(json.dumps(parameter_provenance, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("parameter_provenance must contain finite JSON values") from exc
    for name, value in (("duration_s", duration_s), ("dt_s", dt_s), ("initial_velocity_rad_s", initial_velocity_rad_s)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0 < duration_s <= 120 or not 0.0001 <= dt_s <= 0.05 or duration_s / dt_s > 250000:
        raise ValueError("duration_s must be in (0,120], dt_s in [0.0001,0.05], and at most 250000 steps")
    if abs(initial_velocity_rad_s) > 1e6:
        raise ValueError("initial_velocity_rad_s exceeds the numerical input bound of 1e6")
    if scenario not in SCENARIOS:
        raise ValueError("scenario must be one of " + ", ".join(SCENARIOS))
    if controller not in ("nominal", "disabled"):
        raise ValueError("controller must be nominal or disabled")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not isinstance(abort_on_limit, bool):
        raise ValueError("abort_on_limit must be boolean")
    q = p.max_angle_rad if scenario in ("close", "passive_hold") else 0.0
    if initial_angle_rad is not None:
        if isinstance(initial_angle_rad, bool) or not isinstance(initial_angle_rad, (int, float)) or not math.isfinite(initial_angle_rad):
            raise ValueError("initial_angle_rad must be finite")
        q = float(initial_angle_rad)
    if not 0 <= q <= p.max_angle_rad:
        raise ValueError("initial angle must lie inside the physical stops")
    v = float(initial_velocity_rad_s)
    force = 0.0
    t = 0.0
    rng = random.Random(seed)
    trace: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    short_length = geometry(0, p)["length_m"]
    work_abs = 0.0
    work_signed = 0.0
    saturated_duration = 0.0
    error_integral = 0.0
    power_loss_recorded = False
    speed_limit_recorded = False
    termination = "completed"
    last_contact: str | None = None

    while True:
        if duration_s - t <= 1e-12:
            t = duration_s
        if scenario == "power_loss" and abs(t - p.power_loss_time_s) <= 1e-12:
            t = p.power_loss_time_s
        target, target_v, target_a = reference(t, p, scenario)
        g = geometry(q, p)
        observed = q + p.sensor_bias_rad + rng.gauss(0, p.sensor_noise_std_rad)
        powered = controller != "disabled" and scenario != "passive_hold"
        if scenario == "power_loss" and t >= p.power_loss_time_s - 1e-12:
            powered = False
            if not power_loss_recorded:
                events.append({"time_s": t, "type": "power_loss", "details": "Motor demand disabled; residual force decays with actuator lag."})
                power_loss_recorded = True
        demand = 0.0
        if powered:
            nominal_torque = (
                control_model.inertia_kg_m2 * target_a
                + p.controller_kp_Nm_rad * (target - observed)
                + p.controller_kd_Nm_s_rad * (target_v - v)
                + gravity_torque(q, control_model)
                - 2 * gas_force(q, control_model) * g["lever_m"]
                + control_model.friction_coulomb_Nm * math.tanh(target_v / 0.025)
                + control_model.friction_viscous_Nm_s * target_v
            )
            demand = nominal_torque / (2 * g["lever_m"])
        requested = _clip(demand, -p.motor_force_max_N_each, p.motor_force_max_N_each)
        requested_delivered = requested * p.motor_efficiency
        gas = gas_force(q, p)
        external = 2 * (force + gas) * g["lever_m"] - gravity_torque(q, p)
        brake = p.holding_brake_Nm if not powered else 0.0
        damping = p.friction_viscous_Nm_s + 2 * p.strut_damping_N_s_m_each * g["lever_m"] ** 2
        if abs(v) < 1e-12 and abs(external) <= p.friction_static_Nm + brake:
            friction = external
        else:
            friction = math.copysign(p.friction_coulomb_Nm + brake, v if abs(v) > 1e-12 else external) + damping * v
        trace.append({
            "time_s": t, "angle_rad": q, "target_angle_rad": target,
            "observed_angle_rad": observed, "velocity_rad_s": v,
            "length_m": g["length_m"], "stroke_m": g["length_m"] - short_length,
            "lever_m": g["lever_m"], "motor_force_N_each": force,
            "requested_motor_force_N_each": requested,
            "gas_force_N_each": gas, "motor_torque_Nm": 2 * force * g["lever_m"],
            "gas_torque_Nm": 2 * gas * g["lever_m"], "gravity_torque_Nm": gravity_torque(q, p),
            "friction_torque_Nm": friction, "unconstrained_torque_Nm": external - friction,
            "tracking_error_rad": target - q, "motor_powered": powered,
            "force_saturated": abs(demand) > p.motor_force_max_N_each,
        })
        if abs(v) > p.speed_limit_rad_s:
            if not speed_limit_recorded:
                events.append({"time_s": t, "type": "speed_limit", "details": {"actual_rad_s": abs(v), "limit_rad_s": p.speed_limit_rad_s}})
                speed_limit_recorded = True
            if abort_on_limit:
                termination = "aborted_speed_limit"
                break
        if t >= duration_s - 1e-12:
            break
        h = min(dt_s, duration_s - t)
        if scenario == "power_loss" and t < p.power_loss_time_s < t + h:
            h = p.power_loss_time_s - t
        # Analytic first-order actuator response at midpoint and endpoint.
        force_mid = requested_delivered + (force - requested_delivered) * math.exp(-0.5 * h / p.actuator_time_constant_s)
        force_new = requested_delivered + (force - requested_delivered) * math.exp(-h / p.actuator_time_constant_s)
        q_mid = _clip(q + 0.5 * h * v, 0.0, p.max_angle_rad)
        gm = geometry(q_mid, p)
        net_mid = 2 * (force_mid + gas_force(q_mid, p)) * gm["lever_m"] - gravity_torque(q_mid, p)
        damping_mid = p.friction_viscous_Nm_s + 2 * p.strut_damping_N_s_m_each * gm["lever_m"] ** 2
        v_new = _friction_velocity(v, net_mid, damping_mid, h, p, brake)
        q_new = q + 0.5 * h * (v + v_new)
        contact = "lower_stop" if q_new < 0 else "upper_stop" if q_new > p.max_angle_rad else None
        if contact:
            if contact != last_contact:
                events.append({"time_s": min(duration_s, t + h), "type": contact,
                               "details": {"incident_speed_rad_s": abs(v_new), "impact_model": "inelastic projection"}})
            q_new = _clip(q_new, 0, p.max_angle_rad)
            v_new = 0.0
        if not all(math.isfinite(value) for value in (q_new, v_new, force_new, net_mid, damping_mid)):
            raise ValueError("simulation produced a nonfinite state; reduce the timestep or revise the parameter range")
        last_contact = contact
        step_work = 2 * force_mid * gm["lever_m"] * (q_new - q)
        work_abs += abs(step_work)
        work_signed += step_work
        error_integral += h * (target - q) ** 2
        if abs(demand) > p.motor_force_max_N_each:
            saturated_duration += h
        q, v, force = q_new, v_new, force_new
        t = min(duration_s, t + h)

    elapsed = trace[-1]["time_s"]
    metrics = {
        "tracking_rmse_deg": math.degrees(math.sqrt(error_integral / elapsed)) if elapsed else abs(math.degrees(trace[0]["tracking_error_rad"])),
        "final_angle_deg": math.degrees(trace[-1]["angle_rad"]),
        "final_tracking_error_deg": math.degrees(trace[-1]["tracking_error_rad"]),
        "peak_speed_rad_s": max(abs(row["velocity_rad_s"]) for row in trace),
        "peak_motor_force_N_each": max(abs(row["motor_force_N_each"]) for row in trace),
        "mechanical_work_abs_J": work_abs, "mechanical_work_signed_J": work_signed,
        "force_saturation_fraction": saturated_duration / elapsed if elapsed else 0.0,
        "completed_duration_s": elapsed, "termination": termination,
        "passive_hold": passive_hold(p), "event_count": len(events),
    }
    return {
        "schema_version": "recursivecal.run/1", "model_id": MODEL_ID,
        "provenance": {"source_kind": "synthetic", "measured_data_used": bool(parameter_provenance and parameter_provenance["source_kind"] == "measured"),
                       "parameter_origin": "declared data-derived parameters" if parameter_provenance else "user-specified assumptions or illustrative defaults",
                       "parameter_provenance": parameter_provenance,
                       "hardware_validated": False, "signal_origin": "simulator state and synthetic sensor",
                       "current_model": "not implemented; no current or electrical-energy claim"},
        "parameters": asdict(p), "controller_parameters": asdict(control_model),
        "configuration": {"scenario": scenario, "controller": controller, "duration_s": duration_s,
                          "dt_s": dt_s, "seed": seed, "abort_on_limit": abort_on_limit,
                          "initial_angle_rad": trace[0]["angle_rad"], "initial_velocity_rad_s": initial_velocity_rad_s},
        "trace": trace, "metrics": metrics, "events": events,
    }
