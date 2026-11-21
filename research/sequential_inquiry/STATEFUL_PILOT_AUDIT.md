# Stateful diagnostic inquiry: exploratory RL and Bayesian pilot (21 November 2026)

**Research question:** Can a trained policy choose a sequence of experiments that helps investigate an unfamiliar physical system, and outperform a strong Bayesian system-identification or experimental-design comparator? This is an exploratory mechanism and learning pilot, **not** the claimed achievement of that goal or an independent blinded study.

The simulator in [`stateful_plant.py`](stateful_plant.py) resets the mechanical fixture between diagnostic pulses but retains a hidden synthetic thermal-friction state. The ordering of probes therefore affects subsequent observations. Every final calibration is scored on cold-start trajectories to keep probe heating from directly improving terminal quality. None of the laws or parameter ranges are based on measured liftgate data.

## Executed protocol

- Finite 32-particle Bayesian prior sampled independently from training-design seeds 100000 onward, containing **three thermal-mechanism particles**. The filter propagates each particle's latent thermal state after each executed test, and makes one-step expected terminal-utility decisions using 32 Monte Carlo observation samples per candidate probe. This is **not** a globally optimal non-myopic Bayesian planner.
- A deliberately misspecified ablation uses the same 32 particles with their thermal-friction coefficients set to zero, so it is a controlled missing-model comparison, not an independent Bayesian method.
- The best fixed schedule is chosen from 58 predefined permitted sequences using 64 training cases and a shortlist of five on 24 validation cases. The selected sequence is `pulse_neg_low` then `pulse_pos_high`.
- Three independent small NumPy REINFORCE actor seeds (13, 37, 103), each using 800 *online selected-action* training episodes with identical plant-seed list but different policy randomization. Checkpoints were chosen by validation reward on 24 cases, not by test reward. The actor chooses legal diagnostic probes or STOP, using only observed history and a Bayesian posterior. The **terminal calibration is still Bayesian** and the learner does not revise the hypothesis family.
- Two synthetic cohorts: `finite_test` (known equations, unseen seed-derived parameters and noise) and `directional_shift` (a structurally different directional-friction multiplier omitted from all Bayesian inference banks). The **same** 32 seeds `20000..20031` are used for every policy and actor, but their two cohort populations differ. On the finite cohort, 10/32 plants have nonzero thermal friction; on the shifted cohort, 2/32 do. These are too few examples for subgroup claims.
- Primary descriptive objective: terminal calibration quality minus `0.012 * diagnostic_cost`. There are at most three distinct tests, each pulse costs one and the sensor reference costs 1.5. The policy has a hard budget of 3.5 and can stop before spending it. Guarded numerical-limit events are retained separately; these are not real-world safety certifications.
- Source and raw episode manifests are emitted by the two scripts. Two executed local summary-file SHA-256 values: stateful Bayesian baseline `b923268b61c16d86df4cbfd4b16e1d78ba7c0333f87`; RL pilot `97959aa94451fa177a6adae07ffd1d6a2a992df12d662da1f16cca3a7339befe`. This summary is a description of one run, not externally replicated.

### Observed mean net reward, 32 held-out cases per cohort

| Strategy | Known equations | Directional-friction shift |
| --- | ---: | ---: |
| No diagnostic test | 0.800988 | 0.834752 |
| Train/validation-selected fixed two-test schedule | 0.840934 | 0.807798 |
| Thermal-aware Bayesian one-step design | **0.843527** | 0.835561 |
| No-thermal Bayesian ablation | 0.805871 | **0.845524** |
| Episodic RL, seed 13 | 0.829096 | 0.822321 |
| Episodic RL, seed 37 | 0.837849 | 0.834553 |
| Episodic RL, seed 103 | 0.826983 | 0.828886 |

These are single-run *descriptive* differences with no p-values, corrected intervals, independent training-seed distribution analysis, or selection-bias adjustment. In particular, the apparent advantage of the no-thermal ablation on the shifted cohort does **not** establish that an incomplete model is better. No RL seed beats the thermal-aware Bayesian baseline on either cohort, though the seed-37 policy is close on the shifted cohort. We must not rank strategies generally from this very small synthetic sample.

### What the policies did

| Strategy | Known-family mean quality | Known-family mean test cost | Shifted-family mean quality | Shifted-family mean test cost |
| --- | ---: | ---: | ---: | ---: |
| No probe | 0.800988 | 0.000 | 0.834752 | 0.000 |
| Fixed | 0.864934 | 2.000 | 0.831798 | 2.000 |
| Thermal-aware Bayes | 0.866777 | 1.938 | 0.856749 | 1.766 |
| No-thermal Bayes | 0.822371 | 1.375 | 0.862024 | 1.375 |
| RL seed 13 | 0.866221 | 3.094 | 0.860946 | 3.219 |
| RL seed 37 | 0.864286 | 2.203 | 0.868303 | 2.812 |
| RL seed 103 | 0.865421 | 3.203 | 0.863948 | 2.922 |

The learned policies exhibit variable second and third tests but **each seed chooses one constant first test across all 32 cases**: seed 13 starts with `pulse_neg_offset`, while seeds 37 and 103 always start with `pulse_neg_high`. On the known-family cohort, 29/32, 14/32, and 31/32 episodes respectively used all three probes. None stopped without a test. This is not evidence of self-generated hypotheses or discovery of a better experiment protocol. It is evidence that allowing a third action is *used*, often at an excessive diagnostic cost.

The thermally informed Bayesian policy varies its first action on the test cases, so a constant-first policy is **not an environmental requirement**. All methods use the same cold-start terminal quality evaluator and recorded seed ranges, but the test population is small, the fixed schedule had less training data than RL, and the Bayesian planner only uses a one-step approximation. Stronger comparators remain necessary.

## Reproduction (foreground, CPU)

From a checkout of the research branch with `numpy>=1.24,<3` installed, run in fresh output directories:

```bash
python -m unittest discover -s tests -p 'test_*inquiry.py' -v
python -m unittest discover -s tests -p 'test_*stateful*.py' -v
python -m research.sequential_inquiry.bayes_stateful \
  --particles 32 --train 64 --validation 24 --test 32 --samples 32 \
  --output runs/stateful-bayes-v0
python -m research.sequential_inquiry.train_rl \
  --particles 32 --episodes 800 --validation 24 --test 32 \
  --seeds 13 37 103 --output runs/stateful-rl-v0
```

The scripts save selected schedules, checkpoints, training histories, per-episode actions, calibration choices, diagnostic cost, quality, guard counts, seed and split identity, source SHA hashes, and output hashes. Preserve the source commit with any reported artifact. Repeated runs in different Python/NumPy platforms may differ in last digits; neither numerical nor scientific generalization is established by deterministic software alone.

## Decision and next falsifiable gate

**Stop optimizing the toy actor for a win on these observed 32 cases.** Do not present this run as a new RL method, a physical safety result, a discovered model, or a publication-ready comparison.

Before a stronger claim, implement and freeze:

1. A **non-myopic** finite-horizon Bayesian planner that propagates both beliefs and physical thermal state, plus a fixed budget-normalized schedule. The existing one-step planner is necessary but insufficient.
2. A sufficiently rich prior and a separate controlled no-thermal prior, without relying on just three thermal particles. Report quality and cost separately across plant families, multiple fresh unseen seeds, and model-mismatch conditions.
3. A multi-step environment where the agent can *propose and reject* competing model hypotheses, not merely choose from a menu of seven probes. Define what constitutes model discovery, a failed assumption, or a justified STOP decision before collecting final test results.
4. A new independently frozen test suite, stronger per-family sample sizes, more RL training seeds, action-matched controls and multiple experimental costs. A useful result must beat strong comparators on a specified metric or clearly characterize a reproducible failure that existing methods cannot explain.

The current milestone is a **valid but negative experimental gate** in pursuit of the Prime Intellect residency question.
