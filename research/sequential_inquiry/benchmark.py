"""Exploratory sequential diagnostic decisions over the frozen normalized plant.

This is an environment and classical-baseline gate for the original RL proposal.
There is NO trained RL policy and NO model-structure discovery in this module.
A learned policy can later consume ``observe()`` and choose a legal action.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
from typing import Callable

import numpy as np

import recursivecal as legacy
import recursivecal_lab.experiments as frozen_experiments
from recursivecal_lab.experiments import COST_COEFFICIENT, EvaluationData, FiniteBank

STOP = -1
MAX_PROBES = 3
MAX_COST = 3.5
COHORTS = ("finite_test", "continuous_jitter", "unseen_high_load",
           "extreme_deadzone", "directional_friction")


class SequentialEpisode:
    """Three-test decision interface. Hidden data belongs only to the evaluator.

    A policy receives ``observe()``, not this episode object or its complete
    simulated observation table. Probes start from the frozen simulator's
    independent fixture reset; these are sequential decisions, not coupled
    physical trajectories. This distinction is material.
    """

    def __init__(self, bank: FiniteBank, data: EvaluationData, index: int):
        if index < 0 or index >= len(data.episode_ids):
            raise IndexError("Unknown episode")
        self._bank = bank
        self._truth = data.quality[index].copy()
        self._unobserved = data.observations[index].copy()
        self.episode_id = data.episode_ids[index]
        self._belief = bank.prior.copy()
        self._history: list[tuple[int, np.ndarray]] = []
        self._cost = 0.0
        self._ended = False

    def legal_actions(self) -> list[int]:
        if self._ended:
            return []
        actions = [STOP]
        if len(self._history) < MAX_PROBES:
            used = {a for a, _ in self._history}
            actions.extend(i for i, probe in enumerate(legacy.PROBES)
                           if i not in used and self._cost + probe.cost <= MAX_COST + 1e-12)
        return actions

    def observe(self) -> dict:
        """Public observation, with no latent plant, reward, or unchosen probe."""
        if self._ended:
            raise ValueError("Episode has ended")
        residual = np.zeros(len(self._bank.prior))
        dimensions = 0
        for action, measured in self._history:
            d = len(measured)
            r = ((measured[None, :] - self._bank.means[:, action, :d])
                 / self._bank.sigma[action, :d])
            residual += np.square(r).sum(axis=1)
            dimensions += d
        discrepancy = float(np.sqrt(residual.min() / dimensions)) if dimensions else 0.0
        return {
            "belief": self._belief.tolist(),
            "measurements": [{"action": a, "name": legacy.PROBES[a].name,
                              "observed": values.tolist()} for a, values in self._history],
            "legal_actions": self.legal_actions(),
            "cost_spent": self._cost,
            "remaining_cost": MAX_COST - self._cost,
            "discrepancy": discrepancy,
        }

    def step(self, action: int) -> dict | None:
        if not isinstance(action, (int, np.integer)) or action not in self.legal_actions():
            raise ValueError("Illegal, repeated, over-budget, or post-terminal action")
        if action == STOP:
            self._ended = True
            return None
        d = int(self._bank.dimensions[action])
        reading = self._unobserved[action, :d].copy()
        self._belief = self._bank.posterior(self._belief[None, :], reading[None, :], action)[0]
        self._history.append((action, reading))
        self._cost += legacy.PROBES[action].cost
        return {"action": int(action), "name": legacy.PROBES[action].name,
                "observed": reading.tolist(), "cost": legacy.PROBES[action].cost}

    def finish(self) -> dict:
        if not self._ended:
            raise ValueError("Choose STOP before evaluation")
        calibration = int(np.argmax(self._belief @ self._bank.quality))
        quality = float(self._truth[calibration])
        return {"episode_id": self.episode_id, "reward": quality - COST_COEFFICIENT * self._cost,
                "quality": quality, "cost": self._cost, "probes": len(self._history),
                "calibration": calibration,
                "actions": [int(a) for a, _ in self._history],
                "measurements": [{"action": int(a), "observed": v.tolist()}
                                 for a, v in self._history]}


def choose_myopic(bank: FiniteBank, state: dict) -> int:
    """One-step Bayesian expected terminal utility, with STOP and actual costs.

    This is deliberately MYOPIC, not a full-horizon Bayesian optimum. It does
    not peek at evaluator observations. The same public finite model is used
    for posterior updates and prospective observations.
    """
    legal = state["legal_actions"]
    if legal == [STOP]:
        return STOP
    belief = np.asarray(state["belief"], dtype=float)
    quality = bank._efficient_quality  # model bank, not hidden ground truth
    stop_value = float(np.max(belief @ quality))
    best_value, best_action = stop_value, STOP
    for action in legal:
        if action == STOP:
            continue
        likelihood, weights = bank._grid(action)
        n_models, n_nodes = len(belief), len(weights)
        posterior_unnormalized = likelihood * belief[None, :]
        denominators = posterior_unnormalized.sum(axis=1, keepdims=True)
        posterior = posterior_unnormalized / np.maximum(denominators, 1e-300)
        terminal = np.max(posterior @ quality, axis=1).reshape(n_models, n_nodes)
        future_value = float(np.sum(terminal * belief[:, None] * weights[None, :]))
        net = future_value - COST_COEFFICIENT * legacy.PROBES[action].cost
        if net > best_value + 1e-12:
            best_value, best_action = net, action
    return best_action


def _fixed_rewards(bank: FiniteBank, data: EvaluationData, schedule: tuple[int, ...]) -> np.ndarray:
    n = len(data.episode_ids)
    belief = np.broadcast_to(bank.prior, (n, len(bank.prior))).copy()
    for action in schedule:
        belief = bank.posterior(belief, data.observations[:, action], action)
    calibration = np.argmax(belief @ bank.quality, axis=1)
    costs = sum(legacy.PROBES[a].cost for a in schedule)
    return data.quality[np.arange(n), calibration] - COST_COEFFICIENT * costs


def select_fixed(bank: FiniteBank, train: EvaluationData, validation: EvaluationData) -> dict:
    """Select without touching any held-out evaluation cohort."""
    candidates = [tuple()] + [x for n in (1, 2, 3)
                              for x in itertools.combinations(range(len(legacy.PROBES)), n)
                              if sum(legacy.PROBES[a].cost for a in x) <= MAX_COST]
    train_scores = [(float(_fixed_rewards(bank, train, seq).mean()), seq) for seq in candidates]
    shortlist = sorted(train_scores, key=lambda row: (-row[0], len(row[1]), row[1]))[:5]
    selected = sorted([(float(_fixed_rewards(bank, validation, seq).mean()), seq)
                       for _, seq in shortlist], key=lambda row: (-row[0], len(row[1]), row[1]))[0]
    return {"schedule": list(selected[1]), "validation_mean": selected[0],
            "shortlist": [{"schedule": list(seq), "train_mean": score}
                          for score, seq in shortlist],
            "selection": "top five schedules on train; best on validation; no test cohort used"}


def rollout(bank: FiniteBank, data: EvaluationData,
            policy: Callable[[dict], int]) -> list[dict]:
    records = []
    for i in range(len(data.episode_ids)):
        episode = SequentialEpisode(bank, data, i)
        while True:
            state = episode.observe()
            action = policy(state)
            episode.step(action)
            if action == STOP:
                records.append(episode.finish())
                break
    return records


def run_study(output: Path | str, *, train_size: int = 128, validation_size: int = 64,
              test_size: int = 32, quadrature_order: int = 3) -> dict:
    """Run the first baseline gate in the foreground, not the proposed RL study."""
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Destination is not empty")
    out.mkdir(parents=True, exist_ok=True)
    bank = FiniteBank(quadrature_order=quadrature_order)
    print("[sequential] selecting fixed schedule from train and validation", flush=True)
    selection = select_fixed(bank, bank.make_data(train_size, "train"),
                             bank.make_data(validation_size, "validation"))
    schedule = selection["schedule"]

    def fixed(state: dict) -> int:
        for action in schedule:
            if action not in [entry["action"] for entry in state["measurements"]]:
                return action
        return STOP

    policies = {
        "no_probe": lambda state: STOP,
        "selected_fixed": fixed,
        "bayes_myopic": lambda state: choose_myopic(bank, state),
    }
    all_records = []
    summary = {"schema": "recursivecal.sequential-inquiry.v0", "status": "exploratory baseline gate; no RL trained",
               "model": "recursivecal-normalized-v0.2", "quadrature_order": quadrature_order,
               "max_distinct_probes": MAX_PROBES, "max_cost": MAX_COST,
               "train_size": train_size, "validation_size": validation_size, "test_size_per_cohort": test_size,
               "selection": selection, "results": {},
               "scope": "independent fixture reset for each probe; no physical hardware or model revision",
               "source_sha256": {
                   "research/sequential_inquiry/benchmark.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "recursivecal_lab/experiments.py": hashlib.sha256(Path(frozen_experiments.__file__).read_bytes()).hexdigest(),
                   "recursivecal.py": hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest(),
               }, "numpy_version": np.__version__}
    for cohort in COHORTS:
        print(f"[sequential] evaluating {cohort}", flush=True)
        data = bank.make_data(test_size, cohort)
        summary["results"][cohort] = {}
        for name, policy in policies.items():
            rows = rollout(bank, data, policy)
            for row in rows:
                all_records.append({"cohort": cohort, "policy": name, **row})
            summary["results"][cohort][name] = {
                "mean_reward": float(np.mean([r["reward"] for r in rows])),
                "mean_quality": float(np.mean([r["quality"] for r in rows])),
                "mean_cost": float(np.mean([r["cost"] for r in rows])),
                "mean_probes": float(np.mean([r["probes"] for r in rows])),
            }
    path = out / "episodes.csv"
    fields = ("cohort", "policy", "episode_id", "reward", "quality", "cost", "probes", "calibration", "actions", "measurements")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in all_records:
            writer.writerow({**row, "actions": json.dumps(row["actions"]),
                             "measurements": json.dumps(row["measurements"])})
    summary["episodes_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Exploratory sequential-inquiry baseline, not RL evidence")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train", type=int, default=128)
    parser.add_argument("--validation", type=int, default=64)
    parser.add_argument("--test", type=int, default=32)
    parser.add_argument("--quadrature", type=int, choices=(3, 5, 9), default=3)
    args = parser.parse_args()
    summary = run_study(args.output, train_size=args.train, validation_size=args.validation,
                        test_size=args.test, quadrature_order=args.quadrature)
    for cohort, results in summary["results"].items():
        print(cohort, {k: round(v["mean_reward"], 6) for k, v in results.items()}, flush=True)
    print("[sequential] saved", args.output, flush=True)


if __name__ == "__main__":
    main()
