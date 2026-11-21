# RecursiveCal test workbench design

Updated 21 November 2026. This pass changes the interface and its inspection workflow. The CAD mesh, mechanical renderer and physics equations are unchanged.

## Research and decisions

The design draws on documented engineering workflows, rather than copying a vendor's branding or interface assets.

| Official source | Relevant pattern | RecursiveCal implementation |
| --- | --- | --- |
| [NI VeriStand: Viewing, Creating, and Interacting with Screens](https://www.ni.com/docs/en-US/bundle/veristand/page/screens.html) | Project files, configuration, instrument screens and runtime tools have distinct places in the editor. | A persistent experiment panel, central assembly view, signal inspector, and a separate Results view. |
| [ETAS LABCAR-OPERATOR](https://www.etas.com/ww/en/downloads/software-downloads-overview/labcar-operator-product-installer/) and [ETAS Experiment Environment overview in the vendor's LABCAR release document](https://etas.services/download-center-files/products_LABCAR_Software_Products/LABCAR-OPERATOR_V5.4.3_What_is_new.pdf) | An experiment environment exposes parameters and measurements, instrumentation, signal generation and recording. | Visible plant parameters, explicit controller settings, a fixed opening stimulus, and trace/run exports. The older release document is used for workflow context, not current feature/version claims. |
| [dSPACE ControlDesk](https://www.dspace.com/en/pub/home/products/sw/experimentandvisualization/controldesk.cfm) | Experiment management, instrumentation and synchronized measurement share one workspace. | CAD animation, signal values and the plot cursor use one simulation time. Angle, current and torque share the same playback controls. |
| [Vector CANoe](https://www.vector.com/en/product/canoe/) | Fault scenarios and graphical or textual evaluation support test workflows across software and hardware contexts. | Seven synthetic fault scenarios, factory/modified trajectory comparison, a metric table, and transparent illustrative acceptance checks. |

## Interface

- Light application panels and a dark CAD stage separate configuration from spatial inspection.
- Consistent blue and green signal colors identify factory and modified controllers. The target uses a dashed neutral line.
- The Run/Pause, Reset and Export controls stay in a consistent toolbar. Playback starts at the beginning on the first run, even though the initial inspection preview is at 3.25 s.
- The inspector labels physical units and distinguishes per-actuator current from total hinge motor torque.
- Selecting Compare supplies the fault-informed preset if no modified configuration exists, and tells the user what was applied.
- Factory selection displays the factory values. Moving a slider from Factory creates a modified configuration from those displayed values.
- The gravity slider accepts 0.01 increments so the existing 1.12 preset is represented exactly.
- Mobile layouts offer a Setup disclosure and vertically arranged assembly, inspector and trace panels.
- Keyboard support includes Space for playback outside controls, arrow keys for the focused CAD/plot, plus/minus for CAD zoom, and Escape to leave the expanded view. Focus styles, labels and pressed states are provided.

## Data and scope

Both full trajectories are computed whenever the setup changes. The animation is playback of these computed trajectories, not real-time execution against a hardware target. Results describe the full simulated cycle even while playback is paused.

The integrator advances in 10 ms steps. The exported trace contains 218 frames per controller: every third integration step and the final frame. CSV contains both controllers, for 436 data rows; JSON also records the plant, controller parameters, preset source, metrics and inspection position.

The three displayed checks are deliberately labeled illustrative: modified-controller mean tracking error at most 5 degrees, absolute final error at most 2 degrees, and sampled peak current at most 9.5 A per actuator. They are not engineering acceptance requirements, a hardware safety verdict, or a compliance claim. The current peak is computed from recorded frames, not from every integration step. The force metric is the peak of |motor force| plus gas force, matching the existing physics metric. Mechanical work is approximate and uses absolute motor work.

Presets use known synthetic fault parameters. This interface does not perform learned RL, autonomous fault diagnosis, real ECU execution, OEM measurement, or a certified HIL test. The model notes and exports state those limits.

## Verification

`tests/browser_smoke.py` accepts the generated standalone viewer by default, or any viewer `index.html` as a positional argument. The deployed portfolio copy runs the same check before publishing GitHub Pages.

The browser check covers initialization, all seven scenarios, numerical finiteness, exact preset representation, run/pause/reset/completion, side-by-side comparison, cutaway/labels, signal selection, keyboard inspection, CSV and JSON contents, Results, expanded view, model notes, and horizontal overflow at 1536, 1100, 820, 390 and 360 pixels. It saves screenshots and a structured report as CI artifacts for review.

Example:

```sh
python -m pip install 'playwright>=1.51,<2'
python -m playwright install chromium
python tests/browser_smoke.py viewer/index.html --artifacts artifacts/recursivecal-ui
```
