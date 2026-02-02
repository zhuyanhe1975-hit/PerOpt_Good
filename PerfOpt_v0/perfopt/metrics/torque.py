"""Torque statistics."""

from __future__ import annotations

from typing import List, Tuple


def compute_torque_stats(torque: List[List[float]]) -> Tuple[float, float, float]:
    if not torque:
        return 0.0, 0.0, 0.0
    flat = [abs(v) for vec in torque for v in vec]
    if not flat:
        return 0.0, 0.0, 0.0
    t_max = max(flat)
    t_min = min(flat)
    t_mean = sum(flat) / len(flat)
    return float(t_max), float(t_min), float(t_mean)
