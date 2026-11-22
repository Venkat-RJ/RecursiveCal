# RecursiveCal workbench

The workbench is an interface to the local Python simulation and data pipeline. The root workspace defaults to research rig 3, with two DC drives, sampled instruments and an explicit holding brake acting on one rigid hinge. It inspects saved traces, runs diagnostic experiments and verifies calibration. Measurement tools retain the earlier force-domain workflow. No hardware is connected.

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

The **Physical model** selector distinguishes **Research rig 3** from **Force model 2**. For rig 3, expand **Drives, brake and sampled instruments** to set supply voltage, unpowered brake capacity, independent left/right effectiveness, sample period, sensor latency, command latency and angle noise. Imported results restore their own model version and configuration. Rig 3 uses the authored geometry, a maximum 15-second duration, and an outer control step between 1 and 20 ms. Its solver subdivides internally for electrical and mechanical stiffness. Declared limit termination is mandatory in this model.

Once a trace is available, one clock drives the rig pose, actuator extension, plots, sample markers and numeric readouts. Drag the timeline, click a plot, step between recorded samples, or play at the selected speed. Numeric channels interpolate at the recorded timestamps. Discrete power states are held between samples and ended runs are not extrapolated. **Replaying** means saved motion, while **Computing** means the local backend is working. Source labels distinguish recorded examples, locally computed results and imported evidence.

The investigation view uses the sensor angle and combined strut-force signal, even when a loaded sealed report also contains evaluator truth. The verifier view uses the evaluator trace after commitment. Agent acquisition samples are marked separately from the denser instrument replay. The three candidate paths are the highest-weight model predictions before the selected test, not fitted curves drawn after observing it. Older reports without saved predictions remain usable and do not receive fabricated prediction paths.

The actuator cutaway is illustrative, not manufacturing CAD. Its translating nut and rod follow geometric extension. In version 3, selecting an actuator shows its current, terminal voltage, motor speed, winding temperature and delivered force, alongside sensor age and brake state. The electrical/thermal states are independent on each side; shaft motion is constrained by the shared rigid hinge, gear ratio and screw lead. Panel twist, backlash and rotor inertia are outside this model. Version-2 traces retain their force-only interpretation and do not gain fabricated current or thermal channels. The 3D assembly uses the standard mount geometry; incompatible imported mounts retain trace/readout access without displaying the standard assembly.

The sensor model records acquisition time separately from delivery and trace time. Defaults are a 10 ms sample period, 10 ms delivery latency and 10 ms command delay, with quantization and seeded noise. A held acquisition is reused until a newer delivered sample is available; the controller does not receive ideal state in version 3. One initial acquisition is explicitly available at reset. Camera and plot interpolation is for inspecting the recording and does not create extra acquisitions for the investigator.

The calibration table separates inferred estimates from the frozen commitment. When the investigator abstains, the committed values remain nominal. Uncertainty is conditional on the finite model bank, not a hardware confidence guarantee. Motion verification requires completion, tracking RMSE no greater than 3 degrees, absolute final error no greater than 2 degrees, peak speed no greater than 1.15 rad/s and saturation fraction no greater than 0.35 for every profile. Passive support, power loss and hardware validation are shown separately.

**Export** retains the complete original report. **CSV** exports the selected displayed trace. Investigation imports validate the report digest and the committed observation-history digest; changed evidence is rejected while the previous report remains available. These hashes detect changes, not authorship. Python `recursivecal verify-inquiry` also checks the report protocol and acceptance result.

**Open recorded example** restores the bundled research-rig-3 simulation or investigation. This does not execute a new simulation or train a policy. Use **Measurement tools** to open `data.html` for the legacy force-model settings, fitting and historical benchmark workflows below. That page retains **Load recorded example** and **Load recorded benchmark** with their original provenance, including archived physics-1 evidence.

### Camera controls

The camera selector provides **Isometric**, **Front**, **Side** and **Top** views. Orbiting away from a preset orientation changes the selector to **Custom**; zoom and pan retain its orientation label. Preset changes keep the current assembly/mechanism focus. The reset button restores that focus's default pose and zoom.

| Input | Action |
| --- | --- |
| Drag or one-finger drag | Orbit the rig |
| Shift-drag or middle-button drag | Pan the target |
| Scroll | Zoom |
| Two-finger gesture | Pinch to zoom and move together to pan |
| Double-click, Home or `0` | Reset the current focus |
| Arrow keys | Orbit while the canvas is focused |
| Shift plus arrow keys | Pan while the canvas is focused |
| `+`, `=` or `-` | Zoom while the canvas is focused |
| `1`, `2`, `3`, `4` | Isometric, front, side and top presets |

Tab reaches and leaves the canvas normally. Camera changes update projected overlays and leave the simulation state and replay time unchanged. The renderer uses the same camera/projection in WebGL and software fallback. Its schema-versioned state can be copied with `getCamera()` and restored with `setCamera(state)`; invalid or unsupported state is rejected before changing the view. These methods belong to the renderer API, not a camera-file import dialog. This camera serves human inspection and is not an RGB/depth sensor for an agent.

### Holding and power-loss behavior

The healthy version-3 reference includes a 120 N·m spring-applied brake. It holds the default hatch without motor power. After power loss or a latched drive-protection trip, the model disconnects the drives into their declared dump circuit and schedules brake engagement after 20 ms. The brake does not instantly erase velocity. A zero-capacity brake is an explicit negative case; its support failure is preserved rather than corrected by calibration. Changed loads may also exceed the configured capacity. Hardware validation remains unavailable even when every synthetic motion profile passes.

### Terminal entry points

```bash
recursivecal simulate --rig-version 3 --scenario power_loss --output runs/power-loss.json
recursivecal inquire --rig-version 3 --case weak_motor --seed 7 --output runs/inquiry.json
recursivecal verify-inquiry runs/inquiry.json
recursivecal rl-rollout --split test --seed 7 --policy fixed --output runs/physical-rl.json
recursivecal verify-rl runs/physical-rl.json
recursivecal rl-schema
```

Commands run in the foreground. The physical RL rollout uses the same version-3 plant and produces a sealed baseline episode; it does not train a policy. The browser investigation remains the Bayesian/fixed/no-probe workflow. Version-2 reproduction uses `--rig-version 2`. Direct HTTP calls should include `rig_version`; omitting it preserves the version-2 compatibility default.

## Extended simulation and measurement tools

The following controls are on `data.html`, opened from **Measurement tools** in the workspace. New simulations from this legacy page use force model 2; its archived examples retain their own model identifiers.

### Run a physical scenario

1. Choose **Open and hold**, **Close**, **Passive hold**, or **Power loss during opening**.
2. Set the plant assumptions, duration and numerical time step. The extended settings expose friction, actuator lag, force limits, sensor errors and the initial state.
3. Choose the nominal controller or disable the motor. Passive hold is always unpowered. The nominal feedforward model does not silently use the altered plant's fault parameters.
4. Click **Run simulation**. Inspect termination first, then the signal plots, metrics, events and passive-hold calculation.
5. Use the trace slider or playback button to inspect individual samples. Playback only replays saved data. It does not rerun the simulation.
6. Export **JSON** to retain the full configuration, parameters, provenance, events, metrics and trace. Export **CSV** for the numeric signal table.

The legacy diagram is a hinge schematic driven by the saved opening angle. Its force-model plots show motor force and mechanical work. Use the root workspace's research-rig-3 simulation to inspect modeled electrical and thermal state.

### Limits and stopped runs

The stop-on-limit option is enabled by default. A triggered limit remains visible as a stopped run even though the HTTP request completed normally. The event list records the time and relevant values. Disabling an abort changes experiment handling; it does not make the plant safe.

The passive-hold card reports the static force balance at the open stop, including declared static friction and holding-brake capacity. The legacy version-2 default has insufficient passive holding capacity. This differs from the explicit braked version-3 reference. A modeled brake changes the calculation but does not establish that such hardware exists.

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
node tests/camera_contracts.cjs
```

End-to-end checks, with Playwright, Chromium and WebKit installed:

```bash
python tests/workbench_smoke.py
python tests/workspace_smoke.py
python tests/camera_smoke.py --all --output artifacts/camera-browser
```

The tests start temporary local servers and close them with the browsers on completion or failure. The workbench test covers measurement fitting, comparison and archived evidence at `data.html`. The workspace test checks timestamp interpolation against exported trace data, synchronized pose and extension, recorded predictions, all four tabs at mobile/tablet/desktop widths, a real power-loss simulation, a real streamed investigation that fails verification, tampered evidence rejection and static recorded mode. It saves actual screenshots and a JSON report to `artifacts/workspace/`; the CI compatibility entry point `tests/inquiry_smoke.py` uses `artifacts/inquiry-browser/`. These tests do not control the user's computer.

The camera test loads the packaged renderer and CAD directly, without a server. It exercises native mouse and keyboard controls in Chromium and WebKit, native multitouch injection in Chromium, strict camera-state import, narrow layouts, and WebGL/software projection agreement. WebKit multitouch injection is explicitly marked unavailable. It saves screenshots and reports in `artifacts/camera-browser/`. These are inspection-camera tests, not physical camera calibration or sensor validation.

