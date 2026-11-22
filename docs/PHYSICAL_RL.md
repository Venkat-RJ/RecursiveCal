# Physical calibration RL task

The physical task connects an observation-only policy to the version 3 research rig. Its identifiers are:

| Contract | Identifier |
| --- | --- |
| Task and reward | `recursivecal.physical-calibration-rl/1` |
| Physical plant | `recursivecal.physical-rig/3` |
| World sampler | `recursivecal.physical-world-sampler/1` |
| Sealed episode report | `recursivecal.physical-rl-episode/1` |
| Optional Verifiers plugin | `recursivecal-physical` |

This is separate from the earlier normalized benchmark and its `recursivecal-v1` Verifiers registration. A policy evaluated on that earlier benchmark has not thereby been evaluated on this physical rig.

The plant includes two electrical drives, winding temperature, a declared holding brake and sampled instruments. Read [the rig specification](RESEARCH_RIG.md) for its equations, numerical scope and unsupported effects. All default coefficients and sensors are synthetic. This release provides an executable task and baseline rollouts; it does not claim a trained physical RL policy or measured-hardware accuracy.

## Run a CPU-only baseline in the foreground

The core task requires the normal NumPy-only project installation. It does not call a model provider or need a GPU.

```bash
python -m pip install -e .
recursivecal rl-schema
recursivecal rl-rollout --split test --seed 7 --policy no_probe --output runs/physical-no-probe.json
recursivecal verify-rl runs/physical-no-probe.json
recursivecal rl-rollout --split test --seed 7 --policy fixed --output runs/physical-fixed.json
recursivecal verify-rl runs/physical-fixed.json
```

The commands run in the current terminal. An existing output path is protected unless `--overwrite` is explicitly supplied.

`no_probe` explicitly abstains and retains the nominal calibration. `fixed` requests the high, low and mid sweeps in that order, then commits nominal values if the episode has not already ended. It checks the real engine, acquisition, budget, commitment and verifier wiring. It does not fit a controller, train a policy, or establish that this sequence is a useful diagnostic baseline. A negative reward or rejected candidate can be a valid completed rollout.

Each report contains the observation-only policy transcript, the exact sampled world, frozen commitment, complete verification traces, reward components and source hashes. The sampled world and verifier evidence are evaluator-only records, available after the terminal decision.

`verify-rl` checks the digest and protocol consistency, including the sampled split, diagnostic cost, committed history, terminal reward and motion metrics checked against sealed traces. It also checks every policy observation against the public contract and the corresponding experiment history, remaining budget and episode progression. Undeclared evaluator fields and inconsistent transcript observations are rejected even when the report digest has been recomputed. It does not rerun the physical simulator or authenticate the report's author. A report with valid integrity can still contain a failed calibration.

## Python episode interface

```python
from recursivecal_lab.rl_environment import PhysicalCalibrationEnv, verify_episode_report

env = PhysicalCalibrationEnv(budget=8.0, max_tests=5)
observation, info = env.reset(seed=7, split="test")

observation, reward, terminated, truncated, info = env.step(
    {"experiment": "high_sweep"}
)

if not (terminated or truncated):
    observation, reward, terminated, truncated, info = env.step({"abstain": True})

# Evaluator-side evidence; this must not be fed back as another policy observation.
report = env.host_report()
assert verify_episode_report(report)["valid"]
```

`reset` and `host_report` are host operations. A policy receives only the returned public observations. Calling `host_report` before commitment or forced termination raises an error. Calling `step` after termination also raises; the host must explicitly reset for a new episode.

The API follows the familiar five-value step convention but is not a Gymnasium subclass. Its variable-length sensor history and structured calibration action use a JSON contract rather than fabricated fixed-size Box spaces. `rl-schema` and `protocol()` return that contract.

### Policy observations and actions

Observations include timestamped angle, angular rate, axial force per strut, declared ambient temperature, acquisition age, permitted experiment history, legal actions and remaining budget. Both the controller and policy use the declared sampled instrument pipeline. The policy does not receive true physical parameters, the sampled split or seed, per-side electrical telemetry, tracking quality or verifier results during the episode.

Each action must contain exactly one key:

```json
{"experiment": "high_sweep"}
```

```json
{"commit": {"mass_kg": 25, "motor_efficiency": 1, "gas_scale": 1, "friction_coulomb_Nm": 6, "sensor_bias_rad": 0}}
```

```json
{"abstain": true}
```

A commitment must contain all five fields, with finite values inside the bounds reported in the observation. `motor_efficiency` is the existing field name for motor effectiveness; in version 3 it scales the reciprocal torque and back-EMF constants, not an energetic efficiency.

The physical catalog supplies `low_sweep`, `high_sweep`, `mid_sweep`, `hold`, `coast` and `reference`. Only currently legal, affordable actions can be selected. State persists across experiments. The external reference fixture is an explicit bench operation, not a free reset of elapsed time or drive heat.

The default budget is eight declared test-cost units with at most five experiments. Cost includes protocol setup assumptions and is not wall-clock time, electrical energy or money. A test that aborts still pays its declared cost. Two invalid actions truncate the episode. Diagnostic limits or drive trips force nominal abstention. Commitment is allowed once, followed by fresh verifier states and no return to the policy.

## Continuous, disjoint sampled worlds

The sampler varies the following six dimensions. Temperature is an observed condition, not a sixth calibration estimate.

| Dimension | Sampling range |
| --- | --- |
| Moving mass | 22 to 32 kg |
| Motor effectiveness | 0.70 to 1.00 |
| Gas-force multiplier | 0.80 to 1.10 |
| Coulomb friction | 4 to 12 N·m |
| Encoder bias | −0.020 to +0.020 rad |
| Ambient temperature during investigation | 10 to 35°C |

Each dimension is divided into eight cells. SHA-256 of the sampler version and six-dimensional cell assigns the entire cell to a bucket: buckets 0 through 6 are training, bucket 7 is validation, and buckets 8 and 9 are test. Continuous values are sampled within the declared range until the requested split's cell is selected. Split names and seeds initialize independent deterministic generators; seed ranges alone do not define the split.

This keeps a parameter cell out of the other splits, while permitting interpolation across nearby cells. It is not a claim of transfer to unseen hardware or radically different physics. The world identifier hashes the actual plant and fault configuration, and the episode identifier additionally includes the acquisition and evaluator seeds. They are retained only in host evidence.

The separate `ood` split adds either 12 to 24 N·m of closing-direction friction or unequal side effectiveness: left 0.45 to 0.65 and right 0.90 to 1.05. These effects lie outside the five-field calibration description. An OOD label does not guarantee that every case is distinguishable or should be rejected. In particular, two motors acting on one rigid hinge can have indistinguishable aggregate responses. Identifiability must be studied under the available observations.

The four verifier profiles are full opening, full closing, partial reversal and cold opening. Both the nominal and candidate controller receive the same new initial conditions and paired sensor seeds. Their calibration stays frozen throughout those checks. These are prescribed development profiles, not an undisclosed final benchmark.

## Frozen terminal reward

Every nonterminal step returns reward zero. After the terminal calibration is sealed, let each verifier profile have quality:

```text
q = exp(-((tracking_RMSE / 3 degrees)^2 + (final_error / 2 degrees)^2))
```

An incomplete profile, a peak-speed breach or a saturation-fraction breach has quality zero. `Q` is the mean of the four profile qualities, bounded between zero and one. Motion acceptance still requires every explicit threshold, including completion, RMSE at most 3°, absolute final error at most 2°, peak speed at most 1.15 rad/s and saturation fraction at most 0.35.

The reward is:

```text
R = Q(candidate) - Q(nominal)
    - 0.012 * diagnostic_cost
    - 1.0 if a candidate commitment fails motion verification
    - 1.0 if the episode is forcibly ended
```

Explicit abstention commits nominal values, so its improvement is exactly zero and its reward is minus consumed test cost. A failed candidate cannot receive a positive reward by improving some metrics while missing a required limit. Diagnostic aborts, invalid-action truncation, a model stopping without commitment, and host turn-limit termination receive the forced-end penalty.

`force_end("agent_stopped")` is a host-only operation. It seals nominal calibration and evaluates the same verifier conditions. Stopping a model response stream is therefore not a free zero-reward alternative to deciding whether to abstain. Simulator or infrastructure exceptions remain errors; the adapter does not silently score them as policy failures.

## JSON dialogue boundary

`recursivecal_v1.physical_protocol.PhysicalCalibrationDialogue` wraps the same environment for a language-model harness. `observation()` returns JSON, and `act(response)` returns the next JSON response and a completion flag. The final reply states that the decision was submitted; it does not return verifier scores or truth as another policy turn. The host calls `reward()` and `host_report()` separately.

The Python API prevents accidental disclosure through its observation contract. It does not isolate adversarial code in the same interpreter. Keep the evaluator outside an agent's coding process and expose only the JSON messages. Completed host reports must not be mounted into the agent's workspace or replayed as permitted observations.

## Optional Prime Intellect Verifiers plugin

Install the optional SDK in an appropriate environment:

```bash
python -m pip install -e '.[verifiers]'
```

The supported dependency range is Verifiers 0.4.x. The integration uses its real `Task`, `Taskset`, `Env`, `Interaction` and `Trace` APIs. The plugin ID is `recursivecal-physical`; its import package is `recursivecal_physical`. The original `recursivecal-v1` registration remains separate.

Configuration can be constructed without starting a model:

```python
import verifiers.v1 as vf
from recursivecal_v1.physical_taskset import (
    PhysicalCalibrationTasksetConfig,
    PhysicalCalibrationVerifierConfig,
)

config = PhysicalCalibrationVerifierConfig(
    taskset=PhysicalCalibrationTasksetConfig(
        split="test", seed_start=0, num_tasks=4,
    ),
)
environment = vf.load_environment(config)
tasks = list(vf.load_taskset(config.taskset))
```

The default dataset is finite and reproducible. Its task names are opaque identifiers. Seed and split stay on the evaluator's task and are removed from the task passed into the agent interaction. The task prompt is empty because the environment opens the interaction with its initial sensor observation.

The plugin selects the SDK's tool-less `null` harness and a local subprocess runtime. It rejects a coding-harness override for this observation-only protocol. The default agent turn cap is eight. The SDK interaction is closed before terminal rewards, metrics or optional complete evidence are added to its trace.

After configuring a model endpoint and its credentials through Verifiers, a small model evaluation can be started in the foreground:

```bash
vf-run recursivecal-physical -m YOUR_CONFIGURED_MODEL -n 4 -c 1 --env.taskset.split test
```

This command invokes the selected model endpoint and may incur provider charges. It is separate from the CPU-only baseline and SDK smoke checks above; no model evaluation is required to verify the environment installation.

The CLI and interaction usage follow the official [v0.4.1 runner](https://github.com/PrimeIntellect-ai/verifiers/blob/v0.4.1/verifiers/v1/cli/run.py), [interaction contract](https://github.com/PrimeIntellect-ai/verifiers/blob/v0.4.1/verifiers/v1/agent.py), [plugin loader](https://github.com/PrimeIntellect-ai/verifiers/blob/v0.4.1/verifiers/v1/utils/loaders.py) and [null harness](https://github.com/PrimeIntellect-ai/verifiers/blob/v0.4.1/verifiers/v1/harnesses/null/harness.py).

### SDK compatibility check without a model

```bash
RECURSIVECAL_REQUIRE_VERIFIERS=1 python -m unittest discover -s tests -p 'test_physical_adapter.py' -v
```

These tests use the installed SDK's loaders, configuration validation, task iteration, segment type and trace reward recording. Responses are scripted; the tests make no model call and require no API key. Separate CI jobs install Verifiers 0.4.0 and 0.4.1 with the strict flag, so an absent SDK cannot silently become a skipped compatibility check. A normal core installation skips these optional SDK tests.

The physical contract tests also exercise real version 3 episodes. A privileged known-parameter control establishes that the task can reward a calibration improvement. That control receives evaluator truth and is explicitly not a learned policy or an information-budget-compliant competitor.

## Research limits

This task supports experiments on choosing diagnostics and calibrating the five declared compensation parameters. It does not establish uniqueness of the inferred physical explanation, learned-policy superiority, a calibrated probability of safety, transfer from the older normalized benchmark, or real hardware operation.

Freeze a training protocol, compare against meaningful fixed and adaptive baselines under equal budgets, and report independent evaluation before making a learning claim. Physical accuracy still requires the measured evidence in [the hardware protocol](HARDWARE_PROTOCOL.md).
