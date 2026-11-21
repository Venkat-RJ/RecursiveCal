"""Correct-model Bayesian baseline for the stateful synthetic actuator.

A deliberately transparent, approximate one-step expected-terminal-utility
planner. This is NOT globally optimal Bayes planning or RL. The model bank is
constructed independently of evaluation tasks; no hidden plant is accessible
through ``observe`` or the policy interface.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np

from .stateful_plant import (CALIBRATIONS, MAX_COST, MAX_PROBES, PROBES,
                             StatefulEpisode, pulse, sample_plant,
                             terminal_quality)

SIGMAS = np.array([(.006, 1.) if p.reference else (.004, .009) for p in PROBES])


class BayesianBank:
    """An explicit finite approximation to the publicly specified training prior."""

    def __init__(self, particles: int = 32, *, include_thermal: bool = True):
        if particles < 8:
            raise ValueError("At least eight particles required")
        plants = [sample_plant(i + 100_000, "train") for i in range(particles)]
        self.plants = (plants if include_thermal else
                       [replace(p, thermal_friction=0.) for p in plants])
        self.include_thermal = include_thermal
        self.quality = np.array([[terminal_quality(p, c) for c in CALIBRATIONS]
                                 for p in self.plants], dtype=float)
        self.prior = np.full(particles, 1. / particles)


class BayesianBelief:
    """Track candidate plants and their hidden thermal states through actions."""

    def __init__(self, bank: BayesianBank, seed: int = 0):
        self.bank = bank
        self.weights = bank.prior.copy()
        self.heat = np.zeros(len(bank.plants))
        self.rng = np.random.default_rng(seed)

    def forecast(self, probe_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Model predictions from public plant candidates, not evaluator truth."""
        probe = PROBES[probe_index]
        if probe.reference:
            means = np.array([[p.sensor_bias, 0.] for p in self.bank.plants])
            return means, self.heat.copy(), np.zeros(len(self.heat), dtype=bool)
        rows = [pulse(p, probe, float(h)) for p, h in zip(self.bank.plants, self.heat)]
        return (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]),
                np.array([r[2] for r in rows], dtype=bool))

    @staticmethod
    def posterior(prior: np.ndarray, means: np.ndarray, probe_index: int,
                  observed: np.ndarray, predicted_guard: np.ndarray, guarded: bool) -> np.ndarray:
        dimensions = 1 if PROBES[probe_index].reference else 2
        r = (observed[:dimensions] - means[:, :dimensions]) / SIGMAS[probe_index, :dimensions]
        logs = np.log(np.maximum(prior, 1e-300)) - 0.5 * np.sum(r * r, axis=1)
        logs -= 20. * (predicted_guard != guarded)
        logs -= logs.max()
        w = np.exp(logs)
        return w / w.sum()

    def update(self, probe_index: int, public_record: dict) -> None:
        means, heats, guards = self.forecast(probe_index)
        if public_record["probe"] != PROBES[probe_index].name:
            raise ValueError("Probe and observed record mismatch")
        self.weights = self.posterior(self.weights, means, probe_index,
                                       np.asarray(public_record["observed"]),
                                       guards, public_record["guarded"])
        self.heat = heats

    def calibration(self) -> int:
        return int(np.argmax(self.weights @ self.bank.quality))

    def choose_next(self, legal: list[str], samples: int = 32) -> str:
        """One-step value of information under the known finite bank.

        Each prospective reading is a mixture draw from the current posterior,
        and the counterfactual posterior selects a terminal calibration. This
        is a Monte Carlo approximation and does not plan through two future
        probes. Strict > guards against low-value unnecessary tests.
        """
        stop_value = float(np.max(self.weights @ self.bank.quality))
        best_value, best = stop_value, "STOP"
        indices = {p.name: j for j, p in enumerate(PROBES)}
        for name in legal:
            if name == "STOP":
                continue
            action = indices[name]
            means, _, guards = self.forecast(action)
            d = 1 if PROBES[action].reference else 2
            picks = self.rng.choice(len(self.weights), size=samples, p=self.weights)
            draws = means[picks, :d] + self.rng.normal(size=(samples, d)) * SIGMAS[action, :d]
            hypothetical = []
            for chosen, observed in zip(picks, draws):
                post = self.posterior(self.weights, means, action, observed,
                                      guards, bool(guards[chosen]))
                hypothetical.append(float(np.max(post @ self.bank.quality)))
            value = float(np.mean(hypothetical)) - .012 * PROBES[action].cost
            if value > best_value + 1e-12:
                best_value, best = value, name
        return best


def evaluate_one(bank: BayesianBank, seed: int, split: str, policy: str,
                 fixed: tuple[str, ...] = (), samples: int = 32) -> dict:
    env = StatefulEpisode(seed, split)
    belief = BayesianBelief(bank, seed=seed * 17 + 703)
    chosen: list[str] = []
    history: list[dict] = []
    while True:
        state = env.observe()
        if policy == "no_probe":
            action = "STOP"
        elif policy == "fixed":
            action = next((name for name in fixed if name not in chosen), "STOP")
        elif policy == "myopic":
            action = belief.choose_next(state["legal_actions"], samples=samples)
        else:
            raise ValueError("Unknown policy")
        record = env.step(action)
        if action == "STOP":
            result = env.finish(CALIBRATIONS[belief.calibration()])
            return {"seed": seed, "split": split, "policy": policy, "actions": chosen,
                    "measurements": history, "calibration": belief.calibration(), **result}
        belief.update(next(i for i, p in enumerate(PROBES) if p.name == action), record)
        chosen.append(action)
        history.append(record)


def schedules() -> list[tuple[str, ...]]:
    """Frozen shortlist includes zero/one/two ordered probes and 3-probe mechanisms."""
    names = [p.name for p in PROBES]
    all_schedules = [tuple()] + [(n,) for n in names]
    all_schedules += list(itertools.permutations(names, 2))
    # A limited, predeclared 3-step shortlist, not all 210 permutations.
    triples = [
        ("pulse_pos_high", "pulse_neg_low", "reference_check"),
        ("pulse_neg_high", "pulse_pos_low", "reference_check"),
        ("pulse_pos_high", "pulse_neg_high", "reference_check"),
        ("pulse_neg_high", "pulse_pos_high", "reference_check"),
        ("pulse_pos_low", "pulse_neg_low", "reference_check"),
        ("pulse_neg_low", "pulse_pos_low", "reference_check"),
        ("pulse_pos_high", "pulse_pos_offset", "reference_check"),
        ("pulse_neg_high", "pulse_neg_offset", "reference_check"),
    ]
    all_schedules += triples
    return [s for s in all_schedules if len(s) <= MAX_PROBES
            and sum(next(p.cost for p in PROBES if p.name == a) for a in s) <= MAX_COST]


def run(output: Path | str, *, particles: int = 32, train_n: int = 32,
        validation_n: int = 16, test_n: int = 32, samples: int = 32) -> dict:
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Destination not empty")
    out.mkdir(parents=True, exist_ok=True)
    print("[stateful] building training-prior bank and terminal quality table", flush=True)
    bank = BayesianBank(particles)
    incomplete = BayesianBank(particles, include_thermal=False)
    schedules_list = schedules()
    print(f"[stateful] selecting fixed policy from {len(schedules_list)} candidate sequences", flush=True)
    train_seeds = range(1000, 1000 + train_n)
    val_seeds = range(3000, 3000 + validation_n)
    ranking = []
    for schedule in schedules_list:
        outcomes = [evaluate_one(bank, seed, "train", "fixed", schedule) for seed in train_seeds]
        ranking.append((float(np.mean([o["reward"] for o in outcomes])), schedule))
    shortlist = sorted(ranking, key=lambda x: (-x[0], len(x[1]), x[1]))[:5]
    validation = [(float(np.mean([evaluate_one(bank, seed, "validation", "fixed", seq)["reward"]
                                  for seed in val_seeds])), seq) for _, seq in shortlist]
    selected = sorted(validation, key=lambda x: (-x[0], len(x[1]), x[1]))[0][1]
    print("[stateful] selected fixed sequence:", selected, flush=True)
    summary = {"schema": "recursivecal.stateful-inquiry.v0", "status": "exploratory Bayesian baseline, no RL",
               "n_particles": particles, "mc_samples": samples, "train_cases": train_n,
               "validation_cases": validation_n, "test_cases_per_cohort": test_n, "test_seed_range_start": 20000,
               "fixed_schedule": list(selected), "fixed_shortlist": [list(s) for _, s in shortlist],
               "model_bank": {"candidate_count": particles,
                              "thermal_candidates": sum(p.thermal_friction > 0 for p in bank.plants),
                              "misspecified_ablation": "same candidate seeds, all thermal_friction=0"},
               "source_sha256": {
                   "bayes_stateful.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "stateful_plant.py": hashlib.sha256(Path(__import__("research.sequential_inquiry.stateful_plant", fromlist=["__file__"]).__file__).read_bytes()).hexdigest(),
               },
               "results": {}, "scope": "synthetic thermal history; no hardware, no learned agent"}
    all_records = []
    for split in ("finite_test", "directional_shift"):
        print("[stateful] evaluating", split, flush=True)
        scores = {}
        for name in ("no_probe", "fixed", "myopic", "myopic_misspecified"):
            active_bank = incomplete if name == "myopic_misspecified" else bank
            evaluation_policy = "myopic" if name == "myopic_misspecified" else name
            rows = [evaluate_one(active_bank, seed, split, evaluation_policy, selected, samples)
                    for seed in range(20000, 20000 + test_n)]
            for row in rows:
                row["policy"] = name
            scores[name] = {
                "mean_reward": float(np.mean([r["reward"] for r in rows])),
                "mean_quality": float(np.mean([r["quality"] for r in rows])),
                "mean_cost": float(np.mean([r["cost"] for r in rows])),
                "mean_probes": float(np.mean([r["probes"] for r in rows])),
                "guarded_total": int(sum(r["guarded_probes"] for r in rows)),
                "action_sequences": {},
            }
            for r in rows:
                seq = " / ".join(r["actions"]) if r["actions"] else "STOP"
                scores[name]["action_sequences"][seq] = scores[name]["action_sequences"].get(seq, 0) + 1
            all_records.extend(rows)
        summary["results"][split] = scores
    (out / "episodes.json").write_text(json.dumps(all_records, indent=2) + "\n")
    summary["episodes_sha256"] = hashlib.sha256((out / "episodes.json").read_bytes()).hexdigest()
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Stateful synthetic Bayesian baseline, not RL")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--particles", type=int, default=32)
    parser.add_argument("--train", type=int, default=32)
    parser.add_argument("--validation", type=int, default=16)
    parser.add_argument("--test", type=int, default=32)
    parser.add_argument("--samples", type=int, default=32)
    args = parser.parse_args()
    results = run(args.output, particles=args.particles, train_n=args.train,
                  validation_n=args.validation, test_n=args.test, samples=args.samples)
    for k, v in results["results"].items():
        print(k, {p: round(x["mean_reward"], 6) for p, x in v.items()}, flush=True)


if __name__ == "__main__":
    main()
