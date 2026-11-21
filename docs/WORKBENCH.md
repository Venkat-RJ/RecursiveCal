# RecursiveCal workbench

The workbench is an interface to the local Python simulation and data pipeline. It runs the SI liftgate model, inspects its saved traces, fits force measurements, compares trajectories, and displays completed diagnostic experiments. It does not connect to a vehicle, a controller, or a hardware test bench.

## Start the application

From an installed checkout:

```bash
recursivecal serve
```

The command prints the local address, normally `http://127.0.0.1:8765`. Open it in a browser. Keep the command in the foreground while using the workbench. Press Ctrl+C to stop the server. The server binds to loopback and serves packaged assets without a CDN or a separate JavaScript build.

For a different local port:

```bash
recursivecal serve --port 8766
```

The root page is the physical workspace. A static HTTPS preview can replay the bundled synthetic evidence and import compatible JSON reports. Computation buttons remain disabled when the local API is unavailable. Integrity checks require a secure browser context such as HTTPS or localhost. Static mode never substitutes invented results for an unavailable backend.

## The physical workspace

| Tab | What it shows |
| --- | --- |
| Rig & data | Mechanism, selected actuator, illustrated internal assembly, simulation signals and events |
| Investigate | Test sequence, pre-test candidate predictions, instrument traces, acquired samples and posterior updates |
| Calibrate | Nominal, inferred and committed parameter values, conditional model-bank uncertainty and commitment reason |
| Verify | Baseline/candidate motion, every motion acceptance limit, passive support, power loss and hardware evidence |

Click **Configure** to choose the next simulation or investigation, then run it. The local investigation endpoint streams real stage events: test selected, test completed, belief updated, committed and verification complete. It does not stream an invented per-frame solver progress percentage. Monitor callbacks receive detached public observations; hidden plant truth is retained until the sealed report. Candidate predictions are saved before the corresponding experiment runs.

Once a trace is available, one clock drives the rig pose, actuator extension, plots, sample markers and numeric readouts. Drag the timeline, click a plot, step between recorded samples, or play at the selected speed. Numeric channels interpolate at the recorded timestamps. Discrete power states are held between samples and ended runs are not extrapolated. **Replaying** means saved motion, while **Computing** means the local backend is working. Source labels distinguish recorded examples, locally computed results and imported evidence.

The investigation view uses the sensor angle and combined strut-force signal, even when a loaded sealed report also contains evaluator truth. The verifier view uses the evaluator trace after commitment. Agent acquisition samples are marked separately from the denser instrument replay. The three candidate paths are the highest-weight model predictions before the selected test, not fitted curves drawn after observing it. Older reports without saved predictions remain usable and do not receive fabricated prediction paths.

The actuator cutaway is illustrative, not manufacturing CAD. Its translating nut and rod follow geometric extension. Motor rotation, current and temperature remain unmodeled. The two struts share one actuator force state. The 3D assembly uses the standard mount geometry; a run with incompatible imported mounts keeps its trace and readouts but does not display a misleading standard assembly.

The calibration table separates inferred estimates from the frozen commitment. When the investigator abstains, the committed values remain nominal. Uncertainty is conditional on the finite model bank, not a hardware confidence guarantee. Motion verification requires completion, tracking RMSE no greater than 3 degrees, absolute final error no greater than 2 degrees, peak speed no greater than 1.15 rad/s and saturation fraction no greater than 0.35 for every profile. Passive support, power loss and hardware validation are shown separately.

**Export** retains the complete original report. **CSV** exports the selected displayed trace. Investigation imports validate the report digest and the committed observation-history digest; changed evidence is rejected while the previous report remains available. These hashes detect changes, not authorship. Python `recursivecal verify-inquiry` also checks the report protocol and acceptance result.

**Open recorded example** restores the bundled physics-2 simulation or investigation. This does not execute a new simulation or train a policy. Use **Measurement tools** to open `data.html` for the extended settings, fitting and historical benchmark workflows below. That page retains **Load recorded example** and **Load recorded benchmark** with their original provenance, including archived physics-1 evidence.

## Extended simulation and measurement tools

The following controls are on `data.html`, opened from **Measurement tools** in the workspace.

### Run a physical scenario

1. Choose **Open and hold**, **Close**, **Passive hold**, or **Power loss during opening**.
2. Set the plant assumptions, duration and numerical time step. The extended settings expose friction, actuator lag, force limits, sensor errors and the initial state.
3. Choose the nominal controller or disable the motor. Passive hold is always unpowered. The nominal feedforward model does not silently use the altered plant's fault parameters.
4. Click **Run simulation**. Inspect termination first, then the signal plots, metrics, events and passive-hold calculation.
5. Use the trace slider or playback button to inspect individual samples. Playback only replays saved data. It does not rerun the simulation.
6. Export **JSON** to retain the full configuration, parameters, provenance, events, metrics and trace. Export **CSV** for the numeric signal table.

The diagram is a hinge schematic driven by the saved opening angle. It is labelled separately from the earlier CAD explorer. The web plots show motor force and mechanical work, not invented motor current or electrical energy.

### Limits and stopped runs

The stop-on-limit option is enabled by default. A triggered limit remains visible as a stopped run even though the HTTP request completed normally. The event list records the time and relevant values. Disabling an abort changes experiment handling; it does not make the plant safe.

The passive-hold card reports the static force balance at the open stop, including the declared static friction and holding-brake capacity. The default model has insufficient passive holding capacity. A hypothetical added brake changes this calculation but does not establish that such hardware exists.

### Compare runs

Click **Pin for comparison**, change the configuration, and run again. The pinned trace appears in purple alongside the current trace. The current run's metrics remain attached to that run. Different durations share a common time axis. The pin and all results stay in browser memory until the page closes; export the files to retain them.

An imported run restores its visible settings and retains any additional parameter fields in the saved configuration. Changing the scenario resets the optional initial angle to that scenario's default. A fresh run always goes through backend validation.

## Fit a force curve

The **Measurements** view accepts a force CSV with these columns:

```csv
length_m,force_N_each,split
0.55,215.0,train
0.65,202.1,train
0.75,189.0,train
0.85,175.9,train
0.95,163.0,train
0.60,208.6,validation
0.80,182.3,validation
0.90,169.7,validation
```

These values are an invented example. The built-in example button explicitly marks them synthetic. They only exercise the pipeline.

Supply a source or acquisition ID and declare the data origin. Length is in metres and force is in newtons per strut. Optional temperature is in degrees Celsius. The full data requirements, temperature treatment, split checks and limits of identification are documented in [DATA_CONTRACT.md](DATA_CONTRACT.md).

Click **Fit and validate curve** to compute the training fit and separate validation residuals. Inspect the full JSON for coefficient values, fit errors, source hashes and provenance. A low fit error does not identify hatch mass, hinge friction, sensor bias or the entire plant.

When the training range covers the model geometry, **Apply this curve to configuration** maps the fitted force curve to the plant's gas parameters. The backend rejects unsupported extrapolation. Application changes the configuration only; click **Run simulation** to compute a new trace. The result retains the fit's provenance and records any parameter overrides made afterwards. Its trace is still synthetic, even if the force measurements were real.

The “measured” selection records a declaration supplied by the operator. It is not independent verification of the data source. Keep the original acquisition files and context with the exported fit.

## Compare a trajectory

Run or import a simulation, then supply a trajectory CSV:

```csv
time_s,angle_rad
0.0,0.0
0.1,0.003
```

The example above illustrates the format only. The optional velocity column is `velocity_rad_s`. Provide the source and origin, then choose **Compare with current run**. Every measurement timestamp must lie within the saved simulation interval; the backend interpolates there without refitting or extrapolation and returns residual metrics. Loading a different simulation clears the previous comparison so it cannot be mistaken for a result against the new run.

A trace exported by the same simulator is useful for checking the import and comparison plumbing. It provides no independent physical validation. Use an independently acquired trace for that question.

## Inspect research evidence

The **Evidence** view accepts `summary.json` produced by the experiment runner. Its schema is `recursivecal.experiment.v1`. The page displays the stored cohort results, policy means, diagnostic costs and paired comparison intervals.

These policy experiments use the frozen normalized actuator benchmark. They are separate from the SI liftgate model. An adaptive policy result must not be interpreted as a trained controller for the liftgate workbench.

The no-probe baseline uses a fixed calibration selected from the prior. It does not necessarily mean factory calibration or no change. Net reward includes the diagnostic test cost. Equal numbers of probes do not necessarily imply equal costs.

The imported file is displayed as recorded. Use its source manifest, protocol, episode outputs and checkpoints to reproduce it. Importing a JSON file does not independently verify its claims.

## Files and browser behavior

The interface makes no external API calls to compute results. Source and documentation links open only when selected. Imported text is inserted as text, not executable HTML. The workbench does not use browser storage for runs or datasets. Closing or refreshing the page discards unsaved in-memory work.

The browser import limit is 32 MiB. The local API applies its own request-size and step limits, which can be stricter. Use the CLI for datasets outside the local API's limits. A file's size, schema, trace time ordering and finite numeric fields are checked before it is displayed.

## Verification

Pure contract checks, without a browser:

```bash
node tests/workbench_contracts.cjs
node tests/workspace_contracts.cjs
```

End-to-end checks, with Playwright and Chromium installed:

```bash
python tests/workbench_smoke.py
python tests/workspace_smoke.py
```

The tests start temporary local servers and close them with the browsers on completion or failure. The workbench test covers measurement fitting, comparison and archived evidence at `data.html`. The workspace test checks timestamp interpolation against exported trace data, synchronized pose and extension, recorded predictions, all four tabs at mobile/tablet/desktop widths, a real power-loss simulation, a real streamed investigation that fails verification, tampered evidence rejection and static recorded mode. It saves actual screenshots and a JSON report to `artifacts/workspace/`; the CI compatibility entry point `tests/inquiry_smoke.py` uses `artifacts/inquiry-browser/`. These tests do not control the user's computer.

