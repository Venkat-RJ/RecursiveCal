# First sequential-choice gate audit (21 November 2026)

This is a post-run descriptive audit of an **exploratory 64-case-per-cohort smoke run**, not a pre-registered hypothesis test. The recorded evidence is the GitHub Actions artifact `recursivecal-sequential-inquiry-v0`, run [44911499799](https://github.com/Venkat-RJ/RecursiveCal/actions/runs/44911499799), generated with `--train 256 --validation 128 --test 64 --quadrature 5`. The episode file SHA-256 is `3cce83079821380e4e819738134143978b919dd97618cacccf8286c601577714`. Each of five cohorts contains the **same 64 cases** evaluated under three policies, resulting in 960 policy-case records, not 960 independent plants.

## Baselines and observed scores

The fixed schedule `[0,6]` is low positive pulse plus a sensor reference. All reported values are mean `calibration_quality - 0.012*probe_cost`; higher is better.

| Cohort | No probe | Fixed schedule | Bayesian myopic |
| --- | ---: | ---: | ---: |
| Finite test | 0.848668 | 0.877788 | 0.892754 |
| Continuous jitter | 0.830965 | 0.871245 | 0.883159 |
| Unseen high load | **0.931536** | 0.881974 | 0.894911 |
| Extreme deadzone | 0.517579 | 0.504811 | **0.522811** |
| Directional friction | 0.809279 | **0.828061** | 0.812842 |

The Bayesian myopic strategy chose the same first probe (`pulse_pos_low`) on all 320 test cases and **never used a third probe**. In the finite cohort, it used only the first probe on 30/64 cases, added the reference on 20, and added the high positive pulse on 13. Thus allowing a three-probe horizon did not make this frozen task meaningfully deeper. This is an observed negative design result.

## Distinguish cost savings from better calibration

| Cohort | Method | Mean terminal quality | Mean test cost |
| --- | --- | ---: | ---: |
| Finite test | No probe | 0.84867 | 0.000 |
| Finite test | Fixed | 0.90779 | 2.500 |
| Finite test | Bayesian myopic | 0.91300 | 1.688 |
| Unseen high load | No probe | **0.93154** | 0.000 |
| Unseen high load | Fixed | 0.91197 | 2.500 |
| Unseen high load | Bayesian myopic | 0.91197 | 1.422 |
| Directional friction | No probe | 0.80928 | 0.000 |
| Directional friction | Fixed | **0.85806** | 2.500 |
| Directional friction | Bayesian myopic | 0.82559 | 1.062 |

In unseen high-load conditions, the prior-optimal **zero-test calibration** is better in raw quality than the tested Bayes-selected calibration. The difference cannot be explained by measurement cost alone. In directional friction, the fixed schedule's second test materially improves raw quality, while the myopic Bayes strategy tends to stop early and sacrifice that improvement.

No seed uncertainty or paired interval is asserted from these small smoke numbers. The task was designed and inspected within this project; choices of test families and policies were not blinded.

## Research decision

This gate validates the reproducible episode and cost contracts, but **fails** to demonstrate a genuinely longer investigation problem or the role of RL. Do not publish this as a new algorithmic result. The next environment introduces hidden persistent thermal-friction state whose response to a probe depends on earlier probes, documented in `STATEFUL_PROTOCOL.md`. That mechanism must be tested against honest stateful Bayesian and fixed-order baselines before any RL superiority claim.
