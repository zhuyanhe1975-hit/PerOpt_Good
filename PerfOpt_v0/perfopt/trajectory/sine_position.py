"""Sinusoidal joint position reference trajectory with soft-start.

Position reference (per joint):
  q_ref_j(t) = q0_j + s(t) * B_j * sin(2*pi*f_j*t + phi_j)

Soft-start envelope s(t) ramps from 0->1 with s(0)=0 and s'(0)=0 to avoid a
non-zero initial cosine velocity when phi != -pi/2.

We pick B_j from joint range and optional velocity limit:
  B_j <= margin_j = min(q0_j - qmin_j, qmax_j - q0_j)
  B_j <= vel_limit_j / (2*pi*f_j)   (if vel_limits provided and f_j>0)
  B_j is also scaled by amp_scale: B_j := min(B_j, amp_scale*margin_j)
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


def _envelope_half_cos(t: float, t_ramp: float) -> tuple[float, float, float]:
    """Half-cosine envelope s(t) with s(0)=0, s'(0)=0.

    Returns (s, s_dot, s_ddot).
    """
    if t_ramp <= 0.0:
        return 1.0, 0.0, 0.0
    if t <= 0.0:
        return 0.0, 0.0, 0.5 * (math.pi / t_ramp) ** 2
    if t >= t_ramp:
        return 1.0, 0.0, 0.0

    x = math.pi * t / t_ramp
    s = 0.5 * (1.0 - math.cos(x))
    s_dot = 0.5 * (math.pi / t_ramp) * math.sin(x)
    s_ddot = 0.5 * (math.pi / t_ramp) ** 2 * math.cos(x)
    return s, s_dot, s_ddot


@dataclass
class SinePositionTrajectory(TrajectoryPlanner):
    q0: List[float]
    qpos_min: Optional[List[float]] = None
    qpos_max: Optional[List[float]] = None
    vel_limits: Optional[List[float]] = None

    freq_hz: Union[float, Sequence[float]] = 0.5
    phase: Union[float, Sequence[float]] = 0.0
    amp_scale: float = 0.2
    ramp_time: float = 0.2
    duration: Optional[float] = None

    amps: Optional[List[float]] = None

    def total_time(self) -> float:
        if self.duration is not None:
            return float(self.duration)
        return 0.0

    def sample(self, t: float) -> TrajectorySample:
        n = len(self.q0)
        f = _as_list(self.freq_hz, n)
        phi = _as_list(self.phase, n)

        if self.amps is None:
            self.amps = self._compute_pos_amps(n, f)
        B = self.amps

        s, s_dot, s_ddot = _envelope_half_cos(float(t), float(self.ramp_time))

        q_ref: List[float] = []
        qd_ref: List[float] = []
        qdd_ref: List[float] = []
        qddd_ref: List[float] = []

        for j in range(n):
            fj = float(f[j])
            w = 2.0 * math.pi * fj
            th = w * float(t) + float(phi[j])
            sin_th = math.sin(th)
            cos_th = math.cos(th)

            q = self.q0[j] + s * B[j] * sin_th
            qd = (s * B[j] * w * cos_th) + (s_dot * B[j] * sin_th)
            qdd = (s * B[j] * (-w * w) * sin_th) + (2.0 * s_dot * B[j] * w * cos_th) + (s_ddot * B[j] * sin_th)

            # We don't currently use jerk in the controller, but keep a simple placeholder.
            qddd = 0.0

            q_ref.append(q)
            qd_ref.append(qd)
            qdd_ref.append(qdd)
            qddd_ref.append(qddd)

        return TrajectorySample(q_ref=q_ref, qd_ref=qd_ref, qdd_ref=qdd_ref, qddd_ref=qddd_ref)

    def _compute_pos_amps(self, n: int, f: List[float]) -> List[float]:
        """Compute per-joint position amplitude B with range + velocity bounds."""
        B = [0.0] * n

        # Range-based amplitude.
        for j in range(n):
            lo = float(self.qpos_min[j]) if self.qpos_min and j < len(self.qpos_min) else -1.0e30
            hi = float(self.qpos_max[j]) if self.qpos_max and j < len(self.qpos_max) else 1.0e30
            margin = 1.0e30
            if not (lo <= -1.0e20 and hi >= 1.0e20):
                margin = min(self.q0[j] - lo, hi - self.q0[j])
            if margin <= 0.0:
                B[j] = 0.0
                continue
            B[j] = min(float(self.amp_scale) * margin, margin)

        # Velocity-based amplitude: peak |qd| approximately B*w (after ramp completes).
        # During ramp, envelope derivative adds an extra term: qd includes s_dot*B*sin(...).
        # Bound conservatively with: |qd| <= B*(w + s_dot_max).
        if self.vel_limits is not None:
            for j in range(n):
                w = 2.0 * math.pi * float(f[j])
                if w <= 0.0:
                    B[j] = 0.0
                    continue
                lim = abs(float(self.vel_limits[j])) if j < len(self.vel_limits) else 0.0
                if lim > 0.0:
                    s_dot_max = 0.0
                    if float(self.ramp_time) > 0.0:
                        s_dot_max = 0.5 * (math.pi / float(self.ramp_time))
                    B[j] = min(B[j], lim / (w + s_dot_max))

        return [max(0.0, x) for x in B]
