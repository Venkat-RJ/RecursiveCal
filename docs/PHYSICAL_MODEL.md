# SI liftgate model

`recursivecal_lab.physics` supplies a single-axis software-in-the-loop model. Its current identifier is `recursivecal.si-liftgate/2`. The persistent rig calls the same mechanical kernel. Archived `/1` results remain tied to their original source revision; the frozen normalized benchmark is another separate model. Scores across these definitions are not interchangeable. See the [physics validation record](PHYSICS_VALIDATION.md).

The included geometry follows the repository's illustrative CAD mounts. Mass, inertia, force ratings, friction, actuator response, and controller settings are assumptions. No production-vehicle identification data have been supplied. The model is therefore a research instrument, not a validated digital twin or a hardware controller.

## Equations and units

The hinge angle `q` is measured in radians from the closed position. Opening is positive. The local hatch anchor `(x_h, -d_h)` rotates about the hinge. Its body-frame coordinates are

\[
x(q)=x_h\cos q+d_h\sin q,\qquad
z(q)=z_{hinge}+x_h\sin q-d_h\cos q.
\]

For fixed body mount `(x_b,z_b)`, the strut length is `L(q)=sqrt((x-x_b)^2+(z-z_b)^2)`. The signed moment arm is the analytic derivative `dL/dq`. Two identical struts generate total opening torque `2 F dL/dq`. Geometry validation rejects coincident anchors and arms below 0.01 m across the configured motion range.

The rotational equation is

\[
J\ddot q=2(F_m+F_g)L'(q)-mg r_c\sin(q+q_c)-\tau_{ext}
 -\tau_{friction}-2c_s[L'(q)]^2\dot q.
\]

`J` is in kg m², forces in N per strut, torques in Nm, and lengths in metres. Positive external closing torque opposes opening. The parallel-axis constraint requires `J >= mass_kg * com_radius_m**2`; configurations that violate it are rejected.

Gas force is a linear interpolation between compressed and extended force ratings in the **length** coordinate. It is multiplied by the configured gas-force scale and `(temperature_C+273.15)/(reference_temperature_C+273.15)`. This fixed ideal-gas temperature multiplier omits seal behavior, friction hysteresis, and transient thermal dynamics. It is an explicit approximation, not a fitted thermal law.

The motor force follows `dF_m/dt=(F_request*efficiency-F_m)/tau` with bounded requested force. The first-order response is integrated analytically within each step. A positive force extends the strut, a negative force retracts it. This is a force-domain actuator abstraction. There is no electrical circuit, battery-energy, or current prediction.

The hinge uses Coulomb friction, a static holding threshold, and viscous damping. At zero speed, torque within the directional static-friction capacity is balanced. A sliding interval ends at its actual zero-velocity time; static friction is reapplied before any reversal. Both velocity and displacement are integrated. The persistent rig can add a separate closing-direction friction term. A configured holding brake contributes capacity only while unpowered. Its default is zero.

## Controller and scenarios

The default controller uses a quintic position reference, proportional/derivative feedback, and nominal feedforward. Sensor bias and seeded Gaussian angle noise can be added. The feedforward parameter set remains nominal when the simulated plant is faulted. Passing `controller_parameters` is the explicit way to supply an identified model. Velocity is assumed available without noise; no observer or velocity-estimation performance is claimed.

| Scenario | Initial condition and behavior |
| --- | --- |
| `open` | Starts closed, opens over the configured reference duration, then holds under active control. |
| `close` | Starts open and follows the reverse reference. |
| `passive_hold` | Starts open with the motor disengaged. Tests gas support, hinge stiction, and any explicit brake. |
| `power_loss` | Opens under control, then disables motor demand at the specified loss time. Residual force decays through the actuator model. |

The default hatch needs approximately 65.75 Nm of support in addition to its modeled gas torque at 78 degrees. The 8 Nm static-friction assumption leaves approximately 57.75 Nm of additional holding capacity required. The default passive-hold run falls and reaches the simulation's speed limit. Adding a 70 Nm brake changes that **modeled architecture** and holds the hatch. This is a conditional design calculation, not evidence that such a brake exists on a real mechanism.

The separate historical CAD model uses `g=9.81`; this model uses `g=9.80665`. Its results therefore differ slightly even at the same geometry and nominal loads. The original physical requirement audit remains unchanged for traceability.

## Numerical method and events

Geometry, gas/gravity torque and the viscous coefficient use an iterated position midpoint. Within that local approximation, the motor force retains its exponential time dependence in velocity, displacement and motor work. Sliding intervals use an analytic linear-ODE flow. Zero-velocity transitions and static release split that flow, including the remaining time after a reversal. This avoids applying a whole-step average motor force to motion that occurred earlier in the step. Smooth-case refinement is checked against an independent solver; it is not a global error bound for every hybrid trajectory.

The final step is shortened to the requested duration. The integrator also stops a step exactly at a power-loss boundary. The last reported timestamp is the actual completed time, including early termination. Repeated runs with the same inputs and seed are deterministic in the same Python environment.

Lower and upper stops localize contact within the local trajectory, set velocity to zero inelastically, record incoming speed and kinetic-energy loss, and integrate the remaining interval. A resting stop supplies unilateral reaction while motor force continues to evolve; sufficient inward force can release it. This remains an idealized rigid-contact approximation. Contact force, elastic deformation and anti-pinch behaviour are not modeled. `unconstrained_torque_Nm` excludes the stop reaction.

Speed monitoring includes local velocity extrema and incoming contact speeds, before the stop resets velocity. With `abort_on_limit=True`, a breach records `aborted_speed_limit`. Termination takes effect at the outer control-step boundary, rather than at an exactly localized speed-threshold crossing. This is an experiment guard, not a hardware emergency stop. Force saturation is reported as a fraction of completed time.

`mechanical_work_signed_J` approximates total motor work `integral 2 F_m L'(q) dq`, retaining the motor's time dependence in each locally frozen geometry. Absolute work accounts for force and motion reversals. Separate friction and impact dissipation fields are provided. `mechanical_energy()` includes kinetic, gravitational, external-load and assumed gas-spring potential energy. These are quantities of the numerical model; none predicts electrical losses or battery consumption.

## Python interface

```python
from recursivecal_lab.physics import ModelParameters, simulate, passive_hold
from recursivecal_lab.measurements import export_trace_csv

run = simulate(
    {"mass_kg": 29, "motor_efficiency": 0.7},
    scenario="open", duration_s=6.5, dt_s=0.01, seed=10,
)
print(run["metrics"])
export_trace_csv(run, "outputs/open_trace.csv")
print(passive_hold(ModelParameters()))
```

The JSON trace is `recursivecal.run/1`; all values are finite JSON values. `parameter_schema()` returns form-friendly defaults, unit names, and descriptions. Parameters reject nonfinite values, unknown keys, invalid geometry, and unsupported numerical ranges. These input bounds are computational checks, not a validated hardware operating envelope.

## What is verified

The test suite checks the mount derivative, virtual-work identity, conservative energy refinement before contact, trajectory convergence, reproducibility, exact duration, power-loss event timing, force bounds, invalid-input rejection, and passive hold with and without an explicit brake. Those are software and numerical checks. They cannot establish the accuracy of assumed coefficients.

Current machine-readable numerical evidence is in `research/releases/physics-v2/validation.json`. Reproduce the current checks in the foreground with:

```bash
python -m pip install -e '.[validation]'
python -m unittest discover -s tests -p 'test_mechanics_foundation_v2.py' -v
python scripts/validate_physics.py --output artifacts/physics-validation.json
```

The current audit evaluates 24 smooth mechanisms, three motor-reversal contact cases and 60 seconds of conservative oscillation. Its criteria are engineering regression tolerances, not independently preregistered hardware accuracy limits. Archived `physical-v1/` and `physical-inquiry-v1/` reports remain historical evidence for source revision `8d51692799b1eaffb18c3f91def12fac44a1b8af`. Reproduce those reports from that revision. Their source and evidence hashes are pinned in `physics-v2/historical-evidence.json`; the current audit separately checks the current source hashes.

## Independent physical reference

The NHTSA report *Engineering Analysis EA06-020: Toyota Sienna Power Liftgates*, June 2008, describes a particular vehicle whose motor disengages at full opening and whose gas struts then support the liftgate. It documents strut-related unexpected closing. This motivates testing the unpowered hold condition for that architecture. Its measurements are **not transferred** to RecursiveCal's different CAD mounts or used as fitting labels.

Source: <https://static.nhtsa.gov/odi/inv/2006/INCR-EA06020-29305P.pdf>, especially the system-description and testing sections. This source does not establish a universal gas-only holding requirement for mechanisms with a brake, latch, or self-locking transmission.

## Boundaries for a paper

Suitable claims are that this implementation provides a versioned synthetic mechanism, explicit failure conditions, numerical verification, and an executable route to fit and compare measured data. Real hardware accuracy, anti-pinch performance, certification, and transfer of the normalized RL policy to this SI model have not been demonstrated. Structural omissions include flexible bodies, backlash, multi-axis coupling, detailed motor electronics, thermal dynamics, latch behavior, obstacle contact, and physical I/O timing.
