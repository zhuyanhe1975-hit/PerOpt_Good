"""MuJoCo inverse dynamics feedforward.

Uses mujoco.mj_inverse to compute required generalized forces for (q, qd, qdd).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class MujocoInverseDynamicsFF:
    mjm: "object"

    def __post_init__(self) -> None:
        import mujoco

        self._mujoco = mujoco
        self._mjd = mujoco.MjData(self.mjm)

    def compute(self, inp) -> List[float]:
        # inp is FeedforwardInput-like: has q, qd, qdd
        mjd = self._mjd
        mjd.qpos[:] = inp.q
        mjd.qvel[:] = inp.qd
        # MuJoCo uses qacc for inverse dynamics
        mjd.qacc[:] = inp.qdd
        self._mujoco.mj_inverse(self.mjm, mjd)
        return mjd.qfrc_inverse.tolist()
