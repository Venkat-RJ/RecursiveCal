"""Optional source-bound replay of recorded synthetic physical experiments.

The ordinary verifiers check a report's structure and self-consistency. Replay
uses the declared world and recorded actions to run the plant again. This is
deliberately opt-in: it is more expensive, and archived reports must be checked
against the source revision that originally generated them.

Replay does not authenticate an author, provide tamper-proof signatures, or
validate the model against hardware.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
from pathlib import Path
from typing import Any

from .inquiry import run_study, verify_report
from .rl_environment import PhysicalCalibrationEnv, _source_hashes, verify_episode_report


MAX_DIFFERENCES = 12


def _compare(actual: Any, expected: Any, path: str, errors: list[str]) -> None:
    """Recursively compare a complete report with bounded floating tolerance."""
    if len(errors) >= MAX_DIFFERENCES:
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            errors.append(path + ": expected an object")
            return
        if actual.keys() != expected.keys():
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            errors.append(f"{path}: keys differ (missing={missing[:4]}, extra={extra[:4]})")
        for key in sorted(actual.keys() & expected.keys()):
            _compare(actual[key], expected[key], f"{path}.{key}", errors)
            if len(errors) >= MAX_DIFFERENCES:
                return
    elif isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            errors.append(path + ": sequence length or type differs")
            return
        for i, (got, want) in enumerate(zip(actual, expected)):
            _compare(got, want, f"{path}[{i}]", errors)
            if len(errors) >= MAX_DIFFERENCES:
                return
    elif type(expected) is bool:
        if actual is not expected:
            errors.append(path + ": boolean differs")
    elif isinstance(expected, (int, float)):
        if (type(actual) is bool or not isinstance(actual, (int, float))
                or not math.isfinite(actual) or not math.isfinite(expected)
                or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7)):
            errors.append(path + ": numerical value differs")
    elif type(actual) is not type(expected) or actual != expected:
        errors.append(path + ": value differs")


def _replay_scope() -> str:
    return ("Source-bound deterministic replay of the specified synthetic rig; "
            "not authorship authentication, independent physics implementation, "
            "or hardware validation.")


def verify_rl_replay(report: Any) -> dict[str, Any]:
    """Recreate a physical RL episode from its declared seed and public actions.

    Invalid actions are recorded by category rather than raw input. Any
    deliberately invalid payload reproduces their published transition.
    """
    base = verify_episode_report(report)
    if not base["valid"]:
        return {"valid": False, "failures": ["base:" + failure for failure in base["failures"]],
                "scope": _replay_scope()}
    if report.get("source_sha256") != _source_hashes():
        return {"valid": False, "failures": ["source_revision_mismatch"],
                "scope": _replay_scope()}
    try:
        episode = report["episode"]
        env = PhysicalCalibrationEnv(budget=report["budget"], max_tests=report["max_tests"])
        env.reset(seed=episode["seed"], split=episode["split"])
        for action in report["actions"]:
            if env.completed:
                return {"valid": False, "failures": ["action_after_termination"],
                        "scope": _replay_scope()}
            kind = action["kind"]
            if kind == "experiment":
                env.step({"experiment": action["value"]})
            elif kind == "commit":
                env.step({"commit": action["value"]})
            elif kind == "abstain":
                env.step({"abstain": True})
            elif kind == "invalid":
                env.step({"not_a_legal_action": True})
            elif kind == "host_stop":
                env.force_end(action["value"])
            else:
                return {"valid": False, "failures": ["unknown_action"],
                        "scope": _replay_scope()}
        if not env.completed:
            return {"valid": False, "failures": ["episode_not_terminal"],
                    "scope": _replay_scope()}
        reproduced = env.host_report()
        # Hashes validate each original report separately. Floating-point
        # trajectory values may differ in the final few bits across platforms.
        original = {key: value for key, value in report.items() if key != "report_sha256"}
        expected = {key: value for key, value in reproduced.items() if key != "report_sha256"}
        failures: list[str] = []
        _compare(original, expected, "report", failures)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            RuntimeError, OverflowError, RecursionError) as exc:
        failures = ["replay_error:" + type(exc).__name__]
    return {"valid": not failures, "failures": failures, "scope": _replay_scope()}


def verify_inquiry_replay(report: Any) -> dict[str, Any]:
    """Re-run a built-in inquiry from its original seed, case and policy."""
    base = verify_report(report)
    if not base["valid"]:
        return {"valid": False, "errors": ["base:" + error for error in base["errors"]],
                "scope": _replay_scope()}
    try:
        config = report["configuration"]
        module = Path(__file__).parent
        source_names = ["physics.py", "physical_rig.py", "inquiry.py"]
        if config["rig_version"] == 3:
            source_names.append("research_rig.py")
        source_hashes = {
            name: hashlib.sha256((module / name).read_bytes()).hexdigest()
            for name in source_names
        }
        if report["provenance"]["source_sha256"] != source_hashes:
            return {"valid": False, "errors": ["source_revision_mismatch"],
                    "scope": _replay_scope()}
        reproduced = run_study(
            case=config["case"], seed=config["seed"], policy=config["policy"],
            max_tests=config["max_tests"], budget=config["budget"],
            rig_version=config["rig_version"],
        )
        original = deepcopy(report)
        original.pop("report_sha256", None)
        reproduced.pop("report_sha256", None)
        # Runtime versions are provenance, not simulated observations. The
        # source revision is checked separately above.
        for record in (original, reproduced):
            record["provenance"].pop("python", None)
            record["provenance"].pop("numpy", None)
        errors: list[str] = []
        _compare(original, reproduced, "report", errors)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError,
            RuntimeError, OverflowError, RecursionError) as exc:
        errors = ["replay_error:" + type(exc).__name__]
    return {"valid": not errors, "errors": errors, "scope": _replay_scope()}
