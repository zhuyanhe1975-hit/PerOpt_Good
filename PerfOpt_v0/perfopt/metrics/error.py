"""Path error metrics."""

from __future__ import annotations

from typing import List, Tuple


def compute_path_error(tcp: List[List[float]], tcp_ref: List[List[float]]) -> Tuple[float, float]:
    if not tcp or not tcp_ref or len(tcp) != len(tcp_ref):
        return 0.0, 0.0

    def l2(a: List[float], b: List[float]) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    errs = [l2(p, r) for p, r in zip(tcp, tcp_ref)]
    e_max = max(errs) if errs else 0.0
    rmse = (sum(e * e for e in errs) / len(errs)) ** 0.5 if errs else 0.0
    return float(e_max), float(rmse)
