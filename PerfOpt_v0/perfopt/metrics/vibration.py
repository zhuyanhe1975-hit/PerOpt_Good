"""Vibration metrics (frequency-domain energy)."""

from __future__ import annotations

from typing import List, Tuple


def compute_band_energy(freq: List[float], amp: List[float], band: Tuple[float, float]) -> float:
    if not freq or not amp or len(freq) != len(amp):
        return 0.0
    lo, hi = band
    energy = 0.0
    for f, a in zip(freq, amp):
        if lo <= f <= hi:
            energy += a * a
    return float(energy) / max(1, len(freq))
