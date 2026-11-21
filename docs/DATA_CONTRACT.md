# Data import, fitting, and comparison

The data path is executable from CSV through a fitted force curve and an SI simulation. Every import records the CSV SHA-256 and declared source metadata. Included examples are synthetic and remain labeled that way.

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
