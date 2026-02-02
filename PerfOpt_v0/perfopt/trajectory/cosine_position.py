"""Cosine-based joint position reference trajectory (zero start velocity).

We want a smooth reference that starts at the current configuration with zero
velocity, without requiring a separate soft-start envelope.

Per joint (with phase fixed to 0 by default):
  q_ref(t) = q0 + sgn * B * (1 - cos(w t + phi)) / 2

Properties:
- q_ref(0) = q0
- qd_ref(0) = 0   (since sin(0)=0)
- Periodic with period 2*pi/w; returns to q0 after integer cycles.

We choose sgn to move toward the "larger margin" direction to avoid joint limits.
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
class CosinePositionTrajectory(TrajectoryPlanner):
    q0: List[float]
    qpos_min: Optional[List[float]] = None
    qpos_max: Optional[List[float]] = None
    vel_limits: Optional[List[float]] = None

    freq_hz: Union[float, Sequence[float]] = 0.5
    phase: Union[float, Sequence[float]] = 0.0
    amp_scale: float = 0.2
    duration: Optional[float] = None

    amps: Optional[List[float]] = None
    signs: Optional[List[float]] = None

    def total_time(self) -> float:
        if self.duration is not None:
            return float(self.duration)
        return 0.0

    def sample(self, t: float) -> TrajectorySample:
        n = len(self.q0)
        f = _as_list(self.freq_hz, n)
        phi = _as_list(self.phase, n)

        if self.amps is None or self.signs is None:
            self.amps, self.signs = self._compute_amps_and_signs(n, f)
        B = self.amps
        sgn = self.signs

        q_ref: List[float] = []
        qd_ref: List[float] = []
        qdd_ref: List[float] = []
        qddd_ref: List[float] = []

        for j in range(n):
            w = 2.0 * math.pi * float(f[j])
            th = w * float(t) + float(phi[j])
            cos_th = math.cos(th)
            sin_th = math.sin(th)

            # q = q0 + sgn*B*(1-cos)/2
            q = self.q0[j] + sgn[j] * B[j] * (1.0 - cos_th) * 0.5
            qd = sgn[j] * B[j] * (w * sin_th) * 0.5
            qdd = sgn[j] * B[j] * (w * w * cos_th) * 0.5
            qddd = 0.0

            q_ref.append(q)
            qd_ref.append(qd)
            qdd_ref.append(qdd)
            qddd_ref.append(qddd)

        return TrajectorySample(q_ref=q_ref, qd_ref=qd_ref, qdd_ref=qdd_ref, qddd_ref=qddd_ref)

    def _compute_amps_and_signs(self, n: int, f: List[float]) -> tuple[List[float], List[float]]:
        B = [0.0] * n
        sgn = [1.0] * n

        for j in range(n):
            lo = float(self.qpos_min[j]) if self.qpos_min and j < len(self.qpos_min) else -1.0e30
            hi = float(self.qpos_max[j]) if self.qpos_max and j < len(self.qpos_max) else 1.0e30

            margin_hi = 1.0e30 if hi >= 1.0e20 else (hi - self.q0[j])
            margin_lo = 1.0e30 if lo <= -1.0e20 else (self.q0[j] - lo)

            # Pick direction toward larger available margin.
            if margin_lo < margin_hi:
                sgn[j] = 1.0
                margin = margin_hi
            else:
                sgn[j] = -1.0
                margin = margin_lo

            if margin <= 0.0:
                B[j] = 0.0
            else:
                B[j] = min(float(self.amp_scale) * margin, margin)

        # Velocity-based amplitude:
        # qd_ref peak = 0.5*B*w  =>  B <= 2*vel_limit/w
        if self.vel_limits is not None:
            for j in range(n):
                w = 2.0 * math.pi * float(f[j])
                if w <= 0.0:
                    B[j] = 0.0
                    continue
                lim = abs(float(self.vel_limits[j])) if j < len(self.vel_limits) else 0.0
                if lim > 0.0:
                    B[j] = min(B[j], 2.0 * lim / w)

        return [max(0.0, x) for x in B], sgn

