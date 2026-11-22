# Verify the environment before evaluating the investigator

This record covers the shared version 2 rigid-body kernel. The [research-rig readiness record](SIMULATOR_READINESS.md) and [version 3 audit](../research/releases/research-rig-v3/validation.json) add coupled DC-drive comparisons, sensor timing, brake behavior and physical RL checks. Measured-hardware validation remains open.

The current milestone is a trustworthy, inspectable simulator of a declared mechanism. A policy score is useful only after the environment's equations, numerical behaviour and observation contract are understood.

This work updates the SI model to `recursivecal.si-liftgate/2` and the persistent rig to `recursivecal.physical-rig/2`. Both call `advance_mechanics()` in `recursivecal_lab/physics.py`. The earlier normalized RL benchmark remains a different model. The Bayesian investigator is an integration check here; no new policy-performance claim is made.

## What changed

The previous velocity projection could reverse a slowly moving hatch through zero even when the opposing torque was below static friction. Fixing only its final velocity would still leave the wrong stopping distance. The new local flow integrates both displacement and velocity, reapplies static friction at a stop, and selects closing friction from the subsequent sliding direction.

The earlier standalone simulator could reset velocity at a mechanical stop before recording a speed violation. It also called the unconstrained end-of-step velocity the impact speed. Contacts are now localized within the local flow, with incoming speed and kinetic-energy loss recorded before projection. The remaining interval is integrated, including possible inward release from a stop.

A further independent review exposed a less obvious failure: using the motor's average force over a whole step to reconstruct an earlier contact lets later force changes alter the estimated collision. For a 1 ms motor time constant, one example incorrectly moved an impact below the 0.12 rad/s rejection threshold; another missed contact. The kernel now retains the exponential motor force in the velocity and displacement solution. Its displacement includes the first time moment of force, not just its mean.

Mass, centre-of-mass radius and hinge inertia must obey the parallel-axis lower bound, `J >= m*r*r`. Power-loss events occur once at their actual scheduled boundary, including time zero and events very close to observation boundaries. Fixture observations are acquired at their recorded times during an explicitly stationary fixture interval.

## Evidence and acceptance

| Layer | Evidence | Status and scope |
| --- | --- | --- |
| Geometric identities | Analytic moment arm versus numerical derivative; force/extension virtual work; potential-energy gradients | Checked for the declared single-axis geometry. |
| Analytical mechanics | Stopping time and distance, reversal, directional stiction, damping limits, constant-acceleration impacts, contact release, actuator breakaway, shared-interface trajectories | Covered by the mechanics test suite. |
| Independent smooth solver | 24 parameter sets, five force-command intervals each, four step sizes, separately expressed geometry and forces, SciPy DOP853 | Passed the stored engineering tolerances. Dry friction and contact are excluded from this error envelope. |
| Motor-dependent contact | Three independent DOP853 event comparisons covering false contact, missed contact and an incorrectly classified impact | Contact classifications agree. Stored time/speed tolerances are 20 microseconds and 0.0002 rad/s for these cases. |
| Long conservative motion | 60-second interior pendulum motion, three step sizes, independent trajectory, energy and phase checks | Passed; both trajectory and energy errors decrease under refinement. |
| Experiment contract | Persistent state, sensor-only observations, fixture timing, exact acquisition boundaries and sealed commitment | Checked by the existing inquiry suite and new timing regressions. |
| Measured physical accuracy | Matched mechanism, measured forces, inertia, timing and held-out trajectories | Not established. No measured hardware data were used in these checks. |

The complete numerical record is [validation.json](../research/releases/physics-v2/validation.json). It contains all parameters and reference states, rather than only aggregate claims. CI reruns the numerical audit and checks that stored evidence hashes match the current source.

For the recorded 24-case smooth sample:

| Simulation step | Largest angle difference | Largest velocity difference |
| --- | ---: | ---: |
| 20 ms | 0.004314 degrees | 0.00036894 rad/s |
| 10 ms | 0.001080 degrees | 0.00009235 rad/s |
| 5 ms | 0.000270 degrees | 0.00002309 rad/s |
| 2.5 ms | 0.00006750 degrees | 0.000005774 rad/s |

At 10 ms, the separate 60-second oscillation had a maximum angle difference of 0.2115 degrees and a relative energy excursion of about `9.33e-7`, measured against the initial oscillation energy above equilibrium. The angle difference includes accumulated phase error. Halving the step reduced both errors by about four times. A good short trajectory comparison does not imply zero long-term phase drift.

These numbers describe this parameter sample and these commands. They are not worst-case bounds across all inputs accepted by the API. The tolerances are engineering regression criteria chosen during development, not preregistered physical accuracy requirements.

## What the numerical model still assumes

The hatch is one rigid rotational body. The two struts are identical, their mounting geometry is known, and the actuator is a bounded force source with first-order lag. Gas assistance is a linear force/length curve with an ideal-gas temperature multiplier. Friction has declared static, kinetic and viscous terms. These assumptions can be mathematically consistent and still fail to describe a particular real mechanism.

Nonlinear geometry and passive forces are approximated at an iterated midpoint. Local sliding solutions retain motor dynamics, but this remains a finite-step numerical method. Contact is perfectly inelastic and rigid. The model does not predict impact force, panel compliance, pinch force or obstacle contact. Speed-limit termination occurs at the end of the accepted control interval; it is not an exactly localized hardware shutdown. A numerical convergence failure is rejected rather than silently accepted.

The fixture performs externally supplied repositioning and then holds a known pose. Its repositioning motion and work are outside the plant model. Observation noise is synthetic. The persistent rig's control signal is an explicitly ideal filtered angle/rate measurement, distinct from noisy logged instrumentation. Current draw, battery voltage, gearbox backlash, latch behaviour, ECU timing and thermal evolution remain outside the model.

The default liftgate still fails the unpowered support calculation. Its assumed gas assistance and static friction leave roughly 57.75 Nm of additional holding capacity required at full opening. Adding a brake would change the modeled architecture and must remain an explicit parameter choice.

## What must happen before a real-system claim

1. Identify one actual mechanism and record its geometry, moving mass, centre of mass and hinge inertia with uncertainty. Do not transplant force measurements from another vehicle without matching the mechanical arrangement.
2. Acquire synchronized angle/rate, total strut force, command and temperature measurements. Record calibration, sampling, filtering and units. Motor-current or voltage claims require the corresponding electrical measurements and model.
3. Fit a declared subset of parameters using training trajectories. Keep uncertainty, correlations and alternate explanations visible; one fitted force curve does not identify the entire plant.
4. Validate on complete trajectories, directions, loads and temperatures excluded from fitting. Fix acceptable errors before evaluating those held-out records. Compare time histories and event timing, not only an aggregate score.
5. Define a supported operating envelope from that evidence. Investigative policies can then be evaluated within it, with explicit cases outside the model that should trigger abstention or model revision.

The existing [measurement contract](DATA_CONTRACT.md) and [hardware protocol](HARDWARE_PROTOCOL.md) describe the data and experiment interfaces. The lack of measured validation remains an open gate, not a status that software tests can change.

## Historical evidence

Archived `physical-v1` and `physical-inquiry-v1` results belong to source revision `8d51692799b1eaffb18c3f91def12fac44a1b8af`. Their source and artifact hashes are pinned in [historical-evidence.json](../research/releases/physics-v2/historical-evidence.json). The browser can read both model versions and labels recorded physics 1 evidence. New runs state their model identifier and current source hashes. Historical investigator results have not been relabelled as evaluations of physics 2.

## Numerical references

- [Drake: Modeling of Dry Friction](https://drake.mit.edu/doxygen_cxx/group__friction__model.html), for the distinction between static/kinetic friction and numerical approximations.
- [Drake: Continuous Models for Simulation](https://drake.mit.edu/doxygen_cxx/group__mbp__continuous.html), for stick/slip resolution and time-step limitations.
- [SciPy solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html), for DOP853 tolerances and event-root semantics.

These references inform the verification method. They do not validate RecursiveCal's chosen physical parameters.
