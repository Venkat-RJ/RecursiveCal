"""Finite-model terminal-reward experiment design for physical gate protocol 1.

The model bank and its utility table are supplied from declared training worlds.
At run time this module accepts only public policy views. Its predictors use the
real version-3 dynamics with clean, quantized, delayed instrument readings. The
Gaussian likelihood and fantasy observations are explicit approximations to the
noisy feedback-controlled experiment, not access to the evaluator's world.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import math
from typing import Any

import numpy as np

from recursivecal_lab.inquiry import VERIFICATION_PROFILES, public_result
from recursivecal_lab.physical_rig import (
    CATALOG, OBSERVATION_FIELDS, Calibration, RigState, run_experiment, run_motion,
)
from recursivecal_lab.research_rig import ResearchRig
from recursivecal_lab.rl_environment import TEST_COST_WEIGHT, _motion_accepted, _profile_quality

BAYES_ID = "recursivecal.physical-gate-finite-bayes/1"
SIGMA = np.array([0.016, 0.064, 12.0])
FANTASIES = 64
FANTASY_SEED = 7361
STATUS_MISMATCH_LIKELIHOOD = 1e-8
MISSING_ACQUISITION_SQUARED_ERROR = 1e6


def model_qualities(calibration_model: Calibration, candidate: Calibration | None, *,
                    seed: int = 17011) -> dict[str, Any]:
    """Predict four-profile quality on an authored model, never an actual world.

    All verification start angles, profile lengths, recording lengths,
    temperatures and acceptance rules come from the frozen installed contract.
    This function evaluates the candidate only; the caller caches nominal
    quality separately when constructing improvement and rejection utility.
    """
    calibration_model.validate()
    candidate = candidate or Calibration()
    candidate.validate()
    profiles = []
    for index, (name, start, target, profile_s, duration_s, temperature) in enumerate(VERIFICATION_PROFILES):
        rig = ResearchRig(replace(calibration_model.model(), temperature_C=temperature),
                          state=RigState(angle_rad=math.radians(start)), seed=seed + index)
        run = run_motion(rig, start_angle_rad=math.radians(start),
                         target_angle_rad=math.radians(target), duration_s=duration_s,
                         profile_s=profile_s, calibration=candidate, noisy=False,
                         include_truth=False)
        profiles.append({"name": name, "temperature_C": temperature,
                         "profile_duration_s": profile_s, "recording_duration_s": duration_s,
                         "quality": _profile_quality(run), "accepted": _motion_accepted(run),
                         "metrics": run["metrics"]})
    return {"mean_quality": float(np.mean([row["quality"] for row in profiles])),
            "accepted": all(row["accepted"] for row in profiles), "profiles": profiles,
            "measurement_mode": "clean, quantized and delayed version-3 instruments"}


def _key(row: dict[str, Any]) -> float:
    return round(float(row["sensor_sample_time_s"]), 9)


def _vector(row: dict[str, Any]) -> np.ndarray:
    values = [row[name] for name in OBSERVATION_FIELDS]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in values):
        raise ValueError("public acquisitions must contain finite measurements")
    return np.array(values, dtype=float)


def _acquisitions(result: dict[str, Any]) -> dict[float, dict[str, Any]]:
    samples = {}
    for row in [*result["observations"], result["final_observation"]]:
        samples[_key(row)] = row
    return samples


def _normalize(log_weights: np.ndarray) -> np.ndarray:
    shifted = np.exp(log_weights - np.max(log_weights))
    return shifted / shifted.sum()


class FiniteBayes:
    """Persistent public-history Bayesian model bank with one-step terminal VOI."""

    def __init__(self, initial_view: dict[str, Any], models: list[Calibration],
                 utilities: np.ndarray, candidates: list[Calibration | None],
                 mismatch_cutoff: float = 4.0):
        if not models or not candidates:
            raise ValueError("model and candidate banks must not be empty")
        if not math.isfinite(mismatch_cutoff) or mismatch_cutoff <= 0:
            raise ValueError("mismatch_cutoff must be positive")
        self.models = [model.validate() for model in models]
        self.candidates = [candidate.validate() if candidate is not None else None for candidate in candidates]
        if sum(candidate is None for candidate in self.candidates) != 1:
            raise ValueError("candidate bank must contain exactly one explicit abstention")
        self.abstain_index = self.candidates.index(None)
        self.utilities = np.array(utilities, dtype=float, copy=True)
        if self.utilities.shape != (len(models), len(candidates)) or not np.isfinite(self.utilities).all():
            raise ValueError("utility table shape or values are invalid")
        if np.any(np.abs(self.utilities[:, self.abstain_index]) > 1e-12):
            raise ValueError("abstention's terminal improvement utility must be zero")
        self.mismatch_cutoff = float(mismatch_cutoff)
        history = initial_view["history"]
        initial = history[0]["start_observation"] if history else initial_view["measurement"]
        temperature = initial["ambient_temperature_C"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise ValueError("public ambient temperature must be finite")
        self.rigs = [ResearchRig(replace(model.model(), temperature_C=temperature), state=RigState(), seed=0)
                     for model in self.models]
        self.weights = np.ones(len(models), dtype=float) / len(models)
        self._squared_errors = np.zeros(len(models))
        self._max_residual = np.zeros(len(models))
        self._dimension_count = 0
        self._seen_acquisitions: set[float] = set()
        self._actions: list[str] = []
        self._cache: dict[str, tuple[tuple[float, ...], list[ResearchRig], list[dict[str, Any]]]] = {}
        self._update_log: list[dict[str, Any]] = []
        predictions = [{_key(rig.observe(noisy=False)): rig.observe(noisy=False)} for rig in self.rigs]
        self._condition([initial], predictions)
        if history:
            self.update(initial_view)

    def _condition(self, rows: list[dict[str, Any]], predictions: list[dict[float, dict[str, Any]]],
                   predicted_status: list[str] | None = None, observed_status: str | None = None) -> None:
        unique = {_key(row): row for row in rows if _key(row) not in self._seen_acquisitions}
        errors = np.zeros(len(self.models))
        maxima = np.zeros(len(self.models))
        missing = np.zeros(len(self.models), dtype=int)
        for acquisition, row in unique.items():
            observed = _vector(row)
            for index, prediction in enumerate(predictions):
                predicted = prediction.get(acquisition)
                if predicted is None:
                    # A penalty for an impossible/absent predicted acquisition,
                    # never a fabricated measured sample.
                    errors[index] += MISSING_ACQUISITION_SQUARED_ERROR
                    maxima[index] = max(maxima[index], math.sqrt(MISSING_ACQUISITION_SQUARED_ERROR))
                    missing[index] += 1
                else:
                    standardized = (_vector(predicted) - observed) / SIGMA
                    errors[index] += float(standardized @ standardized)
                    maxima[index] = max(maxima[index], float(np.max(np.abs(standardized))))
        self._squared_errors += errors
        self._max_residual = np.maximum(self._max_residual, maxima)
        self._dimension_count += len(unique) * len(OBSERVATION_FIELDS)
        self._seen_acquisitions.update(unique)
        logp = np.log(np.maximum(self.weights, 1e-300)) - 0.5 * errors
        if predicted_status is not None:
            logp += np.array([0.0 if status == observed_status else math.log(STATUS_MISMATCH_LIKELIHOOD)
                              for status in predicted_status])
        self.weights = _normalize(logp)
        self._update_log.append({"new_acquisitions": len(unique), "missing_by_model": missing.tolist(),
                                 "observed_termination": observed_status,
                                 "predicted_terminations": predicted_status,
                                 "weights": self.weights.tolist(),
                                 "best_standardized_rms": self.best_standardized_rms})

    @property
    def best_standardized_rms(self) -> float:
        return float(math.sqrt(float(self._squared_errors.min()) / max(1, self._dimension_count)))

    @property
    def model_mismatch(self) -> bool:
        return self.best_standardized_rms > self.mismatch_cutoff

    def summary(self) -> dict[str, Any]:
        return {"policy_id": BAYES_ID, "weights": self.weights.tolist(),
                "posterior_entropy_nats": float(-np.dot(self.weights, np.log(np.maximum(self.weights, 1e-300)))),
                "largest_posterior_weight": float(self.weights.max()),
                "best_standardized_rms": self.best_standardized_rms,
                "standardized_rms_by_model": np.sqrt(self._squared_errors / max(1, self._dimension_count)).tolist(),
                "max_standardized_residual_by_model": self._max_residual.tolist(),
                "mismatch_cutoff": self.mismatch_cutoff, "model_mismatch": self.model_mismatch,
                "unique_acquisitions": len(self._seen_acquisitions),
                "data_dimension": self._dimension_count, "actions": list(self._actions)}

    def diagnostics(self) -> dict[str, Any]:
        """Stable host-facing diagnostics for the training-only cutoff lock."""
        return {**self.summary(), "dimension_count": self._dimension_count}

    def predict(self, action: str, measurement: dict[str, Any]) -> tuple[list[ResearchRig], list[dict[str, Any]]]:
        if action not in CATALOG:
            raise ValueError("unknown diagnostic experiment")
        start_key = (_key(measurement), *_vector(measurement).tolist())
        if action not in self._cache or self._cache[action][0] != start_key:
            copies = [rig.fork() for rig in self.rigs]
            predictions = [run_experiment(rig, action, measurement, noisy=False) for rig in copies]
            self._cache[action] = (start_key, copies, predictions)
        _, copies, predictions = self._cache[action]
        return copies, predictions

    def update(self, view: dict[str, Any]) -> dict[str, Any]:
        history = view["history"]
        if len(history) < len(self._actions) or [row["action"] for row in history[:len(self._actions)]] != self._actions:
            raise ValueError("public history is not an extension of the fitted prefix")
        for record in history[len(self._actions):]:
            action = record["action"]
            copies, predictions = self.predict(action, record["start_observation"])
            self._condition([*record["observations"], record["final_observation"]],
                            [_acquisitions(result) for result in predictions],
                            [result["metrics"]["termination"] for result in predictions], record["termination"])
            self.rigs = copies
            self._actions.append(action)
            self._cache = {}
        return self.summary()

    def _best(self, weights: np.ndarray, *, mismatch: bool = False) -> tuple[int, float, np.ndarray]:
        expected = weights @ self.utilities
        best = int(np.argmax(expected))
        if mismatch or float(expected[best]) <= 1e-12:
            best = self.abstain_index
        return best, float(expected[best]), expected

    def posterior_utility(self) -> dict[str, Any]:
        index, value, expected = self._best(self.weights, mismatch=self.model_mismatch)
        return {"candidate_index": index, "expected_utility": value,
                "expected_utility_by_candidate": expected.tolist(),
                "disposition": "abstain" if self.candidates[index] is None else "candidate",
                "model_mismatch": self.model_mismatch,
                "best_standardized_rms": self.best_standardized_rms}

    def terminal_action(self) -> tuple[dict[str, Any], dict[str, Any]]:
        details = self.posterior_utility()
        candidate = self.candidates[details["candidate_index"]]
        action = {"abstain": True} if candidate is None else {"commit": asdict(candidate)}
        return action, {**details, "posterior": self.summary()}

    def choose_second(self, view: dict[str, Any], force_two: bool = False) -> tuple[str, dict[str, Any]]:
        """Choose an affordable experiment by expected terminal utility net cost.

        Abort mass is integrated exactly. The completed component uses 64
        posterior-predictive fantasies with common uniforms and Gaussian noise
        across candidate actions. The same cumulative residual mismatch rule
        governs both fantasy terminal choices and real terminal choices.
        """
        self.update(view)
        current = self.posterior_utility()
        legal = [action for action in view["legal_actions"]
                 if action in CATALOG and CATALOG[action].cost <= view["budget_remaining"] + 1e-10]
        stage = len(self._actions)
        rng = np.random.default_rng(np.random.SeedSequence([FANTASY_SEED, stage]))
        uniforms = rng.random(FANTASIES)
        common_noise = rng.normal(size=(FANTASIES, 9))
        scores = []
        for action in legal:
            _, predictions = self.predict(action, view["measurement"])
            samples = [_acquisitions(result) for result in predictions]
            statuses = [result["metrics"]["termination"] for result in predictions]
            complete = np.array([status == "completed" for status in statuses])
            complete_mass = float(self.weights @ complete)
            abort_mass = max(0.0, min(1.0, 1.0 - complete_mass))
            values, mismatches, decisions = [], [], []
            if complete_mass > 0:
                complete_weights = self.weights * complete / complete_mass
                sampled_indices = np.minimum(np.searchsorted(np.cumsum(complete_weights), uniforms, side="right"), len(self.models) - 1)
                for sample_index, model_index in enumerate(sampled_indices):
                    available = {key: row for key, row in samples[int(model_index)].items()
                                 if key not in self._seen_acquisitions}
                    ordered = sorted(available)
                    if len(ordered) * len(OBSERVATION_FIELDS) > common_noise.shape[1]:
                        raise ValueError("diagnostic produced more than three unique public acquisitions")
                    clean = np.concatenate([_vector(available[key]) for key in ordered]) if ordered else np.empty(0)
                    sigma = np.tile(SIGMA, len(ordered))
                    fantasy = clean + common_noise[sample_index, :len(clean)] * sigma
                    errors = np.zeros(len(self.models))
                    for model, sample_rows in enumerate(samples):
                        for acquisition_index, key in enumerate(ordered):
                            predicted = sample_rows.get(key)
                            if predicted is None:
                                errors[model] += MISSING_ACQUISITION_SQUARED_ERROR
                            else:
                                residual = (_vector(predicted) - fantasy[3 * acquisition_index:3 * acquisition_index + 3]) / SIGMA
                                errors[model] += float(residual @ residual)
                    logp = np.log(np.maximum(self.weights, 1e-300)) - 0.5 * errors
                    logp += np.where(complete, 0.0, math.log(STATUS_MISMATCH_LIKELIHOOD))
                    posterior = _normalize(logp)
                    cumulative_rms = math.sqrt(float(np.min(self._squared_errors + errors))
                                               / max(1, self._dimension_count + len(clean)))
                    mismatch = cumulative_rms > self.mismatch_cutoff
                    decision, value, _ = self._best(posterior, mismatch=mismatch)
                    values.append(value)
                    mismatches.append(mismatch)
                    decisions.append(decision)
            expected_completed = float(np.mean(values)) if values else 0.0
            # The real environment forces nominal abstention on an aborted test,
            # charging its full catalog cost and the 1.0 forced-end penalty.
            terminal = complete_mass * expected_completed - abort_mass
            net = terminal - TEST_COST_WEIGHT * CATALOG[action].cost
            scores.append({
                "action": action, "cost": CATALOG[action].cost,
                "predicted_abort_probability": abort_mass,
                "expected_terminal_utility": terminal, "expected_net_utility": net,
                "expected_completed_terminal_utility": expected_completed,
                "fantasy_count": len(values),
                "fantasy_mismatch_fraction": float(np.mean(mismatches)) if mismatches else None,
                "fantasy_candidate_counts": dict(sorted(Counter(str(index) for index in decisions).items())),
                "fantasy_terminal_utilities": values,
                "predicted_public_results": [public_result(result) for result in predictions],
            })
        choice, choice_value = "STOP", current["expected_utility"]
        if scores:
            best = max(scores, key=lambda row: row["expected_net_utility"])
            if force_two or best["expected_net_utility"] > choice_value + 1e-12:
                choice, choice_value = best["action"], best["expected_net_utility"]
        return choice, {
            "policy_id": BAYES_ID, "choice": choice, "expected_utility": choice_value,
            "stop_expected_utility": current["expected_utility"], "forced_two": bool(force_two),
            "fantasy_seed_components": [FANTASY_SEED, stage], "fantasies_per_complete_component": FANTASIES,
            "abort_component": "exact posterior mass times forced-abstention penalty -1",
            "candidates": scores, "current_terminal_decision": current, "posterior": self.summary(),
        }
