"""Scenario weight templates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from perfopt.optimization.loss import LossWeights


@dataclass
class Scenario:
    name: str
    weights: LossWeights
    constraints: Dict[str, float]


def load_default_scenarios() -> Dict[str, Scenario]:
    return {
        "quickmove": Scenario(
            name="quickmove",
            weights=LossWeights(0.7, 0.2, 0.1),
            constraints={"torque_utilization": 0.95},
        ),
        "truemove": Scenario(
            name="truemove",
            weights=LossWeights(0.15, 0.7, 0.15),
            constraints={"max_path_error": 0.2},
        ),
        "stablemove": Scenario(
            name="stablemove",
            weights=LossWeights(0.1, 0.2, 0.7),
            constraints={"vibration_band": 50.0},
        ),
    }
