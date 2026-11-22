"""Versioned, observation-only RL task for the dimensioned research rig.

Reset, sampling and evaluation are host operations. A policy receives only the
observation returned by reset/step. This Python API is not a security sandbox:
untrusted policy code must run in a separate process with JSON transport.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Callable

from .inquiry import ACCEPTANCE, InquirySession, digest, public_result, verify_calibration
from .physical_rig import CATALOG, Calibration, RigState, finite, integer
from .physics import ModelParameters

TASK_ID = "recursivecal.physical-calibration-rl/1"
REPORT_ID = "recursivecal.physical-rl-episode/1"
SAMPLER_ID = "recursivecal.physical-world-sampler/1"
MODEL_ID = "recursivecal.physical-rig/3"
SPLITS = ("train", "validation", "test", "ood")
PARAMETER_BOUNDS = {
    "mass_kg": (22.0, 32.0),
    "motor_efficiency": (0.70, 1.00),
    "gas_scale": (0.80, 1.10),
    "friction_coulomb_Nm": (4.0, 12.0),
    "sensor_bias_rad": (-0.020, 0.020),
    "temperature_C": (10.0, 35.0),
}
CALIBRATION_BOUNDS = {
    "mass_kg": (18.0, 40.0), "motor_efficiency": (0.4, 1.2),
    "gas_scale": (0.4, 1.4), "friction_coulomb_Nm": (0.0, 25.0),
    "sensor_bias_rad": (-0.08, 0.08),
}
CELL_BINS = 8
SPLIT_BUCKETS = {"train": (0, 1, 2, 3, 4, 5, 6), "validation": (7,), "test": (8, 9)}
MAX_INVALID_ACTIONS = 2
MAX_TURNS = 8  # Five tests, up to two invalid turns, and one terminal decision.
TEST_COST_WEIGHT = 0.012
REJECTED_COMMIT_PENALTY = 1.0
FORCED_END_PENALTY = 1.0
PROFILE_NAMES = ("full_open", "full_close", "partial_reverse", "cold_open")
PROFILE_TARGET_DEGREES = {"full_open": 78.0, "full_close": 0.0, "partial_reverse": 27.0, "cold_open": 78.0}


def _seed(*parts: Any, reserve: int = 0) -> int:
    raw = json.dumps([SAMPLER_ID, *parts], separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2**31 - reserve)


def parameter_cell(values: dict[str, float]) -> tuple[int, ...]:
    """Whole parameter cells, rather than neighboring trajectory rows, are held out."""
    cell = []
    for name, (low, high) in PARAMETER_BOUNDS.items():
        value = finite(values[name], name, low, high)
        cell.append(min(CELL_BINS - 1, int((value - low) / (high - low) * CELL_BINS)))
    return tuple(cell)


def cell_split(cell: tuple[int, ...] | list[int]) -> str:
    if len(cell) != len(PARAMETER_BOUNDS) or any(type(x) is not int or not 0 <= x < CELL_BINS for x in cell):
        raise ValueError("invalid physical parameter cell")
    raw = json.dumps([SAMPLER_ID, list(cell)], separators=(",", ":")).encode()
    bucket = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % 10
    return next(name for name, buckets in SPLIT_BUCKETS.items() if bucket in buckets)


@dataclass(frozen=True)
class EpisodeSpec:
    """Evaluator-only sampled world. Never put this object in a policy observation."""

    seed: int
    split: str
    sensor_seed: int
    evaluator_seed: int
    parameters: ModelParameters
    closing_friction_extra_Nm: float
    side_effectiveness: tuple[float, float]
    cell: tuple[int, ...]
    variation: str

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["side_effectiveness"] = list(self.side_effectiveness)
        body["cell"] = list(self.cell)
        body["sampler_id"] = SAMPLER_ID
        world = {"parameters": asdict(self.parameters),
                 "closing_friction_extra_Nm": self.closing_friction_extra_Nm,
                 "side_effectiveness": list(self.side_effectiveness)}
        body["world_id"] = digest(world)
        body["episode_id"] = digest({"task_id": TASK_ID, "world_id": body["world_id"],
                                     "sensor_seed": self.sensor_seed, "evaluator_seed": self.evaluator_seed})
        return body


def sample_episode(seed: int, split: str = "train") -> EpisodeSpec:
    """Deterministic continuous worlds with disjoint train/validation/test cells.

    OOD worlds add either directional friction or unequal side effectiveness,
    neither of which is an unknown in the five-field calibration contract.
    Those worlds are for evaluation, not automatically safe or identifiable.
    """
    integer(seed, "seed", 0, 2**31 - 1)
    if split not in SPLITS:
        raise ValueError("split must be train, validation, test or ood")
    rng = random.Random(_seed("world", split, seed))
    for _ in range(10000):
        values = {name: rng.uniform(low, high) for name, (low, high) in PARAMETER_BOUNDS.items()}
        cell = parameter_cell(values)
        if split == "ood" or cell_split(cell) == split:
            break
    else:
        raise RuntimeError("could not sample a cell for the declared split")
    temperature = values.pop("temperature_C")
    parameters = replace(Calibration(**values).model(), temperature_C=temperature,
                         holding_brake_Nm=120.0).validate()
    extra, sides, variation = 0.0, (1.0, 1.0), "continuous_parameters"
    if split == "ood":
        if rng.randrange(2) == 0:
            extra, variation = rng.uniform(12.0, 24.0), "directional_friction"
        else:
            sides, variation = (rng.uniform(0.45, 0.65), rng.uniform(0.90, 1.05)), "unequal_actuators"
    return EpisodeSpec(seed, split, _seed("sensor", split, seed),
                       _seed("evaluation", split, seed, reserve=65536), parameters,
                       extra, sides, cell, variation)


def protocol() -> dict[str, Any]:
    """Public task definition; contains no sampled world or private seed."""
    return {
        "task_id": TASK_ID, "model_id": MODEL_ID, "sampler_id": SAMPLER_ID,
        "observation": "sensor measurements, acquired history, legal experiments and remaining budget",
        "actions": {"experiment": "one currently legal catalog name",
                    "commit": {name: list(bounds) for name, bounds in CALIBRATION_BOUNDS.items()},
                    "abstain": True},
        "action_rule": "Exactly one action key; commit contains exactly the five calibration fields.",
        "default_budget": 8.0, "default_max_tests": 5, "max_invalid_actions": MAX_INVALID_ACTIONS,
        "default_max_turns": MAX_TURNS, "turn_limit_rule": "max_tests + max_invalid_actions + 1",
        "reward": {
            "timing": "terminal only, after calibration is frozen",
            "formula": "candidate_quality - nominal_quality - 0.012 * test_cost - rejected_commit - forced_end",
            "quality": "mean exp(-((RMSE/3 degrees)^2 + (final_error/2 degrees)^2)) over four profiles; incomplete, speed or saturation breaches score zero",
            "test_cost_weight": TEST_COST_WEIGHT,
            "rejected_commit_penalty": REJECTED_COMMIT_PENALTY,
            "forced_end_penalty": FORCED_END_PENALTY,
            "abstention": "retain nominal calibration; zero improvement, pay only consumed test cost",
            "early_stop": "host forces nominal abstention with a 1.0 penalty when the agent stops before committing",
            "bounds": [-3.144, 1.0],
        },
        "acceptance_limits": dict(ACCEPTANCE), "verification_profiles": list(PROFILE_NAMES),
        "verification_target_degrees": dict(PROFILE_TARGET_DEGREES),
        "splits": {"bounds": {name: list(bounds) for name, bounds in PARAMETER_BOUNDS.items()},
                   "cell_bins_per_dimension": CELL_BINS,
                   "assignment": "SHA-256 of sampler version and six-dimensional cell, modulo 10",
                   "buckets": {name: list(value) for name, value in SPLIT_BUCKETS.items()},
                   "ood": "same continuous envelope plus directional friction or unequal actuator effectiveness"},
        "scope": "Synthetic physical calibration research; no measured-hardware or learned-policy claim.",
    }


def _profile_quality(run: dict[str, Any]) -> float:
    m = run["metrics"]
    names = ("tracking_rmse_deg", "final_error_deg", "peak_speed_rad_s", "saturation_fraction")
    if any(isinstance(m[name], bool) or not isinstance(m[name], (int, float))
           or not math.isfinite(m[name]) for name in names):
        raise ValueError("verification contains invalid metrics")
    if m["tracking_rmse_deg"] < 0 or m["peak_speed_rad_s"] < 0 or not 0 <= m["saturation_fraction"] <= 1:
        raise ValueError("verification contains impossible metrics")
    if (m["termination"] != "completed" or m["peak_speed_rad_s"] > ACCEPTANCE["peak_speed_rad_s_max"]
            or m["saturation_fraction"] > ACCEPTANCE["saturation_fraction_max"]):
        return 0.0
    return math.exp(-((m["tracking_rmse_deg"] / ACCEPTANCE["tracking_rmse_deg_max"]) ** 2
                      + (m["final_error_deg"] / ACCEPTANCE["final_error_deg_max"]) ** 2))


def _motion_accepted(run: dict[str, Any]) -> bool:
    _profile_quality(run)  # Validate finite values even for failed profiles.
    m = run["metrics"]
    return (m["termination"] == "completed"
            and m["tracking_rmse_deg"] <= ACCEPTANCE["tracking_rmse_deg_max"]
            and abs(m["final_error_deg"]) <= ACCEPTANCE["final_error_deg_max"]
            and m["peak_speed_rad_s"] <= ACCEPTANCE["peak_speed_rad_s_max"]
            and m["saturation_fraction"] <= ACCEPTANCE["saturation_fraction_max"])


def _trace_metrics_consistent(run: dict[str, Any], final_target_deg: float) -> bool:
    """Recompute score-driving tracking values from the complete sealed trace."""
    rows, metrics = run["trace"], run["metrics"]
    if len(rows) < 2 or rows[0]["time_s"] != 0:
        return False
    for row in rows:
        for name in ("time_s", "target_angle_rad", "true_angle_rad", "true_velocity_rad_s"):
            if isinstance(row[name], bool) or not isinstance(row[name], (float, int)) or not math.isfinite(row[name]):
                return False
    if any(b["time_s"] <= a["time_s"] for a, b in zip(rows, rows[1:])):
        return False
    duration = rows[-1]["time_s"]
    integral = sum((b["time_s"] - a["time_s"]) * (a["target_angle_rad"] - a["true_angle_rad"])**2
                   for a, b in zip(rows, rows[1:]))
    rmse = math.degrees(math.sqrt(integral / duration))
    # An aborted run has not yet reached the target reference. Its final error
    # is against the profile's requested endpoint, not its intermediate target.
    final_error = final_target_deg - math.degrees(rows[-1]["true_angle_rad"])
    return (abs(rmse - metrics["tracking_rmse_deg"]) < 1e-7
            and abs(final_error - metrics["final_error_deg"]) < 1e-7
            and abs(duration - metrics["completed_duration_s"]) < 1e-9
            and metrics["peak_speed_rad_s"] + 1e-9 >= max(abs(row["true_velocity_rad_s"]) for row in rows))


def reward_components(verification: dict[str, Any], cost: float, *, disposition: str,
                      forced_end: bool = False) -> dict[str, Any]:
    """Frozen bounded terminal score, independent of verbal explanations."""
    finite(cost, "test cost", 0, 12)
    if disposition not in ("candidate", "abstain") or type(forced_end) is not bool:
        raise ValueError("invalid reward disposition")
    rows = verification["comparisons"]
    if tuple(row["name"] for row in rows) != PROFILE_NAMES:
        raise ValueError("verification does not contain the four declared profiles")
    nominal = sum(_profile_quality(row["before"]) for row in rows) / len(PROFILE_NAMES)
    candidate = sum(_profile_quality(row["after"]) for row in rows) / len(PROFILE_NAMES)
    accepted = all(_motion_accepted(row["after"]) for row in rows)
    if disposition == "abstain" and abs(candidate - nominal) > 1e-12:
        raise ValueError("abstention must evaluate the same nominal calibration")
    improvement = 0.0 if disposition == "abstain" else candidate - nominal
    test_penalty = TEST_COST_WEIGHT * cost
    rejected_penalty = REJECTED_COMMIT_PENALTY if disposition == "candidate" and not accepted else 0.0
    forced_penalty = FORCED_END_PENALTY if forced_end else 0.0
    return {"nominal_quality": nominal, "candidate_quality": candidate, "improvement": improvement,
            "test_cost": cost, "test_penalty": test_penalty, "rejected_commit_penalty": rejected_penalty,
            "forced_end_penalty": forced_penalty, "all_motion_profiles_passed": accepted,
            "reward": improvement - test_penalty - rejected_penalty - forced_penalty}


def _decode_action(value: Any) -> tuple[str, Any]:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 8192:
            raise ValueError("action is too large")
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = item
            return result
        def invalid_number(_):
            raise ValueError("nonfinite JSON number")
        value = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_number)
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("provide exactly one action")
    if "experiment" in value and isinstance(value["experiment"], str):
        return "experiment", value["experiment"]
    if "commit" in value:
        return "commit", Calibration.from_dict(value["commit"])
    if "abstain" in value and value["abstain"] is True:
        return "abstain", None
    raise ValueError("unknown or malformed physical action")


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = ("rl_environment.py", "inquiry.py", "physical_rig.py", "research_rig.py", "physics.py")
    return {"recursivecal_lab/" + name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names if (root / name).is_file()}


class PhysicalCalibrationEnv:
    """Dependency-free five-return-value environment for physical calibration.

    This follows reset/step conventions but is not a Gymnasium subclass and does
    not invent Box spaces for variable-length observation histories. The JSON
    action and observation schema is the contract. No hidden evaluation data is
    included in step info, even at termination; host_report is explicitly host-only.
    """

    def __init__(self, *, budget: float = 8.0, max_tests: int = 5,
                 rig_factory: Callable[..., Any] | None = None,
                 evaluator: Callable[..., dict[str, Any]] = verify_calibration):
        self.budget = finite(budget, "budget", 0, 12)
        self.max_tests = integer(max_tests, "max_tests", 0, 6)
        self.__rig_type = rig_factory
        self.__evaluator = evaluator
        self.__session: InquirySession | None = None
        self.__spec: EpisodeSpec | None = None
        self.__report: dict[str, Any] | None = None
        self.__turns = 0
        self.__invalid = 0
        self.__actions: list[dict[str, Any]] = []
        self.__transcript: list[dict[str, Any]] = []
        self.__done = False
        self.__reward = 0.0

    def _factory(self, parameters: ModelParameters, **kwargs):
        if self.__rig_type is None:
            from .research_rig import ResearchRig
            rig_type = ResearchRig
        else:
            rig_type = self.__rig_type
        return rig_type(parameters, side_effectiveness=self.__spec.side_effectiveness, **kwargs)

    def reset(self, *, seed: int = 0, split: str = "train") -> tuple[dict[str, Any], dict[str, Any]]:
        """Host-only deterministic episode creation; seed/split stay out of observations."""
        self.__spec = sample_episode(seed, split)
        rig = self._factory(self.__spec.parameters, seed=self.__spec.sensor_seed,
                            state=RigState(), closing_friction_extra_Nm=self.__spec.closing_friction_extra_Nm)
        if getattr(rig, "model_id", None) != MODEL_ID:
            raise ValueError("physical RL requires the version 3 research rig")
        self.__session = InquirySession(rig, max_tests=self.max_tests, budget=self.budget)
        self.__report, self.__turns, self.__invalid = None, 0, 0
        self.__actions, self.__done, self.__reward = [], False, 0.0
        observation, info = self.observe(), self._info()
        self.__transcript = [{"kind": "reset", "observation": deepcopy(observation), "info": info}]
        return observation, info

    def observe(self) -> dict[str, Any]:
        if self.__session is None:
            raise RuntimeError("reset the environment first")
        view = self.__session.observe()
        view.update({"task_id": TASK_ID, "status": "terminated" if self.__done else "active",
                     "invalid_actions_remaining": MAX_INVALID_ACTIONS - self.__invalid,
                     "turns_remaining": max(0, self.max_tests + MAX_INVALID_ACTIONS + 1 - self.__turns),
                     "calibration_bounds": {name: list(bounds) for name, bounds in CALIBRATION_BOUNDS.items()}})
        return view

    def _info(self, **extra) -> dict[str, Any]:
        return {"task_id": TASK_ID, "model_id": MODEL_ID, **extra}

    def _transition(self, reward: float, terminated: bool, truncated: bool, info: dict[str, Any]):
        observation = self.observe()
        self.__transcript.append({"kind": "step", "action": deepcopy(self.__actions[-1]),
                                  "observation": deepcopy(observation), "reward": reward,
                                  "terminated": terminated, "truncated": truncated, "info": deepcopy(info)})
        return observation, reward, terminated, truncated, info

    def _finish(self, calibration: Calibration, disposition: str, reason: str, *,
                forced: bool = False, truncated: bool = False):
        commitment = self.__session.commit(asdict(calibration), disposition=disposition, reason=reason)
        records = self.__session.sealed_records()
        verification = self.__evaluator(self.__spec.parameters, self.__spec.closing_friction_extra_Nm,
                                       calibration, seed=self.__spec.evaluator_seed, rig_factory=self._factory)
        components = reward_components(verification, records["cost"], disposition=disposition, forced_end=forced)
        self.__done, self.__reward = True, components["reward"]
        transition = self._transition(self.__reward, not truncated, truncated,
                                      self._info(completion_reason=reason))
        report = {"schema_version": REPORT_ID, "task": protocol(), "episode": self.__spec.to_dict(),
                  "budget": self.budget, "max_tests": self.max_tests, "turns": self.__turns,
                  "invalid_actions": self.__invalid, "actions": deepcopy(self.__actions),
                  "policy_transcript": deepcopy(self.__transcript),
                  "completion_reason": reason, "terminated": not truncated, "truncated": truncated,
                  "forced_end": forced, "commitment": commitment, "session": records,
                  "verification": verification, "score": components, "source_sha256": _source_hashes(),
                  "hardware_validated": False}
        report["report_sha256"] = digest(report)
        self.__report = report
        return transition

    def step(self, action: dict[str, Any] | str):
        if self.__session is None:
            raise RuntimeError("reset the environment first")
        if self.__done:
            raise RuntimeError("episode has ended; reset before another action")
        self.__turns += 1
        try:
            kind, value = _decode_action(action)
            if kind == "experiment" and value not in self.__session.observe()["legal_actions"]:
                raise ValueError("experiment is unavailable")
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            self.__invalid += 1
            self.__actions.append({"turn": self.__turns, "kind": "invalid", "accepted": False})
            if self.__invalid >= MAX_INVALID_ACTIONS:
                return self._finish(Calibration(), "abstain", "invalid_action_limit", forced=True, truncated=True)
            return self._transition(0.0, False, False, self._info(error="invalid_action"))
        recorded = asdict(value) if kind == "commit" else value
        self.__actions.append({"turn": self.__turns, "kind": kind, "value": recorded, "accepted": True})
        if kind == "commit":
            return self._finish(value, "candidate", "calibration_committed")
        if kind == "abstain":
            return self._finish(Calibration(), "abstain", "policy_abstained")
        view = self.__session.step(value)
        if view["history"][-1]["termination"] != "completed":
            return self._finish(Calibration(), "abstain", "diagnostic_aborted", forced=True)
        if self.__turns >= self.max_tests + MAX_INVALID_ACTIONS + 1:
            return self._finish(Calibration(), "abstain", "turn_limit", forced=True, truncated=True)
        return self._transition(0.0, False, False, self._info())

    @property
    def completed(self) -> bool:
        return self.__done

    def force_end(self, reason: str = "agent_stopped"):
        """Host-only termination for a stopped model or an exhausted host turn cap.

        An interrupted policy cannot obtain the free zero reward of an explicit
        abstention. Infrastructure or simulator exceptions should still raise;
        they are not classified as policy stops by this method.
        """
        if self.__session is None:
            raise RuntimeError("reset the environment first")
        if self.__done:
            raise RuntimeError("episode has already ended")
        if reason not in ("agent_stopped", "host_turn_limit"):
            raise ValueError("unsupported host termination reason")
        self.__turns += 1
        self.__actions.append({"turn": self.__turns, "kind": "host_stop", "value": reason, "accepted": False})
        return self._finish(Calibration(), "abstain", reason, forced=True, truncated=True)

    @property
    def terminal_reward(self) -> float:
        return self.__reward if self.__done else 0.0

    def host_report(self) -> dict[str, Any]:
        """Evaluator-only evidence, obtainable only after a sealed terminal decision."""
        if self.__report is None:
            raise RuntimeError("commit or abstain before requesting evaluator evidence")
        return deepcopy(self.__report)


def verify_episode_report(report: dict[str, Any]) -> dict[str, Any]:
    """Check integrity and protocol consistency; this does not rerun the physics."""
    failures = []
    try:
        body = {key: value for key, value in report.items() if key != "report_sha256"}
        if digest(body) != report["report_sha256"]:
            failures.append("report_digest")
        if report["schema_version"] != REPORT_ID or report["task"] != protocol():
            failures.append("protocol")
        episode = report["episode"]
        if episode != sample_episode(episode["seed"], episode["split"]).to_dict():
            failures.append("sampled_world")
        integer(report["max_tests"], "max_tests", 0, 6)
        finite(report["budget"], "budget", 0, 12)
        records, commitment = report["session"], report["commitment"]
        history = records["agent_history"]
        if commitment != records["commitment"] or digest(history) != commitment["history_sha256"]:
            failures.append("committed_history")
        calibration = Calibration.from_dict(commitment["estimates"])
        if commitment["disposition"] == "abstain" and asdict(calibration) != asdict(Calibration()):
            failures.append("abstention_calibration")
        expected_cost = sum(CATALOG[row["action"]].cost for row in history)
        if (abs(expected_cost - records["cost"]) > 1e-10 or expected_cost > report["budget"] + 1e-10
                or len(history) > report["max_tests"]):
            failures.append("budget")
        if len(history) != len(records["diagnostics"]):
            failures.append("diagnostic_history")
        for public, private in zip(history, records["diagnostics"]):
            expected = {"action": private["action"], "cost": CATALOG[private["action"]].cost,
                        "start_observation": public["start_observation"], **public_result(private)}
            if public != expected:
                failures.append("observation_boundary")
                break
        if type(report["terminated"]) is not bool or type(report["truncated"]) is not bool or report["terminated"] == report["truncated"]:
            failures.append("terminal_flags")
        reason = report["completion_reason"]
        if reason not in ("calibration_committed", "policy_abstained", "diagnostic_aborted", "invalid_action_limit", "turn_limit",
                          "agent_stopped", "host_turn_limit"):
            failures.append("completion_reason")
        forced = reason in ("diagnostic_aborted", "invalid_action_limit", "turn_limit", "agent_stopped", "host_turn_limit")
        if report["forced_end"] != forced:
            failures.append("forced_end")
        if forced and commitment["disposition"] != "abstain":
            failures.append("forced_commitment")
        if report["truncated"] != (reason in ("invalid_action_limit", "turn_limit", "agent_stopped", "host_turn_limit")):
            failures.append("truncation_reason")
        actions = report["actions"]
        integer(report["invalid_actions"], "invalid_actions", 0, MAX_INVALID_ACTIONS)
        integer(report["turns"], "turns", 1, report["max_tests"] + MAX_INVALID_ACTIONS + 1)
        if (len(actions) != report["turns"] or [row["turn"] for row in actions] != list(range(1, report["turns"] + 1))
                or sum(row["kind"] == "invalid" for row in actions) != report["invalid_actions"]):
            failures.append("turn_history")
        if [row["value"] for row in actions if row["kind"] == "experiment"] != [row["action"] for row in history]:
            failures.append("action_history")
        transcript = report["policy_transcript"]
        if (len(transcript) != len(actions) + 1 or transcript[0]["kind"] != "reset"
                or [row["action"] for row in transcript[1:]] != actions):
            failures.append("policy_transcript")
        if any(row["reward"] != 0 or row["terminated"] or row["truncated"] for row in transcript[1:-1]):
            failures.append("premature_terminal_signal")
        # The digest detects changed bytes, but a rehashed report must also bind
        # the policy's last action to the sealed decision and its terminal cause.
        # Otherwise an action can claim one calibration while another is scored.
        terminal_kind = {
            "calibration_committed": "commit", "policy_abstained": "abstain",
            "diagnostic_aborted": "experiment", "invalid_action_limit": "invalid",
            "turn_limit": "experiment", "agent_stopped": "host_stop",
            "host_turn_limit": "host_stop",
        }.get(reason)
        if (actions[-1]["kind"] != terminal_kind or commitment["reason"] != reason
                or transcript[-1]["info"].get("completion_reason") != reason):
            failures.append("terminal_action")
        if commitment["disposition"] != ("candidate" if reason == "calibration_committed" else "abstain"):
            failures.append("terminal_commitment")
        if reason == "calibration_committed" and Calibration.from_dict(actions[-1]["value"]) != calibration:
            failures.append("terminal_calibration")
        if reason == "policy_abstained" and actions[-1].get("value") is not None:
            failures.append("terminal_action")
        if reason in ("agent_stopped", "host_turn_limit") and actions[-1].get("value") != reason:
            failures.append("terminal_action")
        if (reason == "invalid_action_limit") != (report["invalid_actions"] == MAX_INVALID_ACTIONS):
            failures.append("invalid_action_limit")
        if reason == "turn_limit" and report["turns"] != report["max_tests"] + MAX_INVALID_ACTIONS + 1:
            failures.append("turn_limit")
        for index, action in enumerate(actions):
            kind = action["kind"]
            if (kind not in ("experiment", "commit", "abstain", "invalid", "host_stop")
                    or action.get("accepted") is not (kind in ("experiment", "commit", "abstain"))
                    or (index < len(actions) - 1 and kind in ("commit", "abstain", "host_stop"))):
                failures.append("action_protocol")
                break
        aborted = [index for index, item in enumerate(history) if item["termination"] != "completed"]
        if ((reason == "diagnostic_aborted" and (not history or aborted != [len(history) - 1]))
                or (reason != "diagnostic_aborted" and aborted)):
            failures.append("diagnostic_termination")
        verification = report["verification"]
        for row in verification["comparisons"]:
            for label in ("before", "after"):
                if row[label]["accepted"] != _motion_accepted(row[label]):
                    failures.append("acceptance")
                if not _trace_metrics_consistent(row[label], PROFILE_TARGET_DEGREES[row["name"]]):
                    failures.append("verification_trace")
        if verification["all_motion_profiles_passed"] != all(_motion_accepted(row["after"]) for row in verification["comparisons"]):
            failures.append("overall_acceptance")
        if verification["model_id"] != MODEL_ID:
            failures.append("physical_model")
        expected_score = reward_components(verification, expected_cost,
                                            disposition=commitment["disposition"], forced_end=forced)
        if report["score"] != expected_score:
            failures.append("reward")
        if (transcript[-1]["reward"] != expected_score["reward"]
                or transcript[-1]["terminated"] != report["terminated"]
                or transcript[-1]["truncated"] != report["truncated"]):
            failures.append("terminal_transcript")
        if report["hardware_validated"] is not False or verification["hardware_validated"] is not False:
            failures.append("hardware_claim")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError):
        failures.append("invalid_report")
    return {"valid": not failures, "failures": sorted(set(failures)),
            "scope": "Integrity and protocol consistency; not independent physical replay or authorship authentication."}


def run_smoke(*, seed: int = 7, split: str = "validation", policy: str = "fixed") -> dict[str, Any]:
    """Small real-engine rollout for integration checks, not policy training."""
    if policy not in ("fixed", "no_probe"):
        raise ValueError("smoke policy must be fixed or no_probe")
    env = PhysicalCalibrationEnv()
    env.reset(seed=seed, split=split)
    if policy == "fixed":
        for experiment in ("high_sweep", "low_sweep", "mid_sweep"):
            view = env.observe()
            if env.completed or experiment not in view["legal_actions"]:
                break
            env.step({"experiment": experiment})
    if not env.completed:
        env.step({"abstain": True} if policy == "no_probe" else {"commit": asdict(Calibration())})
    return env.host_report()


def run_smoke_rollout(*, seed: int = 7, split: str = "test", policy: str = "fixed") -> dict[str, Any]:
    """CLI-friendly name; report includes the complete observation-only transcript."""
    return run_smoke(seed=seed, split=split, policy=policy)
