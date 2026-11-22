# Data import, fitting, and comparison

The data path is executable from CSV through a fitted force curve and an SI simulation. Every import records the CSV SHA-256 and declared source metadata. Included examples are synthetic and remain labeled that way.

## Report versions and signal origin

The envelope schema and the physical model version are separate. A stable JSON envelope does not make different model versions interchangeable.

| Artifact | Envelope or task identifier | Physical version and intended use |
| --- | --- | --- |
| SI simulation | `recursivecal.run/1` | Inspect `model_id`: `recursivecal.si-liftgate/1`, `/2` or `/3`. Version 3 uses the electrical research rig. |
| Physical investigation | `recursivecal.physical-inquiry/1` | Inspect `model_id`: `recursivecal.physical-rig/1`, `/2` or `/3`. The report contains both public observations and separately sealed evaluator evidence. |
| Public inquiry observation | `recursivecal.agent-observation/1` | Its `model_id` identifies the plant. Version 3 adds instrument acquisition age and timing. |
| Physical RL episode | `recursivecal.physical-rl-episode/1` | `task.task_id` is `recursivecal.physical-calibration-rl/1`, and `task.model_id` is `recursivecal.physical-rig/3`. |

Historical version 1 and 2 reports retain their original source hashes, model IDs and recorded evidence. Do not relabel them as version 3 results. Missing electrical or acquisition fields in older reports mean unavailable, not zero.

New simulation and inquiry CLI requests default to version 3. Use `--rig-version 2` to reproduce the force-domain model. The Python `recursivecal_lab.physics.simulate` examples below explicitly use version 2; the version 3 entry point is `recursivecal_lab.research_simulation.simulate`.

### Measured channels and simulator truth

Field names depend on the artifact context:

| Signal | SI simulation trace, including version 3 | Investigation diagnostic or verifier trace |
| --- | --- | --- |
| True hinge angle | `angle_rad` | `true_angle_rad`, evaluator only |
| Instrument angle | `observed_angle_rad` | `angle_rad` |
| True angular rate | `velocity_rad_s` | `true_velocity_rad_s`, evaluator only |
| Instrument angular rate | `observed_velocity_rad_s` in version 3 | `velocity_rad_s` |
| Instrument axial force | `strut_force_N_each` when present | `strut_force_N_each` |
| Modeled motor force | `motor_force_N_each` | `true_motor_force_N_each`, evaluator only |

All angles are radians and angular rates are radians per second. An angle sensor bias must remain visible in the observed channel; it must not be replaced by the rendered pose or a `true_*` field during CSV export or policy observation construction.

The public force channel is total axial force expressed per strut: mean motor force plus the assumed gas force minus axial damping. Under unequal left/right drive behavior, it is an aggregate expressed per strut, not two independent load-cell readings. The per-side `left_force_N` and `right_force_N` telemetry described below represent motor force only. They do not include gas assistance or damping and are not supplied to the current investigator.

### Time and acquisition

Version 3 uses sampled, quantized instruments with declared delivery latency. Repeated reads of the same held sample do not create new noise draws.

| Field | Meaning |
| --- | --- |
| Trace `time_s` | Elapsed time relative to the current motion or diagnostic. |
| Trace `absolute_time_s` | Persistent rig time, which continues across diagnostics. |
| Public measurement `time_s` | Persistent rig time when the held measurement is read. |
| Snapshot `sample_time_s` | Scheduled instrumentation query time relative to its diagnostic. |
| `sensor_sample_time_s` | Persistent rig time when the underlying instrument sample was acquired. |
| `sensor_age_s` | Read time minus underlying acquisition time. Held or delayed observations have positive age. |

The snapshot query can return an older instrument sample. Its query time must not be mistaken for a fresh physical acquisition. Agent likelihood inputs use the declared acquired snapshots; the denser diagnostic trace is retained for inspection and audit. Browser interpolation makes replay continuous but does not create additional sensor observations or advance the engine.

### Version 3 electrical and protection telemetry

Simulation and evaluator traces can contain the following fields with a `left_` or `right_` prefix:

| Suffix | Units and interpretation |
| --- | --- |
| `current_A`, `voltage_V` | Signed armature current and applied terminal voltage. |
| `motor_speed_rad_s`, `rotor_angle_rad` | Shaft speed and angle derived from the ideal gear/screw constraint. Rotor angle is relative to the closed length. These are not independent rotor-inertia states. |
| `temperature_C` | Modeled winding temperature, distinct from ambient temperature. |
| `force_N` | That side's motor-generated axial force. |
| `supply_power_W`, `electrical_energy_J` | Signed electrical power and accumulated terminal energy. Negative energy represents regeneration into the declared bidirectional source. |
| `copper_loss_J`, `dump_loss_J` | Accumulated winding and dump-resistor dissipation. |
| `shaft_work_J` | Signed accumulated electrical-model shaft work. |
| `inductive_energy_J`, `initial_inductive_energy_J` | Present and initial stored armature magnetic energy. |
| `drive_saturated`, `drive_tripped` | Drive saturation state and latched protection state. |

The two shaft speeds follow the same rigid hinge kinematics; separate current and temperature states do not imply panel twist or two independent mechanical degrees of freedom.

Global telemetry includes `brake_engaged`, `dropped_sensor_samples`, `axial_dissipation_J` and `coupling_residual_J`. The coupling residual is the difference between electrically integrated shaft work and mechanically integrated motor work. It remains numerical error rather than being relabeled as physical loss.

`force_saturated` on a completed trace row records saturation over the preceding control interval. Aggregate saturation metrics are weighted by interval duration. `motor_powered` is false after supply loss, disabled operation or a latched drive trip; residual armature current and dissipative braking can still exist while unpowered.

The report's `rig_specification` retains drive and sensor configuration, side-effectiveness settings, the brake architecture, numerical step rule and supported scope. Electrical energy is not a battery state-of-charge measurement. These channels remain synthetic even when some mechanical coefficients came from declared measured data.

## Force measurements

```csv
length_m,force_N_each,temperature_C,split
0.57,211.2,20,train
0.65,199.1,20,train
0.82,175.3,20,train
0.94,164.9,20,train
0.61,205.8,20,validation
0.75,184.1,20,validation
```

These rows are schematic values only. Use the bundled `synthetic_force.csv` for a runnable example covering the default geometry.

Required columns are `length_m`, `force_N_each`, and `split`. `temperature_C` is optional. Force is the axial gas-spring force of **one** strut, not combined force or hinge torque. Length is the absolute pin-to-pin length, not stroke. Missing values, unknown headers, duplicate headers, nonfinite values, nonpositive lengths, and negative gas forces are rejected. The parser does not silently convert pounds-force, millimetres, or degrees.

At least three `train` and two `validation` rows are required. Only training rows determine the fit. Training length variation must identify a slope. Exact duplicate measurements appearing in both splits are rejected. The software cannot prove that the supplied split is independent. For actual measurements, define the split before fitting, ideally by acquisition run or hardware unit so adjacent samples from one run do not appear on both sides.

Put metadata beside the CSV using the same base name plus `.metadata.json`, or pass it explicitly:

```json
{
  "source_kind": "measured",
  "source": "Describe the rig, specimen, acquisition procedure, and date",
  "units": {
    "length_m": "m",
    "force_N_each": "N",
    "temperature_C": "degC"
  },
  "instrument": "Document load-cell and displacement-sensor calibration",
  "split_definition": "State which acquisition runs were held out",
  "license": "State the permission to redistribute these data"
}
```

This block is a metadata **template**, not a statement that measurements exist. `source_kind` can be `synthetic`, `measured`, or `unknown`. Measured status is a provider declaration, not independently verified provenance. If no metadata are supplied, units follow the explicit column names and the source remains `unknown`. Unit declarations, when supplied, must match the CSV columns exactly. Optional metadata fields such as instrument and licensing are retained.

### Fit and use the curve

```python
from dataclasses import asdict
from recursivecal_lab.measurements import fit_force_curve, force_curve_parameters
from recursivecal_lab.physics import simulate

fit = fit_force_curve("examples/measurements/synthetic_force.csv")
identified = force_curve_parameters(fit)
run = simulate(
    asdict(identified),
    controller_parameters=asdict(identified),
    parameter_provenance=fit["provenance"],
)
print(fit["validation_metrics_N_each"])
```

The force curve is ordinary least squares with intercept and length slope. When temperature is provided, force is normalized by a fixed absolute-temperature multiplier before fitting. The thermal multiplier is assumed, not estimated. Without temperature samples, the selected reference temperature is assumed for every row and a warning is recorded.

The fit includes per-row predictions, residuals, training and validation errors, the observed training range, and provenance. `force_curve_parameters` maps the fit onto a selected mount geometry only when training lengths cover both closed and open endpoints. Automatic extrapolation is refused. This identifies a two-parameter force curve. It does not identify mass, inertia, friction, controller delay, or a complete liftgate plant.

`parameter_provenance` preserves the fit source on a simulated run. A run generated using declared measured coefficients still has synthetic trajectory data, `source_kind: synthetic`, and `hardware_validated: false`. `measured_data_used` records the coefficient-source declaration.

The version 3 controller contract changes only the five `Calibration` fields: mass, motor effectiveness, gas multiplier, Coulomb friction and encoder bias. Its gains and remaining controller coefficients are fixed. Supplying differing non-calibration controller coefficients, including custom gas-curve endpoints, is rejected explicitly. Use model 2 for a custom full force-curve controller experiment. Passing a fitted curve to the version 3 plant does not automatically rebuild the finite inference bank or its controller model.

## Trajectory comparison

Required columns are `time_s` and `angle_rad`. `velocity_rad_s` is optional. Times must be nonnegative and strictly increasing. The comparison treats angle as an independently observed physical hinge angle; it compares against the simulated state, not the simulator's biased synthetic sensor output. Correct sensor calibration and coordinate registration remain the data provider's responsibility.

```python
from recursivecal_lab.measurements import compare_trajectory
from recursivecal_lab.physics import simulate

run = simulate(duration_s=6.5, dt_s=0.01)
comparison = compare_trajectory(
    "examples/measurements/synthetic_trajectory.csv", run,
    acceptance_limits={"angle_rmse_rad": 0.01},
)
print(comparison["metrics"])
print(comparison["acceptance_passed"])
```

The example threshold is an arbitrary software demonstration. Choose engineering thresholds before inspecting validation residuals and document their justification. A supplied threshold produces a Boolean pass/fail for that comparison. With no threshold, `acceptance_passed` is `null`, not a fabricated pass.

The comparison interpolates the simulation at measurement times. It does not shift time, refit parameters, or extrapolate past the simulated interval. An early-aborted simulation cannot silently be compared to a longer measurement record. Metrics include count, RMSE, MAE, signed bias, maximum absolute error, and empirical 95th-percentile absolute error. The output includes all residuals, the input CSV hash, and a canonical hash of the simulation artifact.

A successful comparison establishes agreement with the supplied dataset and thresholds. It does not establish data independence, a valid calibration certificate, complete hardware safety, or generalization outside the measured conditions.

## Reproduce the included examples

After installing the package from the repository root:

```bash
python examples/measurements/generate_examples.py
python -m unittest discover -s tests -p 'test_lab_*.py' -v
```

The force example has 13 training locations and 7 held-out locations with known synthetic force noise. The trajectory example samples the same SI simulator and adds artificial angle observation error. Because it shares the simulator, it is an end-to-end import demonstration, not independent physical validation. No external data are downloaded by the generator.

Imports are limited to 10 MB and 100,000 rows. These bounds keep interactive comparison manageable and can be changed deliberately in a downstream application. CSV exports contain the full simulation trace and are not automatically accepted as measurement inputs because their extra columns and simulated origin must remain explicit.

## Public observations and sealed evidence

The same allowlist is applied to the initial measurement, start-of-test measurement, acquired snapshots and final measurement: declared times, ambient temperature, angle, angular rate and axial force. Unknown rig/debug fields are removed. Public diagnostic results additionally expose the selected action, its protocol cost, elapsed time, termination and event type/time. They do not expose true parameters, `true_*` state, per-side drive telemetry, tracking metrics or verifier outcomes.

An investigation's full report deliberately contains both `agent_history` and privileged `diagnostics`/verification records. The investigation view reads observed channels, even when privileged channels are present in the loaded report. Simulation and verification views may show evaluator telemetry and true geometry. A completed report must not be passed back to a policy as if it were another public observation.

The physical RL report additionally contains `policy_transcript`, the evaluator-only sampled `episode`, reward components and a sealed commitment. Nonterminal transcript rewards are zero. The task version, sampler, split rules and exact terminal reward are specified in [the physical RL contract](PHYSICAL_RL.md). RL reports are verified through `recursivecal verify-rl` or the Python API; the workbench's simulation/investigation import routes retain their own envelope types.

These Python interfaces prevent accidental disclosure through the public contract. They are not an isolation boundary against arbitrary code executing inside the evaluator process. The optional physical Verifiers adapter uses a tool-less harness, strips host seed/split from the agent-facing task, and records evaluator evidence after the interaction closes.

## JSON integrity and CSV exports

Investigation and physical RL reports carry `report_sha256`; the commitment also retains `history_sha256`. Typed canonical JSON hashing preserves numeric values across a Python/JavaScript JSON round trip. These hashes detect a change against the saved digest, not authorship or physical truth. The Python verifiers also check protocol consistency, budgets, acceptance and tracking evidence. They do not independently rerun the plant.

The SI `recursivecal.run/1` envelope does not acquire a commitment seal merely because it contains source hashes. Its import checks validate structure and finite signals. Source declarations and parameter provenance remain provider-supplied records.

The workspace's JSON export preserves the original complete report. Its JSON import limit is 32 MiB, separate from the measurement CSV limits above. The command-line simulation CSV exports all recorded trace columns and rows. The workspace CSV exports the selected displayed signal set, naming observed angle and display angle separately; optional drive columns appear only when available for that view. An investigation-view CSV does not turn evaluator-only electrical telemetry into an agent observation.

Keep the full JSON artifact alongside a CSV when model version, configuration, event history, calibration commitment or provenance matters. A trace CSV on its own is not the complete experiment record.
