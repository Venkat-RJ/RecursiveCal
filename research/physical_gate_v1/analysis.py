"""World-paired descriptive analysis for the frozen physical gate protocol.

This module consumes already sealed evaluator records. It never selects an
experiment, fits a calibration, or accesses a simulator. A positive gate applies
only to the declared two-test synthetic pilot, not to hardware reliability.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
from typing import Any, Iterable

import numpy as np


SCHEMA = "recursivecal.physical-research-gate-analysis/1"
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 81971
PRACTICAL_MARGIN = 0.005
COST_TOLERANCE = 1e-9
POLICIES = (
    "abstain", "initial_bayes", "fixed_bayes", "adaptive_bayes",
    "shuffled_bayes", "fixed_two_bayes", "adaptive_two_bayes",
    "shuffled_two_bayes", "map_initial", "map_fixed_two",
)
SCORE_FIELDS = (
    "nominal_quality", "candidate_quality", "improvement", "test_cost",
    "rejected_commit_penalty", "forced_end_penalty", "reward",
)
COMPARISONS = (
    ("adaptive_bayes", "initial_bayes"),
    ("adaptive_bayes", "fixed_bayes"),
    ("adaptive_bayes", "shuffled_bayes"),
    ("adaptive_two_bayes", "fixed_two_bayes"),
    ("adaptive_two_bayes", "shuffled_two_bayes"),
    ("adaptive_bayes", "map_fixed_two"),
)
EVALUATION_SEEDS = {
    "validation": tuple(range(3000, 3004)),
    "test": tuple(range(4000, 4012)),
    "ood": tuple(range(5000, 5012)),
}
OOD_FAMILIES = ("directional_friction", "unequal_actuators")
ACTION_ORDER = ("STOP", "low_sweep", "high_sweep", "mid_sweep", "hold", "coast", "reference")
SCOPE = (
    "Exploratory paired-world pilot of a two-test synthetic subtask. Small-sample "
    "percentile intervals do not establish low failure rates, global "
    "identifiability, RL superiority, or measured-hardware accuracy."
)


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _key(record: dict[str, Any]) -> tuple[str, int]:
    return record["split"], record["seed"]


def _world(record: dict[str, Any]) -> dict[str, Any]:
    result = {"split": record["split"], "seed": record["seed"],
              "variation": record.get("variation", "unspecified")}
    if "world_id" in record:
        result["world_id"] = record["world_id"]
    return result


def _policy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict) or not isinstance(value.get("score"), dict):
        return ["missing score object"]
    score = value["score"]
    errors = ["invalid " + field for field in SCORE_FIELDS if not _finite(score.get(field))]
    if value.get("disposition") not in ("candidate", "abstain"):
        errors.append("invalid disposition")
    if not isinstance(value.get("completion_reason"), str):
        errors.append("missing completion reason")
    if type(score.get("all_motion_profiles_passed")) is not bool:
        errors.append("invalid motion acceptance flag")
    if errors:
        return errors
    if not 0 <= score["test_cost"] <= 4.8 + COST_TOLERANCE:
        errors.append("cost outside the declared two-test budget")
    for field in ("nominal_quality", "candidate_quality"):
        if not 0 <= score[field] <= 1:
            errors.append(field + " outside [0, 1]")
    for field in ("rejected_commit_penalty", "forced_end_penalty"):
        if score[field] not in (0, 1):
            errors.append(field + " is not a declared zero-or-one penalty")
    expected_improvement = (0.0 if value["disposition"] == "abstain"
                            else score["candidate_quality"] - score["nominal_quality"])
    if abs(score["improvement"] - expected_improvement) > COST_TOLERANCE:
        errors.append("improvement contradicts quality/disposition")
    expected_reward = (score["improvement"] - .012 * score["test_cost"]
                       - score["rejected_commit_penalty"] - score["forced_end_penalty"])
    if abs(score["reward"] - expected_reward) > COST_TOLERANCE:
        errors.append("reward contradicts its components")
    if value["disposition"] == "abstain":
        if abs(score["candidate_quality"] - score["nominal_quality"]) > COST_TOLERANCE:
            errors.append("abstention changed nominal quality")
        if score["rejected_commit_penalty"]:
            errors.append("abstention charged rejected-commit penalty")
    elif bool(score["rejected_commit_penalty"]) == score["all_motion_profiles_passed"]:
        errors.append("candidate rejection contradicts acceptance flag")
    return errors


def paired_comparison(records: Iterable[dict[str, Any]], policy: str,
                      reference: str) -> dict[str, Any]:
    """Bootstrap within-world reward differences without unpaired substitution.

    The input unit is one world, regardless of how many profile or observation
    rows its policies contain. Missing or invalid outcomes are listed explicitly
    and make the comparison incomplete. No comparison with missing outcomes can
    pass the gate. Each comparison resets the fixed RNG, so comparisons over the
    same ordered worlds share the same bootstrap index draws.
    """
    records = sorted(records, key=_key)
    seen, worlds, differences, missing = set(), [], [], []
    for row in records:
        key = _key(row)
        if key in seen:
            raise ValueError("duplicate world in paired comparison: " + str(key))
        seen.add(key)
        outcomes = row.get("policies", {})
        if any(_policy_errors(outcomes.get(name)) for name in (policy, reference)):
            missing.append(_world(row))
            continue
        worlds.append(_world(row))
        differences.append(float(outcomes[policy]["score"]["reward"]
                                 - outcomes[reference]["score"]["reward"]))
    n = len(differences)
    result = {
        "policy": policy, "reference": reference, "n": n,
        "complete_pairs": not missing, "missing_worlds": missing,
        "worlds": worlds, "paired_differences": differences,
        "mean_difference": None, "ci95": None,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "interval_method": "paired-world percentile bootstrap",
        "exceeds_practical_margin": False,
    }
    if n:
        delta = np.asarray(differences, dtype=float)
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        indices = rng.integers(n, size=(BOOTSTRAP_REPLICATES, n))
        draws = delta[indices].mean(axis=1)
        limits = np.quantile(draws, (.025, .975)).tolist()
        result.update(mean_difference=float(delta.mean()), ci95=limits,
                      exceeds_practical_margin=not missing and limits[0] > PRACTICAL_MARGIN)
    return result


def _policy_summary(records: list[dict[str, Any]], name: str) -> dict[str, Any]:
    present = [(row, row.get("policies", {}).get(name)) for row in records]
    valid = [(row, item) for row, item in present if not _policy_errors(item)]
    scores = [item["score"] for _, item in valid]
    n = len(scores)
    mean = {field: (float(np.mean([score[field] for score in scores])) if n else None)
            for field in SCORE_FIELDS}
    counts = {
        "commit": sum(item["disposition"] == "candidate" for _, item in valid),
        "abstain": sum(item["disposition"] == "abstain" for _, item in valid),
        "rejected": sum(score["rejected_commit_penalty"] > 0 for score in scores),
        "forced": sum(score["forced_end_penalty"] > 0 for score in scores),
        "rejected_or_forced": sum(score["rejected_commit_penalty"] > 0
                                  or score["forced_end_penalty"] > 0 for score in scores),
        "guard_abort": sum(item["completion_reason"] == "diagnostic_aborted" for _, item in valid),
        "all_motion_profiles_passed": sum(score["all_motion_profiles_passed"] for score in scores),
    }
    return {
        "n": n, "expected_world_count": len(records),
        "worlds": [_world(row) for row, _ in valid],
        "mean": mean, "rewards": [float(score["reward"]) for score in scores],
        "counts": counts,
        "rejected_or_forced_fraction": counts["rejected_or_forced"] / n if n else None,
        "actual_total_test_cost": math.fsum(score["test_cost"] for score in scores),
        "second_actions": dict(sorted(Counter(str(item.get("second_action", "unspecified"))
                                               for _, item in valid).items())),
        "completion_reasons": dict(sorted(Counter(item["completion_reason"] for _, item in valid).items())),
    }


def _group_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    records = sorted(records, key=_key)
    return {
        "n": len(records), "worlds": [_world(row) for row in records],
        "policies": {name: _policy_summary(records, name) for name in POLICIES},
        "comparisons": {a + "_minus_" + b: paired_comparison(records, a, b)
                        for a, b in COMPARISONS},
    }


def _shuffle_costs(records: list[dict[str, Any]]) -> dict[str, Any]:
    results = {}
    for a, b in (("adaptive_bayes", "shuffled_bayes"),
                 ("adaptive_two_bayes", "shuffled_two_bayes")):
        valid = [row for row in records if all(not _policy_errors(row.get("policies", {}).get(name))
                                              for name in (a, b))]
        cost_a = math.fsum(row["policies"][a]["score"]["test_cost"] for row in valid)
        cost_b = math.fsum(row["policies"][b]["score"]["test_cost"] for row in valid)
        results[a + "_versus_" + b] = {
            "n": len(valid), "expected_world_count": len(records),
            "adaptive_actual_cost": cost_a, "shuffled_actual_cost": cost_b,
            "difference": cost_a - cost_b, "tolerance": COST_TOLERANCE,
            "passed": bool(records) and len(valid) == len(records)
                      and abs(cost_a - cost_b) <= COST_TOLERANCE,
        }
    return results


def summary(records: Iterable[dict[str, Any]], *, complete: bool = True,
            integrity_passed: bool = True) -> dict[str, Any]:
    """Summarize sealed outcomes and apply the exact protocol-1 readiness gate.

    ``integrity_passed`` must reflect the caller's actual source, interface,
    verifier and replay checks; this function cannot infer their success from
    scores. The declared evaluation seed manifest and every required policy
    outcome are necessary for a complete result. A timeout, missing evidence,
    invalid component arithmetic or unmatched actual shuffle costs yields STOP.
    A complete valid experiment that misses a scientific threshold yields
    REVISE TASK. Only all passing thresholds yield TRAIN.
    """
    records = list(records)
    errors, usable, seen, world_ids = [], [], set(), set()
    for index, row in enumerate(records):
        if (not isinstance(row, dict) or row.get("split") not in ("train", *EVALUATION_SEEDS)
                or type(row.get("seed")) is not int or not isinstance(row.get("policies"), dict)):
            errors.append(f"record {index}: invalid world identity or policy mapping")
            continue
        key = _key(row)
        if key in seen:
            errors.append("duplicate world record: " + str(key))
            continue
        seen.add(key)
        if row["split"] == "train":
            continue  # Training action tables have a separate selection_examples API.
        if ("variation" in row and not isinstance(row["variation"], str)):
            errors.append(f"{key}: invalid variation label")
            continue
        if row["split"] == "ood" and row.get("variation") not in OOD_FAMILIES:
            errors.append(f"{key}: OOD variation is not a declared sampler family")
        if "world_id" in row:
            identifier = row["world_id"]
            if not isinstance(identifier, str) or not identifier:
                errors.append(f"{key}: invalid world ID")
            elif identifier in world_ids:
                errors.append(f"{key}: repeated physical world ID is not an independent world")
            else:
                world_ids.add(identifier)
        usable.append(row)
        for name in POLICIES:
            for error in _policy_errors(row["policies"].get(name)):
                errors.append(f"{key}/{name}: {error}")
        for name in ("abstain", "initial_bayes", "map_initial"):
            item = row["policies"].get(name)
            if not _policy_errors(item) and abs(item["score"]["test_cost"]) > COST_TOLERANCE:
                errors.append(f"{key}/{name}: initial-only policy spent experiment cost")
        item = row["policies"].get("abstain")
        if not _policy_errors(item) and (item["disposition"] != "abstain"
                                        or abs(item["score"]["reward"]) > COST_TOLERANCE):
            errors.append(f"{key}/abstain: immediate abstention must have zero reward")
    splits = {}
    manifest = {}
    cost_checks = {}
    for split, expected in EVALUATION_SEEDS.items():
        rows = [row for row in usable if row["split"] == split]
        actual = sorted(row["seed"] for row in rows)
        manifest[split] = {"expected_seeds": list(expected), "actual_seeds": actual,
                           "passed": actual == list(expected)}
        splits[split] = _group_summary(rows)
        cost_checks[split] = _shuffle_costs(rows)
    ood = [row for row in usable if row["split"] == "ood"]
    family_names = sorted(set(OOD_FAMILIES) | {row.get("variation", "unspecified") for row in ood})
    families = {name: _group_summary([row for row in ood if row.get("variation", "unspecified") == name])
                for name in family_names}
    # Shuffles preserve each whole split's cost, not each OOD family's cost.
    # Requiring family cost equality would reject valid cross-family permutations.
    checks = []

    def check(name: str, passed: bool, detail: Any, category: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail, "category": category})

    check("complete_execution", complete is True, "pilot complete" if complete else "pilot incomplete",
          "evidence")
    check("integrity", integrity_passed is True and not errors,
          {"caller_integrity_passed": integrity_passed, "validation_errors": errors}, "evidence")
    check("evaluation_manifest", all(item["passed"] for item in manifest.values()), manifest, "evidence")
    check("shuffle_actual_costs", all(item["passed"] for split in cost_checks.values() for item in split.values()),
          cost_checks, "evidence")
    test = splits["test"]
    adaptive = test["policies"]["adaptive_bayes"]
    adaptive_mean = adaptive["mean"]["reward"]
    check("adaptive_positive_test_reward", adaptive_mean is not None and adaptive_mean > 0,
          adaptive_mean, "calibration_value")
    for a, b in COMPARISONS[:5]:
        comparison = test["comparisons"][a + "_minus_" + b]
        check(a + "_beats_" + b, comparison["exceeds_practical_margin"], comparison,
              "conditional_experiment_value")
    map_comparison = test["comparisons"]["adaptive_bayes_minus_map_fixed_two"]
    difference = map_comparison["mean_difference"]
    check("adaptive_mean_within_map_margin",
          map_comparison["complete_pairs"] and difference is not None and difference >= -PRACTICAL_MARGIN,
          {"mean_difference": difference, "minimum": -PRACTICAL_MARGIN}, "classical_comparator")
    reference = test["policies"]["map_fixed_two"]
    for name in ("rejected", "guard_abort"):
        check("adaptive_" + name + "_no_more_than_map",
              adaptive["n"] == reference["n"] == len(EVALUATION_SEEDS["test"])
              and adaptive["counts"][name] <= reference["counts"][name],
              {"adaptive": adaptive["counts"][name], "map": reference["counts"][name]},
              "classical_comparator")
    ood_adaptive = splits["ood"]["policies"]["adaptive_bayes"]
    ood_mean = ood_adaptive["mean"]["reward"]
    ood_fraction = ood_adaptive["rejected_or_forced_fraction"]
    check("ood_mean_reward", ood_mean is not None and ood_mean >= -.05,
          {"mean": ood_mean, "minimum": -.05}, "ood")
    check("ood_rejected_or_forced_fraction", ood_fraction is not None and ood_fraction <= .10,
          {"fraction": ood_fraction, "maximum": .10,
           "count": ood_adaptive["counts"]["rejected_or_forced"], "n": ood_adaptive["n"]}, "ood")
    failed = [item for item in checks if not item["passed"]]
    decision = ("STOP" if any(item["category"] == "evidence" for item in failed)
                else "REVISE TASK" if failed else "TRAIN")
    return {
        "schema_version": SCHEMA, "scope": SCOPE, "decision": decision,
        "complete": complete is True and all(item["passed"] for item in manifest.values()),
        "integrity_passed": integrity_passed is True and not errors,
        "pilot_incomplete": complete is not True or not all(item["passed"] for item in manifest.values()),
        "reasons": [item["name"] for item in failed], "checks": checks,
        "validation_errors": errors, "manifest": manifest,
        "splits": splits, "ood_families": families, "shuffle_cost_checks": cost_checks,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
                      "unit": "world", "paired": True, "interval": "percentile 95%"},
    }


def selection_examples(training_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Find training-selected illustrations with different best actual actions.

    Each world supplies ``action_scores`` (or ``policies`` keyed by the seven
    action names). Each value contains a full sealed ``score`` dict, disposition
    and completion reason, as in summary(). ``first_observation`` is copied for
    the illustration. All seven actual counterfactual outcomes must be present.
    Ties follow ACTION_ORDER, but worlds whose sets of reward-maximizing actions
    overlap do not establish distinct optima and are not returned as a pair.
    This searches training data only and is not independent confirmation.
    """
    examples, skipped = [], []
    for row in sorted(training_records, key=_key):
        if row.get("split") != "train":
            raise ValueError("selection illustrations may use training worlds only")
        table = row.get("action_scores", row.get("policies", {}))
        errors = {action: _policy_errors(table.get(action)) for action in ACTION_ORDER}
        errors = {action: value for action, value in errors.items() if value}
        if errors:
            skipped.append({**_world(row), "errors": errors})
            continue
        rewards = {action: float(table[action]["score"]["reward"]) for action in ACTION_ORDER}
        best_reward = max(rewards.values())
        best = [action for action in ACTION_ORDER if best_reward - rewards[action] <= 1e-12]
        other = [reward for action, reward in rewards.items() if action not in best]
        example = {**_world(row), "first_observation": deepcopy(row.get("first_observation")),
                   "best_actions": best, "selected_best_action": best[0],
                   "best_reward": best_reward,
                   "margin_to_other_actions": best_reward - max(other) if other else 0.0,
                   "actions": {action: {
                       "score": deepcopy(table[action]["score"]),
                       "disposition": table[action]["disposition"],
                       "completion_reason": table[action]["completion_reason"],
                       "report_path": table[action].get("report_path"),
                   } for action in ACTION_ORDER}}
        examples.append(example)
    pairs = [(a, b) for i, a in enumerate(examples) for b in examples[i + 1:]
             if set(a["best_actions"]).isdisjoint(b["best_actions"])]
    if pairs:
        chosen = max(pairs, key=lambda pair: min(item["margin_to_other_actions"] for item in pair))
        output = list(chosen)
        reason = "Two training worlds have disjoint reward-maximizing actual second-action sets."
    else:
        output = []
        reason = "No pair of training worlds with disjoint best actual second-action sets was found."
    return {"different_best_actions": bool(pairs), "examples": output, "reason": reason,
            "eligible_worlds": len(examples), "skipped_worlds": skipped,
            "scope": "Training-selected illustrations, not independent held-out confirmation."}
