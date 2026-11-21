# Source and data provenance

## Source baseline

The implementation began from public repository commit `b08153b7d25f671963fc0d8fabe13bd046823c07`. All 87 source files were retrieved from that commit and checked against their Git blob hashes before changes. The normalized reference file `recursivecal.py` remains byte-for-byte the original blob `2d939005aaa177ba8d9f4d2296db0577c6bb3111`.

The historical CAD simulator remains `mechanics/cad_v1/simulation/physics_v2.py`, original blob `fb6f903631a036d2f0d6e7ec1a3f556a7a3a10cc`. The new SI simulator is a separate implementation with a separate model identifier. It retains the illustrative mounting geometry, exposes more assumptions and failure modes, and records its source digest in the physical audit.

## What generated the data

| Evidence | Data origin | Scope |
| --- | --- | --- |
| Historical normalized experiments | Synthetic coefficients and Gaussian observation noise in repository code | Reproduces earlier benchmark behavior |
| New diagnostic experiment | Ten synthetic hypotheses, independent RNG streams, specified parameter and directional-friction shifts | Evaluates a restricted diagnostic policy problem |
| SI motion traces | New explicit single-axis equations and assumed coefficients | Numerical and software-in-the-loop experiments |
| Force CSV example | Synthetic force curve plus seeded artificial measurement noise | Exercises fitting and split handling |
| Trajectory CSV example | Samples from the same SI simulator plus artificial observation error | Exercises replay and residual reporting |
| User-imported CSV | Provider-declared source and units, with recorded file hash | Dataset agreement, subject to the declaration's reliability |
| NHTSA reference | Public report on a particular Toyota Sienna liftgate architecture | Motivates passive-hold failure testing; not used as fitting or training labels |

No production-vehicle data, proprietary OEM model, downloaded RL training dataset, real load-cell recording, or physical test bench was used to generate this release. The data paths are implemented and tested with labeled synthetic inputs.

## Independent engineering reference

National Highway Traffic Safety Administration, *Engineering Analysis Report: EA06-020, Toyota Sienna Power Liftgates*, June 2008: <https://static.nhtsa.gov/odi/inv/2006/INCR-EA06020-29305P.pdf>.

That report concerns a specific design with gas support after motor disengagement. Its dimensions and force measurements are not transplanted onto this project's different geometry. A brake, latch, or self-locking transmission changes the support requirement. The reference establishes the relevance of an architecture-dependent test, not the accuracy of RecursiveCal's coefficients.

## Research method references

- Patterson, Neumann, White, and White. *Empirical Design in Reinforcement Learning*. JMLR 25(318), 2024. <https://jmlr.org/papers/v25/23-0183.html>
- Agarwal, Schwarzer, Castro, Courville, and Bellemare. *Deep Reinforcement Learning at the Edge of the Statistical Precipice*. NeurIPS 2021. <https://proceedings.neurips.cc/paper_files/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html>

These motivate careful baselines, explicit experiment selection, uncertainty reporting, and separation of seed variability from trial variability. They do not validate the model or establish novelty of this work.

## Artifact integrity

Diagnostic runs retain exact source hashes, runtime versions, protocol bytes, split seeds, selected settings, model checkpoints, raw observations, and per-policy trial outcomes. `recursivecal verify` detects inconsistency with the recorded source or files and reconstructs aggregates and learned decisions. Hash consistency is evidence of integrity, not proof of scientific correctness or independent authorship.

The public protocol and development results make this an exploratory study. Fresh RNG streams and checkpoints fixed before test generation prevent direct tuning inside one run, but do not turn a public, iteratively developed task into an independently blinded confirmation.

The README banner is labeled AI-generated concept artwork. It is not a built apparatus or a numerical figure. Paper figures are generated from the saved machine-readable results.

