"""Cross-layer checks for the actual v3 drive, sensor, API and inquiry paths."""
from dataclasses import asdict, replace
import math
import unittest

from recursivecal_lab.api import dispatch
from recursivecal_lab.inquiry import BayesianInvestigator, InquirySession
from recursivecal_lab.physical_rig import Calibration, run_motion
from recursivecal_lab.research_rig import ResearchRig
from recursivecal_lab.research_simulation import simulate


class ResearchIntegrationTests(unittest.TestCase):
    def test_short_recording_keeps_reference_duration_and_exact_endpoint(self):
        run = simulate(duration_s=.55, dt_s=.02)
        self.assertAlmostEqual(run["trace"][-1]["time_s"], .55, places=12)
        self.assertEqual(run["metrics"]["termination"], "completed")
        self.assertLess(run["trace"][-1]["target_angle_rad"], math.radians(2))
        self.assertEqual(run["model_id"], "recursivecal.si-liftgate/3")

    def test_api_declares_brake_and_keeps_sensor_angle_distinct(self):
        run = dispatch("/api/simulate", {"rig_version": 3, "duration_s": .4,
                       "parameters": {"sensor_bias_rad": .02},
                       "sensors": {"angle_noise_std_rad": 0, "angle_resolution_rad": 0}})
        self.assertEqual(run["parameters"]["holding_brake_Nm"], 120)
        self.assertEqual(run["rig_specification"]["drive"]["brake_capacity_Nm"], 120)
        self.assertTrue(run["metrics"]["passive_hold"]["can_hold_open_without_motor"])
        row = run["trace"][0]
        self.assertAlmostEqual(row["observed_angle_rad"] - row["angle_rad"], .02)
        self.assertTrue(any(row["sensor_age_s"] > 0 for row in run["trace"]))

    def test_unbraked_fault_and_per_side_drive_states_are_explicit(self):
        run = simulate(duration_s=.6, drive={"brake_capacity_Nm": 0}, side_effectiveness=(.6, 1))
        self.assertFalse(run["metrics"]["passive_hold"]["can_hold_open_without_motor"])
        self.assertEqual(run["rig_specification"]["side_effectiveness"], [.6, 1])
        self.assertTrue(any(abs(row["left_force_N"] - row["right_force_N"]) > 1 for row in run["trace"]))
        for row in run["trace"]:
            self.assertAlmostEqual(row["motor_force_N_each"], (row["left_force_N"] + row["right_force_N"]) / 2)

    def test_real_drive_trip_is_an_experiment_failure(self):
        rig = ResearchRig()
        # Evaluator-created overheated starting state exercises the real trip.
        rig._motors[0] = replace(rig._motors[0], temperature_C=115)
        result = run_motion(rig, start_angle_rad=rig.state.angle_rad,
                            target_angle_rad=rig.state.angle_rad, duration_s=.1, include_truth=True)
        self.assertEqual(result["metrics"]["termination"], "aborted_drive_trip")
        self.assertIn("drive_trip", [event["type"] for event in result["events"]])
        self.assertLess(result["metrics"]["completed_duration_s"], .1)

    def test_saturation_is_retained_in_trace_and_metrics(self):
        run = simulate(parameters={"motor_force_max_N_each": 1}, duration_s=.4)
        self.assertGreater(run["metrics"]["force_saturation_fraction"], 0)
        self.assertTrue(any(row["force_saturated"] for row in run["trace"]))

    def test_guard_and_model_selection_are_not_silent(self):
        with self.assertRaises(ValueError):
            simulate(abort_on_limit=False)
        with self.assertRaises(ValueError):
            dispatch("/api/simulate", {"rig_version": True})
        with self.assertRaises(ValueError):
            dispatch("/api/simulate", {"rig_version": 2, "drive": {}})

    def test_custom_controller_curve_is_not_silently_discarded(self):
        with self.assertRaisesRegex(ValueError, "gas_force_extended_N_each"):
            simulate(controller_parameters={"gas_force_extended_N_each": 300})
        result = simulate(duration_s=.02, controller_parameters={"motor_efficiency": .8})
        self.assertEqual(result["controller_parameters"]["motor_efficiency"], .8)

    def test_abstention_cannot_change_calibration_and_known_temperature_is_used(self):
        rig = ResearchRig()
        session = InquirySession(rig)
        with self.assertRaises(ValueError):
            session.commit(asdict(Calibration(mass_kg=30)), disposition="abstain")
        session.commit(asdict(Calibration()), disposition="abstain")
        observation = {**rig.observe(), "ambient_temperature_C": -10.0}
        investigator = BayesianInvestigator(observation, rig_factory=ResearchRig)
        self.assertTrue(all(candidate.parameters.temperature_C == -10 for candidate in investigator.rigs))


if __name__ == "__main__":
    unittest.main()
