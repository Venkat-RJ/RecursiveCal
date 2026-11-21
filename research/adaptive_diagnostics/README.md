# RecursiveCal | Independent physical-model and adaptive-RL audit

**21 November 2026. Exploratory synthetic research. All experiments executed in the assistant's CPU environment. No user Mac, no paid GPU, no vehicle hardware, and no OEM calibration data.**

## Decision

The original v0.2 task runs but is not precision-validated and did not produce an adaptive RL policy. A newly defined finite-model task does: small reward-learning policies choose different second experiments based on measured outcomes. This result is reproducible on matched synthetic tasks, but it is **not** evidence of an RL advantage over strong classical Bayesian design or of physical generalization. A previously unseen high-load test reveals a serious failure: diagnostics can be worse than doing nothing.

## Physics and data provenance

- Original 1D simulator: [recursivecal.py](https://github.com/Venkat-RJ/RecursiveCal/blob/main/recursivecal.py) uses normalized motor effectiveness, friction `tanh(v/0.035)`, viscous damping, sine position-dependent load, Gaussian measurement noise, and a torque deadzone on shifted tasks. Coefficients and ranges were **chosen for the benchmark**, not fitted to measured actuators. Source equations were reconstructed locally and cross-checked by reproducing all three 60-task factory mean scores exactly at five decimal places.
- CAD test cell: [physics_v2.py](https://github.com/Venkat-RJ/RecursiveCal/blob/main/mechanics/cad_v1/simulation/physics_v2.py) is a separate 1-DOF hinge model with two gas-assisted powered struts. Model parameters like 25 kg hatch mass, 12 kg m² hinge inertia, 165–212 N gas force, and 330 N per motor were **assumed**. The included synthetic force CSV is *generated from this model*, so fitting it back to the model is not independent validation.
- Engineering context: [Stabilus Gas Springs Technical Information](https://www.betz.cz/stabilus/ke-stazeni/08_Technical_Information_EN.pdf) describes pressure-dependent force curves, extension/temperature influences, load and mounting geometry; [SAE 2020-01-0908](https://saemobilus.sae.org/articles/damped-tailgate-system-drop-dynamics-evaluation-strut-force-durability-2020-01-0908) studies damped tailgate drop physics. Neither source supplies matching geometry and actuator measurements for our simulator. Do not transplant numbers or call the current CAD a validated digital twin.

## Numerical audit of v0.2

The six-parameter probe Jacobian has a zero sensor-bias column for all torque pulses. Reference-check adds the sensor-bias measurement and restores rank in this local analysis. All positive/negative pulse pairs were exactly mirrored for 1,000 sampled plants. This is a property of the simplistic symmetric equations, not a general property of physical mechanisms.

**Identified numerical issue:** diagnostic pulses specified at 0.55 seconds are implemented with `round(0.55 / 0.02) = 28` steps, so they actually last **0.56 seconds**. The alternative exact-duration integration uses 27 full 20-ms steps plus a final 10-ms step. Do not silently rewrite the frozen benchmark without re-running published results.

| Numerical check | Observed |
|---|---:|
| Original pulse duration at 20 ms step | 0.56 s (requested 0.55 s) |
| Maximum pulse displacement difference: original 20 ms vs corrected 2.5 ms reference | 0.007954 |
| Maximum pulse displacement difference: exact-duration 20 ms vs corrected 2.5 ms reference | 0.003978 |
| Maximum model-quality difference, 20 ms vs 2.5 ms over five plant examples | 0.009492 |
| CAD strut moment-arm finite-difference residual | 1.883e-11 m/rad |
| CAD work by force vs torque relative residual | 3.492e-10 |

## New exploratory benchmark

Ten synthetic plant hypotheses, equally weighted, represent nominal, sensor-bias, motor-weakness, high-friction, and torque-deadzone alternatives. These types are physically motivated but **not an empirically observed distribution**. We chose this mixture to examine diagnosis ambiguity; it is not a blind pre-registered challenge and can favor adaptive approaches.

The first test for adaptive policies is always `pulse_pos_low`. After seeing its two noisy outputs, an agent may STOP, run any other permitted pulse, or run `reference_check` at its higher cost. All strategies use the **same 150 final calibration candidates**, the same Bayesian terminal calibration selection, and identical hidden task and noise realizations per evaluation episode. The net score is calibration quality minus 0.012 per probe-cost unit. The 1,024-episode training split alone selects the best fixed schedule among no test, seven single tests and 21 unordered pairs. The 2,048-episode test split is evaluated separately. A 256-episode jitter split varies continuous physical parameters absent from the inference bank. Two 256-episode stress splits use load or deadzone ranges absent from the bank. This is not unseen new physics equations, only parameter-family mismatch.

The second-stage **Bayesian value-of-information** comparator computes posterior-predictive Monte Carlo utility (40 samples per candidate probe) and compares against stopping. It is decision-focused, approximately model-optimal, and stronger than a variance heuristic. A forced-two-test ablation checks whether gains survive without early stopping. Shuffling the proposed second action across tasks preserves how often each test is run but breaks its link to the actual observation.

## Evaluation outcomes

| Split | No test | Best fixed (train-selected) | Adaptive Bayes | Adaptive − fixed | 95% paired bootstrap CI |
|---|---:|---:|---:|---:|---|
| Finite-model heldout, n=2048 | 0.832819 | 0.877871 | 0.890034 | +0.012163 | [+0.011156, +0.013191] |
| Continuous jitter, n=256 | 0.824901 | 0.865888 | 0.874155 | +0.008268 | [+0.005079, +0.011284] |
| Unseen high-load, n=256 | 0.933216 | 0.883843 | 0.896695 | +0.012853 | [+0.010930, +0.014671] |
| Unseen extreme deadzone, n=256 | 0.527863 | 0.516244 | 0.534244 | +0.018000 | [+0.018000, +0.018000] |

Forcing an adaptive second test still improves over the best fixed two-test schedule by **+0.008207** (paired bootstrap 95% CI [0.007313, 0.009158]) on the finite-model test, so this is not solely an early-stopping advantage. The second action varies meaningfully with observations (STOP, reference check, higher-amplitude pulse). The shuffled second-action control drops the in-model reward to **0.861949**.

At a **10 ms** integration step rather than the frozen **20 ms**, a separate 1,024-episode in-model run still finds an adaptive advantage of **+0.011491**; this is a robustness check, not a retroactive replacement for the frozen results.

## Small learned-policy experiment

Three independent CPU contextual-bandit RL policies were trained with a two-layer neural Q network. Each decision sees only the observed first pulse and a Bayesian posterior derived from that observation. The network chooses one second diagnostic action or STOP; a fixed Bayesian component then chooses final calibration. Training used 15,000 independently seeded synthetic contexts and 450 minibatch updates per policy. The policy sees only rewards for **its selected actions**; counterfactual reward tables are simulator precomputation for faster replay and do not enter training gradients. No language model was fine-tuned and no end-to-end motor controller learned.

| RL training seed | Learned net reward, heldout n=2048 | RL − best fixed | RL − adaptive Bayes |
|---|---:|---:|---:|
| 13 | 0.889589 | +0.011718 | -0.000445 |
| 37 | 0.889194 | +0.011323 | -0.000840 |
| 103 | 0.889127 | +0.011255 | -0.000908 |

Every RL seed beat the best fixed schedule in-model and learned nonconstant second actions. All three remained **below the adaptive Bayesian comparator**. The apparent RL success is therefore task-specific and does not demonstrate a new method superior to classical system identification. OOD scores also do not show reliable generalization. Do not merge these new pilot results into the original v0.2 table without clearly separating benchmark versions.

## Model adequacy and failure mode

First-pulse discrepancy is the Euclidean distance to the closest prior prediction after scaling position and speed by their observation noise. A threshold at the **95th percentile of 5,000 training episodes** is evaluated without retuning on held-out tests.

| Split | Fraction flagged | Median standardized mismatch |
|---|---:|---:|
| Finite-model heldout | 4.5% | 1.031 |
| Continuous jitter | 9.6% | 1.089 |
| Unseen high-load | 33.8% | 1.874 |
| Unseen extreme deadzone | 90.6% | 3.748 |

The check flags some model inadequacy, but **misses most unseen high-load cases**. On unseen high-load tasks, not testing scored **0.933216**, whereas the nominal adaptive Bayesian policy scored **0.896695**. The posterior can be falsely confident about an incorrect calibration. On the extreme deadzone split, all second decisions collapsed to STOP. These tests are a warning against real-hardware claims and against measuring only relative improvement over a weak fixed diagnostic schedule.

## Independent liftgate evidence and a physical requirement our model fails

A public **June 2008 U.S. NHTSA engineering investigation** examined the 2004–2006 Toyota Sienna power liftgate ([original report](https://static.nhtsa.gov/odi/inv/2006/INCR-EA06020-29305P.pdf)). Its measurements describe a 71 lb liftgate, new strut A exerting 147 lb at full compression and 119 lb at full extension at 72°F, with material temperature dependence (at 35°F and 110°F, that strut changed its full-extension force from 113 lb to 129 lb). The report's tested *pairs* showed that at 189 lb of combined full-extension support the liftgate remained open, at 176 lb it descended slowly, and at 145 lb it dropped and the vehicle motor engaged. **Those are not measurements from our own geometry.** We must not import them as fake RecursiveCal calibration labels.

They do establish a qualitative physical test requirement that our present CAD model misses: a nominal gas-assisted tailgate must either hold open passively when the opening motor disengages, or explicitly model the separate device that does so. Our current `cad_v1` 78° open position has **68.85 Nm gas-spring opening torque** against **134.65 Nm gravity closing torque**, a **65.79 Nm closing deficit**. To balance gravity with these mounting coordinates would require around **322.67 N per strut**, versus the currently assumed **165 N**. That means our nominal CAD hatch **cannot remain open without active motor support**, unlike the gas-strut-supported mechanism depicted in the real reference. `physical_requirements.py` records this failed check and the external reference without applying mismatched vehicle parameters.

The model also has no latch, motor-disengagement logic, direction-dependent friction/hysteresis, measured temperature effects, obstacle detection, or anti-pinch. This is a **physical-model adequacy failure**, not a numerical implementation failure. A future model must make this requirement pass through proper geometry, mass and force validation, not by copying another vehicle's numbers.

## Independent physical evidence still missing

No sensor or actuator measurements from our own CAD/test bench were used in these experiments. Required external checks include independently measured mounting geometry, hatch mass/inertia, strut force and hysteresis vs stroke/temperature, instrumented position/current traces, direction-dependent friction, latch and anti-pinch logic, and validation against **held-out physical cycles**. The Stabilus example is useful to reason about force/stroke ranges, but is not matched to our mounting geometry or actuator. This phase provides a simulator structure and reproducible numerical checks, not certified SiL/HiL capability.

## Reproduce in a clean Python environment

```bash
python -m pip install 'numpy>=1.24' 'torch>=2'
python TESTS.py
python audit_physics.py --output physics_audit.json
python test_exact_duration.py
python adaptive_benchmark.py --train 1024 --eval 2048 --transfer 256 --dt .02 --output adaptive_results.json
python adaptive_benchmark.py --train 512 --eval 1024 --transfer 128 --dt .01 --output adaptive_dt_0_01_results.json
python train_adaptive_rl.py --train 15000 --steps 450 --eval 2048 --transfer 256 --out rl_adaptive_results.json
python check_mismatch.py
```

All numbers above are deterministic for these seeds under the tested Python/NumPy/PyTorch versions. Cross-platform floating-point variation is possible. `adaptive_benchmark.py` uses a local copy of the published RecursiveCal v0.2 equations; it does not change the original frozen benchmark. The CAD test physics is copied from the previously generated mechanical CAD source kit. Output JSON contains model assumptions, per-policy metrics and paired confidence intervals (but not every episode-level trace). This is exploratory evidence, not an external independent replication.

## Next research gates

1. Fix exact pulse duration and assess integration tolerance in a versioned v0.3 simulator, then **re-run all v0.2 baseline scores** before adopting any new numbers.
2. Replace bespoke hypothesis families with a representative fault taxonomy and physical parameters supported by independently documented data. Add geometry and noisy measurements separately; keep provenance.
3. Benchmark calibration regret and reliable fallback/no-test behavior under unforeseen loads, severe nonlinearities, and failed sensors. Set an absolute safety/regret gate, not only a win over a fixed testing schedule.
4. Only after these pass, test multiple trained RL policies against robust Bayesian design, uncertainty-aware model-mismatch checks and a conservative classical fallback.

**No real-hardware use or safety claims are authorized by this work.**
