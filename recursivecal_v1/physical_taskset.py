"""Prime Intellect Verifiers 0.4 integration for the version 3 physical rig.

Primary API references, checked against the v0.4.0/v0.4.1 release source:
https://github.com/PrimeIntellect-ai/verifiers/tree/v0.4.1/verifiers/v1
This module uses real Task/Taskset/Env/Trace interfaces. It does not replace the
historical normalized-benchmark plugin.
"""
from __future__ import annotations

import hashlib
from typing import Iterator, Literal

from pydantic import Field, model_validator
import verifiers.v1 as vf
from verifiers.v1.harnesses.null import NullHarnessConfig

from recursivecal_lab.physical_rig import integer
from recursivecal_lab.rl_environment import MAX_TURNS, TASK_ID, verify_episode_report
from .physical_protocol import PhysicalCalibrationDialogue, SYSTEM_PROMPT

PLUGIN_ID = "recursivecal-physical"
__all__ = ["PhysicalCalibrationTaskset", "PhysicalCalibrationVerifierEnv"]


class PhysicalCalibrationTaskData(vf.TaskData):
    # Kept on the evaluator's task only. run() strips both fields from the task
    # given to the agent, in addition to excluding them from all model messages.
    host_seed: int | None = Field(None, repr=False)
    host_split: Literal["train", "validation", "test", "ood"] | None = Field(None, repr=False)


class PhysicalCalibrationTask(vf.Task[PhysicalCalibrationTaskData, vf.State, vf.TaskConfig]):
    pass


class PhysicalCalibrationTasksetConfig(vf.TasksetConfig):
    id: str = PLUGIN_ID
    split: Literal["train", "validation", "test", "ood"] = "train"
    seed_start: int = Field(0, ge=0, le=2**31 - 1)
    num_tasks: int = Field(128, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_seed_range(self):
        integer(self.seed_start, "seed_start", 0, 2**31 - 1)
        integer(self.num_tasks, "num_tasks", 1, 100000)
        if self.seed_start + self.num_tasks > 2**31:
            raise ValueError("the requested task range exceeds the seed domain")
        return self


class PhysicalCalibrationTaskset(vf.Taskset[PhysicalCalibrationTask, PhysicalCalibrationTasksetConfig]):
    INFINITE = False

    def load(self) -> Iterator[PhysicalCalibrationTask]:
        for seed in range(self.config.seed_start, self.config.seed_start + self.config.num_tasks):
            opaque = hashlib.sha256(f"{TASK_ID}:{self.config.split}:{seed}".encode()).hexdigest()[:20]
            yield PhysicalCalibrationTask(
                PhysicalCalibrationTaskData(
                    name="physical-" + opaque,
                    # Interaction.turn(initial_observation) opens the exchange.
                    # A nonempty task prompt would require a different first-turn
                    # sequence in the real SDK and is intentionally absent.
                    prompt=None, system_prompt=SYSTEM_PROMPT,
                    host_seed=seed, host_split=self.config.split,
                ),
                self.config.task,
            )


class PhysicalCalibrationVerifierConfig(vf.SingleAgentEnvConfig):
    taskset: PhysicalCalibrationTasksetConfig = PhysicalCalibrationTasksetConfig()
    agent: vf.AgentConfig = vf.AgentConfig(
        harness=NullHarnessConfig(id="null"), runtime=vf.SubprocessConfig(),
        max_turns=MAX_TURNS, network_notice=False,
    )
    record_evidence: bool = True


class PhysicalCalibrationVerifierEnv(vf.Env[PhysicalCalibrationVerifierConfig]):
    def __init__(self, config: PhysicalCalibrationVerifierConfig):
        if config.agent.harness is None or config.agent.harness.id != "null":
            raise ValueError("the physical calibration protocol requires the tool-less null harness")
        super().__init__(config)

    async def run(self, task: PhysicalCalibrationTask, agents) -> None:
        seed = integer(task.data.host_seed, "host_seed", 0, 2**31 - 1)
        if task.data.host_split not in ("train", "validation", "test", "ood"):
            raise ValueError("physical task is missing its evaluator-owned split")
        dialogue = PhysicalCalibrationDialogue(seed, split=task.data.host_split)
        agent_task = task.with_data(host_seed=None, host_split=None, prompt=None)
        observation = dialogue.observation()
        async with agents.agent.interaction(agent_task) as interaction:
            for _ in range(MAX_TURNS):
                segment = await interaction.turn(observation)
                if segment.terminated:
                    dialogue.force_end("agent_stopped")
                    break
                observation, completed = dialogue.act(segment.last_reply)
                if completed:
                    break
            if not dialogue.completed:
                dialogue.force_end("host_turn_limit")
        report = dialogue.host_report()
        checked = verify_episode_report(report)
        if not checked["valid"]:
            raise ValueError("physical episode failed protocol verification: " + ", ".join(checked["failures"]))
        trace = interaction.trace
        trace.record_reward("recursivecal_physical_net_reward", dialogue.reward(), 1.0)
        trace.record_metric("physical_candidate_committed", float(report["commitment"]["disposition"] == "candidate"))
        trace.record_metric("physical_abstained", float(report["commitment"]["disposition"] == "abstain"))
        trace.record_metric("physical_forced_end", float(report["forced_end"]))
        trace.record_metric("physical_invalid_actions", float(report["invalid_actions"]))
        trace.record_metric("physical_diagnostic_cost", report["session"]["cost"])
        trace.record_metric("physical_num_tests", float(len(report["session"]["agent_history"])))
        trace.record_metric("physical_nominal_quality", report["score"]["nominal_quality"])
        trace.record_metric("physical_candidate_quality", report["score"]["candidate_quality"])
        trace.record_metric("physical_motion_pass", float(report["score"]["all_motion_profiles_passed"]))
        # The exchange is closed. This host evidence is never a policy message.
        trace.info["recursivecal_physical"] = report if self.config.record_evidence else {
            "task_id": TASK_ID, "report_sha256": report["report_sha256"],
            "episode": report["episode"], "commitment": report["commitment"],
            "score": report["score"], "completion_reason": report["completion_reason"],
            "source_sha256": report["source_sha256"],
        }
