# Stateful investigation environment v0: exploratory specification

**Status: synthetic mechanism, classical Bayesian baseline, and an exploratory small multi-step RL pilot. No demonstrated RL advantage, autonomous model-structure discovery, or hardware validation.** The parameters and stress cases are synthetic choices made during development, not pre-registered discoveries or measured actuator characteristics.

## What changed from the fixed-fixture benchmark?

The v0.3 simulator independently resets its mechanical state before each pulse. The sequential wrapper in `benchmark.py` allows additional decisions but continues to use independent, precomputed responses. In the first 64-case-per-cohort smoke run, the myopic Bayesian baseline still always chose the same first pulse and never chose a third. That is evidence that increasing the action-count limit alone does not create a meaningful long-horizon inquiry problem.

`stateful_plant.py` introduces one controlled physical-state dependency: the mechanical fixture resets between diagnostic pulses, while a synthetic **hidden thermal-friction state** carries over. A prior high-torque pulse may change how the next pulse responds. That makes probe order capable of changing the evidence an agent receives. It also creates a potential information/safety tradeoff: an informative intervention can alter the tested system. We do not claim this exact numerical heating law describes real hardware.

## Synthetic dynamics and observations

Normalized acceleration is

`a = motor * torque - friction*(1 + thermal_coeff*heat)*(1 + directional_asymmetry*[v>0])*tanh(v/.035) - damping*v - load*sin(pi*x/1.1)`.

The unobserved thermal state evolves per 20 ms simulation step:

`heat_next = heat + 0.02*(2*torque^2 - .15*heat)`.

A reference check measures sensor bias without applying a pulse. A pulse measures displacement relative to the mechanical fixture and terminal velocity. Independent noise standard deviations are 0.004 and 0.009 for pulse coordinates, 0.006 for the reference. Temperature is NOT provided to the policy. All numerical coefficients, laws and sample ranges are chosen for this synthetic benchmark; no measured actuator data is involved.

Permitted probes are low/high positive or negative pulses, two offset pulses, and a higher-cost sensor reference. Repeated probes are forbidden, and the action budget allows at most three probes and total cost 3.5. `STOP` is always permitted. The simulator guards predicted displacement, speed and requested torque using the same normalized limits as the original benchmark. Such software guards are NOT safety certification.

The simulated terminal calibration is selected from 150 legal gain/feedforward/offset combinations and evaluated independently on four reference trajectories. Every candidate starts at ambient thermal state. Diagnostic heating does not transfer to this terminal evaluation, so a policy cannot gain terminal quality simply by warming the actuator. A future study must test this separation as an explicit modeling assumption.

Known families include nominal, weak motor, high friction, high load, sensor bias, and amplified thermal friction; the exploratory `directional_shift` cohort adds a held-out directional asymmetry mechanism. Train/validation/test seeds have explicit, distinct salts. The scalar parameters in the code are the source of truth. All cohorts are synthetic and may favor or penalize particular methods.

## Completed gate (not a research conclusion)

- Six unit tests pass locally, including refusal of repeated/over-budget actions, deterministic episodes, hidden-variable non-disclosure, a terminal cold-start check, and policy access through observation dictionaries only.
- With `Plant(thermal_friction=5)`, the negative-low pulse's displacement changes from approximately -0.042806 when first to -0.018260 when preceded by a high-positive pulse. Difference 0.024546, about 6.14 times the assumed displacement noise standard deviation. With the thermal coefficient zero, this order dependence disappears.
- That confirms a designed mechanism, not that an RL agent discovered it, nor that a physical power liftgate behaves this way.

## Required research comparison before any publication claim

1. Define an explicit Bayesian filter over *stateful* model hypotheses, including thermal history, and a strong non-myopic sequential design/planning baseline. Compare to a deliberately misspecified Bayesian filter as a separate controlled ablation.
2. Train multi-step RL policies against the same public action constraints and same observation history. Report all training seeds, checkpoint selection, paired held-out performance, and matched-action shuffles.
3. Separate model-family classification, parameter estimation, calibration quality, test cost, and simulated guard events. Do not report a reward-only win without these breakdowns.
4. Check if a simple fixed thermal excitation schedule achieves the same gain. If it does, regard that as a negative result for learned investigation.
5. Use one held-out structural family (directional friction) and at least one independent stress family not used to develop the policy. Avoid changing test cases after seeing outcomes without labeling the analysis exploratory.
6. Run numerical step-size checks and parameter sensitivity before calling the synthetic dynamics a useful scientific testbed. No real-hardware claims without independent measurements.

A small multi-seed trained policy comparison has now been run and is recorded in [STATEFUL_PILOT_AUDIT.md](STATEFUL_PILOT_AUDIT.md). It did **not** demonstrate RL superiority. The previous 960-row result archive belongs to the **independent-reset** benchmark and cannot be transferred to the stateful simulator. The sequential Bayesian filter tracks latent thermal state but uses one-step Monte Carlo utility, not full-horizon planning.
