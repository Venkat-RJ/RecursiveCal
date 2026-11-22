# Using RecursiveCal

RecursiveCal provides a synthetic physical liftgate workspace, an observation-only Bayesian investigator, and a versioned physical RL task. The default workbench and CLI use research rig 3: one rigid hinge with two DC drives, sampled instruments and an explicit spring-applied brake. The earlier force model 2 and normalized diagnostic benchmark remain separate, reproducible workflows. No workflow connects to hardware.

## Install and check

Use Python 3.11 or later. From a checkout of this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
recursivecal doctor
```

NumPy is the only required third-party runtime dependency. The command reports the installed version, dependency version, packaged workbench assets, and a short simulation. A GPU, cloud account, API key, CAD application, or paid service is not needed. Installation from the built wheel also supports every new CLI command and the workbench.

## Start the workbench

```bash
recursivecal serve
```

Open `http://127.0.0.1:8765`. The server stays in that terminal. Ctrl+C stops it. Choose another port with `--port 8766`. The server accepts only loopback connections; it is a local single-user tool, not a public hosting service.

The root page has four tabs. **Rig & data** runs the SI model and synchronizes the 3D pose, actuator extension, plots and readouts to one recorded time. **Investigate** runs the bounded Bayesian or fixed-test policy, streams completed computation stages, and compares acquisition samples with predictions made before each test. **Calibrate** separates the inferred parameter values from the values actually committed. **Verify** compares baseline and committed motion, displays every acceptance limit, and reports unpowered support separately.

Use **Configure** to change the next run, **Run simulation** or **New investigation** to execute, and **Export** to retain the complete JSON. The playback controls replay saved data; they do not advance the physical solver. Imported JSON retains its original settings and provenance. Changing a form after a run does not rewrite the saved run. Investigation imports check the report and committed-history digests before replacing the current evidence.

Select a left or right actuator to inspect its modeled current, voltage, shaft speed, winding temperature and force. Research rig 3 maintains independent drive states, which act on the same rigid hinge. The cutaway is an illustrative internal assembly: its nut and rod translate with the displayed extension, while shaft speed comes from the declared gear ratio and screw lead. It is not manufacturing CAD or a panel-twist model. Investigation pose uses the sensor trace; verification pose uses the sealed evaluator trace. Electrical telemetry remains withheld from the investigator.

The healthy research-rig reference has a 120 N·m unpowered brake, with a 20 ms engagement delay after power loss. Its default passive-hold test passes. Setting the brake capacity to zero exposes the unbraked support failure; changed loads or other assumptions can also fail. The earlier force model 2 retains its original unbraked default and support deficit. Always inspect the model identifier and termination result. These are synthetic architecture checks, not measurements of a real brake.

In **Configure**, choose **Research rig 3** or **Force model 2** explicitly. For rig 3, **Drives, brake and sampled instruments** exposes supply voltage, brake capacity, per-side effectiveness, sample period, sensor delay, command delay and angle noise. Rig 3 always stops on a declared motion or drive-protection limit. Its outer time step is 1 to 20 ms; the electrical/mechanical integrator uses smaller internal steps when needed.

### Inspect the mechanism with the camera

Use the camera selector for **Isometric**, **Front**, **Side** or **Top**. Drag to orbit, Shift-drag or middle-drag to pan, and scroll to zoom. On a touch screen, use one finger to orbit or two fingers to pinch and pan. The reset button and a double-click restore the current assembly or mechanism focus.

The canvas is keyboard accessible. With it focused, arrow keys orbit, Shift plus arrows pan, `+`/`-` zoom, and Home or `0` resets. Keys `1` to `4` select the four presets in the order above. Tab leaves the canvas normally. Camera movement does not change the physical state or replay time. This is an inspection camera; the agent receives no camera images or depth observations.

### Understand the sensor timestamps

Rig 3 samples instruments on their own clock. The defaults are a 10 ms sample period, 10 ms delivery latency and 10 ms command delay, with seeded noise and quantization. The controller uses the same held, delivered acquisition as the instrument interface. Repeated reads do not create fresh noise or bypass the configured delay. An initial acquisition is explicitly available at episode reset.

Reports retain the acquisition timestamp and sensor age separately from the time of the trace row. Three diagnostic snapshots per experiment enter the current Bayesian likelihood. The denser replay and its interpolated display do not add observations to the investigator.

**Measurement tools** opens `data.html`, which retains force-length fitting, trajectory comparison, extended simulation settings, pinned runs and the benchmark Evidence view. The recorded examples are saved synthetic artifacts from this release. Static preview mode can inspect those examples and imported files; executing a new simulation or fitting data requires the local server. See [the workspace guide](WORKBENCH.md) for the complete screen and data workflow.

## Run and export a simulation

```bash
recursivecal simulate --rig-version 3 --scenario open --duration 6.5 --dt 0.01 \
  --output runs/open.json --csv runs/open.csv

recursivecal simulate --rig-version 3 --scenario passive_hold \
  --output runs/passive-hold.json

recursivecal model --rig-version 3
```

Version 3 is the CLI default; the explicit flag makes the selected model clear in a reproducible command. JSON contains the full trace, parameter values, drive/sensor specification, model identifier, source provenance, metrics and events. CSV contains the trace columns, including per-side electrical and thermal quantities. Observed angles remain separate from the simulator pose. The final time is shortened exactly to the requested duration unless the run terminates early. A successful process exit means the requested simulation was recorded; inspect `metrics.termination` to distinguish completion from a simulated speed, impact or drive-trip abort.

Existing JSON outputs are protected. Use a new output path or add `--overwrite` intentionally. If exporting both JSON and CSV, both destinations must be available unless overwrite is requested.

Parameter files contain a partial or complete JSON object, such as:

```json
{"mass_kg": 29, "motor_efficiency": 0.7, "sensor_bias_rad": 0.02}
```

```bash
recursivecal simulate --parameters plant.json --output runs/changed.json
```

All unprovided parameters retain documented defaults. Rig 3 uses the authored mount geometry and validates its bounded parameter range. The controller uses a separate nominal calibration. `--controller-parameters controller.json` supplies its five estimated quantities: mass, motor effectiveness, gas-assistance scale, Coulomb friction and encoder bias. Its feedback gains remain fixed. This is an explicit calibration setting, not an RL-trained motor policy. Drive and sensor overrides are available through the workbench and Python interface; they are not fields in the CLI `--parameters` object.

To reproduce the earlier force-domain model:

```bash
recursivecal simulate --rig-version 2 --scenario passive_hold \
  --output runs/legacy-unbraked.json
```

Version 2 has first-order force response and no electrical or thermal drive states. `--continue-on-limit` is available only for that legacy model. For direct HTTP requests, always send `rig_version` explicitly; requests that omit it retain the version-2 compatibility behavior.

## Run a physical investigation

```bash
recursivecal inquire --rig-version 3 --case weak_motor --seed 7 \
  --output runs/physical-inquiry.json
recursivecal verify-inquiry runs/physical-inquiry.json
```

The terminal shows experiment selection, acquired results, commitment and verification. Choose `--policy fixed` or `--policy no_probe` for the comparison baselines. The condition name is evaluator setup and is not included in policy observations. A correct diagnosis can still fail motion verification. A model mismatch or diagnostic limit can lead to nominal abstention. Use `--rig-version 2` to reproduce the earlier physical inquiry model.

## Exercise the physical RL task

```bash
recursivecal rl-schema
recursivecal rl-rollout --split test --seed 7 --policy fixed \
  --output runs/physical-rl.json
recursivecal verify-rl runs/physical-rl.json
```

This task runs research rig 3. The policy selects a legal experiment, commits one calibration, or abstains. Reward is produced only after commitment and independent verification. Training, validation and test use disjoint parameter-cell assignments; `--split ood` adds declared structural changes. The rollout command exercises the fixed or no-probe baseline. It does not train a learned policy or establish learned superiority. `verify-rl` checks the saved episode, protocol and terminal scoring. Add `--replay` to rerun a source-matched synthetic episode and compare all recorded evidence; this costs more computation and cannot establish hardware accuracy. `verify-inquiry` supports the same optional flag. The full completed report is evaluator evidence and must not be fed back as a pre-commit observation.

## Fit a force curve and use it

The bundled examples are entirely synthetic. The same parser accepts user-supplied measurements with explicit provenance and units.

```bash
recursivecal fit-force examples/measurements/synthetic_force.csv \
  --metadata examples/measurements/synthetic_force.metadata.json \
  --output runs/force-fit.json --parameters-output runs/fitted-parameters.json

recursivecal simulate --rig-version 2 --parameters runs/fitted-parameters.json \
  --controller-parameters runs/fitted-parameters.json \
  --output runs/fitted-open.json
```

The CSV must have `length_m`, `force_N_each`, and `split` columns, with explicit `train` and `validation` rows. `temperature_C` is optional. Training rows determine the curve; validation rows only report error. Application refuses a curve whose observed training lengths do not cover the requested mount geometry. Use `--base-parameters plant.json` when fitting for a nondefault geometry.

This example uses version 2 so the fitted force curve is applied to both the plant and its full feedforward parameter set. Version 3's committed calibration has the five quantities listed above; importing a force curve does not automatically rebuild its Bayesian candidate bank. The saved parameter set retains the measurement-source declaration and data hash. Applying measured coefficients does not turn the generated trace into a measured recording or validate the rest of the model. See [the data contract](DATA_CONTRACT.md).

## Compare an angle trace

```bash
recursivecal replay examples/measurements/synthetic_trajectory.csv \
  --metadata examples/measurements/synthetic_trajectory.metadata.json \
  --simulation runs/open.json --output runs/comparison.json \
  --angle-rmse-max 0.01
```

The example threshold is a software demonstration. For an engineering study, choose and justify the threshold before looking at validation residuals. The comparison reports RMSE, MAE, bias, maximum error, and every residual. It interpolates within the simulated time interval without time shifting or refitting. A measurement record longer than an aborted simulation is rejected instead of extrapolated.

Without a threshold, the result has `acceptance_passed: null`. With a failed declared threshold, the report is saved and the CLI exits with status 1. Input or filesystem errors exit with status 2. Velocity comparison is available when the CSV has `velocity_rad_s`, with `--velocity-rmse-max` in rad/s.

## Reproduce the earlier normalized diagnostic experiment

```bash
recursivecal experiment --output runs/smoke --quick
recursivecal verify runs/smoke

recursivecal experiment --output runs/full \
  --train-size 1024 --test-size 512 --seeds 13 37 103 211 509
recursivecal verify runs/full
```

The experiment runs visibly in the current terminal and writes each stage's progress. Use a new directory for a new run. The full release is already recorded in `research/releases/v0.3/`. The verifier checks source and artifact hashes, paired trial identities, aggregates reconstructed from raw rows, and reloaded learned-policy decisions.

The full run creates a manifest, frozen selection, compressed observation and trial CSVs, train/validation arrays, one JSON checkpoint per learner seed, and a summary. Import `summary.json` into Evidence. A quick run is a pipeline smoke test and is explicitly labeled as such.

The [experiment protocol](EXPERIMENT_PROTOCOL.md) explains the finite prior, split seeds, models, learning algorithm, baselines, statistical intervals, and shifts. The frozen normalized equations retain the old 0.55-second request rounding behavior. They are not the new SI liftgate model.

## Troubleshooting

| Symptom | Meaning and action |
| --- | --- |
| `recursivecal` command is missing | Activate the environment used for installation, or use `python -m recursivecal_lab`. |
| Workbench says recorded/static mode | The Python API is unavailable. Use recorded examples or start `recursivecal serve`. |
| Existing output error | Select another result path or add `--overwrite`. |
| Input units rejected | Convert the data explicitly to the documented SI columns and update its metadata. |
| Force fit refuses application | The training lengths do not cover the selected geometry. Obtain supporting measurements rather than silently extrapolating. |
| Trajectory time range rejected | Use a simulation that actually covers the measurement interval, or deliberately select an overlapping validation segment. |
| Artifact source hash differs | Reproduce using the source revision recorded for that experiment. Do not rewrite the manifest to conceal a change. |
| Passive hold fails | Check the model version and brake configuration. The version-2 default and the version-3 zero-brake fault are unbraked; the healthy version-3 reference includes a brake. Changed loads can still exceed its capacity. |
| Version-3 settings are rejected | Use the declared research range and authored geometry. Version 3 enforces limit termination and has a 15-second maximum run duration. |
| Current or temperature shows unavailable | Version-2 runs do not contain these channels. The investigator view also deliberately withholds hidden drive telemetry. |

Historical CAD and neural pilots have their own commands in their respective reports. Optional Torch and Verifiers integrations are not needed for the workbench, physical baseline rollout or NumPy experiment suite. Numerical verification of research rig 3 is recorded separately from measured hardware accuracy; see [RESEARCH_RIG.md](RESEARCH_RIG.md) and [the hardware protocol](HARDWARE_PROTOCOL.md).

