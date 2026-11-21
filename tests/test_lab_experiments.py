"""Behavioral tests for provenance, policy boundaries, and experiment replay."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import recursivecal as legacy
from recursivecal_lab.experiments import (
    ContextualBandit, EvaluationData, FiniteBank, FIRST_PROBE, SECOND_ACTIONS,
    paired_interval, probe_means, quality_matrix, run_experiment, validate_artifacts,
)


class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = FiniteBank(quadrature_order=3)

    def test_vectorized_model_matches_frozen_scalar_evaluator(self):
        # Independent scalar implementation is the frozen source, not another
        # call into the vectorized code under test. Include a guarded abort.
        plants = [legacy.Plant(), legacy.Plant(motor=.72, friction=.25, load=.39),
                  legacy.Plant(sensor_bias=.08, torque_deadzone=.22), legacy.Plant(motor=12.)]
        parameters = np.array([[p.motor, p.friction, p.load, p.damping, p.sensor_bias, p.torque_deadzone]
                               for p in plants])
        q = quality_matrix(parameters)
        means = probe_means(parameters)
        for i, plant in enumerate(plants):
            for j in (0, 19, 57, 89, 131, 149):
                self.assertAlmostEqual(q[i, j], legacy.calibration_quality(plant, legacy.CALIBRATIONS[j]), places=12)
            for j, probe in enumerate(legacy.PROBES):
                expected = legacy.measurement_prediction(plant, probe)
                np.testing.assert_allclose(means[i, j, :len(expected)], expected, atol=1e-13, rtol=0)

    def test_decisions_do_not_receive_hidden_parameters_or_other_probe_values(self):
        data = self.bank.make_data(32, "finite_test")
        model = ContextualBandit(13)
        baseline = model.actions(self.bank.features(data.observations[:, FIRST_PROBE]))
        modified = data.observations.copy()
        modified[:, 1:] += 1000.0
        # Counterfactual unseen observations do not change a decision made
        # before those probes. Neither parameters nor rewards enter features.
        np.testing.assert_array_equal(baseline, model.actions(self.bank.features(modified[:, FIRST_PROBE])))
        alternate_truth = EvaluationData(data.cohort, data.observations, data.parameters * 3,
                                         data.asymmetry, np.zeros_like(data.quality), data.episode_ids)
        original = self.bank.score(data, FIRST_PROBE, baseline)
        altered = self.bank.score(alternate_truth, FIRST_PROBE, baseline)
        np.testing.assert_array_equal(original["calibration"], altered["calibration"])
        self.assertFalse(np.array_equal(original["reward"], altered["reward"]))

    def test_episode_splits_have_distinct_identifiers_and_noise(self):
        train = self.bank.make_data(32, "train")
        validation = self.bank.make_data(32, "validation")
        test = self.bank.make_data(32, "finite_test")
        self.assertFalse(set(train.episode_ids) & set(validation.episode_ids))
        self.assertFalse(set(train.episode_ids) & set(test.episode_ids))
        self.assertFalse(np.array_equal(train.observations, test.observations))
        np.testing.assert_array_equal(test.observations, self.bank.make_data(32, "finite_test").observations)

    def test_structural_shift_breaks_mirror_symmetry(self):
        data = self.bank.make_data(16, "directional_friction")
        shifted = probe_means(data.parameters, data.asymmetry)
        symmetric = probe_means(data.parameters)
        np.testing.assert_allclose(symmetric[:, 0], -symmetric[:, 2], rtol=0, atol=1e-13)
        self.assertGreater(np.max(np.abs(shifted[:, 0] + shifted[:, 2])), .001)

    def test_prior_calibration_baseline_and_budget_are_explicit(self):
        data = self.bank.make_data(16, "finite_test")
        no_probe = self.bank.score(data)
        np.testing.assert_array_equal(no_probe["cost"], np.zeros(16))
        np.testing.assert_array_equal(no_probe["calibration"], np.full(16, self.bank.prior_calibration))
        with self.assertRaises(ValueError):
            self.bank.score(data, 0, np.zeros(16, dtype=int))
        with self.assertRaises(ValueError):
            self.bank.score(data, -1, np.ones(16, dtype=int))
        actions, _ = self.bank.bayesian_second_actions(data.observations[:, 0])
        direct = self.bank.score(data, FIRST_PROBE, actions)
        shuffled = self.bank.score(data, FIRST_PROBE, actions[::-1])
        np.testing.assert_array_equal(np.sort(direct["cost"]), np.sort(shuffled["cost"]))
        self.assertLessEqual(direct["cost"].max(), 2.5)

    def test_checkpoint_replay_and_input_rejection(self):
        model = ContextualBandit(37)
        features = self.bank.features(self.bank.make_data(16, "validation").observations[:, 0])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            model.save(path)
            np.testing.assert_array_equal(model.values(features), ContextualBandit.load(path).values(features))
            invalid = json.loads(path.read_text())
            invalid["weights"]["b2"] = [1.0]
            path.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError):
                ContextualBandit.load(path)
        with self.assertRaises(ValueError):
            model.actions(np.zeros((16, 13)))
        with self.assertRaises(ValueError):
            model.actions(np.full((16, 12), np.nan))

    def test_paired_interval_respects_pairing(self):
        a = np.linspace(.1, .9, 100)
        result = paired_interval(a, a - .02, 56, 300)
        np.testing.assert_allclose(result["ci95"], [.02, .02], atol=1e-14)
        self.assertAlmostEqual(result["mean_difference"], .02)
        with self.assertRaises(ValueError):
            paired_interval(a, a[:-1], 56)

    def test_complete_quick_run_integrity_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "run"
            report = run_experiment(destination, train_size=32, test_size=16, seeds=(13,), quick=True)
            self.assertTrue(report["completed"])
            self.assertEqual(len(report["results"]), 5)
            self.assertTrue(validate_artifacts(destination)["valid"])
            with np.load(destination / "training_data.npz", allow_pickle=False) as training:
                self.assertEqual(len(training["train_episode_ids"]), 32)
            with gzip.open(destination / "episodes.csv.gz", "rt") as stream:
                self.assertIn("episode_id,cohort,policy", stream.readline())
            with self.assertRaises(ValueError):
                run_experiment(destination, train_size=32, test_size=16, seeds=(13,), quick=True)
            manifest_path = destination / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["source_sha256"]["recursivecal.py"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            failure = validate_artifacts(destination)
            self.assertFalse(failure["valid"])
            self.assertTrue(any("source differs" in error for error in failure["errors"]))


if __name__ == "__main__":
    unittest.main()
