"""Single-run evaluator (skeleton)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from perfopt.metrics import (
    compute_band_energy,
    compute_cycle_time,
    compute_energy_proxy,
    compute_path_error,
    compute_torque_stats,
)
from .result import EvalResult


@dataclass
class EvalInputs:
    time: List[float]
    tcp: List[List[float]]
    tcp_ref: List[List[float]]
    freq: List[float]
    amp: List[float]
    torque: List[List[float]]
    qd: List[List[float]]
    qpos: Optional[List[List[float]]] = None
    qpos_min: Optional[List[float]] = None
    qpos_max: Optional[List[float]] = None
    torque_limit: Optional[List[float]] = None
    qd_limit: Optional[List[float]] = None
    dt: float = 0.0


class SingleRunner:
    def __init__(self, freq_band: tuple[float, float] = (0.0, 100.0)) -> None:
        self.freq_band = freq_band

    def run(self, inputs: EvalInputs) -> EvalResult:
        cycle_time = compute_cycle_time(inputs.time)
        e_max, rmse = compute_path_error(inputs.tcp, inputs.tcp_ref)
        vib_energy = compute_band_energy(inputs.freq, inputs.amp, self.freq_band)
        energy = compute_energy_proxy(inputs.torque, inputs.qd, inputs.dt)
        t_max, t_min, t_mean = compute_torque_stats(inputs.torque)

        # Constraint/limit diagnostics (kept as metrics for easier logging/penalties).
        joint_limit_violation_max = 0.0
        joint_limit_violation_sum = 0.0
        if inputs.qpos and inputs.qpos_min and inputs.qpos_max:
            qmin = inputs.qpos_min
            qmax = inputs.qpos_max
            for q in inputs.qpos:
                for qi, lo, hi in zip(q, qmin, qmax):
                    if lo > hi:
                        continue
                    v = 0.0
                    if qi < lo:
                        v = lo - qi
                    elif qi > hi:
                        v = qi - hi
                    if v > joint_limit_violation_max:
                        joint_limit_violation_max = v
                    joint_limit_violation_sum += v

        qd_util_max = 0.0
        qd_util_mean = 0.0
        if inputs.qd and inputs.qd_limit:
            denom = 0.0
            for qd in inputs.qd:
                for qdi, lim in zip(qd, inputs.qd_limit):
                    d = abs(lim)
                    if d <= 0:
                        continue
                    u = abs(qdi) / d
                    qd_util_max = max(qd_util_max, u)
                    qd_util_mean += u
                    denom += 1.0
            if denom > 0:
                qd_util_mean /= denom

        torque_util_max = 0.0
        torque_util_mean = 0.0
        if inputs.torque and inputs.torque_limit:
            denom = 0.0
            for tau in inputs.torque:
                for ti, lim in zip(tau, inputs.torque_limit):
                    d = abs(lim)
                    if d <= 0:
                        continue
                    u = abs(ti) / d
                    torque_util_max = max(torque_util_max, u)
                    torque_util_mean += u
                    denom += 1.0
            if denom > 0:
                torque_util_mean /= denom

        metrics: Dict[str, float] = {
            "cycle_time": cycle_time,
            "e_max": e_max,
            "rmse": rmse,
            "vib_energy": vib_energy,
            "energy": energy,
            "torque_max": t_max,
            "torque_min": t_min,
            "torque_mean": t_mean,
            "joint_limit_violation_max": joint_limit_violation_max,
            "joint_limit_violation_sum": joint_limit_violation_sum,
            "qd_util_max": qd_util_max,
            "qd_util_mean": qd_util_mean,
            "torque_util_max": torque_util_max,
            "torque_util_mean": torque_util_mean,
        }
        return EvalResult(metrics=metrics, meta={})
