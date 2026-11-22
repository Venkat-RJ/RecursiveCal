"""An observation-only investigator connected to the dimensioned physical rig.

The baseline is finite-bank Bayesian system identification and Monte Carlo,
one-step information gain per test cost. It is not RL or optimal experiment design.
The evaluator owns hidden parameters and reveals them only in the sealed report.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import struct
from typing import Any, Callable

import numpy as np

from .physics import ModelParameters, passive_hold
from .physical_rig import (CATALOG, MODEL_ID, OBSERVATION_FIELDS, SENSOR_SIGMA, Calibration,
                           PhysicalRig, RigState, catalog, finite, integer, run_experiment, run_motion)

PROTOCOL_ID = "recursivecal.physical-inquiry/1"
INFERENCE_SIGMA = np.array([0.004, 0.016, 3.0])
MAX_TESTS = 5
BUDGET = 8.0
ACCEPTANCE = {"tracking_rmse_deg_max": 3.0, "final_error_deg_max": 2.0,
              "peak_speed_rad_s_max": 1.15, "saturation_fraction_max": 0.35}
CASE_LABELS = {
    "nominal": "Nominal mechanism", "weak_motor": "Reduced drive effectiveness",
    "payload": "Additional hatch mass", "friction": "Increased hinge friction",
    "gas_loss": "Reduced gas assistance", "sensor_bias": "Encoder offset",
    "compound": "Combined mass, drive, friction and encoder changes",
    "directional_friction": "Unmodeled friction on closing",
    "overload": "Mass beyond the inference bank",
}


def digest(value: Any) -> str:
    # Typed canonical form with IEEE-754 numbers survives Python/JavaScript JSON
    # round trips (1.0 becomes 1 in a browser). This is integrity, not a signature.
    def canonical(item):
        if item is None:
            return ["null"]
        if isinstance(item, bool):
            return ["bool", item]
        if isinstance(item, (int, float)):
            if not math.isfinite(item) or (isinstance(item, int) and abs(item) > 2**53 - 1):
                raise ValueError("digest requires finite, exactly representable JSON numbers")
            return ["number", struct.pack(">d", float(item) if item else 0.0).hex()]
        if isinstance(item, str):
            return ["string", item]
        if isinstance(item, list):
            return ["array", [canonical(x) for x in item]]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            return ["object", [[key, canonical(item[key])] for key in sorted(item)]]
        raise ValueError("digest requires JSON values")
    raw = json.dumps(canonical(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def make_case(name: str) -> tuple[ModelParameters, float]:
    """Evaluator-only named fixtures, never an input to the investigator."""
    if not isinstance(name, str) or name not in CASE_LABELS:
        raise ValueError("unknown physical case")
    changes = {
        "nominal": {}, "weak_motor": {"motor_efficiency": 0.65},
        "payload": {"mass_kg": 30.0}, "friction": {"friction_coulomb_Nm": 14.0},
        "gas_loss": {"gas_scale": 0.75}, "sensor_bias": {"sensor_bias_rad": 0.025},
        "compound": {"motor_efficiency": 0.82, "mass_kg": 30.0, "gas_scale": 0.75,
                     "friction_coulomb_Nm": 14.0, "sensor_bias_rad": -0.025},
        "directional_friction": {}, "overload": {},
    }[name]
    p = Calibration(**changes).model()
    if name == "overload":
        p = replace(p, mass_kg=43.0, inertia_kg_m2=12.0 + 18.0 * 0.55**2)
    return p, 24.0 if name == "directional_friction" else 0.0


def feature_vector(observations: list[dict[str, float]]) -> np.ndarray:
    return np.array([[row[key] for key in OBSERVATION_FIELDS] for row in observations], dtype=float).ravel()


def entropy(weights: np.ndarray) -> float:
    positive = weights[weights > 0]
    return float(-np.dot(positive, np.log(positive)))


def public_measurement(row: dict[str, Any]) -> dict[str, Any]:
    """One allowlist for initial, start-of-test and acquired measurements."""
    return {key: row[key] for key in ("time_s", "sample_time_s", "sensor_sample_time_s", "sensor_age_s",
                                     "ambient_temperature_C", *OBSERVATION_FIELDS) if key in row}


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    """A strict allowlist excludes truth, inferred quality and hidden parameters."""
    return {"observations": [public_measurement(row) for row in result["observations"]],
            "final_observation": public_measurement(result["final_observation"]),
            "termination": result["metrics"]["termination"],
            "elapsed_s": result["metrics"]["completed_duration_s"],
            "events": [{"time_s": event["time_s"], "type": event["type"]} for event in result["events"]]}


class InquirySession:
    """Bounded external-policy interface: observe, step and commit exactly once.

    This Python boundary prevents accidental disclosure, not adversarial code
    execution in the same process. Run untrusted agents in a separate process.
    """

    def __init__(self, rig: PhysicalRig, *, max_tests: int = MAX_TESTS, budget: float = BUDGET):
        self.__rig = rig
        self.model_id = getattr(rig, "model_id", MODEL_ID)
        self.max_tests = integer(max_tests, "max_tests", 0, 6)
        self.budget = finite(budget, "budget", 0, 12)
        self.__cost = 0.0
        self.__history: list[dict[str, Any]] = []
        self.__records: list[dict[str, Any]] = []
        self.__observation = public_measurement(rig.observe())
        self.__committed: dict[str, Any] | None = None
        self.__aborted = False

    def observe(self) -> dict[str, Any]:
        actions = [] if self.__committed is not None or self.__aborted or len(self.__history) >= self.max_tests else [
            name for name, action in CATALOG.items() if action.cost <= self.budget - self.__cost + 1e-10]
        return deepcopy({"schema_version": "recursivecal.agent-observation/1", "model_id": self.model_id,
                         "measurement": self.__observation, "history": self.__history,
                         "catalog": catalog(), "legal_actions": actions, "can_commit": self.__committed is None,
                         "tests_remaining": self.max_tests - len(self.__history),
                         "cost_used": self.__cost, "budget_remaining": self.budget - self.__cost})

    def step(self, action: str) -> dict[str, Any]:
        view = self.observe()
        if action not in view["legal_actions"]:
            raise ValueError("experiment is unavailable, over budget, or session has ended")
        before = deepcopy(self.__observation)
        result = run_experiment(self.__rig, action, before, include_truth=True)
        self.__cost += CATALOG[action].cost
        visible = public_result(result)
        self.__observation = deepcopy(visible["final_observation"])
        self.__history.append({"action": action, "cost": CATALOG[action].cost, "start_observation": before, **visible})
        self.__records.append({"action": action, "cost": CATALOG[action].cost, **result})
        self.__aborted = visible["termination"] != "completed"
        return self.observe()

    def commit(self, calibration: dict[str, Any], *, disposition: str = "candidate", reason: str = "external policy") -> dict[str, Any]:
        if self.__committed is not None:
            raise ValueError("calibration is already committed")
        estimate = Calibration.from_dict(calibration)
        if disposition not in ("candidate", "abstain") or not isinstance(reason, str) or not 1 <= len(reason) <= 1000:
            raise ValueError("invalid calibration disposition or reason")
        if disposition == "abstain" and estimate != Calibration():
            raise ValueError("abstention must retain the nominal calibration")
        if self.__aborted and disposition != "abstain":
            raise ValueError("a limit-aborted diagnostic session must abstain")
        self.__committed = {"estimates": asdict(estimate), "disposition": disposition,
                            "reason": reason, "history_sha256": digest(self.__history)}
        return deepcopy(self.__committed)

    def sealed_records(self) -> dict[str, Any]:
        if self.__committed is None:
            raise ValueError("commit before retrieving evaluator records")
        return deepcopy({"commitment": self.__committed, "diagnostics": self.__records,
                         "agent_history": self.__history, "cost": self.__cost})


class BayesianInvestigator:
    """72 public hypotheses, persistent per-hypothesis states and likelihood checks."""

    def __init__(self, initial_observation: dict[str, float], *, seed: int = 0,
                 rig_factory: Callable[..., PhysicalRig] = PhysicalRig):
        self.seed = integer(seed, "seed", 0, 2**31 - 1)
        self.estimates = [Calibration(mass, motor, gas, friction, bias) for mass, motor, gas, friction, bias in
                          itertools.product((25., 30.), (0.65, 0.82, 1.), (0.75, 1.), (6., 14.), (-0.025, 0., 0.025))]
        temperature = initial_observation.get("ambient_temperature_C", 20.0)
        self.rigs = [rig_factory(replace(estimate.model(), temperature_C=temperature)) for estimate in self.estimates]
        self.weights = np.ones(len(self.rigs)) / len(self.rigs)
        self._squared_errors = np.zeros(len(self.rigs))
        self._max_standardized_residual = np.zeros(len(self.rigs))
        self._dimension_count = 0
        self.history: list[dict[str, Any]] = []
        self.directions: set[str] = set()
        self.cache: dict[str, tuple[list[PhysicalRig], list[dict[str, Any]]]] = {}
        self.model_mismatch = False
        self._condition(feature_vector([initial_observation]),
                        np.stack([feature_vector([rig.observe(noisy=False)]) for rig in self.rigs]),
                        INFERENCE_SIGMA)

    def _condition(self, observed: np.ndarray, predictions: np.ndarray, sigma: np.ndarray) -> float:
        standardized = (predictions - observed) / sigma
        errors = np.sum(standardized**2, axis=1)
        self._squared_errors += errors
        self._max_standardized_residual = np.maximum(self._max_standardized_residual,
                                                     np.max(np.abs(standardized), axis=1))
        self._dimension_count += len(observed)
        log_weights = np.log(np.maximum(self.weights, 1e-300)) - 0.5 * errors
        shifted = np.exp(log_weights - np.max(log_weights))
        self.weights = shifted / shifted.sum()
        adequacy = float(math.sqrt(np.min(self._squared_errors) / self._dimension_count))
        # This threshold is an engineering rejection rule, not a calibrated p-value.
        self.model_mismatch = self.model_mismatch or adequacy > 4.0 or float(self._max_standardized_residual.min()) > 6.0
        return adequacy

    def predict(self, action: str, measurement: dict[str, float]) -> tuple[list[PhysicalRig], list[dict[str, Any]]]:
        if action not in self.cache:
            copies = [rig.fork() for rig in self.rigs]
            predictions = [run_experiment(rig, action, measurement, noisy=False) for rig in copies]
            self.cache[action] = copies, predictions
        return self.cache[action]

    def update(self, record: dict[str, Any]) -> dict[str, Any]:
        action = record["action"]
        copies, predictions = self.predict(action, record["start_observation"])
        count = len(record["observations"])
        # Match only declared acquisition times. A predicted early stop is evidence
        # against that hypothesis, never padded with a fabricated measurement.
        valid = np.array([len(result["observations"]) >= count for result in predictions])
        prior_entropy = entropy(self.weights)
        if count:
            observed = feature_vector(record["observations"])
            matrix = np.stack([feature_vector(result["observations"][:count]) if valid[index]
                               else observed + np.tile(INFERENCE_SIGMA, count) * 100
                               for index, result in enumerate(predictions)])
            adequacy = self._condition(observed, matrix, np.tile(INFERENCE_SIGMA, count))
        else:
            adequacy = float(math.sqrt(np.min(self._squared_errors) / max(1, self._dimension_count)))
        for index, prediction in enumerate(predictions):
            if prediction["metrics"]["termination"] != record["termination"]:
                self.weights[index] *= 1e-8
        self.weights /= self.weights.sum()
        self.rigs = copies
        self.cache = {}
        movement = record["final_observation"]["angle_rad"] - record["start_observation"]["angle_rad"]
        requested_target = CATALOG[action].target_angle_rad
        requested_move = 0 if requested_target is None else requested_target - record["start_observation"]["angle_rad"]
        # Drift during a hold/coast is evidence, but does not count as a commanded
        # bidirectional test. A fixture reposition is not an actuator response.
        if (not CATALOG[action].fixture and abs(requested_move) > math.radians(5)
                and abs(movement) > math.radians(5) and movement * requested_move > 0):
            self.directions.add("opening" if movement > 0 else "closing")
        summary = {"action": action, "entropy_before_nats": prior_entropy, "entropy_after_nats": entropy(self.weights),
                   "best_normalized_residual": adequacy, **self.summary()}
        self.history.append(summary)
        return summary

    def summary(self) -> dict[str, Any]:
        matrix = np.array([list(asdict(estimate).values()) for estimate in self.estimates])
        mean = self.weights @ matrix
        variance = self.weights @ ((matrix - mean)**2)
        names = list(asdict(Calibration()))
        return {"posterior_mean": dict(zip(names, mean.tolist())),
                "posterior_std": dict(zip(names, np.sqrt(variance).tolist())),
                "hypothesis_count": len(self.estimates), "largest_posterior_weight": float(self.weights.max()),
                "entropy_nats": entropy(self.weights), "model_mismatch": self.model_mismatch,
                "best_max_standardized_residual": float(self._max_standardized_residual.min()),
                "directions_observed": sorted(self.directions)}

    def choose(self, view: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        legal = view["legal_actions"]
        if not legal:
            return None, {"reason": "diagnostic budget, test limit or rig stop reached"}
        if self.model_mismatch:
            # A declared fixture is a concrete sensor/model check, not a hidden reset.
            if "reference" in legal and not any(x["action"] == "reference" for x in self.history):
                return "reference", {"reason": "model residual is inconsistent; check the encoder against the fixture"}
            return None, {"reason": "measurements are outside the declared model bank"}
        if len(self.directions) == 2 and entropy(self.weights) < 0.06:
            return None, {"reason": "belief concentrated after both opening and closing observations"}
        candidates = []
        rng = np.random.default_rng(self.seed + 3571 * len(self.history))
        # Shared posterior samples/noise make action comparisons reproducible.
        hypotheses = rng.choice(len(self.rigs), size=48, p=self.weights)
        noise = rng.normal(size=(48, 9))
        for action in legal:
            if self.history and action == self.history[-1]["action"]:
                continue
            _, predictions = self.predict(action, view["measurement"])
            complete = np.array([len(item["observations"]) == 3 and item["metrics"]["termination"] == "completed" for item in predictions])
            risk = float(self.weights @ (~complete))
            if risk > 0.05:
                candidates.append({"action": action, "predicted_abort_probability": risk, "eligible": False})
                continue
            matrix = np.stack([feature_vector(item["observations"]) if complete[index] else np.zeros(9)
                               for index, item in enumerate(predictions)])
            sigma = np.tile(INFERENCE_SIGMA, 3)
            fantasies = matrix[hypotheses] + noise * sigma
            residual = (fantasies[:, None, :] - matrix[None, :, :]) / sigma
            logp = np.log(np.maximum(self.weights, 1e-300))[None, :] - 0.5 * np.sum(residual**2, axis=2)
            logp[:, ~complete] = -1e300
            post = np.exp(logp - logp.max(axis=1, keepdims=True))
            post /= post.sum(axis=1, keepdims=True)
            expected_entropy = float(np.mean(-np.sum(post * np.log(np.maximum(post, 1e-300)), axis=1)))
            gain = max(0.0, entropy(self.weights) - expected_entropy)
            # After concentration, exercise the still-unobserved direction.
            movement = sum(float(weight) * (item["final_observation"]["angle_rad"] - view["measurement"]["angle_rad"])
                           for weight, item in zip(self.weights, predictions))
            new_direction = ((movement > math.radians(5) and "opening" not in self.directions)
                             or (movement < -math.radians(5) and "closing" not in self.directions)) and not CATALOG[action].fixture
            new_direction = new_direction and CATALOG[action].target_angle_rad is not None
            requested_move = (CATALOG[action].target_angle_rad or view["measurement"]["angle_rad"]) - view["measurement"]["angle_rad"]
            new_direction = new_direction and abs(requested_move) > math.radians(5) and requested_move * movement > 0
            score = gain / CATALOG[action].cost + (0.1 if new_direction else 0.0)
            candidates.append({"action": action, "eligible": True, "expected_information_gain_nats": gain,
                               "predicted_abort_probability": risk, "score": score,
                               "adds_direction_coverage": bool(new_direction)})
        eligible = [row for row in candidates if row["eligible"]]
        if not eligible:
            return None, {"reason": "no experiment meets the posterior risk screen", "candidates": candidates}
        if entropy(self.weights) < 0.06:
            # A protocol confirmation phase after identification. Use a large
            # opening excursion before closing so fault-induced drift cannot
            # leave the next commanded excursion too small to be informative.
            preferred = "high_sweep" if "opening" not in self.directions else "low_sweep"
            selected = next((row for row in eligible if row["action"] == preferred and row["adds_direction_coverage"]), None)
            if selected is None and "closing" not in self.directions:
                selected = next((row for row in eligible if row["action"] == "high_sweep"), None)
            if selected is not None:
                return selected["action"], {"reason": "belief concentrated; confirm commanded opening and closing", "candidates": candidates}
        choice = max(eligible, key=lambda row: row["score"])
        return choice["action"], {"reason": "one-step information gain per cost, plus missing-direction coverage", "candidates": candidates}

    def calibration(self) -> Calibration:
        return Calibration.from_dict(self.summary()["posterior_mean"])


def _accepted(run: dict[str, Any]) -> bool:
    m = run["metrics"]
    return (m["termination"] == "completed" and m["tracking_rmse_deg"] <= ACCEPTANCE["tracking_rmse_deg_max"]
            and abs(m["final_error_deg"]) <= ACCEPTANCE["final_error_deg_max"]
            and m["peak_speed_rad_s"] <= ACCEPTANCE["peak_speed_rad_s_max"]
            and m["saturation_fraction"] <= ACCEPTANCE["saturation_fraction_max"])


def verify_calibration(parameters: ModelParameters, closing_extra: float, calibration: Calibration, *, seed: int,
                       rig_factory: Callable[..., PhysicalRig] = PhysicalRig) -> dict[str, Any]:
    """Post-commit evaluator with new trajectories, temperatures and sensor seeds."""
    profiles = (
        ("full_open", 0.0, 78.0, 4.8, 5.8, 20.0),
        ("full_close", 78.0, 0.0, 5.6, 6.6, 20.0),
        ("partial_reverse", 64.0, 27.0, 3.1, 4.1, 20.0),
        ("cold_open", 0.0, 78.0, 5.2, 6.2, -10.0),
    )
    comparisons = []
    for index, (name, start, target, profile, duration, temperature) in enumerate(profiles):
        pair = {}
        for label, estimate in (("before", Calibration()), ("after", calibration)):
            rig = rig_factory(replace(parameters, temperature_C=temperature), seed=seed + 10000 + index,
                              state=RigState(angle_rad=math.radians(start)), closing_friction_extra_Nm=closing_extra)
            run = run_motion(rig, start_angle_rad=math.radians(start), target_angle_rad=math.radians(target),
                             duration_s=duration, profile_s=profile, calibration=estimate, include_truth=True)
            run["accepted"] = _accepted(run)
            pair[label] = run
        comparisons.append({"name": name, "temperature_C": temperature, "profile_duration_s": profile, **pair})
    # Controller tuning cannot repair an unsupported unpowered mechanism.
    hold = rig_factory(parameters, seed=seed + 20001, state=RigState(angle_rad=parameters.max_angle_rad),
                       closing_friction_extra_Nm=closing_extra)
    passive = run_motion(hold, start_angle_rad=parameters.max_angle_rad, target_angle_rad=parameters.max_angle_rad,
                         duration_s=0.8, powered=False, include_truth=True)
    loss = rig_factory(parameters, seed=seed + 20002, state=RigState(angle_rad=math.radians(55)),
                      closing_friction_extra_Nm=closing_extra)
    power_loss = run_motion(loss, start_angle_rad=math.radians(55), target_angle_rad=math.radians(70),
                            duration_s=2.2, profile_s=1.7, calibration=calibration,
                            power_loss_s=0.8, include_truth=True)
    static = passive_hold(replace(hold.parameters, friction_static_Nm=hold.parameters.friction_static_Nm + closing_extra,
                                  friction_coulomb_Nm=hold.parameters.friction_coulomb_Nm + closing_extra))
    passed = all(pair["after"]["accepted"] for pair in comparisons)
    before_rmse = sum(pair["before"]["metrics"]["tracking_rmse_deg"] for pair in comparisons) / len(comparisons)
    after_rmse = sum(pair["after"]["metrics"]["tracking_rmse_deg"] for pair in comparisons) / len(comparisons)
    return {"model_id": getattr(hold, "model_id", MODEL_ID),
            "protocol": "fresh physical states, four held-out motion profiles, paired sensor seeds; no return to policy",
            "acceptance_limits": dict(ACCEPTANCE), "comparisons": comparisons,
            "before_mean_rmse_deg": before_rmse, "after_mean_rmse_deg": after_rmse,
            "all_motion_profiles_passed": passed, "passive_hold": {"static": static, "run": passive},
            "power_loss": power_loss, "hardware_validated": False,
            "system_ready_for_hardware": False,
            "readiness_reason": "No physical validation data; unpowered support must be independently engineered and tested."}


def capabilities() -> dict[str, Any]:
    return {"schema_version": PROTOCOL_ID, "model_id": MODEL_ID, "cases": CASE_LABELS,
            "experiments": catalog(), "default_budget": BUDGET, "default_max_tests": MAX_TESTS,
            "policies": ["bayes", "fixed", "no_probe"], "sensor_sigma": dict(zip(OBSERVATION_FIELDS, SENSOR_SIGMA)),
            "inference_sigma": dict(zip(OBSERVATION_FIELDS, INFERENCE_SIGMA.tolist())),
            "acceptance_limits": ACCEPTANCE, "hardware_connected": False, "source_kind": "synthetic",
            "supported_rig_versions": [2, 3], "workbench_default_rig_version": 3}


def run_study(*, case: str = "compound", seed: int = 7, policy: str = "bayes", max_tests: int = MAX_TESTS,
              budget: float = BUDGET, progress: Callable[[str], None] | None = None,
              on_event: Callable[[dict[str, Any]], None] | None = None,
              rig_version: int = 2) -> dict[str, Any]:
    integer(seed, "seed", 0, 2**31 - 30000)
    if policy not in ("bayes", "fixed", "no_probe"):
        raise ValueError("policy must be bayes, fixed, or no_probe")
    integer(rig_version, "rig_version", 2, 3)
    rig_factory = PhysicalRig
    if rig_version == 3:
        from .research_rig import ResearchRig
        rig_factory = ResearchRig
    parameters, closing_extra = make_case(case)
    plant = rig_factory(parameters, seed=seed, closing_friction_extra_Nm=closing_extra)
    session = InquirySession(plant,
                             max_tests=max_tests, budget=budget)
    initial = session.observe()
    def emit(kind: str, **data: Any) -> None:
        # The monitor is observational. It never supplies actions to the policy.
        # No evaluator records or plant truth are emitted before commitment.
        if on_event is not None:
            on_event(deepcopy({"type": kind, **data}))

    emit("started", observation=initial)
    investigator = BayesianInvestigator(initial["measurement"], seed=seed, rig_factory=rig_factory)
    decisions = []
    prediction_history = []
    fixed = iter(("high_sweep", "low_sweep", "mid_sweep"))
    reason = "no diagnostic tests requested"
    while policy != "no_probe":
        view = session.observe()
        if policy == "bayes":
            action, decision = investigator.choose(view)
        else:
            action = next(fixed, None)
            if action not in view["legal_actions"]:
                action = None
            decision = {"reason": "declared fixed high-low-mid schedule"}
        decisions.append({"step": len(view["history"]) + 1, "action": action, **decision})
        if action is None:
            reason = decision["reason"]
            break
        if progress:
            progress(f"Test {len(view['history']) + 1}: {action}; cost {CATALOG[action].cost:g}; budget remaining {view['budget_remaining']:g}")
        # Record candidate predictions BEFORE acquiring the experiment. These
        # are public model-bank estimates, not the hidden plant parameters.
        _, predictions = investigator.predict(action, view["measurement"])
        candidates = []
        for index in np.argsort(-investigator.weights, kind="stable")[:3]:
            prediction = predictions[int(index)]
            fields = ("time_s", "angle_rad", "velocity_rad_s", "strut_force_N_each")
            candidates.append({"parameters": asdict(investigator.estimates[int(index)]),
                               "prior_weight": float(investigator.weights[int(index)]),
                               "trace": [{key: row[key] for key in fields} for row in prediction["trace"]],
                               "observations": public_result(prediction)["observations"],
                               "termination": prediction["metrics"]["termination"]})
        predicted = {"step": len(view["history"]) + 1, "action": action, "candidates": candidates}
        prediction_history.append(predicted)
        emit("experiment_selected", decision=decisions[-1], prediction=predicted, observation=view)
        observation = session.step(action)
        emit("experiment_completed", record=observation["history"][-1], observation=observation)
        summary = investigator.update(observation["history"][-1])
        emit("belief_updated", belief=investigator.history[-1], summary=summary)
        if progress:
            progress(f"  posterior entropy {summary['entropy_nats']:.4f} nats; normalized residual {summary['best_normalized_residual']:.3f}; model mismatch {summary['model_mismatch']}")
    final_view = session.observe()
    aborted = any(row["termination"] != "completed" for row in final_view["history"])
    adequate = not investigator.model_mismatch and not aborted
    identified = adequate and len(investigator.directions) == 2 and entropy(investigator.weights) < 0.2
    if policy == "no_probe":
        estimate, disposition = Calibration(), "abstain"
        reason = "nominal controller baseline with no diagnostic calibration"
    elif identified:
        estimate, disposition = investigator.calibration(), "candidate"
    else:
        estimate, disposition = Calibration(), "abstain"
        reason = ("model mismatch: no declared hypothesis explains the measurements" if investigator.model_mismatch else
                  "diagnostic limit event" if aborted else "insufficient identification or direction coverage")
    commitment = session.commit(asdict(estimate), disposition=disposition, reason=reason)
    emit("committed", commitment=commitment, final_belief=investigator.summary())
    if progress:
        progress(f"Commit: {disposition}. Running independent motion, passive-hold and power-loss verification.")
    verification = verify_calibration(parameters, closing_extra, estimate, seed=seed, rig_factory=rig_factory)
    records = session.sealed_records()
    source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                     for name in ("physics.py", "physical_rig.py", "inquiry.py")}
    if rig_version == 3:
        source_hashes["research_rig.py"] = hashlib.sha256(Path(__file__).with_name("research_rig.py").read_bytes()).hexdigest()
    report = {"schema_version": PROTOCOL_ID, "model_id": session.model_id,
              "configuration": {"case": case, "seed": seed, "policy": policy, "max_tests": max_tests, "budget": budget,
                                "rig_version": rig_version},
              "provenance": {"source_kind": "synthetic", "measured_data_used": False, "hardware_validated": False,
                             "python": platform.python_version(), "numpy": np.__version__, "source_sha256": source_hashes,
                             "control_sensor": "ideal filtered biased encoder/rate; independent logging noise",
                             "force_sensor": "synthetic inline load cell: motor plus gas force minus strut damping",
                             "initialization": "known 20 degree bench fixture, zero velocity and zero motor force",
                             "inference": "72 finite hypotheses; approximate Gaussian likelihood; 48 Monte Carlo fantasies per action",
                             "cost_units": "declared test-cost units including setup; not elapsed time or a financial cost"},
              "initial_observation": initial, "decisions": decisions, "belief_history": investigator.history,
              "prediction_history": prediction_history,
              "final_belief": investigator.summary(), **records,
              "verification": verification,
              "outcome": "verified_in_simulation" if disposition == "candidate" and verification["all_motion_profiles_passed"]
                         else "verification_failed" if disposition == "candidate" else "abstained",
              "evaluator_only_truth": {"parameters": asdict(plant.parameters), "closing_friction_extra_Nm": closing_extra},
              "limitations": ["All scenarios are synthetic engineering fixtures, not population-level research results.",
                              "Finite model bank and an engineering residual threshold; no calibrated coverage guarantee.",
                              "No learned RL policy, autonomous model-structure revision or real-vehicle validation.",
                              "One rigid rotational DOF; no electrical current, flexible bodies, backlash or pinch/contact model.",
                              "A simulator stop is not a hardware emergency-stop guarantee."]}
    if rig_version == 3:
        report["rig_specification"] = plant.metadata()
        report["provenance"]["control_sensor"] = "sampled, delayed, quantized instrumentation shared with the controller"
        report["limitations"][3] = "One rigid hinge; no flexible bodies, torsional coupling, backlash, latch or obstacle contact."
    report["report_sha256"] = digest(report)
    return report


def verify_report(report: Any) -> dict[str, Any]:
    errors = []
    if not isinstance(report, dict) or report.get("schema_version") != PROTOCOL_ID:
        return {"valid": False, "errors": ["unsupported physical inquiry report"]}
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    try:
        if digest(payload) != report.get("report_sha256"):
            errors.append("report digest does not match")
        if digest(report["agent_history"]) != report["commitment"]["history_sha256"]:
            errors.append("committed observation history differs")
        cost = sum(CATALOG[item["action"]].cost for item in report["agent_history"])
        if abs(cost - report["cost"]) > 1e-8 or cost > report["configuration"]["budget"] + 1e-8:
            errors.append("diagnostic cost violates protocol")
        if len(report["agent_history"]) > report["configuration"]["max_tests"]:
            errors.append("diagnostic test count violates protocol")
        Calibration.from_dict(report["commitment"]["estimates"])
        comparisons = report["verification"]["comparisons"]
        if len(comparisons) != 4 or {x["name"] for x in comparisons} != {"full_open", "full_close", "partial_reverse", "cold_open"}:
            errors.append("independent motion profiles differ from the protocol")
        for pair in comparisons:
            for side in ("before", "after"):
                run = pair[side]
                rows = run["trace"]
                elapsed = rows[-1]["time_s"]
                if rows[0]["time_s"] != 0 or elapsed <= 0 or any(b["time_s"] <= a["time_s"] for a,b in zip(rows, rows[1:])):
                    errors.append("verification trace times are invalid")
                    continue
                integral = sum((b["time_s"] - a["time_s"]) * (a["target_angle_rad"] - a["true_angle_rad"])**2
                               for a, b in zip(rows, rows[1:]))
                rmse = math.degrees(math.sqrt(integral / elapsed))
                if abs(rmse - run["metrics"]["tracking_rmse_deg"]) > 1e-7:
                    errors.append("tracking metric differs from the complete trace")
                if abs(elapsed - run["metrics"]["completed_duration_s"]) > 1e-9:
                    errors.append("duration differs from the trace")
                if run["accepted"] != _accepted(run):
                    errors.append("profile acceptance differs from declared thresholds")
        if report["verification"]["all_motion_profiles_passed"] != all(_accepted(item["after"]) for item in comparisons):
            errors.append("overall motion acceptance differs from the individual profiles")
        expected = "verified_in_simulation" if report["commitment"]["disposition"] == "candidate" and all(
            _accepted(item["after"]) for item in report["verification"]["comparisons"]) else (
                "verification_failed" if report["commitment"]["disposition"] == "candidate" else "abstained")
        if expected != report["outcome"]:
            errors.append("outcome disagrees with independent verification")
        for entry in report["agent_history"]:
            for sample in entry["observations"]:
                if set(sample) - {"sample_time_s", "time_s", "sensor_sample_time_s", "sensor_age_s",
                                  "ambient_temperature_C", *OBSERVATION_FIELDS}:
                    errors.append("unexpected agent observation field")
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        errors.append(f"invalid report content: {exc}")
    return {"valid": not errors, "errors": errors, "model_id": report.get("model_id"),
            "report_sha256": report.get("report_sha256"),
            "scope": "Integrity and protocol checks, not a scientific result replication or authenticity signature."}
