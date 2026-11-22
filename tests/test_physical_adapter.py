"""Actual optional SDK compatibility, with scripted responses instead of model calls.

CI must set RECURSIVECAL_REQUIRE_VERIFIERS=1 after installing .[verifiers].
The test uses the installed SDK's loaders, configs, tasks, segments and traces.
Only the remote model interaction is scripted; no API key/network call is used.
"""
from contextlib import asynccontextmanager
from importlib import metadata
import json
import os
from types import SimpleNamespace
import unittest

try:
    import verifiers.v1 as vf
    from recursivecal_v1.physical_taskset import (
        PLUGIN_ID, PhysicalCalibrationTaskset, PhysicalCalibrationTasksetConfig,
        PhysicalCalibrationVerifierConfig, PhysicalCalibrationVerifierEnv,
    )
    SDK_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name not in ("verifiers", "verifiers.v1"):
        raise
    SDK_AVAILABLE = False
    if os.environ.get("RECURSIVECAL_REQUIRE_VERIFIERS") == "1":
        raise RuntimeError("required real Verifiers SDK is missing; install .[verifiers]") from exc


class ScriptedAgent:
    """No-model interaction using real SDK Segment and Trace types."""
    def __init__(self, replies, config):
        self.replies = iter(replies)
        self.config = config
        self.tasks = []
        self.messages = []
        self.trace = None

    @asynccontextmanager
    async def interaction(self, task):
        self.tasks.append(task)
        self.trace = vf.Trace(
            task=vf.TraceTask(type=type(task).__name__, data=task.data, key=task.key, hash=task.hash),
            agent=vf.AgentInfo(config=self.config),
        )
        yield SimpleNamespace(turn=self.turn, trace=self.trace)
        self.trace.is_completed = True
        self.trace.ok = True

    async def turn(self, message):
        self.messages.append(message)
        response = next(self.replies, None)
        return vf.Segment(messages=[], root_reply=response, terminated=response is None)


@unittest.skipUnless(SDK_AVAILABLE, "optional real Verifiers SDK not installed")
class PhysicalSDKTests(unittest.IsolatedAsyncioTestCase):
    def configuration(self):
        return PhysicalCalibrationVerifierConfig(
            taskset=PhysicalCalibrationTasksetConfig(id=PLUGIN_ID, split="validation", seed_start=8, num_tasks=2),
        )

    def test_actual_sdk_loaders_resolve_unique_physical_and_legacy_plugins(self):
        version = metadata.version("verifiers")
        self.assertTrue(version.startswith("0.4."), version)
        config = self.configuration()
        loaded = vf.load_taskset(config.taskset)
        self.assertIsInstance(loaded, PhysicalCalibrationTaskset)
        env = vf.load_environment(config)
        self.assertIsInstance(env, PhysicalCalibrationVerifierEnv)
        self.assertEqual(env.config.agent.harness.id, "null")
        self.assertIsInstance(env.config.agent.runtime, vf.SubprocessConfig)
        # The old registration must still resolve to its original taskset.
        from recursivecal_v1.taskset import RecursiveCalTaskset
        self.assertIsInstance(vf.load_taskset(vf.TasksetConfig(id="recursivecal-v1")), RecursiveCalTaskset)

    def test_taskset_is_bounded_reproducible_and_does_not_put_seed_in_prompt(self):
        config = self.configuration().taskset
        first = list(PhysicalCalibrationTaskset(config))
        second = list(PhysicalCalibrationTaskset(config))
        self.assertEqual(len(first), 2)
        self.assertEqual([t.data.model_dump() for t in first], [t.data.model_dump() for t in second])
        self.assertEqual([t.data.idx for t in first], [0, 1])
        for task in first:
            self.assertRegex(task.data.name, r"^physical-[0-9a-f]{20}$")
            self.assertIsNone(task.data.prompt)
            self.assertNotIn("validation", task.data.system_prompt)
            self.assertNotIn("host_seed", task.data.system_prompt)

    async def run_script(self, replies):
        config = self.configuration()
        env = vf.load_environment(config)
        task = next(iter(vf.load_taskset(config.taskset)))
        agent = ScriptedAgent(replies, config.agent)
        await env.run(task, SimpleNamespace(agent=agent))
        for exposed in agent.tasks:
            self.assertIsNone(exposed.data.host_seed)
            self.assertIsNone(exposed.data.host_split)
            self.assertNotIn("host_seed", exposed.data.model_dump(exclude_none=True))
        for message in agent.messages:
            parsed = json.loads(message)
            self.assertNotIn("world_id", message)
            self.assertNotIn("nominal_quality", message)
            self.assertNotIn("true_angle_rad", message)
            self.assertEqual(parsed["task_id"], "recursivecal.physical-calibration-rl/1")
        return agent

    async def test_explicit_abstention_records_real_sdk_reward_after_close(self):
        agent = await self.run_script(['{"abstain":true}'])
        reward = agent.trace.rewards["recursivecal_physical_net_reward"]
        self.assertEqual(reward.score, 0)
        self.assertEqual(agent.trace.metrics["physical_forced_end"], 0)
        report = agent.trace.info["recursivecal_physical"]
        self.assertEqual(report["completion_reason"], "policy_abstained")
        self.assertEqual(report["verification"]["model_id"], "recursivecal.physical-rig/3")

    async def test_model_stop_is_penalized_and_sealed(self):
        agent = await self.run_script([])
        self.assertEqual(agent.trace.rewards["recursivecal_physical_net_reward"].score, -1)
        self.assertEqual(agent.trace.metrics["physical_forced_end"], 1)
        self.assertEqual(agent.trace.info["recursivecal_physical"]["completion_reason"], "agent_stopped")

    async def test_invalid_model_replies_cannot_escape_with_zero_reward(self):
        agent = await self.run_script(['{"invalid":true}', '{"invalid":true}'])
        self.assertEqual(agent.trace.rewards["recursivecal_physical_net_reward"].score, -1)
        self.assertEqual(agent.trace.metrics["physical_invalid_actions"], 2)
        self.assertEqual(agent.trace.info["recursivecal_physical"]["completion_reason"], "invalid_action_limit")


if __name__ == "__main__":
    unittest.main()
