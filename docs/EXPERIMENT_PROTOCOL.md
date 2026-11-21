# RecursiveCal experiment protocol v0.3

This protocol specifies the implemented CPU study in `recursivecal_lab/experiments.py`.
It evaluates diagnostic decisions in the frozen normalized v0.2 simulator. The SI
liftgate model, measured force fitting, and this experiment have separate model
identifiers and evidence. A policy trained here is not installed as a liftgate
controller.

## Research question and status

Can a policy use the first diagnostic observation to choose a useful second test,
after accounting for test cost? How does it compare with Bayesian experimental
design, fixed schedules, and doing no diagnostic tests? How does it fail when its
inference model omits relevant behavior?

This is an **exploratory, public synthetic benchmark**. Earlier pilot results and
development smoke results were seen while building this software. Neither this
protocol nor a subsequently larger run is an independent preregistration or a
blinded confirmatory study. The runner freezes selections and model checkpoints
before generating its test cohorts, but that execution order does not erase the
history of benchmark development. No test metric changes a checkpoint inside the
runner.

The task has one fixed first probe, one optional second probe, and a terminal
calibration choice. The trained method is a **contextual bandit with finite-context
replay**. It is not a novel general-purpose RL algorithm, an LLM trained by RL, or
a learned motor controller.

## Data and equations

All coefficients, hypothesis frequencies, observation noise, and shift ranges are
synthetic assumptions. There are no OEM logs, downloaded training datasets, or
measured actuators in this study. `recursivecal.py` is the frozen scalar reference.
The new vectorized implementation is tested against its pulse responses and
terminal quality, including guarded aborts. Core file hashes are recorded in each
manifest. The frozen low-pulse request of 0.55 s actually executes 0.56 s at 20 ms.
That limitation is retained here for comparability. The SI simulator has its own
exact-duration integrator and does not retroactively alter these benchmark scores.

Ten equiprobable hypotheses represent nominal, sensor-bias, weak-motor,
high-friction, and torque-deadzone cases. The exact six-parameter arrays and noise
standard deviations are in `manifest.json`. All policies use the same 150 terminal
calibrations. Their final choice maximizes posterior expected quality under the
same ten-model bank. Terminal quality follows the four frozen closed-loop
trajectories in the legacy model.

The primary score is

`reward = terminal_quality - 0.012 * diagnostic_cost`.

Six pulse actions cost 1.0 each. The reference check costs 1.5. A policy can perform
at most two distinct probes, so the maximum spent cost is 2.5. Pulse observations
have noise standard deviations 0.004 in displacement and 0.009 in velocity. The
reference has one coordinate with standard deviation 0.006. Noise coordinates in
the unused padded reference slot are zero and have no inferential meaning.

## Train, validation, and evaluation

Default run sizes are 1,024 training contexts, 512 validation contexts, and 512
evaluation contexts **per cohort**. The release run uses learner seeds 13, 37, 103,
211, and 509. CLI users can specify run sizes and learner seeds. A `quick` run is a
software check, caps training/test size at 128/64, uses fewer updates, and is labeled
as such in its outputs. It must not be presented as the release experiment.

| Partition | RNG seed | Role |
| --- | ---: | --- |
| Training | 3100261121 | Bandit training and fixed-schedule shortlist |
| Validation | 3200261121 | Checkpoint selection, fixed schedules, mismatch threshold |
| Finite-prior test | 3300261121 | New noise realizations on the ten-model prior |
| Continuous jitter | 3400261121 | Perturbed parameters under the same equations |
| Unseen high load | 3500261121 | High-load parameters absent from the inference bank |
| Extreme deadzone | 3600261121 | Deadzones beyond the prior range |
| Directional friction | 3700261121 | A new asymmetric friction term |
| Shuffle base | 3800261121 | Matched-frequency action permutations |
| Bootstrap base | 3900261121 | Paired interval resampling |

Episode IDs contain partition, seed, and index. Train, validation, and test IDs must
be disjoint. Finite-prior **plant values intentionally overlap** across partitions;
this is not a held-out-plant test. Shared latent plant types do not invalidate a
new-noise estimate, but they limit its generalization scope. Different policies
receive the same pre-generated observations on the same test cases. The raw
evaluations retain each case and policy separately.

The continuous-jitter cohort adds Gaussian perturbations with standard deviations
`[0.025, 0.012, 0.018, 0.018, 0.004, 0.01]` to motor, friction, load, damping, bias,
and deadzone. Deadzone is clipped at zero. High-load and extreme-deadzone ranges
are explicit in `FiniteBank.make_data`. These two cohorts preserve the original
equations. The structural cohort multiplies positive-velocity Coulomb friction by
`1 + asymmetry`, with asymmetry sampled uniformly from 0.5 to 1.2. Negative-velocity
friction keeps its original value. The inference bank assumes zero asymmetry.
This breaks mirror symmetry and supplies a specified synthetic structural stress
test. It is not evidence of any particular real fault distribution.

## Policies and controls

| Policy | Implemented behavior |
| --- | --- |
| `no_probe_prior_calibration` | Select the prior-optimal fixed calibration with zero tests. This is not necessarily the factory calibration. |
| `best_fixed` | Rank 29 schedules on training contexts, then select among the top five on validation. |
| `best_fixed_two` | Select a two-probe schedule on validation among the 21 unique pairs. |
| `fixed_first_only` | Run the common low positive pulse, then calibrate. |
| `bayesian_adaptive` | Run the common first pulse; choose STOP or the second probe by expected terminal quality less its cost. |
| `bayesian_forced_two` | Choose a second probe using the same expected utility, without STOP. |
| `bayesian_shuffled` | Permute the adaptive second choices across cases; recompute each case's posterior from its actual assigned probe. |
| `bayesian_abstain` | If the first reading exceeds a validation-derived mismatch threshold, stop and return the prior-optimal calibration. |
| `learned_seed_*` | Observed-feature MLP chooses STOP or a second probe. The same Bayesian terminal calibrator is used. |
| `learned_seed_*_shuffled` | Permute that learner's choices and recompute calibration using the assigned probe. |

Shuffled controls preserve the complete distribution of selected actions and
therefore **aggregate diagnostic cost**. They break the association between a
case's observation and its second action. Individual paired cases can have
different costs. Equal test counts in the forced-two comparison do not ensure
equal cost because the reference costs more than a pulse. Raw quality, cost,
number of probes, and net reward are all retained to make these distinctions
inspectable.

Bayesian expected utility uses tensor-product Gauss-Hermite quadrature, order 15
in a full run and three in a quick run. It integrates Gaussian observations under
the current finite posterior. Globally dominated calibration candidates can be
removed without changing any posterior-optimal terminal choice. This computation
is an approximation to the continuous observation integral, not a proof of global
optimality for the real world or for all possible first probes. A development
review found that order five can change small policy comparisons. The release
therefore uses the highest implemented order, 15, for its primary baseline and
records validation results at orders 5, 9, and 15 before test generation. Test
cohorts also retain order-five and order-nine outcomes, action-disagreement rates,
and score differences relative to the primary. This is a sensitivity report, not a
proof that order 15 has converged. Tiny learned-versus-Bayesian differences must be
read in that context, without selecting whichever order gives a preferred score.

## Learned policy, selection, and information boundary

The twelve input features contain the first pulse's two observed values, scaled
by 0.15 and 0.4, and the ten public posterior weights scaled by four. The learner
does not receive the true model index, physical parameters, unchosen observations,
or the true terminal quality. Its public action method only accepts this feature
array. Tests change hidden parameters, reward tables, and unobserved probe values
while checking that these changes do not alter a fixed policy's actions or
posterior calibration choice.

The NumPy MLP has one 48-unit tanh hidden layer and seven action values. Training
uses Adam at learning rate 0.0015 for 700 updates, minibatches up to 128, and
epsilon-greedy exploration decreasing from 0.55 to 0.10. A selected reward is
rescaled to `(reward - 0.8) * 10` for regression. Only that action's target enters
the gradient. The host precomputes counterfactual rewards to make replay cheap.
Repeated visits can select different actions on the same finite context, so this
must not be described as fresh online physical interaction.

Every 50 updates, the fitted policy is scored on validation contexts. The highest
validation mean selects the checkpoint, with earlier checkpoints winning ties.
Each learner seed gets its own saved JSON weights, training log, and selected
update. Test cases do not influence this checkpoint selection. All training seeds
are reported, including poor seeds. A saved checkpoint is reloaded before test
evaluation and must exactly reproduce validation actions. Artifact verification
also replays test decisions directly from exported first observations.

## Mismatch detection and fallback

The mismatch statistic is the smallest Euclidean distance from the observed first
pulse to a prior prediction, divided coordinatewise by the known synthetic noise
standard deviations. The threshold is the 95th validation percentile using the
`higher` quantile rule. It is fixed before test evaluation.

Abstention returns the prior-optimal calibration and pays for the first probe
already taken. This can improve some shifted cases and hurt others. False-alarm
rates and all shifted-case rates must be reported. It cannot detect every
inadequacy, does not guarantee a bound on true quality, and is not a certified
safety mechanism. A prior-optimal fallback is not equivalent to preserving a
known-good physical controller.

## Statistics and claims

The runner reports mean quality, mean diagnostic cost, mean probe count, mean net
reward, action counts, and abstention rate for every policy and cohort. Comparisons
other than the shuffled controls use the **paired case difference** with 2,000 percentile bootstrap resamples
(500 in quick runs), giving a 95% interval. These intervals describe episode
uncertainty conditional on the fitted policy and specified synthetic population.
They do not include uncertainty from choosing the benchmark or the physical model.
For a shuffled control, one fixed permutation links cases and induces dependence.
Its contrast is reported descriptively with exact aggregate cost agreement and
`ci95: null`. An ordinary iid paired bootstrap is not claimed for that contrast.

For trained methods, every seed's result and the sample standard deviation across
seed means are shown. Five seeds do not justify strong distributional assumptions
or general claims about RL training reliability. The suite does not flatten
seed-by-episode rows and treat them as independent training runs. Multiple policy
and cohort comparisons are exploratory; intervals are not corrected for multiple
comparisons. A positive interval alone is insufficient for a publication claim of
general algorithmic superiority.

The empirical-design rationale follows [Patterson et al., 2024,
*Empirical Design in Reinforcement Learning*](https://jmlr.org/papers/v25/23-0183.html)
and [Agarwal et al., 2021, *Deep Reinforcement Learning at the Edge of the
Statistical Precipice*](https://proceedings.neurips.cc/paper_files/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html).
Those papers motivate careful experimental reporting. This small task does not
implement their full multi-task evaluation methodologies.

## Evidence and reproduction

From an installed package, run the CLI experiment command documented in the root
README, or invoke the Python API:

```python
from recursivecal_lab.experiments import run_experiment, validate_artifacts

summary = run_experiment(
    "runs/my_experiment",
    train_size=1024,
    test_size=512,
    seeds=(13, 37, 103, 211, 509),
)
assert validate_artifacts("runs/my_experiment")["valid"]
```

The destination must be new or empty. The function runs in the foreground and
prints its current stage. The same source, inputs, and numerical environment
produce deterministic draws and decisions. Cross-platform BLAS and floating-point
differences remain possible, so the manifest records Python, NumPy, and platform.
Execution time is descriptive and is not expected to be byte-identical.

| Artifact | Contents |
| --- | --- |
| `manifest.json` | Model, assumptions, exact seeds, dependencies, source hashes, and run size |
| `protocol.md` | The protocol copied before training, including in installed-wheel runs |
| `selection.json` | All fixed-schedule train/validation scores and the frozen mismatch threshold |
| `checkpoints/bandit_seed_*.json` | Human-readable learned weights and feature/action contracts |
| `training/seed_*.json` | Training loss, exploration, and validation checkpoint history |
| `training_data.npz` | Train/validation observations, parameters, quality tables, and disjoint episode IDs; load with `allow_pickle=False` |
| `episodes.csv.gz` | Every policy's reward, quality, cost, actions, calibration, and abstention, keyed by episode |
| `evaluation_observations.csv.gz` | Evaluation inputs and evaluator-only truths, explicitly for audit |
| `summary.json` | Workbench-readable summary and paired comparisons |
| `SHA256SUMS.json` | Integrity hashes of every run file |

The verifier checks required files, hashes, current source correspondence, frozen
selections, paired episode IDs, raw-to-summary means, split disjointness, and
checkpoint decision replay. A code change after a run produces a source-mismatch
failure, even if the old data itself is intact. Use the recorded source version
to verify that run. Hashes identify content; they are not signatures or evidence
of an external replication.

## Publication boundary

The implemented artifact supports a reproducible software and synthetic-decision
study, including documented failures. It does not establish that a real actuator
can be calibrated safely, that the SI model matches a vehicle, that one learner
beats Bayesian design broadly, or that this method is novel. A future manuscript
must distinguish this completed computational study from empirical validation and
literature-based novelty assessment. The data-import and trajectory-validation
tools enable measured-data work when a suitable physical dataset exists; they do
not create such evidence by themselves.
