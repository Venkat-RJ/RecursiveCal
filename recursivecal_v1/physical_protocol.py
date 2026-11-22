"""JSON dialogue adapter for the SI research rig, separate from the legacy task.

The evaluator owns this adapter. Send only observation()/act() strings to a
policy process. reward() and host_report() are training/evaluation outputs.
"""
from __future__ import annotations

import json
from typing import Any

from recursivecal_lab.rl_environment import MAX_TURNS, PhysicalCalibrationEnv

SYSTEM_PROMPT = """Investigate a simulated physical liftgate and commit one calibration, or abstain.
You observe timestamped angle, angular rate and total force per strut. The hidden
physical parameters and verification results are not available during the episode.
Choose only experiments listed as currently legal. State persists between tests.
Reply with exactly one JSON object per turn:
  {"experiment":"high_sweep"}
  {"commit":{"mass_kg":25,"motor_efficiency":1,"gas_scale":1,"friction_coulomb_Nm":6,"sensor_bias_rad":0}}
  {"abstain":true}
The observation gives calibration bounds, remaining budget and remaining turns.
A commitment is final. Abstention keeps nominal calibration. A separate evaluator
tests the frozen choice on four motion profiles. Reward is improvement over the
nominal controller, minus experiment cost and failed-commit penalties. Two invalid
actions terminate the episode with nominal calibration and a penalty.
All coefficients and sensors are synthetic. No physical hardware is connected.
"""


class PhysicalCalibrationDialogue:
    def __init__(self, seed: int = 0, *, split: str = "train", **environment_kwargs: Any):
        self.__env = PhysicalCalibrationEnv(**environment_kwargs)
        self.__observation, _ = self.__env.reset(seed=seed, split=split)

    @property
    def completed(self) -> bool:
        return self.__env.completed

    def observation(self) -> str:
        return json.dumps(self.__observation, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def act(self, response: str) -> tuple[str, bool]:
        observation, _, terminated, truncated, info = self.__env.step(response)
        self.__observation = observation
        if terminated or truncated:
            # Do not expose verifier scores or truth as another policy turn.
            return json.dumps({"status": "submitted", "reason": info["completion_reason"]},
                              separators=(",", ":")), True
        if "error" in info:
            self.__observation = {**observation, "error": info["error"]}
        return self.observation(), False

    def reward(self) -> float:
        return self.__env.terminal_reward

    def force_end(self, reason: str = "agent_stopped") -> None:
        """Host-only normal model-stop handling; never a free implicit abstention."""
        self.__observation, _, _, _, _ = self.__env.force_end(reason)

    def host_report(self) -> dict[str, Any]:
        return self.__env.host_report()
