# RecursiveCal | Parametric Mechanical Test Cell (CAD v0.2)

An **original, editable mechanical assembly** of a power tailgate with a single rotational hinge, a rigid hatch, two motorized telescoping struts and a host-side simulation. The geometry, strut kinematics, force calculations and live visualization share one set of mount coordinates.

This is a **mechanical research demonstrator**, not an OEM tailgate, production CAD, an engineering design verified for manufacture, or a real-hardware control application. It is independent of RecursiveCal's earlier normalized-actuator reinforcement-learning environment.

## What can be inspected

- **69 named components:** rear body aperture, hatch shell/window, reinforcements, dual hinge brackets, pivot shaft, ball joints, powered-strut housings, gland seals, piston rods, latches, and mounting brackets.
- **Native CAD exports:** closed and open [STEP](assets/recursivecal_tailgate_closed.step) assemblies and [GLB](assets/recursivecal_tailgate_open.glb) meshes. Parts and colors are named in the CAD hierarchy. Parametric source is [cad/build_assembly.py](cad/build_assembly.py).
- **Motion:** 0 to 78° travel. Each strut length is determined by fixed and hatch-mounted pivots. Closed length **567.67 mm**, full-open length **941.20 mm**, travel **373.53 mm**.
- **Dynamics:** hatch inertia, gravity, gas assist, coupled motor force, hinge friction and a bounded feedback controller. The same strut moment arm, **dL/dθ**, determines torque and motion.
- **Interactive test:** [CAD laboratory](viewer/index.html) and an [offline single-file version](viewer/RecursiveCal_CAD_Lab.html). Orbit, inspect cutaway, run or pause the motion, inject seven faults, change controller gains and compare before/after.
- **Measured-data path:** A load-cell CSV schema and curve fitter are provided. No real liftgate load-cell data was used to fit this model.

![Render generated from CAD solids, 78 degree pose](assets/mechanical_open.png)

## Model boundaries

| Quantity | Current value | Provenance |
|---|---:|---|
| Opening angle | 78° | Illustrative design |
| Hatch mass | 25 kg | Assumed |
| Hinge height | 1.76 m | Assumed |
| Hinge inertia | 12 kg·m² | Assumed |
| Strut force at open | 165 N each | Assumed gas spring model |
| Strut force at closed | 212 N each | Assumed gas spring model |
| Drive force cap | 330 N per strut | Assumed limit |
| Mounting geometry | See `assets/assembly_metadata.json` | Parametric CAD |

**These values are not manufacturer measurements.** This version models one rotational DOF; no vehicle-grade flexible body, wiring harness, anti-pinch model, latch force dynamics, thermal/electrical motor model, ECU, CAN bus, or certified hardware safety is implemented.

The code also includes a public-reference discussion in [measurement protocol](docs/measurement_protocol.md). A 2008 [NHTSA vehicle-specific liftgate report](https://static.nhtsa.gov/odi/inv/2006/INRP-EA06020-30343.pdf) shows why actual load-cell and temperature data matter; its measured forces were **not** transplanted into this different geometry.

## Quick start

```bash
python -m pip install cadquery numpy scipy trimesh
python cad/build_assembly.py
python cad/render_assembly.py
python cad/export_viewer_mesh.py
python viewer/build.py
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/test_browser.py
```

Core dynamics: `python simulation/physics_v2.py`. All 11 unit checks passed locally, plus browser interactions and a 7-scenario Python/JS parity audit. The viewer works with a software-3D fallback where WebGL is unavailable; the hardware WebGL pathway has not been independently tested in that environment.

To fit your **own** instrumented strut-force curve:

```bash
python simulation/fit_force_curve.py path/to/real_measurements.csv --out fitted_curve.json
```

The included `SYNTHETIC_force_samples.csv` is **synthetic and labeled**, only an importer example. A fitted curve cannot establish real-hardware safety or identify hinge inertia, motor dynamics, damping or geometry by itself.

## Current comparison

A demonstrative combined fault has weakened drive, increased friction and greater hatch mass. In this model:

| Controller | Final angle | Target | Mean absolute tracking error |
|---|---:|---:|---:|
| Assumed factory calibration | 58.11° | 78° | 12.795° |
| Model-informed modified preset | 70.77° | 78° | 5.684° |

The modified preset has knowledge of the injected fault. **It is not a learned policy, autonomous diagnosis, or RL result.** Results are illustrative and should not be used to claim real vehicle performance.

## Verification and next research step

1. Acquire real mounting dimensions, actuator force/stroke curves, hatch mass/inertia, and synchronized ECU/motor measurements.
2. Identify and validate the plant against separately withheld physical cycles, including temperature and aged struts.
3. Add electrical motor, latch, obstacle detection and multi-body constraints only after data establishes their relevance.
4. Connect the validated physical task to RecursiveCal's agent experiment-selection interface and then test a learned policy against Bayesian system identification.

**Sources used for engineering context:** [SAE strut dynamics](https://saemobilus.sae.org/articles/damped-tailgate-system-drop-dynamics-evaluation-strut-force-durability-2020-01-0908), [Stabilus gas-spring technical information](https://www.solidcomponents.com/files/company/SCCKI48EO/companyfiles/doc/final_stabilus_techn._info_a4_e.pdf), [NHTSA liftgate strut investigation](https://static.nhtsa.gov/odi/inv/2006/INRP-EA06020-30343.pdf).

MIT-licensed independent research prototype.
