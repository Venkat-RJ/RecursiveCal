# Physical inquiry fixture audit

Synthetic development fixture suite. No population inference, preregistration or RL advantage claim.

Seed: 7. Unique physical conditions: 9. Policy runs: 27.

Each compressed JSON contains the full report, including both comparison traces and source hashes. The manifest records the byte digest of every archive.

| Condition | Policy | Tests | Cost | Mean RMSE before | Mean RMSE after | Motion checks | Outcome |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| nominal | bayes | 3 | 4.5 | 0.915° | 0.915° | 4/4 | verified_in_simulation |
| nominal | fixed | 3 | 5.6 | 0.915° | 0.915° | 4/4 | verified_in_simulation |
| nominal | no_probe | 0 | 0.0 | 0.915° | 0.915° | 4/4 | abstained |
| weak_motor | bayes | 3 | 4.5 | 7.185° | 0.915° | 4/4 | verified_in_simulation |
| weak_motor | fixed | 3 | 5.6 | 7.185° | 0.915° | 4/4 | verified_in_simulation |
| weak_motor | no_probe | 0 | 0.0 | 7.185° | 7.185° | 0/4 | abstained |
| payload | bayes | 3 | 4.5 | 5.863° | 1.059° | 4/4 | verified_in_simulation |
| payload | fixed | 3 | 5.6 | 5.863° | 1.059° | 4/4 | verified_in_simulation |
| payload | no_probe | 0 | 0.0 | 5.863° | 5.863° | 0/4 | abstained |
| friction | bayes | 3 | 3.9 | 3.087° | 0.855° | 4/4 | verified_in_simulation |
| friction | fixed | 3 | 5.6 | 3.087° | 0.855° | 4/4 | verified_in_simulation |
| friction | no_probe | 0 | 0.0 | 3.087° | 3.087° | 0/4 | abstained |
| gas_loss | bayes | 3 | 4.5 | 3.715° | 0.877° | 4/4 | verified_in_simulation |
| gas_loss | fixed | 3 | 5.6 | 3.715° | 0.877° | 4/4 | verified_in_simulation |
| gas_loss | no_probe | 0 | 0.0 | 3.715° | 3.715° | 0/4 | abstained |
| sensor_bias | bayes | 3 | 4.5 | 0.920° | 0.915° | 4/4 | verified_in_simulation |
| sensor_bias | fixed | 3 | 5.6 | 0.920° | 0.915° | 4/4 | verified_in_simulation |
| sensor_bias | no_probe | 0 | 0.0 | 0.920° | 0.920° | 4/4 | abstained |
| compound | bayes | 3 | 4.5 | 14.145° | 1.229° | 3/4 | verification_failed |
| compound | fixed | 3 | 5.6 | 14.145° | 1.229° | 3/4 | verification_failed |
| compound | no_probe | 0 | 0.0 | 14.145° | 14.145° | 0/4 | abstained |
| directional_friction | bayes | 4 | 6.0 | 4.253° | 4.253° | 2/4 | abstained |
| directional_friction | fixed | 3 | 5.6 | 4.253° | 4.253° | 2/4 | abstained |
| directional_friction | no_probe | 0 | 0.0 | 4.253° | 4.253° | 2/4 | abstained |
| overload | bayes | 2 | 2.2 | 18.435° | 18.435° | 0/4 | abstained |
| overload | fixed | 3 | 5.6 | 18.435° | 18.435° | 0/4 | abstained |
| overload | no_probe | 0 | 0.0 | 18.435° | 18.435° | 0/4 | abstained |

The nominal controller already satisfies the motion thresholds for the nominal and encoder-offset fixtures. Diagnostic expenditure is therefore not automatically beneficial. The combined-fault calibration fails the cold-opening final-position requirement even after correct identification. The directional-friction and overload fixtures trigger abstention.

Adaptive and fixed policies use the same inference bank and terminal calibration rule. Their differences concern experiment selection, cost and the resulting evidence. These cases do not establish that an RL policy has learned to investigate or that this Bayesian selector is optimal.

Reproduce from the repository root:

```bash
python -u scripts/physical_inquiry_audit.py --output runs/reproduced-physical-audit
```

See [the protocol](../../../docs/PHYSICAL_INQUIRY.md) for assumptions, instrument definitions, acceptance thresholds and physical validation limits.
