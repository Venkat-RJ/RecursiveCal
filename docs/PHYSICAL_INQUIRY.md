# RecursiveCal: learn the machine

The default CLI and workspace now select [research rig 3](RESEARCH_RIG.md). The observation/commitment protocol below is shared across versions. Use `run_study(rig_version=3)` in Python or `--rig-version 3` in the CLI. The earlier force-domain rig remains available with version 2. Version 3 replaces the motor-force lag and ideal control sensor with DC drives and sampled instrumentation, and adds an explicit spring-applied brake.

RecursiveCal's central system is an investigator coupled to a physical simulator. The investigator chooses an experiment, receives instrument readings, revises its belief, and eventually commits a calibration. A separate evaluator then tests that commitment on new trajectories. The evaluator can reject the calibration even when the diagnosis is correct.

The connected foundation is implemented in `physical_rig.py`, `research_rig.py` and `inquiry.py`, with the physical workspace at `/`. The new rig identifier is `recursivecal.physical-rig/3`; both current rigs use the `recursivecal.physical-inquiry/1` evidence contract. The report protocol is unchanged; the mechanics are versioned separately. Archived rig `/1` evidence remains attached to its original source revision. See [physics validation](PHYSICS_VALIDATION.md) for the current mechanical checks.

## Run the complete loop

After installing the repository with `python -m pip install -e .`:

```bash
recursivecal inquire --case weak_motor --seed 7 --output runs/weak-motor.json
recursivecal verify-inquiry runs/weak-motor.json
recursivecal serve
```

Open `http://127.0.0.1:8765/inquiry.html`. The CLI logs each actual test in the foreground. The server also runs in the foreground and stops with Ctrl+C. No GPU, API key, model-provider request, remote queue or hardware driver is involved.

The browser can run new investigations against the local API, import and export complete reports, replay the authored CAD assembly before and after calibration, inspect the investigator's journal, and review every independent motion check. The packaged recorded investigation is explicitly labeled as saved evidence. It does not run new physics in JavaScript.

## The retained version 2 physical model

The mechanics and existing Bayesian calibration fields below remain shared. Read the [version 3 specification](RESEARCH_RIG.md) for its drive, sensor, brake and numerical definitions. Statements about an ideal sensor, force lag or absent electrical model below describe version 2.

The plant is a rigid liftgate with one rotational degree of freedom and two identical powered struts. It shares the authored CAD mount geometry with the existing SI model. The force-to-torque conversion uses the derivative of strut length with respect to hinge angle, so the mechanical advantage changes through the stroke.

The rotational balance includes:

- Hatch gravity and inertia, including the declared assumption that added mass lies at the nominal centre-of-mass radius.
- Two gas-assist force curves, interpolated by strut length, with a stated ideal-gas temperature multiplier.
- Two bounded motor-force commands and an analytic first-order actuator lag.
- Coulomb friction, static friction, hinge damping and axial strut damping.
- Inelastic end stops, a speed-limit event, and explicit unpowered-brake capacity.
- Optional extra friction during closing, used as a structural mismatch fixture.

Command force is limited to ±330 N per strut or the plant's lower force limit. Motor effectiveness multiplies the bounded command. The simulated motor therefore cannot recover arbitrary torque simply because the investigator identifies the correct effectiveness.

Position, velocity, actuator force, elapsed time and cumulative absolute motor work persist between experiments. A change of test does not silently reset the mechanism. The explicit `reference` action uses an external bench fixture: it fixes the angle at 20 degrees, zeros velocity and motor force, advances time and charges a setup cost. Fixture work is not counted as motor work.

Both simulation interfaces call the same mechanical step. It uses an iterated geometric midpoint, analytic motor-dependent sliding flow, explicit static-friction transitions and localized inelastic contacts. Incoming impact speed is retained before velocity is reset. Power-loss and observation boundaries are scheduled separately, even when extremely close. A numerical stop is an experiment outcome, not a certified hardware emergency stop.

### Instrument assumptions

| Signal available to the investigator | Assumed logging noise, standard deviation |
| --- | ---: |
| Biased angle encoder | 0.002 rad |
| Angular-rate instrument | 0.008 rad/s |
| Inline strut load cell, force per strut | 1.5 N |
| Ambient temperature | Exact declared chamber setting |

The load-cell model observes motor force plus gas assistance minus axial damping. It does not expose a fictitious sensor that directly separates unknown motor and gas forces.

The low-level controller uses an explicitly ideal filtered encoder/rate signal, including encoder bias. Independent noise is added to the logged instrumentation. No specific ECU filter, sampling hardware or sensor bandwidth is claimed. Noise, geometry and all default coefficients are synthetic assumptions.

### Present physical scope

This is a dimensioned software-in-the-loop foundation. There are no measured production-vehicle coefficients in the bundled cases. It does not model motor current, battery voltage, thermal evolution, lead-screw backlash, flexible panels, obstacle contact, anti-pinch behavior, latching, CAN or ECU timing. Those require separate model definitions, measurements and validation rather than a visual claim that they exist.

Existing CSV force fitting and trajectory comparison remain available in the Model & measurements workbench. A fitted parameter set can be passed into `PhysicalRig` through Python, with its source provenance retained by the calling experiment. The finite inference bank is not automatically rebuilt from an imported force curve. A measured curve alone does not validate the resulting complete plant.

## The investigator's information boundary

`InquirySession` exposes three operations:

```python
from dataclasses import asdict
from recursivecal_lab.physical_rig import Calibration
from recursivecal_lab.research_rig import ResearchRig
from recursivecal_lab.inquiry import InquirySession

session = InquirySession(ResearchRig(), max_tests=5, budget=8)
view = session.observe()
view = session.step("high_sweep")
commitment = session.commit(asdict(Calibration()), disposition="abstain",
                            reason="external policy example; no identified calibration")
```

An agent receives measured angle, rate, total strut force, timestamps, ambient temperature, legal actions, its recorded observation history and remaining budget. It does not receive true mass, motor effectiveness, friction, true position, the case name, tracking quality or verifier results.

Returned views are copies. A caller cannot change the session by mutating an observation. Tests check the allowlist, copies, budgets, state continuity and commitment rules. This Python interface is an accidental-disclosure boundary. Arbitrary adversarial code in the same Python process is not isolated; an untrusted agent needs a separate process and transport.

After commitment, no further diagnostic steps or replacement commitment are allowed. Evaluator records are available only after the commitment is sealed. The final report deliberately contains a separate `evaluator_only_truth` block for a human audit. Do not feed that completed report back into the investigator as if it were a permitted observation.

## Bounded diagnostic actions

| Action | Physical operation | Duration | Cost units |
| --- | --- | ---: | ---: |
| `low_sweep` | Smooth command to 20 degrees | 1.4 s | 1.4 |
| `high_sweep` | Smooth command to 60 degrees | 2.4 s | 2.4 |
| `mid_sweep` | Smooth command to 40 degrees | 1.8 s | 1.8 |
| `hold` | Hold the current measured angle | 0.7 s | 0.7 |
| `coast` | Disconnect the drive supply and observe the unpowered response | 0.18 s | 0.8 |
| `reference` | External 20-degree encoder fixture check | 0.1 s | 1.5 |

These costs are declared protocol units including setup assumptions. They are neither financial costs nor a claim that every fixture can be repositioned in 0.1 physical seconds. Fixture repositioning is externally supplied and outside the actuator trajectory. The following stationary fixture interval acquires three observations at their actual recorded times. The default budget is 8 units with at most five tests. API bounds are 12 units and six tests.

Three timed instrumentation snapshots per experiment enter the likelihood. The report preserves the full diagnostic trace for audit. A limit-aborted episode must abstain. A Bayesian risk screen can reject a proposed action when more than 5% of posterior mass predicts an abort, but this conditional screen is not a real-world safety probability.

## Bayesian baseline and model criticism

The first connected investigator is a Bayesian baseline, not a trained RL agent. Its public bank contains 72 combinations:

| Unknown | Candidate values |
| --- | --- |
| Mass | 25, 30 kg |
| Motor effectiveness | 0.65, 0.82, 1.00 |
| Gas-force multiplier | 0.75, 1.00 |
| Coulomb friction | 6, 14 N·m |
| Encoder bias | −0.025, 0, +0.025 rad |

Each hypothesis carries its own persistent simulated state. Every actual selected test is also propagated through those hypothesized plants. Likelihoods use a diagonal Gaussian model with standard deviations 0.004 rad, 0.016 rad/s and 3 N. These are twice the logging-noise standard deviations and serve as an explicit inference tolerance.

Action selection estimates one-step information gain using 48 seeded posterior-predictive samples, divides that gain by test cost, and applies the conditional abort screen. It includes a small preference for missing direction coverage. After the belief concentrates, a declared confirmation phase requests sufficiently large opening and closing sweeps. This confirmation phase is part of the protocol, not a claim of globally optimal planning.

Direction coverage requires both a commanded excursion and an observed excursion of more than five degrees in the same direction. Drift during a hold, free coasting and an external fixture reset do not count. This prevents an uncommanded fall from being credited as a successful closing experiment.

Model criticism accumulates normalized residuals for each hypothesis. If the best cumulative normalized RMS residual exceeds 4, or every hypothesis has a maximum normalized residual above 6, the investigator flags a mismatch. It then requests the declared reference check when available and abstains. These are engineering rejection thresholds, not calibrated statistical coverage guarantees.

A concentrated posterior only means that one candidate is favored within this particular bank. Off-grid parameters, unmodeled physics or insufficient excitation can make the bank inadequate. Independent verification remains necessary even if the posterior standard deviation is nearly zero. The investigator does not currently invent new physics or automatically expand its model structure.

## Calibration and independent verification

The committed calibration contains estimates of mass, motor effectiveness, gas assistance, Coulomb friction and encoder offset. These alter controller compensation and the sensor correction. They do not mutate the plant. Feedback gains remain fixed at 178 N·m/rad and 68 N·m·s/rad.

After commitment, the verifier creates fresh physical states and runs paired nominal-controller and committed-controller trajectories:

| Verification profile | Motion time | Total observation time | Temperature |
| --- | ---: | ---: | ---: |
| Full opening, 0 to 78 degrees | 4.8 s | 5.8 s | 20°C |
| Full closing, 78 to 0 degrees | 5.6 s | 6.6 s | 20°C |
| Partial reversal, 64 to 27 degrees | 3.1 s | 4.1 s | 20°C |
| Cold opening, 0 to 78 degrees | 5.2 s | 6.2 s | −10°C |

These trajectories and their outcomes are unavailable to the investigator before commitment. They are known development protocols, not a blinded research test set. The final one-second hold is included in each tracking calculation.

A motion profile passes only when it completes, its tracking RMSE is at most 3 degrees, its absolute final error is at most 2 degrees, peak speed is at most 1.15 rad/s and command saturation occupies at most 35% of the observation interval. A candidate must pass all four profiles to receive `verified_in_simulation`. A failed profile yields `verification_failed`. Insufficient evidence, a model mismatch or a diagnostic limit yields `abstained` with the nominal controller retained.

Separate passive-hold and power-loss runs expose structural requirements. The legacy version 2 mechanism lacks enough unpowered holding capacity. The default version 3 research rig explicitly includes a 120 Nm spring-applied brake with a 20 ms engagement delay and tests that declared architecture. Even a motion-verified calibration does not make the mechanism ready for hardware: the modeled brake is a synthetic assumption, not evidence that a real brake exists or can meet the requirement.

## Reproduction and evidence

```bash
# Compare actual adaptive tests with fixed tests and no diagnosis.
python -u scripts/physical_inquiry_audit.py --output runs/physical-audit

# Inspect a single failure or mismatch.
recursivecal inquire --case compound --output runs/compound.json
recursivecal inquire --case overload --output runs/overload.json

# Focused mechanical and information-boundary regressions.
python -m unittest discover -s tests -p test_lab_physical_inquiry.py -v

# Browser acceptance, including actual server computation and report round trips.
python tests/inquiry_smoke.py
```

The fixture audit uses nine declared conditions and three policies: adaptive Bayes, the fixed high-low-mid schedule and the nominal no-probe baseline. Its 27 policy runs are nine distinct physical conditions. They are engineering development cases, not 27 independent experiments or evidence of population generalization. Source hashes, exact seeds, selected actions and full reports accompany the aggregate.

Reports contain the complete diagnostic history, decision scores, conditional posterior, committed estimates, verification traces and evaluator-only ground truth. SHA-256 uses a documented typed canonical representation with IEEE-754 numeric values so a Python report survives a JavaScript JSON round trip. This detects changed contents; it is not an authenticity signature.

`verify-inquiry` and the workspace importer check the prescribed verification profiles, target trajectories and recording durations. They derive tracking RMSE and signed final error from the motion trace, check recorded speed and guard evidence, and check saturation accounting where the model's trace contract records it. They then check acceptance, aggregate metrics and the reported outcome. The CLI also checks the committed history and diagnostic budget. Recomputing a digest after changing a summary metric does not bypass those consistency checks.

Use `recursivecal verify-inquiry runs/weak-motor.json --replay` to rerun an inquiry against the same source revision, case, seed and policy, then compare the complete diagnostic and verification evidence. This is slower than the normal consistency check. Source revision mismatches are rejected, including older archives that need their original source checkout. Replay still does not establish authorship or measured-hardware accuracy.

Archived model 1 and early model 2 traces may omit interval saturation flags. Their recorded saturation fraction cannot be independently reconstructed from the available trace, so normal verification has explicitly narrower coverage for that legacy field. Model 3 requires the flags. A valid report remains a consistency result unless source-bound replay is explicitly requested.

The CAD renderer and mesh are copied byte-for-byte from the authored assembly and checked against their source by `scripts/check_release.py`. The small browser geometry adapter only moves that assembly using stored hinge angles. It contains no second dynamics engine.

## What counts as a completed next research claim

The engineering foundation connects the plant, instruments, investigator, controller, verifier and workbench. A claim about learning better experiments still needs a stronger comparison than this finite-bank demonstration: independently specified plant variation, adequate Bayesian planning, learned policies trained on observation-only inputs, paired evaluation and a documented compute budget.

A claim about real-world accuracy needs measured geometry and inertia, force and friction data, synchronized trajectories, independent validation conditions and the hardware protocol. Those results cannot be supplied by passing software tests. The implementation keeps those gates visible so future work builds on actual evidence.
