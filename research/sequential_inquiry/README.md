# Sequential inquiry experiment v0

**Scope:** exploratory CPU baseline-first milestone for the original Prime Intellect research proposal. This is a new task, **not** the frozen v0.3 experiment and **not** a published scientific result.

## Question

Can an agent use an evolving history of diagnostic measurements to choose up to three tests, decide when to stop, and improve terminal calibration without seeing hidden plant parameters? Does this behavior survive when the inference model omits relevant physical behavior?

## What is implemented

`benchmark.py` provides a decision interface with `observe()`, `step(action)`, and `finish()`. Every test can be chosen, including the first. A policy sees chosen measurements, a Bayesian posterior computed from those measurements, legal actions, remaining budget, and a descriptive discrepancy score. It never sees simulated unselected measurements, latent parameters, or the evaluator's terminal quality table.

Actions are the original seven bounded diagnostic probes or STOP. No probe may be repeated; a maximum of three probes and 3.5 cost units is enforced. The terminal calibration is the best of 150 candidates under the **same fixed ten-model Bayesian belief** for all baselines. No calibration action is learned yet.

The underlying plant, noise distributions, and five evaluation cohorts reuse `recursivecal_lab.experiments` without altering its source or saved evidence. Every probe is executed from an independent fixture reset, so this is sequential *experimental choice*, not coupled continuous hardware control. Safety is a simulated action envelope, not a proof of safe use on hardware.

## First gate: strong controls before RL

The runner selects a fixed schedule using the train split and then validation, freezes that selection, and evaluates three policies on matched cases:

- `no_probe`: no measurements; prior-optimal calibration
- `selected_fixed`: zero to three fixed tests selected without looking at test cohorts
- `bayes_myopic`: one-step expected terminal calibration utility after each observed measurement, including actual test costs and STOP

`bayes_myopic` is **not** a full-horizon Bayesian planner and must not be called a globally optimal control. In particular, value-of-information complementarity across two tests may defeat a myopic stop decision. The next research gate needs a stronger non-myopic Bayesian baseline before claiming any learned advantage.

The test cohorts are fixed-prior/new-noise, parameter jitter, unseen high load, extreme deadzone, and directional friction. Both the inference bank and the current calibration decision stay fixed across the cohorts. The posterior cannot invent a new physical mechanism. The discrepancy statistic only reports a distance from predictions and is **not** a reliable model-adequacy certificate.

## How to run

From a Python 3.11+ repo checkout after installing `numpy`:

```bash
python -m unittest tests.test_sequential_inquiry -v
python -m research.sequential_inquiry.benchmark --train 128 --validation 64 --test 32 --quadrature 3 --output runs/sequential-v0
```

The program runs in the foreground, prints each stage, and saves per-policy `episodes.csv` plus `summary.json` with the file hash. Run in a new output directory. The values produced with small CI sizes are **smoke results**; we do not present them as preregistered scientific evidence. Test seeds and model coefficients are documented in `docs/EXPERIMENT_PROTOCOL.md` and the unchanged source.

## What would count as progress on the residency question

1. **Decision dependence:** a learned policy demonstrably changes its probe choice in response to changed measurements, and its actions outperform an action-frequency-matched shuffle on fresh cases.
2. **Appropriate comparison:** compare on held-out data with train-selected fixed schedules, no-probe, and a non-myopic Bayesian design/planning baseline under the same costs and observation access.
3. **Model surprise:** deliberately withhold a physics mechanism, check failure detection and safe refusal, and distinguish new-model identification from merely detecting large residuals.
4. **Genuine sequential learning:** move beyond the fixed Bayesian terminal calibrator to a trained multi-step policy, with several training seeds, saved checkpoints, independently verified action replay, and scoped test results.
5. **Transfer:** held-out combinations and structural changes must be evaluated without tuning on those test outcomes.

No generalization, novelty, hardware safety, or RL superiority claim follows merely from this interface or the first smoke run. This benchmark is an intermediate research instrument, not the destination.
## Separate stateful mechanism gate

The independent-reset benchmark was audited after the 64-case-per-cohort pilot in [INITIAL_GATE_AUDIT.md](INITIAL_GATE_AUDIT.md). Its myopic Bayesian policy never used a third probe, so it did not demonstrate a longer investigation process.

[STATEFUL_PROTOCOL.md](STATEFUL_PROTOCOL.md) describes a separate synthetic actuator in [stateful_plant.py](stateful_plant.py), where hidden thermal-friction state persists across fixture resets and makes test order matter. [The contract tests](../../tests/test_stateful_inquiry.py) verify that mechanism and non-disclosure. **No Bayesian stateful planner or RL policy has yet been trained or evaluated against this new simulator.**
