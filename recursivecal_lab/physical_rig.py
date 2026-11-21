"""Persistent SI liftgate rig used by the physical inquiry protocol.

This version reuses the published CAD geometry and mechanical constitutive
functions. The v1 simulator and its archived results remain byte-for-byte intact.
All coefficients and sensor specifications here are declared synthetic assumptions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
import random
from typing import Any

from .physics import ModelParameters, geometry, gas_force, gravity_torque, _friction_velocity

MODEL_ID = "recursivecal.physical-rig/1"
MAX_FORCE_N = 330.0
MAX_SPEED_RAD_S = 1.15
MAX_ANGLE_RAD = math.radians(78.0)
SENSOR_SIGMA = (0.002, 0.008, 1.5)
OBSERVATION_FIELDS = ("angle_rad", "velocity_rad_s", "strut_force_N_each")


def finite(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return float(value)


def integer(value: Any, name: str, low: int, high: int) -> int:
    finite(value, name, low, high)
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class Calibration:
    """Controller estimates, never a mutation of the physical plant."""

    mass_kg: float = 25.0
    motor_efficiency: float = 1.0
    gas_scale: float = 1.0
    friction_coulomb_Nm: float = 6.0
    sensor_bias_rad: float = 0.0

    def validate(self) -> "Calibration":
        for name, low, high in (
            ("mass_kg", 18, 40), ("motor_efficiency", 0.4, 1.2),
            ("gas_scale", 0.4, 1.4), ("friction_coulomb_Nm", 0, 25),
            ("sensor_bias_rad", -0.08, 0.08),
        ):
            finite(getattr(self, name), name, low, high)
        return self

    def model(self) -> ModelParameters:
        self.validate()
        # Added mass is assumed to be at the nominal centre-of-mass radius.
        # This is a modeling assumption, not an identified inertia measurement.
        return replace(ModelParameters(), mass_kg=self.mass_kg,
                       inertia_kg_m2=12.0 + (self.mass_kg - 25.0) * 0.55 ** 2,
                       motor_efficiency=self.motor_efficiency, gas_scale=self.gas_scale,
                       friction_coulomb_Nm=self.friction_coulomb_Nm,
                       friction_static_Nm=self.friction_coulomb_Nm + 2.0,
                       sensor_bias_rad=self.sensor_bias_rad).validate()

    @classmethod
    def from_dict(cls, value: Any) -> "Calibration":
        if not isinstance(value, dict) or set(value) != set(asdict(cls())):
            raise ValueError("calibration must contain exactly the five declared estimate fields")
        return cls(**value).validate()


@dataclass(frozen=True)
class RigState:
    time_s: float = 0.0
    angle_rad: float = math.radians(20.0)
    velocity_rad_s: float = 0.0
    motor_force_N_each: float = 0.0
    mechanical_work_abs_J: float = 0.0


@dataclass(frozen=True)
class Experiment:
    name: str
    label: str
    target_angle_rad: float | None
    duration_s: float
    cost: float
    powered: bool = True
    fixture: bool = False


EXPERIMENTS = (
    Experiment("low_sweep", "Move to 20 degrees", math.radians(20), 1.4, 1.4),
    Experiment("high_sweep", "Move to 60 degrees", math.radians(60), 2.4, 2.4),
    Experiment("mid_sweep", "Move to 40 degrees", math.radians(40), 1.8, 1.8),
    Experiment("hold", "Hold the current measured angle", None, 0.7, 0.7),
    Experiment("coast", "Release motor for 0.18 seconds", None, 0.18, 0.8, powered=False),
    Experiment("reference", "Check encoder at a known fixture angle", math.radians(20), 0.1, 1.5, fixture=True),
)
CATALOG = {action.name: action for action in EXPERIMENTS}


def catalog() -> list[dict[str, Any]]:
    return [asdict(action) for action in EXPERIMENTS]


def smooth_reference(t: float, start: float, target: float, duration: float) -> tuple[float, float, float]:
    r = max(0.0, min(1.0, t / duration))
    d = target - start
    return (start + d * (10 * r**3 - 15 * r**4 + 6 * r**5),
            d * (30 * r**2 - 60 * r**3 + 30 * r**4) / duration,
            d * (60 * r - 180 * r**2 + 120 * r**3) / duration**2)


class PhysicalRig:
    """Evaluator-owned plant. Give a policy an InquirySession, never this object.

    The control loop uses an ideal filtered angle/rate signal with the declared
    encoder bias. Logged instrumentation adds independent Gaussian noise. The
    distinction is explicit: this is not a model of a particular ECU filter.
    """

    def __init__(self, parameters: ModelParameters | None = None, *, seed: int = 0,
                 state: RigState | None = None, closing_friction_extra_Nm: float = 0.0):
        self.parameters = (parameters or ModelParameters()).validate()
        integer(seed, "seed", 0, 2**31 - 1)
        self.closing_friction_extra_Nm = finite(closing_friction_extra_Nm, "closing_friction_extra_Nm", 0, 40)
        self.state = state or RigState()
        for name, low, high in (("time_s", 0, 1e6), ("angle_rad", 0, self.parameters.max_angle_rad),
                                ("velocity_rad_s", -10, 10), ("motor_force_N_each", -1000, 1000),
                                ("mechanical_work_abs_J", 0, 1e9)):
            finite(getattr(self.state, name), name, low, high)
        self._rng = random.Random(seed)

    def fork(self) -> "PhysicalRig":
        copy = PhysicalRig(self.parameters, state=self.state,
                           closing_friction_extra_Nm=self.closing_friction_extra_Nm)
        copy._rng.setstate(self._rng.getstate())
        return copy

    def observe(self, *, noisy: bool = True) -> dict[str, float]:
        s, p = self.state, self.parameters
        arm = geometry(s.angle_rad, p)["lever_m"]
        values = (s.angle_rad + p.sensor_bias_rad, s.velocity_rad_s,
                  s.motor_force_N_each + gas_force(s.angle_rad, p)
                  - p.strut_damping_N_s_m_each * arm * s.velocity_rad_s)
        return {"time_s": s.time_s, "ambient_temperature_C": p.temperature_C,
                **{name: value + (self._rng.gauss(0, sigma) if noisy else 0)
                for name, value, sigma in zip(OBSERVATION_FIELDS, values, SENSOR_SIGMA)}}

    def advance(self, command_N_each: float, dt_s: float, *, powered: bool = True) -> dict[str, Any]:
        """Advance one continuous state using bounded force and dissipative friction.

        Stops are inelastic projections. A limit event ends an experiment; it is
        not a claim that real hardware can be arrested instantaneously.
        """
        finite(command_N_each, "command_N_each", -1e6, 1e6)
        finite(dt_s, "dt_s", 1e-6, 0.02)
        if not isinstance(powered, bool):
            raise ValueError("powered must be boolean")
        p, s = self.parameters, self.state
        cap = min(MAX_FORCE_N, p.motor_force_max_N_each)
        requested = max(-cap, min(cap, command_N_each)) if powered else 0.0
        delivered = requested * p.motor_efficiency
        fm = delivered + (s.motor_force_N_each - delivered) * math.exp(-0.5 * dt_s / p.actuator_time_constant_s)
        fn = delivered + (s.motor_force_N_each - delivered) * math.exp(-dt_s / p.actuator_time_constant_s)
        qm = max(0.0, min(p.max_angle_rad, s.angle_rad + 0.5 * dt_s * s.velocity_rad_s))
        arm = geometry(qm, p)["lever_m"]
        net = 2 * (fm + gas_force(qm, p)) * arm - gravity_torque(qm, p)
        damping = p.friction_viscous_Nm_s + 2 * p.strut_damping_N_s_m_each * arm**2
        friction_model = p
        if self.closing_friction_extra_Nm and (s.velocity_rad_s < -1e-9 or (abs(s.velocity_rad_s) <= 1e-9 and net < 0)):
            friction_model = replace(p, friction_coulomb_Nm=p.friction_coulomb_Nm + self.closing_friction_extra_Nm,
                                     friction_static_Nm=p.friction_static_Nm + self.closing_friction_extra_Nm)
        vn = _friction_velocity(s.velocity_rad_s, net, damping, dt_s, friction_model,
                                p.holding_brake_Nm if not powered else 0.0)
        qn = s.angle_rad + 0.5 * dt_s * (s.velocity_rad_s + vn)
        incident = abs(vn)
        event = None
        if qn < 0 or qn > p.max_angle_rad:
            event = {"type": "lower_stop" if qn < 0 else "upper_stop", "incident_speed_rad_s": incident}
            qn = max(0.0, min(p.max_angle_rad, qn))
            vn = 0.0
        speed_breach = max(abs(s.velocity_rad_s), incident) > min(MAX_SPEED_RAD_S, p.speed_limit_rad_s)
        work = 2 * fm * arm * (qn - s.angle_rad)
        if not all(math.isfinite(value) for value in (qn, vn, fn, work)):
            raise ValueError("nonfinite mechanical state")
        self.state = RigState(s.time_s + dt_s, qn, vn, fn, s.mechanical_work_abs_J + abs(work))
        return {"command_N_each": requested, "saturated": powered and abs(command_N_each) > cap,
                "contact": event, "speed_breach": speed_breach, "precontact_speed_rad_s": incident,
                "mechanical_work_signed_J": work}

    def fixture(self, angle_rad: float = math.radians(20), duration_s: float = 0.1) -> None:
        """Explicit external fixturing: resets motion/force, preserves elapsed time/work.

        Repositioning is supplied by an external bench fixture. Its work is not
        counted as motor work; the diagnostic protocol charges a fixture cost.
        """
        finite(angle_rad, "fixture angle", 0, self.parameters.max_angle_rad)
        finite(duration_s, "fixture duration", 0.001, 10)
        self.state = RigState(self.state.time_s + duration_s, angle_rad, 0.0, 0.0,
                              self.state.mechanical_work_abs_J)


def controller_command(observation: dict[str, float], target: tuple[float, float, float],
                       calibration: Calibration) -> float:
    """Only measured angle/rate, public geometry and committed estimates enter."""
    # The caller pre-validates the immutable calibration for a full trajectory.
    q = max(0.0, min(MAX_ANGLE_RAD, observation["angle_rad"] - calibration.sensor_bias_rad))
    v = observation["velocity_rad_s"]
    qt, vt, at = target
    nominal = ModelParameters()
    arm = geometry(q, nominal)["lever_m"]
    inertia = 12.0 + (calibration.mass_kg - 25.0) * nominal.com_radius_m**2
    gravity = calibration.mass_kg * nominal.gravity_m_s2 * nominal.com_radius_m * math.sin(q + nominal.com_offset_rad)
    temperature = observation.get("ambient_temperature_C", 20.0)
    gas = gas_force(q, nominal) * calibration.gas_scale * (temperature + 273.15) / 293.15
    torque = (inertia * at + 178.0 * (qt - q) + 68.0 * (vt - v) + gravity - 2 * gas * arm
              + calibration.friction_coulomb_Nm * math.tanh(vt / 0.025)
              + nominal.friction_viscous_Nm_s * vt)
    return torque / (2 * arm * calibration.motor_efficiency)


def run_motion(rig: PhysicalRig, *, start_angle_rad: float, target_angle_rad: float,
               duration_s: float, profile_s: float | None = None, dt_s: float = 0.01,
               calibration: Calibration | None = None, powered: bool = True,
               power_loss_s: float | None = None, noisy: bool = True,
               include_truth: bool = False) -> dict[str, Any]:
    """A bounded trajectory, continuing the supplied rig without an implicit reset."""
    finite(start_angle_rad, "start_angle_rad", -0.2, MAX_ANGLE_RAD + 0.2)
    finite(target_angle_rad, "target_angle_rad", 0, MAX_ANGLE_RAD)
    finite(duration_s, "duration_s", 0.001, 15)
    finite(dt_s, "dt_s", 0.001, 0.02)
    if not isinstance(powered, bool) or not isinstance(noisy, bool) or not isinstance(include_truth, bool):
        raise ValueError("powered, noisy and include_truth must be boolean")
    profile_s = duration_s if profile_s is None else finite(profile_s, "profile_s", 0.001, duration_s)
    if power_loss_s is not None:
        finite(power_loss_s, "power_loss_s", 0, duration_s)
    estimate = (calibration or Calibration()).validate()
    start_time, start_work = rig.state.time_s, rig.state.mechanical_work_abs_J
    rows, observations, events = [], [], []
    # Three independent instrumentation snapshots with explicitly aligned times.
    samples = [duration_s / 3, 2 * duration_s / 3, duration_s]
    elapsed, sample_index, error_sum, sat_time, work_signed = 0.0, 0, 0.0, 0.0, 0.0
    peak_speed, termination = abs(rig.state.velocity_rad_s), "completed"
    initial_state = asdict(rig.state) if include_truth else None

    def record(t: float, command: float, target: float, measured: dict[str, float]) -> None:
        row = {"time_s": t, "absolute_time_s": rig.state.time_s,
               "target_angle_rad": target, "command_N_each": command, **measured}
        row["time_s"] = t
        if include_truth:
            row.update({"true_angle_rad": rig.state.angle_rad,
                        "true_velocity_rad_s": rig.state.velocity_rad_s,
                        "true_motor_force_N_each": rig.state.motor_force_N_each})
        rows.append(row)

    initial = rig.observe(noisy=noisy)
    record(0.0, 0.0, start_angle_rad, initial)
    while elapsed < duration_s - 1e-12:
        target = smooth_reference(elapsed, start_angle_rad, target_angle_rad, profile_s)
        # An explicitly ideal filtered control signal, distinct from logged noise.
        control_reading = rig.observe(noisy=False)
        enabled = powered and (power_loss_s is None or elapsed < power_loss_s - 1e-12)
        command = controller_command(control_reading, target, estimate) if enabled else 0.0
        h = min(dt_s, duration_s - elapsed, samples[sample_index] - elapsed)
        if power_loss_s is not None and elapsed < power_loss_s < elapsed + h:
            h = power_loss_s - elapsed
        error_sum += h * (target[0] - rig.state.angle_rad)**2
        step = rig.advance(command, h, powered=enabled)
        elapsed = min(duration_s, rig.state.time_s - start_time)
        if abs(elapsed - samples[sample_index]) < 1e-10:
            elapsed = samples[sample_index]
        if step["saturated"]:
            sat_time += h
        peak_speed = max(peak_speed, step["precontact_speed_rad_s"])
        work_signed += step["mechanical_work_signed_J"]
        measured = rig.observe(noisy=noisy)
        new_target = smooth_reference(elapsed, start_angle_rad, target_angle_rad, profile_s)[0]
        record(elapsed, step["command_N_each"], new_target, measured)
        if step["contact"]:
            events.append({"time_s": elapsed, **step["contact"]})
        if power_loss_s is not None and abs(elapsed - power_loss_s) < 1e-10:
            events.append({"time_s": elapsed, "type": "power_loss"})
        if step["speed_breach"]:
            events.append({"time_s": elapsed, "type": "speed_limit"})
            termination = "aborted_speed_limit"
        elif step["contact"] and step["contact"]["incident_speed_rad_s"] > 0.12:
            termination = "aborted_stop_impact"
        if abs(elapsed - samples[sample_index]) < 1e-10:
            observations.append({"sample_time_s": elapsed, **measured})
            sample_index += 1
        if termination != "completed":
            break
    metrics = {"termination": termination, "completed_duration_s": elapsed,
               "peak_speed_rad_s": peak_speed, "saturation_fraction": sat_time / max(elapsed, 1e-12),
               "mechanical_work_abs_J": rig.state.mechanical_work_abs_J - start_work,
               "mechanical_work_signed_J": work_signed,
               "tracking_rmse_deg": math.degrees(math.sqrt(error_sum / max(elapsed, 1e-12))),
               "final_error_deg": math.degrees(target_angle_rad - rig.state.angle_rad)}
    result = {"observations": observations, "trace": rows, "events": events, "metrics": metrics,
              "final_observation": measured, "duration_s": duration_s}
    if include_truth:
        result["initial_state"] = initial_state
        result["final_state"] = asdict(rig.state)
    return result


def run_experiment(rig: PhysicalRig, name: str, start_observation: dict[str, float], *,
                   noisy: bool = True, include_truth: bool = False) -> dict[str, Any]:
    if not isinstance(name, str) or name not in CATALOG:
        raise ValueError("unknown experiment")
    action = CATALOG[name]
    if action.fixture:
        previous = asdict(rig.state) if include_truth else None
        began = rig.state.time_s
        rig.fixture(action.target_angle_rad, action.duration_s)
        observations = [{**rig.observe(noisy=noisy), "sample_time_s": action.duration_s * index / 3,
                         "time_s": began + action.duration_s * index / 3} for index in (1, 2, 3)]
        result = {"observations": observations, "trace": [], "events": [{"time_s": action.duration_s, "type": "external_fixture"}],
                  "metrics": {"termination": "completed", "completed_duration_s": action.duration_s},
                  "final_observation": observations[-1], "duration_s": action.duration_s}
        if include_truth:
            result.update(initial_state=previous, final_state=asdict(rig.state))
        return result
    start = max(0.0, min(MAX_ANGLE_RAD, start_observation["angle_rad"]))
    target = action.target_angle_rad if action.target_angle_rad is not None else start
    return run_motion(rig, start_angle_rad=start, target_angle_rad=target,
                      duration_s=action.duration_s, powered=action.powered,
                      noisy=noisy, include_truth=include_truth)
