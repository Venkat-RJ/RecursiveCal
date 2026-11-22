"""Progress and prediction evidence must preserve the investigator boundary."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from recursivecal_lab.inquiry import BayesianInvestigator, run_study, verify_report


class WorkspaceStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = []

        def monitor(event):
            cls.events.append(deepcopy(event))
            # A UI consumer is not allowed to rewrite the investigator's data.
            if "observation" in event:
                event["observation"]["measurement"]["angle_rad"] = -999
            if "prediction" in event:
                event["prediction"]["candidates"][0]["trace"].clear()
            event.clear()
            event["observation"] = {"measurement": {"angle_rad": -999}}

        configuration = {"case": "weak_motor", "seed": 7, "policy": "fixed", "max_tests": 1}
        cls.monitored = run_study(**configuration, on_event=monitor)
        cls.unmonitored = run_study(**configuration)

    def test_monitor_does_not_change_physics_actions_or_report(self):
        self.assertEqual(self.monitored, self.unmonitored)
        self.assertTrue(verify_report(self.monitored)["valid"])

    def test_progress_is_ordered_and_contains_no_evaluator_truth(self):
        self.assertEqual([event["type"] for event in self.events],
                         ["started", "experiment_selected", "experiment_completed", "belief_updated", "committed"])

        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertFalse(key.startswith("true_"), key)
                    self.assertNotIn(key, {"evaluator_only_truth", "verification", "initial_state", "final_state"})
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        inspect(self.events)
        selected = self.events[1]
        self.assertEqual(selected["observation"]["history"], [])
        self.assertEqual(selected["prediction"], self.monitored["prediction_history"][0])

    def test_predictions_reproduce_without_the_acquired_observation(self):
        initial = self.monitored["initial_observation"]["measurement"]
        agent = BayesianInvestigator(initial, seed=7)
        _, predictions = agent.predict("high_sweep", initial)
        recorded = self.monitored["prediction_history"][0]
        for candidate in recorded["candidates"]:
            index = next(i for i, estimate in enumerate(agent.estimates)
                         if asdict(estimate) == candidate["parameters"])
            self.assertAlmostEqual(candidate["prior_weight"], agent.weights[index])
            expected = [{key: row[key] for key in ("time_s", "angle_rad", "velocity_rad_s", "strut_force_N_each")}
                        for row in predictions[index]["trace"]]
            self.assertEqual(candidate["trace"], expected)


if __name__ == "__main__":
    unittest.main()
