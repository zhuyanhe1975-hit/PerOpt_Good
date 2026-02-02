#!/usr/bin/env python3
"""PerfOpt v0 CLI (single entrypoint).

This file contains the implementation for `scripts/run_v0.py`.
Keep the surface area small and avoid adding extra subcommands.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _parse_csv_floats(s: Optional[str]) -> Optional[List[float]]:
    if s is None or str(s).strip() == "":
        return None
    return [float(x) for x in str(s).split(",") if str(x).strip() != ""]


def _parse_pair(s: str, *, name: str) -> Tuple[float, float]:
    vals = _parse_csv_floats(s)
    if not vals or len(vals) != 2:
        raise ValueError(f"{name} must be like 'min,max'")
    return float(vals[0]), float(vals[1])


def _parse_freq_band(s: str) -> Tuple[float, float]:
    lo, hi = _parse_pair(s, name="--freq-band")
    return lo, hi


def _fmt_vec(v: Sequence[float], max_len: int = 6) -> str:
    if not v:
        return "[]"
    v = list(v)[:max_len]
    return "[" + ",".join(f"{x:.2f}" for x in v) + "]"


def _load_config(argv: List[str]) -> Dict[str, Any]:
    # Default behavior: if user doesn't pass --config, try repo default.
    if "--config" not in argv:
        default_path = Path("configs/run_v0_defaults.json")
        if default_path.exists():
            path = default_path
        else:
            return {}
    else:
        idx = argv.index("--config")
        if idx + 1 >= len(argv):
            raise SystemExit("error: --config requires a path")
        path = Path(argv[idx + 1])
    if not path.exists():
        raise SystemExit(f"error: config not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"error: failed to load config json: {path}: {e}")


def _apply_config_defaults(parser: argparse.ArgumentParser, cfg: Dict[str, Any]) -> None:
    if not cfg:
        return

    def csv(v) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return ",".join(str(x) for x in v)
        return str(v)

    # Back-compat: older configs used boolean `ideal` instead of `ff_mode="ideal"`.
    ff_mode = cfg.get("ff_mode", None)
    if ff_mode is None and bool(cfg.get("ideal", False)):
        ff_mode = "ideal"

    parser.set_defaults(
        mjcf=cfg.get("mjcf", cfg.get("mjcf_path")),
        dt=cfg.get("dt", parser.get_default("dt")),
        steps=cfg.get("steps", parser.get_default("steps")),
        integrator=cfg.get("integrator", parser.get_default("integrator")),
        freq_band=csv(cfg.get("freq_band")) or parser.get_default("freq_band"),
        traj=cfg.get("traj", parser.get_default("traj")),
        sine_freq=cfg.get("sine_freq", parser.get_default("sine_freq")),
        sine_phase=cfg.get("sine_phase", parser.get_default("sine_phase")),
        sine_amp_scale=cfg.get("sine_amp_scale", parser.get_default("sine_amp_scale")),
        sine_ramp_time=cfg.get("sine_ramp_time", parser.get_default("sine_ramp_time")),
        sine_cycles=cfg.get("sine_cycles", parser.get_default("sine_cycles")),
        dq=csv(cfg.get("dq")),
        vel_limits=csv(cfg.get("vel_limits")),
        torque_limit=csv(cfg.get("torque_limit")),
        kp=csv(cfg.get("kp")),
        ki=csv(cfg.get("ki")),
        kd=csv(cfg.get("kd")),
        ff_mode=ff_mode if ff_mode is not None else parser.get_default("ff_mode"),
        preset=cfg.get("preset", parser.get_default("preset")),
        weights=csv(cfg.get("weights")),
        use_baseline=bool(cfg.get("use_baseline", parser.get_default("use_baseline"))),
        engine=cfg.get("engine", parser.get_default("engine")),
        jobs=int(cfg.get("jobs", parser.get_default("jobs"))),
        jobs_backend=cfg.get("jobs_backend", parser.get_default("jobs_backend")),
        target_e_max=cfg.get("target_e_max", parser.get_default("target_e_max")),
        max_trials=int(cfg.get("max_trials", parser.get_default("max_trials"))),
        seed=int(cfg.get("seed", parser.get_default("seed"))),
        print_interval=cfg.get("print_interval", parser.get_default("print_interval")),
        kp_range=csv(cfg.get("kp_range")) or parser.get_default("kp_range"),
        kd_range=csv(cfg.get("kd_range")) or parser.get_default("kd_range"),
        ki_range=csv(cfg.get("ki_range")) or parser.get_default("ki_range"),
        optuna_timeout=cfg.get("optuna_timeout", parser.get_default("optuna_timeout")),
        optuna_storage=cfg.get("optuna_storage", parser.get_default("optuna_storage")),
        study_name=cfg.get("study_name", parser.get_default("study_name")),
        viewer=bool(cfg.get("viewer", parser.get_default("viewer"))),
        quiet=bool(cfg.get("quiet", parser.get_default("quiet"))),
    )


@dataclass
class RunContext:
    mjcf_path: str
    dt: float
    steps: int
    integrator: str
    freq_band: Tuple[float, float]
    traj: str
    waypoints: Optional[List[List[float]]]
    vel_limits: Optional[List[float]]
    sine_freq_hz: float
    sine_phase: float
    sine_amp_scale: float
    sine_ramp_time: float
    torque_limit: Optional[List[float]]
    weights: Optional[Dict[str, float]]
    baseline_metrics: Optional[Dict[str, float]]
    dof_damping: Optional[float]
    dof_armature: Optional[float]
    use_ff: bool
    computed_torque: bool
    disable_limits: bool
    ff_mode: str

    def run(
        self,
        *,
        kp: Optional[Sequence[float]] = None,
        ki: Optional[Sequence[float]] = None,
        kd: Optional[Sequence[float]] = None,
        viewer: bool = False,
        viewer_loop: bool = False,
        debug_ct: bool = False,
        return_payload: bool = False,
    ) -> Dict[str, Any]:
        from perfopt import run_v0

        return run_v0(
            mjcf_path=self.mjcf_path,
            dt=self.dt,
            steps=self.steps,
            integrator=str(self.integrator),
            traj=self.traj,
            waypoints=self.waypoints,
            vel_limits=self.vel_limits,
            sine_freq_hz=self.sine_freq_hz,
            sine_phase=self.sine_phase,
            sine_amp_scale=self.sine_amp_scale,
            sine_ramp_time=self.sine_ramp_time,
            kp=list(kp) if kp is not None else None,
            ki=list(ki) if ki is not None else None,
            kd=list(kd) if kd is not None else None,
            torque_limit=self.torque_limit,
            weights=self.weights,
            baseline_metrics=self.baseline_metrics,
            freq_band=self.freq_band,
            dof_damping=self.dof_damping,
            dof_armature=self.dof_armature,
            use_mujoco_inverse_dynamics_ff=self.use_ff,
            ff_mode=str(self.ff_mode),
            computed_torque=bool(self.computed_torque),
            disable_limits=bool(self.disable_limits),
            debug_ct=bool(debug_ct),
            viewer=bool(viewer),
            viewer_loop=bool(viewer_loop),
            return_payload=return_payload,
        )


def _plot_tcp_error(*, before: dict, after: dict, out_path: str) -> None:
    try:
        import numpy as np
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("Plotting requires numpy + matplotlib in the active environment") from e

    def series(run: dict) -> tuple["np.ndarray", "np.ndarray"]:
        payload = run.get("payload") or {}
        t = np.asarray(payload.get("time", []), dtype=float)
        tcp = np.asarray(payload.get("tcp", []), dtype=float)
        ref = np.asarray(payload.get("tcp_ref", []), dtype=float)
        if t.size == 0 or tcp.size == 0 or ref.size == 0:
            return np.zeros((0,), dtype=float), np.zeros((0,), dtype=float)
        n = min(len(t), len(tcp), len(ref))
        t = t[:n]
        e = np.linalg.norm(tcp[:n] - ref[:n], axis=1)
        return t, e

    t0, e0 = series(before)
    t1, e1 = series(after)

    if e0.size == 0 or e1.size == 0:
        raise RuntimeError("Missing payload in before/after runs; re-run with --plot-tcp-error")

    fig = plt.figure(figsize=(10, 4))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(t0, e0, label="before", linewidth=1.5)
    ax.plot(t1, e1, label="after", linewidth=1.5)
    ax.axhline(0.1, color="k", linestyle="--", linewidth=1.0, alpha=0.6, label="target 0.1m")
    ax.set_title("TCP tracking error: before vs after")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("||tcp - tcp_ref|| (m)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, dpi=160)
    plt.close(fig)
    print(f"wrote: {p}")


def _plot_torque_single(*, run: dict, out_path: str, max_points: int = 5000) -> None:
    """Plot time vs joint torques for a single run."""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("Plotting requires numpy + matplotlib in the active environment") from e

    payload = run.get("payload") or {}
    t = np.asarray(payload.get("time", []), dtype=float)
    tau = np.asarray(payload.get("torque", []), dtype=float)
    if t.size == 0 or tau.size == 0 or tau.ndim != 2:
        raise RuntimeError("Missing torque payload; re-run with return_payload=True")

    n = min(len(t), len(tau))
    t = t[:n]
    tau = tau[:n]
    if n > max_points:
        idx = np.linspace(0, n - 1, num=max_points, dtype=int)
        t = t[idx]
        tau = tau[idx]

    nv = int(tau.shape[1])
    fig, axes = plt.subplots(nv, 1, figsize=(12, max(6, 1.6 * nv)), sharex=True)
    if nv == 1:
        axes = [axes]

    for j in range(nv):
        axes[j].plot(t, tau[:, j], linewidth=1.0)
        axes[j].axhline(0.0, color="k", linewidth=0.8, alpha=0.4)
        axes[j].set_ylabel(f"tau[{j}] (Nm)")
        axes[j].grid(True, alpha=0.2)

    axes[-1].set_xlabel("time (s)")
    fig.suptitle("Joint torque over time", y=0.995)

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, dpi=160)
    plt.close(fig)
    print(f"wrote: {p}")


def _plot_tcp_error_multi(*, runs: Dict[str, dict], out_path: str) -> None:
    """Plot time vs TCP error for multiple runs."""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("Plotting requires numpy + matplotlib in the active environment") from e

    fig = plt.figure(figsize=(11, 4.5))
    ax = fig.add_subplot(1, 1, 1)

    for name, run in runs.items():
        payload = run.get("payload") or {}
        t = np.asarray(payload.get("time", []), dtype=float)
        tcp = np.asarray(payload.get("tcp", []), dtype=float)
        ref = np.asarray(payload.get("tcp_ref", []), dtype=float)
        if t.size == 0 or tcp.size == 0 or ref.size == 0:
            continue
        n = min(len(t), len(tcp), len(ref))
        t = t[:n]
        e = np.linalg.norm(tcp[:n] - ref[:n], axis=1)
        ax.plot(t, e, label=name, linewidth=1.6)

    ax.axhline(0.0001, color="k", linestyle="--", linewidth=1.0, alpha=0.6, label="0.1mm")
    ax.set_title("TCP tracking error (m): feedforward/computed-torque comparison")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("||tcp - tcp_ref|| (m)")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, dpi=160)
    plt.close(fig)
    print(f"wrote: {p}")


def _plot_torque_multi(*, runs: Dict[str, dict], out_path: str, max_points: int = 5000) -> None:
    """Plot time vs joint torques for multiple runs.

    The plot uses one subplot per joint and overlays all run curves.
    Large runs are downsampled for reasonable rendering time.
    """
    try:
        import numpy as np
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("Plotting requires numpy + matplotlib in the active environment") from e

    # Determine joint count from first available run.
    nv = 0
    for run in runs.values():
        payload = run.get("payload") or {}
        tau = payload.get("torque") or []
        if tau and isinstance(tau[0], list):
            nv = len(tau[0])
            break
    if nv <= 0:
        raise RuntimeError("Missing torque payload; re-run with return_payload=True")

    fig, axes = plt.subplots(nv, 1, figsize=(12, max(6, 1.6 * nv)), sharex=True)
    if nv == 1:
        axes = [axes]

    for name, run in runs.items():
        payload = run.get("payload") or {}
        t = np.asarray(payload.get("time", []), dtype=float)
        tau = np.asarray(payload.get("torque", []), dtype=float)
        if t.size == 0 or tau.size == 0:
            continue
        n = min(len(t), len(tau))
        t = t[:n]
        tau = tau[:n]

        # Downsample uniformly for plotting.
        if n > max_points:
            idx = np.linspace(0, n - 1, num=max_points, dtype=int)
            t = t[idx]
            tau = tau[idx]

        for j in range(min(nv, tau.shape[1] if tau.ndim > 1 else 0)):
            axes[j].plot(t, tau[:, j], linewidth=1.0, label=name)

    for j in range(nv):
        axes[j].axhline(0.0, color="k", linewidth=0.8, alpha=0.4)
        axes[j].set_ylabel(f"tau[{j}] (Nm)")
        axes[j].grid(True, alpha=0.2)
        if j == 0:
            axes[j].legend(loc="best")

    axes[-1].set_xlabel("time (s)")
    fig.suptitle("Joint torque over time: feedforward/computed-torque comparison", y=0.995)

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, dpi=160)
    plt.close(fig)
    print(f"wrote: {p}")


def _maybe_load_result(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    return json.loads(p.read_text(encoding="utf-8"))


def _summarize_debug_ct(run: dict) -> dict:
    payload = run.get("payload") or {}
    t = payload.get("time") or []
    q_err = payload.get("q_err") or []
    tau_res_l2 = payload.get("tau_res_l2") or []
    tau_res = payload.get("tau_res") or []
    qdd_err = payload.get("qdd_err") or []
    tcp = payload.get("tcp") or []
    tcp_ref = payload.get("tcp_ref") or []

    # Residual summary.
    res_max = None
    res_t = None
    if tau_res_l2:
        res_max = float(max(tau_res_l2))
        i = int(max(range(len(tau_res_l2)), key=lambda k: float(tau_res_l2[k])))
        res_t = float(t[i]) if i < len(t) else None

    # Joint error summary (per joint max abs error and when it happens).
    per_joint = []
    if q_err:
        n = len(q_err[0]) if isinstance(q_err[0], list) else 0
        for j in range(n):
            best = 0.0
            best_i = 0
            mean_abs = 0.0
            denom = 0.0
            for i, e in enumerate(q_err):
                if not isinstance(e, list) or j >= len(e):
                    continue
                a = abs(float(e[j]))
                mean_abs += a
                denom += 1.0
                if a > best:
                    best = a
                    best_i = i
            if denom > 0:
                mean_abs /= denom
            per_joint.append(
                {
                    "joint": j,
                    "q_err_abs_max": float(best),
                    "t_at_max_s": float(t[best_i]) if best_i < len(t) else None,
                    "q_err_abs_mean": float(mean_abs),
                }
            )

    # Torque residual per-joint max abs.
    tau_res_per_joint = []
    if tau_res:
        n = len(tau_res[0]) if isinstance(tau_res[0], list) else 0
        for j in range(n):
            best = 0.0
            best_i = 0
            mean_abs = 0.0
            denom = 0.0
            for i, r in enumerate(tau_res):
                if not isinstance(r, list) or j >= len(r):
                    continue
                a = abs(float(r[j]))
                mean_abs += a
                denom += 1.0
                if a > best:
                    best = a
                    best_i = i
            if denom > 0:
                mean_abs /= denom
            tau_res_per_joint.append(
                {
                    "joint": j,
                    "tau_res_abs_max": float(best),
                    "t_at_max_s": float(t[best_i]) if best_i < len(t) else None,
                    "tau_res_abs_mean": float(mean_abs),
                }
            )

    def _first_nonempty(hist):
        for row in hist:
            if isinstance(row, list) and len(row) > 0:
                return row
        return None

    # Acceleration tracking error per-joint max abs.
    qdd_err_per_joint = []
    if qdd_err:
        first = _first_nonempty(qdd_err)
        n = len(first) if first is not None else 0
        for j in range(n):
            best = 0.0
            best_i = 0
            mean_abs = 0.0
            denom = 0.0
            for i, e in enumerate(qdd_err):
                if not isinstance(e, list) or j >= len(e):
                    continue
                a = abs(float(e[j]))
                mean_abs += a
                denom += 1.0
                if a > best:
                    best = a
                    best_i = i
            if denom > 0:
                mean_abs /= denom
            qdd_err_per_joint.append(
                {
                    "joint": j,
                    "qdd_err_abs_max": float(best),
                    "t_at_max_s": float(t[best_i]) if best_i < len(t) else None,
                    "qdd_err_abs_mean": float(mean_abs),
                }
            )

    # TCP tracking error (norm) statistics.
    tcp_err = []
    if t and tcp and tcp_ref:
        n = min(len(t), len(tcp), len(tcp_ref))
        for i in range(n):
            try:
                dx = float(tcp[i][0]) - float(tcp_ref[i][0])
                dy = float(tcp[i][1]) - float(tcp_ref[i][1])
                dz = float(tcp[i][2]) - float(tcp_ref[i][2])
                tcp_err.append((dx * dx + dy * dy + dz * dz) ** 0.5)
            except Exception:
                tcp_err.append(0.0)

    tcp_stats = {}
    if tcp_err:
        tcp_mean = sum(float(x) for x in tcp_err) / float(len(tcp_err))
        tcp_max = max(float(x) for x in tcp_err)
        i = int(max(range(len(tcp_err)), key=lambda k: float(tcp_err[k])))
        tcp_stats = {
            "tcp_err_mean_m": float(tcp_mean),
            "tcp_err_max_m": float(tcp_max),
            "tcp_err_t_at_max_s": float(t[i]) if i < len(t) else None,
        }

    return {
        "tau_res_l2_max": res_max,
        "tau_res_l2_t_at_max_s": res_t,
        "per_joint": per_joint,
        "tau_res_per_joint": tau_res_per_joint,
        "qdd_err_per_joint": qdd_err_per_joint,
        "tcp": tcp_stats,
    }


def _plot_error_time_series(*, dbg_out: dict, out_path: str) -> None:
    """Plot time vs TCP error + per-joint |q_err| for the worst joint."""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("Plotting requires numpy + matplotlib in the active environment") from e

    run = (dbg_out.get("run") or {})
    payload = (run.get("payload") or {})
    t = np.asarray(payload.get("time", []), dtype=float)
    tcp = np.asarray(payload.get("tcp", []), dtype=float)
    tcp_ref = np.asarray(payload.get("tcp_ref", []), dtype=float)
    q_err = payload.get("q_err") or []

    if t.size == 0 or tcp.size == 0 or tcp_ref.size == 0:
        raise RuntimeError("debug_ct payload missing time/tcp/tcp_ref; re-run with --debug-ct")

    n = min(len(t), len(tcp), len(tcp_ref))
    t = t[:n]
    tcp_err = np.linalg.norm(tcp[:n] - tcp_ref[:n], axis=1)

    # Pick the joint with the largest abs max error.
    worst_j = None
    worst_j_max = -1.0
    if q_err and isinstance(q_err[0], list):
        nq = len(q_err[0])
        for j in range(nq):
            m = 0.0
            for row in q_err[:n]:
                if not isinstance(row, list) or j >= len(row):
                    continue
                m = max(m, abs(float(row[j])))
            if m > worst_j_max:
                worst_j_max = m
                worst_j = j

    fig = plt.figure(figsize=(11, 5))
    ax = fig.add_subplot(1, 1, 1)
    ax.plot(t, tcp_err, label="TCP error (m)", linewidth=1.6)
    ax.axhline(0.1, color="k", linestyle="--", linewidth=1.0, alpha=0.6, label="0.1m")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("error")
    ax.grid(True, alpha=0.25)

    if worst_j is not None:
        qe = np.asarray([abs(float(row[worst_j])) if isinstance(row, list) and worst_j < len(row) else 0.0 for row in q_err[:n]], dtype=float)
        ax2 = ax.twinx()
        ax2.plot(t, qe, color="#d95f02", alpha=0.85, linewidth=1.2, label=f"|q_err| joint {worst_j} (rad)")
        ax2.set_ylabel("joint error (rad)")
        # Merge legends
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    else:
        ax.legend(loc="upper right")

    fig.suptitle("Tracking error over time (debug_ct)")
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, dpi=160)
    plt.close(fig)


def _feasible(metrics: Dict[str, float]) -> bool:
    jl = float(metrics.get("joint_limit_violation_max", 0.0))
    qd_u = float(metrics.get("qd_util_max", 0.0))
    return (jl <= 0.0) and (qd_u <= 1.0 + 1.0e-9)


def _optimize_random(
    *,
    ctx: RunContext,
    target_e_max: float,
    max_trials: int,
    seed: int,
    print_interval_s: float,
    kp_range: Tuple[float, float],
    kd_range: Tuple[float, float],
    ki_range: Tuple[float, float],
) -> Dict[str, Any]:
    if kp_range[0] <= 0 or kd_range[0] <= 0:
        raise ValueError("kp/kd ranges must be positive for log-uniform sampling")
    if ki_range[0] < 0 or ki_range[1] < 0 or ki_range[0] > ki_range[1]:
        raise ValueError("ki-range must be non-negative and min<=max")

    # "Base strong, wrist weak" scaling of ranges; still independent per joint.
    gain_profile = [1.0, 1.0, 0.85, 0.65, 0.45, 0.35]

    def log_uniform(rng: random.Random, lo: float, hi: float) -> float:
        u = rng.random()
        return lo * ((hi / lo) ** u)

    rng = random.Random(seed)
    best = None
    best_e = float("inf")
    best_any = None
    best_any_e = float("inf")

    t0 = time.perf_counter()
    last_print = t0

    for trial in range(1, int(max_trials) + 1):
        n = len(gain_profile)
        kp = [log_uniform(rng, kp_range[0] * gain_profile[j], kp_range[1] * gain_profile[j]) for j in range(n)]
        kd = [log_uniform(rng, kd_range[0] * gain_profile[j], kd_range[1] * gain_profile[j]) for j in range(n)]
        if ki_range[1] <= 0.0:
            ki = [0.0] * n
        elif ki_range[0] <= 0.0:
            ki = [ki_range[1] * gain_profile[j] * rng.random() for j in range(n)]
        else:
            ki = [log_uniform(rng, ki_range[0] * gain_profile[j], ki_range[1] * gain_profile[j]) for j in range(n)]

        out = ctx.run(kp=kp, ki=ki, kd=kd, return_payload=False)
        m = out["metrics"]
        e_max = float(m.get("e_max", 0.0))
        feas = _feasible(m)

        if e_max < best_any_e:
            best_any_e, best_any = e_max, out
        if feas and e_max < best_e:
            best_e, best = e_max, out

        now = time.perf_counter()
        if (now - last_print) >= float(print_interval_s):
            shown = best if best is not None else best_any
            ctrl = (shown or {}).get("config", {}).get("controller", {})
            best_kp = ctrl.get("kp") or []
            best_kd = ctrl.get("kd") or []
            jl = float(m.get("joint_limit_violation_max", 0.0))
            qd_u = float(m.get("qd_util_max", 0.0))
            print(
                "t=%.1fs  trial=%d  best_e_max=%.4f  last_e_max=%.4f  last(jl=%.4g,qd_u=%.3f)  best(kp=%s,kd=%s)"
                % (now - t0, trial, best_e if best is not None else best_any_e, e_max, jl, qd_u, _fmt_vec(best_kp), _fmt_vec(best_kd))
            )
            last_print = now

        if best is not None and best_e <= float(target_e_max):
            print("target reached: best_e_max=%.6f <= %.6f (feasible)" % (best_e, float(target_e_max)))
            return best

    out = best if best is not None else best_any
    if best is not None:
        print("stopped: max_trials reached; best_e_max=%.6f" % best_e)
    else:
        print("stopped: max_trials reached; no feasible trial found; best_any_e_max=%.6f" % best_any_e)
    return out


def _optimize_optuna(
    *,
    ctx: RunContext,
    target_e_max: float,
    max_trials: int,
    seed: int,
    n_jobs: int,
    print_interval_s: float,
    timeout_s: Optional[float],
    kp_range: Tuple[float, float],
    kd_range: Tuple[float, float],
    ki_range: Tuple[float, float],
    optuna_storage: Optional[str],
    study_name: Optional[str],
    init_kp: Optional[List[float]] = None,
    init_kd: Optional[List[float]] = None,
    init_ki: Optional[List[float]] = None,
    enqueue_init: bool = True,
) -> Dict[str, Any]:
    from perfopt.optimization import run_optuna

    if kp_range[0] <= 0 or kd_range[0] <= 0:
        raise ValueError("kp/kd ranges must be positive for log-uniform sampling")
    if ki_range[0] < 0 or ki_range[1] < 0 or ki_range[0] > ki_range[1]:
        raise ValueError("ki-range must be non-negative and min<=max")

    gain_profile = [1.0, 1.0, 0.85, 0.65, 0.45, 0.35]
    n = len(gain_profile)
    lock = threading.Lock()

    state: Dict[str, Any] = {
        "t0": time.perf_counter(),
        "last_print": time.perf_counter(),
        "best_feasible_e": float("inf"),
        "best_feasible_params": None,
        "best_value": float("inf"),
        "best_value_params": None,
    }

    def decode(params: dict) -> tuple[List[float], List[float], List[float]]:
        kp = [float(params.get(f"kp_{j}", 0.0)) for j in range(n)]
        kd = [float(params.get(f"kd_{j}", 0.0)) for j in range(n)]
        ki = [float(params.get(f"ki_{j}", 0.0)) for j in range(n)]
        return kp, ki, kd

    def encode(kp: Optional[List[float]], ki: Optional[List[float]], kd: Optional[List[float]]) -> Optional[dict]:
        if kp is None and ki is None and kd is None:
            return None
        out: dict = {}
        kp = list(kp or [])
        kd = list(kd or [])
        ki = list(ki or [])
        for j in range(n):
            if j < len(kp):
                lo = kp_range[0] * gain_profile[j]
                hi = kp_range[1] * gain_profile[j]
                out[f"kp_{j}"] = float(min(max(float(kp[j]), lo), hi))
            if j < len(kd):
                lo = kd_range[0] * gain_profile[j]
                hi = kd_range[1] * gain_profile[j]
                out[f"kd_{j}"] = float(min(max(float(kd[j]), lo), hi))
            if ki_range[1] <= 0.0:
                out[f"ki_{j}"] = 0.0
            elif j < len(ki):
                lo = ki_range[0] * gain_profile[j]
                hi = ki_range[1] * gain_profile[j]
                out[f"ki_{j}"] = float(min(max(float(ki[j]), lo), hi))
        return out or None

    def objective(trial) -> float:
        kp = [
            trial.suggest_float(f"kp_{j}", kp_range[0] * gain_profile[j], kp_range[1] * gain_profile[j], log=True)
            for j in range(n)
        ]
        kd = [
            trial.suggest_float(f"kd_{j}", kd_range[0] * gain_profile[j], kd_range[1] * gain_profile[j], log=True)
            for j in range(n)
        ]
        if ki_range[1] <= 0.0:
            ki = [0.0] * n
            for j in range(n):
                trial.suggest_float(f"ki_{j}", 0.0, 0.0)
        else:
            ki = [
                trial.suggest_float(
                    f"ki_{j}",
                    ki_range[0] * gain_profile[j],
                    ki_range[1] * gain_profile[j],
                    log=(ki_range[0] > 0.0),
                )
                for j in range(n)
            ]

        out = ctx.run(kp=kp, ki=ki, kd=kd, return_payload=False)
        m = out["metrics"]
        e_max = float(m.get("e_max", 0.0))
        jl = float(m.get("joint_limit_violation_max", 0.0))
        qd_u = float(m.get("qd_util_max", 0.0))
        # In ideal mode (computed-torque + no limits), do not prune on constraints.
        if bool(ctx.disable_limits):
            feas = True
        else:
            feas = (jl <= 0.0) and (qd_u <= 1.0 + 1.0e-9)

        trial.set_user_attr("e_max", e_max)
        trial.set_user_attr("jl", jl)
        trial.set_user_attr("qd_u", qd_u)
        trial.set_user_attr("feasible", bool(feas))

        if not feas:
            try:
                import optuna

                raise optuna.exceptions.TrialPruned()
            except Exception:
                return float(out["loss_total"]) + 1.0e6

        return float(out["loss_total"])

    def callback(study, trial) -> None:
        now = time.perf_counter()
        e_max = float(trial.user_attrs.get("e_max", float("nan")))
        jl = float(trial.user_attrs.get("jl", float("nan")))
        qd_u = float(trial.user_attrs.get("qd_u", float("nan")))
        feas = bool(trial.user_attrs.get("feasible", False))

        with lock:
            try:
                if trial.value is not None and float(trial.value) < float(state["best_value"]):
                    state["best_value"] = float(trial.value)
                    state["best_value_params"] = dict(trial.params)
            except Exception:
                pass

            if feas and e_max < float(state["best_feasible_e"]):
                state["best_feasible_e"] = e_max
                state["best_feasible_params"] = dict(trial.params)

            if (now - float(state["last_print"])) >= float(print_interval_s):
                t = now - float(state["t0"])
                best_fe = float(state["best_feasible_e"])
                best_params = state["best_feasible_params"] or {}
                best_kp, _, best_kd = decode(best_params)
                print(
                    "t=%.1fs  trial=%d  best_e_max=%.4f  last_e_max=%.4f  last(jl=%.4g,qd_u=%.3f)  best(kp=%s,kd=%s)"
                    % (t, len(study.trials), best_fe, e_max, jl, qd_u, _fmt_vec(best_kp), _fmt_vec(best_kd))
                )
                state["last_print"] = now

            if feas and e_max <= float(target_e_max):
                state["best_feasible_e"] = e_max
                state["best_feasible_params"] = dict(trial.params)
                study.stop()

    # Warm-start: use provided initial gains (typically from config or --kp/--kd/--ki).
    init_params = encode(init_kp, init_ki, init_kd) if bool(enqueue_init) else None
    if init_params:
        state["best_value_params"] = dict(init_params)
        state["best_feasible_params"] = dict(init_params)

    res = run_optuna(
        objective=objective,
        n_trials=int(max_trials),
        seed=int(seed),
        timeout_s=timeout_s,
        callback=callback,
        n_jobs=max(1, int(n_jobs)),
        storage=optuna_storage,
        study_name=study_name,
        enqueue_trials=([init_params] if init_params else None),
    )

    final_params = state["best_feasible_params"] or state["best_value_params"] or res.best_params
    kp, ki, kd = decode(final_params or {})
    best_out = ctx.run(kp=kp, ki=ki, kd=kd, return_payload=False)

    m = best_out["metrics"]
    e_max = float(m.get("e_max", 0.0))
    if _feasible(m) and e_max <= float(target_e_max):
        print("target reached: best_e_max=%.6f <= %.6f (feasible)" % (e_max, float(target_e_max)))
    else:
        print("stopped: optuna finished; best_e_max=%.6f (feasible=%s)" % (e_max, str(bool(_feasible(m)))))
    return best_out


def _make_waypoints_if_linear(mjcf_path: str, dq_csv: Optional[str]) -> Optional[List[List[float]]]:
    dq = _parse_csv_floats(dq_csv)
    if dq is None:
        return None
    import mujoco

    mjm = mujoco.MjModel.from_xml_path(mjcf_path)
    mjd = mujoco.MjData(mjm)
    mujoco.mj_forward(mjm, mjd)
    q0 = mjd.qpos.copy().tolist()
    dq = (dq + [0.0] * mjm.nv)[: mjm.nv]
    q1 = [a + b for a, b in zip(q0, dq)]
    return [q0, q1, q0]


def _configure_logging(quiet: bool) -> None:
    if not quiet:
        return
    try:
        import logging

        logging.getLogger("optuna").setLevel(logging.WARNING)
        logging.getLogger("optuna").propagate = False
    except Exception:
        pass


def _optimize_optuna_process(
    *,
    ctx: "RunContext",
    argv: List[str],
    target_e_max: float,
    max_trials: int,
    seed: int,
    n_jobs: int,
    print_interval_s: float,
    timeout_s: Optional[float],
    kp_range: Tuple[float, float],
    kd_range: Tuple[float, float],
    ki_range: Tuple[float, float],
    optuna_storage: str,
    study_name: str,
    init_kp: Optional[List[float]],
    init_kd: Optional[List[float]],
    init_ki: Optional[List[float]],
    quiet: bool,
) -> Dict[str, Any]:
    """Run Optuna trials in multiple OS processes.

    Implementation strategy (robust + minimal): spawn N worker processes that all
    run the same CLI with a shared RDB storage + study name.
    """

    try:
        import optuna
    except Exception as e:
        raise RuntimeError("Optuna is required for process-parallel optimization") from e

    # Create or load study so it exists before workers start.
    sampler = optuna.samplers.TPESampler(seed=int(seed))
    study = optuna.create_study(direction="minimize", sampler=sampler, storage=str(optuna_storage), study_name=str(study_name), load_if_exists=True)

    # Enqueue initial gains once (warm start).
    if init_kp is not None or init_kd is not None or init_ki is not None:
        # Encode into optuna params (respecting gain_profile scaling).
        gain_profile = [1.0, 1.0, 0.85, 0.65, 0.45, 0.35]
        n = len(gain_profile)
        kp = list(init_kp or [])
        kd = list(init_kd or [])
        ki = list(init_ki or [])
        p: Dict[str, Any] = {}
        for j in range(n):
            if j < len(kp):
                lo = kp_range[0] * gain_profile[j]
                hi = kp_range[1] * gain_profile[j]
                p[f"kp_{j}"] = float(min(max(float(kp[j]), lo), hi))
            if j < len(kd):
                lo = kd_range[0] * gain_profile[j]
                hi = kd_range[1] * gain_profile[j]
                p[f"kd_{j}"] = float(min(max(float(kd[j]), lo), hi))
            if ki_range[1] <= 0.0:
                p[f"ki_{j}"] = 0.0
            elif j < len(ki):
                lo = ki_range[0] * gain_profile[j]
                hi = ki_range[1] * gain_profile[j]
                p[f"ki_{j}"] = float(min(max(float(ki[j]), lo), hi))
        if p:
            study.enqueue_trial(p)

    # Split trials across workers.
    n_jobs = max(1, int(n_jobs))
    max_trials = max(1, int(max_trials))
    base = max_trials // n_jobs
    rem = max_trials % n_jobs
    trials_per_worker = [(base + (1 if i < rem else 0)) for i in range(n_jobs)]

    # Build base worker argv: rerun this script, but mark as worker and use the shared storage.
    # Remove any existing --jobs/--jobs-backend/--optuna-storage/--study-name/--max-trials to avoid conflicts.
    def _strip_args(a: List[str], names: List[str]) -> List[str]:
        out: List[str] = []
        skip_next = False
        for tok in a:
            if skip_next:
                skip_next = False
                continue
            if tok in names:
                skip_next = True
                continue
            if any(tok.startswith(n + "=") for n in names):
                continue
            out.append(tok)
        return out

    stripped = _strip_args(argv, ["--jobs", "--jobs-backend", "--optuna-storage", "--study-name", "--max-trials", "--print-interval"])
    repo_root = Path(__file__).resolve().parents[2]
    worker_entry = repo_root / "scripts" / "run_v0.py"
    worker_base = [sys.executable, str(worker_entry)] + stripped
    # Force optuna engine, shared storage/study, single-threaded per worker.
    worker_base += [
        "--engine",
        "optuna",
        "--optuna-storage",
        str(optuna_storage),
        "--study-name",
        str(study_name),
        "--jobs",
        "1",
        "--jobs-backend",
        "thread",
        "--optuna-worker",
        "--print-interval",
        "1e9",
    ]
    if quiet:
        worker_base.append("--quiet")

    procs: List[subprocess.Popen] = []
    for i, ntr in enumerate(trials_per_worker):
        if ntr <= 0:
            continue
        cmd = list(worker_base) + ["--max-trials", str(int(ntr)), "--target-e-max", str(float(target_e_max))]
        if timeout_s is not None:
            cmd += ["--optuna-timeout", str(float(timeout_s))]
        # Stagger seeds to reduce correlation.
        cmd += ["--seed", str(int(seed) + i + 1)]
        procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL if quiet else None, stderr=subprocess.DEVNULL if quiet else None))

    # Monitor progress from the parent process (clean output).
    t0 = time.perf_counter()
    last_print = 0.0
    while any(p.poll() is None for p in procs):
        now = time.perf_counter()
        if (now - last_print) >= float(print_interval_s):
            last_print = now
            try:
                study = optuna.load_study(study_name=str(study_name), storage=str(optuna_storage))
                trials = list(study.trials)
                n_done = len(trials)
                # best feasible e_max among completed trials
                best_e = float("inf")
                last_e = float("nan")
                last_jl = float("nan")
                last_qd_u = float("nan")
                for tr in trials:
                    try:
                        if tr.user_attrs.get("feasible") and float(tr.user_attrs.get("e_max", float("inf"))) < best_e:
                            best_e = float(tr.user_attrs.get("e_max"))
                    except Exception:
                        pass
                # Find the most recent trial that has recorded user attrs.
                for tr in reversed(trials):
                    if "e_max" in (tr.user_attrs or {}):
                        last_e = float(tr.user_attrs.get("e_max", float("nan")))
                        last_jl = float(tr.user_attrs.get("jl", float("nan")))
                        last_qd_u = float(tr.user_attrs.get("qd_u", float("nan")))
                        break
                print(
                    "t=%.1fs  trial=%d  best_e_max=%s  last_e_max=%s  last(jl=%s,qd_u=%s)"
                    % (
                        now - t0,
                        n_done,
                        ("inf" if best_e == float("inf") else f"{best_e:.4f}"),
                        ("nan" if last_e != last_e else f"{last_e:.4f}"),
                        ("nan" if last_jl != last_jl else f"{last_jl:.4g}"),
                        ("nan" if last_qd_u != last_qd_u else f"{last_qd_u:.3f}"),
                    )
                )
            except Exception:
                pass
        time.sleep(0.05)

    # Ensure all workers exited.
    for p in procs:
        p.wait()

    # Evaluate best params in this process to return a normal result payload.
    study = optuna.load_study(study_name=str(study_name), storage=str(optuna_storage))
    best = study.best_trial
    n = 6
    kp = [float(best.params.get(f"kp_{j}", 0.0)) for j in range(n)]
    kd = [float(best.params.get(f"kd_{j}", 0.0)) for j in range(n)]
    ki = [float(best.params.get(f"ki_{j}", 0.0)) for j in range(n)]

    best_out = ctx.run(kp=kp, ki=ki, kd=kd, return_payload=False)
    return best_out
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        optuna.logging.disable_default_handler()
        optuna.logging.enable_propagation(False)
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else []

    # Track whether user explicitly passed gain vectors on the CLI.
    # Config defaults should not block --load-result from taking effect.
    def _flag_present(name: str) -> bool:
        if name in argv:
            return True
        prefix = name + "="
        return any(str(a).startswith(prefix) for a in argv)

    kp_explicit = _flag_present("--kp")
    kd_explicit = _flag_present("--kd")
    ki_explicit = _flag_present("--ki")
    ff_mode_explicit = _flag_present("--ff-mode")
    dt_explicit = _flag_present("--dt")
    traj_explicit = _flag_present("--traj")
    integrator_explicit = _flag_present("--integrator")
    sine_freq_explicit = _flag_present("--sine-freq")
    sine_amp_explicit = _flag_present("--sine-amp-scale")
    sine_phase_explicit = _flag_present("--sine-phase")
    sine_ramp_explicit = _flag_present("--sine-ramp-time")
    sine_cycles_explicit = _flag_present("--sine-cycles")
    vel_limits_explicit = _flag_present("--vel-limits")
    torque_limit_explicit = _flag_present("--torque-limit")

    cfg = _load_config(argv)

    ap = argparse.ArgumentParser(description="PerfOpt v0 single-run entrypoint (CPU/MuJoCo).")
    ap.add_argument("--config", default=None, help="Path to a JSON config file with default parameters.")
    ap.add_argument("--mjcf", default=None, help="Path to MJCF model (e.g. models/er15-1400.mjcf.xml)")
    ap.add_argument("--dt", type=float, default=0.002, help="Simulation timestep (s)")
    ap.add_argument("--steps", type=int, default=400, help="Simulation steps")
    ap.add_argument(
        "--integrator",
        default="euler",
        choices=["euler", "rk4"],
        help="MuJoCo integrator (Euler is default; RK4 improves accuracy at higher compute cost).",
    )
    ap.add_argument("--freq-band", default="0,80", help="FFT band for vib_energy proxy, e.g. '0,80'")

    ap.add_argument("--traj", default="sine_pos", choices=["sine_pos", "cosine_pos", "sine_vel", "linear"])
    ap.add_argument("--sine-freq", type=float, default=0.5)
    ap.add_argument("--sine-phase", type=float, default=0.0)
    ap.add_argument("--sine-amp-scale", type=float, default=0.2)
    ap.add_argument("--sine-ramp-time", type=float, default=0.2)
    ap.add_argument("--sine-cycles", type=int, default=2, help="Number of integer sine cycles to simulate (sine_* only).")

    ap.add_argument("--dq", default=None, help="Joint delta for linear trajectory, comma-separated.")
    ap.add_argument("--vel-limits", default=None, help="Joint speed limits (also used as speed constraint), csv.")

    ap.add_argument("--kp", default=None, help="KP per joint, comma-separated")
    ap.add_argument("--ki", default=None, help="KI per joint, comma-separated")
    ap.add_argument("--kd", default=None, help="KD per joint, comma-separated")
    ap.add_argument("--torque-limit", default=None, help="Torque limit per joint, comma-separated (N*m)")
    ap.add_argument(
        "--ff-mode",
        default="ref",
        choices=["no", "ref", "meas", "ideal"],
        help=(
            "Control/feedforward mode: "
            "no=pure PID (no inverse-dynamics FF), "
            "ref=ID(q_ref,qd_ref,qdd_ref)+PID, "
            "meas=ID(q_meas,qd_meas,qdd_ref)+PID, "
            "ideal=ideal computed-torque upper bound (ID(q_meas,qd_meas,qdd_cmd), limits disabled)."
        ),
    )
    ap.add_argument("--dof-damping", type=float, default=None, help="Override MuJoCo dof_damping (scalar).")
    ap.add_argument("--dof-armature", type=float, default=None, help="Override MuJoCo dof_armature (scalar).")
    # Back-compat flags (deprecated): prefer --ff-mode.
    ap.add_argument("--no-ff", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--ideal", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--debug-ct",
        action="store_true",
        help="Dump computed-torque diagnostics: ||tau_applied - qfrc_inverse(state)|| and joint error time series.",
    )
    ap.add_argument(
        "--debug-out",
        default="artifacts/debug_ct.json",
        help="Where to write debug_ct json (only when --debug-ct is set).",
    )
    ap.add_argument(
        "--debug-plot",
        default="artifacts/debug_ct_error.png",
        help="Where to write debug_ct time-error plot png (only when --debug-ct is set).",
    )

    ap.add_argument("--preset", default=None, choices=["quickmove", "truemove", "stablemove"])
    ap.add_argument("--weights", default=None, help="Loss weights as 'wq,wt,ws' (used when preset not set).")
    ap.add_argument("--use-baseline", action="store_true")

    ap.add_argument("--optimize", action="store_true")
    ap.add_argument("--engine", default="random", choices=["random", "optuna"])
    ap.add_argument("--optuna-timeout", type=float, default=None)
    ap.add_argument(
        "--optuna-storage",
        default=None,
        help="Optuna storage URL, e.g. sqlite:///artifacts/optuna.db (enables dashboard).",
    )
    ap.add_argument(
        "--study-name",
        default=None,
        help="Optuna study name (used only when --optuna-storage is set).",
    )

    # Internal: used by process-parallel driver to avoid recursive spawning.
    ap.add_argument("--optuna-worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--target-e-max", type=float, default=0.1)
    ap.add_argument("--max-trials", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument(
        "--jobs-backend",
        default="process",
        choices=["process", "thread"],
        help="Parallelization backend for Optuna: process (default) or thread.",
    )
    ap.add_argument("--print-interval", type=float, default=1.0)
    ap.add_argument("--kp-range", default="50,1000")
    ap.add_argument("--kd-range", default="1,80")
    ap.add_argument("--ki-range", default="0,0")

    ap.add_argument("--plot-tcp-error", default=None)
    ap.add_argument(
        "--plot-torque",
        default=None,
        help="Write a joint torque plot png for this run (requires payload).",
    )
    ap.add_argument("--out", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--viewer",
        action="store_true",
        help="Open MuJoCo viewer (only for non-optimize runs or for a post-optimization replay).",
    )
    ap.add_argument(
        "--load-result",
        default=None,
        help="Load a previous result json (e.g. artifacts/opt_result.json) and use its controller gains.",
    )
    ap.add_argument(
        "--compare-ff",
        action="store_true",
        help="Compare ff-mode variants (no/ref/meas/ideal) under the same conditions.",
    )
    ap.add_argument(
        "--compare-ff-json",
        default="artifacts/compare_ff_modes.json",
        help="Where to write comparison json (only when --compare-ff is set).",
    )
    ap.add_argument(
        "--compare-ff-plot",
        default="artifacts/compare_ff_modes.png",
        help="Where to write TCP error comparison plot png (only when --compare-ff is set).",
    )
    ap.add_argument(
        "--compare-ff-torque-plot",
        default="artifacts/compare_ff_torque.png",
        help="Where to write joint torque comparison plot png (only when --compare-ff is set).",
    )

    _apply_config_defaults(ap, cfg)

    # Optional TAB completion (bash/zsh) via argcomplete.
    # Users can register completion just for this script:
    #   eval "$(register-python-argcomplete scripts/run_v0.py)"
    try:
        import argcomplete  # type: ignore
    except Exception:
        argcomplete = None  # type: ignore
    if argcomplete is not None:
        argcomplete.autocomplete(ap)  # type: ignore[attr-defined]

    args = ap.parse_args(argv)

    # Back-compat mapping: if user uses deprecated flags, map to --ff-mode.
    # Precedence: explicit --ff-mode > deprecated flags.
    if (bool(args.no_ff) or bool(args.ideal)) and not ff_mode_explicit:
        if bool(args.ideal):
            args.ff_mode = "ideal"
        elif bool(args.no_ff):
            args.ff_mode = "no"
    elif (bool(args.no_ff) or bool(args.ideal)) and ff_mode_explicit:
        raise SystemExit("error: do not mix --ff-mode with deprecated --no-ff/--ideal")

    if not args.mjcf:
        raise SystemExit("error: --mjcf is required (or provide it via --config)")

    def _apply_ff_mode_to_ctx(ctx: RunContext, mode: str) -> None:
        mode = str(mode).strip().lower()
        if mode == "ideal":
            ctx.use_ff = True
            ctx.computed_torque = True
            ctx.disable_limits = True
            ctx.ff_mode = "ref"
        elif mode == "no":
            ctx.use_ff = False
            ctx.computed_torque = False
            ctx.disable_limits = False
            ctx.ff_mode = "ref"
        elif mode == "meas":
            ctx.use_ff = True
            ctx.computed_torque = False
            ctx.disable_limits = False
            ctx.ff_mode = "meas"
        else:
            ctx.use_ff = True
            ctx.computed_torque = False
            ctx.disable_limits = False
            ctx.ff_mode = "ref"

    def _mode_from_loaded_cfg(cfg: dict) -> Optional[str]:
        if not isinstance(cfg, dict):
            return None
        m = cfg.get("ff_mode")
        if isinstance(m, str) and m.strip():
            return m.strip().lower()
        # Back-compat: derive from booleans if present.
        use_ff = bool(cfg.get("use_mujoco_inverse_dynamics_ff", True))
        if not use_ff:
            return "no"
        # If config doesn't have computed_torque flags, assume ref.
        return "ref"

    def _warn_if_mismatch(name: str, a, b) -> None:
        # Simple mismatch warning helper.
        if a is None or b is None:
            return
        if isinstance(a, float) or isinstance(b, float):
            try:
                if abs(float(a) - float(b)) <= 1e-12:
                    return
            except Exception:
                pass
        if a == b:
            return
        print(f"warning: --load-result config mismatch for {name}: loaded={a} current={b} (may not reproduce)")

    _configure_logging(bool(args.quiet))

    from perfopt.configs import load_default_scenarios

    mjcf_path = str(Path(args.mjcf))
    freq_band = _parse_freq_band(str(args.freq_band))

    # We only construct waypoints for linear.
    waypoints = None
    if str(args.traj) == "linear":
        waypoints = _make_waypoints_if_linear(mjcf_path, args.dq)

    weights = None
    if args.preset is not None:
        sc = load_default_scenarios()[str(args.preset)]
        weights = {"wq": sc.weights.wq, "wt": sc.weights.wt, "ws": sc.weights.ws}
    elif args.weights is not None:
        w = _parse_csv_floats(args.weights)
        if not w or len(w) != 3:
            raise ValueError("--weights must be like '0.2,0.6,0.2'")
        weights = {"wq": float(w[0]), "wt": float(w[1]), "ws": float(w[2])}

    vel_limits = _parse_csv_floats(args.vel_limits)
    if vel_limits is None and str(args.traj) != "linear":
        # For sine trajectories, vel_limits is used both for clipping and for constraints.
        vel_limits = [2.0] * 6

    # For sine references, run an integer number of cycles so metrics are stable.
    steps = int(args.steps)
    if str(args.traj) in ("sine_pos", "cosine_pos", "sine_vel"):
        f = float(args.sine_freq)
        cycles = int(args.sine_cycles)
        if f > 0.0 and cycles > 0:
            period = 1.0 / f
            duration = float(cycles) * period
            steps = max(1, int(round(duration / float(args.dt))))

    ctx = RunContext(
        mjcf_path=mjcf_path,
        dt=float(args.dt),
        steps=steps,
        integrator=str(args.integrator),
        freq_band=freq_band,
        traj=str(args.traj),
        waypoints=waypoints,
        vel_limits=vel_limits,
        sine_freq_hz=float(args.sine_freq),
        sine_phase=float(args.sine_phase),
        sine_amp_scale=float(args.sine_amp_scale),
        sine_ramp_time=float(args.sine_ramp_time),
        torque_limit=_parse_csv_floats(args.torque_limit),
        weights=weights,
        baseline_metrics=None,
        dof_damping=args.dof_damping,
        dof_armature=args.dof_armature,
        use_ff=(str(args.ff_mode) != "no"),
        computed_torque=(str(args.ff_mode) == "ideal"),
        disable_limits=(str(args.ff_mode) == "ideal"),
        ff_mode=("ref" if str(args.ff_mode) in ("no", "ideal") else str(args.ff_mode)),
    )

    # Load previous best gains for replay / demo and (optionally) default ff-mode.
    loaded_gains = None
    loaded_cfg = None
    if args.load_result:
        try:
            loaded = _maybe_load_result(str(args.load_result))
            loaded_cfg = (loaded.get("config") or {})
            ctrl = (loaded_cfg.get("controller") or {})
            loaded_gains = {"kp": ctrl.get("kp"), "ki": ctrl.get("ki"), "kd": ctrl.get("kd")}
        except Exception as e:
            raise SystemExit(f"error: failed to load --load-result: {e}")

    baseline_metrics = None
    if bool(args.use_baseline):
        base = ctx.run(kp=_parse_csv_floats(args.kp), ki=_parse_csv_floats(args.ki), kd=_parse_csv_floats(args.kd))
        baseline_metrics = dict(base["metrics"])
    ctx.baseline_metrics = baseline_metrics

    before = None
    if (bool(args.plot_tcp_error) or bool(args.plot_torque)) and bool(args.optimize):
        before = ctx.run(kp=_parse_csv_floats(args.kp), ki=_parse_csv_floats(args.ki), kd=_parse_csv_floats(args.kd), return_payload=True)

    elif bool(args.viewer) and not bool(args.optimize):
        # Convenience: if user wants a viewer demo and didn't specify gains, try last saved result.
        default_path = Path("artifacts/opt_result.json")
        if default_path.exists() and args.kp is None and args.kd is None and args.ki is None:
            try:
                loaded = _maybe_load_result(str(default_path))
                loaded_cfg = (loaded.get("config") or {})
                ctrl = (loaded_cfg.get("controller") or {})
                loaded_gains = {"kp": ctrl.get("kp"), "ki": ctrl.get("ki"), "kd": ctrl.get("kd")}
                print(f"viewer: loaded last result: {default_path}")
            except Exception:
                loaded_gains = None

    # If we loaded a result, optionally adopt its ff-mode and warn on config mismatches.
    if loaded_cfg is not None:
        loaded_mode = _mode_from_loaded_cfg(loaded_cfg)
        current_mode = str(args.ff_mode).strip().lower()
        if loaded_mode:
            if ff_mode_explicit and loaded_mode != current_mode:
                _warn_if_mismatch("ff_mode", loaded_mode, current_mode)
            elif not ff_mode_explicit:
                # Auto adopt loaded mode for reproducibility.
                args.ff_mode = loaded_mode
                _apply_ff_mode_to_ctx(ctx, loaded_mode)

        # Warn on other mismatches (do not auto-change).
        _warn_if_mismatch("mjcf", loaded_cfg.get("mjcf_path"), mjcf_path)
        _warn_if_mismatch("dt", loaded_cfg.get("dt"), float(args.dt))
        _warn_if_mismatch("integrator", loaded_cfg.get("integrator"), str(args.integrator))
        _warn_if_mismatch("traj", loaded_cfg.get("traj"), str(args.traj))
        _warn_if_mismatch("sine_freq_hz", loaded_cfg.get("sine_freq_hz"), float(args.sine_freq))
        _warn_if_mismatch("sine_amp_scale", loaded_cfg.get("sine_amp_scale"), float(args.sine_amp_scale))
        _warn_if_mismatch("sine_phase", loaded_cfg.get("sine_phase"), float(args.sine_phase))
        _warn_if_mismatch("sine_ramp_time", loaded_cfg.get("sine_ramp_time"), float(args.sine_ramp_time))
        _warn_if_mismatch("steps", loaded_cfg.get("steps"), int(ctx.steps))
        _warn_if_mismatch("vel_limits", loaded_cfg.get("vel_limits"), vel_limits)
        if isinstance(loaded_cfg.get("controller"), dict):
            _warn_if_mismatch("torque_limit", (loaded_cfg.get("controller") or {}).get("torque_limit"), _parse_csv_floats(args.torque_limit))

    if bool(args.optimize):
        kp_range = _parse_pair(str(args.kp_range), name="--kp-range")
        kd_range = _parse_pair(str(args.kd_range), name="--kd-range")
        ki_range = _parse_pair(str(args.ki_range), name="--ki-range")

        if str(args.engine) == "optuna":
            jobs_backend = str(args.jobs_backend).strip().lower()
            if jobs_backend == "process" and int(args.jobs) > 1 and not bool(args.optuna_worker):
                storage = args.optuna_storage
                study_name = args.study_name
                if storage is None:
                    storage = "sqlite:///artifacts/optuna.db"
                    if not bool(args.quiet):
                        print(f"info: --jobs-backend process requires optuna storage; using {storage}")
                if study_name is None:
                    # Avoid mixing trials across unrelated runs when we auto-pick a storage.
                    study_name = f"run_v0_{int(time.time())}"
                    if not bool(args.quiet):
                        print(f"info: --jobs-backend process using study-name {study_name}")
                out = _optimize_optuna_process(
                    ctx=ctx,
                    argv=list(argv),
                    target_e_max=float(args.target_e_max),
                    max_trials=int(args.max_trials),
                    seed=int(args.seed),
                    n_jobs=int(args.jobs),
                    print_interval_s=float(args.print_interval),
                    timeout_s=args.optuna_timeout,
                    kp_range=kp_range,
                    kd_range=kd_range,
                    ki_range=ki_range,
                    optuna_storage=str(storage),
                    study_name=str(study_name),
                    init_kp=_parse_csv_floats(args.kp),
                    init_kd=_parse_csv_floats(args.kd),
                    init_ki=_parse_csv_floats(args.ki),
                    quiet=bool(args.quiet),
                )
            else:
                # Thread backend (or worker process): use Optuna's in-process parallelism.
                out = _optimize_optuna(
                    ctx=ctx,
                    target_e_max=float(args.target_e_max),
                    max_trials=int(args.max_trials),
                    seed=int(args.seed),
                    n_jobs=int(args.jobs) if jobs_backend == "thread" else 1,
                    print_interval_s=float(args.print_interval),
                    timeout_s=args.optuna_timeout,
                    kp_range=kp_range,
                    kd_range=kd_range,
                    ki_range=ki_range,
                    optuna_storage=args.optuna_storage,
                    study_name=args.study_name,
                    init_kp=_parse_csv_floats(args.kp),
                    init_kd=_parse_csv_floats(args.kd),
                    init_ki=_parse_csv_floats(args.ki),
                    enqueue_init=not bool(args.optuna_worker),
                )
        else:
            out = _optimize_random(
                ctx=ctx,
                target_e_max=float(args.target_e_max),
                max_trials=int(args.max_trials),
                seed=int(args.seed),
                print_interval_s=float(args.print_interval),
                kp_range=kp_range,
                kd_range=kd_range,
                ki_range=ki_range,
            )
        if bool(args.viewer):
            ctrl = out.get("config", {}).get("controller", {})
            print("viewer: replay best parameters ...")
            ctx.run(
                kp=ctrl.get("kp"),
                ki=ctrl.get("ki"),
                kd=ctrl.get("kd"),
                viewer=True,
                viewer_loop=True,
                return_payload=False,
            )
    else:
        kp_in = _parse_csv_floats(args.kp)
        ki_in = _parse_csv_floats(args.ki)
        kd_in = _parse_csv_floats(args.kd)
        if loaded_gains is not None:
            # Precedence: explicit CLI flags > --load-result > config defaults.
            if not kp_explicit:
                kp_in = loaded_gains.get("kp")
            if not ki_explicit:
                ki_in = loaded_gains.get("ki")
            if not kd_explicit:
                kd_in = loaded_gains.get("kd")

        out = ctx.run(
            kp=kp_in,
            ki=ki_in,
            kd=kd_in,
            viewer=bool(args.viewer),
            viewer_loop=bool(args.viewer),
            return_payload=bool(args.plot_tcp_error) or bool(args.plot_torque),
        )

    if bool(args.compare_ff):
        # Need gains to compare.
        ctrl = out.get("config", {}).get("controller", {}) or {}
        kp0, ki0, kd0 = ctrl.get("kp"), ctrl.get("ki"), ctrl.get("kd")
        if kp0 is None or kd0 is None:
            raise SystemExit("error: --compare-ff requires controller gains; pass --load-result or run --optimize first.")

        from perfopt import run_v0 as _run_v0

        base_kwargs = dict(
            mjcf_path=mjcf_path,
            dt=float(args.dt),
            steps=int(ctx.steps),
            integrator=str(args.integrator),
            traj=str(args.traj),
            waypoints=waypoints,
            vel_limits=vel_limits,
            sine_freq_hz=float(args.sine_freq),
            sine_phase=float(args.sine_phase),
            sine_amp_scale=float(args.sine_amp_scale),
            sine_ramp_time=float(args.sine_ramp_time),
            torque_limit=_parse_csv_floats(args.torque_limit),
            weights=weights,
            baseline_metrics=baseline_metrics,
            freq_band=freq_band,
            dof_damping=args.dof_damping,
            dof_armature=args.dof_armature,
            kp=kp0,
            ki=ki0,
            kd=kd0,
            return_payload=True,
        )

        runs = {
            # no: pure PID (no inverse-dynamics FF)
            "no": _run_v0(
                **base_kwargs,
                use_mujoco_inverse_dynamics_ff=False,
                ff_mode="ref",
                computed_torque=False,
                disable_limits=False,
                debug_ct=False,
            ),
            # ref: ID(q_ref, qd_ref, qdd_ref) + PID
            "ref": _run_v0(
                **base_kwargs,
                use_mujoco_inverse_dynamics_ff=True,
                ff_mode="ref",
                computed_torque=False,
                disable_limits=False,
                debug_ct=False,
            ),
            # meas: ID(q_meas, qd_meas, qdd_ref) + PID
            "meas": _run_v0(
                **base_kwargs,
                use_mujoco_inverse_dynamics_ff=True,
                ff_mode="meas",
                computed_torque=False,
                disable_limits=False,
                debug_ct=False,
            ),
            # ideal: computed-torque upper bound (limits disabled)
            "ideal": _run_v0(
                **base_kwargs,
                use_mujoco_inverse_dynamics_ff=True,
                ff_mode="ref",
                computed_torque=True,
                disable_limits=True,
                debug_ct=False,
            ),
        }

        def _tau_stats(run: dict) -> dict:
            payload = run.get("payload") or {}
            tau = payload.get("torque") or []
            if not tau or not isinstance(tau[0], list):
                return {"per_joint": []}
            n = len(tau[0])
            per = []
            for j in range(n):
                vals = [abs(float(x[j])) for x in tau if isinstance(x, list) and j < len(x)]
                if not vals:
                    per.append({"joint": j, "tau_abs_mean": 0.0, "tau_abs_max": 0.0})
                    continue
                per.append({"joint": j, "tau_abs_mean": float(sum(vals) / len(vals)), "tau_abs_max": float(max(vals))})
            return {"per_joint": per}

        # Write json summary.
        out_json = {
            "conditions": {
                "dt": float(args.dt),
                "integrator": str(args.integrator),
                "traj": str(args.traj),
                "sine_freq": float(args.sine_freq),
                "sine_cycles": int(args.sine_cycles),
                "steps": int(ctx.steps),
            },
            "metrics": {k: v.get("metrics", {}) for k, v in runs.items()},
            "torque_stats": {k: _tau_stats(v) for k, v in runs.items()},
        }
        p = Path(str(args.compare_ff_json))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote: {p}")

        # Plot TCP error curves.
        try:
            _plot_tcp_error_multi(runs=runs, out_path=str(args.compare_ff_plot))
        except Exception as e:
            print(f"warning: failed to plot compare_ff: {e}")

        # Plot joint torque curves.
        try:
            _plot_torque_multi(runs=runs, out_path=str(args.compare_ff_torque_plot))
        except Exception as e:
            print(f"warning: failed to plot compare_ff torque: {e}")

        # Print a short table.
        for name, r in runs.items():
            m = r.get("metrics", {})
            print(
                "compare_ff: %-8s e_max=%.6f(m) rmse=%.6f(m) energy=%.3f cycle=%.3f(s)"
                % (
                    name,
                    float(m.get("e_max", 0.0)),
                    float(m.get("rmse", 0.0)),
                    float(m.get("energy", 0.0)),
                    float(m.get("cycle_time", 0.0)),
                )
            )

    if args.plot_tcp_error:
        if before is None:
            before = ctx.run(kp=None, ki=None, kd=None, return_payload=True)
        ctrl = out.get("config", {}).get("controller", {})
        after = ctx.run(kp=ctrl.get("kp"), ki=ctrl.get("ki"), kd=ctrl.get("kd"), return_payload=True)
        _plot_tcp_error(before=before, after=after, out_path=str(args.plot_tcp_error))

    if args.plot_torque:
        if before is None and bool(args.optimize):
            before = ctx.run(kp=None, ki=None, kd=None, return_payload=True)
        # Ensure the run has payload.
        if not (out.get("payload") or {}).get("torque"):
            ctrl = out.get("config", {}).get("controller", {})
            out = ctx.run(kp=ctrl.get("kp"), ki=ctrl.get("ki"), kd=ctrl.get("kd"), return_payload=True)
        _plot_torque_single(run=out, out_path=str(args.plot_torque))

    m = out["metrics"]
    print(
        "elapsed_s=%.4f  loss=%.6f  e_max=%.6f(m)  rmse=%.6f(m)  cycle=%.4f(s)"
        % (out["elapsed_s"], out["loss_total"], m.get("e_max", 0.0), m.get("rmse", 0.0), m.get("cycle_time", 0.0))
    )

    if args.out:
        p = Path(str(args.out))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote: {p}")
    elif bool(args.optimize):
        # Always keep a "last run" result for quick viewer replay.
        p = Path("artifacts/opt_result.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote: {p}")

    if bool(args.debug_ct):
        # Run a fresh rollout (no viewer loop) with debug traces, then write + summarize.
        ctrl = out.get("config", {}).get("controller", {}) or {}
        dbg = ctx.run(
            kp=ctrl.get("kp"),
            ki=ctrl.get("ki"),
            kd=ctrl.get("kd"),
            viewer=False,
            viewer_loop=False,
            debug_ct=True,
            return_payload=True,
        )
        summ = _summarize_debug_ct(dbg)
        dbg_out = {
            "summary": summ,
            "run": dbg,
        }
        p = Path(str(args.debug_out))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dbg_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote: {p}")
        try:
            _plot_error_time_series(dbg_out=dbg_out, out_path=str(args.debug_plot))
            print(f"wrote: {Path(str(args.debug_plot))}")
        except Exception as e:
            print(f"warning: failed to plot debug_ct errors: {e}")
        if summ.get("tau_res_l2_max") is not None:
            print(
                "debug_ct: max ||tau_applied - qfrc_inverse(state)||_2 = %.6f at t=%.3fs"
                % (float(summ["tau_res_l2_max"]), float(summ.get("tau_res_l2_t_at_max_s") or 0.0))
            )
        pj = summ.get("per_joint") or []
        if pj:
            worst = max(pj, key=lambda d: float(d.get("q_err_abs_max", 0.0)))
            print(
                "debug_ct: worst joint q_err_abs_max = %.6f(rad) at joint=%d t=%.3fs"
                % (float(worst["q_err_abs_max"]), int(worst["joint"]), float(worst.get("t_at_max_s") or 0.0))
            )
            mean_abs = float(worst.get("q_err_abs_mean", 0.0))
            print("debug_ct: that joint q_err_abs_mean = %.6f(rad)" % mean_abs)
        trj = summ.get("tau_res_per_joint") or []
        if trj:
            worst = max(trj, key=lambda d: float(d.get("tau_res_abs_max", 0.0)))
            print(
                "debug_ct: worst joint |tau_applied - tau_id(state)| = %.6f(Nm) at joint=%d t=%.3fs"
                % (float(worst["tau_res_abs_max"]), int(worst["joint"]), float(worst.get("t_at_max_s") or 0.0))
            )
        tcp_stats = (summ.get("tcp") or {})
        if tcp_stats:
            print(
                "debug_ct: TCP err mean=%.6f(m) max=%.6f(m) t_at_max=%.3fs"
                % (
                    float(tcp_stats.get("tcp_err_mean_m", 0.0)),
                    float(tcp_stats.get("tcp_err_max_m", 0.0)),
                    float(tcp_stats.get("tcp_err_t_at_max_s") or 0.0),
                )
            )
        qdj = summ.get("qdd_err_per_joint") or []
        if qdj:
            worst = max(qdj, key=lambda d: float(d.get("qdd_err_abs_max", 0.0)))
            print(
                "debug_ct: worst joint |qdd_cmd - qacc| = %.6f(rad/s^2) at joint=%d t=%.3fs"
                % (float(worst["qdd_err_abs_max"]), int(worst["joint"]), float(worst.get("t_at_max_s") or 0.0))
            )

    return 0
