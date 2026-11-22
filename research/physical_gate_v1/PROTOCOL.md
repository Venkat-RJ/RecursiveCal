# Physical research gate, protocol 1

## Purpose and freeze

This CPU-only pilot addresses issue 7 against RecursiveCal 0.5.2, source commit
`bff95c2bf5b9102c7e9db5f005ca20de343c7287`. The sampler, physical equations,
sensor contract, calibration contract, acceptance criteria and terminal reward
remain unchanged. This is a synthetic research gate, not a hardware validation.

The protocol is written before test or OOD episodes are opened. Development may
use the nominal authored mechanism and train seed 0 for implementation timing.
Training records select the fixed schedule and an empirical mismatch cutoff.
A selection lock records these choices, all source hashes and the exact seed
manifest before validation, test and OOD scoring. Validation is descriptive;
it does not authorize changes to this frozen run. Any implementation correction
must be disclosed and requires a new run identifier and selection lock. A new
identifier does not restore unseen status: method changes informed by test/OOD
results require newly predeclared evaluation seeds. A mechanical repair rerun
on already inspected seeds is a disclosed diagnostic reproduction.

## Scope and resource limit

The decision experiment is a declared two-test subtask of the existing task:
budget 4.8, at most two experiments, first experiment `high_sweep`. A terminal
decision is always permitted. The second choice is STOP or any of the six
catalog experiments. No implicit repositioning is allowed. The published
default task remains budget 8 and five tests. Conclusions from this subtask
must not be generalized to every affordable longer schedule.

All simulation runs are foreground CPU processes. No API models, GPU training
or paid compute are required. The default decision-pilot elapsed cap is 7,200
seconds; the observability cap is 600 seconds. The decision cap is checked
between bounded predictor, fitting and verification calls; a call already in
progress can finish before the cap is detected. On timeout, retain a checkpoint
and label the experiment incomplete. Do not drop difficult episodes or extend
the cap after inspecting held-out scores.

## Declared worlds

Use the existing `sample_episode` function without changing distributions or
cell assignment. Keep temperature, noise, delay and quantization as sampled
or specified by the actual rig. Each policy sees only public observations.

| Use | Split | Seeds | Count |
| --- | --- | --- | ---: |
| Prior model and calibration bank | train | 1000 through 1011 | 12 |
| Fixed-schedule and mismatch selection | train | 2000 through 2007 | 8 |
| Descriptive validation | validation | 3000 through 3003 | 4 |
| Held-out primary comparison | test | 4000 through 4011 | 12 |
| Structural shifts | ood | 5000 through 5011 | 12 |

Publish world IDs, cell IDs, variations and parameters in evaluator evidence
after decisions are sealed. Confirm no train/validation/test cell overlaps.
OOD uses the original directional-friction or unequal-actuator sampler and is
reported by family as well as pooled. Do not reselect seeds to balance results.

## Parameter and decision identifiability

At calibration `(27 kg, 0.85, 0.95, 8 Nm, 0 rad)`, evaluate all six single
experiments and the persistent sequence `hold`, `high_sweep`, `low_sweep`,
`reference`, `coast` (cost 6.8, five tests). Show every affordable prefix.
The actual public fields are angle, rate and combined mean strut force, plus
the public sampling times and temperature. Deduplicate repeated acquisitions;
the final observation is not an extra independent sample.

Primary finite differences use the default instruments and controller at
10, 22.5 and 35 C, sensor seeds 101, 211 and 307, and central perturbations
of 0.05 and 0.025 times the five sampler parameter widths. An auxiliary smooth
analysis keeps timing and delays but removes noise and quantization, using
relative steps 0.01 and 0.005. Preserve the mass/inertia and friction coupling
defined by `Calibration.model()`.

Report range-scaled, noise-whitened Jacobians, singular spectra, ranks at
absolute singular thresholds 0.001, 0.01, 0.1 and 1, column correlations,
weakest parameter directions, and changed acquisition/event/termination masks.
A discontinuity is not padded into an apparently smooth derivative. Local
rank is not a proof of global identifiability or precise estimation.

Reproduce the exact left/right exchange pair `(0.55, 0.95)` versus
`(0.95, 0.55)` and the product-preserving pair
`efficiency 0.85, gains (0.6, 1.0)` versus
`efficiency 1.0, gains (0.51, 0.85)`. Compare public histories and terminal
common-controller quality at tolerance 1e-10, with matched sensor streams.
These are parameter equivalence classes. Because the terminal decision is a
common calibration, side-label ambiguity alone does not block this task.
No equivalence of arbitrary same-average motor pairs is asserted.

## Classical policies

The finite Bayesian model bank contains the 12 training worlds' five-field
calibrations, with fixed symmetric drives. Its prior is uniform. The candidate
set is those 12 calibrations, the nominal calibration and explicit abstention.
Predicted terminal utility uses the actual four verification profiles,
acceptance and rejected-commit penalty, with deterministic clean measurements
and the declared delayed/quantized controller. This is model-based prediction,
not access to any held-out evaluator. Cache this matrix once.

At an observed temperature, replay each hypothesis through the actual acquired
action sequence. Retain the hypothesis's continuous physical state. Use the
recorded public start observation for each requested motion. Condition on the
unique angle/rate/force acquisitions. A diagonal Gaussian approximation uses
standard deviations `(0.016 rad, 0.064 rad/s, 12 N)`, four times the existing
inference scale. It is deliberately broader than instrument noise to allow
some finite-bank error, but is not an exact feedback-noise likelihood. Discrete
termination mismatches receive negligible likelihood. Publish residuals.

For one-step value of information, use 64 posterior-predictive fantasies per
legal second action. Compute expected best terminal utility after the fantasy,
including the rejection penalty, and subtract `0.012 * action cost`.
An aborted fantasy receives the actual forced nominal-abstention penalty of
-1 and the full experiment cost; it cannot choose a candidate calibration.
STOP uses the current best terminal utility. All policies retain the option
of explicit abstention. The RNG seed is 7361 and depends only on the stage,
not on a hidden episode identifier. This is finite-model Monte Carlo VOI,
not a claim of an optimal Bayesian solution to the continuous task.

The same bank, posterior update and terminal decision rule are used by:

1. Initial-only Bayes, using the free reset observation.
2. Train-selected fixed Bayes, including the option of stopping after the first
   experiment. Select the second action by mean actual terminal reward on the
   eight selection worlds; ties follow the declared catalog order.
3. Adaptive Bayes, choosing the second experiment or STOP using terminal VOI.
4. Action-shuffled Bayes, with the adaptive second actions permuted across
   eligible worlds and the terminal decision recomputed on each recipient.
5. Fixed-two Bayes, selected from non-STOP schedules on training worlds.
6. Adaptive-two Bayes, choosing from non-STOP second actions.
7. Action-shuffled adaptive-two Bayes.

The mismatch cutoff is the larger of 4 and the 95th percentile of the smallest
bank standardized RMS residual on the training selection observations, pooled
over initial, first and all second-action histories. A policy abstains when
this cutoff is exceeded at the terminal decision. All probe policies still
perform their shared first experiment. Forced-two policies always perform a
second experiment when the first completed; mismatch can change their final
commitment, not secretly reduce their experiment count. Adaptive STOP remains
an explicit VOI option. Fantasy terminal decisions apply the same cumulative
residual cutoff. The cutoff is frozen before held-out evaluation.

Additional comparators are immediate abstention (exact reward zero), and
continuous regularized MAP with initial-only data or the predeclared
`high_sweep`, `low_sweep` schedule. MAP fits all five parameters within the
existing calibration bounds, with a weak Gaussian prior of strength 0.5 at
the sampler midpoint. The forward model preserves acquisition timing and
delays but removes noise and quantization for a smooth objective. Its residual
scale is `(0.004 rad, 0.016 rad/s, 3 N)`. Use at most 20 optimizer function
evaluations and 144 actual forward calls. Report convergence, rank, boundary
hits and residuals. An exception, forward-call exhaustion, nonfinite result or
SciPy optimizer status 0 (evaluation cap without convergence) is a failed fit
and abstains. This rule is not relaxed after seeing test results. A data RMS residual
above 4 also abstains. Otherwise, commit only if the fitted model predicts
positive net improvement before sunk test cost; a model-predicted rejected
candidate is an abstention. This decision uses the fitted model, never actual
world parameters. MAP is a continuous classical comparator, not an exact
posterior or an asserted optimum.

## Execution, controls and evidence

The policy accepts public views only. The host owns reset seeds, world objects,
terminal scores and raw reports. Never use held-out truth, private motor
telemetry, evaluator seeds, reports or rewards to select actions or estimates.
All evaluated actions are executed through `PhysicalCalibrationEnv`. Preserve
aborts, rejected commits, optimizer failures and abstentions as outcomes.

For each split, shuffle only within identical legal/affordable second-action
sets after the same first experiment. First-probe aborts remain in all policy
aggregates but do not enter the permutation pool. Use the fixed permutation
seed 99173 (and 99174 for forced-two), with no score-dependent retry. Include
STOP in the principal shuffle. Check exact aggregate experiment cost equality.
This is one randomization, so its randomization uncertainty remains a pilot
limitation. Fixed schedules may have different costs; report those costs
separately and use the cost-matched shuffles to test conditional choice value.

Save complete public decisions, predictions, posterior diagnostics, raw
observations and sealed episode reports. Exact duplicate action/commitment
runs may share one source-bound report by ID. This does not turn repeated
policies on the same world into independent samples. Verify every distinct
report with the ordinary verifier and replay the adaptive-Bayes record from
the first world of each validation/test/OOD split, plus each exact structural
counterexample separately. Bind every aggregate outcome back to its complete
sealed report, then recompute the training schedule selection and paired
summary. Hashes and replay check consistency, not authorship authentication.
Keep reproducible source, protocol, selection and raw-evidence hashes. Publish
two training-selection examples with different best actual second actions,
when such a pair exists, including their public first measurements, complete
evaluated action/reward tables and costs. These are selected illustrations,
not independent confirmation. If no such pair exists, record that outcome.

## Statistics and decision

The independent sampling unit is a world. Use 10,000 paired world bootstrap
replicates, seed 81971, and percentile 95% intervals. Publish raw per-world
differences and separate candidate quality, nominal quality, improvement,
test cost, rejection and forced-end penalties. Report test and both OOD
families separately. Intervals with 12 worlds are exploratory and do not
establish low failure rates.

`TRAIN` permits only a subsequent small synthetic learning study. Require all:

- Complete valid evidence and no interface or replay failure.
- Positive held-out adaptive mean reward, and lower 95% paired bounds above
  0.005 against initial-only Bayes, train-selected fixed Bayes and the matched
  action-shuffled Bayes control.
- The forced-two adaptive comparison also has lower 95% bounds above 0.005
  against fixed-two and shuffled-two controls.
- Adaptive Bayes is not worse than fixed-two continuous MAP by more than 0.005
  in mean held-out reward. Its rejected-commit and guard-abort counts do not
  exceed those of that classical comparator.
- In pooled OOD, mean adaptive reward is at least -0.05 and its rejected or
  forced-end fraction is at most 0.10; report the counts in each family.

`REVISE TASK` means this evidence does not clear the gate. State whether the
cause is estimator/model inadequacy, missing conditional experiment value,
OOD failures or statistical uncertainty. A negative finite-bank result does
not prove that every adaptive policy fails or that the mechanism is globally
unidentifiable. Do not change the sampler or score to obtain a positive answer.

`STOP` means invalid evidence, a resource-cap termination, or a provably
impossible target. A timeout is labeled pilot incomplete. Neither this pilot
nor passing software tests establishes physical accuracy on real hardware.
