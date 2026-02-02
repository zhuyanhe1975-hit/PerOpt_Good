"""PID loop utilities (position/velocity/torque)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PIDState:
    integ: List[float]


class PIDLoops:
    def __init__(self, kp: List[float], ki: List[float], kd: List[float]):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.state = PIDState(integ=[0.0] * len(kp))

    def set_gains(self, kp: List[float], ki: List[float], kd: List[float]) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def reset(self) -> None:
        self.state.integ = [0.0] * len(self.state.integ)

    def step(self, err: List[float], derr: List[float], dt: float) -> List[float]:
        for i in range(len(err)):
            self.state.integ[i] += err[i] * dt
        out = []
        for i in range(len(err)):
            out.append(self.kp[i] * err[i] + self.ki[i] * self.state.integ[i] + self.kd[i] * derr[i])
        return out
