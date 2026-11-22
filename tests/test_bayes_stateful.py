"""Classical stateful Bayesian filter contracts and missing-model ablation."""
from __future__ import annotations
import unittest
import numpy as np
from research.sequential_inquiry.stateful_plant import StatefulEpisode, PROBES
from research.sequential_inquiry.bayes_stateful import BayesianBank, BayesianBelief, evaluate_one, schedules


class StatefulBayesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = BayesianBank(particles=12)

    def test_prior_and_posterior_normalization(self):
        belief = BayesianBelief(self.bank, seed=7)
        self.assertAlmostEqual(float(belief.weights.sum()), 1.)
        ep = StatefulEpisode(79, "finite_test")
        for name in ("pulse_pos_high", "pulse_neg_low", "reference_check"):
            reading = ep.step(name)
            belief.update(next(i for i, probe in enumerate(PROBES) if probe.name == name), reading)
            self.assertAlmostEqual(float(belief.weights.sum()), 1., places=12)
            self.assertTrue(np.isfinite(belief.weights).all())
        self.assertGreater(float(np.max(belief.heat)), 0.)

    def test_thermal_history_changes_model_prediction(self):
        belief = BayesianBelief(self.bank, seed=7)
        b = next(i for i, probe in enumerate(PROBES) if probe.name == "pulse_neg_low")
        cold, _, _ = belief.forecast(b)
        ep = StatefulEpisode(3, "finite_test")
        high = next(i for i, probe in enumerate(PROBES) if probe.name == "pulse_pos_high")
        belief.update(high, ep.step("pulse_pos_high"))
        warm, _, _ = belief.forecast(b)
        if any(p.thermal_friction > 0 for p in self.bank.plants):
            self.assertGreater(float(np.max(abs(cold - warm))), 1e-4)

    def test_misspecified_prior_explicitly_omits_thermal_family(self):
        missing = BayesianBank(particles=12, include_thermal=False)
        self.assertTrue(all(p.thermal_friction == 0 for p in missing.plants))
        self.assertEqual(len(self.bank.plants), len(missing.plants))

    def test_decisions_use_real_records_and_valid_actions(self):
        result = evaluate_one(self.bank, 71, "finite_test", "myopic", samples=8)
        self.assertLessEqual(result["probes"], 3)
        self.assertLessEqual(result["cost"], 3.5)
        self.assertEqual(len(result["measurements"]), result["probes"])
        self.assertTrue(0 <= result["calibration"] < 150)
        self.assertTrue(all(len(s) <= 3 for s in schedules()))


if __name__ == "__main__":
    unittest.main()
