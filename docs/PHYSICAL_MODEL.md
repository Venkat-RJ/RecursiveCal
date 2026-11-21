# SI liftgate model

`recursivecal_lab.physics` supplies a usable single-axis software-in-the-loop model. Its identifier is `recursivecal.si-liftgate/1`. It is separate from the frozen normalized v0.2 reinforcement-learning benchmark. Scores from those two systems are not interchangeable.

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

`J` is in kg m², forces in N per strut, torques in Nm, and lengths in metres. Positive external closing torque opposes opening.

Gas force is a linear interpolation between compressed and extended force ratings in the **length** coordinate. It is multiplied by the configured gas-force scale and `(temperature_C+273.15)/(reference_temperature_C+273.15)`. This fixed ideal-gas temperature multiplier omits seal behavior, friction hysteresis, and transient thermal dynamics. It is an explicit approximation, not a fitted thermal law.

The motor force follows `dF_m/dt=(F_request*efficiency-F_m)/tau` with bounded requested force. The first-order response is integrated analytically within each step. A positive force extends the strut, a negative force retracts it. This is a force-domain actuator abstraction. There is no electrical circuit, battery-energy, or current prediction.

The hinge uses Coulomb friction, a static holding threshold, and viscous damping. At zero speed, net torque below static-friction capacity is balanced. During motion, a dissipative velocity projection applies kinetic friction and implicit viscous damping. A configured holding brake contributes torque capacity only while the motor is unpowered. Its default is zero. The model does not invent a brake to hide a passive-hold failure.

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

Motor response is analytic within a step. Geometry and external torque are evaluated at a predicted midpoint. Velocity uses the friction projection, and position uses the average of old and new velocity. With damping and switching the overall method is generally first order. In the frictionless, contact-free energy test, refinement gives the expected faster convergence. No blanket fourth-order claim is made.

The final step is shortened to the requested duration. The integrator also stops a step exactly at a power-loss boundary. The last reported timestamp is the actual completed time, including early termination. Repeated runs with the same inputs and seed are deterministic in the same Python environment.

Lower and upper mechanical stops project position into range and set velocity to zero. This is an inelastic contact approximation, not a contact-force or anti-pinch model. Stop events record the incident speed. `unconstrained_torque_Nm` excludes the impulsive stop reaction and must not be interpreted as a load-cell measurement during contact.

Speed is checked at each recorded state. With `abort_on_limit=True`, exceeding the configured threshold terminates the simulation and records `aborted_speed_limit`. A step can cross the threshold before detection. This monitor is an experiment guard, not a continuous-time safety guarantee or physical emergency-stop system. Force saturation is reported as the fraction of completed time, not hidden as a successful calibration.

`mechanical_work_signed_J` approximates total motor work `integral 2 F_m L'(q) dq`. `mechanical_work_abs_J` sums its absolute incremental magnitude. Neither includes electrical losses or predicts battery consumption.

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

The published machine-readable evidence is in `research/releases/physical-v1/`. After installing the package, regenerate it with:

```bash
python research/releases/physical-v1/reproduce.py
```

The script emits twelve explicit software gates, their observed values, and their criteria. It writes a diagnostic audit and exits with an error if any gate fails. The criteria are regression tolerances chosen during software development, not independently preregistered physical accuracy limits. One gate deliberately requires the default unsupported hatch to fail passive hold. Passing the software audit therefore does not mean that the default mechanical architecture is adequate.

## Independent physical reference

The NHTSA report *Engineering Analysis EA06-020: Toyota Sienna Power Liftgates*, June 2008, describes a particular vehicle whose motor disengages at full opening and whose gas struts then support the liftgate. It documents strut-related unexpected closing. This motivates testing the unpowered hold condition for that architecture. Its measurements are **not transferred** to RecursiveCal's different CAD mounts or used as fitting labels.

Source: <https://static.nhtsa.gov/odi/inv/2006/INCR-EA06020-29305P.pdf>, especially the system-description and testing sections. This source does not establish a universal gas-only holding requirement for mechanisms with a brake, latch, or self-locking transmission.

## Boundaries for a paper

Suitable claims are that this implementation provides a versioned synthetic mechanism, explicit failure conditions, numerical verification, and an executable route to fit and compare measured data. Real hardware accuracy, anti-pinch performance, certification, and transfer of the normalized RL policy to this SI model have not been demonstrated. Structural omissions include flexible bodies, backlash, multi-axis coupling, detailed motor electronics, thermal dynamics, latch behavior, obstacle contact, and physical I/O timing.
