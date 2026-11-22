"""Foreground, source-frozen CPU pilot for the version 3 physical task.

Run from the repository root. All learned choices are locked using training
worlds before validation/test/OOD execution. The host holds worlds and scores;
policy functions receive public observations and a public training-model bank.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recursivecal_lab.evidence_replay import verify_rl_replay
from recursivecal_lab.inquiry import digest
from recursivecal_lab.physical_rig import CATALOG, Calibration
from recursivecal_lab.rl_environment import PhysicalCalibrationEnv, sample_episode, verify_episode_report
from research.physical_gate_v1.bayes import FiniteBayes, model_qualities
from research.physical_gate_v1.identification import fit_history
from research.physical_gate_v1.analysis import summary, selection_examples
from research.physical_gate_v1.evidence import EvidenceStore, load_report

RUN_ID = "recursivecal.physical-research-gate/1"
BASE_COMMIT = "bff95c2bf5b9102c7e9db5f005ca20de343c7287"
FIRST = "high_sweep"
SECOND = ["STOP", *CATALOG]
SEEDS = {"bank": list(range(1000, 1012)), "selection": list(range(2000, 2008)),
         "validation": list(range(3000, 3004)), "test": list(range(4000, 4012)),
         "ood": list(range(5000, 5012))}
POLICIES = ["abstain", "initial_bayes", "fixed_bayes", "adaptive_bayes", "shuffled_bayes",
            "fixed_two_bayes", "adaptive_two_bayes", "shuffled_two_bayes", "map_initial", "map_fixed_two"]
SOURCES = ["recursivecal_lab/physics.py", "recursivecal_lab/physical_rig.py",
           "recursivecal_lab/research_rig.py", "recursivecal_lab/inquiry.py",
           "recursivecal_lab/rl_environment.py", "recursivecal_lab/evidence_replay.py",
           *["research/physical_gate_v1/" + name for name in
             ("run.py", "identification.py", "bayes.py", "analysis.py", "evidence.py", "observability.py",
              "sensitivity.py", "PROTOCOL.md", "requirements.lock")]]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def read_json(path: Path) -> Any:
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


class Limit(RuntimeError):
    pass


def verify_observability(output: Path) -> dict[str, Any]:
    audit = read_json(output / "observability.json.gz")
    prefixes = read_json(output / "observability-prefixes.json.gz")
    for report in (audit, prefixes):
        if report["status"] != "complete" or digest({k: v for k, v in report.items() if k != "report_sha256"}) != report["report_sha256"]:
            raise ValueError("observability report is incomplete or has an invalid digest")
        for name, expected in report["source_sha256"].items():
            if sha(ROOT / name) != expected:
                raise ValueError("observability source differs: " + name)
    if (len(audit["analyses"]) != 168 or len(audit["runs"]) != 1764
            or len(prefixes["analyses"]) != 144 or not audit["structural_checks_passed"]
            or prefixes["original_report_sha256"] != audit["report_sha256"]
            or prefixes["input"]["file_sha256"] != sha(output / "observability.json.gz")):
        raise ValueError("observability coverage or prefix binding differs")
    return {"valid": True, "trajectories": len(audit["runs"]), "analyses": len(audit["analyses"]),
            "prefix_analyses": len(prefixes["analyses"]),
            "structural_checks_passed": audit["structural_checks_passed"],
            "primary_prefix_summary": prefixes["primary_by_cost"]}


class Pilot:
    def __init__(self, output: Path, max_seconds: float):
        self.output, self.started, self.max_seconds = output, time.monotonic(), max_seconds
        self.source_hashes = {name: sha(ROOT / name) for name in SOURCES}
        self.models: list[Calibration] = []
        self.candidates: list[Calibration | None] = [None, Calibration()]
        self.utilities = None
        self.cutoff = 1e100
        self.records: list[dict[str, Any]] = []
        self.training: list[dict[str, Any]] = []
        self.report_files: dict[str, dict[str, Any]] = {}
        self.integrity_checks: list[dict[str, Any]] = []
        self.evidence = EvidenceStore(output)
        self.state = {"schema_version": RUN_ID, "base_commit": BASE_COMMIT, "status": "running",
                      "seed_manifest": SEEDS, "source_sha256": self.source_hashes,
                      "max_seconds": max_seconds, "python": platform.python_version(),
                      "numpy": np.__version__, "scipy": scipy.__version__, "selection_locked": False,
                      "hardware_validated": False}
        self.checkpoint()

    def check(self) -> None:
        if time.monotonic() - self.started >= self.max_seconds:
            raise Limit("declared elapsed cap reached")
        if any(sha(ROOT / name) != expected for name, expected in self.source_hashes.items()):
            raise RuntimeError("a frozen source file changed during the experiment")

    def checkpoint(self) -> None:
        self.state["elapsed_seconds"] = time.monotonic() - self.started
        self.state["completed_evaluation_worlds"] = len(self.records)
        self.state["completed_selection_worlds"] = len(self.training)
        write_json(self.output / "checkpoint.json", self.state)
        write_json(self.output / "worlds.json.gz", self.records)
        write_json(self.output / "selection-worlds.json.gz", self.training)

    def planning_table(self) -> None:
        model_specs = [sample_episode(seed, "train") for seed in SEEDS["bank"]]
        names = asdict(Calibration()).keys()
        self.models = [Calibration(**{k: getattr(spec.parameters, k) for k in names}) for spec in model_specs]
        self.candidates += self.models
        rows, utilities = [], []
        for index, model in enumerate(self.models):
            self.check()
            nominal = model_qualities(model, Calibration())
            scores, details = [0.0], [None]
            for candidate in self.candidates[1:]:
                self.check()
                prediction = nominal if candidate == Calibration() else model_qualities(model, candidate)
                value = prediction["mean_quality"] - nominal["mean_quality"] - int(not prediction["accepted"])
                scores.append(value)
                details.append(prediction)
            utilities.append(scores)
            rows.append({"model": asdict(model), "world": model_specs[index].to_dict(),
                         "nominal": nominal, "candidate_predictions": details, "utility": scores})
            print(f"planning model {index + 1}/{len(self.models)} elapsed {time.monotonic()-self.started:.1f}s", flush=True)
            write_json(self.output / "planning-table.json.gz", {"rows": rows, "source_sha256": self.source_hashes})
        self.utilities = np.asarray(utilities, dtype=float)
        self.state["bank_world_ids"] = [spec.to_dict()["world_id"] for spec in model_specs]
        self.checkpoint()

    def context(self, seed: int, split: str) -> dict[str, Any]:
        self.check()
        initial = PhysicalCalibrationEnv(budget=4.8, max_tests=2)
        view, _ = initial.reset(seed=seed, split=split)
        bank = FiniteBayes(view, self.models, self.utilities, self.candidates, mismatch_cutoff=self.cutoff)
        first = deepcopy(initial)
        first_view, _, _, _, _ = first.step({"experiment": FIRST})
        first_bank = deepcopy(bank)
        first_bank.update(first_view)
        return {"seed": seed, "split": split, "initial_env": initial, "initial_view": view,
                "initial_bank": bank, "first_env": first, "first_view": first_view,
                "first_bank": first_bank, "branches": {}, "outcomes": {}}

    def branch(self, ctx: dict[str, Any], second: str) -> tuple[Any, Any, Any]:
        if second not in ctx["branches"]:
            self.check()
            env, bank = deepcopy(ctx["first_env"]), deepcopy(ctx["first_bank"])
            view = deepcopy(ctx["first_view"])
            if second != "STOP" and not env.completed:
                view, _, _, _, _ = env.step({"experiment": second})
                bank.update(view)
            ctx["branches"][second] = env, bank, view
        return ctx["branches"][second]

    def save_report(self, report: dict[str, Any], split: str, seed: int) -> str:
        checked = verify_episode_report(report)
        if not checked["valid"]:
            raise RuntimeError("invalid report: " + repr(checked["failures"]))
        report_id = report["report_sha256"]
        if report_id not in self.report_files:
            relative = self.evidence.save(report)
            self.report_files[report_id] = {"path": relative, "report_sha256": report_id,
                                          "file_sha256": sha(self.output / relative), "valid": True}
        return self.report_files[report_id]["path"]

    def outcome(self, ctx: dict[str, Any], *, second: str = "STOP", method: str = "bayes",
                initial: bool = False) -> dict[str, Any]:
        key = (second, method, initial)
        if key in ctx["outcomes"]:
            return deepcopy(ctx["outcomes"][key])
        self.check()
        if initial:
            env, bank, view = deepcopy(ctx["initial_env"]), deepcopy(ctx["initial_bank"]), ctx["initial_view"]
        else:
            env0, bank0, view = self.branch(ctx, second)
            env, bank = deepcopy(env0), deepcopy(bank0)
        details: dict[str, Any] = {}
        if not env.completed:
            if method == "abstain":
                action = {"abstain": True}
            elif method == "map":
                try:
                    fitted = fit_history(view, max_nfev=20, max_forward_calls=144)
                except (ValueError, RuntimeError, ArithmeticError) as exc:
                    fitted = {"converged": False, "error_type": type(exc).__name__, "error": str(exc)}
                details["fit"] = fitted
                action, model_prediction = self.map_decision(fitted)
                details["model_prediction"] = model_prediction
            else:
                action, details = bank.terminal_action()
            env.step(action)
        report = env.host_report()
        result = {"second_action": second, "initial_only": initial, "estimator": method,
                  "score": report["score"], "disposition": report["commitment"]["disposition"],
                  "completion_reason": report["completion_reason"],
                  "actions": report["actions"], "calibration": report["commitment"]["estimates"],
                  "policy_details": details,
                  "report_path": self.save_report(report, ctx["split"], ctx["seed"])}
        ctx["outcomes"][key] = result
        return deepcopy(result)

    def map_decision(self, fitted: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        residual = fitted.get("standardized_residual_rms")
        if (not fitted.get("converged", False) or fitted.get("budget_exhausted", False)
                or fitted.get("optimizer_status") == 0
                or type(residual) not in (int, float) or not math.isfinite(residual) or residual > 4):
            return {"abstain": True}, {"reason": "fit_failure_or_mismatch"}
        try:
            estimate = Calibration.from_dict(fitted.get("estimate"))
        except (ValueError, TypeError):
            return {"abstain": True}, {"reason": "invalid_fit_estimate"}
        self.check()
        nominal = model_qualities(estimate, Calibration())
        self.check()
        candidate = model_qualities(estimate, estimate)
        utility = candidate["mean_quality"] - nominal["mean_quality"] - int(not candidate["accepted"])
        result = {"nominal": nominal, "candidate": candidate, "utility_before_test_cost": utility}
        return ({"commit": asdict(estimate)} if utility > 0 else {"abstain": True}), result

    def select(self) -> dict[str, Any]:
        contexts, residuals = [], []
        for seed in SEEDS["selection"]:
            ctx = self.context(seed, "train")
            residuals += [ctx["initial_bank"].diagnostics()["best_standardized_rms"],
                          ctx["first_bank"].diagnostics()["best_standardized_rms"]]
            for second in SECOND[1:]:
                _, bank, _ = self.branch(ctx, second)
                if not ctx["first_env"].completed:
                    residuals.append(bank.diagnostics()["best_standardized_rms"])
            contexts.append(ctx)
            print(f"training observations {seed}: {len(contexts)}/{len(SEEDS['selection'])}", flush=True)
        self.cutoff = max(4.0, float(np.quantile(residuals, 0.95)))
        for ctx in contexts:
            for bank in [ctx["initial_bank"], ctx["first_bank"], *[item[1] for item in ctx["branches"].values()]]:
                bank.mismatch_cutoff = self.cutoff
            action_scores = {second: self.outcome(ctx, second=second) for second in SECOND}
            spec = sample_episode(ctx["seed"], "train").to_dict()
            self.training.append({"split": "train", "seed": ctx["seed"], "variation": spec["variation"],
                                  "world": spec, "world_id": spec["world_id"], "first_observation": ctx["first_view"],
                                  "action_scores": action_scores})
            print(f"training scores {ctx['seed']}: {len(self.training)}/{len(contexts)}", flush=True)
            self.checkpoint()
        means = {action: float(np.mean([row["action_scores"][action]["score"]["reward"]
                                        for row in self.training])) for action in SECOND}
        fixed = max(SECOND, key=lambda name: means[name])
        fixed_two = max(SECOND[1:], key=lambda name: means[name])
        lock = {"schema_version": RUN_ID, "source_sha256": self.source_hashes,
                "seed_manifest": SEEDS, "protocol_sha256": sha(ROOT / "research/physical_gate_v1/PROTOCOL.md"),
                "mismatch_cutoff": self.cutoff, "mismatch_selection_residuals": residuals,
                "fixed_second": fixed, "fixed_two_second": fixed_two, "training_mean_rewards": means,
                "models": [asdict(model) for model in self.models],
                "candidates": [asdict(value) if value is not None else None for value in self.candidates],
                "utilities": self.utilities.tolist(), "planning_file_sha256": sha(self.output / "planning-table.json.gz"),
                "selection_evidence_sha256": sha(self.output / "selection-worlds.json.gz"),
                "counterexamples": selection_examples(self.training),
                "held_out_opened": False, "elapsed_at_lock_seconds": time.monotonic() - self.started}
        write_json(self.output / "selection-lock.json", lock)
        self.state.update(selection_locked=True, selection_lock_sha256=sha(self.output / "selection-lock.json"))
        self.checkpoint()
        print(f"SELECTION LOCKED: fixed={fixed}, fixed_two={fixed_two}, mismatch={self.cutoff:.6f}", flush=True)
        return lock

    @staticmethod
    def shuffled(contexts: list[dict[str, Any]], actions: list[str], seed: int) -> list[str]:
        assigned = list(actions)
        groups: dict[tuple[str, ...], list[int]] = {}
        for index, ctx in enumerate(contexts):
            if not ctx["first_env"].completed:
                groups.setdefault(tuple(ctx["first_view"]["legal_actions"]), []).append(index)
        rng = np.random.default_rng(seed)
        for indices in groups.values():
            permutation = rng.permutation(indices)
            for recipient, donor in zip(indices, permutation):
                assigned[recipient] = actions[int(donor)]
        return assigned

    def evaluate_split(self, split: str, lock: dict[str, Any]) -> None:
        if not self.state["selection_locked"] or sha(self.output / "selection-lock.json") != self.state["selection_lock_sha256"]:
            raise RuntimeError("selection lock missing or changed")
        contexts, adaptive, forced_two, choices = [], [], [], []
        for seed in SEEDS[split]:
            ctx = self.context(seed, split)
            if ctx["first_env"].completed:
                selected, two, info, info_two = "STOP", "STOP", {"reason": "first_probe_aborted"}, {"reason": "first_probe_aborted"}
            else:
                selected, info = ctx["first_bank"].choose_second(ctx["first_view"], force_two=False)
                two, info_two = ctx["first_bank"].choose_second(ctx["first_view"], force_two=True)
            contexts.append(ctx)
            adaptive.append(selected)
            forced_two.append(two)
            choices.append({"seed": seed, "public_first_view": ctx["first_view"],
                            "adaptive_second": selected, "adaptive_two_second": two,
                            "adaptive_prediction": info, "adaptive_two_prediction": info_two})
            print(f"{split} second-action selection {seed}: {selected}, forced-two={two}", flush=True)
        shuffled = self.shuffled(contexts, adaptive, 99173)
        shuffled_two = self.shuffled(contexts, forced_two, 99174)
        for index, item in enumerate(choices):
            item.update(shuffled_second=shuffled[index], shuffled_two_second=shuffled_two[index])
        write_json(self.output / f"decisions-{split}.json.gz", {"choices": choices,
                    "selection_lock_sha256": self.state["selection_lock_sha256"],
                    "terminal_scores_used_for_action_selection": False})
        for index, ctx in enumerate(contexts):
            self.check()
            policies = {
                "abstain": self.outcome(ctx, initial=True, method="abstain"),
                "initial_bayes": self.outcome(ctx, initial=True),
                "fixed_bayes": self.outcome(ctx, second=lock["fixed_second"]),
                "adaptive_bayes": self.outcome(ctx, second=adaptive[index]),
                "shuffled_bayes": self.outcome(ctx, second=shuffled[index]),
                "fixed_two_bayes": self.outcome(ctx, second=lock["fixed_two_second"]),
                "adaptive_two_bayes": self.outcome(ctx, second=forced_two[index]),
                "shuffled_two_bayes": self.outcome(ctx, second=shuffled_two[index]),
                "map_initial": self.outcome(ctx, initial=True, method="map"),
                "map_fixed_two": self.outcome(ctx, second="low_sweep", method="map"),
            }
            spec = sample_episode(ctx["seed"], split).to_dict()
            self.records.append({"split": split, "seed": ctx["seed"], "variation": spec["variation"],
                                 "world": spec, "world_id": spec["world_id"], "policies": policies})
            print(f"{split} scored {ctx['seed']}: adaptive={policies['adaptive_bayes']['score']['reward']:.6f}, "
                  f"MAP={policies['map_fixed_two']['score']['reward']:.6f}, "
                  f"elapsed={time.monotonic()-self.started:.1f}s", flush=True)
            self.checkpoint()
        # One predeclared diagnostic-containing policy from the first world.
        reference = next(row for row in self.records if row["split"] == split)
        report = load_report(self.output, reference["policies"]["adaptive_bayes"]["report_path"])
        self.check()
        replay = verify_rl_replay(report)
        self.integrity_checks.append({"split": split, "seed": reference["seed"],
                                      "policy": "adaptive_bayes", "replay": replay})
        if not replay["valid"]:
            raise RuntimeError("deterministic replay failed")
        print(f"{split} source-bound replay: PASS", flush=True)

    def finish(self) -> dict[str, Any]:
        self.check()
        observability = verify_observability(self.output)
        sets = {split: {tuple(row["world"]["cell"]) for row in self.records if row["split"] == split}
                for split in ("validation", "test")}
        training_cells = {tuple(sample_episode(seed, "train").cell)
                          for seed in SEEDS["bank"] + SEEDS["selection"]}
        cell_disjoint = not (training_cells & sets["validation"] or training_cells & sets["test"]
                             or sets["validation"] & sets["test"])
        if not cell_disjoint:
            raise RuntimeError("train/validation/test cells overlap")
        results = summary(self.records, complete=True, integrity_passed=True)
        results.update(schema_version=RUN_ID, source_sha256=self.source_hashes,
                       selection_lock_sha256=self.state["selection_lock_sha256"],
                       cell_disjoint=True, replay_checks=self.integrity_checks,
                       elapsed_seconds=time.monotonic()-self.started,
                       selection_counterexamples=selection_examples(self.training),
                       distinct_reports=len(self.report_files), hardware_validated=False)
        results["observability"] = observability
        write_json(self.output / "summary.json", results)
        self.state["status"] = "completed"
        self.state["decision"] = results["decision"]
        self.checkpoint()
        write_json(self.output / "evidence-manifest.json", {"source_sha256": self.source_hashes,
                    "reports": list(self.report_files.values()), "chunks": self.evidence.manifest(),
                    "files": {str(path.relative_to(self.output)): sha(path) for path in sorted(self.output.iterdir())
                              if path.is_file() and path.name != "evidence-manifest.json"}})
        print(json.dumps({"status": "completed", "decision": results["decision"],
                          "worlds": len(self.records), "distinct_reports": len(self.report_files),
                          "elapsed_seconds": results["elapsed_seconds"]}, indent=2), flush=True)
        return results


def verify_saved(output: Path) -> dict[str, Any]:
    verify_observability(output)
    manifest = read_json(output / "evidence-manifest.json")
    for name, expected in manifest["source_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("source mismatch: " + name)
    for name, expected in manifest["files"].items():
        if sha(output / name) != expected:
            raise ValueError("artifact mismatch: " + name)
    for row in manifest["reports"]:
        if sha(output / row["path"]) != row["file_sha256"]:
            raise ValueError("report envelope mismatch")
        report = load_report(output, row["path"])
        if report["report_sha256"] != row["report_sha256"] or not verify_episode_report(report)["valid"]:
            raise ValueError("report verification failed")
    records = read_json(output / "worlds.json.gz")
    training = read_json(output / "selection-worlds.json.gz")
    report_paths = {row["path"] for row in manifest["reports"]}
    for record in [*training, *records]:
        expected_world = sample_episode(record["seed"], record["split"]).to_dict()
        if digest(record["world"]) != digest(expected_world) or record["world_id"] != expected_world["world_id"]:
            raise ValueError("record world differs from the frozen sampler")
        outcomes = record.get("policies", record.get("action_scores", {}))
        for outcome in outcomes.values():
            if outcome["report_path"] not in report_paths:
                raise ValueError("outcome references an unlisted report")
            report = load_report(output, outcome["report_path"])
            if digest(report["episode"]) != digest(expected_world):
                raise ValueError("outcome references a different world")
            bindings = {"score": report["score"], "actions": report["actions"],
                        "calibration": report["commitment"]["estimates"],
                        "disposition": report["commitment"]["disposition"],
                        "completion_reason": report["completion_reason"]}
            if any(digest(outcome[key]) != digest(value) for key, value in bindings.items()):
                raise ValueError("outcome differs from its sealed episode report")
    lock = read_json(output / "selection-lock.json")
    if lock["source_sha256"] != manifest["source_sha256"] or lock["seed_manifest"] != SEEDS:
        raise ValueError("selection lock source or seed manifest differs")
    if [(row["split"], row["seed"]) for row in training] != [("train", seed) for seed in SEEDS["selection"]]:
        raise ValueError("training selection manifest differs")
    training_means = {action: float(np.mean([row["action_scores"][action]["score"]["reward"]
                                           for row in training])) for action in SECOND}
    if (digest(training_means) != digest(lock["training_mean_rewards"])
            or max(SECOND, key=training_means.get) != lock["fixed_second"]
            or max(SECOND[1:], key=training_means.get) != lock["fixed_two_second"]):
        raise ValueError("fixed schedule differs from sealed training outcomes")
    expected_cutoff = max(4.0, float(np.quantile(lock["mismatch_selection_residuals"], 0.95)))
    if expected_cutoff != lock["mismatch_cutoff"]:
        raise ValueError("mismatch selection arithmetic differs")
    regenerated = summary(records, complete=True, integrity_passed=True)
    saved = read_json(output / "summary.json")
    for key, value in regenerated.items():
        if digest(value) != digest(saved[key]):
            raise ValueError("summary differs from paired raw worlds: " + key)
    result = {"valid": True, "distinct_reports": len(manifest["reports"]), "decision": saved["decision"],
              "worlds": len(records)}
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=7200.0)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_saved(args.output)
        return
    allowed_existing = {"observability.json.gz", "observability-prefixes.json.gz"}
    if args.output.exists() and any(path.name not in allowed_existing for path in args.output.iterdir()):
        raise SystemExit("Output already contains a run; preserve it and choose a new directory.")
    verify_observability(args.output)
    pilot = Pilot(args.output, args.max_seconds)
    try:
        pilot.planning_table()
        lock = pilot.select()
        for split in ("validation", "test", "ood"):
            pilot.evaluate_split(split, lock)
        pilot.finish()
        verify_saved(args.output)
    except (Exception, KeyboardInterrupt) as exc:
        pilot.state.update(status="incomplete", decision="STOP", failure_type=type(exc).__name__, failure=str(exc))
        pilot.checkpoint()
        print(json.dumps(pilot.state, indent=2), flush=True)
        raise


if __name__ == "__main__":
    main()
