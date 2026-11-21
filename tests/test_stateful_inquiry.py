"""Physics-family, experiment-order, action safety, and observation boundaries."""
from __future__ import annotations

import unittest

from research.sequential_inquiry.stateful_plant import (
    Calibration, CALIBRATIONS, Plant, PROBE_BY_NAME, StatefulEpisode,
    pulse, rollout, terminal_quality,
)


class StatefulInquiryTests(unittest.TestCase):
    def test_thermal_physics_carries_state_between_distinct_probes(self):
        plant = Plant(thermal_friction=5.0)
        a, b = PROBE_BY_NAME["pulse_pos_high"], PROBE_BY_NAME["pulse_neg_low"]
        direct_b, _, _ = pulse(plant, b, 0.)
        _, warmed, _ = pulse(plant, a, 0.)
        later_b, _, _ = pulse(plant, b, warmed)
        self.assertGreater(abs(later_b[0] - direct_b[0]), 1e-4)
        self.assertGreater(warmed, 0.)

    def test_no_thermal_coupling_when_coefficient_zero(self):
        plant = Plant(thermal_friction=0.)
        a, b = PROBE_BY_NAME["pulse_pos_high"], PROBE_BY_NAME["pulse_neg_low"]
        direct_b, _, _ = pulse(plant, b, 0.)
        _, warmed, _ = pulse(plant, a, 0.)
        later_b, _, _ = pulse(plant, b, warmed)
        self.assertEqual(direct_b, later_b)

    def test_action_order_matters_in_real_episode_but_not_open_state(self):
        ep = StatefulEpisode(19, noise_scale=0.)
        self.assertEqual(ep.observe()["measurements"], [])
        self.assertNotIn("plant", str(ep.observe()))
        self.assertEqual(len(ep.legal_actions()), 8)
        first = ep.step("pulse_pos_high")
        self.assertEqual(first["probe"], "pulse_pos_high")
        original = ep.observe()["measurements"][0]["observed"][0]
        first["observed"][0] = 999
        copied = ep.observe()
        copied["measurements"][0]["observed"][0] = 999
        self.assertEqual(ep.observe()["measurements"][0]["observed"][0], original)
        with self.assertRaises(ValueError):
            ep.step("pulse_pos_high")
        ep.step("pulse_neg_low")
        ep.step("reference_check")
        self.assertEqual(ep.legal_actions(), ["STOP"])
        with self.assertRaises(ValueError):
            ep.finish(CALIBRATIONS[0])
        ep.step("STOP")
        result = ep.finish(CALIBRATIONS[0])
        self.assertEqual(result["probes"], 3)
        self.assertLessEqual(result["cost"], 3.5)
        with self.assertRaises(ValueError):
            ep.finish(CALIBRATIONS[1])
        with self.assertRaises(ValueError):
            ep.step("pulse_pos_offset")

    def test_deterministic_episode_and_heldout_family(self):
        a = StatefulEpisode(2026, "directional_shift", noise_scale=0.)
        b = StatefulEpisode(2026, "directional_shift", noise_scale=0.)
        self.assertGreater(a._plant.directional_asymmetry, 0)
        self.assertEqual(a.step("pulse_pos_high"), b.step("pulse_pos_high"))
        self.assertEqual(a.step("pulse_neg_low"), b.step("pulse_neg_low"))

    def test_terminal_evaluation_does_not_reuse_probe_heat(self):
        plant = Plant(thermal_friction=4.)
        cal_a, cal_b = CALIBRATIONS[0], CALIBRATIONS[112]
        quality_a = terminal_quality(plant, cal_a)
        quality_b = terminal_quality(plant, cal_b)
        self.assertTrue(0 <= quality_a <= 1)
        self.assertNotAlmostEqual(quality_a, quality_b, places=6)
        ep = StatefulEpisode(64, noise_scale=0.)
        ep.step("pulse_pos_high")
        self.assertGreater(ep._heat, 0)
        ep.step("STOP")
        self.assertEqual(ep.finish(cal_a)["quality"], terminal_quality(ep._plant, cal_a))

    def test_rollout_policy_receives_only_observations(self):
        seen = []
        def policy(state):
            seen.append(state)
            return "pulse_pos_low" if not state["measurements"] else "STOP"
        result = rollout(70, "finite_test", policy, CALIBRATIONS[0])
        self.assertEqual(result["probes"], 1)
        self.assertEqual(len(seen), 2)
        self.assertFalse(any("plant" in key or "true" in key for key in seen[0]))


if __name__ == "__main__":
    unittest.main()
