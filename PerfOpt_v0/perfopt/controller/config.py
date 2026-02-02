"""Controller configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ControllerConfig:
    kp: List[float]
    ki: List[float]
    kd: List[float]
    torque_limit: List[float]
    vel_limit: List[float]
    acc_limit: List[float]


@dataclass
class FeedforwardConfig:
    friction_params: Dict[str, float] = field(default_factory=dict)
    inertia_scale: float = 1.0
    payload_params: Dict[str, float] = field(default_factory=dict)


@dataclass
class TrajectoryConfig:
    time_scale: float = 1.0
    jerk_limit: float = 0.0
    smoothing_alpha: float = 0.0
    waypoints: List[List[float]] = field(default_factory=list)
    dt: float = 0.001
