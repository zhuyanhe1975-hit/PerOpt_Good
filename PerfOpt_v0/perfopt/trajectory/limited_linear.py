"""Velocity-limited joint-space linear trajectory.

Each segment duration is chosen so that |qd_ref_i| <= vel_limit_i.
This prevents unrealistic reference speeds that cause torque saturation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .base import TrajectoryPlanner, TrajectorySample


@dataclass
class VelocityLimitedLinearTrajectory(TrajectoryPlanner):
    vel_limits: Optional[List[float]] = None

    def _seg_duration(self, q0: List[float], q1: List[float]) -> float:
        if not self.vel_limits:
            return self.dt
        max_t = self.dt
        for dq, vlim in zip((b - a for a, b in zip(q0, q1)), self.vel_limits):
            v = abs(vlim)
            if v <= 0:
                continue
            max_t = max(max_t, abs(dq) / v)
        return max_t

    def total_time(self) -> float:
        if len(self.waypoints) < 2:
            return 0.0
        t = 0.0
        for i in range(len(self.waypoints) - 1):
            t += self._seg_duration(self.waypoints[i], self.waypoints[i + 1])
        return float(t)

    def sample(self, t: float) -> TrajectorySample:
        if len(self.waypoints) < 2:
            n = len(self.waypoints[0]) if self.waypoints else 0
            return TrajectorySample([0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n)

        # Find segment index by accumulating durations.
        seg_t0 = 0.0
        idx = 0
        for i in range(len(self.waypoints) - 1):
            dur = self._seg_duration(self.waypoints[i], self.waypoints[i + 1])
            if t <= seg_t0 + dur or i == len(self.waypoints) - 2:
                idx = i
                seg_dur = dur
                break
            seg_t0 += dur

        q0 = self.waypoints[idx]
        q1 = self.waypoints[idx + 1]
        alpha = 0.0 if seg_dur <= 0 else min(1.0, max(0.0, (t - seg_t0) / seg_dur))

        q_ref = [(1 - alpha) * a + alpha * b for a, b in zip(q0, q1)]
        qd_ref = [(b - a) / seg_dur for a, b in zip(q0, q1)]
        qdd_ref = [0.0] * len(q_ref)
        qddd_ref = [0.0] * len(q_ref)

        return TrajectorySample(q_ref, qd_ref, qdd_ref, qddd_ref)
