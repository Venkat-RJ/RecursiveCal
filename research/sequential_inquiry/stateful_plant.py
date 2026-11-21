"""Synthetic stateful actuator for investigation of experiment order and model adequacy.

Independent mechanical fixture resets are assumed between tests, but a hidden
thermal-friction state persists. The scalar dynamics and coefficients are an
exploratory construction, NOT a measured actuator or a validated digital twin.
No learning, system discovery or safe real-hardware operation is claimed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Callable

DT = .02
LIMIT_X = .50
LIMIT_V = .75
LIMIT_TORQUE = .85
MAX_PROBES = 3
MAX_COST = 3.5


@dataclass(frozen=True)
class Plant:
    motor: float = 1.
    friction: float = .10
    load: float = .12
    damping: float = .23
    sensor_bias: float = 0.
    thermal_friction: float = 0.
    directional_asymmetry: float = 0.


@dataclass(frozen=True)
class Probe:
    name: str
    torque: float
    fixture_x: float = 0.
    seconds: float = .5
    cost: float = 1.
    reference: bool = False


PROBES = (
    Probe("pulse_pos_low", .45), Probe("pulse_neg_low", -.45),
    Probe("pulse_pos_high", .85), Probe("pulse_neg_high", -.85),
    Probe("pulse_pos_offset", .65, .25), Probe("pulse_neg_offset", -.65, -.25),
    Probe("reference_check", 0., 0., 0., 1.5, True),
)
PROBE_BY_NAME = {p.name: p for p in PROBES}


@dataclass(frozen=True)
class Calibration:
    gain: float
    friction_ff: float
    sensor_offset: float


CALIBRATIONS = tuple(Calibration(g, f, b)
                     for b in (-.08, -.04, 0., .04, .08)
                     for f in (0., .08, .16, .24, .32)
                     for g in (.75, .90, 1., 1.12, 1.25, 1.40))
EVAL_TRAJECTORIES = ((-.15, .28), (.15, -.28), (-.05, .32), (.05, -.32))


def _clip(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


def _accel(plant: Plant, x: float, v: float, torque: float, heat: float) -> float:
    shape = math.tanh(v / .035)
    asym = 1. + plant.directional_asymmetry * (1. if v > 0 else 0.)
    friction = plant.friction * (1. + plant.thermal_friction * heat) * asym * shape
    return (plant.motor * torque - friction - plant.damping * v
            - plant.load * math.sin(math.pi * x / 1.1))


def _advance_heat(heat: float, torque: float) -> float:
    # Synthetic unitless first-order dissipation and resistive heating.
    return heat + DT * (2.0 * torque * torque - .15 * heat)


def pulse(plant: Plant, probe: Probe, heat: float) -> tuple[tuple[float, float], float, bool]:
    """Run a guarded pulse. Mechanical state resets; heat remains coupled."""
    if probe.reference or abs(probe.torque) > LIMIT_TORQUE or abs(probe.fixture_x) > .30 \
            or not 0 < probe.seconds <= .60:
        raise ValueError("Invalid or unsafe pulse command")
    x, v = probe.fixture_x, 0.
    guarded = False
    for _ in range(int(round(probe.seconds / DT))):
        a = _accel(plant, x, v, probe.torque, heat)
        new_v = v + a * DT
        new_x = x + new_v * DT
        if abs(new_v) > LIMIT_V or abs(new_x) > LIMIT_X:
            guarded = True
            break
        x, v = new_x, new_v
        heat = _advance_heat(heat, probe.torque)
    return (x - probe.fixture_x, v), heat, guarded


def terminal_quality(plant: Plant, calibration: Calibration) -> float:
    """Evaluator-only cold-start calibration quality; no probe-heating benefit.

    Every candidate faces the same ambient starting state regardless of probes.
    This isolates the information gained by testing from temporary heating.
    """
    total = 0.
    for start, target in EVAL_TRAJECTORIES:
        x, v, heat, effort, tracking, guarded = start, 0., 0., 0., 0., False
        for _ in range(int(1.8 / DT)):
            error = target - (x + plant.sensor_bias - calibration.sensor_offset)
            raw = calibration.gain * (3.1 * error - 1.25 * v
                                      + calibration.friction_ff * math.tanh(error / .045))
            torque = _clip(raw, LIMIT_TORQUE)
            acceleration = _accel(plant, x, v, torque, heat)
            nv, nx = v + acceleration * DT, x + (v + acceleration * DT) * DT
            if abs(nx) >= LIMIT_X or abs(nv) >= LIMIT_V:
                guarded = True
                break
            x, v = nx, nv
            heat = _advance_heat(heat, torque)
            tracking += abs(target - x) * DT
            effort += abs(torque) * DT
        total += (3.8 * abs(x - target) + .45 * abs(v) + .05 * tracking
                  + .006 * effort + 3.0 * int(guarded))
    return math.exp(-total / len(EVAL_TRAJECTORIES))


def sample_plant(seed: int, split: str) -> Plant:
    """Seed-separated synthetic families. Directional asymmetry is held out."""
    if split not in ("train", "validation", "finite_test", "directional_shift"):
        raise ValueError("Unknown split")
    salts = {"train": 101, "validation": 211, "finite_test": 307, "directional_shift": 401}
    rng = random.Random(seed * 1009 + salts[split])
    params = dict(motor=rng.uniform(.90, 1.04), friction=rng.uniform(.09, .15),
                  load=rng.uniform(.10, .16), damping=rng.uniform(.20, .27),
                  sensor_bias=rng.uniform(-.008, .008))
    family = rng.choice(("nominal", "weak_motor", "high_friction", "high_load",
                         "sensor_bias", "thermal"))
    if family == "weak_motor":
        params["motor"] = rng.uniform(.65, .82)
    elif family == "high_friction":
        params["friction"] = rng.uniform(.23, .35)
    elif family == "high_load":
        params["load"] = rng.uniform(.28, .42)
    elif family == "sensor_bias":
        params["sensor_bias"] = rng.choice((-1, 1)) * rng.uniform(.04, .08)
    elif family == "thermal":
        params["thermal_friction"] = rng.uniform(2.5, 5.)
    if split == "directional_shift":
        params["directional_asymmetry"] = rng.uniform(.5, 1.2)
    return Plant(**params)


class StatefulEpisode:
    """No privileged data is returned by ``observe`` or ``step``."""

    def __init__(self, seed: int, split: str = "train", noise_scale: float = 1.):
        if noise_scale < 0:
            raise ValueError("Negative noise scale")
        self._plant = sample_plant(seed, split)
        self._rng = random.Random(seed * 43 + 112)
        self._noise_scale = noise_scale
        self._heat = 0.
        self._used: set[str] = set()
        self._records: list[dict] = []
        self._cost = 0.
        self._ended = False
        self._scored = False

    def legal_actions(self) -> list[str]:
        if self._ended:
            return []
        result = ["STOP"]
        if len(self._used) < MAX_PROBES:
            result.extend(probe.name for probe in PROBES
                          if probe.name not in self._used
                          and self._cost + probe.cost <= MAX_COST + 1e-12)
        return result

    def observe(self) -> dict:
        if self._ended:
            raise ValueError("Episode finished")
        return {"measurements": [self._public_record(r) for r in self._records],
                "legal_actions": self.legal_actions(),
                "remaining_budget": MAX_COST - self._cost}

    @staticmethod
    def _public_record(record: dict) -> dict:
        # Never expose the mutable list inside the evaluator's record.
        return {**record, "observed": list(record["observed"])}

    def step(self, action: str) -> dict | None:
        if action not in self.legal_actions():
            raise ValueError("Illegal, repeated, over-budget, or finished action")
        if action == "STOP":
            self._ended = True
            return None
        probe = PROBE_BY_NAME[action]
        if probe.reference:
            expected, guarded = (self._plant.sensor_bias,), False
            # Reference requires no motor torque and its fixture is independent.
        else:
            reading, self._heat, guarded = pulse(self._plant, probe, self._heat)
            expected = reading
        sigmas = (.006,) if probe.reference else (.004, .009)
        observed = [float(m + self._rng.gauss(0, sigma * self._noise_scale))
                    for m, sigma in zip(expected, sigmas)]
        record = {"probe": action, "observed": observed, "cost": probe.cost,
                  "guarded": bool(guarded)}
        self._records.append(record)
        self._used.add(action)
        self._cost += probe.cost
        return self._public_record(record)

    def finish(self, calibration: Calibration) -> dict:
        if not self._ended or self._scored or calibration not in CALIBRATIONS:
            raise ValueError("Must STOP and choose a single legal terminal calibration")
        self._scored = True
        quality = terminal_quality(self._plant, calibration)
        return {"quality": quality, "reward": quality - .012 * self._cost,
                "cost": self._cost, "probes": len(self._used),
                "guarded_probes": sum(r["guarded"] for r in self._records)}


def rollout(seed: int, split: str, policy: Callable[[dict], str],
            calibration: Calibration) -> dict:
    ep = StatefulEpisode(seed, split)
    while True:
        state = ep.observe()
        action = policy(state)  # Observed-only state, no environment object.
        ep.step(action)
        if action == "STOP":
            return ep.finish(calibration)
