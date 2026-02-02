"""Time (cycle/beat) metrics."""

from __future__ import annotations

from typing import List


def compute_cycle_time(time: List[float]) -> float:
    if not time:
        return 0.0
    return float(time[-1] - time[0])
