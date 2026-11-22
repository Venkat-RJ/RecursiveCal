"""Statistical and evidence-gate tests using sealed-shaped synthetic scores."""
from copy import deepcopy
import unittest

from research.physical_gate_v1.analysis import (
    ACTION_ORDER, EVALUATION_SEEDS, POLICIES, paired_comparison,
    selection_examples, summary,
)


def candidate(reward, cost=3.8):
    improvement = reward + .012 * cost
    return {
        "score": {"nominal_quality": .1, "candidate_quality": .1 + improvement,
                  "improvement": improvement, "test_cost": cost,
                  "rejected_commit_penalty": 0., "forced_end_penalty": 0.,
                  "reward": reward, "all_motion_profiles_passed": True},
        "disposition": "candidate", "completion_reason": "calibration_committed",
        "second_action": "low_sweep", "report_path": "synthetic-fixture-only",
    }


def abstention(cost=0.):
    result = candidate(0., cost)
    result.update(disposition="abstain", completion_reason="policy_abstained", second_action="STOP")
    result["score"].update(candidate_quality=.1, improvement=0., reward=-.012 * cost)
    return result


def records():
    rows = []
    for split, seeds in EVALUATION_SEEDS.items():
        for index, seed in enumerate(seeds):
            policies = {name: candidate(.1) for name in POLICIES}
            policies.update(abstain=abstention(), initial_bayes=candidate(.05, 0.),
                            map_initial=candidate(.05, 0.), adaptive_bayes=candidate(.2),
                            adaptive_two_bayes=candidate(.2), map_fixed_two=candidate(.2))
            variation = ("directional_friction" if index % 2 == 0 else "unequal_actuators")
            rows.append({"split": split, "seed": seed,
                         "variation": variation if split == "ood" else "continuous_parameters",
                         "policies": policies})
    return rows


class PairedAnalysisTests(unittest.TestCase):
    def test_pairs_world_outcomes_and_ignores_profile_row_count(self):
        rows = [row for row in records() if row["split"] == "test"][:3]
        for i, row in enumerate(rows):
            row["policies"]["adaptive_bayes"] = candidate(.2 + .1 * i)
            row["policies"]["fixed_bayes"] = candidate(.1 + .1 * i)
            row["policies"]["adaptive_bayes"]["verification_profiles"] = [0] * (1000 * (i + 1))
        result = paired_comparison(list(reversed(rows)), "adaptive_bayes", "fixed_bayes")
        self.assertEqual(result["n"], 3)
        self.assertEqual([world["seed"] for world in result["worlds"]], [4000, 4001, 4002])
        self.assertAlmostEqual(result["mean_difference"], .1)
        self.assertAlmostEqual(result["ci95"][0], .1)
        self.assertAlmostEqual(result["ci95"][1], .1)
        self.assertEqual(len(result["paired_differences"]), 3)

    def test_missing_outcome_cannot_be_dropped_into_a_passing_comparison(self):
        rows = [row for row in records() if row["split"] == "test"][:3]
        del rows[0]["policies"]["fixed_bayes"]
        result = paired_comparison(rows, "adaptive_bayes", "fixed_bayes")
        self.assertEqual(result["n"], 2)
        self.assertFalse(result["complete_pairs"])
        self.assertFalse(result["exceeds_practical_margin"])
        self.assertEqual(result["missing_worlds"][0]["seed"], 4000)

    def test_duplicate_world_is_not_an_independent_sample(self):
        row = [row for row in records() if row["split"] == "test"][0]
        with self.assertRaisesRegex(ValueError, "duplicate world"):
            paired_comparison([row, deepcopy(row)], "adaptive_bayes", "fixed_bayes")


class ResearchGateTests(unittest.TestCase):
    def test_train_requires_complete_matching_manifest_and_all_thresholds(self):
        result = summary(records())
        self.assertEqual(result["decision"], "TRAIN")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["splits"]["test"]["n"], 12)
        self.assertEqual(result["ood_families"]["directional_friction"]["n"], 6)
        self.assertEqual(result["ood_families"]["unequal_actuators"]["n"], 6)

    def test_actual_cost_mismatch_stops_even_if_proposed_actions_match(self):
        rows = records()
        row = next(row for row in rows if row["split"] == "test")
        row["policies"]["shuffled_bayes"] = candidate(.1, 3.9)
        self.assertEqual(row["policies"]["shuffled_bayes"]["second_action"],
                         row["policies"]["adaptive_bayes"]["second_action"])
        result = summary(rows)
        self.assertEqual(result["decision"], "STOP")
        self.assertIn("shuffle_actual_costs", result["reasons"])
        cost = result["shuffle_cost_checks"]["test"]["adaptive_bayes_versus_shuffled_bayes"]
        self.assertAlmostEqual(cost["difference"], -.1)
        self.assertFalse(cost["passed"])

    def test_valid_no_advantage_is_revise_task_not_invalid_evidence(self):
        rows = records()
        for row in rows:
            if row["split"] == "test":
                row["policies"]["adaptive_bayes"] = candidate(.1)
        result = summary(rows)
        self.assertEqual(result["decision"], "REVISE TASK")
        self.assertTrue(result["integrity_passed"])
        self.assertIn("adaptive_bayes_beats_fixed_bayes", result["reasons"])

    def test_missing_declared_world_and_timeout_are_incomplete(self):
        missing = summary(records()[:-1])
        self.assertEqual(missing["decision"], "STOP")
        self.assertTrue(missing["pilot_incomplete"])
        self.assertIn("evaluation_manifest", missing["reasons"])
        timeout = summary(records(), complete=False)
        self.assertEqual(timeout["decision"], "STOP")
        self.assertTrue(timeout["pilot_incomplete"])

    def test_bad_reward_arithmetic_cannot_pass_integrity(self):
        rows = records()
        rows[0]["policies"]["adaptive_bayes"]["score"]["reward"] += .1
        result = summary(rows)
        self.assertEqual(result["decision"], "STOP")
        self.assertFalse(result["integrity_passed"])
        self.assertTrue(any("reward contradicts" in error for error in result["validation_errors"]))

    def test_seed_labels_do_not_make_a_repeated_physical_world_independent(self):
        rows = records()
        rows[0]["world_id"] = rows[1]["world_id"] = "same-physical-world"
        result = summary(rows)
        self.assertEqual(result["decision"], "STOP")
        self.assertTrue(any("repeated physical world" in error for error in result["validation_errors"]))

    def test_initial_only_label_cannot_hide_paid_experiments(self):
        rows = records()
        rows[0]["policies"]["initial_bayes"] = candidate(.05, .7)
        result = summary(rows)
        self.assertEqual(result["decision"], "STOP")
        self.assertTrue(any("initial-only policy spent" in error for error in result["validation_errors"]))

    def test_ood_cost_is_matched_for_the_split_not_each_family(self):
        rows = records()
        for row in rows:
            if row["split"] == "ood":
                one_family = row["variation"] == "directional_friction"
                row["policies"]["adaptive_bayes"] = candidate(.2, 3. if one_family else 4.6)
                row["policies"]["shuffled_bayes"] = candidate(.1, 4.6 if one_family else 3.)
        result = summary(rows)
        self.assertEqual(result["decision"], "TRAIN")
        family = result["ood_families"]["directional_friction"]["policies"]
        self.assertNotEqual(family["adaptive_bayes"]["actual_total_test_cost"],
                            family["shuffled_bayes"]["actual_total_test_cost"])
        self.assertTrue(result["shuffle_cost_checks"]["ood"]["adaptive_bayes_versus_shuffled_bayes"]["passed"])


class SelectionExampleTests(unittest.TestCase):
    def test_selects_distinct_actual_best_actions_from_training_only(self):
        rows = []
        for i, best in enumerate(("low_sweep", "reference")):
            rows.append({"split": "train", "seed": 2000 + i, "variation": "continuous_parameters",
                         "first_observation": {"angle_rad": .9 + i * .01},
                         "action_scores": {action: candidate(.3 if action == best else .1)
                                           for action in ACTION_ORDER}})
        result = selection_examples(rows)
        self.assertTrue(result["different_best_actions"])
        self.assertEqual([row["selected_best_action"] for row in result["examples"]],
                         ["low_sweep", "reference"])
        self.assertEqual(len(result["examples"][0]["actions"]), 7)
        rows[0]["split"] = "test"
        with self.assertRaisesRegex(ValueError, "training worlds only"):
            selection_examples(rows)

    def test_shared_tied_optimum_does_not_imply_decision_dependence(self):
        rows = [{"split": "train", "seed": seed,
                 "action_scores": {action: candidate(.2) for action in ACTION_ORDER}}
                for seed in (2000, 2001)]
        result = selection_examples(rows)
        self.assertFalse(result["different_best_actions"])
        self.assertEqual(result["examples"], [])


if __name__ == "__main__":
    unittest.main()
