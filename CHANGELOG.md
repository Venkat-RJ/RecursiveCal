# Changelog

## 0.5.2 - 2026-11-22

Added opt-in, source-bound deterministic physical replay for both sealed RL episodes and built-in inquiry reports. Replay reconstructs the synthetic experiment from the declared seed and recorded actions, then compares diagnostic observations, drive and motion traces, decisions, and terminal scores with the reproduced run. Existing fast verification remains available and existing core physics, reward functions and preserved evidence are unchanged.

Added real-rig tests showing that a coherently rehashed intermediate motion record can pass the fast consistency verifier but must fail source replay. The replay mode explicitly rejects mismatched core source revisions. It is not an authenticity signature, independently implemented physics check or measured-hardware validation.

Updated package license metadata to its non-deprecated SPDX form.

## 0.5.1 - 2026-11-22

Strengthened inquiry report verification and browser imports so acceptance and outcomes are checked against the recorded motion and the prescribed verification profiles. Changing a summary metric and recomputing a report digest cannot promote an unchanged failing trajectory to success.

Strengthened physical RL evidence verification to check policy observations against the public contract, diagnostic history, remaining budget and episode progression. Rehashed transcripts with undeclared evaluator fields or inconsistent observations are rejected.

Added regressions for both evidence-consistency gaps and regenerated the current source-bound rig, workspace and RL evidence. Original 0.5.0 artifacts remain addressable through their immutable source commit and the evidence-history manifest. Report verification checks recorded consistency; it does not authenticate an author or independently rerun physical trajectories.

## 0.5.0 - 2026-11-22

The physical workspace, CLI, investigator and physical RL task now run the same version 3 research rig by default. The declared healthy mechanism opens, closes, reverses and holds without power using an explicit spring-applied brake.

Added independent left and right DC drives with reciprocal motor constants, signed electrical and shaft work, winding heat, voltage and current limits, thermal derating, latched trips, a power-loss dump circuit and delayed brake engagement. Added sampled, delayed and quantized instruments, command transport delay, seeded noise, sample age and optional acquisition drops.

Added an independent coupled-equation numerical audit with refinement and energy checks, four healthy motion profiles, power-loss and zero-brake checks, and twelve retained fault conditions. The tested synthetic mechanism is explicitly specified; measured-hardware accuracy remains unestablished.

Added a physical reset/step RL task with disjoint parameter cells, bounded diagnostics, sealed commitment, terminal reward, evidence verification and a separate Verifiers plugin. Terminal actions, commitments and completion reasons must agree when reports are verified. Scripted SDK tests use real Verifiers types without calling a model; this release makes no learned-policy performance claim.

Added camera presets, orbit, pan, zoom, keyboard and touch controls, synchronized per-side drive telemetry, and native Chromium/WebKit acceptance gates. The camera is for human inspection and is not a policy observation channel.

Added installed-wheel physical RL checks, source-bound release evidence, an explicit simulator readiness record, and updated citation metadata. Historical models, reports and normalized benchmark results remain preserved.

### Shared mechanics foundation

- Both SI simulation interfaces now use the same mechanical kernel and model identifiers ending in `/2`.
- Resolve sliding stops, directional static friction, motor-lag displacement and inelastic contact within a step. Preserve incoming impact speed and post-impact elapsed time.
- Reject hinge inertia below the parallel-axis lower bound. Record power loss once at its actual boundary and acquire fixture observations at their stated timestamps.
- Add analytical regressions, independent DOP853 trajectory/contact checks, a 60-second conservative-motion audit, and a dedicated CI validation job.
- Preserve model `/1` reports with pinned source/evidence hashes; browser imports support both model versions and label archived evidence.
- These checks verify synthetic mechanics. No measured-hardware validation or new policy-performance claim is introduced.

## 0.4.0 - 2026-11-21

Connected the physical simulator, observation-only investigator, calibration controller, independent verifier and CAD workbench. The rig carries position, velocity, actuator force, time and work between tests, with an explicit charged fixture operation.

Added a finite-bank Bayesian baseline, seeded one-step information-gain estimates, commanded opening/closing confirmation, residual-based model rejection and abstention. Added fixed-test and nominal-controller comparisons. This is a physical engineering foundation, not an RL superiority claim.

Added the `inquire` and `verify-inquiry` foreground commands, bounded synchronous HTTP operations, full evidence reports, browser-compatible integrity digests, trace-derived metric verification and authored CAD playback. Added mechanical, information-boundary and browser acceptance tests.

Retained the frozen normalized benchmark, original SI equations, v0.3 evidence and manuscript. All new fixture data remains synthetic; physical validation and sufficient unpowered support remain explicit requirements.

## 0.3.0 - 2026-11-21

Added an installable local research workbench with a foreground CLI and HTTP API, strict input contracts, simulation and trace export, experiment artifact verification, and packaged offline assets.

Added a separate SI liftgate model with explicit mount geometry, force lag, Coulomb friction and stiction, gas-force and temperature assumptions, hard stops, power-loss and passive-hold cases, exact final duration, and recorded limit events. The model defaults remain synthetic and expose the known passive-support failure.

Added measured/synthetic CSV provenance, force-curve fitting on explicit train rows with separate validation, parameter mapping within the observed support, and trajectory replay comparisons. No hardware measurements were acquired for this release.

Added a reproducible NumPy contextual-bandit suite, validation-selected fixed diagnostics, adaptive Bayesian controls, matched action-frequency shuffles, mismatch-triggered abstention, parameter and structural shift stress cases, checkpoints, raw trial tables, and uncertainty estimates.

Fixed the historical mismatch-check imports, NumPy compatibility, exact-duration abort accounting, package-aware research imports, and inaccurate preregistration language. Historical scores and frozen benchmark equations are retained.

Added clean wheel tests, supported NumPy/Python CI, real browser acceptance checks, source-bound evidence verification, contribution and security notes, a citation file, source/data provenance, and a manuscript with generated figures.

## 0.2.0

Normalized synthetic actuator benchmark, classical Bayesian identification, small CPU neural pilot, Verifiers adapter, and separate CAD/visual demos. The original neural pilot selected a fixed probe; its performance is not evidence of adaptive diagnostic selection. Historical reports remain available.

