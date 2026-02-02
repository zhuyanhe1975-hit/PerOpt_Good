"""Inverse dynamics feedforward interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class FeedforwardInput:
    q: List[float]
    qd: List[float]
    qdd: List[float]


class InverseDynamicsFF:
    def __init__(self) -> None:
        pass

    def compute(self, inp: FeedforwardInput) -> List[float]:
        # Placeholder: returns zero torque until dynamics backend is wired.
        return [0.0] * len(inp.q)
