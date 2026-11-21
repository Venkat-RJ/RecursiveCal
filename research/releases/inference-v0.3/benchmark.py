"""Descriptive foreground inference timing on a shared synthetic case batch.

This is a local measurement, not a latency guarantee or an algorithmic-speed
claim. It excludes training, bank construction, I/O, and terminal calibration.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time

import numpy as np
from recursivecal_lab import experiments
from recursivecal_lab.experiments import ContextualBandit, FiniteBank, validate_artifacts


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cpu_model():
    source = Path("/proc/cpuinfo")
    if source.is_file():
        for line in source.read_text().splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    return platform.processor() or "not reported"


def summarize(elapsed_ns, count):
    durations = [value / 1e9 for value in elapsed_ns]
    per_decision_us = [value / count / 1000 for value in elapsed_ns]
    return {"repeat_duration_s": durations, "median_duration_s": statistics.median(durations),
            "per_decision_us": {"median": statistics.median(per_decision_us),
                                "min": min(per_decision_us), "max": max(per_decision_us)},
            "decisions_per_repeat": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path(__file__).resolve().parents[1] / "v0.3")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("timing.json"))
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 512 or not 3 <= args.repeats <= 50 or not 1 <= args.warmups <= 10:
        parser.error("batch-size must be 1..512, repeats 3..50, and warmups 1..10")
    verification = validate_artifacts(args.release)
    if not verification["valid"]:
        raise RuntimeError("Release integrity check failed: " + "; ".join(verification["errors"]))
    checkpoint = args.release / "checkpoints/bandit_seed_13.json"
    data_path = args.release / "evaluation_observations.csv.gz"
    with gzip.open(data_path, "rt", newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["cohort"] == "finite_test"][:args.batch_size]
    if len(rows) != args.batch_size:
        raise ValueError("release contains fewer finite-test observations than the requested batch")
    observed = np.asarray([[float(row["observed_pulse_pos_low_0"]), float(row["observed_pulse_pos_low_1"])] for row in rows])
    print(f"timing: shared finite-test observations={len(observed)}; warmups={args.warmups}; repeats={args.repeats}", flush=True)
    print("timing: construct Bayesian bank and load checkpoint outside measured intervals", flush=True)
    bank = FiniteBank(15)
    model = ContextualBandit.load(checkpoint)
    features = bank.features(observed)
    # Public decision APIs only. No private planning internals or patched model.
    cases = {
        "posterior_only_batch": lambda: bank.first_beliefs(observed),
        "posterior_and_feature_preparation_batch": lambda: bank.features(observed),
        "learned_network_only_batch": lambda: model.actions(features),
        "learned_end_to_end_batch": lambda: model.actions(bank.features(observed)),
        "bayesian_order15_end_to_end_batch": lambda: bank.bayesian_second_actions(observed)[0],
        "learned_end_to_end_scalar_loop": lambda: [model.actions(bank.features(observed[i:i+1]))[0] for i in range(len(observed))],
        "bayesian_order15_end_to_end_scalar_loop": lambda: [bank.bayesian_second_actions(observed[i:i+1])[0][0] for i in range(len(observed))],
    }
    print("timing: warm all public call paths, including quadrature caches", flush=True)
    for _ in range(args.warmups):
        for function in cases.values():
            function()
    samples = {name: [] for name in cases}
    for repeat in range(args.repeats):
        # Alternate path order to reduce simple ordering effects. The shared
        # executor still has uncontrolled scheduling and contention.
        names = list(cases)
        if repeat % 2:
            names.reverse()
        for name in names:
            start = time.perf_counter_ns()
            cases[name]()
            samples[name].append(time.perf_counter_ns() - start)
        print(f"timing: foreground repeat {repeat + 1}/{args.repeats} complete", flush=True)
    learned = model.actions(features)
    bayesian = bank.bayesian_second_actions(observed)[0]
    learned_scalar = np.array(cases["learned_end_to_end_scalar_loop"]())
    bayesian_scalar = np.array(cases["bayesian_order15_end_to_end_scalar_loop"]())
    if not np.array_equal(learned, learned_scalar) or not np.array_equal(bayesian, bayesian_scalar):
        raise RuntimeError("Scalar and batch calls changed decisions; timing comparison refused")
    config = np.__config__.show(mode="dicts")
    result = {
        "schema_version": "recursivecal.inference-timing/1",
        "scope": "Descriptive measurement on this shared CPU and these saved synthetic observations. No real-time guarantee or general algorithmic speed claim.",
        "release_manifest_sha256": digest(args.release / "manifest.json"),
        "source_sha256": {"experiments.py": digest(experiments.__file__), "benchmark.py": digest(__file__),
                          "checkpoint": digest(checkpoint), "observations": digest(data_path)},
        "inputs": {"cohort": "finite_test", "episode_ids": [row["episode_id"] for row in rows],
                   "observed_first_probe": observed.tolist(), "batch_size": len(observed),
                   "checkpoint_seed": 13, "bayesian_quadrature_order": 15,
                   "warmups": args.warmups, "repeats": args.repeats},
        "timing": {name: summarize(values, len(observed)) for name, values in samples.items()},
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                        "cpu_model": cpu_model(), "logical_cpu_count": os.cpu_count(),
                        "available_cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                        "blas_thread_environment": {name: os.environ.get(name) for name in (
                            "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")},
                        "numpy_build_configuration": config},
        "checks": {"release_integrity_valid": True, "same_observations_for_both_methods": True,
                   "scalar_batch_decisions_identical": True,
                   "learned_bayesian_action_agreement_fraction": float(np.mean(learned == bayesian))},
        "measurement_notes": [
            "Bank construction, checkpoint loading, training, data generation, disk I/O, and terminal calibration are outside timed intervals.",
            "Both end-to-end paths include their public posterior computation; the shared posterior and learner feature-construction costs are also timed separately.",
            "Posterior-only, feature-preparation, and network-only rows are components and must not be added to end-to-end rows.",
            "Bayesian public API also computes its forced-two choice from the same utility table; the optional choice is used here.",
            "Batch per-decision numbers are amortized batch time divided by batch size, not single-case response latency.",
            "Scalar-loop per-decision numbers average separate one-observation calls including Python-loop overhead; they are not tail-latency percentiles.",
            "Min, median, and max describe seven repeated runs (or configured repeats), not confidence intervals or worst-case guarantees.",
            "Shared CPU scheduling, BLAS configuration, frequency scaling, and cache state are not controlled; no thread environment is changed by this script.",
            "This compares implementations on one finite prior and batch, and does not establish method accuracy, novelty, or asymptotic complexity.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({name: values["per_decision_us"] for name, values in result["timing"].items()}, indent=2))
    print(f"timing: saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
