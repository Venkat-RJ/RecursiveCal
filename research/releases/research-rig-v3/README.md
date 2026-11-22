# Research rig 3 numerical evidence

`validation.json` is a browsable summary linked by compressed and uncompressed SHA-256 hashes to `validation.json.gz`. The gzip file preserves the complete original audit bytes, including declared inputs, reference trajectories, three integration refinements, error limits fixed before the run, energy checks, four healthy motion profiles, passive-support and power-loss tests, twelve stratified extreme conditions, and source hashes before and after execution. No trajectories are rounded or discarded.

Regenerate from the matching source revision:

```bash
python -m pip install -e '.[validation]'
python scripts/validate_research_rig.py --output artifacts/rig-validation.json
recursivecal rl-rollout --policy fixed --split test --seed 7 --output artifacts/rig-rl-smoke.json
python scripts/package_rig_evidence.py --validation artifacts/rig-validation.json \
  --rl-smoke artifacts/rig-rl-smoke.json --output research/releases/research-rig-v3
python scripts/check_release.py
```

All 19 gates pass in this record. The fault sweep retains rejected calibrations and guarded aborts as explicit outcomes. It is not a report of twelve successful calibrations. Numerical verification does not establish measured physical accuracy.

`rl-smoke.json.gz` is a losslessly compressed, seeded test-split episode produced by the fixed-action policy. Its content digest is unchanged by compression. It exercises the public observation/action contract, sealed commitment, evaluator and report verification. The verification command checks recorded integrity and protocol consistency; it does not rerun the physics. This is a pipeline smoke result, not a learned-policy benchmark.

```bash
recursivecal verify-rl research/releases/research-rig-v3/rl-smoke.json.gz
```

See [the specification](../../../docs/RESEARCH_RIG.md), [readiness scope](../../../docs/SIMULATOR_READINESS.md) and [physical RL contract](../../../docs/PHYSICAL_RL.md).
