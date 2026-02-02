"""Trajectory planner base interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class TrajectorySample:
    q_ref: List[float]
    qd_ref: List[float]
    qdd_ref: List[float]
    qddd_ref: List[float]


class TrajectoryPlanner:
    def __init__(self) -> None:
        self.waypoints: List[List[float]] = []
        self.dt: float = 0.001

    def set_waypoints(self, waypoints: List[List[float]]) -> None:
        self.waypoints = waypoints

    def set_dt(self, dt: float) -> None:
        self.dt = dt

    def total_time(self) -> float:
        raise NotImplementedError

    def sample(self, t: float) -> TrajectorySample:
        raise NotImplementedError
