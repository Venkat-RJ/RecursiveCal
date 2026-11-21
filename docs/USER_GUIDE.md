# Using RecursiveCal

RecursiveCal 0.3 provides two executable research tools: a physical-unit liftgate workbench and a separate normalized diagnostic benchmark. The workbench helps inspect assumed mechanisms and compare measurements. The benchmark tests observation-dependent diagnostic decisions. Neither is connected to hardware.

## Install and check

Use Python 3.11 or later. From a checkout of this repository:

```bash
python -m venv .venv
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

The Simulation view runs the SI model. Configure the scenario, physical parameters, controller, numerical step, noise seed, and limit behavior. Inspect the signal traces, move the time cursor, pin a run to compare, and export JSON or CSV. Imported JSON retains its original settings and provenance. Changing a form after a run does not rewrite the saved run.

Passive hold and power loss intentionally reveal the default support deficit. The default passive-hold simulation stops when it reaches its assumed speed limit. Its short trace is an aborted run, not a completed 6.5-second success. An explicit holding-brake parameter changes the modeled architecture; it does not establish a real brake's capacity.

The Measurements view fits force-length data or compares angle traces. The Evidence view reads benchmark summaries. The recorded examples are saved synthetic artifacts from this release. Static preview mode can inspect those examples and imported files; executing a new simulation or fitting data requires the local server.

## Run and export a simulation

```bash
recursivecal simulate --scenario open --duration 6.5 --dt 0.01 \
  --output runs/open.json --csv runs/open.csv

recursivecal simulate --scenario passive_hold \
  --output runs/passive-hold.json

recursivecal model
```

JSON contains the full trace, exact parameter values, model identifier, source provenance, metrics, and events. CSV contains all trace columns in SI units. The final time is shortened exactly to the requested duration unless the run terminates early. A successful process exit means the requested simulation was recorded; inspect `metrics.termination` to distinguish completion from a deliberately simulated limit abort.

Existing JSON outputs are protected. Use a new output path or add `--overwrite` intentionally. If exporting both JSON and CSV, both destinations must be available unless overwrite is requested.

Parameter files contain a partial or complete JSON object, such as:

```json
{"mass_kg": 29, "motor_efficiency": 0.7, "sensor_bias_rad": 0.02}
```

```bash
recursivecal simulate --parameters plant.json --output runs/changed.json
```

All unprovided parameters retain documented defaults. The controller uses a separate nominal model. To supply a calibrated feedforward model, use `--controller-parameters controller.json`. That is an explicit model-based controller setting, not an RL-trained motor policy.

## Fit a force curve and use it

The bundled examples are entirely synthetic. The same parser accepts user-supplied measurements with explicit provenance and units.

```bash
recursivecal fit-force examples/measurements/synthetic_force.csv \
  --metadata examples/measurements/synthetic_force.metadata.json \
  --output runs/force-fit.json --parameters-output runs/fitted-parameters.json

recursivecal simulate --parameters runs/fitted-parameters.json \
  --controller-parameters runs/fitted-parameters.json \
  --output runs/fitted-open.json
```

The CSV must have `length_m`, `force_N_each`, and `split` columns, with explicit `train` and `validation` rows. `temperature_C` is optional. Training rows determine the curve; validation rows only report error. Application refuses a curve whose observed training lengths do not cover the requested mount geometry. Use `--base-parameters plant.json` when fitting for a nondefault geometry.

The saved parameter set retains the measurement-source declaration and data hash. The resulting motion is still a synthetic simulation. Applying measured coefficients does not turn the generated trace into a measured recording or validate the rest of the model. See [the data contract](DATA_CONTRACT.md).

## Compare an angle trace

```bash
recursivecal replay examples/measurements/synthetic_trajectory.csv \
  --metadata examples/measurements/synthetic_trajectory.metadata.json \
  --simulation runs/open.json --output runs/comparison.json \
  --angle-rmse-max 0.01
```

The example threshold is a software demonstration. For an engineering study, choose and justify the threshold before looking at validation residuals. The comparison reports RMSE, MAE, bias, maximum error, and every residual. It interpolates within the simulated time interval without time shifting or refitting. A measurement record longer than an aborted simulation is rejected instead of extrapolated.

Without a threshold, the result has `acceptance_passed: null`. With a failed declared threshold, the report is saved and the CLI exits with status 1. Input or filesystem errors exit with status 2. Velocity comparison is available when the CSV has `velocity_rad_s`, with `--velocity-rmse-max` in rad/s.

## Reproduce the diagnostic experiment

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
| Passive hold fails | This is an expected failure of the default assumed support architecture. Inspect the force balance and explicit holding capacity. |

Historical CAD and neural pilots have their own commands in their respective reports. Optional Torch and Verifiers integrations are not needed for the new workbench or NumPy experiment suite.

