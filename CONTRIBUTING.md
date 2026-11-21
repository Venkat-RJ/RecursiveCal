# Contributing to RecursiveCal

Use Python 3.11 or later and work from a branch. Install with `python -m pip install -e '.[dev]'` and run `python -m unittest discover -s tests -v`. The core workbench and new experiment suite need only NumPy. Optional historical neural tests need `.[rl]`; the Prime Intellect adapter needs `.[verifiers]`.

Keep the frozen `recursivecal.py` benchmark unchanged when reproducing old scores. A change in equations, diagnostic timing, noise, calibration grid, or reward requires a new model identifier and a separately recorded result. Never overwrite historical result files to make old claims appear consistent with new code.

Every new model needs explicit units, parameter provenance, identifiable assumptions, numerical checks, and failure cases. A synthetic fixture must say synthetic in both metadata and filenames. Do not turn a measured CSV label into an assertion of independent validation: sensor calibration, mounting geometry, sampling, and a held-out validation protocol remain separate evidence.

For experiment changes, preserve disjoint data partitions and compare policies on the same evaluation cases. Tune schedules, thresholds, and hyperparameters before test evaluation. Store trial rows, checkpoints, versions, source hashes, and confidence-interval definitions. Report negative results and controls alongside favorable averages.

For workbench changes, run `python tests/workbench_smoke.py` with Playwright Chromium installed. The test owns its server process and stops it on completion. Check keyboard operation, mobile layout, import errors, early-stop events, and exports. Product interfaces should use physical units and distinguish simulations, measurements, and evidence files.

A contribution is ready when its relevant tests pass, clean wheel installation works, documentation commands run, and any affected source-bound experiment evidence is regenerated under a new run identity. Explain the problem, resulting behavior, and evidence in the pull request. Avoid unverified industrial performance, safety, or novelty claims.

