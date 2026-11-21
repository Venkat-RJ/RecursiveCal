# RecursiveCal

**Can an AI agent learn which experiment to run next before recalibrating an unfamiliar physical system?**

RecursiveCal is an experimental RL research project for safe, budgeted diagnosis and calibration of physical systems. The first task is **SafeCal**, a synthetic electromechanical actuator with hidden faults, noisy measurements, and a limited number of diagnostic probes.

The question is not just whether the agent finds a good calibration. It is whether it can update its understanding after each measurement, choose a useful next experiment, and know when to stop.

## Why this problem?

At Continental, I used Bayesian optimization to reduce an automotive power-liftgate calibration process from about three weeks to 1.5 hours. That work made me curious about a harder question: what happens when the system itself changes, and the agent has to discover *what* to test before deciding *how* to calibrate?

The simulator and all its parameters are synthetic. This repository contains no proprietary engineering data or real hardware-control software.

## The first environment: SafeCal

An episode starts with an unfamiliar single-axis actuator. Its motor efficiency, friction, load, and sensor bias may have changed. The agent:

1. Observes noisy sensor readings.
2. Chooses from bounded, host-validated diagnostic maneuvers.
3. Updates its estimate of the actuator.
4. Stops testing and submits calibration parameters.
5. Receives a score from an independent evaluator on unseen motion trajectories.

The reward accounts for calibration quality and diagnostic cost. Physical safety constraints are enforced by the simulator. That does **not** establish safety on real hardware.

There are three test splits: individual faults, combined faults, and a shifted-dynamics condition with an unmodeled torque deadzone.

## What we have learned so far

The first pilot taught us why strong classical baselines matter.

| Policy (mean net reward, 60 tasks per split) | Single faults | Combined faults | Shifted dynamics |
|---|---:|---:|---:|
| Factory default | 0.84053 | 0.79321 | 0.64360 |
| Bayesian identification, up to 2 probes | **0.86167** | **0.87811** | **0.78425** |

A CPU-only neural diagnostic-selection policy was also trained for 720 simulated episodes. It learned to use the **same single probe every time**. A hand-coded fixed-probe policy matched it exactly, so this is **not** evidence of learned adaptive experimentation.

A separate small-model smoke test with Qwen2.5-0.5B completed through the real Verifiers v1 environment, but produced invalid actions and zero reward. No language model has been RL fine-tuned for RecursiveCal.

Read [RESULTS.md](RESULTS.md), [RL_PILOT.md](RL_PILOT.md), [LLM_SMOKE.md](LLM_SMOKE.md), and [RESEARCH_PLAN.md](RESEARCH_PLAN.md) for the protocols, limitations, and next experiment.

**Next research question:** Can we create identifiable systems where the best second test genuinely depends on the outcome of the first, and can RL improve adaptive experiment selection over cost-aware Bayesian methods?

## Run locally

Python 3.11+:

```bash
python -m pip install -e '.[rl]'
python -m unittest discover -s tests -v
python demo.py
python benchmark.py --tasks 60 --split combined --policies default bayes2
python train_probe_rl.py --help
```

The code still uses the `safecal` and `safecal_v1` Python modules for the first task. Keeping those names avoids breaking the tested simulator and its Verifiers adapter.

### Prime Intellect Verifiers v1

```bash
python -m pip install -e '.[bayes,verifiers]'
# Requires a configured model endpoint and an isolated runtime
vf-eval safecal-v1 -n 10 --model your-provider/your-model \
  --env.taskset.split train --env.agent.runtime.type docker --no-push
```

The v1 taskset and scripted host interaction passed against an installed Verifiers runtime. Full `vf-eval` rollout, large-model RL training, and real-hardware validation remain future work.

## Background and provenance

This standalone repository was prepared from the earlier [SafeCal research folder](https://github.com/Venkat-RJ/openresearch/tree/main/safecal). The simulation, tests, reported results, and original research limitations are preserved. The broader research direction is now called **RecursiveCal**.

MIT licensed. Research prototype only.
