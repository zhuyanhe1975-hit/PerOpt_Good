"""Sinusoidal joint velocity reference trajectory.

We define per-joint reference velocity:
  qd_ref_j(t) = A_j * sin(2*pi*f_j*t + phi_j)

where A_j is clipped so that |qd_ref_j(t)| <= vel_limit_j (peak bound).
Position reference is the integral with q_ref_j(0) = q0_j:
  q_ref_j(t) = q0_j + (A_j/(2*pi*f_j)) * (1 - cos(2*pi*f_j*t + phi_j)) - (A_j/(2*pi*f_j)) * (1 - cos(phi_j))

This yields a smooth (C-infinity) reference with bounded peak velocity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

from .base import TrajectoryPlanner, TrajectorySample


def _as_list(x: Union[float, Sequence[float]], n: int) -> List[float]:
    if isinstance(x, (list, tuple)):
        vals = [float(v) for v in x]
        if len(vals) < n:
            return vals + [vals[-1]] * (n - len(vals))
        return vals[:n]
    return [float(x)] * n


@dataclass
class SineVelocityTrajectory(TrajectoryPlanner):
    q0: List[float]
    vel_limits: Optional[List[float]] = None
    qpos_min: Optional[List[float]] = None
    qpos_max: Optional[List[float]] = None
    freq_hz: Union[float, Sequence[float]] = 0.5
    phase: Union[float, Sequence[float]] = 0.0
    amp_scale: float = 1.0
    duration: Optional[float] = None
    amps: Optional[List[float]] = None

    def total_time(self) -> float:
        # Prefer explicit duration; otherwise infer from dt if possible.
        if self.duration is not None:
            return float(self.duration)
        return 0.0

    def sample(self, t: float) -> TrajectorySample:
        n = len(self.q0)
        f = _as_list(self.freq_hz, n)
        phi = _as_list(self.phase, n)

        # Amplitude A_j is computed once and cached in self.amps.
        if self.amps is None:
            self.amps = self._compute_amps(n, f)
        A = self.amps

        q_ref: List[float] = []
        qd_ref: List[float] = []
        qdd_ref: List[float] = []
        qddd_ref: List[float] = []

        for j in range(n):
            fj = float(f[j])
            w = 2.0 * math.pi * fj
            th = w * float(t) + float(phi[j])

            # Velocity / acceleration.
            qd = A[j] * math.sin(th)
            qdd = A[j] * w * math.cos(th)
            qddd = -A[j] * (w * w) * math.sin(th)

            # Position is integral of qd, shifted so q_ref(0)=q0.
            if w > 0.0:
                c0 = 1.0 - math.cos(float(phi[j]))
                q = self.q0[j] + (A[j] / w) * (1.0 - math.cos(th) - c0)
            else:
                # Degenerate: zero frequency => constant velocity 0 in our definition.
                q = self.q0[j]

            q_ref.append(q)
            qd_ref.append(qd)
            qdd_ref.append(qdd)
            qddd_ref.append(qddd)

        return TrajectorySample(q_ref=q_ref, qd_ref=qd_ref, qdd_ref=qdd_ref, qddd_ref=qddd_ref)

    def _compute_amps(self, n: int, f: List[float]) -> List[float]:
        """Compute per-joint velocity amplitude A with both velocity and position bounds."""
        # First: velocity peak bound from vel_limits.
        if self.vel_limits is None:
            A = [0.0] * n
        else:
            A = []
            for lim in self.vel_limits[:n]:
                lim_abs = abs(float(lim))
                a = lim_abs * float(self.amp_scale)
                # Ensure peak does not exceed limit.
                A.append(min(a, lim_abs))

        # Second: position excursion bound from joint range.
        # With q_ref(t) = q0 + (A/w) * (cos(phi) - cos(wt+phi)),
        # max |q_ref - q0| <= 2A/w. To keep q within [qmin, qmax], require 2A/w <= margin.
        if not (self.qpos_min and self.qpos_max):
            return A

        qmin = self.qpos_min[:n]
        qmax = self.qpos_max[:n]
        for j in range(n):
            lo = float(qmin[j]) if j < len(qmin) else -1.0e30
            hi = float(qmax[j]) if j < len(qmax) else 1.0e30
            if lo <= -1.0e20 and hi >= 1.0e20:
                continue  # effectively unbounded
            margin = min(self.q0[j] - lo, hi - self.q0[j])
            if margin <= 0.0:
                A[j] = 0.0
                continue
            w = 2.0 * math.pi * float(f[j])
            if w <= 0.0:
                A[j] = 0.0
                continue
            a_pos_max = 0.5 * w * margin
            if A[j] > a_pos_max:
                A[j] = max(0.0, a_pos_max)
        return A
