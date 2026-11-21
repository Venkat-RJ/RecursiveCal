# Measurement protocol for a future vehicle-calibrated model

The current model uses **illustrative** mass, mount geometry, gas-spring force, torque limits and friction coefficients. The code includes a CSV load-cell fitter, but **no real RecursiveCal plant measurements have been supplied or used**.

## What a real calibration would require

- **CAD/dimensions:** rear hinge centerline, left/right ball-stud mount points, hatch mass, center of gravity, and hinge inertia. Verify clearances and measured strut extension through full stroke.
- **Load-cell readings:** force on each powered strut at measured hinge angles; record loading/unloading direction, speed, ambient temperature and fixture geometry. Calibrate the sensor. Separate motor force from gas-assist force where possible.
- **Motion:** encoder angle and angular speed, motor current/voltage, commanded drive, estimated torque, opening/closing cycle times. Timestamp all channels from one timebase.
- **Faults:** temperature variation, aging, seal friction, motor weakening, sensor offset and load changes under controlled, safe test protocols.
- **Safety:** obstruction detection, current/speed limits, reversal logic, pinch-force limits, fixture interlocks and emergency stop procedures are prerequisites for any real hardware experiments.
- **Validation:** hold out complete test cycles, temperatures and mechanical configurations. Evaluate speed, endpoint error, load, current, thermal behavior and adverse events.

## Import schema

The reference fitting utility accepts 

```csv
angle_deg,strut_force_N_each,measurement_type,temperature_C
0,215.2,MEASURED_LOAD_CELL,23.0
20,209.3,MEASURED_LOAD_CELL,23.0
45,191.4,MEASURED_LOAD_CELL,23.0
78,166.1,MEASURED_LOAD_CELL,23.0
```

The numbers above demonstrate the schema and are **fictional**. Do not copy them as measured values. Run:

```bash
python simulation/fit_force_curve.py your_force_measurements.csv --out fitted_curve.json
```

A separate [synthetic fixture](../assets/SYNTHETIC_force_samples.csv) is provided only to test the importer. The fitted curve represents force versus CAD strut extension; it does not identify hysteresis, damping, motor dynamics, geometry, or physical safety by itself.

## Measured public reference for context, not calibration

NHTSA Vehicle Research and Test Center, *Investigation of Liftgate Strut Failure on 2004–2005 Toyota Sienna*, final report, August 2008, reports vehicle-specific support forces for the liftgate over several positions. Its documented liftgate and mounting geometry are different from this **original illustrative assembly**, so those force measurements must **not** be reused directly as per-strut force values or as a validation claim for RecursiveCal.

- [Official report](https://static.nhtsa.gov/odi/inv/2006/INRP-EA06020-30343.pdf)
- [Stabilus technical gas-spring information](https://www.solidcomponents.com/files/company/SCCKI48EO/companyfiles/doc/final_stabilus_techn._info_a4_e.pdf)
- [SAE 2020-01-0908, strut force and tailgate dynamics](https://saemobilus.sae.org/articles/damped-tailgate-system-drop-dynamics-evaluation-strut-force-durability-2020-01-0908)
