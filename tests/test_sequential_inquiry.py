"""Contracts for sequential decisions, test independence, and baseline selection."""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import numpy as np

from recursivecal_lab.experiments import EvaluationData, FiniteBank
from research.sequential_inquiry.benchmark import (
    STOP, MAX_COST, SequentialEpisode, _fixed_rewards, choose_myopic,
    rollout, run_study, select_fixed,
)


class SequentialInquiryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = FiniteBank(quadrature_order=3)
        cls.train = cls.bank.make_data(16, "train")

    def test_all_first_probes_are_available_and_budget_is_enforced(self):
        ep = SequentialEpisode(self.bank, self.train, 0)
        self.assertEqual(ep.legal_actions(), [-1, 0, 1, 2, 3, 4, 5, 6])
        ep.step(0)
        with self.assertRaises(ValueError):
            ep.step(0)
        ep.step(1)
        ep.step(6)
        self.assertEqual(ep.legal_actions(), [STOP])
        with self.assertRaises(ValueError):
            ep.finish()
        ep.step(STOP)
        result = ep.finish()
        self.assertEqual(result["probes"], 3)
        self.assertLessEqual(result["cost"], MAX_COST)
        with self.assertRaises(ValueError):
            ep.step(2)
        with self.assertRaises(ValueError):
            ep.observe()

    def test_hidden_truth_and_unchosen_readings_do_not_enter_observation(self):
        ep = SequentialEpisode(self.bank, self.train, 0)
        initial = ep.observe()
        self.assertNotIn("truth", str(initial))
        self.assertNotIn("parameters", str(initial))
        self.assertEqual(initial["measurements"], [])
        modified = self.train.observations.copy()
        modified[0, 1:] += 100
        altered = EvaluationData(self.train.cohort, modified, self.train.parameters * 9,
                                 self.train.asymmetry, np.zeros_like(self.train.quality),
                                 self.train.episode_ids)
        other = SequentialEpisode(self.bank, altered, 0)
        ep.step(0)
        other.step(0)
        self.assertEqual(ep.observe(), other.observe())
        self.assertNotEqual(ep._truth.tolist(), other._truth.tolist())  # evaluator-only

    def test_fixed_vectorized_matches_sequential_rollout(self):
        schedule = (0, 2, 6)
        vector = _fixed_rewards(self.bank, self.train, schedule)
        def policy(state):
            used = [r["action"] for r in state["measurements"]]
            return next((a for a in schedule if a not in used), STOP)
        online = rollout(self.bank, self.train, policy)
        np.testing.assert_allclose(vector, [r["reward"] for r in online], rtol=0, atol=1e-12)

    def test_myopic_only_reads_public_belief_and_legal_actions(self):
        ep = SequentialEpisode(self.bank, self.train, 1)
        first = choose_myopic(self.bank, ep.observe())
        self.assertIn(first, ep.legal_actions())
        if first != STOP:
            ep.step(first)
            second = choose_myopic(self.bank, ep.observe())
            self.assertIn(second, ep.legal_actions())

    def test_selection_and_smoke_are_reproducible(self):
        selected = select_fixed(self.bank, self.train, self.bank.make_data(10, "validation"))
        self.assertEqual(len(selected["shortlist"]), 5)
        self.assertLessEqual(sum(__import__("recursivecal").PROBES[a].cost
                                 for a in selected["schedule"]), MAX_COST)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "study"
            result = run_study(path, train_size=12, validation_size=10, test_size=5)
            self.assertEqual(len(result["results"]), 5)
            self.assertEqual(result["status"], "exploratory baseline gate; no RL trained")
            self.assertEqual(len((path / "episodes.csv").read_text().splitlines()), 5 * 5 * 3 + 1)
            with self.assertRaises(ValueError):
                run_study(path, train_size=12, validation_size=10, test_size=5)


if __name__ == "__main__":
    unittest.main()