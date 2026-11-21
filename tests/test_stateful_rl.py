"""Independent policy-gradient contracts for the exploratory stateful testbed."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from research.sequential_inquiry.bayes_stateful import BayesianBank, BayesianBelief
from research.sequential_inquiry.stateful_plant import StatefulEpisode, PROBES
from research.sequential_inquiry.train_rl import ACTIONS, Actor, episode, evaluate, features, train


class StatefulRLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = BayesianBank(particles=12)

    def test_features_rely_on_public_observations_and_belief(self):
        env = StatefulEpisode(81, "finite_test")
        belief = BayesianBelief(self.bank)
        first = env.observe()
        x0 = features(first, belief)
        # Simulator truth and unchosen measurements are not exposed.
        self.assertEqual(set(first), {"measurements", "legal_actions", "remaining_budget"})
        self.assertTrue(np.isfinite(x0).all())
        next_record = env.step("pulse_pos_high")
        belief.update(next(i for i, p in enumerate(PROBES) if p.name == "pulse_pos_high"), next_record)
        x1 = features(env.observe(), belief)
        self.assertFalse(np.array_equal(x0, x1))
        # Privileged values are never arguments to features or Actor.choose.
        self.assertEqual(features(env.observe(), belief).shape, x0.shape)

    def test_action_mask_and_stop(self):
        env = StatefulEpisode(7, "finite_test")
        x = features(env.observe(), BayesianBelief(self.bank))
        net = Actor(23, len(x))
        _, probability = net.distribution(x, ["STOP", "reference_check"])
        self.assertAlmostEqual(float(probability.sum()), 1.0)
        self.assertTrue(np.all(probability >= 0.0))
        for idx, name in enumerate(ACTIONS):
            if name not in ("STOP", "reference_check"):
                self.assertEqual(float(probability[idx]), 0.0)
        _, only_stop = net.distribution(x, ["STOP"])
        self.assertEqual(float(only_stop[-1]), 1.0)
        with self.assertRaises(ValueError):
            net.distribution(x, ["pulse_pos_low"])
        with self.assertRaises(ValueError):
            net.distribution(np.full(x.shape, np.nan), ["STOP"])
        with self.assertRaises(ValueError):
            net.distribution(np.zeros(len(x)+1), ["STOP"])

    def test_policy_gradient_direction_matches_finite_difference(self):
        env = StatefulEpisode(8, "train")
        x = features(env.observe(), BayesianBelief(self.bank))
        actor = Actor(11, len(x), hidden=5)
        legal = env.legal_actions()
        hidden, probabilities = actor.distribution(x, legal)
        idx = 2
        gradients = actor.gradients(x, hidden, probabilities, idx)
        step = 1e-6
        for key, coords in (("w1", (2, 1)), ("b1", (2,)),
                            ("w2", (1, 3)), ("b2", (3,))):
            value = actor.weights[key][coords]
            actor.weights[key][coords] = value + step
            plus = np.log(actor.distribution(x, legal)[1][idx])
            actor.weights[key][coords] = value - step
            minus = np.log(actor.distribution(x, legal)[1][idx])
            actor.weights[key][coords] = value
            self.assertAlmostEqual(float(gradients[key][coords]), float((plus-minus)/(2*step)), places=5)

    def test_checkpoint_roundtrip_and_invalid_shapes(self):
        env = StatefulEpisode(11, "train")
        x = features(env.observe(), BayesianBelief(self.bank))
        actor = Actor(13, len(x), hidden=6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actor.json"
            actor.save(path, {"seed": 13})
            loaded, metadata = Actor.load(path)
            self.assertEqual(metadata, {"seed": 13})
            np.testing.assert_array_equal(actor.distribution(x, env.legal_actions())[1],
                                          loaded.distribution(x, env.legal_actions())[1])
            damaged = json.loads(path.read_text())
            damaged["weights"]["w2"] = [[0.0]]
            path.write_text(json.dumps(damaged))
            with self.assertRaises(ValueError):
                Actor.load(path)

    def test_deterministic_episode_and_quick_checkpoint_selection(self):
        env = StatefulEpisode(18, "train")
        x = features(env.observe(), BayesianBelief(self.bank))
        actor = Actor(13, len(x))
        first, traces = episode(actor, self.bank, 90, "finite_test")
        second, _ = episode(actor, self.bank, 90, "finite_test")
        self.assertEqual(first, second)
        self.assertEqual(traces, [])  # No sampled action gradient during evaluation.
        self.assertTrue(0 <= first["calibration"] < 150)
        self.assertTrue(0 <= first["probes"] <= 3)
        self.assertTrue(first["cost"] <= 3.5)
        self.assertEqual(len(first["measurements"]), first["probes"])
        self.assertEqual([m["probe"] for m in first["measurements"]], first["actions"])
        for reading in first["measurements"]:
            self.assertEqual(set(reading), {"probe", "observed", "cost", "guarded"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actor.json"
            trained, history = train(self.bank, 13, path, episodes=48,
                                     batch_size=24, validation_n=4)
            self.assertTrue(path.exists())
            self.assertGreater(len(history["history"]), 0)
            a = evaluate(trained, self.bank, 20000, 4, "finite_test")
            b = evaluate(trained, self.bank, 20000, 4, "finite_test")
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
