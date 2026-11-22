# The declared research rig

Version 3 is a synthetic, dimensioned mechanism for investigating physical faults. Its identifier is `recursivecal.physical-rig/3`; its specification is `recursivecal.research-rig-spec/1`. It retains the same rigid-body equations as physics 2 and adds electrical drives, thermal state and an acquisition pipeline. Version 2 reports retain their original model identifier and equations.

This specification is the model we implement and test. Its numbers are assumptions, not measurements of a production actuator. Passing the numerical and experiment checks does not establish hardware accuracy.

## Healthy reference mechanism

The reference is the authored 78-degree, one-hinge liftgate with a 25 kg moving body, two powered struts, gas assistance and an explicitly modeled spring-applied holding brake. The brake contributes 120 N·m of static or sliding resistance while engaged. It releases when powered operation begins and engages 20 ms after supply loss or a drive-protection trip. A trip disconnects both drives and remains latched for that rig instance.

At 78 degrees and 20°C, nominal gravity closes the hatch with approximately 134.60 N·m and gas assistance opens it with approximately 68.85 N·m. Including 8 N·m of hinge stiction and the 120 N·m brake leaves approximately 62.25 N·m of static holding margin in this model. The brake is part of the declared architecture. It is not a calibration estimate and is not proof that a real brake has this capacity.

`DriveParameters.brake_capacity_Nm=0` explicitly selects the unsupported unpowered mechanism used as a negative test. A legacy `ModelParameters.holding_brake_Nm` value does not silently override the version 3 architecture; drive configuration owns that choice.

## Independent electrical drives

Each side retains its own current, current-controller integrator, winding temperature, terminal voltage, magnetic energy, copper loss, dump-resistor loss and signed electrical and shaft work. The two struts act on the same rigid hinge. Different left/right drive effectiveness can therefore change net torque, but it cannot bend or twist the panel in this model.

The armature equations are

\[
L_e \dot I = V - R(T)I - K_e\omega_m,
\qquad \tau_m=K_t I,
\qquad K_e=K_t
\]

in consistent SI units. With gear ratio `G`, screw lead `p` in metres per revolution and strut length `l`, the ideal kinematic transformer is

\[
k=2\pi G/p,\qquad
\omega_m=k\dot l,\qquad
\theta_m=k(l-l_{closed}),\qquad
F_m=k\tau_m.
\]

Using the same transform for force and speed preserves power: `tau_m * omega_m = F_m * dl/dt`. The existing axial damping and hinge friction provide explicit mechanical dissipation. No direction-dependent efficiency multiplier is applied to regenerative motion.

The legacy calibration field `motor_efficiency` is a **motor effectiveness multiplier** in version 3. It scales both `Kt` and `Ke`, preserving their reciprocal relationship. It is not an energetic efficiency. `side_effectiveness=(left,right)` supplies additional evaluator-defined asymmetry. The nominal force request is converted to a current request using the nominal motor constant, so the controller does not receive the faulted constant.

The default drive uses a 12 V supply, 0.7 ohm armature resistance at 20°C, 6 mH inductance, a 0.015 N·m/A torque constant, an 8:1 gear ratio and a 12 mm screw lead. The force request is bounded by the experiment's 330 N per-strut command limit. A 9 A current regulator and supply voltage constrain the electrical response. Actual transient force follows current; it is not clipped to the requested force after integration.

The inner PI current regulator is an ideal continuous control law approximated by explicit voltage holds at the internal integration steps. It has no claimed hardware PWM frequency. Voltage saturation uses anti-windup. The current limiter changes applied voltage using the exact local electrical response; it does not discard stored inductor energy by clipping current. A physically infeasible powered current bound latches a drive trip.

The source is explicitly bidirectional and can absorb regenerative electrical energy. On power loss the source disconnects and each armature recirculates through a declared 3 ohm dump resistor in addition to winding resistance. That circuit can generate braking torque while the spring brake engages. This is an assumed drive architecture, not a battery or ECU model.

## Temperature and energy

Winding resistance depends on winding temperature. Copper loss heats a lumped winding thermal capacity, and a thermal resistance connects that winding to the declared ambient temperature. The current allowance decreases above 80°C and reaches zero at the 110°C trip threshold. Dump-resistor energy is tracked separately and is not assigned to the winding.

Every electrical interval retains the signed identity

\[
E_{terminal}=E_{copper}+E_{dump}+W_{shaft}+\Delta E_{inductor}.
\]

Negative terminal energy denotes regeneration. Electrical energy is not presented as battery energy consumption or state of charge.

The mechanical kernel integrates motor work and dissipation. `coupling_residual_J` reports the accumulated difference between electrically integrated shaft work and mechanically integrated motor work. This residual is numerical error and remains visible; it is not silently classified as loss. The audit checks its size and refinement.

## Instrument and command timing

The default angle, angular-rate and axial load-cell instruments sample every 10 ms, with 10 ms delivery latency. Force commands have 10 ms transport delay. Acquisition and command boundaries split integration steps exactly.

Angle resolution is 0.0005 rad, angular-rate resolution is 0.002 rad/s, and force resolution is 0.25 N. Seeded Gaussian noise is applied at acquisition, before quantization. Repeated observation reads return the same held sample and cannot obtain new independent noise draws. Optional seeded sample drops leave the last delivered measurement in place.

Both the controller and investigator receive the same acquisition. `noisy=False` removes stochastic noise for prediction and numerical checks but retains sampling, latency and quantization. It does not expose current simulator state. The observation includes the read time, `sensor_sample_time_s`, and `sensor_age_s` so held or delayed data are explicit.

Reset supplies one labelled initial acquisition with normal bias, noise and quantization. Subsequent acquisitions incur the declared latency. This is initialization of an episode, not a claim to reconstruct unobserved motion before reset.

The controller and investigator currently use angle, rate and combined axial strut-force observations. Per-side current, voltage, rotor speed, temperature and true force belong to evaluator/inspection telemetry. Giving an agent those additional channels requires an explicit observation-contract version.

## Numerical scope

The mechanical kernel remains `physics.advance_mechanics`. A symmetric split integrates an exact electrical half-interval, advances the mechanical kernel using the midpoint mean motor force, then integrates the remaining electrical half-interval using the new shaft speed. Resistance and shaft speed are frozen locally for each electrical interval. Thermal state uses the interval's integrated copper heat.

The default maximum internal interval is 1 ms. It is shortened further according to electrical/current-loop rates and the coupling between both drives and the hinge:

\[
h \le \min\left(h_{requested},
\frac{0.2}{\max\left((R+K_p)/L_e,\sqrt{K_i/L_e},\omega_{coupled}\right)}\right).
\]

The coupled frequency uses both motor constants, the gear/screw transform, the maximum moment arm over the declared travel and the hinge inertia. This prevents accepted high-ratio or high-gain configurations from silently using the default interval. `metadata()` records the current effective bound and rule.

Exact local electrical integration does not make the entire coupled system exact. The explicit PI approximation can produce first-order trajectory error. Coupling-energy error is measured separately under refinement; no global second-order claim is made. Smooth independent-reference checks exclude switching, contact and saturation, which have separate regressions and outcome cases.

## Supported task and deliberate exclusions

The supplied task varies mass, motor effectiveness, gas assistance, hinge friction and encoder bias. The plant also accepts declared drive, sensor and per-side fault settings for separate robustness studies. The supported geometry is the authored mechanism. Configuration bounds reject unsupported dimensions and malformed inputs, but those bounds are not hardware operating limits or a promise that every allowed combination completes a motion.

The external reference fixture remains a declared bench operation. Repositioning and its work lie outside the plant model. It preserves elapsed time, winding heat and energy history, dissipates stored armature energy into the declared dump path, and acquires subsequent observations through the normal sensor pipeline.

The following effects are deliberately outside this version: gearbox/screw backlash, rotor inertia, panel compliance or torsion, obstacle and pinch contact, latch dynamics, battery chemistry and physical I/O. Current, RPM and winding heat are now modeled; those exclusions are not hidden behind the rendered assembly.

Before a claim of physical accuracy, obtain measured geometry/inertia, drive constants, friction, synchronized instrument traces and held-out conditions using [the hardware protocol](HARDWARE_PROTOCOL.md). The synthetic environment can be ready for a declared learning task while that empirical validation remains open.
