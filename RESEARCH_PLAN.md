# RecursiveCal research plan

**Question:** Can reinforcement learning improve sequential diagnostic experiment selection and calibration under uncertain dynamics, beyond strong classical system-identification and experimental-design methods?

This is a falsifiable research question, **not** a claim that RL already works.

## Current evidence

- The first `RecursiveCal` environment is a synthetic single-axis actuator with seven shielded diagnostic probes, 150 legal final calibrations, a cost budget, and an independent terminal evaluator.
- Classical Bayesian particle-based identification with a train-selected two-probe limit performs strongly on current single-fault, combined-fault, and one torque-deadzone shifted-dynamics split. See [RESULTS.md](RESULTS.md).
- A 720-episode CPU policy-gradient pilot learned to use exactly one fixed probe. A hand-coded fixed-probe control reproduced its held-out scores; there is **no evidence of learned adaptive experiment selection**. See [RL_PILOT.md](RL_PILOT.md).
- The Verifiers v1 interface passed taskset and scripted-interaction checks. A two-episode small-language-model smoke test completed but produced invalid action sequences and zero rewards. No language model has been fine-tuned with RL. See [LLM_SMOKE.md](LLM_SMOKE.md).

## Proposed next experiment

The current tasks do not reliably require a policy to react to earlier measurements. Before any larger training run, introduce a task family where **the optimal next test differs depending on the outcome of a prior test**.

### 1. Verify that the new task is identifiable

Construct different hidden plant families that initially look similar but yield different responses to particular diagnostic probes. Show, by exhaustive or high-precision analysis, that:

- all important fault classes can be distinguished within the available probe budget,
- the *best next action* depends on observed measurements, not a fixed probe schedule,
- the calibration objective and diagnostic cost do not reward always stopping immediately,
- task generation and reward design were fixed before evaluating learned policies.

A task that makes RL look good by construction is not useful.

### 2. Strengthen the classical controls

Compare against non-privileged alternatives using the same observations, legal actions, and cost:

- no-test calibration, random probes, and fixed schedules,
- regularized least-squares / maximum-a-posteriori system identification,
- particle-based Bayesian identification with budget-aware stopping,
- expected value-of-information and decision-focused probe selection.

Select hyperparameters using **training tasks only**. A privileged oracle may provide an upper-bound reference, but not a fair policy comparator.

### 3. Evaluate learned experiment selection

Only after the task passes the identifiability and adaptive-action tests:

- train small diagnostic policies, including a model-free baseline;
- establish zero-shot tool-using language-model performance with valid structured actions;
- evaluate RL-trained 1B–3B language models if feasible and justified by measured throughput;
- run repeated training seeds, not just a single policy seed;
- compare with fixed-probe controls and the strongest classical approach.

The purpose is to isolate **experiment-selection learning** from improvements due to a better estimator, a different number of tests, or a cheaper fixed schedule.

### 4. Measure transfer and failure

**Primary endpoint:** paired net calibration reward at identical maximum diagnostic budgets on held-out dynamical-system classes.

Also report:

- raw calibration quality without probe-cost penalties,
- number and cost of diagnostic actions,
- unsafe/invalid requests and host-side interventions,
- decisions at matched sample budgets,
- calibration performance under shifted dynamics,
- confidence intervals, repeated training-seed variation, and failure examples.

Test on separately constructed held-out dynamics, not merely unseen seeds from the same generator. Keep scoring host-side and shield diagnostic actions independently of the agent.

## Stop criteria

A positive result requires a measured, reproducible benefit over strong classical and fixed-probe controls that survives held-out dynamics and a reward audit. If classical methods tie or win, if the learned policy collapses to a static action, or if the task has an identifiability flaw, report the negative result and revise the scientific question rather than spending larger training budgets.

## Boundaries

All mechanics and telemetry are simulated. This environment is not a model of any particular production actuator. It contains no proprietary parameters, and its host-side action restrictions are **not** a real-hardware safety validation.

Source: [README](README.md) · [classical results](RESULTS.md) · [neural pilot](RL_PILOT.md).
