"""Fast policy-contract checks without opening the pilot's evaluation worlds."""
from copy import deepcopy
from dataclasses import asdict
import unittest
from unittest.mock import patch

import numpy as np

from recursivecal_lab.inquiry import InquirySession
from recursivecal_lab.physical_rig import Calibration
from recursivecal_lab.research_rig import ResearchRig
from research.physical_gate_v1.bayes import FiniteBayes

try:
    import scipy  # noqa: F401
except ImportError:
    HAS_SCIPY = False
else:
    HAS_SCIPY = True
    from research.physical_gate_v1.identification import fit_history
    from research.physical_gate_v1.run import Pilot


def initial_view():
    return InquirySession(ResearchRig(seed=0), budget=4.8, max_tests=2).observe()


def agent_for(view, *, positive_utility=False, mismatch_cutoff=4.0):
    utility = np.array([[0.8, 0.0], [0.4, 0.0]]) if positive_utility else np.zeros((2, 2))
    return FiniteBayes(view, [Calibration(), Calibration()], utility,
                       [Calibration(), None], mismatch_cutoff=mismatch_cutoff)


def prediction_fixture(base, *, aborted=False, repeated=False):
    """An explicit likelihood fixture, not a claimed physical trajectory."""
    if aborted:
        return {"observations": [], "final_observation": deepcopy(base),
                "metrics": {"termination": "aborted_speed_limit", "completed_duration_s": 0.1},
                "events": [{"time_s": 0.1, "type": "speed_limit"}]}
    rows = [{**base, "sensor_sample_time_s": acquisition, "time_s": elapsed,
             "sample_time_s": elapsed, "sensor_age_s": elapsed - acquisition}
            for acquisition, elapsed in ((0.23, 0.7 / 3), (0.46, 1.4 / 3), (0.69, 0.7))]
    if repeated:
        rows = [deepcopy(rows[-1]) for _ in range(3)]
    return {"observations": rows, "final_observation": deepcopy(rows[-1]),
            "metrics": {"termination": "completed", "completed_duration_s": 0.7}, "events": []}


def with_private_fields(view):
    augmented = deepcopy(view)
    # Deliberately nonfinite/contradictory private values must not enter either
    # likelihood. The declared public measurements remain identical.
    augmented.update(episode={"parameters": {"mass_kg": 1e12}, "sensor_seed": 991},
                     evaluator_seed=123, world_id="not-a-policy-input",
                     verification={"candidate_quality": float("nan")})
    augmented["measurement"].update(true_angle_rad=float("nan"), true_mass_kg=-1e12,
                                    motor_left_current_A=float("inf"))
    return augmented


class FiniteBayesPolicyTests(unittest.TestCase):
    def test_abort_mass_charges_forced_end_and_full_experiment_cost(self):
        view = initial_view()
        view["legal_actions"] = ["hold"]
        agent = agent_for(view)
        complete = prediction_fixture(view["measurement"])
        aborted = prediction_fixture(view["measurement"], aborted=True)
        with patch.object(agent, "predict", return_value=(agent.rigs, [complete, aborted])):
            choice, details = agent.choose_second(view, force_two=True)
            stopping, _ = agent.choose_second(view)
        score = details["candidates"][0]
        self.assertEqual(choice, "hold")
        self.assertEqual(stopping, "STOP")
        self.assertEqual(score["predicted_abort_probability"], 0.5)
        self.assertEqual(score["expected_completed_terminal_utility"], 0.0)
        self.assertAlmostEqual(score["expected_net_utility"], -0.5084, places=12)

    def test_mismatch_abstains_but_forced_two_still_runs_an_experiment(self):
        view = initial_view()
        view["measurement"]["strut_force_N_each"] += 12.0
        view["legal_actions"] = ["hold"]
        agent = agent_for(view, positive_utility=True, mismatch_cutoff=1e-9)
        self.assertTrue(agent.model_mismatch)
        self.assertEqual(agent.terminal_action()[0], {"abstain": True})
        complete = prediction_fixture(view["measurement"])
        with patch.object(agent, "predict", return_value=(agent.rigs, [complete, deepcopy(complete)])):
            choice, details = agent.choose_second(view, force_two=True)
        self.assertEqual(choice, "hold")
        self.assertTrue(details["forced_two"])
        self.assertEqual(details["candidates"][0]["fantasy_mismatch_fraction"], 1.0)
        self.assertEqual(details["candidates"][0]["expected_completed_terminal_utility"], 0.0)

    def test_repeated_acquisition_and_repeated_update_are_not_recounted(self):
        view = initial_view()
        agent = agent_for(view)
        self.assertEqual(agent.diagnostics()["dimension_count"], 3)
        result = prediction_fixture(view["measurement"], repeated=True)
        next_view = deepcopy(view)
        next_view["history"] = [{"action": "hold", "cost": 0.7,
                                 "start_observation": deepcopy(view["measurement"]),
                                 "observations": result["observations"],
                                 "final_observation": result["final_observation"],
                                 "termination": "completed"}]
        next_view["measurement"] = result["final_observation"]
        with patch.object(agent, "predict", return_value=(agent.rigs, [result, deepcopy(result)])) as predict:
            agent.update(next_view)
            first = agent.diagnostics()
            agent.update(next_view)
            second = agent.diagnostics()
        self.assertEqual(predict.call_count, 1)
        self.assertEqual(first["dimension_count"], 6)
        self.assertEqual(first["unique_acquisitions"], 2)
        self.assertEqual(first, second)

    def test_private_evaluator_fields_do_not_change_bayesian_inference(self):
        view = initial_view()
        plain = agent_for(view, positive_utility=True)
        augmented = agent_for(with_private_fields(view), positive_utility=True)
        self.assertEqual(plain.diagnostics(), augmented.diagnostics())
        self.assertEqual(plain.terminal_action(), augmented.terminal_action())


@unittest.skipUnless(HAS_SCIPY, "SciPy validation extra is required for the continuous MAP comparator")
class ContinuousMAPPolicyTests(unittest.TestCase):
    def test_private_evaluator_fields_do_not_change_continuous_fit(self):
        view = initial_view()
        plain = fit_history(view)
        augmented = fit_history(with_private_fields(view))
        for key in ("estimate", "data_standardized_residual", "numerical_rank", "forward_calls"):
            self.assertEqual(plain[key], augmented[key])
        self.assertEqual(plain["numerical_rank"], 2)

    def test_failed_or_nonfinite_map_fit_abstains_before_prediction(self):
        pilot = Pilot.__new__(Pilot)
        valid_shape = {"converged": True, "budget_exhausted": False, "optimizer_status": 1,
                       "standardized_residual_rms": 0.1, "estimate": asdict(Calibration())}
        invalid_estimate = {**asdict(Calibration()), "mass_kg": float("nan")}
        cases = {
            "not_converged": {**valid_shape, "converged": False},
            "iteration_limit": {**valid_shape, "optimizer_status": 0},
            "forward_call_limit": {**valid_shape, "budget_exhausted": True},
            "nan_residual": {**valid_shape, "standardized_residual_rms": float("nan")},
            "infinite_residual": {**valid_shape, "standardized_residual_rms": float("inf")},
            "large_residual": {**valid_shape, "standardized_residual_rms": 4.01},
            "malformed_estimate": {**valid_shape, "estimate": {"mass_kg": 25.0}},
            "nonfinite_estimate": {**valid_shape, "estimate": invalid_estimate},
            "missing_fit": {},
        }
        with patch.object(pilot, "check", side_effect=AssertionError("failed fit must not reach a prediction")), \
                patch("research.physical_gate_v1.run.model_qualities",
                      side_effect=AssertionError("failed fit must not run a model")):
            for name, fitted in cases.items():
                with self.subTest(name=name):
                    action, details = pilot.map_decision(fitted)
                    self.assertEqual(action, {"abstain": True})
                    self.assertIn(details["reason"], ("fit_failure_or_mismatch", "invalid_fit_estimate"))


if __name__ == "__main__":
    unittest.main()
