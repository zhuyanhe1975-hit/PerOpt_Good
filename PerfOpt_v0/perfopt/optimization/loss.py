"""Unified loss function and weight handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class LossWeights:
    wq: float
    wt: float
    ws: float

    def normalize(self) -> "LossWeights":
        s = self.wq + self.wt + self.ws
        if s <= 0:
            return LossWeights(1.0, 0.0, 0.0)
        return LossWeights(self.wq / s, self.wt / s, self.ws / s)


def compute_loss(
    metrics: Dict[str, float],
    weights: LossWeights,
    baseline: Optional[Dict[str, float]] = None,
) -> Tuple[float, Dict[str, float]]:
    w = weights.normalize()

    def norm(key: str) -> float:
        val = metrics.get(key, 0.0)
        if baseline is None:
            return val
        base = baseline.get(key, 0.0)
        return val / base if base > 0 else val

    l_quick = norm("cycle_time") + 0.01 * norm("energy")
    l_true = norm("e_max") + norm("rmse")
    l_stable = norm("vib_energy")

    # Constraints as penalties (keep un-normalized and large enough to matter).
    jl_vmax = float(metrics.get("joint_limit_violation_max", 0.0))
    qd_util_max = float(metrics.get("qd_util_max", 0.0))
    qd_vmax = max(0.0, qd_util_max - 1.0)

    # Penalize joint limit violations strongly. Velocity violation is also penalized.
    p_joint = 1.0e3 * jl_vmax
    p_vel = 1.0e2 * qd_vmax

    total = w.wq * l_quick + w.wt * l_true + w.ws * l_stable + p_joint + p_vel
    return total, {
        "l_quick": l_quick,
        "l_true": l_true,
        "l_stable": l_stable,
        "p_joint_limit": p_joint,
        "p_vel_limit": p_vel,
    }
