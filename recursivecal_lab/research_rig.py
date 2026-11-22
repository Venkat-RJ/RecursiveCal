"""Version 3 synthetic liftgate with drives and sampled instrumentation.

The rigid-body equations remain owned by ``physics.advance_mechanics``.  Each
drive is a DC armature connected to an ideal gear/screw transformer.  Electrical
integration is exact while speed and resistance are locally frozen; symmetric
electrical/mechanical splitting is checked by timestep refinement.  This is a
declared research mechanism, not an identified production actuator.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
import math
from typing import Any

from .physical_rig import PhysicalRig, RigState, MAX_FORCE_N, MAX_SPEED_RAD_S, finite
from .physics import ModelParameters, advance_mechanics, gas_force, geometry

MODEL_ID = "recursivecal.physical-rig/3"
SPEC_ID = "recursivecal.research-rig-spec/1"


@dataclass(frozen=True)
class DriveParameters:
    supply_voltage_V: float = 12.0
    resistance_ohm: float = 0.7
    inductance_H: float = 0.006
    torque_constant_Nm_A: float = 0.015
    gear_ratio: float = 8.0
    screw_lead_m: float = 0.012
    max_current_A: float = 9.0
    current_kp_ohm: float = 0.4
    current_ki_ohm_s: float = 20.0
    coil_heat_capacity_J_K: float = 15.0
    thermal_resistance_K_W: float = 8.0
    resistance_temperature_coefficient_K: float = 0.00393
    derate_start_C: float = 80.0
    trip_temperature_C: float = 110.0
    freewheel_resistance_ohm: float = 3.0
    brake_capacity_Nm: float = 120.0
    brake_delay_s: float = 0.02
    integration_dt_s: float = 0.001

    def validate(self) -> "DriveParameters":
        for name, low, high in DRIVE_BOUNDS:
            finite(getattr(self, name), name, low, high)
        if self.trip_temperature_C <= self.derate_start_C:
            raise ValueError("trip temperature must exceed the derating temperature")
        return self


DRIVE_BOUNDS = (
    ("supply_voltage_V", 6, 16), ("resistance_ohm", .2, 2),
    ("inductance_H", .001, .05), ("torque_constant_Nm_A", .005, .05),
    ("gear_ratio", 4, 20), ("screw_lead_m", .006, .03),
    ("max_current_A", 2, 15), ("current_kp_ohm", 0, 2),
    ("current_ki_ohm_s", 0, 100), ("coil_heat_capacity_J_K", 5, 100),
    ("thermal_resistance_K_W", 1, 30), ("resistance_temperature_coefficient_K", 0, .01),
    ("derate_start_C", 50, 100), ("trip_temperature_C", 90, 150),
    ("freewheel_resistance_ohm", .5, 20), ("brake_capacity_Nm", 0, 200),
    ("brake_delay_s", 0, .1), ("integration_dt_s", .0001, .001),
)


@dataclass(frozen=True)
class SensorParameters:
    sample_period_s: float = .01
    latency_s: float = .01
    command_delay_s: float = .01
    angle_resolution_rad: float = .0005
    velocity_resolution_rad_s: float = .002
    force_resolution_N: float = .25
    angle_noise_std_rad: float = .002
    velocity_noise_std_rad_s: float = .008
    force_noise_std_N: float = 1.5
    dropout_probability: float = 0.0

    def validate(self) -> "SensorParameters":
        for name, low, high in SENSOR_BOUNDS:
            finite(getattr(self, name), name, low, high)
        return self


SENSOR_BOUNDS = (
    ("sample_period_s", .005, .05), ("latency_s", 0, .1),
    ("command_delay_s", 0, .1), ("angle_resolution_rad", 0, .01),
    ("velocity_resolution_rad_s", 0, .05), ("force_resolution_N", 0, 5),
    ("angle_noise_std_rad", 0, .02), ("velocity_noise_std_rad_s", 0, .1),
    ("force_noise_std_N", 0, 10), ("dropout_probability", 0, .1),
)


def _config(value: Any, cls):
    if value is None:
        return cls().validate()
    if isinstance(value, cls):
        return value.validate()
    if not isinstance(value, dict):
        raise ValueError(f"{cls.__name__} must be an object")
    unknown = set(value) - {field.name for field in fields(cls)}
    if unknown:
        raise ValueError("unknown configuration fields: " + ", ".join(sorted(unknown)))
    return cls(**value).validate()


def configuration_schema() -> dict[str, Any]:
    """Serializable limits for configuration UIs, not a measured operating envelope."""
    def schema(cls, bounds):
        default = asdict(cls())
        return [{"name": name, "default": default[name], "minimum": low, "maximum": high}
                for name, low, high in bounds]
    return {"model_id": MODEL_ID, "spec_id": SPEC_ID,
            "drive": schema(DriveParameters, DRIVE_BOUNDS),
            "sensors": schema(SensorParameters, SENSOR_BOUNDS),
            "side_effectiveness": {"default": [1.0, 1.0], "minimum": .4, "maximum": 1.2}}


@dataclass(frozen=True)
class DriveState:
    current_A: float = 0.0
    temperature_C: float = 20.0
    integral_V: float = 0.0
    voltage_V: float = 0.0
    electrical_energy_J: float = 0.0
    copper_loss_J: float = 0.0
    dump_loss_J: float = 0.0
    shaft_work_J: float = 0.0
    initial_inductive_energy_J: float = 0.0
    saturated: bool = False
    tripped: bool = False


def electrical_interval(current_A: float, voltage_V: float, speed_rad_s: float,
                        resistance_ohm: float, inductance_H: float,
                        torque_constant_Nm_A: float, duration_s: float) -> dict[str, float]:
    """Exact constant-speed DC armature response and its energy integrals.

    Kt and Ke have the same SI value. Signed terminal energy is positive into the
    drive; negative energy is regeneration. No post-integration current clipping
    or discarded magnetic energy is used.
    """
    for name, value in (("current", current_A), ("voltage", voltage_V), ("speed", speed_rad_s)):
        finite(value, name, -1e9, 1e9)
    finite(resistance_ohm, "resistance", 1e-9, 1e6)
    finite(inductance_H, "inductance", 1e-12, 1e6)
    finite(torque_constant_Nm_A, "torque constant", 0, 1e6)
    finite(duration_s, "duration", 0, 1e6)
    rate = resistance_ohm / inductance_H
    emf = torque_constant_Nm_A * speed_rad_s
    steady = (voltage_V - emf) / resistance_ohm
    amplitude = current_A - steady
    one_minus = -math.expm1(-rate * duration_s)
    integral_i = steady * duration_s + amplitude * one_minus / rate
    integral_i2 = (steady * steady * duration_s
                   + 2 * steady * amplitude * one_minus / rate
                   + amplitude * amplitude * -math.expm1(-2 * rate * duration_s) / (2 * rate))
    # Cancellation near a tiny interval can produce an insignificant negative.
    integral_i2 = max(0.0, integral_i2)
    current = current_A - amplitude * one_minus
    return {"current_A": current, "charge_C": integral_i, "current_squared_integral_A2_s": integral_i2,
            "terminal_energy_J": voltage_V * integral_i,
            "resistive_loss_J": resistance_ohm * integral_i2,
            "shaft_work_J": emf * integral_i,
            "inductive_energy_change_J": .5 * inductance_H * (current * current - current_A * current_A)}


class ResearchRig(PhysicalRig):
    """Evaluator-owned v3 plant. Policies receive only InquirySession observations.

    Both drives act on one rigid hinge. Independent currents and temperatures do
    not imply a panel-twist model. The ideal gear/screw transformer neglects
    rotor inertia and backlash; explicit hinge and axial friction remain active.
    """

    model_id = MODEL_ID

    def __init__(self, parameters: ModelParameters | None = None, *, seed: int = 0,
                 state: RigState | None = None, closing_friction_extra_Nm: float = 0.0,
                 drive: DriveParameters | dict[str, Any] | None = None,
                 sensors: SensorParameters | dict[str, Any] | None = None,
                 side_effectiveness: tuple[float, float] | list[float] = (1.0, 1.0)):
        self.drive = _config(drive, DriveParameters)
        self.sensors = _config(sensors, SensorParameters)
        if not isinstance(side_effectiveness, (list, tuple)) or len(side_effectiveness) != 2:
            raise ValueError("side_effectiveness needs exactly left and right values")
        self.side_effectiveness = tuple(finite(value, "side effectiveness", .4, 1.2)
                                        for value in side_effectiveness)
        p = parameters or ModelParameters()
        if not isinstance(p, ModelParameters):
            raise ValueError("parameters must be ModelParameters")
        # The v3 architecture is deliberately explicit; an archived v2 value of
        # zero does not silently remove its brake. Drive config owns the choice.
        p = replace(p, holding_brake_Nm=self.drive.brake_capacity_Nm)
        super().__init__(p, seed=seed, state=state,
                         closing_friction_extra_Nm=closing_friction_extra_Nm)
        self.seed = seed
        finite(p.mass_kg, "mass_kg", 18, 45)
        finite(p.motor_efficiency, "motor effectiveness", .4, 1.2)
        finite(p.gas_scale, "gas_scale", .4, 1.4)
        finite(p.temperature_C, "ambient temperature", -10, 50)
        finite(p.friction_coulomb_Nm, "friction_coulomb_Nm", 0, 25)
        finite(p.sensor_bias_rad, "sensor_bias_rad", -.08, .08)
        nominal = ModelParameters()
        for name in ("hinge_height_m", "body_anchor_x_m", "body_anchor_z_m", "hatch_anchor_x_m",
                     "hatch_anchor_down_m", "max_angle_rad", "com_radius_m", "com_offset_rad"):
            if abs(getattr(p, name) - getattr(nominal, name)) > 1e-10:
                raise ValueError(f"research rig has fixed declared geometry: {name}")
        self._ratio = 2 * math.pi * self.drive.gear_ratio / self.drive.screw_lead_m
        maximum_arm = max(geometry(p.max_angle_rad * index / 100, p)["lever_m"] for index in range(101))
        self._coupling_frequency_rad_s = math.sqrt(sum(
            (self.drive.torque_constant_Nm_A * p.motor_efficiency * gain * self._ratio * maximum_arm)**2
            / (p.inertia_kg_m2 * self.drive.inductance_H) for gain in self.side_effectiveness))
        self._closed_length = geometry(0.0, p)["length_m"]
        self._motors = []
        for gain in self.side_effectiveness:
            current = self.state.motor_force_N_each / (self.drive.torque_constant_Nm_A * self._ratio * p.motor_efficiency * gain)
            if abs(current) > self.drive.max_current_A:
                raise ValueError("initial motor force exceeds the drive current envelope")
            self._motors.append(DriveState(current_A=current, temperature_C=p.temperature_C,
                                           initial_inductive_energy_J=.5 * self.drive.inductance_H * current**2))
        self._powered = False
        self._trip_latched = False
        self._brake_deadline = self.state.time_s
        self._command = 0.0
        self._command_queue: deque[tuple[float, float]] = deque()
        self._pending_samples: deque[tuple[float, dict[str, float], dict[str, float]]] = deque()
        self._next_sample_time = self.state.time_s + self.sensors.sample_period_s
        self._sample_number = 0
        self._dropped_samples = 0
        self._fixture_active = False
        self._coupling_residual_J = 0.0
        self._axial_dissipation_J = 0.0
        clean, noisy = self._instrument_sample()
        self._clean_sample, self._noisy_sample = clean, noisy

    def fork(self) -> "ResearchRig":
        return deepcopy(self)

    def metadata(self) -> dict[str, Any]:
        return {"model_id": MODEL_ID, "spec_id": SPEC_ID, "source_kind": "synthetic",
                "hardware_validated": False, "measured_data_used": False,
                "architecture": "one rigid hinge; two independent DC drives; ideal gear/screw; spring-applied brake",
                "parameters": asdict(self.parameters), "drive": asdict(self.drive),
                "sensors": asdict(self.sensors), "side_effectiveness": list(self.side_effectiveness),
                "seed": self.seed, "closing_friction_extra_Nm": self.closing_friction_extra_Nm,
                "motor_effectiveness_definition": "matched SI torque/back-EMF constant multiplier, not energetic efficiency",
                "supply_model": "ideal bidirectional voltage source accepts regenerative energy; no battery state of charge",
                "power_loss_model": "supply disconnected; armatures recirculate through dump resistors; delayed spring brake",
                "initial_sensor_acquisition": "one labelled initial acquisition is available at reset; subsequent samples incur latency",
                "numerical_method": "symmetric exact electrical halfsteps around shared mechanical midpoint kernel",
                "current_regulator": "ideal continuous PI approximated by explicit internal-step voltage holds; no hardware PWM-rate claim; global control accuracy is first order",
                "replaced_v2_parameters": ["actuator_time_constant_s", "sensor_noise_std_rad"],
                "effective_internal_step_s": self._internal_step_bound(),
                "internal_step_rule": "min(requested step, 0.2/max(electrical-current-loop rate, PI rate, coupled electromechanical frequency))",
                "supported_scope": {"mass_kg": [18, 45], "temperature_C": [-10, 50],
                                    "motor_effectiveness": [.4, 1.2], "gas_scale": [.4, 1.4],
                                    "control_step_s_max": .02, "geometry": "fixed authored 78-degree mechanism"},
                "unsupported_effects": ["gear/screw backlash", "rotor inertia", "panel twist/compliance",
                                        "obstacle/pinch contact", "latch dynamics", "battery chemistry",
                                        "measured hardware accuracy"]}

    @staticmethod
    def _quantize(value: float, resolution: float) -> float:
        return round(value / resolution) * resolution if resolution else value

    def _instrument_sample(self) -> tuple[dict[str, float], dict[str, float]]:
        s, p, cfg = self.state, self.parameters, self.sensors
        arm = geometry(s.angle_rad, p)["lever_m"]
        values = (s.angle_rad + p.sensor_bias_rad, s.velocity_rad_s,
                  s.motor_force_N_each + gas_force(s.angle_rad, p)
                  - p.strut_damping_N_s_m_each * arm * s.velocity_rad_s)
        names = ("angle_rad", "velocity_rad_s", "strut_force_N_each")
        resolutions = (cfg.angle_resolution_rad, cfg.velocity_resolution_rad_s, cfg.force_resolution_N)
        noises = (cfg.angle_noise_std_rad, cfg.velocity_noise_std_rad_s, cfg.force_noise_std_N)
        base = {"sensor_sample_time_s": s.time_s, "ambient_temperature_C": p.temperature_C}
        clean = {**base, **{name: self._quantize(value, res) for name, value, res in zip(names, values, resolutions)}}
        noisy = {**base, **{name: self._quantize(value + self._rng.gauss(0.0, sigma), res)
                           for name, value, sigma, res in zip(names, values, noises, resolutions)}}
        return clean, noisy

    def _publish_samples(self) -> None:
        now = self.state.time_s
        while self._pending_samples and self._pending_samples[0][0] <= now + 1e-12:
            _, self._clean_sample, self._noisy_sample = self._pending_samples.popleft()

    def observe(self, *, noisy: bool = True) -> dict[str, float]:
        if not isinstance(noisy, bool):
            raise ValueError("noisy must be boolean")
        sample = self._noisy_sample if noisy else self._clean_sample
        return {**sample, "time_s": self.state.time_s,
                "sensor_age_s": max(0.0, self.state.time_s - sample["sensor_sample_time_s"])}

    def control_observation(self, *, noisy: bool = True) -> dict[str, float]:
        # Exactly the same held acquisition as the public instrument view.
        return self.observe(noisy=noisy)

    def _resistance(self, temperature: float) -> float:
        return self.drive.resistance_ohm * max(.2, 1 + self.drive.resistance_temperature_coefficient_K * (temperature - 20))

    def _thermal_current_limit(self, temperature: float) -> float:
        cfg = self.drive
        return cfg.max_current_A * max(0.0, min(1.0, (cfg.trip_temperature_C - temperature)
                                                / (cfg.trip_temperature_C - cfg.derate_start_C)))

    def _internal_step_bound(self) -> float:
        cfg = self.drive
        electrical_rate = max((self._resistance(m.temperature_C) + cfg.current_kp_ohm)
                              / cfg.inductance_H for m in self._motors)
        fastest = max(electrical_rate, math.sqrt(cfg.current_ki_ohm_s / cfg.inductance_H),
                      self._coupling_frequency_rad_s)
        return min(cfg.integration_dt_s, .2 / fastest)

    def _voltage_command(self, motor: DriveState, speed: float, h: float, enabled: bool) -> tuple[float, float, bool]:
        if not enabled or motor.tripped:
            return 0.0, 0.0, False
        cfg = self.drive
        desired = self._command / (cfg.torque_constant_Nm_A * self._ratio)
        limit = self._thermal_current_limit(motor.temperature_C)
        target = max(-limit, min(limit, desired))
        error = target - motor.current_A
        integral = motor.integral_V + cfg.current_ki_ohm_s * error * h
        voltage = cfg.resistance_ohm * target + cfg.torque_constant_Nm_A * speed + cfg.current_kp_ohm * error + integral
        saturated = abs(voltage) > cfg.supply_voltage_V or abs(desired) > limit
        if (voltage > cfg.supply_voltage_V and error > 0) or (voltage < -cfg.supply_voltage_V and error < 0):
            integral = motor.integral_V
            voltage = cfg.resistance_ohm * target + cfg.torque_constant_Nm_A * speed + cfg.current_kp_ohm * error + integral
        return max(-cfg.supply_voltage_V, min(cfg.supply_voltage_V, voltage)), integral, saturated

    def _electrical_step(self, motor: DriveState, voltage: float, speed: float,
                         gain: float, h: float, enabled: bool, integral: float,
                         saturated: bool) -> DriveState:
        cfg = self.drive
        coil_r = self._resistance(motor.temperature_C)
        if not enabled:
            voltage, integral = 0.0, 0.0
        resistance = coil_r + (0.0 if enabled else cfg.freewheel_resistance_ohm)
        kt = cfg.torque_constant_Nm_A * self.parameters.motor_efficiency * gain
        tripped = motor.tripped or motor.temperature_C >= cfg.trip_temperature_C
        if tripped:
            enabled, voltage, integral = False, 0.0, 0.0
            resistance = coil_r + cfg.freewheel_resistance_ohm
        if enabled:
            # The current regulator alters voltage, never clips stored current.
            # Bounds are imposed on the exact interval endpoint.
            e = math.exp(-resistance * h / cfg.inductance_H)
            one_minus = -math.expm1(-resistance * h / cfg.inductance_H)
            limit = max(abs(motor.current_A), self._thermal_current_limit(motor.temperature_C))
            low = kt * speed + resistance * (-limit - motor.current_A * e) / one_minus
            high = kt * speed + resistance * (limit - motor.current_A * e) / one_minus
            lower, upper = max(-cfg.supply_voltage_V, low), min(cfg.supply_voltage_V, high)
            if lower > upper:
                # Overspeed/back-EMF can make a powered current bound infeasible.
                # Disconnect into the declared dissipative circuit and latch it.
                enabled, tripped, voltage, integral = False, True, 0.0, 0.0
                resistance = coil_r + cfg.freewheel_resistance_ohm
            else:
                limited = max(lower, min(upper, voltage))
                saturated = saturated or abs(limited - voltage) > 1e-10
                voltage = limited
        result = electrical_interval(motor.current_A, voltage, speed, resistance,
                                     cfg.inductance_H, kt, h)
        copper = coil_r * result["current_squared_integral_A2_s"]
        dump = (resistance - coil_r) * result["current_squared_integral_A2_s"]
        decay = math.exp(-h / (cfg.coil_heat_capacity_J_K * cfg.thermal_resistance_K_W))
        temperature = (self.parameters.temperature_C + (motor.temperature_C - self.parameters.temperature_C) * decay
                       + copper / h * cfg.thermal_resistance_K_W * (1 - decay))
        return DriveState(result["current_A"], temperature, integral, voltage,
                          motor.electrical_energy_J + result["terminal_energy_J"],
                          motor.copper_loss_J + copper, motor.dump_loss_J + dump,
                          motor.shaft_work_J + result["shaft_work_J"],
                          motor.initial_inductive_energy_J, saturated, tripped)

    def _force(self, motor: DriveState, gain: float) -> float:
        return self.drive.torque_constant_Nm_A * self.parameters.motor_efficiency * gain * self._ratio * motor.current_A

    @property
    def brake_engaged(self) -> bool:
        return (self.drive.brake_capacity_Nm > 0 and (not self._powered or self._trip_latched)
                and self.state.time_s >= self._brake_deadline - 1e-12)

    def advance(self, command_N_each: float, dt_s: float, *, powered: bool = True) -> dict[str, Any]:
        finite(command_N_each, "command_N_each", -1e6, 1e6)
        finite(dt_s, "dt_s", 0, .02)
        if dt_s == 0:
            raise ValueError("dt_s must be positive")
        if not isinstance(powered, bool):
            raise ValueError("powered must be boolean")
        cap = min(MAX_FORCE_N, self.parameters.motor_force_max_N_each)
        requested = max(-cap, min(cap, command_N_each)) if powered else 0.0
        began, finish = self.state.time_s, self.state.time_s + dt_s
        if powered != self._powered:
            self._command_queue.clear()
            self._command = 0.0
            if not powered and not self._trip_latched:
                self._brake_deadline = began + self.drive.brake_delay_s
            self._powered = powered
        if powered:
            self._command_queue.append((began + self.sensors.command_delay_s, requested))
        else:
            self._command = 0.0
        saturated = powered and abs(command_N_each) > cap
        contacts: list[dict[str, Any]] = []
        work = friction = impact = 0.0
        peak = abs(self.state.velocity_rad_s)
        while self.state.time_s < finish - 1e-14:
            now = self.state.time_s
            while self._command_queue and self._command_queue[0][0] <= now + 1e-12:
                _, self._command = self._command_queue.popleft()
            end = min(finish, now + self._internal_step_bound(), self._next_sample_time)
            if self._command_queue and self._command_queue[0][0] > now + 1e-12:
                end = min(end, self._command_queue[0][0])
            if (not powered or self._trip_latched) and self._brake_deadline > now + 1e-12:
                end = min(end, self._brake_deadline)
            h = end - now
            if h <= 1e-14:
                self._next_sample_time += self.sensors.sample_period_s
                continue
            old = self.state
            arm = geometry(old.angle_rad, self.parameters)["lever_m"]
            speed = self._ratio * arm * old.velocity_rad_s
            drive_enabled = powered and not self._trip_latched
            commands = [self._voltage_command(motor, speed, h, drive_enabled) for motor in self._motors]
            half = [self._electrical_step(motor, voltage, speed, gain, h / 2, drive_enabled, integral, limited)
                    for motor, gain, (voltage, integral, limited) in zip(self._motors, self.side_effectiveness, commands)]
            mean_force = sum(self._force(motor, gain) for motor, gain in zip(half, self.side_effectiveness)) / 2
            trips = any(motor.tripped for motor in half)
            if trips and not self._trip_latched:
                self._trip_latched = True
                self._brake_deadline = now + self.drive.brake_delay_s
            brake = (not powered or self._trip_latched) and now >= self._brake_deadline - 1e-12
            if self._fixture_active:
                step = {"angle_rad": old.angle_rad, "velocity_rad_s": 0.0, "mechanical_work_signed_J": 0.0,
                        "mechanical_work_abs_J": 0.0, "friction_dissipation_J": 0.0,
                        "impact_dissipation_J": 0.0, "peak_speed_rad_s": 0.0, "contacts": []}
            else:
                step = advance_mechanics(old.angle_rad, old.velocity_rad_s, mean_force, mean_force,
                                         h, self.parameters, powered=not brake,
                                         closing_extra=self.closing_friction_extra_Nm)
            next_arm = geometry(step["angle_rad"], self.parameters)["lever_m"]
            next_speed = self._ratio * next_arm * step["velocity_rad_s"]
            motors = [self._electrical_step(motor, voltage, next_speed, gain, h / 2, drive_enabled and not self._trip_latched,
                                           integral, limited or motor.saturated)
                      for motor, gain, (voltage, integral, limited) in zip(half, self.side_effectiveness, commands)]
            shaft_delta = sum(new.shaft_work_J - old_m.shaft_work_J for new, old_m in zip(motors, self._motors))
            self._coupling_residual_J += shaft_delta - step["mechanical_work_signed_J"]
            mean_v = .5 * (old.velocity_rad_s + step["velocity_rad_s"])
            mean_arm = .5 * (arm + next_arm)
            self._axial_dissipation_J += 2 * self.parameters.strut_damping_N_s_m_each * (mean_arm * mean_v)**2 * h
            self._motors = motors
            if any(motor.tripped for motor in motors) and not self._trip_latched:
                self._trip_latched = True
                self._brake_deadline = end + self.drive.brake_delay_s
            final_force = sum(self._force(motor, gain) for motor, gain in zip(motors, self.side_effectiveness)) / 2
            self.state = RigState(end, step["angle_rad"], step["velocity_rad_s"], final_force,
                                  old.mechanical_work_abs_J + step["mechanical_work_abs_J"])
            saturated = saturated or any(motor.saturated for motor in motors)
            for contact in step["contacts"]:
                contacts.append({**contact, "time_offset_s": now - began + contact["time_offset_s"]})
            peak = max(peak, step["peak_speed_rad_s"])
            work += step["mechanical_work_signed_J"]
            friction += step["friction_dissipation_J"]
            impact += step["impact_dissipation_J"]
            if end >= self._next_sample_time - 1e-12:
                self._sample_number += 1
                if self.sensors.dropout_probability and self._rng.random() < self.sensors.dropout_probability:
                    self._dropped_samples += 1
                else:
                    clean, noisy = self._instrument_sample()
                    self._pending_samples.append((end + self.sensors.latency_s, clean, noisy))
                self._next_sample_time += self.sensors.sample_period_s
            self._publish_samples()
        return {"command_N_each": requested, "saturated": saturated,
                "contact": contacts[0] if contacts else None, "contacts": contacts,
                "speed_breach": peak > min(MAX_SPEED_RAD_S, self.parameters.speed_limit_rad_s),
                "precontact_speed_rad_s": peak, "friction_dissipation_J": friction,
                "impact_dissipation_J": impact, "mechanical_work_signed_J": work,
                "drive_trip": self._trip_latched}

    def fixture(self, angle_rad: float = math.radians(20), duration_s: float = .1) -> None:
        finite(angle_rad, "fixture angle", 0, self.parameters.max_angle_rad)
        finite(duration_s, "fixture duration", .001, 10)
        self.state = replace(self.state, angle_rad=angle_rad, velocity_rad_s=0.0, motor_force_N_each=0.0)
        self._motors = [replace(motor, current_A=0.0, integral_V=0.0, voltage_V=0.0,
                                dump_loss_J=motor.dump_loss_J + .5 * self.drive.inductance_H * motor.current_A**2)
                        for motor in self._motors]
        self._fixture_active = True
        try:
            end = self.state.time_s + duration_s
            while self.state.time_s < end - 1e-13:
                self.advance(0.0, min(.02, end - self.state.time_s), powered=False)
        finally:
            self._fixture_active = False

    def telemetry(self) -> dict[str, Any]:
        g = geometry(self.state.angle_rad, self.parameters)
        speed = self._ratio * g["lever_m"] * self.state.velocity_rad_s
        angle = self._ratio * (g["length_m"] - self._closed_length)
        result: dict[str, Any] = {"brake_engaged": self.brake_engaged,
                                  "sensor_age_s": self.observe(noisy=False)["sensor_age_s"],
                                  "coupling_residual_J": self._coupling_residual_J,
                                  "axial_dissipation_J": self._axial_dissipation_J,
                                  "dropped_sensor_samples": self._dropped_samples}
        for side, motor, gain in zip(("left", "right"), self._motors, self.side_effectiveness):
            values = {"current_A": motor.current_A, "voltage_V": motor.voltage_V,
                      "motor_speed_rad_s": speed, "rotor_angle_rad": angle,
                      "temperature_C": motor.temperature_C, "force_N": self._force(motor, gain),
                      "supply_power_W": motor.voltage_V * motor.current_A,
                      "electrical_energy_J": motor.electrical_energy_J,
                      "copper_loss_J": motor.copper_loss_J, "dump_loss_J": motor.dump_loss_J,
                      "shaft_work_J": motor.shaft_work_J,
                      "inductive_energy_J": .5 * self.drive.inductance_H * motor.current_A**2,
                      "initial_inductive_energy_J": motor.initial_inductive_energy_J,
                      "drive_saturated": motor.saturated, "drive_tripped": motor.tripped}
            result.update({side + "_" + key: value for key, value in values.items()})
        return result
