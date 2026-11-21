# Protocol for independent physical evidence

This document specifies what data would change the project's validation status. It is not a record of completed hardware testing. The software needed to ingest, fit, compare, and retain these data is implemented in this release. No real actuator was connected or actuated during development.

## Define the intended mechanism and claim

Identify the physical specimen, mounting coordinates, coordinate origin, angle limits, and holding architecture. Establish whether the motor disengages, remains actively controlled, uses a brake, or drives a self-locking transmission. The current model defaults describe none of those architectures accurately without checking the actual hardware.

Choose a bounded claim such as "predicts hinge angle within a specified error over this measured opening envelope". Avoid a general safe-controller or automotive-certification claim. Record the approved error thresholds, conditions, and held-out units before examining validation traces.

## Measurement records

| Record | Required observations | Implemented input/output path |
| --- | --- | --- |
| Geometry | Hinge location, centre of mass estimate, both strut mounts, closed/open pin lengths | SI parameter JSON with acquisition notes |
| Gas-force curve | Pin length, axial force of each strut, temperature, loading direction, specimen ID | Force CSV, explicit train/validation labels, metadata sidecar |
| Motion | Synchronized timestamp and calibrated hinge angle; velocity if independently available | Trajectory CSV and metadata sidecar |
| Actuation | Requested and actual actuator effort or measured current with a separately identified conversion | Retained raw acquisition data; this model consumes force, not an unvalidated current proxy |
| Passive support | Hold angle, unpowered drift, holding-device state, temperature, strut condition | Passive-hold simulation plus independent angle replay |

Document sensor units, calibration records, sample timing, missing samples, filtering, and uncertainty. The parser requires SI values and refuses silent conversion. A useful dataset identifier records specimen and acquisition session, not merely a row number.

## Separation of fitting and validation

Fit the force curve only on declared training acquisitions. Hold out complete runs, temperatures, or specimens where the proposed claim requires that generalization. Randomly splitting neighboring samples from one motion trace can underestimate error and does not test transfer to another mechanism.

Select model structure and controller settings using training data. Use validation data to evaluate the chosen model. Do not align time, remove inconvenient segments, or revise thresholds after viewing errors without recording that decision as exploratory. Retain raw and processed files with transformation code and hashes.

The implemented two-parameter force fit does not identify mass, inertia, friction, sensor bias, or latency. Obtain those parameters independently or implement and verify a specifically identifiable estimation procedure before using them as measured coefficients.

## Controlled test sequence

Begin with geometry and isolated force measurements, then low-energy supported motion, then full intended trajectories only after the responsible test engineer accepts the setup. A supported fixture and independent stopping mechanism are necessary for a physical hatch; the software's speed monitor does not stop hardware. Keep people outside the moving or falling mechanism's path.

Exercise opening, closing, repeated motion, relevant temperatures, degraded assistance, and loss of power under the mechanism's actual architecture. Define the permitted operating envelope and stop conditions from the real rig. The synthetic defaults are not operating instructions for a vehicle.

For each comparison, save the CSV, metadata, fitted parameter set, simulation JSON, residual report, threshold rationale, and source revision. Report the worst errors and failure conditions as well as averages. Test more than the acquisition used to build the model.

## Evidence status

The current release completes software interfaces and numerical checks. Physical validation remains **not established** because independent measurements and a real rig were not available. This is a factual limit on the present evidence, not a hidden software implementation task. A future dataset can pass or fail a declared comparison without changing the reporting machinery.

Hardware-in-the-loop operation additionally requires an actual I/O adapter, timestamp and latency verification, failure handling, and independent physical safeguards. No such adapter is claimed in version 0.3. The project's existing CAD explorer and new local workbench are software simulations.

