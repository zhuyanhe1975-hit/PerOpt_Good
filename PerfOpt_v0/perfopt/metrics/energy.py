"""Energy-related metrics (torque power proxy)."""

from __future__ import annotations

from typing import List


def compute_energy_proxy(torque: List[List[float]], qd: List[List[float]], dt: float) -> float:
    if not torque or not qd or len(torque) != len(qd):
        return 0.0
    total = 0.0
    for tau_vec, qd_vec in zip(torque, qd):
        total += sum(abs(t) * abs(v) for t, v in zip(tau_vec, qd_vec))
    denom = max(1, len(torque) * (len(torque[0]) if torque and torque[0] else 1))
    return float(total) * max(0.0, dt) / denom
