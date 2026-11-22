"""Exploratory multi-step REINFORCE pilot on synthetic stateful actuators.

RL selects diagnostic probes or STOP from public observations. The finite-model
Bayesian filter still chooses terminal calibration. No trained physical
controller, model creation, or hardware use is claimed. This baseline-first
research pilot cannot establish novel RL performance by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .bayes_stateful import BayesianBank, BayesianBelief
from .stateful_plant import CALIBRATIONS, MAX_COST, MAX_PROBES, PROBES, StatefulEpisode

ACTIONS = tuple(p.name for p in PROBES) + ("STOP",)
N_ACTIONS = len(ACTIONS)


def features(observed: dict, belief: BayesianBelief) -> np.ndarray:
    """Observed readings, action history, posterior, and deterministic metadata.

    Excludes latent plant, simulator heat, true quality, unselected readings, and
    evaluation identity. The posterior was computed from public measurements.
    """
    readings = np.zeros((len(PROBES), 2))
    used = np.zeros(len(PROBES))
    indices = {p.name: i for i, p in enumerate(PROBES)}
    for record in observed["measurements"]:
        index = indices[record["probe"]]
        used[index] = 1.
        readings[index, :len(record["observed"])] = record["observed"]
    readings /= np.array([.12, .35])
    w = belief.weights
    entropy = -float((w * np.log(np.maximum(w, 1e-300))).sum()) / np.log(len(w))
    x = np.concatenate((w * len(w), readings.flatten(), used,
                        [observed["remaining_budget"] / MAX_COST,
                         len(observed["measurements"]) / MAX_PROBES, entropy]))
    if not np.isfinite(x).all():
        raise ValueError("Nonfinite policy input")
    return x


class Actor:
    """Small NumPy MLP with a masked 8-way categorical action head."""
    def __init__(self, seed: int, input_size: int, hidden: int = 32):
        rng = np.random.default_rng(seed)
        self.weights = {"w1": rng.normal(0., .06, (input_size, hidden)),
                        "b1": np.zeros(hidden),
                        "w2": rng.normal(0., .04, (hidden, N_ACTIONS)),
                        "b2": np.zeros(N_ACTIONS)}

    def distribution(self, x: np.ndarray, legal: list[str]) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray(x, dtype=float)
        if x.ndim != 1 or x.shape[0] != self.weights["w1"].shape[0] or not np.isfinite(x).all():
            raise ValueError("Policy input must be a finite observed-feature vector")
        h = np.tanh(x @ self.weights["w1"] + self.weights["b1"])
        logits = h @ self.weights["w2"] + self.weights["b2"]
        mask = np.array([name in legal for name in ACTIONS])
        if not mask[-1]:
            raise ValueError("STOP must be allowed")
        logits = np.where(mask, logits, -1e9)
        p = np.exp(logits - logits.max())
        return h, p / p.sum()

    def choose(self, x: np.ndarray, legal: list[str], rng: np.random.Generator | None = None) -> tuple[int, np.ndarray, np.ndarray]:
        h, p = self.distribution(x, legal)
        index = int(np.argmax(p)) if rng is None else int(rng.choice(N_ACTIONS, p=p))
        return index, h, p

    def gradients(self, x: np.ndarray, h: np.ndarray, p: np.ndarray, chosen: int) -> dict:
        # Gradient of log pi(a|s). Advantage is applied by the optimizer.
        delta = -p.copy()
        delta[chosen] += 1.
        hidden_grad = (self.weights["w2"] @ delta) * (1. - h * h)
        return {"w2": np.outer(h, delta), "b2": delta,
                "w1": np.outer(x, hidden_grad), "b1": hidden_grad}

    def save(self, path: Path, metadata: dict) -> None:
        path.write_text(json.dumps({"schema": "recursivecal.stateful-actor.v0",
                                    "action_names": list(ACTIONS), "metadata": metadata,
                                    "weights": {k: v.tolist() for k,v in self.weights.items()}}, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> tuple["Actor", dict]:
        value = json.loads(path.read_text())
        if value.get("schema") != "recursivecal.stateful-actor.v0" or value.get("action_names") != list(ACTIONS):
            raise ValueError("Incompatible policy checkpoint")
        tensors = {k: np.asarray(value["weights"][k], float) for k in ("w1", "b1", "w2", "b2")}
        n, d = tensors["w1"].shape
        if (n < 1 or d < 1 or tensors["b1"].shape != (d,) or tensors["w2"].shape != (d, N_ACTIONS)
                or tensors["b2"].shape != (N_ACTIONS,) or not all(np.isfinite(v).all() for v in tensors.values())):
            raise ValueError("Invalid policy tensor shapes")
        actor = cls(0, n, d)
        actor.weights = tensors
        return actor, value["metadata"]


def episode(actor: Actor, bank: BayesianBank, seed: int, split: str,
            rng: np.random.Generator | None = None) -> tuple[dict, list[dict]]:
    env = StatefulEpisode(seed, split)
    belief = BayesianBelief(bank, seed=seed * 17 + 703)
    gradients: list[dict] = []
    selected: list[str] = []
    measurements: list[dict] = []
    while True:
        public = env.observe()
        x = features(public, belief)
        idx, hidden, probabilities = actor.choose(x, public["legal_actions"], rng)
        action = ACTIONS[idx]
        if rng is not None:
            gradients.append(actor.gradients(x, hidden, probabilities, idx))
        record = env.step(action)
        if action == "STOP":
            choice = belief.calibration()
            result = env.finish(CALIBRATIONS[choice])
            return {"seed": seed, "split": split, "actions": selected,
                    "measurements": measurements, "calibration": choice, **result}, gradients
        belief.update(idx, record)
        selected.append(action)
        measurements.append({**record, "observed": list(record["observed"])})


def evaluate(actor: Actor, bank: BayesianBank, start_seed: int, n: int, split: str) -> list[dict]:
    return [episode(actor, bank, start_seed+i, split)[0] for i in range(n)]


def train(bank: BayesianBank, seed: int, output: Path, *, episodes: int = 800,
          batch_size: int = 24, validation_n: int = 24, learning_rate: float = .003) -> tuple[Actor, dict]:
    if episodes < batch_size:
        raise ValueError("Training episode count must cover a full batch")
    rng = np.random.default_rng(seed)
    initial = StatefulEpisode(1000, "train")
    dim = len(features(initial.observe(), BayesianBelief(bank)))
    actor = Actor(seed, dim)
    moments = {k: np.zeros_like(v) for k,v in actor.weights.items()}
    variances = {k: np.zeros_like(v) for k,v in actor.weights.items()}
    step = 0
    baseline = .8
    best_validation, best_weights, best_step = -float("inf"), None, 0
    log = []
    for start in range(0, episodes, batch_size):
        selected = [(episode(actor, bank, 1000 + i, "train", rng))
                    for i in range(start, min(start+batch_size, episodes))]
        rewards = np.array([v[0]["reward"] for v in selected])
        # All actions in the episode receive the terminal advantage. Rewards
        # are observed for selected trajectories only; no oracle table is used.
        grad = {k: np.zeros_like(v) for k,v in actor.weights.items()}
        for (result, traces) in selected:
            advantage = 10. * (result["reward"] - baseline)
            for trace in traces:
                for key in grad:
                    grad[key] += advantage * trace[key] / len(selected)
        norm = float(np.sqrt(sum(np.sum(g*g) for g in grad.values())))
        if norm > 5.:
            grad = {k: g * (5. / norm) for k,g in grad.items()}
        step += 1
        for key in grad:
            moments[key] = .9*moments[key] + .1*grad[key]
            variances[key] = .999*variances[key] + .001*grad[key]**2
            m = moments[key]/(1-.9**step)
            v = variances[key]/(1-.999**step)
            actor.weights[key] += learning_rate*m/(np.sqrt(v)+1e-8)
        baseline = .9*baseline + .1*float(rewards.mean())
        if (start+len(selected)) % (batch_size*5) == 0 or start+len(selected) == episodes:
            val = evaluate(actor, bank, 3000, validation_n, "validation")
            value = float(np.mean([r["reward"] for r in val]))
            log.append({"episodes": start+len(selected), "train_batch_reward": float(rewards.mean()),
                        "validation_reward": value, "baseline": baseline})
            if value > best_validation + 1e-12:
                best_validation, best_step = value, start+len(selected)
                best_weights = {k:v.copy() for k,v in actor.weights.items()}
    if best_weights is None:
        raise RuntimeError("Checkpoint selection never occurred")
    actor.weights = best_weights
    metadata = {"train_seed": seed, "episodes": episodes, "batch_size": batch_size,
                "validation_n": validation_n, "best_validation": best_validation,
                "selected_episode": best_step, "status": "exploratory multi-step policy gradient; Bayesian terminal calibration"}
    actor.save(output, metadata)
    restored, restored_metadata = Actor.load(output)
    first = evaluate(actor, bank, 3000, validation_n, "validation")
    second = evaluate(restored, bank, 3000, validation_n, "validation")
    if [r["actions"] for r in first] != [r["actions"] for r in second]:
        raise AssertionError("Checkpoint action replay failed")
    return restored, {"metadata": restored_metadata, "history": log}


def run(output: Path | str, *, particles: int = 32, train_episodes: int = 800,
        validation_n: int = 24, test_n: int = 32, training_seeds: tuple[int,...] = (13, 37, 103)) -> dict:
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Destination must be empty")
    (out/"checkpoints").mkdir(parents=True, exist_ok=True)
    bank=BayesianBank(particles)
    summary={"schema":"recursivecal.stateful-rl-pilot.v0", "status":"exploratory; no RL superiority established",
             "particles":particles,"training_episodes_per_seed":train_episodes,
             "validation_n":validation_n,"test_n_per_cohort":test_n, "test_seed_range_start":20000,
             "seed_results":[], "source_sha256":{
                 "train_rl.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 "bayes_stateful.py": hashlib.sha256(Path(__import__("research.sequential_inquiry.bayes_stateful", fromlist=["__file__"]).__file__).read_bytes()).hexdigest(),
                 "stateful_plant.py": hashlib.sha256(Path(__import__("research.sequential_inquiry.stateful_plant", fromlist=["__file__"]).__file__).read_bytes()).hexdigest()},
             "scope":"RL selects only diagnostic probes; terminal calibration is Bayesian, synthetic model"}
    for seed in training_seeds:
        print("[stateful RL] training seed",seed,flush=True)
        path=out/"checkpoints"/f"actor_{seed}.json"
        actor, fit=train(bank,seed,path,episodes=train_episodes,validation_n=validation_n)
        cohorts={}
        for split in ("finite_test","directional_shift"):
            results=evaluate(actor,bank,20000,test_n,split)
            cohorts[split]={"mean_reward":float(np.mean([r["reward"] for r in results])),
                            "mean_quality":float(np.mean([r["quality"] for r in results])),
                            "mean_cost":float(np.mean([r["cost"] for r in results])),
                            "mean_probes":float(np.mean([r["probes"] for r in results])),
                            "guarded_total":int(sum(r["guarded_probes"] for r in results)),
                            "action_sequences":{}}
            for r in results:
                key=" / ".join(r["actions"]) or "STOP"
                cohorts[split]["action_sequences"][key]=cohorts[split]["action_sequences"].get(key,0)+1
            (out/f"episodes_{split}_{seed}.json").write_text(json.dumps(results,indent=2)+"\n")
        print("[stateful RL] seed",seed,"heldout",{k:round(v["mean_reward"],6) for k,v in cohorts.items()},flush=True)
        summary["seed_results"].append({"seed":seed,"training":fit,"test":cohorts})
    summary["artifact_sha256"] = {str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
                                  for f in sorted(out.rglob("*.json")) if f.name!="summary.json"}
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary


def main():
    p=argparse.ArgumentParser(description="Exploratory stateful RL probe policy pilot")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--particles",type=int,default=32)
    p.add_argument("--episodes",type=int,default=800)
    p.add_argument("--validation",type=int,default=24)
    p.add_argument("--test",type=int,default=32)
    p.add_argument("--seeds",type=int,nargs="+",default=[13,37,103])
    a=p.parse_args()
    run(a.output,particles=a.particles,train_episodes=a.episodes,validation_n=a.validation,
        test_n=a.test,training_seeds=tuple(a.seeds))


if __name__=="__main__":
    main()
