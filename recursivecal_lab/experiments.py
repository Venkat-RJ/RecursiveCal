"""Reproducible, deliberately limited diagnostic decision experiments.

This module evaluates the frozen normalized v0.2 model. It is not the SI
liftgate simulator, a hardware controller, or a claim of physical validity.
The learned policy is a two-stage contextual bandit with a fixed first probe.
All action selection receives observed features only. The evaluator alone owns
hidden plants and counterfactual reward tables.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import itertools
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.polynomial.hermite import hermgauss

import recursivecal as legacy


SCHEMA_VERSION = "recursivecal.experiment.v1"
MODEL_ID = "recursivecal-normalized-v0.2"
COST_COEFFICIENT = 0.012
FIRST_PROBE = 0
SECOND_ACTIONS = (-1, 1, 2, 3, 4, 5, 6)
ACTION_NAMES = ["STOP" if a < 0 else legacy.PROBES[a].name for a in SECOND_ACTIONS]
SPLIT_SEEDS = {
    "train": 3100261121,
    "validation": 3200261121,
    "finite_test": 3300261121,
    "continuous_jitter": 3400261121,
    "unseen_high_load": 3500261121,
    "extreme_deadzone": 3600261121,
    "directional_friction": 3700261121,
    "shuffle": 3800261121,
    "bootstrap": 3900261121,
}


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_plants() -> tuple[legacy.Plant, ...]:
    """A published exploratory finite prior; every coefficient is synthetic."""
    P = legacy.Plant
    return (
        P(), P(motor=.98, friction=.12, load=.13),
        P(sensor_bias=.075), P(sensor_bias=-.075),
        P(motor=.69, friction=.115), P(motor=.78, friction=.12),
        P(motor=.92, friction=.30, load=.14),
        P(motor=.95, friction=.27, load=.14),
        P(motor=.91, friction=.14, load=.14, torque_deadzone=.25),
        P(motor=1.02, friction=.17, load=.14, torque_deadzone=.31),
    )


def _plant_array(plants: tuple[legacy.Plant, ...] | list[legacy.Plant]) -> np.ndarray:
    return np.array([[p.motor, p.friction, p.load, p.damping,
                      p.sensor_bias, p.torque_deadzone] for p in plants], dtype=float)


def _acceleration(parameters: np.ndarray, x: np.ndarray, v: np.ndarray,
                  torque: np.ndarray | float, asymmetry: np.ndarray) -> np.ndarray:
    delivered = np.sign(torque) * np.maximum(0.0, np.abs(torque) - parameters[..., 5])
    friction_shape = np.tanh(v / .035)
    return (parameters[..., 0] * delivered
            - parameters[..., 1] * (friction_shape + asymmetry * np.maximum(friction_shape, 0.0))
            - parameters[..., 3] * v
            - parameters[..., 2] * np.sin(np.pi * x / 1.1))


def quality_matrix(parameters: np.ndarray, asymmetry: np.ndarray | None = None) -> np.ndarray:
    """Vectorized parity implementation of all 150 frozen calibrations.

    asymmetry=0 reproduces legacy.calibration_quality. A positive asymmetry
    adds direction-dependent friction in a separate structural-shift cohort.
    It never changes the inference prior or the historical model.
    """
    parameters = np.asarray(parameters, dtype=float)
    if parameters.ndim != 2 or parameters.shape[1] != 6 or not np.isfinite(parameters).all():
        raise ValueError("Expected finite plant parameters with shape (n, 6)")
    n = len(parameters)
    asymmetry = np.zeros(n) if asymmetry is None else np.asarray(asymmetry, dtype=float)
    if asymmetry.shape != (n,) or not np.isfinite(asymmetry).all():
        raise ValueError("Expected finite asymmetry with shape (n,)")
    c = np.array([[x.gain, x.friction_ff, x.sensor_offset] for x in legacy.CALIBRATIONS])
    p = parameters[:, None, :]
    shape = (n, len(c))
    loss = np.zeros(shape)
    for start, target in legacy.EVAL_TRAJECTORIES:
        x = np.full(shape, start)
        v = np.zeros(shape)
        active = np.ones(shape, dtype=bool)
        intervention = np.zeros(shape)
        effort = np.zeros(shape)
        tracking = np.zeros(shape)
        for _ in range(int(1.8 / legacy.DT)):
            error = target - (x + p[..., 4] - c[None, :, 2])
            torque = np.clip(c[None, :, 0] * (3.1 * error - 1.25 * v
                              + c[None, :, 1] * np.tanh(error / .045)),
                              -legacy.TORQUE_LIMIT, legacy.TORQUE_LIMIT)
            acceleration = _acceleration(p, x, v, torque, asymmetry[:, None])
            nv = v + acceleration * legacy.DT
            nx = x + nv * legacy.DT
            unsafe = active & ((np.abs(nx) >= legacy.POSITION_LIMIT) | (np.abs(nv) >= legacy.SPEED_LIMIT))
            intervention += unsafe
            active &= ~unsafe
            x = np.where(active, nx, x)
            v = np.where(active, nv, v)
            tracking += np.where(active, np.abs(target - x) * legacy.DT, 0)
            effort += np.where(active, np.abs(torque) * legacy.DT, 0)
        loss += (3.8 * np.abs(x - target) + .45 * np.abs(v) + .05 * tracking
                 + .006 * effort + 3.0 * intervention)
    return np.exp(-loss / len(legacy.EVAL_TRAJECTORIES))


def probe_means(parameters: np.ndarray, asymmetry: np.ndarray | None = None) -> np.ndarray:
    """Frozen pulse timing, including its documented 0.55 -> 0.56 s behavior."""
    n = len(parameters)
    asymmetry = np.zeros(n) if asymmetry is None else asymmetry
    means = np.zeros((n, len(legacy.PROBES), 2))
    for a, probe in enumerate(legacy.PROBES):
        if probe.kind == "reference":
            means[:, a, 0] = parameters[:, 4]
            continue
        x = np.full(n, probe.fixture_x)
        v = np.zeros(n)
        active = np.ones(n, dtype=bool)
        for _ in range(int(round(probe.seconds / legacy.DT))):
            acceleration = _acceleration(parameters, x, v, probe.torque, asymmetry)
            nv = v + acceleration * legacy.DT
            nx = x + nv * legacy.DT
            active &= (np.abs(nv) <= legacy.SPEED_LIMIT) & (np.abs(nx) <= legacy.POSITION_LIMIT)
            x = np.where(active, nx, x)
            v = np.where(active, nv, v)
        means[:, a, 0] = x - probe.fixture_x
        means[:, a, 1] = v
    return means


@dataclass
class EvaluationData:
    """Evaluator-only data. Never passed to a learned decision function."""
    cohort: str
    observations: np.ndarray
    parameters: np.ndarray
    asymmetry: np.ndarray
    quality: np.ndarray
    episode_ids: list[str]


class FiniteBank:
    """Finite-prior posterior inference and numerically integrated decisions."""
    def __init__(self, quadrature_order: int = 15):
        if quadrature_order < 2 or quadrature_order > 15:
            raise ValueError("quadrature_order must be between 2 and 15")
        self.parameters = _plant_array(_model_plants())
        self.prior = np.full(len(self.parameters), 1 / len(self.parameters))
        self.means = probe_means(self.parameters)
        self.quality = quality_matrix(self.parameters)
        self.sigma = np.array([(.006, 1.0) if p.kind == "reference" else (.004, .009)
                               for p in legacy.PROBES])
        self.dimensions = np.array([1 if p.kind == "reference" else 2 for p in legacy.PROBES])
        self.costs = np.array([p.cost for p in legacy.PROBES])
        self.quadrature_order = quadrature_order
        self._grids: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.prior_calibration = int((self.prior @ self.quality).argmax())
        # Remove only globally dominated choices. They cannot maximize any
        # nonnegative posterior-weighted score, preserving the Bayes optimum.
        dominated = np.zeros(self.quality.shape[1], dtype=bool)
        for j in range(self.quality.shape[1]):
            dominates = np.all(self.quality >= self.quality[:, j:j+1], axis=0)
            strictly = np.any(self.quality > self.quality[:, j:j+1], axis=0)
            dominated[j] = bool(np.any(dominates & strictly))
        self._efficient_quality = self.quality[:, ~dominated]

    def posterior(self, belief: np.ndarray, measured: np.ndarray, action: int) -> np.ndarray:
        d = int(self.dimensions[action])
        measured = np.asarray(measured, dtype=float)
        if measured.ndim != 2 or measured.shape[1] < d or not np.isfinite(measured).all():
            raise ValueError("Probe observations must be a finite two-dimensional array")
        residual = (measured[:, None, :d] - self.means[None, :, action, :d]) / self.sigma[action, :d]
        logp = np.log(np.maximum(belief, 1e-300)) - .5 * np.sum(residual ** 2, axis=2)
        logp -= logp.max(axis=1, keepdims=True)
        posterior = np.exp(logp)
        return posterior / posterior.sum(axis=1, keepdims=True)

    def first_beliefs(self, observed_first: np.ndarray) -> np.ndarray:
        belief = np.broadcast_to(self.prior, (len(observed_first), len(self.prior)))
        return self.posterior(belief, observed_first, FIRST_PROBE)

    def features(self, observed_first: np.ndarray) -> np.ndarray:
        observed_first = np.asarray(observed_first, dtype=float)
        if observed_first.ndim != 2 or observed_first.shape[1] != 2:
            raise ValueError("Only the first probe's two observed values are policy input")
        posterior = self.first_beliefs(observed_first)
        return np.column_stack((observed_first / np.array([.15, .4]), posterior * 4))

    def mismatch_distance(self, observed_first: np.ndarray) -> np.ndarray:
        residual = ((observed_first[:, None, :] - self.means[None, :, FIRST_PROBE, :])
                    / self.sigma[FIRST_PROBE])
        return np.sqrt(np.square(residual).sum(axis=2).min(axis=1))

    def _grid(self, action: int) -> tuple[np.ndarray, np.ndarray]:
        if action in self._grids:
            return self._grids[action]
        nodes, weights = hermgauss(self.quadrature_order)
        nodes, weights = nodes * np.sqrt(2), weights / np.sqrt(np.pi)
        d = int(self.dimensions[action])
        combinations = list(itertools.product(range(self.quadrature_order), repeat=d))
        noise = np.array([[nodes[i] for i in combo] for combo in combinations])
        integration_weight = np.array([np.prod([weights[i] for i in combo]) for combo in combinations])
        points = (self.means[:, action, :d, None] + self.sigma[action, :d, None] * noise.T[None])
        points = points.transpose(0, 2, 1).reshape(-1, d)
        residual = (points[:, None, :] - self.means[None, :, action, :d]) / self.sigma[action, :d]
        logp = -.5 * np.square(residual).sum(axis=2)
        logp -= logp.max(axis=1, keepdims=True)
        self._grids[action] = (np.exp(logp), integration_weight)
        return self._grids[action]

    def bayesian_second_actions(self, observed_first: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        belief = self.first_beliefs(observed_first)
        values = np.empty((len(belief), len(SECOND_ACTIONS)))
        values[:, 0] = (belief @ self._efficient_quality).max(axis=1)
        for column, action in enumerate(SECOND_ACTIONS[1:], start=1):
            likelihood, weights = self._grid(action)
            for begin in range(0, len(belief), 32):
                b = belief[begin:begin+32]
                unnormalized = b[:, None, :] * likelihood[None]
                posterior = unnormalized / np.maximum(unnormalized.sum(axis=2, keepdims=True), 1e-300)
                best = (posterior @ self._efficient_quality).max(axis=2)
                expected = (best.reshape(len(b), len(self.prior), len(weights)) * weights).sum(axis=2)
                values[begin:begin+len(b), column] = (expected * b).sum(axis=1) - COST_COEFFICIENT * self.costs[action]
        optional = np.asarray(SECOND_ACTIONS)[values.argmax(axis=1)]
        forced = np.asarray(SECOND_ACTIONS[1:])[values[:, 1:].argmax(axis=1)]
        return optional, forced

    def make_data(self, size: int, split: str) -> EvaluationData:
        if split not in SPLIT_SEEDS or split in ("shuffle", "bootstrap"):
            raise ValueError("Unknown evaluation split")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("Data size must be a positive integer")
        rng = np.random.default_rng(SPLIT_SEEDS[split])
        choice = rng.integers(0, len(self.parameters), size)
        parameters = self.parameters[choice].copy()
        asymmetry = np.zeros(size)
        if split == "continuous_jitter":
            parameters += rng.normal(size=parameters.shape) * np.array([.025, .012, .018, .018, .004, .01])
            parameters[:, 5] = np.maximum(parameters[:, 5], 0)
        elif split == "unseen_high_load":
            parameters = np.tile(self.parameters[0], (size, 1))
            parameters[:, 0] = rng.uniform(.90, 1.0, size)
            parameters[:, 1] = rng.uniform(.09, .15, size)
            parameters[:, 2] = rng.uniform(.29, .46, size)
            parameters[:, 3] = rng.uniform(.20, .27, size)
        elif split == "extreme_deadzone":
            parameters = np.tile(self.parameters[0], (size, 1))
            parameters[:, 0] = rng.uniform(.68, .92, size)
            parameters[:, 1] = rng.uniform(.13, .22, size)
            parameters[:, 2] = rng.uniform(.1, .16, size)
            parameters[:, 5] = rng.uniform(.37, .48, size)
        elif split == "directional_friction":
            parameters[:, 1] *= rng.uniform(.9, 1.1, size)
            asymmetry = rng.uniform(.5, 1.2, size)
        observations = probe_means(parameters, asymmetry) + rng.normal(size=(size, 7, 2)) * self.sigma[None]
        observations[:, 6, 1] = 0.0  # the reference has exactly one observed coordinate
        quality = (self.quality[choice] if split in ("train", "validation", "finite_test")
                   else quality_matrix(parameters, asymmetry))
        ids = [f"{split}:{SPLIT_SEEDS[split]}:{i}" for i in range(size)]
        return EvaluationData(split, observations, parameters, asymmetry, quality, ids)

    def score(self, data: EvaluationData, first: int = -1, second: np.ndarray | None = None,
              abstain: np.ndarray | None = None) -> dict[str, np.ndarray]:
        n = len(data.episode_ids)
        second = np.full(n, -1, dtype=int) if second is None else np.asarray(second, dtype=int)
        if second.shape != (n,) or np.any(second < -1) or np.any(second >= 7):
            raise ValueError("Invalid second actions")
        if first < -1 or first >= 7 or (first == -1 and np.any(second != -1)):
            raise ValueError("Invalid first action")
        if first >= 0 and np.any(second == first):
            raise ValueError("Repeated probe is disallowed")
        beliefs = np.broadcast_to(self.prior, (n, len(self.prior))).copy()
        costs = np.zeros(n)
        probes = np.zeros(n, dtype=int)
        if first >= 0:
            beliefs = self.posterior(beliefs, data.observations[:, first], first)
            costs += self.costs[first]
            probes += 1
        for action in range(7):
            selected = second == action
            if selected.any():
                beliefs[selected] = self.posterior(beliefs[selected], data.observations[selected, action], action)
                costs[selected] += self.costs[action]
                probes[selected] += 1
        if np.any(costs > 2.5 + 1e-12):
            raise ValueError("This protocol allows at most two unique probes and cost 2.5")
        calibration = (beliefs @ self.quality).argmax(axis=1)
        abstain = np.zeros(n, dtype=bool) if abstain is None else np.asarray(abstain, dtype=bool)
        if abstain.shape != (n,):
            raise ValueError("Invalid abstention mask")
        calibration[abstain] = self.prior_calibration
        quality = data.quality[np.arange(n), calibration]
        return {"reward": quality - COST_COEFFICIENT * costs, "quality": quality,
                "cost": costs, "probes": probes, "calibration": calibration,
                "first": np.full(n, first), "second": second.copy(), "abstained": abstain}


class ContextualBandit:
    """NumPy MLP trained from selected-action reward observations only.

    Replayed contexts are finite synthetic training samples. This is not an
    online long-horizon RL algorithm. The public predict method accepts only
    observed features and has no data/evaluator parameter.
    """
    def __init__(self, seed: int, feature_count: int = 12, hidden: int = 48):
        rng = np.random.default_rng(seed)
        self.seed = int(seed)
        self.weights = {
            "w1": rng.normal(0, .15, (feature_count, hidden)), "b1": np.zeros(hidden),
            "w2": rng.normal(0, .05, (hidden, len(SECOND_ACTIONS))),
            "b2": np.zeros(len(SECOND_ACTIONS)),
        }
        self.selected_update = 0

    def values(self, observed_features: np.ndarray) -> np.ndarray:
        x = np.asarray(observed_features, dtype=float)
        if x.ndim != 2 or x.shape[1] != self.weights["w1"].shape[0] or not np.isfinite(x).all():
            raise ValueError("Policy requires finite observed feature rows")
        hidden = np.tanh(x @ self.weights["w1"] + self.weights["b1"])
        return hidden @ self.weights["w2"] + self.weights["b2"]

    def actions(self, observed_features: np.ndarray) -> np.ndarray:
        return np.asarray(SECOND_ACTIONS)[self.values(observed_features).argmax(axis=1)]

    def save(self, path: Path) -> None:
        _json_write(path, {"schema_version": "recursivecal.bandit.v1", "model_id": MODEL_ID,
                           "seed": self.seed, "selected_update": self.selected_update,
                           "feature_contract": "first_probe_observed_x_v_scaled_plus_public_posterior",
                           "second_actions": list(SECOND_ACTIONS),
                           "weights": {k: v.tolist() for k, v in self.weights.items()}})

    @classmethod
    def load(cls, path: Path | str) -> "ContextualBandit":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("schema_version") != "recursivecal.bandit.v1" or value.get("model_id") != MODEL_ID:
            raise ValueError("Unsupported checkpoint schema/model")
        if value.get("second_actions") != list(SECOND_ACTIONS):
            raise ValueError("Checkpoint action contract differs")
        weights = {k: np.asarray(value["weights"][k], dtype=float) for k in ("w1", "b1", "w2", "b2")}
        if weights["w1"].ndim != 2 or weights["w1"].shape[0] != 12:
            raise ValueError("Invalid checkpoint input shape")
        hidden = weights["w1"].shape[1]
        if not (1 <= hidden <= 512):
            raise ValueError("Invalid checkpoint width")
        if (weights["b1"].shape != (hidden,) or weights["w2"].shape != (hidden, 7)
                or weights["b2"].shape != (7,) or not all(np.isfinite(w).all() for w in weights.values())):
            raise ValueError("Invalid checkpoint tensors")
        model = cls(int(value["seed"]), hidden=hidden)
        model.weights = weights
        model.selected_update = int(value["selected_update"])
        return model


def _counterfactual_table(bank: FiniteBank, data: EvaluationData) -> np.ndarray:
    return np.column_stack([bank.score(data, FIRST_PROBE, np.full(len(data.episode_ids), a))["reward"]
                            for a in SECOND_ACTIONS])


def train_bandit(bank: FiniteBank, train: EvaluationData, validation: EvaluationData,
                 seed: int, updates: int = 700) -> tuple[ContextualBandit, list[dict[str, Any]]]:
    x = bank.features(train.observations[:, FIRST_PROBE])
    xv = bank.features(validation.observations[:, FIRST_PROBE])
    rewards = _counterfactual_table(bank, train)
    validation_rewards = _counterfactual_table(bank, validation)
    rng = np.random.default_rng(seed)
    model = ContextualBandit(seed)
    moments = {key: np.zeros_like(value) for key, value in model.weights.items()}
    variances = {key: np.zeros_like(value) for key, value in model.weights.items()}
    best_score, best_weights, best_update = -np.inf, None, 0
    log: list[dict[str, Any]] = []
    for update in range(1, updates + 1):
        idx = rng.integers(0, len(x), size=min(128, len(x)))
        xb = x[idx]
        hidden = np.tanh(xb @ model.weights["w1"] + model.weights["b1"])
        prediction = hidden @ model.weights["w2"] + model.weights["b2"]
        actions = prediction.argmax(axis=1)
        epsilon = .55 - .45 * (update - 1) / max(1, updates - 1)
        explore = rng.random(len(idx)) < epsilon
        actions[explore] = rng.integers(0, 7, int(explore.sum()))
        # Only one selected outcome per sampled context enters this update.
        target = (rewards[idx, actions] - .8) * 10
        residual = prediction[np.arange(len(idx)), actions] - target
        grad_out = np.zeros_like(prediction)
        grad_out[np.arange(len(idx)), actions] = 2 * residual / len(idx)
        grad_hidden = (grad_out @ model.weights["w2"].T) * (1 - hidden ** 2)
        gradients = {"w2": hidden.T @ grad_out, "b2": grad_out.sum(axis=0),
                     "w1": xb.T @ grad_hidden, "b1": grad_hidden.sum(axis=0)}
        for key, gradient in gradients.items():
            moments[key] = .9 * moments[key] + .1 * gradient
            variances[key] = .999 * variances[key] + .001 * gradient ** 2
            m = moments[key] / (1 - .9 ** update)
            v = variances[key] / (1 - .999 ** update)
            model.weights[key] -= .0015 * m / (np.sqrt(v) + 1e-8)
        if update % 50 == 0 or update == updates:
            action = model.values(xv).argmax(axis=1)
            score = float(validation_rewards[np.arange(len(xv)), action].mean())
            log.append({"update": update, "epsilon": epsilon, "train_selected_mse": float(np.mean(residual ** 2)),
                        "validation_mean_reward": score})
            if score > best_score + 1e-12:
                best_score, best_update = score, update
                best_weights = {k: v.copy() for k, v in model.weights.items()}
    assert best_weights is not None
    model.weights, model.selected_update = best_weights, best_update
    return model, log


def _summarize(result: dict[str, np.ndarray]) -> dict[str, Any]:
    unique, counts = np.unique(result["second"], return_counts=True)
    return {"n": len(result["reward"]), "mean_reward": float(result["reward"].mean()),
            "mean_quality": float(result["quality"].mean()), "mean_cost": float(result["cost"].mean()),
            "mean_probes": float(result["probes"].mean()),
            "abstention_rate": float(result["abstained"].mean()),
            "action_counts": {"STOP" if a < 0 else legacy.PROBES[a].name: int(count)
                              for a, count in zip(unique, counts)}}


def paired_interval(a: np.ndarray, b: np.ndarray, seed: int, resamples: int = 2000) -> dict[str, Any]:
    a, b = np.asarray(a), np.asarray(b)
    if a.ndim != 1 or a.shape != b.shape or len(a) == 0 or not np.isfinite(a - b).all():
        raise ValueError("Paired scores must be nonempty finite vectors with identical shape")
    d = a - b
    rng = np.random.default_rng(seed)
    samples = np.concatenate([d[rng.integers(0, len(d), (min(100, resamples - i), len(d)))].mean(axis=1)
                              for i in range(0, resamples, 100)])
    return {"mean_difference": float(d.mean()), "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "method": "paired episode percentile bootstrap",
            "resamples": resamples, "seed": seed,
            "scope": "episode uncertainty conditional on this fitted policy; not training-seed uncertainty"}


def _freeze_selection(bank: FiniteBank, train: EvaluationData, validation: EvaluationData) -> dict[str, Any]:
    schedules = [()] + [(a,) for a in range(7)] + list(itertools.combinations(range(7), 2))
    candidates = []
    for schedule in schedules:
        scores = {}
        for name, data in (("train", train), ("validation", validation)):
            n = len(data.episode_ids)
            result = bank.score(data, schedule[0] if schedule else -1,
                                np.full(n, schedule[1] if len(schedule) > 1 else -1))
            scores[name] = float(result["reward"].mean())
        candidates.append({"schedule": list(schedule), "train_mean_reward": scores["train"],
                           "validation_mean_reward": scores["validation"]})
    train_order = sorted(candidates, key=lambda c: (-c["train_mean_reward"], len(c["schedule"]), c["schedule"]))
    shortlist = train_order[:5]
    chosen = sorted(shortlist, key=lambda c: (-c["validation_mean_reward"], len(c["schedule"]), c["schedule"]))[0]
    two = sorted([c for c in candidates if len(c["schedule"]) == 2],
                 key=lambda c: (-c["validation_mean_reward"], c["schedule"]))[0]
    distance = bank.mismatch_distance(validation.observations[:, FIRST_PROBE])
    threshold = float(np.quantile(distance, .95, method="higher"))
    return {"fixed_schedule": chosen["schedule"], "fixed_two_schedule": two["schedule"],
            "candidate_schedules": candidates,
            "selection": "top five schedules on train, select on validation; fixed-two selected on validation",
            "first_probe_for_adaptive_policies": FIRST_PROBE,
            "mismatch_threshold": threshold, "mismatch_quantile": .95,
            "mismatch_fit_split": "validation", "test_used_for_selection": False}


def run_experiment(output_dir: str | Path, train_size: int = 1024, test_size: int = 512,
                   seeds: tuple[int, ...] | list[int] = (13, 37, 103), quick: bool = False) -> dict[str, Any]:
    """Run a complete CPU suite in the foreground and persist its evidence.

    A nonempty destination is rejected to avoid silently replacing a completed
    run. quick caps train/test at 128/64 and updates at 100 for CI only.
    """
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 16 for x in (train_size, test_size)):
        raise ValueError("train_size and test_size must be integers >=16")
    if not seeds or len(set(seeds)) != len(seeds) or any(not isinstance(s, int) or isinstance(s, bool) or s < 0 for s in seeds):
        raise ValueError("Seeds must be distinct nonnegative integers")
    if legacy.DT != .02:
        raise ValueError("The frozen normalized experiment requires legacy.DT == 0.02")
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use a new empty output directory to preserve previous evidence")
    out.mkdir(parents=True, exist_ok=True)
    if quick:
        train_size, test_size = min(train_size, 128), min(test_size, 64)
    validation_size = max(64, train_size // 2)
    updates = 100 if quick else 700
    started = time.perf_counter()
    protocol_path = Path(__file__).resolve().parents[1] / "docs" / "EXPERIMENT_PROTOCOL.md"
    if not protocol_path.is_file():
        protocol_path = Path(__file__).resolve().parent / "data" / "EXPERIMENT_PROTOCOL.md"
    if not protocol_path.is_file():
        raise RuntimeError("The distribution is missing its experiment protocol asset")
    (out / "protocol.md").write_bytes(protocol_path.read_bytes())
    print(f"experiment: build finite prior; train={train_size}, validation={validation_size}, each test={test_size}", flush=True)
    bank = FiniteBank(quadrature_order=3 if quick else 15)
    train = bank.make_data(train_size, "train")
    validation = bank.make_data(validation_size, "validation")
    selections = _freeze_selection(bank, train, validation)
    validation_quadrature = {}
    if not quick:
        print("experiment: validation numerical sensitivity; quadrature orders 5, 9, 15", flush=True)
        for order in (5, 9, 15):
            integration_bank = bank if order == bank.quadrature_order else FiniteBank(order)
            action, _ = integration_bank.bayesian_second_actions(validation.observations[:, FIRST_PROBE])
            score = bank.score(validation, FIRST_PROBE, action)
            validation_quadrature[str(order)] = _summarize(score)
        selections["bayesian_resolution"] = {
            "primary_order": 15,
            "decision": "Use the highest implemented quadrature order; report residual sensitivity, not exact optimality.",
            "validation_results": validation_quadrature,
        }
    models = []
    for seed in seeds:
        print(f"experiment: training observed-feature contextual bandit seed={seed}; updates={updates}", flush=True)
        model, trainlog = train_bandit(bank, train, validation, seed, updates)
        checkpoint = out / "checkpoints" / f"bandit_seed_{seed}.json"
        model.save(checkpoint)
        reloaded = ContextualBandit.load(checkpoint)
        if not np.array_equal(model.actions(bank.features(validation.observations[:, FIRST_PROBE])),
                              reloaded.actions(bank.features(validation.observations[:, FIRST_PROBE]))):
            raise RuntimeError("Checkpoint reload changed validation decisions")
        _json_write(out / "training" / f"seed_{seed}.json", trainlog)
        models.append(reloaded)
    _json_write(out / "selection.json", selections)
    # Written before test generation. This is execution ordering, not a claim
    # of an independently preregistered or blinded study.
    source_paths = [Path(__file__).resolve(), Path(legacy.__file__).resolve()]
    manifest = {
        "schema_version": SCHEMA_VERSION, "model_id": MODEL_ID,
        "scope": "Exploratory synthetic diagnosis. No measured-data training, SI liftgate inference, or hardware validation.",
        "preregistered": False, "quick_ci_run": quick,
        "train_size": train_size, "validation_size": validation_size, "test_size_per_cohort": test_size,
        "training_seeds": list(seeds), "split_seeds": SPLIT_SEEDS,
        "split_disjointness": "unique episode identifiers and RNG streams; finite-support plant values intentionally overlap",
        "policy": "NumPy MLP contextual bandit with fixed first probe; replayed contexts; selected-action reward regression",
        "learning": {"updates": updates, "batch_size_max": 128, "hidden_units": 48,
                     "optimizer": "Adam", "learning_rate": .0015, "epsilon_start": .55, "epsilon_end": .10,
                     "checkpoint_selection": "best validation mean reward every 50 updates"},
        "bayesian_quadrature_order": bank.quadrature_order, "cost_coefficient": COST_COEFFICIENT,
        "maximum_probes": 2, "maximum_cost": 2.5,
        "model_assumptions": {"prior": bank.parameters.tolist(), "prior_probabilities": bank.prior.tolist(),
                              "noise_sigmas": bank.sigma.tolist(), "legacy_dt": legacy.DT,
                              "legacy_055s_pulse_actual_seconds": round(.55 / legacy.DT) * legacy.DT},
        "source_sha256": {"experiments.py": _digest(source_paths[0]), "recursivecal.py": _digest(source_paths[1])},
        "selection_sha256": _digest(out / "selection.json"),
        "protocol_sha256": _digest(out / "protocol.md"),
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "platform": platform.platform(), "byteorder": sys.byteorder},
        "physical_model_validated": False,
    }
    _json_write(out / "manifest.json", manifest)
    all_episode_ids = set(train.episode_ids) | set(validation.episode_ids)
    results: dict[str, Any] = {}
    cohorts = ("finite_test", "continuous_jitter", "unseen_high_load", "extreme_deadzone", "directional_friction")
    episode_rows = []
    observation_rows = []
    for cohort_index, cohort in enumerate(cohorts):
        print(f"experiment: evaluate {cohort}; paired cases={test_size}", flush=True)
        data = bank.make_data(test_size, cohort)
        if all_episode_ids.intersection(data.episode_ids):
            raise RuntimeError("Episode identifier overlap between splits")
        all_episode_ids.update(data.episode_ids)
        optional, forced = bank.bayesian_second_actions(data.observations[:, FIRST_PROBE])
        distance = bank.mismatch_distance(data.observations[:, FIRST_PROBE])
        flagged = distance > selections["mismatch_threshold"]
        permutation = np.random.default_rng(SPLIT_SEEDS["shuffle"] + cohort_index).permutation(test_size)
        scored = {"no_probe_prior_calibration": bank.score(data),
                  "fixed_first_only": bank.score(data, FIRST_PROBE),
                  "bayesian_adaptive": bank.score(data, FIRST_PROBE, optional),
                  "bayesian_forced_two": bank.score(data, FIRST_PROBE, forced),
                  "bayesian_shuffled": bank.score(data, FIRST_PROBE, optional[permutation])}
        quadrature_sensitivity = {str(bank.quadrature_order): {
            "mean_reward": float(scored["bayesian_adaptive"]["reward"].mean()),
            "fraction_actions_differ_from_primary": 0.0, "mean_reward_difference_from_primary": 0.0}}
        if not quick:
            for order in (5, 9):
                alternative, _ = FiniteBank(order).bayesian_second_actions(data.observations[:, FIRST_PROBE])
                alternative_score = bank.score(data, FIRST_PROBE, alternative)
                scored[f"bayesian_order_{order}"] = alternative_score
                quadrature_sensitivity[str(order)] = {
                    "mean_reward": float(alternative_score["reward"].mean()),
                    "fraction_actions_differ_from_primary": float(np.mean(alternative != optional)),
                    "mean_reward_difference_from_primary": float((alternative_score["reward"] - scored["bayesian_adaptive"]["reward"]).mean()),
                }
        for name, key in (("best_fixed", "fixed_schedule"), ("best_fixed_two", "fixed_two_schedule")):
            schedule = selections[key]
            scored[name] = bank.score(data, schedule[0] if schedule else -1,
                                      np.full(test_size, schedule[1] if len(schedule) > 1 else -1))
        guarded = optional.copy()
        guarded[flagged] = -1
        scored["bayesian_abstain"] = bank.score(data, FIRST_PROBE, guarded, flagged)
        x = bank.features(data.observations[:, FIRST_PROBE])
        for model in models:
            actions = model.actions(x)
            name = f"learned_seed_{model.seed}"
            scored[name] = bank.score(data, FIRST_PROBE, actions)
            scored[name + "_shuffled"] = bank.score(data, FIRST_PROBE, actions[permutation])
            if not np.array_equal(np.sort(scored[name]["cost"]), np.sort(scored[name + "_shuffled"]["cost"])):
                raise RuntimeError("Shuffled ablation changed action-cost distribution")
        if not np.array_equal(np.sort(scored["bayesian_adaptive"]["cost"]), np.sort(scored["bayesian_shuffled"]["cost"])):
            raise RuntimeError("Bayesian shuffle changed action-cost distribution")
        comparisons = {}
        pairs = [("bayesian_adaptive", "best_fixed"), ("bayesian_adaptive", "bayesian_shuffled"),
                 ("bayesian_adaptive", "no_probe_prior_calibration"),
                 ("bayesian_forced_two", "best_fixed_two"),
                 ("bayesian_abstain", "bayesian_adaptive")]
        for model in models:
            name = f"learned_seed_{model.seed}"
            pairs += [(name, "best_fixed"), (name, "bayesian_adaptive"), (name, name + "_shuffled")]
        for j, (a, b) in enumerate(pairs):
            if b.endswith("shuffled"):
                comparisons[f"{a} minus {b}"] = {
                    "mean_difference": float((scored[a]["reward"] - scored[b]["reward"]).mean()),
                    "ci95": None, "method": "descriptive single-permutation matched-frequency control",
                    "resamples": 0, "seed": SPLIT_SEEDS["shuffle"] + cohort_index,
                    "aggregate_cost_difference": float(scored[a]["cost"].sum() - scored[b]["cost"].sum()),
                    "scope": "Rows share a fixed permutation and are dependent; no iid bootstrap interval is claimed.",
                }
            else:
                comparisons[f"{a} minus {b}"] = paired_interval(scored[a]["reward"], scored[b]["reward"],
                                                                 SPLIT_SEEDS["bootstrap"] + 100 * cohort_index + j,
                                                                 500 if quick else 2000)
        learned_means = [float(scored[f"learned_seed_{m.seed}"]["reward"].mean()) for m in models]
        results[cohort] = {
            "policies": {name: _summarize(value) for name, value in scored.items()},
            "paired_comparisons": comparisons,
            "bayesian_quadrature_sensitivity": quadrature_sensitivity,
            "mismatch_flag_rate": float(flagged.mean()),
            "learned_training_seed_summary": {"seeds": list(seeds), "mean_rewards": learned_means,
                "mean": float(np.mean(learned_means)), "sample_standard_deviation": float(np.std(learned_means, ddof=1)) if len(seeds) > 1 else None,
                "note": "Descriptive across seeds. No population-level interval from these few training runs."},
            "no_probe_definition": "prior-optimal fixed calibration, not necessarily factory settings",
            "shift_type": "new direction-dependent friction equation" if cohort == "directional_friction" else
                          "new parameter range under frozen equations" if cohort not in ("finite_test", "continuous_jitter") else
                          "continuous parameter perturbation" if cohort == "continuous_jitter" else "in-support finite prior",
        }
        for i, episode_id in enumerate(data.episode_ids):
            obs = {"episode_id": episode_id, "cohort": cohort, "mismatch_distance": float(distance[i]),
                   "mismatch_flag": bool(flagged[i]), "asymmetric_friction": float(data.asymmetry[i]),
                   **{name: float(value) for name, value in zip(("motor", "friction", "load", "damping", "sensor_bias", "torque_deadzone"), data.parameters[i])}}
            for a, probe in enumerate(legacy.PROBES):
                for d in range(int(bank.dimensions[a])):
                    obs[f"observed_{probe.name}_{d}"] = float(data.observations[i, a, d])
            observation_rows.append(obs)
            for name, score in scored.items():
                row = {"episode_id": episode_id, "cohort": cohort, "policy": name}
                for key, array in score.items():
                    row[key] = array[i].item()
                episode_rows.append(row)
    for filename, rows in (("episodes.csv.gz", episode_rows), ("evaluation_observations.csv.gz", observation_rows)):
        with (out / filename).open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
                with io.TextIOWrapper(compressed, newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
    # Saving complete training observations supports exact evidence replay.
    np.savez_compressed(out / "training_data.npz", train_observations=train.observations,
                        train_parameters=train.parameters, train_quality=train.quality,
                        train_episode_ids=np.asarray(train.episode_ids),
                        validation_observations=validation.observations,
                        validation_parameters=validation.parameters, validation_quality=validation.quality,
                        validation_episode_ids=np.asarray(validation.episode_ids))
    summary = {"schema_version": SCHEMA_VERSION, "model_id": MODEL_ID, "seeds": list(seeds),
               "scope": manifest["scope"], "preregistered": False, "quick_ci_run": quick,
               "results": results, "selection": {k: v for k, v in selections.items() if k != "candidate_schedules"},
               "completed": True, "elapsed_seconds": time.perf_counter() - started,
               "limitations": [
                   "Synthetic normalized plant coefficients and noise; no empirical physical validation.",
                   "New directional-friction case is a specified synthetic stress test, not a measured fault.",
                   "Small finite prior and short decision horizon suit a Bayesian baseline. Its observation integral is numerically approximated.",
                   "Quadrature sensitivity is reported. Small learner-versus-Bayesian differences cannot establish an advantage beyond numerical uncertainty.",
                   "Single-permutation shuffled controls are descriptive and have no iid bootstrap confidence interval.",
                   "Episode bootstrap intervals condition on a trained policy and do not replace more training seeds.",
                   "Mismatch abstention falls back to prior-optimal calibration after paying for the first probe; it is not a certified safeguard.",
                   "Bayesian forced-two and best-fixed-two use equal test counts but may spend different test costs.",
                   "Protocol and test cases are public and exploratory; this is not a blinded or independently preregistered study.",
                   "Frozen v0.2 numerical timing is preserved for comparability, including 0.56 s low pulses.",
               ]}
    _json_write(out / "summary.json", summary)
    hashes = {str(p.relative_to(out)): _digest(p) for p in sorted(out.rglob("*")) if p.is_file()}
    _json_write(out / "SHA256SUMS.json", hashes)
    verification = validate_artifacts(out)
    if not verification["valid"]:
        raise RuntimeError("Artifact integrity verification failed")
    print(f"experiment: complete; {len(episode_rows)} policy/episode rows; {len(models)} reloadable checkpoints; {time.perf_counter() - started:.1f}s", flush=True)
    return summary


def validate_artifacts(output_dir: str | Path) -> dict[str, Any]:
    """Check hash integrity, paired case IDs, and means against saved raw rows."""
    out = Path(output_dir)
    hashes = json.loads((out / "SHA256SUMS.json").read_text(encoding="utf-8"))
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Empty or invalid artifact hash manifest")
    errors = []
    required = {"summary.json", "manifest.json", "selection.json", "protocol.md", "episodes.csv.gz",
                "evaluation_observations.csv.gz", "training_data.npz"}
    if not required.issubset(hashes):
        errors.append("hash manifest omits required evidence files")
    for name, expected in hashes.items():
        path = (out / name).resolve()
        if not path.is_relative_to(out.resolve()) or not path.is_file() or _digest(path) != expected:
            errors.append(f"hash mismatch: {name}")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    source_paths = {"experiments.py": Path(__file__).resolve(),
                    "recursivecal.py": Path(legacy.__file__).resolve()}
    for name, path in source_paths.items():
        if manifest.get("source_sha256", {}).get(name) != _digest(path):
            errors.append(f"current source differs from run: {name}; use the recorded source revision")
    if manifest.get("selection_sha256") != _digest(out / "selection.json"):
        errors.append("frozen selection hash differs")
    if manifest.get("protocol_sha256") != _digest(out / "protocol.md"):
        errors.append("frozen protocol hash differs")
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    with gzip.open(out / "episodes.csv.gz", "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            grouped.setdefault((row["cohort"], row["policy"]), []).append(row)
    for cohort, info in summary["results"].items():
        reference_ids = None
        for policy, values in info["policies"].items():
            rows = grouped.get((cohort, policy), [])
            ids = [row["episode_id"] for row in rows]
            if len(ids) != len(set(ids)) or (reference_ids is not None and ids != reference_ids):
                errors.append(f"unpaired or duplicate episodes: {cohort}/{policy}")
            reference_ids = ids
            if len(rows) != values["n"]:
                errors.append(f"row count: {cohort}/{policy}")
            for metric, key in (("mean_reward", "reward"), ("mean_quality", "quality"), ("mean_cost", "cost")):
                observed = np.array([float(row[key]) for row in rows])
                expected = float(values[metric])
                if (not rows or not np.isfinite(observed).all() or not np.isfinite(expected)
                        or abs(float(np.mean(observed)) - expected) > 1e-12):
                    errors.append(f"aggregate mismatch: {cohort}/{policy}/{metric}")
    saved_observations: dict[str, list[dict[str, str]]] = {}
    with gzip.open(out / "evaluation_observations.csv.gz", "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            saved_observations.setdefault(row["cohort"], []).append(row)
    bank = FiniteBank()
    with np.load(out / "training_data.npz", allow_pickle=False) as training:
        train_ids = set(training["train_episode_ids"].tolist())
        validation_ids = set(training["validation_episode_ids"].tolist())
        test_ids = {row["episode_id"] for rows in saved_observations.values() for row in rows}
        if train_ids & validation_ids or train_ids & test_ids or validation_ids & test_ids:
            errors.append("train, validation, or test episode identifiers overlap")
    for seed in manifest.get("training_seeds", []):
        checkpoint = out / "checkpoints" / f"bandit_seed_{seed}.json"
        if str(checkpoint.relative_to(out)) not in hashes or not checkpoint.is_file():
            errors.append(f"missing checkpoint: seed {seed}")
            continue
        model = ContextualBandit.load(checkpoint)
        for cohort, rows in saved_observations.items():
            observed = np.array([[float(row["observed_pulse_pos_low_0"]),
                                  float(row["observed_pulse_pos_low_1"])] for row in rows])
            actions = model.actions(bank.features(observed))
            recorded = grouped.get((cohort, f"learned_seed_{seed}"), [])
            if [row["episode_id"] for row in recorded] != [row["episode_id"] for row in rows]:
                errors.append(f"checkpoint replay case mismatch: {cohort}/seed {seed}")
            elif not np.array_equal(actions, np.array([int(row["second"]) for row in recorded])):
                errors.append(f"checkpoint replay decision mismatch: {cohort}/seed {seed}")
    return {"valid": not errors, "errors": errors, "files_checked": len(hashes),
            "policy_cohorts_checked": len(grouped)}
