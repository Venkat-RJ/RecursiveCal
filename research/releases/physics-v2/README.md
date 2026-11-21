# Physics foundation v2 evidence

`validation.json` records numerical checks of `recursivecal.si-liftgate/2`, also used by the persistent rig. It contains the parameters, command schedules, independent reference states, errors at each timestep, contact cases, long-motion results, gate criteria and source hashes.

`historical-evidence.json` pins the source revision and hashes for the archived version 1 evidence. It prevents old reports from being silently relabelled as results of the new kernel. No version 1 artifact is overwritten by this work.

Run from the repository root:

```bash
python -m pip install -e '.[validation]'
python -m unittest discover -s tests -p 'test_mechanics_foundation_v2.py' -v
python scripts/validate_physics.py --output artifacts/physics-validation.json
```

All operations run in the current terminal. The audit requires no API key, paid compute or GPU. SciPy is needed only for independent validation; the core simulator does not depend on it.

These are synthetic mechanics checks. They do not establish hardware accuracy, safe operating limits or an advantage for an investigation policy. Full scope and limitations are in [the validation note](../../../docs/PHYSICS_VALIDATION.md).
