"""Physical RL protocol regressions, with separate real-engine integration checks."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import math
import unittest

from recursivecal_lab.inquiry import ACCEPTANCE, VERIFICATION_PROFILES, digest
from recursivecal_lab.physical_rig import Calibration, PhysicalRig, smooth_reference
from recursivecal_lab.physics import passive_hold
from recursivecal_lab.rl_environment import (
    MODEL_ID, PARAMETER_BOUNDS, PROFILE_NAMES, PROFILE_TARGET_DEGREES, PhysicalCalibrationEnv, cell_split,
    parameter_cell, protocol, reward_components, sample_episode, verify_episode_report,
)
from recursivecal_v1.physical_protocol import PhysicalCalibrationDialogue


class ContractRig(PhysicalRig):
    """Fast fixture for task-boundary tests only; not v3 physical validation."""
    model_id = MODEL_ID

    def __init__(self, parameters, *, side_effectiveness=(1., 1.), **kwargs):
        super().__init__(parameters, **kwargs)

    def observe(self, **kwargs):
        return {**super().observe(**kwargs), "sensor_sample_time_s": self.state.time_s, "sensor_age_s": 0.0}


class AbortingContractRig(ContractRig):
    def advance(self, *args, **kwargs):
        result = super().advance(*args, **kwargs)
        result["speed_breach"] = True
        return result


class LeakyContractRig(ContractRig):
    def observe(self, **kwargs):
        return {**super().observe(**kwargs), "true_angle_rad": 123., "secret_motor_efficiency": 456.}


def contract_evaluator(parameters, closing_extra, calibration, *, seed, rig_factory):
    """Deterministic verifier fixture that makes nominal abstention exactly paired."""
    def run(estimate, name="full_open"):
        residual = abs(estimate.mass_kg - parameters.mass_kg)
        _, start, target, profile_s, duration, temperature = next(row for row in VERIFICATION_PROFILES if row[0] == name)
        metrics = {"termination": "completed", "tracking_rmse_deg": 0.3 + residual * .15,
                   "final_error_deg": residual * .08, "peak_speed_rad_s": .4, "saturation_fraction": .02,
                   "completed_duration_s": duration, "mechanical_work_abs_J": 0., "mechanical_work_signed_J": 0.}
        trace = []
        for index, t in enumerate((0.0, duration / 2, duration * .98, duration)):
            reference = smooth_reference(t, math.radians(start), math.radians(target), profile_s)[0]
            error = (0 if index == 0 else math.radians(metrics["final_error_deg"]) if index == 3
                     else math.radians(metrics["tracking_rmse_deg"] * math.sqrt(2)))
            trace.append({"time_s": t, "absolute_time_s": t, "ambient_temperature_C": temperature,
                          "target_angle_rad": reference, "true_angle_rad": reference - error,
                          "true_velocity_rad_s": 0., "true_motor_force_N_each": 0., "command_N_each": 0.,
                          "force_saturated": index == 3})
        def state(row):
            return {"time_s": row["time_s"], "angle_rad": row["true_angle_rad"], "velocity_rad_s": 0.,
                    "motor_force_N_each": 0., "mechanical_work_abs_J": 0.}
        return {"metrics": metrics, "trace": trace, "duration_s": duration, "events": [],
                "initial_state": state(trace[0]), "final_state": state(trace[-1]),
                "accepted": metrics["tracking_rmse_deg"] <= 3
                and metrics["final_error_deg"] <= 2}

    def auxiliary(start, target, profile_s, duration, loss=None):
        trace = []
        for t in (0.0, duration):
            reference = smooth_reference(t, math.radians(start), math.radians(target), profile_s)[0]
            trace.append({"time_s": t, "absolute_time_s": t, "ambient_temperature_C": parameters.temperature_C,
                          "target_angle_rad": reference, "true_angle_rad": reference, "true_velocity_rad_s": 0.,
                          "true_motor_force_N_each": 0., "command_N_each": 0., "force_saturated": False})
        return {"metrics": {"termination": "completed", "tracking_rmse_deg": 0., "final_error_deg": 0.,
                            "peak_speed_rad_s": 0., "saturation_fraction": 0., "completed_duration_s": duration,
                            "mechanical_work_abs_J": 0., "mechanical_work_signed_J": 0.},
                "trace": trace, "duration_s": duration,
                "events": [] if loss is None else [{"time_s": loss, "type": "power_loss"}],
                "initial_state": {"time_s": 0., "angle_rad": trace[0]["true_angle_rad"], "velocity_rad_s": 0.,
                                  "motor_force_N_each": 0., "mechanical_work_abs_J": 0.},
                "final_state": {"time_s": duration, "angle_rad": trace[-1]["true_angle_rad"], "velocity_rad_s": 0.,
                                "motor_force_N_each": 0., "mechanical_work_abs_J": 0.}}
    comparisons = [{"name": name, "profile_duration_s": profile, "temperature_C": temperature,
                    "before": run(Calibration(), name), "after": run(calibration, name)}
                   for name, _, _, profile, _, temperature in VERIFICATION_PROFILES]
    return {"comparisons": comparisons, "hardware_validated": False, "system_ready_for_hardware": False,
            "acceptance_limits": dict(ACCEPTANCE), "before_mean_rmse_deg": run(Calibration())["metrics"]["tracking_rmse_deg"],
            "after_mean_rmse_deg": run(calibration)["metrics"]["tracking_rmse_deg"],
            "passive_hold": {"run": auxiliary(78., 78., .8, .8),
                             "static": passive_hold(replace(parameters,
                                friction_static_Nm=parameters.friction_static_Nm + closing_extra,
                                friction_coulomb_Nm=parameters.friction_coulomb_Nm + closing_extra))},
            "power_loss": auxiliary(55., 70., 1.7, 2.2, .8),
            "model_id": MODEL_ID, "all_motion_profiles_passed": run(calibration)["accepted"]}


class SamplingTests(unittest.TestCase):
    def test_deterministic_continuous_worlds_and_disjoint_cells(self):
        cells, worlds = {}, {}
        for split in ("train", "validation", "test"):
            specs = [sample_episode(seed, split) for seed in range(100)]
            cells[split] = {s.cell for s in specs}
            worlds[split] = {s.to_dict()["world_id"] for s in specs}
            self.assertGreater(len(worlds[split]), 95)
            for spec in specs:
                self.assertEqual(spec, sample_episode(spec.seed, split))
                self.assertEqual(cell_split(spec.cell), split)
                self.assertEqual(parameter_cell(asdict(spec.parameters)), spec.cell)
                for key, (low, high) in PARAMETER_BOUNDS.items():
                    self.assertLessEqual(low, getattr(spec.parameters, key))
                    self.assertLessEqual(getattr(spec.parameters, key), high)
                self.assertNotIn(spec.parameters.mass_kg, (25., 30.))
        for first, second in (("train", "validation"), ("train", "test"), ("validation", "test")):
            self.assertFalse(cells[first] & cells[second])
            self.assertFalse(worlds[first] & worlds[second])

    def test_ood_has_explicit_structural_variation(self):
        specs = [sample_episode(seed, "ood") for seed in range(30)]
        self.assertEqual({s.variation for s in specs}, {"directional_friction", "unequal_actuators"})
        for s in specs:
            self.assertTrue(s.closing_friction_extra_Nm > 0 or s.side_effectiveness != (1., 1.))
            self.assertEqual(s, sample_episode(s.seed, "ood"))

    def test_invalid_sampling_inputs_and_evaluator_seed_margin(self):
        for seed in (-1, True, 1.1, 2**31):
            with self.assertRaises(ValueError):
                sample_episode(seed)
        with self.assertRaises(ValueError):
            sample_episode(1, "unknown")
        for seed in (0, 1, 2**31 - 1):
            self.assertLess(sample_episode(seed).evaluator_seed + 20002, 2**31)


class EpisodeContractTests(unittest.TestCase):
    def env(self, **kwargs):
        env = PhysicalCalibrationEnv(rig_factory=ContractRig, evaluator=contract_evaluator, **kwargs)
        env.reset(seed=17, split="validation")
        return env

    def test_observations_never_include_world_seed_or_verifier_data(self):
        env = self.env()
        with self.assertRaises(RuntimeError):
            env.host_report()
        view, reward, terminated, truncated, info = env.step({"experiment": "hold"})
        self.assertEqual(reward, 0)
        self.assertFalse(terminated or truncated)
        text = json.dumps({"observation": view, "info": info})
        for forbidden in ("world_id", "episode_id", "sensor_seed", "evaluator_seed", "nominal_quality",
                          "evaluator_only_truth", "true_angle_rad", '"parameters"', '"split"'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(view["model_id"], MODEL_ID)
        view["measurement"]["angle_rad"] = -100
        view["history"].clear()
        self.assertNotEqual(env.observe()["measurement"]["angle_rad"], -100)
        self.assertEqual(len(env.observe()["history"]), 1)

    def test_unexpected_rig_debug_fields_cannot_reach_any_policy_observation(self):
        env = PhysicalCalibrationEnv(rig_factory=LeakyContractRig, evaluator=contract_evaluator)
        initial, _ = env.reset(seed=17)
        later = env.step({"experiment": "hold"})[0]
        for view in (initial, later):
            self.assertNotIn("true_angle_rad", json.dumps(view))
            self.assertNotIn("secret_motor_efficiency", json.dumps(view))

    def test_exact_budget_commit_once_and_terminal_report_copy(self):
        env = self.env(max_tests=1, budget=.7)
        view, reward, terminated, truncated, _ = env.step({"experiment": "hold"})
        self.assertEqual(view["budget_remaining"], 0)
        self.assertEqual(view["legal_actions"], [])
        self.assertEqual(reward, 0)
        self.assertFalse(terminated or truncated)
        _, reward, terminated, truncated, _ = env.step({"abstain": True})
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertAlmostEqual(reward, -.012 * .7, places=14)
        report = env.host_report()
        self.assertEqual(report["commitment"]["estimates"], asdict(Calibration()))
        self.assertTrue(verify_episode_report(report)["valid"])
        report["score"]["reward"] = 999
        self.assertNotEqual(env.host_report()["score"]["reward"], 999)
        for action in ({"experiment": "hold"}, {"commit": asdict(Calibration())}, {"abstain": True}):
            with self.assertRaises(RuntimeError):
                env.step(action)

    def test_invalid_actions_are_bounded_without_spending_test_budget(self):
        cases = ["not json", '{"abstain":true,"abstain":false}', '{"commit":{"mass_kg":NaN}}',
                 {"abstain": False}, {"experiment": "unknown"},
                 {"experiment": "hold", "abstain": True}, {"commit": {"mass_kg": 25}},
                 {"commit": {**asdict(Calibration()), "mass_kg": True}}, {"abstain": True, "x": 1}]
        for bad in cases:
            env = self.env()
            view, reward, terminated, truncated, info = env.step(bad)
            self.assertEqual(info["error"], "invalid_action")
            self.assertFalse(terminated or truncated)
            self.assertEqual(reward, 0)
            self.assertEqual(view["cost_used"], 0)
            _, reward, terminated, truncated, _ = env.step(bad)
            self.assertFalse(terminated)
            self.assertTrue(truncated)
            self.assertEqual(reward, -1.0)
            self.assertEqual(env.host_report()["completion_reason"], "invalid_action_limit")

    def test_diagnostic_abort_forces_abstention(self):
        env = PhysicalCalibrationEnv(rig_factory=AbortingContractRig, evaluator=contract_evaluator)
        env.reset(seed=17, split="test")
        _, reward, terminated, truncated, info = env.step({"experiment": "hold"})
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertLess(reward, -1)
        self.assertEqual(info["completion_reason"], "diagnostic_aborted")
        self.assertEqual(env.host_report()["commitment"]["disposition"], "abstain")

    def test_reset_replays_the_same_observations_and_score(self):
        env = self.env()
        episodes = []
        for _ in range(2):
            initial, info = env.reset(seed=71, split="train")
            step = env.step({"experiment": "hold"})
            end = env.step({"abstain": True})
            episodes.append((initial, info, step, end, env.host_report()))
        self.assertEqual(episodes[0], episodes[1])

    def test_verifier_runs_only_after_session_commit(self):
        calls = []
        env = None
        def evaluator(parameters, closing_extra, calibration, **kwargs):
            calls.append(env.observe()["can_commit"])
            return contract_evaluator(parameters, closing_extra, calibration, **kwargs)
        env = PhysicalCalibrationEnv(rig_factory=ContractRig, evaluator=evaluator)
        env.reset(seed=0)
        env.step({"experiment": "hold"})
        self.assertEqual(calls, [])
        env.step({"abstain": True})
        self.assertEqual(calls, [False])

    def test_tampered_reward_world_and_budget_fail_even_with_recomputed_digest(self):
        env = self.env()
        env.step({"experiment": "hold"})
        env.step({"abstain": True})
        report = env.host_report()
        self.assertTrue(verify_episode_report(report)["valid"])
        for modify in (lambda r: r["score"].update(reward=1.0),
                       lambda r: r["episode"]["parameters"].update(mass_kg=39),
                       lambda r: r.update(budget=0),
                       lambda r: r.update(forced_end=True)):
            altered = deepcopy(report)
            modify(altered)
            altered["report_sha256"] = digest({k: v for k, v in altered.items() if k != "report_sha256"})
            self.assertFalse(verify_episode_report(altered)["valid"])

    def test_rehashed_terminal_action_must_match_sealed_calibration_and_reason(self):
        env = self.env()
        env.step({"commit": asdict(Calibration())})
        report = env.host_report()
        self.assertTrue(verify_episode_report(report)["valid"])

        def change_calibration(value):
            value["actions"][-1]["value"]["mass_kg"] = 39.0

        def change_action(value):
            value["actions"][-1].update(kind="abstain", value=None)

        mutations = {
            "calibration": change_calibration,
            "action_kind": change_action,
            "action_acceptance": lambda r: r["actions"][-1].update(accepted=False),
            "completion_reason": lambda r: r.update(completion_reason="policy_abstained"),
            "commitment_reason": lambda r: r["commitment"].update(reason="policy_abstained"),
            "terminal_info": lambda r: r["policy_transcript"][-1]["info"].update(completion_reason="policy_abstained"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                altered = deepcopy(report)
                mutate(altered)
                # Keep the duplicated records consistent and recompute the hash:
                # the rejection must come from the action/decision relationship.
                altered["policy_transcript"][-1]["action"] = deepcopy(altered["actions"][-1])
                altered["session"]["commitment"] = deepcopy(altered["commitment"])
                altered["report_sha256"] = digest({k: v for k, v in altered.items() if k != "report_sha256"})
                self.assertFalse(verify_episode_report(altered)["valid"])

    def test_commit_and_abstention_remain_valid_without_diagnostic_budget(self):
        for action in ({"abstain": True}, {"commit": asdict(Calibration())}):
            with self.subTest(action=action):
                env = self.env(max_tests=0, budget=0)
                self.assertEqual(env.observe()["legal_actions"], [])
                env.step(action)
                report = env.host_report()
                self.assertTrue(verify_episode_report(report)["valid"], verify_episode_report(report))

    def test_rehashed_policy_transcript_rejects_private_or_contradictory_views(self):
        env = self.env()
        env.step({"experiment": "hold"})
        env.step({"abstain": True})
        report = env.host_report()
        mutations = {
            "private_reset": lambda r: r["policy_transcript"][0]["observation"].update(evaluator_only_truth=r["episode"]["parameters"]),
            "private_instrument": lambda r: r["policy_transcript"][0]["observation"]["measurement"].update(true_angle_rad=.3),
            "private_info": lambda r: r["policy_transcript"][0]["info"].update(sensor_seed=r["episode"]["sensor_seed"]),
            "free_budget": lambda r: r["policy_transcript"][0]["observation"].update(budget_remaining=999),
            "future_history": lambda r: r["policy_transcript"][0]["observation"].update(history=r["session"]["agent_history"]),
            "legal_actions": lambda r: r["policy_transcript"][1]["observation"].update(legal_actions=[]),
            "wrong_measurement": lambda r: r["policy_transcript"][1]["observation"]["measurement"].update(angle_rad=1.2),
            "future_sample": lambda r: r["policy_transcript"][0]["observation"]["measurement"].update(sensor_sample_time_s=1),
            "private_clock": lambda r: r["session"]["diagnostics"][0]["initial_state"].update(time_s=1),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                altered = deepcopy(report)
                mutate(altered)
                altered["report_sha256"] = digest({k: v for k, v in altered.items() if k != "report_sha256"})
                self.assertFalse(verify_episode_report(altered)["valid"])

    def test_rehashed_start_measurement_must_follow_previous_observation(self):
        env = self.env()
        env.step({"experiment": "hold"})
        env.step({"abstain": True})
        report = env.host_report()
        history = report["session"]["agent_history"]
        history[0]["start_observation"]["angle_rad"] += .1
        report["commitment"]["history_sha256"] = digest(history)
        report["session"]["commitment"] = deepcopy(report["commitment"])
        for item in report["policy_transcript"]:
            count = len(item["observation"]["history"])
            item["observation"]["history"] = deepcopy(history[:count])
        report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
        self.assertIn("policy_measurement_continuity", verify_episode_report(report)["failures"])

    def test_current_rig_cannot_omit_saturation_or_auxiliary_evidence(self):
        env = self.env()
        env.step({"abstain": True})
        report = env.host_report()
        for name in ("saturation", "passive", "power_loss", "static", "peak_guard"):
            with self.subTest(name=name):
                altered = deepcopy(report)
                if name == "saturation":
                    for row in altered["verification"]["comparisons"][0]["before"]["trace"]:
                        del row["force_saturated"]
                elif name in ("passive", "power_loss"):
                    del altered["verification"]["passive_hold" if name == "passive" else name]
                elif name == "static":
                    altered["verification"]["passive_hold"]["static"]["holding_margin_Nm"] = -999
                else:
                    before = altered["verification"]["comparisons"][0]["before"]
                    before["metrics"]["peak_speed_rad_s"] = 1.2
                    before["accepted"] = False
                altered["report_sha256"] = digest({k: v for k, v in altered.items() if k != "report_sha256"})
                self.assertFalse(verify_episode_report(altered)["valid"])

    def test_forced_terminal_reports_match_their_recorded_trigger(self):
        cases = []
        env = self.env()
        env.step({"bad": True})
        env.step({"bad": True})
        cases.append(env.host_report())
        env = PhysicalCalibrationEnv(rig_factory=AbortingContractRig, evaluator=contract_evaluator)
        env.reset(seed=17, split="test")
        env.step({"experiment": "hold"})
        cases.append(env.host_report())
        for reason in ("agent_stopped", "host_turn_limit"):
            env = self.env(max_tests=0, budget=0)
            env.force_end(reason)
            cases.append(env.host_report())
        for report in cases:
            with self.subTest(reason=report["completion_reason"]):
                self.assertTrue(verify_episode_report(report)["valid"], verify_episode_report(report))
                altered = deepcopy(report)
                altered["actions"][-1] = {"turn": report["turns"], "kind": "host_stop",
                                           "value": "agent_stopped", "accepted": False}
                if report["completion_reason"] == "agent_stopped":
                    altered["actions"][-1]["value"] = "host_turn_limit"
                altered["policy_transcript"][-1]["action"] = deepcopy(altered["actions"][-1])
                altered["report_sha256"] = digest({k: v for k, v in altered.items() if k != "report_sha256"})
                self.assertFalse(verify_episode_report(altered)["valid"])

    def test_json_dialogue_withholds_terminal_evaluator_score(self):
        dialogue = PhysicalCalibrationDialogue(17, split="validation", rig_factory=ContractRig,
                                               evaluator=contract_evaluator)
        first = json.loads(dialogue.observation())
        self.assertNotIn("episode", first)
        self.assertEqual(dialogue.reward(), 0)
        reply, completed = dialogue.act('{"abstain":true}')
        self.assertTrue(completed)
        self.assertEqual(json.loads(reply), {"status": "submitted", "reason": "policy_abstained"})
        self.assertNotIn("quality", reply)
        self.assertEqual(dialogue.reward(), 0)
        self.assertTrue(verify_episode_report(dialogue.host_report())["valid"])

    def test_model_stop_is_sealed_and_penalized_instead_of_free_abstention(self):
        dialogue = PhysicalCalibrationDialogue(17, split="validation", rig_factory=ContractRig,
                                               evaluator=contract_evaluator)
        dialogue.force_end()
        self.assertTrue(dialogue.completed)
        self.assertEqual(dialogue.reward(), -1)
        report = dialogue.host_report()
        self.assertEqual(report["completion_reason"], "agent_stopped")
        self.assertTrue(report["truncated"])
        self.assertTrue(verify_episode_report(report)["valid"], verify_episode_report(report))
        with self.assertRaises(RuntimeError):
            dialogue.force_end()


class RewardTests(unittest.TestCase):
    def verification(self):
        def run(error):
            return {"metrics": {"termination": "completed", "tracking_rmse_deg": error,
                                "final_error_deg": error / 2, "peak_speed_rad_s": .5,
                                "saturation_fraction": .1}, "accepted": error <= 3}
        return {"comparisons": [{"name": name, "before": run(2), "after": run(.3)}
                                for name in PROFILE_NAMES]}

    def test_improvement_cost_and_rejection_have_declared_direction(self):
        v = self.verification()
        good = reward_components(v, 0, disposition="candidate")
        costly = reward_components(v, 3, disposition="candidate")
        self.assertGreater(good["reward"], 0)
        self.assertAlmostEqual(good["reward"] - costly["reward"], .036)
        v["comparisons"][-1]["after"]["metrics"]["final_error_deg"] = 2.01
        rejected = reward_components(v, 0, disposition="candidate")
        self.assertFalse(rejected["all_motion_profiles_passed"])
        self.assertLessEqual(rejected["reward"], 0)
        self.assertEqual(rejected["rejected_commit_penalty"], 1)

    def test_incomplete_motion_cannot_score_perfect_zero_error(self):
        v = self.verification()
        for row in v["comparisons"]:
            row["after"]["metrics"].update(termination="aborted_speed_limit", tracking_rmse_deg=0, final_error_deg=0)
        components = reward_components(v, 0, disposition="candidate")
        self.assertEqual(components["candidate_quality"], 0)
        self.assertLess(components["reward"], -1)

    def test_abstention_cannot_sneak_in_an_improved_calibration(self):
        with self.assertRaises(ValueError):
            reward_components(self.verification(), 0, disposition="abstain")

    def test_protocol_is_detached_and_metric_nan_is_rejected(self):
        one = protocol()
        one["acceptance_limits"]["tracking_rmse_deg_max"] = 999
        self.assertEqual(protocol()["acceptance_limits"]["tracking_rmse_deg_max"], 3)
        v = self.verification()
        v["comparisons"][0]["after"]["metrics"]["tracking_rmse_deg"] = math.nan
        with self.assertRaises(ValueError):
            reward_components(v, 0, disposition="candidate")


class RealPhysicalIntegrationTests(unittest.TestCase):
    def test_actual_version_three_episode_replays_and_seals(self):
        # This exercises the actual electromechanical rig and the normal verifier.
        # Its outcome may pass or fail; a failed physical world remains valid data.
        env = PhysicalCalibrationEnv(max_tests=1, budget=.7)
        first, _ = env.reset(seed=8, split="validation")
        self.assertEqual(first["model_id"], MODEL_ID)
        observation, reward, terminated, truncated, _ = env.step({"experiment": "hold"})
        if not (terminated or truncated):
            self.assertEqual(reward, 0)
            env.step({"abstain": True})
        report = env.host_report()
        self.assertEqual(report["verification"]["model_id"], MODEL_ID)
        self.assertEqual(len(report["verification"]["comparisons"]), 4)
        self.assertTrue(verify_episode_report(report)["valid"], verify_episode_report(report))
        json.dumps(report, allow_nan=False)
        repeat, _ = env.reset(seed=8, split="validation")
        self.assertEqual(first, repeat)
        repeated = env.step({"experiment": "hold"})[0]
        self.assertEqual(observation, repeated)

    def test_known_parameters_can_improve_a_sampled_physical_world(self):
        # Evaluator-only oracle sanity check, never a claimed learned-policy score.
        # Establishes that calibration actually changes the task's terminal reward.
        spec = sample_episode(1, "train")
        known = Calibration(**{name: getattr(spec.parameters, name) for name in asdict(Calibration())})
        env = PhysicalCalibrationEnv()
        env.reset(seed=1, split="train")
        _, reward, terminated, truncated, _ = env.step({"commit": asdict(known)})
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertGreater(reward, .1)
        report = env.host_report()
        self.assertTrue(report["score"]["all_motion_profiles_passed"])
        self.assertGreater(report["score"]["candidate_quality"], report["score"]["nominal_quality"])
        self.assertTrue(verify_episode_report(report)["valid"], verify_episode_report(report))


if __name__ == "__main__":
    unittest.main()
