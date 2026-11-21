# RecursiveCal

**An experimental RL environment for diagnosis and calibration under unknown dynamics.**

RecursiveCal studies a specific decision problem: **which experiment should an agent run next, and when does it know enough to stop?**

The current task is a synthetic single-axis actuator. Its dynamics are hidden. An agent can perform bounded diagnostic tests, observe noisy results, and select a final calibration. The environment scores the calibration on unseen trajectories.

This is a **research simulator**, not an industrial calibration product, real-hardware controller, or certified safety system.

## Parametric mechanical CAD test cell

**[Explore RecursiveCal's editable mechanical CAD module](mechanics/cad_v1/README.md)**

This newer test cell is built from an original 69-component parametric assembly, with native STEP/GLB exports, articulated hinge/strut geometry, CAD-linked force calculations, a load-cell fitting workflow, and an interactive CAD-mesh viewer. Its hardware dimensions and forces are illustrative, not measured or OEM-validated. The original RL benchmark remains unchanged.

## 3D physical systems test cell

**[Open the new physical tailgate demo](visualization/physical_twin/demo.html)** · [Source and model notes](visualization/physical_twin/README.md)

This is a separate experimental 3D hinge model. An articulated hatch rotates around its hinge while two telescoping struts move between their mounting points. The opening angle, strut extension, controller response, gravity, and modeled force are linked by the same numerical simulation. Try fault injection, orbit inspection, mechanism cutaway, full-screen physical view, and synchronized factory/modified comparison.

**Research boundary:** this model uses illustrative mechanism geometry and physical parameters, not manufacturer CAD, real plant measurements, or certified vehicle controls. Its reference calibration uses known simulator parameters and is not an RL policy.

The [earlier 2D actuator demonstration](visualization/index.html) remains available. It is tied to the original normalized linear-actuator benchmark and should not be confused with the new hinge model.

## Environment

```text
  Hidden actuator dynamics
           |
     Initial observation
           |
   Choose diagnostic probe <----+
           |                    |
     Noisy measurement          |
           |                    |
  Update estimate / belief      |
           |                    |
   Test again or stop? ---------+
           |
     Submit calibration
           |
  Independent held-out scoring
```

- **Hidden variables:** motor efficiency, friction, load, damping, and sensor bias. One evaluation split also introduces a torque deadzone absent from the baseline model.
- **Actions:** six torque-pulse tests, one reference check, or submission of a calibration from a fixed grid of 150 legal choices.
- **Constraints:** diagnostic actions have costs and are restricted by a host-side action envelope. Repeated, invalid, or over-budget probes are rejected.
- **Observations:** noisy displacement/velocity measurements or a sensor-reference measurement. The agent does not receive hidden plant parameters.
- **Objective:** maximize calibration quality on four unseen trajectories minus diagnostic cost.

The simulator's terminal reward is

```text
net_reward = held_out_calibration_quality - 0.012 * diagnostic_cost
```

Safety interventions affect calibration quality; the environment also enforces limits on allowable diagnostic actions. These are **simulation-level protections**, not evidence of real-world safety.

## Independent physics and adaptive-experiment audit (November 2026)

A new [numerical audit and adaptive diagnostic research module](research/adaptive_diagnostics/README.md) tests whether the simulated environment actually requires observation-dependent experiments. It includes the source, classical controls, a three-seed CPU contextual-bandit RL pilot, parameter-shift stress tests, and reproducible result JSONs.

**What improved:** On a deliberately constructed ten-hypothesis synthetic task, three small learned policies chose different follow-up tests and scored 0.8891–0.8896, compared with 0.8779 for the best train-selected fixed schedule and 0.8900 for adaptive Bayesian design (2,048 held-out cases). This is *not* an RL victory over strong classical inference, nor physical-world validation. The original v0.2 neural pilot below remains a separate negative result.

**What needs fixing:** A requested 0.55 s diagnostic pulse actually lasts 0.56 s at the v0.2 integration step. The study preserves those frozen equations to reproduce old scores and documents an exact-duration correction for a future version. In an unseen high-load stress test, doing no diagnostic test was better than both adaptive methods. No actual vehicle measurements were used.

## Results so far

The strongest classical baseline uses particle-based Bayesian system identification and cost-aware probe selection. The maximum probe count was selected using training seeds, then evaluated on separate fixed seeds.

**Mean net reward, 60 synthetic tasks per split. Higher is better.**

| Policy | Single fault | Combined faults | Shifted dynamics |
|---|---:|---:|---:|
| Factory calibration, no probes | 0.84053 | 0.79321 | 0.64360 |
| Bayesian identification, up to 2 probes | **0.86167** | **0.87811** | **0.78425** |
| Neural diagnostic policy, 720 training episodes | 0.84763 | 0.89186 | 0.78962 |

The neural policy's apparently good performance on combined faults is **not evidence of adaptive diagnosis**. It chose the same `pulse_neg_low` probe on all 180 held-out tasks. A hand-coded policy making that same fixed choice reproduced its rewards exactly. It did not outperform the appropriate fixed-action control.

A separate Qwen2.5-0.5B-Instruct smoke test ran two model-generated episodes through the installed Verifiers v1 environment. Neither completed a valid calibration; both received zero reward. This was an integration smoke test, not a representative language-model evaluation or language-model RL experiment.

Details: [classical baselines](RESULTS.md) · [RL pilot and negative control](RL_PILOT.md) · [language-model smoke test](LLM_SMOKE.md).

## Research question

The current simulator still allows a simple fixed diagnostic strategy to perform well. It is **not yet evidence that RL learns better experiment selection**.

The next test is to construct *identifiable but ambiguous* systems in which the best second experiment depends on the first measurement. Then compare learned policies against:

- fixed and random diagnostics,
- classical system-identification methods,
- Bayesian expected value-of-information and stopping policies,
- matched-budget tool-using language-model agents.

Evaluation must include unseen dynamics, calibration quality, diagnostic cost, blocked/invalid actions, and fixed-probe controls. A result only matters if it survives strong non-privileged baselines on held-out systems. See [research plan](RESEARCH_PLAN.md).

## Reproduce

Python 3.11+:

```bash
python -m pip install -e '.[bayes,rl]'
python -m unittest discover -s tests -v
python demo.py
python benchmark.py --tasks 60 --split heldout --policies default bayes2 --json results_heldout.json
python benchmark.py --tasks 60 --split combined --policies default bayes2 --json results_combined.json
python benchmark.py --tasks 60 --split shifted --policies default bayes2 --json results_shifted.json
```

The summary in [PUBLIC_RESULTS.json](PUBLIC_RESULTS.json) records the classical pilot; the scripts regenerate per-seed results. RL training commands and reproducibility limits are in [RL_PILOT.md](RL_PILOT.md). The trained checkpoint and full run artifacts are not currently tracked in this repository.

### Verifiers v1 integration

`recursivecal_v1/` implements a multi-turn taskset and host-side environment for [Prime Intellect Verifiers](https://github.com/PrimeIntellect-ai/verifiers).

```bash
python -m pip install -e '.[bayes,verifiers]'
```

Taskset initialization, scripted interaction, and package imports passed against the installed Verifiers v1 runtime. A custom small-model inference smoke also ran. A native `vf-eval` model-provider run and language-model RL training have **not** been validated.

## Repository layout

| Path | Purpose |
|---|---|
| `recursivecal.py` | Synthetic plant, diagnostic action shield, and independent terminal score |
| `bayes_id.py` | Particle-based Bayesian identification and classical probe selection |
| `recursivecal_v1/` | Verifiers v1 taskset, protocol, and environment |
| `benchmark.py`, `budget_sweep.py` | Seeded evaluations and probe-budget comparisons |
| `train_probe_rl.py`, `audit_rl.py` | CPU RL pilot and fixed-probe audit |
| `tests/` | Unit and protocol tests |

The Python module is `recursivecal` and the Verifiers taskset is `recursivecal_v1`.

## Scope

All dynamics, faults, and measurements are synthetic and normalized. There is no proprietary industrial data, hardware validation, sim-to-real claim, or evidence of safe deployment. Strong classical methods may remain the best approach, and negative findings are part of the result.

MIT licensed. Earlier experiment provenance is retained in the project's Git history.
