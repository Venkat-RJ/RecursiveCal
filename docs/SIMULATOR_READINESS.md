# Simulator readiness and its evidence

The delivered scope is a synthetic research environment for identifying and calibrating one specified liftgate mechanism. The CLI and physical workspace default to research rig 3. The same plant, instrumentation and controller run beneath simulation, diagnostic experiments and the physical RL task.

The environment is suitable for developing policies against this declared model once the release gates below pass. Physical accuracy remains unestablished until independent measurements are supplied. No real actuator is connected by the application.

## What is implemented

| Area | Delivered behavior | Evidence |
| --- | --- | --- |
| Mechanical plant | Authored one-hinge geometry, gravity and inertia, gas assistance, friction, damping, localized end stops and speed guards | [Mechanical validation](PHYSICS_VALIDATION.md) |
| Healthy reference | Explicit 120 N·m spring-applied brake; powered motion and a stable unpowered hold | [Complete rig audit](../research/releases/research-rig-v3/validation.json) |
| Two drives | Independent DC current, terminal voltage, winding heat, motor force, signed work, current limits, thermal derating and latched trips | [Rig specification](RESEARCH_RIG.md) |
| Power loss | Source disconnection, declared armature dump circuit and delayed brake engagement | Complete rig audit and drive regressions |
| Instrumentation | Sampled and delayed angle, angular rate and combined axial force; quantization, seeded noise, optional sample drops and explicit sample age | Rig regressions and causal-observation audit |
| Calibration experiments | Persistent physical state, bounded actions and budgets, sealed commitment, independent motion verification and rejection | [Inquiry protocol](PHYSICAL_INQUIRY.md) |
| Physical RL | Seeded reset/step episodes, disjoint parameter cells, out-of-distribution conditions, terminal reward, abstention and report verification | [Physical RL contract](PHYSICAL_RL.md) |
| Human inspection | Assembly and mechanism views, camera presets, orbit, pan, zoom, keyboard controls, touch gestures and trace-linked overlays | Chromium and WebKit camera checks |
| Evidence workbench | Recorded/live labels, JSON and CSV export, import verification, per-side drive telemetry and an explicit investigator/evaluator boundary | Workbench contract and browser checks |

Per-side current, voltage, RPM, force and winding temperature are modeled quantities. They are shown in simulation and evaluator inspection. They are deliberately absent from the current investigator observation contract. The investigator sees its declared instruments and legal actions.

The inspection camera is a UI camera. This task does not use vision observations, camera calibration, depth images or rendered images as policy input. A future vision task needs a separate sensor model and observation contract.

## Numerical acceptance

The complete audit independently rederives the smooth mechanical, electrical, thermal and energy equations and compares them with SciPy DOP853. It does not reuse the production force or integration helpers for its reference equations. It also tests the hybrid application separately, including braking, power loss and finite extreme conditions.

The recorded audit passes 19 gates. At the default adaptive internal step, the largest smooth-reference differences are approximately 0.015213 degrees in angle, 0.002075 rad/s in angular rate, 0.018054 A in current and 0.000230°C in winding temperature. State and energy errors decrease under refinement. These are numerical regression results over the retained conditions, not hardware error bounds or a guarantee over every accepted configuration.

All four healthy reference motions pass: opening, closing, partial reversal and cold opening. The brake holds the unpowered reference. Removing the brake exposes the intended support failure. Twelve stratified extreme conditions return explicit outcomes without unhandled errors; all twelve reject the nominal calibration, including three early guard terminations. Rejection is retained as an experiment result.

The default maximum internal interval is 1 ms, shortened for stiff electrical or coupled mechanical settings. The explicit sampled PI voltage update can produce first-order trajectory error. The code and audit do not claim global second-order integration.

## Release gates

The product workflow runs these gates on the review branch:

1. Python package and regression tests on Python 3.11, 3.12 and 3.13, including an installed-wheel run away from the source directory.
2. Independent mechanical and complete-rig numerical audits.
3. Real Verifiers 0.4.0 and 0.4.1 plugin tests using scripted policy replies and actual SDK types. The strict CI environment fails if the SDK is missing.
4. Native Chromium and WebKit camera interactions, plus the complete workbench browser flow. Chromium also tests native multi-touch; WebKit multi-touch is explicitly untested because the harness cannot inject native touch there.
5. Evidence integrity, documentation links, archive contents and source hashes. Both the recorded workspace and current numerical evidence must match the model source. Rehashed reports must still satisfy trace-derived motion acceptance and the public policy-observation contract; a matching digest alone does not establish consistency.

The required result is a passing workflow for the exact reviewed commit. A previous commit's green checks do not qualify a later revision. Scripted SDK tests establish integration behavior; they do not establish that an RL policy has learned the task.

## Run it locally

Install from the repository and keep the server in the foreground:

```bash
python -m pip install -e '.[validation]'
recursivecal doctor
recursivecal serve
```

Open `http://127.0.0.1:8765/`. Ctrl+C stops the server. The workspace can also show its bundled recorded example without a backend, but creating a new experiment requires the foreground server.

For a reproducible physical episode:

```bash
recursivecal rl-schema
recursivecal rl-rollout --policy fixed --split test --seed 7 --output runs/physical-rl.json
recursivecal verify-rl runs/physical-rl.json
```

For a complete numerical check:

```bash
python scripts/validate_physics.py --output artifacts/physics-validation.json
python scripts/validate_research_rig.py --output artifacts/research-rig-validation.json
```

Existing output files require the CLI's explicit overwrite option where applicable. Reports preserve their model identifier. The older force-domain model remains available with `--rig-version 2`; historical evidence is preserved with its original provenance.

## What remains outside this release

The geometry has one rigid hinge. Independent drive forces act on that hinge, so the model cannot predict panel twisting. The ideal gear/screw transformer excludes backlash, rotor inertia, compliance and transmission efficiency losses. Latch dynamics, obstacle and pinch contact, battery chemistry, physical I/O and hardware safety controls are absent.

Before transferring a policy to a real mechanism, measure geometry and inertia, identify drive and friction coefficients, characterize the acquisition timing, then compare synchronized trajectories under held-out loads and temperatures. The [hardware protocol](HARDWARE_PROTOCOL.md) specifies the data and comparison process. A visual match or a fitted gas curve alone does not validate the full plant.

The bundled Bayesian investigator and fixed-action RL smoke rollout are development baselines. This release supplies the environment and integration contract. It does not claim a trained physical RL policy or successful transfer to hardware.
