"""Source-bound replay tests on the actual synthetic electromechanical rig."""
from copy import deepcopy
import unittest

from recursivecal_lab.cli import parser
from recursivecal_lab.evidence_replay import verify_inquiry_replay, verify_rl_replay
from recursivecal_lab.inquiry import digest, run_study, verify_report
from recursivecal_lab.rl_environment import PhysicalCalibrationEnv, verify_episode_report


def rehash(report):
    report["report_sha256"] = digest(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    return report


class ReplayTests(unittest.TestCase):
    def test_cli_replay_is_explicit_opt_in(self):
        self.assertFalse(parser().parse_args(["verify-rl", "report.json"]).replay)
        self.assertTrue(parser().parse_args(["verify-rl", "report.json", "--replay"]).replay)
        self.assertFalse(parser().parse_args(["verify-inquiry", "report.json"]).replay)
        self.assertTrue(parser().parse_args(["verify-inquiry", "report.json", "--replay"]).replay)

    def test_rl_replay_finds_self_consistent_intermediate_force_change(self):
        env = PhysicalCalibrationEnv(max_tests=0, budget=0)
        env.reset(seed=8, split="validation")
        env.step({"abstain": True})
        report = env.host_report()
        self.assertTrue(verify_episode_report(report)["valid"])
        self.assertTrue(verify_rl_replay(report)["valid"], verify_rl_replay(report))

        altered = deepcopy(report)
        altered["verification"]["comparisons"][0]["before"]["trace"][1]["true_motor_force_N_each"] += 0.5
        rehash(altered)
        # The fast verifier establishes consistency, not physical replay.
        self.assertTrue(verify_episode_report(altered)["valid"], verify_episode_report(altered))
        checked = verify_rl_replay(altered)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("true_motor_force_N_each" in error for error in checked["failures"]), checked)

        mismatched_source = deepcopy(report)
        mismatched_source["source_sha256"]["recursivecal_lab/physics.py"] = "0" * 64
        rehash(mismatched_source)
        self.assertFalse(verify_rl_replay(mismatched_source)["valid"])
        self.assertIn("source_revision_mismatch", verify_rl_replay(mismatched_source)["failures"])

    def test_rl_replay_reconstructs_a_real_diagnostic(self):
        env = PhysicalCalibrationEnv(max_tests=1, budget=0.7)
        env.reset(seed=8, split="validation")
        env.step({"experiment": "hold"})
        if not env.completed:
            env.step({"abstain": True})
        report = env.host_report()
        self.assertTrue(verify_episode_report(report)["valid"])
        self.assertTrue(verify_rl_replay(report)["valid"], verify_rl_replay(report))

    def test_inquiry_replay_finds_self_consistent_intermediate_force_change(self):
        report = run_study(case="nominal", seed=9, policy="no_probe",
                           max_tests=0, budget=0, rig_version=3)
        self.assertTrue(verify_report(report)["valid"], verify_report(report))
        self.assertTrue(verify_inquiry_replay(report)["valid"], verify_inquiry_replay(report))

        altered = deepcopy(report)
        altered["verification"]["comparisons"][0]["before"]["trace"][1]["true_motor_force_N_each"] += 0.5
        rehash(altered)
        self.assertTrue(verify_report(altered)["valid"], verify_report(altered))
        checked = verify_inquiry_replay(altered)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("true_motor_force_N_each" in error for error in checked["errors"]), checked)


if __name__ == "__main__":
    unittest.main()
