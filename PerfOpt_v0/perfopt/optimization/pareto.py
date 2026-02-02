"""Simple Pareto front utility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ParetoPoint:
    objectives: Tuple[float, float, float]
    payload: dict


def is_dominated(a: ParetoPoint, b: ParetoPoint) -> bool:
    """Returns True if a is dominated by b (b no worse in all, better in at least one)."""
    ax = a.objectives
    bx = b.objectives
    no_worse = all(bx[i] <= ax[i] for i in range(3))
    better = any(bx[i] < ax[i] for i in range(3))
    return no_worse and better


def pareto_front(points: List[ParetoPoint]) -> List[ParetoPoint]:
    front: List[ParetoPoint] = []
    for p in points:
        dominated = False
        for q in points:
            if p is q:
                continue
            if is_dominated(p, q):
                dominated = True
                break
        if not dominated:
            front.append(p)
    return front
